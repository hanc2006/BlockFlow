"""CivitAI catalog provider: request building + normalization.

HTTP is mocked at the curl_cffi boundary. Payload fixtures are hand-written
from the field names CivitAI's public API returns (no live network here).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from backend.catalog import civitai  # noqa: E402
from backend.catalog.errors import CatalogUpstreamError  # noqa: E402


def _resp(status: int, body) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    m.text = str(body)
    return m


MODEL = {
    "id": 101,
    "name": "Cinematic Light",
    "type": "LORA",
    "nsfw": False,
    "tags": ["style", "lighting"],
    "creator": {"username": "alice"},
    "stats": {"downloadCount": 1234, "thumbsUpCount": 56},
    "description": "<p>Moody light.</p>",
    "modelVersions": [
        {
            "id": 9001,
            "name": "v2",
            "baseModel": "Flux.1 D",
            "trainedWords": ["cinelight", "moody"],
            "createdAt": "2026-01-02T00:00:00.000Z",
            "images": [
                {"url": "https://image.civitai.com/x/nsfw.jpeg", "nsfwLevel": 8, "type": "image"},
                {"url": "https://image.civitai.com/x/safe.jpeg", "nsfwLevel": 1, "type": "image"},
            ],
            "files": [
                {"name": "cinelight_v2.safetensors", "sizeKB": 1024.0, "primary": True,
                 "hashes": {"SHA256": "ABCDEF0123"},
                 "downloadUrl": "https://civitai.com/api/download/models/9001"},
                {"name": "cinelight_v2_training.zip", "sizeKB": 10.0, "type": "Training Data",
                 "downloadUrl": "https://civitai.com/api/download/models/9001?type=Training%20Data"},
            ],
        },
        {
            "id": 9000,
            "name": "v1",
            "baseModel": "SDXL 1.0",
            "trainedWords": [],
            "images": [],
            "files": [],
        },
    ],
}


def test_search_builds_params_and_normalizes(mocker) -> None:
    get = mocker.patch.object(civitai._requests, "get", return_value=_resp(
        200, {"items": [MODEL], "metadata": {"nextCursor": "abc|123"}}
    ))

    out = civitai.search_models(
        query="light", types=["LORA"], base_models=["Flux.1 D", "Flux.1 S"],
        sort="Most Downloaded", period="Month", limit=10, api_key="KEY",
    )

    url = get.call_args.args[0]
    params = get.call_args.kwargs["params"]
    assert url == "https://civitai.com/api/v1/models"
    assert params["query"] == "light"
    assert params["types"] == ["LORA"]
    assert params["baseModels"] == ["Flux.1 D", "Flux.1 S"]
    assert params["sort"] == "Most Downloaded"
    assert params["period"] == "Month"
    assert params["limit"] == 10
    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer KEY"}

    assert out["next_cursor"] == "abc|123"
    (item,) = out["items"]
    assert item["source"] == "civitai"
    assert item["id"] == "101"
    assert item["name"] == "Cinematic Light"
    assert item["type"] == "lora"
    assert item["type_raw"] == "LORA"
    assert item["base_model"] == "Flux.1 D"
    assert item["family"] == "Flux"
    assert item["media"] == "image"
    assert item["trigger_words"] == ["cinelight", "moody"]
    assert item["creator"] == "alice"
    assert item["stats"] == {"downloads": 1234, "likes": 56}
    # Thumbnail prefers a SFW preview.
    assert item["thumbnail"] == "https://image.civitai.com/x/safe.jpeg"
    assert item["url"] == "https://civitai.com/models/101"
    # Search results stay light: no description HTML.
    assert "description" not in item


def test_search_anonymous_without_key_and_omits_empty_params(mocker) -> None:
    get = mocker.patch.object(civitai._requests, "get",
                              return_value=_resp(200, {"items": [], "metadata": {}}))
    out = civitai.search_models()
    params = get.call_args.kwargs["params"]
    assert get.call_args.kwargs["headers"] == {}
    assert set(params) == {"limit"}
    assert out == {"items": [], "next_cursor": None}


def test_search_passes_cursor(mocker) -> None:
    get = mocker.patch.object(civitai._requests, "get",
                              return_value=_resp(200, {"items": [], "metadata": {}}))
    civitai.search_models(query="x", cursor="abc|123")
    assert get.call_args.kwargs["params"]["cursor"] == "abc|123"


def test_version_files_and_download_entry() -> None:
    item = civitai.normalize_model(MODEL, detailed=True)
    v2, v1 = item["versions"]
    assert v2["id"] == "9001"
    assert v2["family"] == "Flux"
    assert v1["family"] == "SDXL"
    model_file, training = v2["files"]
    assert model_file == {
        "name": "cinelight_v2.safetensors",
        "size_bytes": 1024 * 1024,
        "sha256": "abcdef0123",
        "download_url": "https://civitai.com/api/download/models/9001",
        "primary": True,
    }
    # Download entry matches BlockFlow's preset `{source, url, dest}` shape and
    # the civitai URL pattern preset_resolver expects.
    assert v2["download"] == {
        "source": "civitai",
        "url": "https://civitai.com/api/download/models/9001",
        "dest": "loras/cinelight_v2.safetensors",
        "sha256": "abcdef0123",
    }
    # Version without files has nothing to download.
    assert v1["download"] is None
    assert item["description"] == "<p>Moody light.</p>"


def test_get_model_detailed(mocker) -> None:
    get = mocker.patch.object(civitai._requests, "get", return_value=_resp(200, MODEL))
    item = civitai.get_model(101)
    assert get.call_args.args[0] == "https://civitai.com/api/v1/models/101"
    assert item["versions"][0]["files"][0]["name"] == "cinelight_v2.safetensors"


def test_unknown_type_has_no_dest() -> None:
    raw = {**MODEL, "type": "Workflows"}
    item = civitai.normalize_model(raw, detailed=True)
    assert item["type"] == "workflow"
    assert item["versions"][0]["download"]["dest"] is None


def test_model_without_versions_is_tolerated() -> None:
    item = civitai.normalize_model({"id": 5, "name": "Empty", "type": "Checkpoint"})
    assert item["base_model"] is None
    assert item["family"] == "Other"
    assert item["trigger_words"] == []
    assert item["thumbnail"] is None


@pytest.mark.parametrize("status", [401, 404, 429, 500])
def test_http_errors_raise_upstream_error(mocker, status: int) -> None:
    mocker.patch.object(civitai._requests, "get", return_value=_resp(status, {"error": "x"}))
    with pytest.raises(CatalogUpstreamError) as exc:
        civitai.search_models(query="x")
    assert exc.value.status == status
    assert exc.value.source == "civitai"


def test_network_error_raises_upstream_error(mocker) -> None:
    mocker.patch.object(civitai._requests, "get", side_effect=OSError("connection reset"))
    with pytest.raises(CatalogUpstreamError) as exc:
        civitai.get_model(1)
    assert exc.value.status is None


IMAGE = {
    "id": 77,
    "url": "https://image.civitai.com/x/img.jpeg",
    "type": "image",
    "nsfwLevel": 1,
    "baseModel": "Flux.1 D",
    "meta": {
        "prompt": "a cat in cinelight",
        "negativePrompt": "blurry",
        "seed": 42,
        "steps": 20,
        "cfgScale": 3.5,
        "sampler": "Euler",
        "scheduler": "simple",
        "clipSkip": 2,
        "Size": "832x1216",
        "Model": "flux1-dev",
        "resources": [
            {"type": "lora", "name": "cinelight", "weight": 0.8, "hash": "aa11"},
            {"type": "model", "name": "flux1-dev", "hash": "bb22"},
        ],
        "civitaiResources": [
            {"type": "lora", "modelVersionId": 9001, "weight": 0.7},
            {"type": "checkpoint", "modelVersionId": 1},
        ],
    },
}


def test_search_images_requests_meta_and_extracts_prompts(mocker) -> None:
    get = mocker.patch.object(civitai._requests, "get", return_value=_resp(
        200, {"items": [IMAGE, {"id": 78, "url": "u", "meta": None}], "metadata": {"nextCursor": "n"}}
    ))
    out = civitai.search_images(model_version_id=9001, base_models=["Flux.1 D"], limit=5)

    assert get.call_args.args[0] == "https://civitai.com/api/v1/images"
    params = get.call_args.kwargs["params"]
    assert params["withMeta"] == "true"
    assert params["modelVersionId"] == 9001
    assert params["baseModels"] == ["Flux.1 D"]
    assert out["next_cursor"] == "n"

    img, bare = out["items"]
    assert img["prompt"] == "a cat in cinelight"
    assert img["negative_prompt"] == "blurry"
    assert img["media"] == "image"
    assert img["family"] == "Flux"
    assert img["settings"] == {"seed": 42, "steps": 20, "cfg_scale": 3.5,
                               "sampler": "Euler", "scheduler": "simple", "clip_skip": 2,
                               "width": 832, "height": 1216, "model": "flux1-dev"}
    assert img["loras"] == [
        {"name": "cinelight", "weight": 0.8, "hash": "aa11", "model_version_id": None},
        {"name": None, "weight": 0.7, "hash": None, "model_version_id": 9001},
    ]
    assert bare["prompt"] is None
    assert bare["loras"] == []


def test_search_images_only_with_prompt_filters_locally(mocker) -> None:
    mocker.patch.object(civitai._requests, "get", return_value=_resp(
        200, {"items": [IMAGE, {"id": 78, "url": "u", "meta": {}}], "metadata": {}}
    ))
    out = civitai.search_images(only_with_prompt=True)
    assert [i["id"] for i in out["items"]] == ["77"]


def test_video_image_media() -> None:
    img = civitai.normalize_image({"id": 1, "url": "u.mp4", "type": "video", "meta": {}})
    assert img["media"] == "video"


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        ("832x1216", {"width": 832, "height": 1216}),
        ("1024 X 1024", {"width": 1024, "height": 1024}),
        ("832 x 480", {"width": 832, "height": 480}),
        ("832x", {}),
        ("abcxdef", {}),
        ("32x32", {}),          # below 64 px: not a real generation size
        ("9000x512", {}),       # above 8192 px
        (832, {}),              # not a string
        ("", {}),
    ],
)
def test_image_size_parsing(size, expected) -> None:
    img = civitai.normalize_image({"id": 1, "url": "u", "meta": {"Size": size}})
    assert {k: v for k, v in img["settings"].items() if k in ("width", "height")} == expected


def test_image_lowercase_size_key_and_clip_skip_as_string() -> None:
    img = civitai.normalize_image({"id": 1, "url": "u", "meta": {"size": "512x768", "clipSkip": "1"}})
    assert img["settings"] == {"width": 512, "height": 768, "clip_skip": 1}


def test_image_bad_clip_skip_is_dropped() -> None:
    img = civitai.normalize_image({"id": 1, "url": "u", "meta": {"clipSkip": "two"}})
    assert "clip_skip" not in img["settings"]
