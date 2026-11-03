"""Catalog service: turn family/media/type filters into provider queries and
cache the results for a few minutes (browsing re-requests the same pages)."""
from __future__ import annotations

import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from backend.catalog import civitai, huggingface, vocab

CACHE_TTL_SEC = 300
CACHE_MAX_ENTRIES = 256

_cache: OrderedDict[tuple, tuple[float, Any]] = OrderedDict()
_lock = threading.Lock()

EMPTY_PAGE = {"items": [], "next": None}


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _cached(key: tuple, fn: Callable[[], Any]) -> Any:
    """Return a cached value or compute it. Exceptions propagate and are not cached."""
    now = time.monotonic()
    with _lock:
        hit = _cache.get(key)
        if hit and hit[0] > now:
            _cache.move_to_end(key)
            return hit[1]
    value = fn()
    with _lock:
        _cache[key] = (now + CACHE_TTL_SEC, value)
        _cache.move_to_end(key)
        while len(_cache) > CACHE_MAX_ENTRIES:
            _cache.popitem(last=False)
    return value


def _base_models_filter(family: str | None, media: str | None) -> list[str] | None:
    """None = no filter; [] = the combination matches nothing."""
    if not family and not media:
        return None
    return vocab.base_models_for(family=family or None, media=media or None)


def search(
    *,
    source: str,
    query: str = "",
    type_: str | None = None,
    family: str | None = None,
    media: str | None = None,
    sort: str = "",
    period: str = "",
    limit: int = 20,
    cursor: str = "",
    civitai_key: str = "",
    hf_token: str = "",
) -> dict:
    """-> {items, next}. `next` is an opaque cursor string for the next page."""
    key = ("search", source, query, type_, family, media, sort, period, limit, cursor,
           civitai_key, hf_token)
    if source == "civitai":
        base_models = _base_models_filter(family, media)
        if base_models == []:
            return dict(EMPTY_PAGE)

        def run() -> dict:
            out = civitai.search_models(
                query=query,
                types=vocab.civitai_types_for(type_) if type_ else None,
                base_models=base_models,
                sort=sort, period=period, limit=limit, cursor=cursor, api_key=civitai_key,
            )
            return {"items": out["items"], "next": out["next_cursor"]}
        return _cached(key, run)

    if source == "huggingface":
        if cursor and not cursor.isdigit():
            raise ValueError("Hugging Face cursor must be a page number")

        def run() -> dict:
            out = huggingface.search_models(
                query=query,
                filters=["lora"] if type_ == "lora" else None,
                sort=sort or "downloads", limit=limit, page=int(cursor or 0),
                token=hf_token, type_hint=type_ or "",
            )
            items = out["items"]
            # The Hub has no base-model / media filter: narrow the page locally.
            if family:
                items = [i for i in items if i["family"] == family]
            if media:
                items = [i for i in items if i["media"] == media]
            nxt = out["next_page"]
            return {"items": items, "next": str(nxt) if nxt is not None else None}
        return _cached(key, run)

    raise ValueError(f"unknown source {source!r}")


def model(*, source: str, model_id: str, type_hint: str = "", civitai_key: str = "",
          hf_token: str = "") -> dict:
    if source == "civitai":
        mid = int(model_id)
        return _cached(("model", source, mid, civitai_key),
                       lambda: civitai.get_model(mid, api_key=civitai_key))
    if source == "huggingface":
        return _cached(("model", source, model_id, type_hint, hf_token),
                       lambda: huggingface.get_model(model_id, token=hf_token, type_hint=type_hint))
    raise ValueError(f"unknown source {source!r}")


def compatible(*, family: str, type_: str | None = "lora", query: str = "", sort: str = "",
               limit: int = 20, cursor: str = "", civitai_key: str = "") -> dict:
    """Models built for `family` (e.g. LoRAs for a Flux checkpoint)."""
    if family not in {f["family"] for f in vocab.families()}:
        raise ValueError(f"unknown family {family!r}")
    page = search(source="civitai", query=query, type_=type_, family=family, sort=sort,
                  limit=limit, cursor=cursor, civitai_key=civitai_key)
    return {"family": family, **page}


def prompts(*, model_id: int | None = None, model_version_id: int | None = None,
            family: str | None = None, sort: str = "", period: str = "", nsfw: str = "None",
            only_with_prompt: bool = True, limit: int = 20, cursor: str = "",
            civitai_key: str = "") -> dict:
    """Example generations (prompt, settings, LoRAs) from CivitAI's gallery."""
    base_models = _base_models_filter(family, None)
    if base_models == []:
        return dict(EMPTY_PAGE)
    key = ("prompts", model_id, model_version_id, family, sort, period, nsfw, only_with_prompt,
           limit, cursor, civitai_key)

    def run() -> dict:
        out = civitai.search_images(
            model_id=model_id, model_version_id=model_version_id, base_models=base_models,
            sort=sort, period=period, nsfw=nsfw, only_with_prompt=only_with_prompt,
            limit=limit, cursor=cursor, api_key=civitai_key,
        )
        return {"items": out["items"], "next": out["next_cursor"]}
    return _cached(key, run)
