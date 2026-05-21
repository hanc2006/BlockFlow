"""Preset installer manifest layer (sgs-ui-wisp-las.3 Stage A).

Routes:
  - GET  /api/presets/manifest[?refresh=1]      → fetch registry manifest
  - GET  /api/presets/installed                 → list installed presets
  - GET  /api/presets/installed/{preset_id}     → one installed preset (full)

Stage A is the read-only foundation. Stage B adds the install/uninstall
routes that actually call comfy-gen download. Stage C adds the /presets
Next.js page.

The manifest is fetched from a single public URL (per .3 design grilling):
`https://raw.githubusercontent.com/Hearmeman24/blockflow-presets/main/manifest.json`.
1-hour in-memory cache + on-disk fallback for offline cases.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from curl_cffi import requests as _cffi_requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from backend import config, settings_store

router = APIRouter()

# Where to fetch the canonical manifest from.
_MANIFEST_URL = (
    "https://raw.githubusercontent.com/Hearmeman24/blockflow-presets/main/manifest.json"
)
_CACHE_TTL_SEC = 3600  # 1 hour
_HTTP_TIMEOUT_SEC = 15

# Persistent fallback cache (survives process restarts → offline-friendly).
_CACHE_PATH: Path = config.ROOT_DIR / "preset_manifest_cache.json"

# In-memory cache
_cache: dict[str, Any] = {
    "fetched_at": 0.0,
    "manifest": None,
}


def _cache_reset() -> None:
    """Test helper — wipe both layers of cache."""
    _cache["fetched_at"] = 0.0
    _cache["manifest"] = None
    try:
        _CACHE_PATH.unlink(missing_ok=True)
    except OSError:
        pass


def _force_cache_expired() -> None:
    """Test helper — make the in-memory cache look stale without nuking the
    on-disk fallback. Used to simulate TTL expiry."""
    _cache["fetched_at"] = 0.0


def _load_disk_cache() -> dict | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        return json.loads(_CACHE_PATH.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def _save_disk_cache(manifest: dict) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(manifest, indent=2) + "\n")
    except OSError:
        pass  # best-effort; in-memory cache still works


def _cache_is_fresh() -> bool:
    if _cache["manifest"] is None:
        return False
    return (time.time() - _cache["fetched_at"]) < _CACHE_TTL_SEC


def _fetch_manifest() -> dict:
    """Hit the registry URL and return the parsed manifest. Raises on
    network failure or non-JSON response."""
    resp = _cffi_requests.get(_MANIFEST_URL, timeout=_HTTP_TIMEOUT_SEC)
    if resp.status_code >= 400:
        raise RuntimeError(f"registry returned HTTP {resp.status_code}")
    try:
        return resp.json()
    except (ValueError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"registry returned non-JSON: {exc}") from exc


@router.get("/api/presets/manifest")
def get_manifest(refresh: int = 0) -> JSONResponse:
    """Return the registry manifest. Cached in-memory for ~1h; on network
    failure with no cache, returns 502."""
    if not refresh and _cache_is_fresh():
        return JSONResponse(_cache["manifest"])

    try:
        manifest = _fetch_manifest()
    except Exception as exc:
        # Network / parse error. Try the disk fallback so we degrade gracefully.
        # If the in-memory cache is populated (just expired), prefer that —
        # it's at least as fresh as the disk copy.
        fallback = _cache["manifest"] or _load_disk_cache()
        if fallback is not None:
            payload = {**fallback, "cache": "stale", "fetch_error": str(exc)}
            return JSONResponse(payload)
        raise HTTPException(
            status_code=502,
            detail=f"could not reach preset registry: {exc}",
        ) from exc

    # Success — refresh both layers of cache
    _cache["manifest"] = manifest
    _cache["fetched_at"] = time.time()
    _save_disk_cache(manifest)
    return JSONResponse(manifest)


@router.get("/api/presets/installed")
def list_installed() -> JSONResponse:
    rows = settings_store.list_installed_presets()
    return JSONResponse({"installed": rows})


@router.get("/api/presets/installed/{preset_id}")
def get_installed(preset_id: str) -> JSONResponse:
    row = settings_store.get_installed_preset(preset_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"preset '{preset_id}' is not installed")
    # workflow_json is stored as a string; parse for the consumer.
    try:
        wf = json.loads(row["workflow_json"]) if row["workflow_json"] else {}
    except (ValueError, json.JSONDecodeError):
        wf = {}
    return JSONResponse({**row, "workflow_json": wf})
