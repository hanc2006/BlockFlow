"""CivitAI provider: model search, model details, gallery images.

Request parameters and response fields follow CivitAI's public REST API
(/api/v1/models, /api/v1/models/<id>, /api/v1/images). Parameter handling is
adapted from comfyui-tiny-model-manager's civitai_provider.py and the image
prompt/LoRA extraction from ComfyUI-Civitai-Gallery-Explorer (both MIT, see
THIRD_PARTY.md).
"""
from __future__ import annotations

from typing import Any

import curl_cffi.requests as _requests

from backend.catalog import vocab
from backend.catalog._http import bearer, get_json

SOURCE = "civitai"
API_BASE = "https://civitai.com/api/v1"
SITE = "https://civitai.com"


def search_models(
    *,
    query: str = "",
    types: list[str] | None = None,
    base_models: list[str] | None = None,
    sort: str = "",
    period: str = "",
    nsfw: bool | None = None,
    limit: int = 20,
    cursor: str = "",
    api_key: str = "",
) -> dict:
    """-> {items: [model item], next_cursor: str | None}"""
    params: dict[str, Any] = {"limit": limit}
    if query:
        params["query"] = query
    if types:
        params["types"] = list(types)
    if base_models:
        params["baseModels"] = list(base_models)
    if sort:
        params["sort"] = sort
    if period:
        params["period"] = period
    if nsfw is not None:
        params["nsfw"] = "true" if nsfw else "false"
    if cursor:
        params["cursor"] = cursor
    data = get_json(_requests, SOURCE, f"{API_BASE}/models", params=params, headers=bearer(api_key))
    return {
        "items": [normalize_model(m) for m in data.get("items") or []],
        "next_cursor": (data.get("metadata") or {}).get("nextCursor") or None,
    }


def get_model(model_id: int, *, api_key: str = "") -> dict:
    data = get_json(_requests, SOURCE, f"{API_BASE}/models/{int(model_id)}", headers=bearer(api_key))
    return normalize_model(data, detailed=True)


def search_images(
    *,
    model_id: int | None = None,
    model_version_id: int | None = None,
    base_models: list[str] | None = None,
    username: str = "",
    sort: str = "",
    period: str = "",
    nsfw: str = "",
    only_with_prompt: bool = False,
    limit: int = 20,
    cursor: str = "",
    api_key: str = "",
) -> dict:
    """Gallery images with their generation data. -> {items, next_cursor}

    `only_with_prompt` filters locally, so a page can hold fewer than `limit`.
    """
    # CivitAI omits prompt/resource meta unless withMeta is set.
    params: dict[str, Any] = {"limit": limit, "withMeta": "true"}
    if model_id:
        params["modelId"] = model_id
    if model_version_id:
        params["modelVersionId"] = model_version_id
    if base_models:
        params["baseModels"] = list(base_models)
    if username:
        params["username"] = username
    if sort:
        params["sort"] = sort
    if period:
        params["period"] = period
    if nsfw:
        params["nsfw"] = nsfw
    if cursor:
        params["cursor"] = cursor
    data = get_json(_requests, SOURCE, f"{API_BASE}/images", params=params, headers=bearer(api_key))
    items = [normalize_image(i) for i in data.get("items") or []]
    if only_with_prompt:
        items = [i for i in items if i["prompt"]]
    return {"items": items, "next_cursor": (data.get("metadata") or {}).get("nextCursor") or None}


# ---------------------------------------------------------------- normalize

def _is_sfw(img: dict) -> bool:
    level = img.get("nsfwLevel")
    if isinstance(level, int):
        return level <= 1
    return not img.get("nsfw")


def _file(f: dict) -> dict:
    size_kb = f.get("sizeKB")
    sha = ((f.get("hashes") or {}).get("SHA256") or "").lower() or None
    return {
        "name": f.get("name"),
        "size_bytes": int(size_kb * 1024) if isinstance(size_kb, (int, float)) else None,
        "sha256": sha,
        "download_url": f.get("downloadUrl"),
        "primary": bool(f.get("primary")),
    }


def _primary_file(files: list[dict]) -> dict | None:
    return next((f for f in files if f.get("primary")), files[0] if files else None)


def _version(v: dict, type_: str, *, detailed: bool) -> dict:
    raw_files = v.get("files") or []
    primary = _primary_file(raw_files)
    download = None
    if primary and primary.get("name"):
        folder = vocab.dest_folder(type_)
        download = {
            "source": SOURCE,
            "url": primary.get("downloadUrl") or f"{SITE}/api/download/models/{v.get('id')}",
            "dest": f"{folder}/{primary['name']}" if folder else None,
            "sha256": _file(primary)["sha256"],
        }
    out = {
        "id": str(v.get("id")),
        "name": v.get("name"),
        "base_model": v.get("baseModel"),
        "family": vocab.family_of(v.get("baseModel")),
        "trigger_words": list(v.get("trainedWords") or []),
        "created_at": v.get("createdAt"),
        "files": [_file(f) for f in raw_files],
        "download": download,
    }
    if detailed:
        out["images"] = [
            {"url": i.get("url"), "media": "video" if i.get("type") == "video" else "image",
             "nsfw_level": i.get("nsfwLevel")}
            for i in v.get("images") or [] if i.get("url")
        ]
    return out


def normalize_model(m: dict, *, detailed: bool = False) -> dict:
    type_ = vocab.type_from_civitai(m.get("type"))
    raw_versions = m.get("modelVersions") or []
    head = raw_versions[0] if raw_versions else {}
    base = head.get("baseModel")
    thumbnail = next((i.get("url") for v in raw_versions for i in v.get("images") or []
                      if i.get("url") and _is_sfw(i)), None)
    stats = m.get("stats") or {}
    item = {
        "source": SOURCE,
        "id": str(m.get("id")),
        "name": m.get("name"),
        "type": type_,
        "type_raw": m.get("type"),
        "base_model": base,
        "family": vocab.family_of(base),
        "media": vocab.media_of(base),
        "tags": list(m.get("tags") or []),
        "nsfw": bool(m.get("nsfw")),
        "creator": (m.get("creator") or {}).get("username"),
        "stats": {"downloads": stats.get("downloadCount"), "likes": stats.get("thumbsUpCount")},
        "thumbnail": thumbnail,
        "url": f"{SITE}/models/{m.get('id')}",
        "trigger_words": list(head.get("trainedWords") or []),
        "versions": [_version(v, type_, detailed=detailed) for v in raw_versions],
    }
    if detailed:
        item["description"] = m.get("description") or ""
    return item


def _first(meta: dict, *keys: str) -> Any:
    return next((meta[k] for k in keys if meta.get(k) not in (None, "")), None)


def _lora_refs(meta: dict) -> list[dict]:
    """LoRAs from `resources` (A1111-style, by hash) and `civitaiResources`
    (CivitAI generator, by version id). Same rule as Gallery Explorer: a LoRA
    is kept only if it can be resolved (has a hash or a version id)."""
    out = []
    for key in ("resources", "civitaiResources"):
        for r in meta.get(key) or []:
            if not isinstance(r, dict) or str(r.get("type", "")).lower() != "lora":
                continue
            if not (r.get("hash") or r.get("modelVersionId")):
                continue
            out.append({
                "name": r.get("name"),
                "weight": r.get("weight"),
                "hash": r.get("hash"),
                "model_version_id": r.get("modelVersionId"),
            })
    return out


def normalize_image(i: dict) -> dict:
    meta = i.get("meta") if isinstance(i.get("meta"), dict) else {}
    settings = {
        "seed": meta.get("seed"),
        "steps": meta.get("steps"),
        "cfg_scale": meta.get("cfgScale"),
        "sampler": meta.get("sampler"),
        "model": _first(meta, "Model", "model"),
    }
    base = i.get("baseModel")
    return {
        "id": str(i.get("id")),
        "url": i.get("url"),
        "media": "video" if i.get("type") == "video" else "image",
        "nsfw_level": i.get("nsfwLevel"),
        "base_model": base,
        "family": vocab.family_of(base) if base else None,
        "prompt": _first(meta, "prompt", "Prompt", "positive", "textPrompt"),
        "negative_prompt": _first(meta, "negativePrompt", "NegativePrompt", "negative"),
        "settings": {k: v for k, v in settings.items() if v is not None},
        "loras": _lora_refs(meta),
    }
