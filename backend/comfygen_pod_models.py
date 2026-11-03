"""Model files on an attached persistent ComfyGen server ("dedicated" runtime).

With a pod server attached there is no serverless endpoint or network volume:
the pod's own ComfyUI models folder is managed through its /models/* routes
(ComfyGen server.py + pod_models.py). Used by the Models, LoRA and preset
routes. Paths are relative to the pod's models folder ("loras/x.safetensors").
"""
from __future__ import annotations

import time
from typing import Any, Callable
from urllib.parse import quote

from fastapi import HTTPException

from backend import comfygen_remote, config, settings_store

# Seconds between progress polls of a pod download job, and how many failed
# polls in a row are tolerated before giving up on it.
POLL_SEC = 2.0
MAX_POLL_ERRORS = 15
# Longest single download BlockFlow waits for (the pod keeps going regardless).
DOWNLOAD_TIMEOUT_SEC = 6 * 3600

CIVITAI_DOWNLOAD_URL = "https://civitai.com/api/download/models/{version_id}"


def is_dedicated() -> bool:
    return settings_store.get_comfygen_runtime().get("runtime_kind") == "dedicated"


def server() -> tuple[str, str]:
    """(base_url, token) of the attached server; 400 if either is missing."""
    base_url = str(settings_store.get_comfygen_runtime().get("base_url") or "")
    token = (settings_store.get_credential("comfygen_remote_token") or "").strip()
    if not base_url or not token:
        raise HTTPException(
            status_code=400,
            detail="Dedicated ComfyGen server URL and bearer token are required",
        )
    return base_url, token


def tokens() -> dict[str, str]:
    """Download credentials from Settings, sent to the pod with each download."""
    civitai = settings_store.get_credential("civitai_api_key") or getattr(config, "CIVITAI_API_KEY", None) or ""
    return {
        "hf_token": settings_store.get_credential("hf_token") or "",
        "civitai_token": civitai,
    }


def civitai_download_url(version_id: int | str) -> str:
    return CIVITAI_DOWNLOAD_URL.format(version_id=int(version_id))


def list_folders(folders: list[str] | tuple[str, ...]) -> dict[str, list[dict[str, Any]]]:
    """{folder: [{"filename", "path", "size_bytes"}]} from the pod; 502 if unreachable."""
    base_url, token = server()
    try:
        resp = comfygen_remote.request_json(
            base_url, token, "GET", f"/models/list?folders={quote(','.join(folders), safe=',')}", timeout=60,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"could not list models on the pod: {exc}") from exc
    listing = resp.get("folders") if isinstance(resp.get("folders"), dict) else {}
    out: dict[str, list[dict[str, Any]]] = {}
    for folder in folders:
        rows = listing.get(folder) if isinstance(listing.get(folder), list) else []
        out[folder] = [
            {"filename": str(r["filename"]), "path": str(r.get("path") or f"{folder}/{r['filename']}"),
             "size_bytes": r.get("size_bytes")}
            for r in rows if isinstance(r, dict) and r.get("filename")
        ]
    return out


def delete(paths: list[str]) -> list[dict[str, Any]]:
    """Delete files on the pod. Returns [{"path", "deleted", "error"}]; 502 if unreachable."""
    base_url, token = server()
    try:
        resp = comfygen_remote.request_json(
            base_url, token, "POST", "/models/delete", {"paths": paths}, timeout=120,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"could not delete files on the pod: {exc}") from exc
    results = resp.get("results") if isinstance(resp.get("results"), list) else []
    return [
        {"path": r.get("path"), "deleted": bool(r.get("deleted")), "error": r.get("error") or r.get("reason")}
        for r in results if isinstance(r, dict)
    ]


def download(
    models: list[dict[str, Any]],
    on_progress: Callable[[dict[str, Any]], None] | None = None,
) -> tuple[bool, Any]:
    """Run a download job on the pod and wait for it.

    models: [{"url", "dest", "sha256"?, "size_gb"?}] with dest relative to the
    models folder. Returns (True, final_status) or (False, error_message).
    on_progress receives every status the pod reports while it runs.
    """
    try:
        base_url, token = server()
    except HTTPException as exc:
        return (False, str(exc.detail))
    try:
        started = comfygen_remote.request_json(
            base_url, token, "POST", "/models/download", {"models": models, **tokens()}, timeout=60,
        )
    except Exception as exc:
        return (False, f"could not start the download on the pod: {exc}")
    job_id = str(started.get("id") or "")
    if not job_id:
        return (False, "pod did not return a download id")

    errors = 0
    deadline = time.monotonic() + DOWNLOAD_TIMEOUT_SEC
    while time.monotonic() < deadline:
        try:
            status = comfygen_remote.request_json(
                base_url, token, "GET", f"/models/download/{job_id}", timeout=30,
            )
            errors = 0
        except Exception as exc:
            errors += 1
            if errors >= MAX_POLL_ERRORS:
                return (False, f"Lost contact with the pod while downloading: {exc}")
            time.sleep(POLL_SEC)
            continue
        if on_progress is not None:
            on_progress(status)
        state = status.get("status")
        if state == "completed":
            return (True, status)
        if state in ("failed", "cancelled"):
            return (False, str(status.get("message") or f"download {state} on the pod"))
        time.sleep(POLL_SEC)
    return (False, f"download still running on the pod after {DOWNLOAD_TIMEOUT_SEC}s")


def percent_done(status: dict[str, Any]) -> int:
    """Overall download percentage from a pod status (by bytes, else by files)."""
    files = status.get("files") if isinstance(status.get("files"), list) else []
    total = sum(int(f.get("bytes_total") or 0) for f in files)
    if total > 0:
        done = sum(
            int(f.get("bytes_total") or 0) if f.get("status") == "done"
            else int(f.get("bytes_done") or 0) if f.get("status") == "downloading" else 0
            for f in files
        )
        return min(100, int(done * 100 / total))
    if files:
        return int(100 * sum(1 for f in files if f.get("status") == "done") / len(files))
    return 0
