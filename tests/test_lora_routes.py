"""HTTP route tests for /api/loras/* (sgs-ui-eqc.1).

Subprocess calls to comfy-gen are mocked at module-level helper boundaries.
CivitAI API calls mocked via the civitai_client._requests handle.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend import civitai_client, config, lora_metadata, lora_routes, settings_store  # noqa: E402


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(config, "COMFY_GEN_INFO_CACHE_PATH",
                        tmp_path / "comfy_gen_info_cache.json")
    monkeypatch.setattr(lora_metadata, "DB_PATH", tmp_path / "run_history.db")
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "run_history.db")
    settings_store.init_db()
    lora_metadata.init_db()

    app = FastAPI()
    app.include_router(lora_routes.router)

    # Reset module-level concurrency state between tests.
    lora_routes._download_in_flight = False

    return TestClient(app)


def _seed_cache(tmp_path, filenames, fetched_at=None):
    """Write the shared comfy_gen info cache file with the given LoRA list."""
    import time as _time
    path = tmp_path / "comfy_gen_info_cache.json"
    path.write_text(json.dumps({
        "samplers": [], "schedulers": [],
        "loras": list(filenames),
        "fetched_at": fetched_at if fetched_at is not None else _time.time(),
    }))


def _configure_endpoint() -> None:
    settings_store.set_endpoint(type="comfygen", endpoint_id="ep-test-123", volume_id="vol-1")


def _resp(status: int, body: dict) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json.return_value = body
    m.raise_for_status.return_value = None if status < 400 else None
    if status >= 400:
        m.raise_for_status.side_effect = RuntimeError(f"http {status}")
    return m


# ---- GET /api/loras ----

def test_list_returns_409_when_no_endpoint(client) -> None:
    r = client.get("/api/loras")
    assert r.status_code == 409


def test_list_merges_cached_volume_with_db_and_prunes_orphans(client, tmp_path) -> None:
    _configure_endpoint()
    lora_metadata.upsert(filename="known.safetensors", source="civitai", source_id="1",
                         trigger_words=["trig"])
    lora_metadata.upsert(filename="orphan.safetensors", source="civitai", source_id="2")
    _seed_cache(tmp_path, ["known.safetensors", "legacy.safetensors"])

    r = client.get("/api/loras")
    assert r.status_code == 200
    data = r.json()
    by_name = {row["filename"]: row for row in data["loras"]}
    assert set(by_name.keys()) == {"known.safetensors", "legacy.safetensors"}
    assert by_name["known.safetensors"]["source"] == "civitai"
    assert by_name["known.safetensors"]["trigger_words"] == ["trig"]
    assert by_name["legacy.safetensors"]["source"] == "unknown"
    assert data["pruned"] == ["orphan.safetensors"]
    assert lora_metadata.get("orphan.safetensors") is None
    assert data["stale"] is False
    assert data["fetched_at"] is not None


def test_list_marks_stale_when_no_cache(client) -> None:
    _configure_endpoint()
    r = client.get("/api/loras")
    assert r.status_code == 200
    data = r.json()
    assert data["loras"] == []
    assert data["stale"] is True
    assert data["fetched_at"] is None


def test_list_marks_stale_when_cache_older_than_24h(client, tmp_path) -> None:
    _configure_endpoint()
    _seed_cache(tmp_path, ["a.safetensors"], fetched_at=0.0)  # epoch
    r = client.get("/api/loras")
    assert r.json()["stale"] is True


def test_sync_shells_out_and_refreshes_cache(client, monkeypatch, tmp_path) -> None:
    _configure_endpoint()
    # Stub the cold-path subprocess so test stays fast and offline.
    monkeypatch.setattr(lora_routes, "_fetch_loras_from_comfygen",
                        lambda eid: ["fresh.safetensors", "newer.safetensors"])

    r = client.post("/api/loras/sync")
    assert r.status_code == 200
    data = r.json()
    assert {row["filename"] for row in data["loras"]} == {"fresh.safetensors", "newer.safetensors"}
    assert data["stale"] is False


# ---- POST /api/loras/delete ----

def test_delete_batch_drops_db_rows_for_deleted_only(client, monkeypatch) -> None:
    _configure_endpoint()
    for fn in ("a.safetensors", "b.safetensors", "c.safetensors"):
        lora_metadata.upsert(filename=fn, source="civitai", source_id="1")

    def fake_delete(filenames, eid):
        # b fails, others succeed
        return [
            {"path": f"/runpod-volume/ComfyUI/models/loras/{fn}",
             "deleted": fn != "b.safetensors",
             "error": "in use" if fn == "b.safetensors" else None}
            for fn in filenames
        ]

    monkeypatch.setattr(lora_routes, "_delete_subprocess", fake_delete)

    r = client.post("/api/loras/delete",
                    json={"filenames": ["a.safetensors", "b.safetensors", "c.safetensors"]})
    assert r.status_code == 207  # partial failure
    data = r.json()
    by_name = {row["filename"]: row for row in data["results"]}
    assert by_name["a.safetensors"]["deleted"] is True
    assert by_name["b.safetensors"]["deleted"] is False
    assert by_name["b.safetensors"]["error"] == "in use"
    assert by_name["c.safetensors"]["deleted"] is True

    assert lora_metadata.get("a.safetensors") is None
    assert lora_metadata.get("b.safetensors") is not None  # NOT dropped
    assert lora_metadata.get("c.safetensors") is None


def test_delete_all_ok_returns_200(client, monkeypatch) -> None:
    _configure_endpoint()
    lora_metadata.upsert(filename="a.safetensors", source="civitai", source_id="1")

    monkeypatch.setattr(lora_routes, "_delete_subprocess",
                        lambda fns, eid: [{"path": f"/runpod-volume/ComfyUI/models/loras/{fn}",
                                            "deleted": True} for fn in fns])

    r = client.post("/api/loras/delete", json={"filenames": ["a.safetensors"]})
    assert r.status_code == 200


def test_delete_empty_filenames_rejected(client) -> None:
    _configure_endpoint()
    r = client.post("/api/loras/delete", json={"filenames": []})
    assert r.status_code == 400


def test_delete_409_when_no_endpoint(client) -> None:
    r = client.post("/api/loras/delete", json={"filenames": ["a.safetensors"]})
    assert r.status_code == 409


def test_delete_removes_filenames_from_shared_cache(client, monkeypatch, tmp_path) -> None:
    """Successful deletes must update the shared comfy_gen cache so the
    ComfyGen block's LoRA dropdown reflects the new state immediately."""
    _configure_endpoint()
    _seed_cache(tmp_path, ["keep.safetensors", "drop.safetensors"])
    lora_metadata.upsert(filename="drop.safetensors", source="civitai", source_id="1")

    monkeypatch.setattr(lora_routes, "_delete_subprocess",
                        lambda fns, eid: [{"path": f"/runpod-volume/ComfyUI/models/loras/{fn}",
                                            "deleted": True} for fn in fns])

    client.post("/api/loras/delete", json={"filenames": ["drop.safetensors"]})

    cached = json.loads((tmp_path / "comfy_gen_info_cache.json").read_text())["loras"]
    assert "drop.safetensors" not in cached
    assert "keep.safetensors" in cached


def test_delete_failed_rows_stay_in_cache(client, monkeypatch, tmp_path) -> None:
    _configure_endpoint()
    _seed_cache(tmp_path, ["a.safetensors", "b.safetensors"])

    monkeypatch.setattr(lora_routes, "_delete_subprocess",
                        lambda fns, eid: [
                            {"path": "/runpod-volume/ComfyUI/models/loras/a.safetensors", "deleted": True},
                            {"path": "/runpod-volume/ComfyUI/models/loras/b.safetensors",
                             "deleted": False, "error": "in use"},
                        ])

    client.post("/api/loras/delete", json={"filenames": ["a.safetensors", "b.safetensors"]})

    cached = json.loads((tmp_path / "comfy_gen_info_cache.json").read_text())["loras"]
    assert "a.safetensors" not in cached
    assert "b.safetensors" in cached


# ---- POST /api/loras/download ----

def test_civitai_download_persists_metadata(client, monkeypatch, mocker) -> None:
    _configure_endpoint()
    monkeypatch.setattr(config, "CIVITAI_API_KEY", "")

    payload = {
        "id": 67890, "modelId": 12345, "baseModel": "Flux.1 D",
        "trainedWords": ["trigger one"],
        "files": [{"primary": True, "name": "char_v2.safetensors", "sizeKB": 100.0}],
    }
    mocker.patch.object(civitai_client._requests, "get",
                        return_value=_resp(200, payload))

    dl_calls = []
    def fake_download(entries, eid):
        dl_calls.append((entries, eid))
        return {"ok": True}
    monkeypatch.setattr(lora_routes, "_download_subprocess", fake_download)

    r = client.post("/api/loras/download",
                    json={"source": "civitai", "version_id": 67890})
    assert r.status_code == 200
    assert r.json() == {"ok": True, "filename": "char_v2.safetensors"}
    assert dl_calls[0][0] == [{"source": "civitai", "version_id": 67890, "dest": "loras"}]

    row = lora_metadata.get("char_v2.safetensors")
    assert row is not None
    assert row["source"] == "civitai"
    assert row["source_id"] == "67890"
    assert row["base_model"] == "Flux.1 D"
    assert row["trigger_words"] == ["trigger one"]
    assert row["size_bytes"] == 100 * 1024


def test_civitai_download_succeeds_when_metadata_fetch_fails(client, monkeypatch, mocker) -> None:
    _configure_endpoint()
    monkeypatch.setattr(config, "CIVITAI_API_KEY", "")
    mocker.patch.object(civitai_client._requests, "get",
                        side_effect=RuntimeError("network down"))
    monkeypatch.setattr(lora_routes, "_download_subprocess",
                        lambda entries, eid: {"ok": True})

    r = client.post("/api/loras/download",
                    json={"source": "civitai", "version_id": 99999, "filename": "fallback.safetensors"})
    assert r.status_code == 200
    row = lora_metadata.get("fallback.safetensors")
    assert row["source"] == "civitai"
    assert row["source_id"] == "99999"
    assert row["trigger_words"] == []
    assert row["base_model"] is None


def test_url_download_detects_huggingface(client, monkeypatch) -> None:
    _configure_endpoint()
    monkeypatch.setattr(lora_routes, "_download_subprocess",
                        lambda entries, eid: {"ok": True})

    r = client.post("/api/loras/download",
                    json={"source": "url",
                          "url": "https://huggingface.co/foo/bar/resolve/main/model.safetensors"})
    assert r.status_code == 200
    row = lora_metadata.get("model.safetensors")
    assert row["source"] == "hf"
    assert row["source_id"] == "https://huggingface.co/foo/bar/resolve/main/model.safetensors"
    assert row["trigger_words"] == []


def test_url_download_generic_url(client, monkeypatch) -> None:
    _configure_endpoint()
    monkeypatch.setattr(lora_routes, "_download_subprocess",
                        lambda entries, eid: {"ok": True})

    r = client.post("/api/loras/download",
                    json={"source": "url", "url": "https://example.com/some/path/x.safetensors"})
    assert r.status_code == 200
    row = lora_metadata.get("x.safetensors")
    assert row["source"] == "url"


def test_download_appends_filename_to_shared_cache(client, monkeypatch, tmp_path) -> None:
    _configure_endpoint()
    _seed_cache(tmp_path, ["existing.safetensors"])
    monkeypatch.setattr(lora_routes, "_download_subprocess",
                        lambda entries, eid: {"ok": True})

    client.post("/api/loras/download",
                json={"source": "url", "url": "https://example.com/new.safetensors"})

    cached = json.loads((tmp_path / "comfy_gen_info_cache.json").read_text())["loras"]
    assert "new.safetensors" in cached
    assert "existing.safetensors" in cached


def test_download_concurrent_returns_409(client, monkeypatch) -> None:
    _configure_endpoint()
    lora_routes._download_in_flight = True
    try:
        r = client.post("/api/loras/download",
                        json={"source": "url", "url": "https://x/a.safetensors"})
        assert r.status_code == 409
    finally:
        lora_routes._download_in_flight = False


def test_download_409_when_no_endpoint(client) -> None:
    r = client.post("/api/loras/download",
                    json={"source": "civitai", "version_id": 1})
    assert r.status_code == 409


def test_download_unknown_source_rejected(client, monkeypatch) -> None:
    _configure_endpoint()
    r = client.post("/api/loras/download", json={"source": "ftp", "url": "ftp://x"})
    assert r.status_code == 400


# ---- POST /api/loras/set-source ----

def test_set_source_civitai_fetches_metadata(client, monkeypatch, mocker) -> None:
    _configure_endpoint()
    monkeypatch.setattr(config, "CIVITAI_API_KEY", "")
    payload = {
        "id": 555, "modelId": 1, "baseModel": "SDXL",
        "trainedWords": ["wow"],
        "files": [{"primary": True, "name": "existing.safetensors", "sizeKB": 50}],
    }
    mocker.patch.object(civitai_client._requests, "get",
                        return_value=_resp(200, payload))

    r = client.post("/api/loras/set-source",
                    json={"filename": "existing.safetensors", "source": "civitai", "source_id": "555"})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["lora"]["source"] == "civitai"
    assert body["lora"]["trigger_words"] == ["wow"]
    assert body["lora"]["base_model"] == "SDXL"


def test_set_source_url_persists_without_fetch(client) -> None:
    _configure_endpoint()
    r = client.post("/api/loras/set-source",
                    json={"filename": "x.safetensors", "source": "url",
                          "url": "https://example.com/x.safetensors"})
    assert r.status_code == 200
    row = lora_metadata.get("x.safetensors")
    assert row["source"] == "url"
    assert row["source_id"] == "https://example.com/x.safetensors"


def test_set_source_civitai_requires_integer_id(client) -> None:
    _configure_endpoint()
    r = client.post("/api/loras/set-source",
                    json={"filename": "x.safetensors", "source": "civitai", "source_id": "not-int"})
    assert r.status_code == 400


def test_set_source_invalid_source_rejected(client) -> None:
    r = client.post("/api/loras/set-source",
                    json={"filename": "x.safetensors", "source": "ftp"})
    assert r.status_code == 400
