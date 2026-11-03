"""HTTP routes for the model catalog (CivitAI + Hugging Face search).

GET /api/catalog/families                         families, media kinds, model types
GET /api/catalog/search                           ?source=civitai|huggingface&q=&type=&family=&media=&sort=&period=&limit=&cursor=
GET /api/catalog/model/civitai/{model_id}         one model with versions, files, download entries
GET /api/catalog/model/huggingface/{owner}/{repo} same, for a Hub repo (?type= sets the dest folder)
GET /api/catalog/compatible                       ?family=Flux&type=lora — models built for a base family
GET /api/catalog/prompts                          ?model_version_id=&model_id=&family= — gallery prompts, settings, LoRAs

Pages are `{items, next}`; pass `next` back as `cursor`. Upstream failures map
to 502 (429 when the provider rate-limits) with {source, status, message}.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from backend import settings_store
from backend.catalog import service, vocab
from backend.catalog.errors import CatalogUpstreamError

router = APIRouter()

Source = Literal["civitai", "huggingface"]
Media = Literal["image", "video", "audio"]
ModelType = Literal[tuple(vocab.TYPES)]  # type: ignore[valid-type]


def _civitai_key() -> str:
    return settings_store.get_credential("civitai_api_key") or ""


def _hf_token() -> str:
    return settings_store.get_credential("hf_token") or ""


def _call(fn, **kwargs):
    try:
        return fn(**kwargs)
    except CatalogUpstreamError as exc:
        status = 429 if exc.status == 429 else 502
        raise HTTPException(status_code=status, detail={
            "source": exc.source, "status": exc.status, "message": exc.message,
        }) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/api/catalog/families")
def families_route() -> dict:
    return {"families": vocab.families(), "types": list(vocab.TYPES), "media": list(vocab.MEDIA)}


@router.get("/api/catalog/search")
def search_route(
    source: Source = "civitai",
    q: str = Query("", max_length=200),
    type: ModelType | None = None,  # noqa: A002 — public query parameter name
    family: str | None = Query(None, max_length=64),
    media: Media | None = None,
    sort: str = Query("", max_length=64),
    period: str = Query("", max_length=32),
    limit: int = Query(20, ge=1, le=100),
    cursor: str = Query("", max_length=4000),
) -> dict:
    return _call(
        service.search, source=source, query=q.strip(), type_=type, family=family, media=media,
        sort=sort, period=period, limit=limit, cursor=cursor,
        civitai_key=_civitai_key() if source == "civitai" else "",
        hf_token=_hf_token() if source == "huggingface" else "",
    )


@router.get("/api/catalog/model/civitai/{model_id}")
def civitai_model_route(model_id: int) -> dict:
    return _call(service.model, source="civitai", model_id=str(model_id),
                 civitai_key=_civitai_key())


@router.get("/api/catalog/model/huggingface/{repo_id:path}")
def huggingface_model_route(repo_id: str, type: ModelType | None = None) -> dict:  # noqa: A002
    return _call(service.model, source="huggingface", model_id=repo_id,
                 type_hint=type or "", hf_token=_hf_token())


@router.get("/api/catalog/compatible")
def compatible_route(
    family: str = Query(..., max_length=64),
    type: ModelType | None = "lora",  # noqa: A002
    q: str = Query("", max_length=200),
    sort: str = Query("", max_length=64),
    limit: int = Query(20, ge=1, le=100),
    cursor: str = Query("", max_length=4000),
) -> dict:
    return _call(service.compatible, family=family, type_=type, query=q.strip(), sort=sort,
                 limit=limit, cursor=cursor, civitai_key=_civitai_key())


@router.get("/api/catalog/prompts")
def prompts_route(
    model_id: int | None = None,
    model_version_id: int | None = None,
    family: str | None = Query(None, max_length=64),
    sort: str = Query("", max_length=64),
    period: str = Query("", max_length=32),
    nsfw: Literal["None", "Soft", "Mature", "X"] = "None",
    only_with_prompt: bool = True,
    limit: int = Query(20, ge=1, le=100),
    cursor: str = Query("", max_length=4000),
) -> dict:
    return _call(service.prompts, model_id=model_id, model_version_id=model_version_id,
                 family=family, sort=sort, period=period, nsfw=nsfw,
                 only_with_prompt=only_with_prompt, limit=limit, cursor=cursor,
                 civitai_key=_civitai_key())
