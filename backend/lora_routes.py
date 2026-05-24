"""HTTP routes for the LoRA management page (sgs-ui-eqc.1).

GET    /api/loras                  list LoRAs (volume + metadata, reconciled)
POST   /api/loras/sync             explicit refresh: re-runs `comfy-gen list loras`
POST   /api/loras/download         download from CivitAI version_id or URL/HF
POST   /api/loras/delete           batch delete with per-file results
POST   /api/loras/set-source       backfill source metadata for an existing LoRA

Returns 409 when no ComfyGen endpoint is configured (matches preset_routes).
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from typing import Any
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend import civitai_client, config, lora_metadata, settings_store

router = APIRouter()

LORA_DEST_DIR = "/runpod-volume/ComfyUI/models/loras"
_SUBPROCESS_TIMEOUT_SEC = 120  # `comfy-gen list loras` can cold-start ~50s
CACHE_STALE_AFTER_SEC = 24 * 3600  # 24h — matches the ComfyGen block cache TTL
_cache_lock = threading.Lock()

# One batch download at a time. Concurrent submits get a 409.
_download_lock = threading.Lock()
_download_in_flight = False


# ---- Pydantic ----

class DownloadRequest(BaseModel):
    source: str = Field(description="'civitai' | 'url'")
    version_id: int | None = None
    url: str | None = None
    filename: str | None = None
    base_model: str | None = None


class DeleteRequest(BaseModel):
    filenames: list[str]


class SetSourceRequest(BaseModel):
    filename: str
    source: str
    source_id: str | None = None
    url: str | None = None


# ---- Helpers (monkeypatched in tests) ----

def _endpoint_id_or_409() -> str:
    ep = settings_store.get_endpoint("comfygen")
    if ep is None or not ep.get("endpoint_id"):
        raise HTTPException(
            status_code=409,
            detail="no ComfyGen endpoint configured — set one up via Settings → Endpoints first",
        )
    return str(ep["endpoint_id"])


def _read_cached_loras() -> tuple[list[str], float | None]:
    """Read the shared comfy_gen info cache file. Returns (filenames, fetched_at).

    Same file the ComfyGen block reads/writes — avoids divergent caches.
    Missing file or unparseable returns ([], None).
    """
    path = config.COMFY_GEN_INFO_CACHE_PATH
    if not path.exists():
        return ([], None)
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return ([], None)
    loras = data.get("loras") or []
    fetched_at = data.get("fetched_at")
    names = [s for s in loras if isinstance(s, str)]
    return (names, float(fetched_at) if fetched_at else None)


def _write_cached_loras(filenames: list[str], fetched_at: float | None = None) -> None:
    """Update the shared cache file's `loras` field, preserving other keys.

    Called after a successful download/delete so the next GET shows fresh
    state without paying the cold-pod cost of a real `comfy-gen list loras`.
    """
    path = config.COMFY_GEN_INFO_CACHE_PATH
    with _cache_lock:
        data: dict[str, Any] = {}
        if path.exists():
            try:
                data = json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                data = {}
        data["loras"] = sorted(set(filenames))
        if fetched_at is not None:
            data["fetched_at"] = fetched_at
        data.setdefault("samplers", [])
        data.setdefault("schedulers", [])
        data.setdefault("fetched_at", time.time())
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False))


def _fetch_loras_from_comfygen(endpoint_id: str) -> list[str]:
    """Invoke `comfy-gen list loras` and return filenames.

    Cold-path: takes 50-90s on a cold CPU pod. Only called from explicit
    /sync, never from GET. Updates the shared cache file as a side effect.
    """
    if not shutil.which("comfy-gen"):
        raise HTTPException(status_code=500, detail="comfy-gen CLI not found on PATH")
    proc = subprocess.run(
        ["comfy-gen", "list", "loras", "--endpoint-id", endpoint_id, "--json"],
        capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"comfy-gen list loras failed: {(proc.stderr or proc.stdout).strip()[:500]}",
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"comfy-gen returned invalid JSON: {exc}") from exc
    items = data.get("loras") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[str] = []
    for item in items:
        if isinstance(item, str):
            out.append(item)
        elif isinstance(item, dict) and item.get("filename"):
            out.append(str(item["filename"]))
    _write_cached_loras(out, fetched_at=time.time())
    return out


def _delete_subprocess(filenames: list[str], endpoint_id: str) -> list[dict[str, Any]]:
    """Invoke `comfy-gen delete --batch` and return per-file results.

    Returns a list of {path, deleted, error?} dicts.
    """
    paths = [f"{LORA_DEST_DIR}/{f}" for f in filenames]
    payload = json.dumps(paths)
    proc = subprocess.run(
        ["comfy-gen", "delete", "--batch", "-", "--endpoint-id", endpoint_id, "--json"],
        input=payload, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SEC,
    )
    if proc.returncode != 0 and not proc.stdout.strip():
        raise HTTPException(
            status_code=502,
            detail=f"comfy-gen delete failed: {(proc.stderr or '').strip()[:500]}",
        )
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"comfy-gen returned invalid JSON: {exc}") from exc
    results = data.get("results") if isinstance(data, dict) else data
    return results if isinstance(results, list) else []


def _download_subprocess(entries: list[dict[str, Any]], endpoint_id: str) -> dict[str, Any]:
    """Invoke `comfy-gen download --batch` and return parsed result."""
    payload = json.dumps(entries)
    proc = subprocess.run(
        ["comfy-gen", "download", "--batch", "-", "--endpoint-id", endpoint_id, "--json"],
        input=payload, capture_output=True, text=True, timeout=_SUBPROCESS_TIMEOUT_SEC * 8,
    )
    if proc.returncode != 0:
        raise HTTPException(
            status_code=502,
            detail=f"comfy-gen download failed: {(proc.stderr or proc.stdout).strip()[:500]}",
        )
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=502, detail=f"comfy-gen returned invalid JSON: {exc}") from exc


# ---- Routes ----

@router.get("/api/loras")
def list_loras_route() -> JSONResponse:
    """Fast path: serves the cached volume listing merged with DB metadata.

    Does NOT shell out to comfy-gen. Returns `stale: true` and `fetched_at: null`
    when no cache has been built yet, signaling the UI to trigger /sync.
    """
    _endpoint_id_or_409()
    filenames, fetched_at = _read_cached_loras()
    reconciled = lora_metadata.reconcile(filenames)
    stale = fetched_at is None or (time.time() - fetched_at) > CACHE_STALE_AFTER_SEC
    return JSONResponse({
        "loras": reconciled["merged"],
        "pruned": reconciled["pruned"],
        "fetched_at": fetched_at,
        "stale": stale,
    })


@router.post("/api/loras/sync")
def sync_loras_route() -> JSONResponse:
    """Cold path: shells out to `comfy-gen list loras`, then reconciles.

    Updates the shared comfy_gen cache file as a side effect, so the
    ComfyGen block dropdown also benefits.
    """
    endpoint_id = _endpoint_id_or_409()
    filenames = _fetch_loras_from_comfygen(endpoint_id)
    reconciled = lora_metadata.reconcile(filenames)
    return JSONResponse({
        "loras": reconciled["merged"],
        "pruned": reconciled["pruned"],
        "fetched_at": time.time(),
        "stale": False,
    })


@router.post("/api/loras/delete")
def delete_loras_route(body: DeleteRequest) -> JSONResponse:
    endpoint_id = _endpoint_id_or_409()
    if not body.filenames:
        raise HTTPException(status_code=400, detail="filenames must be non-empty")

    results = _delete_subprocess(body.filenames, endpoint_id)
    deleted_filenames: list[str] = []
    out: list[dict[str, Any]] = []
    for r in results:
        path = str(r.get("path", ""))
        fname = path.rsplit("/", 1)[-1] if path else ""
        deleted = bool(r.get("deleted"))
        out.append({
            "filename": fname,
            "deleted": deleted,
            "error": r.get("error"),
        })
        if deleted and fname:
            deleted_filenames.append(fname)
    if deleted_filenames:
        lora_metadata.delete_many(deleted_filenames)
        cached, fetched_at = _read_cached_loras()
        remaining = [f for f in cached if f not in set(deleted_filenames)]
        _write_cached_loras(remaining, fetched_at=fetched_at)

    all_ok = all(r["deleted"] for r in out)
    status = 200 if all_ok else 207
    return JSONResponse({"results": out}, status_code=status)


@router.post("/api/loras/download")
def download_lora_route(body: DownloadRequest) -> JSONResponse:
    global _download_in_flight  # noqa: PLW0603

    endpoint_id = _endpoint_id_or_409()

    with _download_lock:
        if _download_in_flight:
            raise HTTPException(status_code=409, detail="another download is in progress")
        _download_in_flight = True

    try:
        if body.source == "civitai":
            return _do_civitai_download(body, endpoint_id)
        elif body.source == "url":
            return _do_url_download(body, endpoint_id)
        else:
            raise HTTPException(status_code=400, detail=f"unknown source: {body.source!r}")
    finally:
        with _download_lock:
            _download_in_flight = False


def _do_civitai_download(body: DownloadRequest, endpoint_id: str) -> JSONResponse:
    if body.version_id is None:
        raise HTTPException(status_code=400, detail="civitai source requires version_id")

    api_key = config.CIVITAI_API_KEY
    meta: civitai_client.CivitAIVersionMetadata | None = None
    try:
        meta = civitai_client.fetch_version_metadata(body.version_id, api_key=api_key)
    except Exception:
        meta = None  # network failure / 404 / etc — proceed without enrichment

    filename = body.filename or (meta.primary_file_name if meta else None) \
        or f"civitai_{body.version_id}.safetensors"

    entry = {
        "source": "civitai",
        "version_id": body.version_id,
        "dest": "loras",
    }
    _download_subprocess([entry], endpoint_id)

    size_bytes = int(meta.primary_file_size_kb * 1024) if (meta and meta.primary_file_size_kb) else None
    lora_metadata.upsert(
        filename=filename,
        source="civitai",
        source_id=str(body.version_id),
        base_model=(meta.base_model if meta else None) or body.base_model,
        trigger_words=(meta.trigger_words if meta else []),
        size_bytes=size_bytes,
    )
    _append_to_cache(filename)
    return JSONResponse({"ok": True, "filename": filename})


def _do_url_download(body: DownloadRequest, endpoint_id: str) -> JSONResponse:
    if not body.url:
        raise HTTPException(status_code=400, detail="url source requires url")

    host = (urlparse(body.url).hostname or "").lower()
    detected_source = "hf" if host.endswith("huggingface.co") else "url"

    filename = body.filename or _filename_from_url(body.url)

    entry = {
        "source": "url",
        "url": body.url,
        "dest": "loras",
        "filename": filename,
    }
    _download_subprocess([entry], endpoint_id)

    lora_metadata.upsert(
        filename=filename,
        source=detected_source,
        source_id=body.url,
        base_model=body.base_model,
        trigger_words=[],
    )
    _append_to_cache(filename)
    return JSONResponse({"ok": True, "filename": filename})


def _append_to_cache(filename: str) -> None:
    cached, fetched_at = _read_cached_loras()
    if filename not in set(cached):
        _write_cached_loras([*cached, filename], fetched_at=fetched_at)


def _filename_from_url(url: str) -> str:
    path = urlparse(url).path
    name = path.rsplit("/", 1)[-1] or "download.safetensors"
    return name


@router.post("/api/loras/set-source")
def set_source_route(body: SetSourceRequest) -> JSONResponse:
    if body.source not in lora_metadata.VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"invalid source: {body.source!r}")

    base_model: str | None = None
    trigger_words: list[str] = []
    source_id = body.source_id or body.url

    if body.source == "civitai":
        if not body.source_id:
            raise HTTPException(status_code=400, detail="civitai source requires source_id (version_id)")
        try:
            vid = int(body.source_id)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="civitai source_id must be an integer version_id") from exc
        try:
            meta = civitai_client.fetch_version_metadata(vid, api_key=config.CIVITAI_API_KEY)
            base_model = meta.base_model
            trigger_words = meta.trigger_words
        except Exception:
            pass  # graceful: persist source linkage even if metadata fetch fails

    lora_metadata.upsert(
        filename=body.filename,
        source=body.source,
        source_id=source_id,
        base_model=base_model,
        trigger_words=trigger_words,
    )
    row = lora_metadata.get(body.filename)
    return JSONResponse({"ok": True, "lora": row})
