"""Dataset Caption block.

For every image in a dataset that lacks a matching .txt caption, run a
vision-LLM over the image and write `<trigger_word>, <caption>` to disk.
Skip images that already have captions unless `overwrite=True`.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
import re
import time
import threading
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from backend import config, services

log = logging.getLogger(__name__)
router = APIRouter()

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
DATASETS_DIR = config.LOCAL_OUTPUT_DIR / "datasets"

DEFAULT_SYSTEM_PROMPT = (
    "You are writing a single-sentence caption for a LoRA training dataset. "
    "Describe ONLY what is visible: clothing, pose, location, lighting, background. "
    "Do NOT describe the subject's identity (no names, no hair colour, no facial features) "
    "— the trigger word handles identity. Keep it to one dense sentence, no preamble, no quotes, "
    "no markdown."
)
DEFAULT_USER_PROMPT = "Caption this image for LoRA training. One sentence."

# ---------------------------------------------------------------------------
# Job state
# ---------------------------------------------------------------------------

JOBS_LOCK = threading.Lock()
JOBS: dict[str, dict[str, Any]] = {}


def _set(job_id: str, **fields: Any) -> None:
    with JOBS_LOCK:
        rec = JOBS.get(job_id)
        if rec is None:
            return
        rec.update(fields)


# ---------------------------------------------------------------------------
# Vision call
# ---------------------------------------------------------------------------


def _image_to_data_uri(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    if not mime:
        mime = "image/png"
    b64 = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{b64}"


def _caption_one(model: str, system_prompt: str, user_prompt: str,
                  image_path: Path, max_tokens: int, temperature: float) -> str:
    image_url = _image_to_data_uri(image_path)
    messages: list[dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": [
            {"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}},
        ]})
    messages.append({"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": image_url}},
        {"type": "text", "text": user_prompt},
    ]})
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        # Captioning is shallow — use minimal reasoning so most of the
        # max_tokens budget goes to the visible caption. Some models
        # (e.g. Gemini 3.5 Flash) reject `effort: none`, so use `low`.
        "reasoning": {"effort": "low"},
    }
    resp = services._openrouter_request_json("POST", "/chat/completions", body, timeout=180)
    text = services._extract_openrouter_completion_text(resp) or ""
    # Clean up — strip quotes, trailing periods optional, single line
    text = text.strip().strip('"').strip("'").strip()
    # Drop any leading "Caption:" / "Description:" preambles the model adds
    text = re.sub(r"^(caption|description|answer)\s*[:\-]\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+", " ", text).strip()
    return text


# ---------------------------------------------------------------------------
# Dataset resolution
# ---------------------------------------------------------------------------


def _resolve_dataset_dir(spec: dict[str, Any] | None, folder_id: str | None) -> tuple[Path, str]:
    if spec and isinstance(spec, dict):
        images = spec.get("images") or []
        if isinstance(images, list) and images:
            first = images[0]
            if isinstance(first, str) and first.startswith("/outputs/datasets/"):
                folder = first[len("/outputs/datasets/"):].split("/", 1)[0]
                p = DATASETS_DIR / folder
                if p.is_dir():
                    return p, str(spec.get("name") or folder)
    if folder_id:
        safe = re.sub(r"[^a-zA-Z0-9_.-]", "", folder_id)
        p = DATASETS_DIR / safe
        if p.is_dir():
            return p, safe
    raise ValueError("No dataset selected — connect a Dataset Create block or pick one from the dropdown.")


# ---------------------------------------------------------------------------
# Worker
# ---------------------------------------------------------------------------


def _run_captioning(job_id: str, dataset_dir: Path, model: str,
                    system_prompt: str, user_prompt: str, trigger_word: str,
                    overwrite: bool, max_tokens: int, temperature: float,
                    concurrency: int) -> None:
    started = time.time()
    try:
        images = sorted([p for p in dataset_dir.iterdir()
                          if p.is_file() and p.suffix.lower() in IMAGE_EXTS])
        total = len(images)
        if total == 0:
            _set(job_id, status="FAILED", error="Dataset has no images", ended_at=time.time())
            return

        # Decide which images need captions
        targets: list[Path] = []
        skipped = 0
        for img in images:
            cap = img.with_suffix(".txt")
            if cap.exists() and not overwrite:
                skipped += 1
                continue
            targets.append(img)

        _set(job_id, total=total, targets=len(targets), skipped=skipped)

        if not targets:
            _set(job_id, status="COMPLETED", completed=0, ended_at=time.time())
            return

        # Bounded parallelism via a semaphore-like list of slots
        import concurrent.futures
        completed = 0
        failed = 0
        errors: list[str] = []
        prefix = (trigger_word.strip() + ", ") if trigger_word.strip() else ""

        def _one(img: Path) -> tuple[Path, str | None, str | None]:
            try:
                with JOBS_LOCK:
                    if JOBS.get(job_id, {}).get("cancel_requested"):
                        return img, None, "cancelled"
                caption = _caption_one(model, system_prompt, user_prompt, img, max_tokens, temperature)
                if not caption:
                    return img, None, "empty caption"
                final = prefix + caption
                img.with_suffix(".txt").write_text(final + "\n", encoding="utf-8")
                return img, final, None
            except Exception as exc:
                return img, None, str(exc)

        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(concurrency, 8))) as ex:
            futures = [ex.submit(_one, img) for img in targets]
            for fut in concurrent.futures.as_completed(futures):
                img, final, err = fut.result()
                if err:
                    failed += 1
                    errors.append(f"{img.name}: {err[:200]}")
                else:
                    completed += 1
                _set(job_id, completed=completed, failed=failed)

        elapsed = time.time() - started
        status = "FAILED" if (completed == 0 and failed > 0) else ("PARTIAL" if failed > 0 else "COMPLETED")
        _set(job_id, status=status, ended_at=time.time(), elapsed=elapsed,
             error="; ".join(errors[:5])[:800] if errors else "")

    except Exception as exc:
        log.exception("[dataset_caption] job %s crashed", job_id)
        _set(job_id, status="FAILED", error=str(exc), ended_at=time.time())


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@router.get("/health")
def health() -> JSONResponse:
    return JSONResponse({
        "ok": True,
        "openrouter_key_present": bool(config.OPENROUTER_API_KEY),
        "default_system_prompt": DEFAULT_SYSTEM_PROMPT,
        "default_user_prompt": DEFAULT_USER_PROMPT,
    })


@router.get("/datasets")
def list_datasets() -> JSONResponse:
    out: list[dict[str, Any]] = []
    if DATASETS_DIR.exists():
        for folder in sorted(DATASETS_DIR.iterdir()):
            if not folder.is_dir():
                continue
            imgs = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
            captions = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".txt"]
            thumb_urls = [f"/outputs/datasets/{folder.name}/{p.name}" for p in imgs[:4]]
            out.append({
                "id": folder.name,
                "name": folder.name,
                "image_count": len(imgs),
                "caption_count": len(captions),
                "thumb_urls": thumb_urls,
            })
    return JSONResponse({"ok": True, "datasets": out})


@router.post("/run")
async def run(request: Request) -> JSONResponse:
    body = await request.json()
    model = str(body.get("model") or "").strip()
    trigger_word = str(body.get("trigger_word") or "").strip()
    overwrite = bool(body.get("overwrite", False))
    concurrency = int(body.get("concurrency") or 4)
    max_tokens = int(body.get("max_tokens") or 2000)
    temperature = float(body.get("temperature", 0.4))
    system_prompt = str(body.get("system_prompt") or DEFAULT_SYSTEM_PROMPT)
    user_prompt = str(body.get("user_prompt") or DEFAULT_USER_PROMPT)
    dataset_spec = body.get("dataset") if isinstance(body.get("dataset"), dict) else None
    dataset_folder = body.get("dataset_folder")

    if not model:
        return JSONResponse({"ok": False, "error": "model is required"}, status_code=400)
    if not config.OPENROUTER_API_KEY:
        return JSONResponse({"ok": False, "error": "OPENROUTER_API_KEY not set in .env"}, status_code=400)
    try:
        dataset_dir, dataset_name = _resolve_dataset_dir(dataset_spec, dataset_folder)
    except ValueError as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)

    job_id = uuid.uuid4().hex
    rec = {
        "job_id": job_id, "dataset_name": dataset_name, "dataset_path": str(dataset_dir),
        "model": model, "trigger_word": trigger_word, "overwrite": overwrite,
        "status": "RUNNING", "total": 0, "targets": 0, "skipped": 0,
        "completed": 0, "failed": 0, "started_at": time.time(), "ended_at": None,
        "error": "", "cancel_requested": False,
    }
    with JOBS_LOCK:
        JOBS[job_id] = rec

    t = threading.Thread(
        target=_run_captioning,
        args=(job_id, dataset_dir, model, system_prompt, user_prompt, trigger_word,
              overwrite, max_tokens, temperature, concurrency),
        daemon=True,
    )
    t.start()

    return JSONResponse({
        "ok": True, "job_id": job_id, "dataset_folder": dataset_dir.name,
        "dataset_relative_url": f"/outputs/datasets/{dataset_dir.name}",
    })


@router.get("/status/{job_id}")
def status(job_id: str) -> JSONResponse:
    with JOBS_LOCK:
        rec = JOBS.get(job_id)
        if not rec:
            return JSONResponse({"ok": False, "error": "job not found"}, status_code=404)
        snap = dict(rec)
    return JSONResponse({"ok": True, "job": snap})


@router.post("/cancel/{job_id}")
def cancel(job_id: str) -> JSONResponse:
    with JOBS_LOCK:
        rec = JOBS.get(job_id)
        if not rec:
            return JSONResponse({"ok": False, "error": "job not found"}, status_code=404)
        rec["cancel_requested"] = True
    return JSONResponse({"ok": True})
