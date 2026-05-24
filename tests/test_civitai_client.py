"""HTTP client tests for the CivitAI public API (sgs-ui-eqc.1).

All HTTP calls mocked at the boundary (curl_cffi.requests). No live network.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from backend import civitai_client  # noqa: E402


def _resp(status: int, body: dict) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    if status >= 400:
        m.raise_for_status.side_effect = RuntimeError(f"http {status}")
    else:
        m.raise_for_status.return_value = None
    return m


def test_fetch_version_extracts_core_fields(mocker) -> None:
    payload = {
        "id": 67890,
        "modelId": 12345,
        "name": "v2",
        "baseModel": "Flux.1 D",
        "trainedWords": ["trigger one", "trigger two"],
        "files": [
            {"primary": True, "name": "char_v2.safetensors", "sizeKB": 144000.5,
             "downloadUrl": "https://civitai.com/api/download/models/67890"},
        ],
    }
    mocker.patch.object(civitai_client._requests, "get",
                        return_value=_resp(200, payload))

    meta = civitai_client.fetch_version_metadata(67890)
    assert meta.version_id == 67890
    assert meta.model_id == 12345
    assert meta.base_model == "Flux.1 D"
    assert meta.trigger_words == ["trigger one", "trigger two"]
    assert meta.primary_file_name == "char_v2.safetensors"
    assert meta.primary_file_size_kb == 144000.5
    assert meta.download_url == "https://civitai.com/api/download/models/67890"


def test_fetch_version_handles_missing_trained_words(mocker) -> None:
    payload = {"id": 1, "modelId": 2, "files": [{"primary": True, "name": "a.safetensors"}]}
    mocker.patch.object(civitai_client._requests, "get",
                        return_value=_resp(200, payload))

    meta = civitai_client.fetch_version_metadata(1)
    assert meta.trigger_words == []
    assert meta.base_model is None


def test_fetch_version_sends_bearer_when_api_key_set(mocker) -> None:
    payload = {"id": 1, "modelId": 2, "files": []}
    get_mock = mocker.patch.object(civitai_client._requests, "get",
                                   return_value=_resp(200, payload))

    civitai_client.fetch_version_metadata(1, api_key="abc123")
    _, kwargs = get_mock.call_args
    assert kwargs["headers"] == {"Authorization": "Bearer abc123"}


def test_fetch_version_anonymous_when_no_key(mocker) -> None:
    payload = {"id": 1, "modelId": 2, "files": []}
    get_mock = mocker.patch.object(civitai_client._requests, "get",
                                   return_value=_resp(200, payload))

    civitai_client.fetch_version_metadata(1)
    _, kwargs = get_mock.call_args
    assert kwargs["headers"] == {}


def test_fetch_version_404_raises(mocker) -> None:
    mocker.patch.object(civitai_client._requests, "get",
                        return_value=_resp(404, {}))
    with pytest.raises(RuntimeError):
        civitai_client.fetch_version_metadata(99999999)


def test_fetch_latest_version_uses_first_published(mocker) -> None:
    payload = {
        "id": 12345,
        "modelVersions": [
            {"id": 999, "modelId": 12345, "baseModel": "SDXL", "trainedWords": ["latest"],
             "files": [{"primary": True, "name": "latest.safetensors", "sizeKB": 100}]},
            {"id": 998, "modelId": 12345, "baseModel": "SDXL", "trainedWords": ["old"],
             "files": []},
        ],
    }
    mocker.patch.object(civitai_client._requests, "get",
                        return_value=_resp(200, payload))

    meta = civitai_client.fetch_latest_version_for_model(12345)
    assert meta.version_id == 999
    assert meta.trigger_words == ["latest"]


def test_fetch_latest_version_no_versions_raises(mocker) -> None:
    payload = {"id": 12345, "modelVersions": []}
    mocker.patch.object(civitai_client._requests, "get",
                        return_value=_resp(200, payload))

    with pytest.raises(civitai_client.CivitAIRefError):
        civitai_client.fetch_latest_version_for_model(12345)
