"""HTTP routes for the model catalog (/api/catalog/*).

Providers are mocked at the module boundary; these tests check routing,
parameter translation (family/media/type -> provider filters), credentials,
caching and error mapping.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import catalog_routes  # noqa: E402
from backend.catalog import service  # noqa: E402
from backend.catalog.errors import CatalogUpstreamError  # noqa: E402


@pytest.fixture
def client(mocker) -> TestClient:
    service.clear_cache()
    creds = {"civitai_api_key": "CIVKEY", "hf_token": "HFTOKEN"}
    mocker.patch.object(catalog_routes.settings_store, "get_credential",
                        side_effect=lambda name: creds.get(name))
    app = FastAPI()
    app.include_router(catalog_routes.router)
    return TestClient(app)


def test_catalog_routes_are_mounted_on_main_app() -> None:
    from backend.main import app

    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/catalog/search" in paths
    assert "/api/catalog/model/huggingface/{repo_id:path}" in paths


def test_families_endpoint(client) -> None:
    body = client.get("/api/catalog/families").json()
    fams = {f["family"]: f for f in body["families"]}
    assert fams["Wan"]["media"] == "video"
    assert "Flux.1 D" in fams["Flux"]["base_models"]
    assert "lora" in body["types"]


def test_search_civitai_translates_family_type_and_media(client, mocker) -> None:
    search = mocker.patch.object(service.civitai, "search_models",
                                 return_value={"items": [{"id": "1"}], "next_cursor": "c2"})
    r = client.get("/api/catalog/search", params={
        "source": "civitai", "q": "light", "type": "lora", "family": "Flux",
        "sort": "Most Downloaded", "cursor": "c1",
    })
    assert r.status_code == 200
    assert r.json() == {"items": [{"id": "1"}], "next": "c2"}
    kw = search.call_args.kwargs
    assert kw["query"] == "light"
    assert kw["types"] == ["LORA", "LoCon", "DoRA"]
    assert "Flux.1 D" in kw["base_models"] and "Flux.1 Kontext" not in kw["base_models"]
    assert kw["sort"] == "Most Downloaded"
    assert kw["cursor"] == "c1"
    assert kw["api_key"] == "CIVKEY"


def test_search_civitai_media_video_restricts_base_models(client, mocker) -> None:
    search = mocker.patch.object(service.civitai, "search_models",
                                 return_value={"items": [], "next_cursor": None})
    client.get("/api/catalog/search", params={"source": "civitai", "media": "video"})
    bms = search.call_args.kwargs["base_models"]
    assert bms and all("Wan" in b or "LTX" in b or "Hunyuan" in b or b in
                       ("CogVideoX", "Mochi", "MiniMax H3") for b in bms)


def test_family_and_media_conflict_is_empty_not_unfiltered(client, mocker) -> None:
    search = mocker.patch.object(service.civitai, "search_models")
    r = client.get("/api/catalog/search",
                   params={"source": "civitai", "family": "Flux", "media": "video"})
    assert r.status_code == 200
    assert r.json() == {"items": [], "next": None}
    search.assert_not_called()


def test_search_huggingface_passes_token_and_filters(client, mocker) -> None:
    search = mocker.patch.object(service.huggingface, "search_models",
                                 return_value={"items": [], "next_page": 1})
    r = client.get("/api/catalog/search",
                   params={"source": "huggingface", "q": "wan", "type": "lora", "cursor": "0"})
    assert r.json()["next"] == "1"
    kw = search.call_args.kwargs
    assert kw["query"] == "wan"
    assert kw["filters"] == ["lora"]
    assert kw["page"] == 0
    assert kw["token"] == "HFTOKEN"
    assert kw["type_hint"] == "lora"


@pytest.mark.parametrize("params", [
    {"source": "nope"},
    {"source": "civitai", "type": "nope"},
    {"source": "civitai", "media": "nope"},
    {"source": "huggingface", "cursor": "abc"},
    {"source": "civitai", "limit": "0"},
    {"source": "civitai", "limit": "500"},
])
def test_search_rejects_bad_params(client, params) -> None:
    assert client.get("/api/catalog/search", params=params).status_code == 422


def test_search_results_are_cached(client, mocker) -> None:
    search = mocker.patch.object(service.civitai, "search_models",
                                 return_value={"items": [], "next_cursor": None})
    for _ in range(3):
        client.get("/api/catalog/search", params={"source": "civitai", "q": "same"})
    assert search.call_count == 1
    client.get("/api/catalog/search", params={"source": "civitai", "q": "other"})
    assert search.call_count == 2


def test_upstream_errors_are_not_cached_and_map_to_502(client, mocker) -> None:
    search = mocker.patch.object(service.civitai, "search_models",
                                 side_effect=CatalogUpstreamError("civitai", 500, "boom"))
    for _ in range(2):
        r = client.get("/api/catalog/search", params={"source": "civitai", "q": "x"})
        assert r.status_code == 502
        assert r.json()["detail"] == {"source": "civitai", "status": 500, "message": "boom"}
    assert search.call_count == 2


def test_upstream_rate_limit_maps_to_429(client, mocker) -> None:
    mocker.patch.object(service.civitai, "search_models",
                        side_effect=CatalogUpstreamError("civitai", 429, "slow down"))
    assert client.get("/api/catalog/search", params={"source": "civitai"}).status_code == 429


def test_model_detail_civitai_and_hf(client, mocker) -> None:
    civ = mocker.patch.object(service.civitai, "get_model", return_value={"id": "101"})
    hf = mocker.patch.object(service.huggingface, "get_model", return_value={"id": "a/b"})

    assert client.get("/api/catalog/model/civitai/101").json() == {"id": "101"}
    assert civ.call_args.args == (101,)
    assert civ.call_args.kwargs["api_key"] == "CIVKEY"

    assert client.get("/api/catalog/model/huggingface/a/b", params={"type": "vae"}).json() == {"id": "a/b"}
    assert hf.call_args.args == ("a/b",)
    assert hf.call_args.kwargs == {"token": "HFTOKEN", "type_hint": "vae"}


def test_model_detail_bad_ids(client, mocker) -> None:
    assert client.get("/api/catalog/model/civitai/abc").status_code == 422
    mocker.patch.object(service.huggingface, "get_model", side_effect=ValueError("bad repo id"))
    assert client.get("/api/catalog/model/huggingface/bad..id").status_code == 422


def test_compatible_requires_family_and_uses_civitai(client, mocker) -> None:
    search = mocker.patch.object(service.civitai, "search_models",
                                 return_value={"items": [{"id": "1"}], "next_cursor": None})
    assert client.get("/api/catalog/compatible", params={"type": "lora"}).status_code == 422
    r = client.get("/api/catalog/compatible", params={"family": "Wan", "type": "lora", "q": "motion"})
    assert r.json()["family"] == "Wan"
    kw = search.call_args.kwargs
    assert "Wan Video 2.2 I2V-A14B" in kw["base_models"]
    assert kw["types"] == ["LORA", "LoCon", "DoRA"]
    assert kw["query"] == "motion"


def test_compatible_unknown_family_is_422(client) -> None:
    assert client.get("/api/catalog/compatible", params={"family": "Nope"}).status_code == 422


def test_prompts_endpoint(client, mocker) -> None:
    imgs = mocker.patch.object(service.civitai, "search_images",
                               return_value={"items": [{"prompt": "p"}], "next_cursor": None})
    r = client.get("/api/catalog/prompts", params={"model_version_id": "9001", "family": "Flux"})
    assert r.json() == {"items": [{"prompt": "p"}], "next": None}
    kw = imgs.call_args.kwargs
    assert kw["model_version_id"] == 9001
    assert "Flux.1 D" in kw["base_models"]
    assert kw["only_with_prompt"] is True
    assert kw["nsfw"] == "None"
