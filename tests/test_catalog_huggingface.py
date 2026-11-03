"""Hugging Face catalog provider: request building + normalization.

HTTP is mocked at the curl_cffi boundary. Payload fixtures are hand-written
from the field names the Hub's /api/models endpoints return.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from backend.catalog import huggingface  # noqa: E402
from backend.catalog.errors import CatalogUpstreamError  # noqa: E402


def _resp(status: int, body) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    m.text = str(body)
    return m


REPO = {
    "id": "acme/wan-motion-lora",
    "author": "acme",
    "downloads": 900,
    "likes": 12,
    "pipeline_tag": "image-to-video",
    "tags": ["lora", "base_model:adapter:Wan-AI/Wan2.2-I2V-A14B", "license:apache-2.0"],
    "cardData": {"base_model": "Wan-AI/Wan2.2-I2V-A14B", "instance_prompt": "wmotion"},
    "siblings": [
        {"rfilename": "README.md"},
        {"rfilename": "preview.png"},
        {"rfilename": "wan_motion.safetensors", "size": 2048,
         "lfs": {"oid": "deadbeef", "size": 2048}},
        {"rfilename": "small.bin", "size": 10, "blobId": "sha1sha1"},
    ],
}


def test_search_builds_params_and_normalizes(mocker) -> None:
    get = mocker.patch.object(huggingface._requests, "get", return_value=_resp(200, [REPO]))
    out = huggingface.search_models(query="wan", filters=["lora"], limit=2, page=0, token="T")

    assert get.call_args.args[0] == "https://huggingface.co/api/models"
    params = get.call_args.kwargs["params"]
    assert params["search"] == "wan"
    assert params["filter"] == ["lora"]
    assert params["limit"] == 2
    assert params["p"] == 0
    assert params["full"] == "true"
    assert params["sort"] == "downloads"
    assert get.call_args.kwargs["headers"] == {"Authorization": "Bearer T"}

    # Page was full (2 requested, 1 returned) -> no next page.
    assert out["next_page"] is None
    (item,) = out["items"]
    assert item["source"] == "huggingface"
    assert item["id"] == "acme/wan-motion-lora"
    assert item["base_model"] == "Wan-AI/Wan2.2-I2V-A14B"
    assert item["family"] == "Wan"
    assert item["media"] == "video"
    assert item["type"] == "lora"
    assert item["trigger_words"] == ["wmotion"]
    assert item["creator"] == "acme"
    assert item["stats"] == {"downloads": 900, "likes": 12}
    assert item["thumbnail"] == "https://huggingface.co/acme/wan-motion-lora/resolve/main/preview.png"
    assert item["url"] == "https://huggingface.co/acme/wan-motion-lora"


def test_full_page_reports_next_page(mocker) -> None:
    mocker.patch.object(huggingface._requests, "get", return_value=_resp(200, [REPO, REPO]))
    out = huggingface.search_models(query="wan", limit=2, page=3)
    assert out["next_page"] == 4


def test_get_model_lists_model_files_with_sha256(mocker) -> None:
    get = mocker.patch.object(huggingface._requests, "get", return_value=_resp(200, REPO))
    item = huggingface.get_model("acme/wan-motion-lora")

    assert get.call_args.args[0] == "https://huggingface.co/api/models/acme/wan-motion-lora"
    assert get.call_args.kwargs["params"] == {"blobs": "true"}
    (version,) = item["versions"]
    assert version["id"] == "main"
    lora, small = version["files"]
    assert lora == {
        "name": "wan_motion.safetensors",
        "size_bytes": 2048,
        "sha256": "deadbeef",
        "download_url": "https://huggingface.co/acme/wan-motion-lora/resolve/main/wan_motion.safetensors",
        "primary": True,
    }
    # Non-LFS blobs carry a SHA-1, never reported as sha256.
    assert small["sha256"] is None
    assert small["primary"] is False
    assert version["download"] == {
        "source": "huggingface",
        "url": "https://huggingface.co/acme/wan-motion-lora/resolve/main/wan_motion.safetensors",
        "dest": "loras/wan_motion.safetensors",
        "sha256": "deadbeef",
    }


def test_files_in_subfolders_keep_their_path_in_url_but_flat_dest(mocker) -> None:
    repo = {**REPO, "siblings": [{"rfilename": "split_files/vae/wan_vae.safetensors", "size": 5,
                                  "lfs": {"oid": "ff"}}]}
    mocker.patch.object(huggingface._requests, "get", return_value=_resp(200, repo))
    item = huggingface.get_model("acme/wan-motion-lora", type_hint="vae")
    dl = item["versions"][0]["download"]
    assert dl["url"].endswith("/resolve/main/split_files/vae/wan_vae.safetensors")
    assert dl["dest"] == "vae/wan_vae.safetensors"


def test_unknown_type_without_hint_has_no_dest(mocker) -> None:
    repo = {**REPO, "tags": [], "pipeline_tag": "text-to-image"}
    mocker.patch.object(huggingface._requests, "get", return_value=_resp(200, repo))
    item = huggingface.get_model("acme/wan-motion-lora")
    assert item["type"] == "other"
    assert item["versions"][0]["download"]["dest"] is None


@pytest.mark.parametrize(
    ("card", "tags", "expected"),
    [
        ({"base_model": ["black-forest-labs/FLUX.1-dev"]}, [], "black-forest-labs/FLUX.1-dev"),
        ({}, ["base_model:finetune:stabilityai/stable-diffusion-xl-base-1.0"],
         "stabilityai/stable-diffusion-xl-base-1.0"),
        ({}, [], None),
    ],
)
def test_base_model_from_card_or_tags(card, tags, expected) -> None:
    item = huggingface.normalize_model({"id": "a/b", "cardData": card, "tags": tags})
    assert item["base_model"] == expected


@pytest.mark.parametrize("repo_id", ["", "../etc", "a/b/c", "a b/c"])
def test_get_model_rejects_bad_repo_ids(repo_id: str) -> None:
    with pytest.raises(ValueError):
        huggingface.get_model(repo_id)


def test_http_error_raises_upstream_error(mocker) -> None:
    mocker.patch.object(huggingface._requests, "get", return_value=_resp(401, {"error": "gated"}))
    with pytest.raises(CatalogUpstreamError) as exc:
        huggingface.get_model("acme/private")
    assert exc.value.status == 401
    assert exc.value.source == "huggingface"
