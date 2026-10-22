"""Hugging Face provider: repo search and repo files.

Uses the Hub's /api/models endpoints. Search parameters, repo-id validation and
the LFS-sha256 rule are adapted from comfyui-tiny-model-manager's
huggingface_provider.py (MIT, see THIRD_PARTY.md).
"""
from __future__ import annotations

import posixpath
import re
from typing import Any

import curl_cffi.requests as _requests

from backend.catalog import vocab
from backend.catalog._http import bearer, get_json

SOURCE = "huggingface"
API_BASE = "https://huggingface.co/api"
SITE = "https://huggingface.co"

MODEL_EXTENSIONS = (".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin", ".sft", ".onnx")
_PREFERRED_EXTENSIONS = (".safetensors", ".gguf", ".sft")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif")
VIDEO_PIPELINES = {"text-to-video", "image-to-video", "video-to-video"}

_REPO_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def validate_repo_id(repo_id: str) -> str:
    repo_id = (repo_id or "").strip()
    if not _REPO_ID_RE.fullmatch(repo_id) or ".." in repo_id:
        raise ValueError(f"invalid Hugging Face repo id: {repo_id!r}")
    return repo_id


def search_models(
    *,
    query: str = "",
    filters: list[str] | None = None,
    pipeline_tag: str = "",
    sort: str = "downloads",
    limit: int = 20,
    page: int = 0,
    token: str = "",
    type_hint: str = "",
) -> dict:
    """-> {items: [model item], next_page: int | None}"""
    params: dict[str, Any] = {
        "search": query,
        "limit": limit,
        "sort": sort,
        "direction": -1,
        "p": page,
        "full": "true",  # include siblings, so results get thumbnails
    }
    if filters:
        params["filter"] = list(filters)
    if pipeline_tag:
        params["pipeline_tag"] = pipeline_tag
    data = get_json(_requests, SOURCE, f"{API_BASE}/models", params=params, headers=bearer(token))
    data = data if isinstance(data, list) else []
    return {
        "items": [normalize_model(m, type_hint=type_hint) for m in data],
        "next_page": page + 1 if len(data) >= limit else None,
    }


def get_model(repo_id: str, *, token: str = "", type_hint: str = "") -> dict:
    repo_id = validate_repo_id(repo_id)
    data = get_json(_requests, SOURCE, f"{API_BASE}/models/{repo_id}",
                    params={"blobs": "true"}, headers=bearer(token))
    return normalize_model(data, type_hint=type_hint, detailed=True)


# ---------------------------------------------------------------- normalize

def _as_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v.strip()]
    return []


def _base_model(m: dict) -> str | None:
    card = m.get("cardData") or {}
    from_card = _as_list(card.get("base_model"))
    if from_card:
        return from_card[0]
    for tag in m.get("tags") or []:
        # base_model:<relation>:<repo> or base_model:<repo>
        if isinstance(tag, str) and tag.startswith("base_model:"):
            return tag.split(":")[-1] or None
    return None


def _type(m: dict, type_hint: str) -> str:
    if type_hint:
        return type_hint
    tags = [t for t in m.get("tags") or [] if isinstance(t, str)]
    if "lora" in tags or any(t.startswith("base_model:adapter:") for t in tags):
        return "lora"
    return "other"


def _file_url(repo_id: str, name: str) -> str:
    return f"{SITE}/{repo_id}/resolve/main/{name}"


def _files(repo_id: str, siblings: list[dict]) -> list[dict]:
    model_files = [s for s in siblings
                   if str(s.get("rfilename", "")).lower().endswith(MODEL_EXTENSIONS)]
    primary = next((s for s in model_files
                    if s["rfilename"].lower().endswith(_PREFERRED_EXTENSIONS)),
                   model_files[0] if model_files else None)
    return [
        {
            "name": s["rfilename"],
            "size_bytes": s.get("size"),
            # LFS oid is the file's SHA-256; plain git blobs only have a SHA-1.
            "sha256": (s.get("lfs") or {}).get("oid") or None,
            "download_url": _file_url(repo_id, s["rfilename"]),
            "primary": s is primary,
        }
        for s in model_files
    ]


def normalize_model(m: dict, *, type_hint: str = "", detailed: bool = False) -> dict:
    repo_id = m.get("id") or m.get("modelId") or ""
    siblings = [s for s in m.get("siblings") or [] if isinstance(s, dict) and s.get("rfilename")]
    base = _base_model(m)
    type_ = _type(m, type_hint)
    family = vocab.family_of(base)
    media = ("video" if m.get("pipeline_tag") in VIDEO_PIPELINES or family in vocab.VIDEO_FAMILIES
             else "image")
    thumbnail = next((_file_url(repo_id, s["rfilename"]) for s in siblings
                      if s["rfilename"].lower().endswith(IMAGE_EXTENSIONS)), None)
    card = m.get("cardData") or {}
    item = {
        "source": SOURCE,
        "id": repo_id,
        "name": repo_id.split("/")[-1],
        "type": type_,
        "type_raw": m.get("pipeline_tag"),
        "base_model": base,
        "family": family,
        "media": media,
        "tags": [t for t in m.get("tags") or [] if isinstance(t, str)],
        "nsfw": "not-for-all-audiences" in (m.get("tags") or []),
        "creator": m.get("author") or (repo_id.split("/")[0] if "/" in repo_id else None),
        "stats": {"downloads": m.get("downloads"), "likes": m.get("likes")},
        "thumbnail": thumbnail,
        "url": f"{SITE}/{repo_id}",
        "trigger_words": _as_list(card.get("instance_prompt")),
        "versions": [],
    }
    if detailed:
        files = _files(repo_id, siblings)
        primary = next((f for f in files if f["primary"]), None)
        download = None
        if primary:
            folder = vocab.dest_folder(type_)
            download = {
                "source": SOURCE,
                "url": primary["download_url"],
                "dest": f"{folder}/{posixpath.basename(primary['name'])}" if folder else None,
                "sha256": primary["sha256"],
            }
        item["versions"] = [{
            "id": "main",
            "name": "main",
            "base_model": base,
            "family": family,
            "trigger_words": item["trigger_words"],
            "created_at": m.get("lastModified"),
            "files": files,
            "download": download,
        }]
        item["description"] = card.get("description") or ""
    return item
