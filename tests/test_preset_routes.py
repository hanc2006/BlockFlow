"""HTTP route tests for the preset installer manifest layer
(sgs-ui-wisp-las.3 Stage A).

Stage A scope: backend can fetch the public registry manifest, cache it for
1h (fallback to stale cache on network failure), list installed presets
from Settings. NO actual install yet — that's Stage B.

Tests mock the HTTP boundary (curl_cffi.requests) to verify caching,
TTL, fallback semantics, and route shape.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import preset_routes, settings_store  # noqa: E402


@pytest.fixture
def app(tmp_path, monkeypatch):
    db_path = tmp_path / "preset_test.db"
    monkeypatch.setattr(settings_store, "DB_PATH", db_path)
    settings_store.init_db()
    # Isolate the manifest cache to a per-test tmp file so cross-test bleed
    # can't happen.
    monkeypatch.setattr(preset_routes, "_CACHE_PATH", tmp_path / "manifest_cache.json")
    # Reset the in-memory cache between tests
    preset_routes._cache_reset()

    fastapi_app = FastAPI()
    fastapi_app.include_router(preset_routes.router)
    return fastapi_app


@pytest.fixture
def client(app):
    return TestClient(app)


def _manifest(presets: list[dict]) -> dict:
    return {"manifest_version": 1, "presets": presets}


def _qwen_preset_entry() -> dict:
    return {
        "id": "qwen-image-lighting",
        "name": "Qwen Image 2512 — Lightning 4-step",
        "description": "Test description",
        "comfygen_min_version": "0.2.0",
        "tags": ["t2i", "qwen"],
        "disk_size_estimate_gb": 65,
        "gpu_tier_hint": "recommended",
        "preset_url": "https://example/preset.json",
    }


def _mock_response(body: dict, status: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.text = json.dumps(body)
    m.json = lambda: body
    return m


# === manifest fetch =========================================================

def test_manifest_fetches_from_registry_url(client, mocker):
    """Happy path: GET /api/presets/manifest → fetch from registry URL,
    return the parsed manifest."""
    body = _manifest([_qwen_preset_entry()])
    fetch_mock = MagicMock(return_value=_mock_response(body))
    mocker.patch.object(preset_routes._cffi_requests, "get", fetch_mock)

    r = client.get("/api/presets/manifest")

    assert r.status_code == 200
    assert r.json() == body
    fetch_mock.assert_called_once()
    # Verify the canonical URL is used
    assert "raw.githubusercontent.com/Hearmeman24/blockflow-presets" in fetch_mock.call_args.args[0]
    assert fetch_mock.call_args.args[0].endswith("/main/manifest.json")


def test_manifest_caches_within_ttl(client, mocker):
    """Second fetch within TTL hits the cache, not the network."""
    body = _manifest([_qwen_preset_entry()])
    fetch_mock = MagicMock(return_value=_mock_response(body))
    mocker.patch.object(preset_routes._cffi_requests, "get", fetch_mock)

    r1 = client.get("/api/presets/manifest")
    r2 = client.get("/api/presets/manifest")

    assert r1.json() == r2.json() == body
    assert fetch_mock.call_count == 1, "second call should hit the cache"


def test_manifest_refreshes_after_ttl(client, mocker, monkeypatch):
    """Cache expires after the TTL; next call re-fetches."""
    body_v1 = _manifest([_qwen_preset_entry()])
    body_v2 = _manifest([{**_qwen_preset_entry(), "name": "Updated"}])

    responses = [_mock_response(body_v1), _mock_response(body_v2)]
    fetch_mock = MagicMock(side_effect=responses)
    mocker.patch.object(preset_routes._cffi_requests, "get", fetch_mock)
    # Tight TTL so we don't have to sleep an hour
    monkeypatch.setattr(preset_routes, "_CACHE_TTL_SEC", 1)

    r1 = client.get("/api/presets/manifest").json()
    time.sleep(1.2)
    r2 = client.get("/api/presets/manifest").json()

    assert r1["presets"][0]["name"] == "Qwen Image 2512 — Lightning 4-step"
    assert r2["presets"][0]["name"] == "Updated"
    assert fetch_mock.call_count == 2


def test_manifest_falls_back_to_stale_cache_on_network_error(client, mocker):
    """If GitHub is unreachable and we have a cached manifest, return it with
    a {cache: 'stale'} flag so the UI can show 'showing offline copy'."""
    body = _manifest([_qwen_preset_entry()])
    # First call succeeds, second errors
    responses = [_mock_response(body), Exception("network unreachable")]
    fetch_mock = MagicMock(side_effect=responses)
    mocker.patch.object(preset_routes._cffi_requests, "get", fetch_mock)

    client.get("/api/presets/manifest")  # populate cache

    # Force expiry so next call refetches
    preset_routes._force_cache_expired()
    r = client.get("/api/presets/manifest")

    assert r.status_code == 200
    payload = r.json()
    assert payload["presets"] == body["presets"]
    assert payload.get("cache") == "stale"


def test_manifest_returns_502_when_unreachable_and_no_cache(client, mocker):
    """No cache + network error → real 502 (UI shows 'cannot reach registry')."""
    fetch_mock = MagicMock(side_effect=Exception("network unreachable"))
    mocker.patch.object(preset_routes._cffi_requests, "get", fetch_mock)

    r = client.get("/api/presets/manifest")
    assert r.status_code == 502
    assert "registry" in r.json()["detail"].lower() or "unreachable" in r.json()["detail"].lower()


def test_manifest_force_refresh_bypasses_cache(client, mocker):
    """?refresh=1 ignores the in-memory cache and fetches from network."""
    body_v1 = _manifest([_qwen_preset_entry()])
    body_v2 = _manifest([{**_qwen_preset_entry(), "name": "Refreshed"}])
    responses = [_mock_response(body_v1), _mock_response(body_v2)]
    fetch_mock = MagicMock(side_effect=responses)
    mocker.patch.object(preset_routes._cffi_requests, "get", fetch_mock)

    client.get("/api/presets/manifest")
    r = client.get("/api/presets/manifest?refresh=1")

    assert r.json()["presets"][0]["name"] == "Refreshed"
    assert fetch_mock.call_count == 2


def test_manifest_returns_502_on_invalid_json_from_registry(client, mocker):
    """If the registry returns non-JSON (e.g. GitHub serving an error page),
    we shouldn't crash — return 502 with a clear message."""
    bad = MagicMock()
    bad.status_code = 200
    bad.text = "<html>not json</html>"
    bad.json = MagicMock(side_effect=ValueError("not json"))
    mocker.patch.object(preset_routes._cffi_requests, "get", MagicMock(return_value=bad))

    r = client.get("/api/presets/manifest")
    assert r.status_code == 502


# === installed presets list =================================================

def test_list_installed_empty(client):
    r = client.get("/api/presets/installed")
    assert r.status_code == 200
    assert r.json() == {"installed": []}


def test_list_installed_returns_settings_rows(client):
    """Pre-populate Settings as if Stage B's install had completed."""
    settings_store.record_installed_preset(
        preset_id="qwen-image-lighting",
        version="0.2.0",
        disk_size_gb=65,
        workflow_json='{"3": {"class_type": "KSampler"}}',
    )
    settings_store.record_installed_preset(
        preset_id="another-preset",
        version="0.1.0",
        disk_size_gb=15,
        workflow_json='{}',
    )

    r = client.get("/api/presets/installed")
    assert r.status_code == 200
    body = r.json()
    ids = sorted(p["preset_id"] for p in body["installed"])
    assert ids == ["another-preset", "qwen-image-lighting"]
    qwen = next(p for p in body["installed"] if p["preset_id"] == "qwen-image-lighting")
    assert qwen["version"] == "0.2.0"
    assert qwen["disk_size_gb"] == 65
    # workflow_json is NOT in the list response (would bloat); UI fetches detail separately
    assert "workflow_json" not in qwen


# === installed presets detail ===============================================

def test_get_installed_detail_returns_workflow_json(client):
    settings_store.record_installed_preset(
        preset_id="qwen-image-lighting",
        version="0.2.0",
        disk_size_gb=65,
        workflow_json='{"3": {"class_type": "KSampler"}}',
    )
    r = client.get("/api/presets/installed/qwen-image-lighting")
    assert r.status_code == 200
    body = r.json()
    assert body["preset_id"] == "qwen-image-lighting"
    assert body["workflow_json"] == {"3": {"class_type": "KSampler"}}


def test_get_installed_detail_404_when_missing(client):
    r = client.get("/api/presets/installed/never-installed")
    assert r.status_code == 404
