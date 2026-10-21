from __future__ import annotations

import importlib.util
import json
import sys
import threading
from email.message import Message
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import comfygen_remote, config, db, services, settings_store, state  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "comfy_gen_block_remote",
    ROOT / "custom_blocks" / "comfy_gen" / "backend.block.py",
)
block = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = block
_spec.loader.exec_module(block)


class FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json"):
        self.body = body
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def read(self, *_args):
        return self.body


def test_request_json_uses_bearer_auth_and_runpod_compatible_paths(monkeypatch):
    captured = {}

    def fake_open(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        captured["method"] = req.method
        captured["timeout"] = timeout
        return FakeResponse(b'{"id":"remote-1"}')

    monkeypatch.setattr(comfygen_remote, "_urlopen", fake_open)

    result = comfygen_remote.request_json(
        "https://gpu.example.com:8000/",
        "remote-token",
        "POST",
        "/run",
        {"input": {"workflow": {"1": {"class_type": "KSampler"}}}},
    )

    assert result == {"id": "remote-1"}
    assert captured == {
        "url": "https://gpu.example.com:8000/run",
        "headers": {
            "Authorization": "Bearer remote-token",
            "Content-type": "application/json",
        },
        "method": "POST",
        "timeout": 30,
    }


def test_upload_input_sends_bytes_with_field_and_filename(monkeypatch, tmp_path):
    source = tmp_path / "reference image.png"
    source.write_bytes(b"image-data")
    captured = {}

    def fake_open(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        captured["data"] = req.data
        captured["timeout"] = timeout
        return FakeResponse(b'{"name":"reference.png","subfolder":"","field":"image"}')

    monkeypatch.setattr(comfygen_remote, "_urlopen", fake_open)

    result = comfygen_remote.upload_input(
        "https://gpu.example.com:8000", "remote-token", "image", source,
    )

    assert result == {"name": "reference.png", "subfolder": "", "field": "image"}
    assert captured["url"] == "https://gpu.example.com:8000/upload/image"
    assert captured["headers"]["Authorization"] == "Bearer remote-token"
    assert captured["headers"]["X-filename"] == "reference image.png"
    assert captured["data"] == b"image-data"
    assert captured["timeout"] == 120


def test_download_output_returns_bytes_and_content_type(monkeypatch):
    captured = {}

    def fake_open(req, timeout):
        captured["url"] = req.full_url
        captured["headers"] = req.headers
        return FakeResponse(b"output-bytes", "video/mp4")

    monkeypatch.setattr(comfygen_remote, "_urlopen", fake_open)

    result = comfygen_remote.download_output(
        "https://gpu.example.com:8000", "remote-token", "remote-1", 0,
    )

    assert result == (b"output-bytes", "video/mp4")
    assert captured["url"] == "https://gpu.example.com:8000/outputs/remote-1/0"
    assert captured["headers"]["Authorization"] == "Bearer remote-token"


def test_dedicated_job_uploads_inputs_polls_and_persists_local_output(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")
    settings_store.init_db()
    db.init_db()
    settings_store.set_credential("comfygen_remote_token", "remote-token")
    settings_store.set_comfygen_runtime(
        runtime_kind="dedicated",
        base_url="https://gpu.example.com:8000",
    )
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    monkeypatch.setattr(config, "LOCAL_OUTPUT_DIR", output_dir)
    monkeypatch.setattr(state, "JOBS", {})
    monkeypatch.setattr(state, "JOBS_LOCK", threading.Lock())

    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
        "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
    }))
    source_path = tmp_path / "reference.png"
    source_path.write_bytes(b"input-bytes")
    state.JOBS["local-1"] = {"job_id": "local-1", "status": "QUEUED"}
    calls = []

    def fake_json(base_url, token, method, path, payload=None, **kwargs):
        calls.append((method, path, payload))
        if path == "/run":
            return {"id": "dedicated-1"}
        if path == "/status/dedicated-1":
            return {
                "job_id": "dedicated-1",
                "status": "COMPLETED",
                "output": {
                    "ok": True,
                    "output": {"files": [{
                        "index": 0,
                        "filename": "result.png",
                        "subfolder": "",
                        "type": "output",
                        "media_type": "image",
                    }]},
                },
            }
        raise AssertionError(path)

    monkeypatch.setattr(comfygen_remote, "upload_input", lambda *_args: {
        "name": "reference.png", "subfolder": "", "field": "image",
    })
    monkeypatch.setattr(comfygen_remote, "request_json", fake_json)
    monkeypatch.setattr(comfygen_remote, "download_output", lambda *_args: (b"output-bytes", "image/png"))
    monkeypatch.setattr(block.time, "sleep", lambda _seconds: None)
    embedded_metadata = []
    monkeypatch.setattr(block.media_meta, "embed_metadata", lambda _path, metadata: embedded_metadata.append(metadata))

    block._run_dedicated_comfy_job(
        "local-1", str(workflow_path), {"1": str(source_path)}, {"2.filename_prefix": "test"},
    )

    job = services._job_snapshot("local-1")
    assert calls, job.get("error")
    run_payload = calls[0][2]["input"]
    assert run_payload["file_inputs"] == {
        "1": {"name": "reference.png", "subfolder": "", "field": "image"},
    }
    assert run_payload["workflow"]["1"]["inputs"]["image"] == "reference.png"
    assert job["remote_job_id"] == "dedicated-1"
    assert job["status"] == "COMPLETED"
    assert Path(job["local_file"]).read_bytes() == b"output-bytes"
    assert Path(job["local_file"]).parent == config.LOCAL_OUTPUT_DIR
    assert job["local_image_url"].startswith("/outputs/")
    assert embedded_metadata[0]["software"] == "ComfyUI (ComfyGen dedicated host)"


def test_cancel_dedicated_job_uses_compatibility_server(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "settings.db")
    settings_store.init_db()
    settings_store.set_credential("comfygen_remote_token", "remote-token")
    settings_store.set_comfygen_runtime(
        runtime_kind="dedicated",
        base_url="https://gpu.example.com:8000",
    )
    monkeypatch.setattr(state, "JOBS", {
        "local-1": {
            "job_id": "local-1",
            "status": "RUNNING",
            "remote_job_id": "dedicated-1",
            "runtime_kind": "dedicated",
        },
    })
    monkeypatch.setattr(state, "JOBS_LOCK", threading.Lock())
    calls = []
    monkeypatch.setattr(comfygen_remote, "request_json", lambda *args, **kwargs: calls.append((args, kwargs)) or {
        "job_id": "dedicated-1", "status": "cancelled",
    })
    monkeypatch.setattr(block.subprocess, "run", lambda *_args, **_kwargs: (_ for _ in ()).throw(
        AssertionError("serverless CLI must not handle dedicated cancellation"),
    ))
    app = FastAPI()
    app.include_router(block.router)

    response = TestClient(app).post("/cancel/local-1")

    assert response.status_code == 200
    assert response.json()["remote_cancel_status"] == "ok"
    assert calls[0][0][2:4] == ("POST", "/cancel")
    assert calls[0][0][4] == {"job_id": "dedicated-1"}


def test_dedicated_inventory_refresh_updates_existing_cache(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "settings.db")
    settings_store.init_db()
    settings_store.set_credential("comfygen_remote_token", "remote-token")
    settings_store.set_comfygen_runtime(
        runtime_kind="dedicated",
        base_url="https://gpu.example.com:8000",
    )
    monkeypatch.setattr(config, "COMFY_GEN_INFO_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(block.config, "COMFY_GEN_INFO_CACHE_PATH", tmp_path / "cache.json")
    monkeypatch.setattr(block, "_cache", {
        "samplers": [], "schedulers": [], "loras": [], "lora_details": [], "fetched_at": None,
    })
    calls = []
    monkeypatch.setattr(comfygen_remote, "request_json", lambda *args, **kwargs: calls.append((args, kwargs)) or {
        "ok": True,
        "samplers": ["euler"],
        "schedulers": ["normal"],
        "models": {"loras": ["style.safetensors"]},
    })

    block._run_remote_refresh("https://gpu.example.com:8000", "remote-token")

    assert calls[0][0][2:4] == ("GET", "/inventory")
    assert block._cache["samplers"] == ["euler"]
    assert block._cache["schedulers"] == ["normal"]
    assert block._cache["loras"] == ["style.safetensors"]
    assert block._cache["lora_details"] == [{"filename": "style.safetensors"}]
    assert json.loads((tmp_path / "cache.json").read_text())["loras"] == [
        {"filename": "style.safetensors"},
    ]


def test_cancel_during_upload_does_not_submit_remote_job(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "settings.db")
    settings_store.init_db()
    settings_store.set_credential("comfygen_remote_token", "remote-token")
    settings_store.set_comfygen_runtime(
        runtime_kind="dedicated",
        base_url="https://gpu.example.com:8000",
    )
    monkeypatch.setattr(state, "JOBS", {})
    monkeypatch.setattr(state, "JOBS_LOCK", threading.Lock())
    workflow_path = tmp_path / "workflow.json"
    workflow_path.write_text(json.dumps({
        "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    }))
    source_path = tmp_path / "reference.png"
    source_path.write_bytes(b"input-bytes")
    cancel_event = threading.Event()
    state.JOBS["local-1"] = {
        "job_id": "local-1", "status": "QUEUED", "_cancel_event": cancel_event,
    }
    app = FastAPI()
    app.include_router(block.router)
    cancel_client = TestClient(app)
    submitted = []

    def cancel_during_upload(*_args):
        assert cancel_client.post("/cancel/local-1").status_code == 200
        return {"name": "reference.png", "subfolder": "", "field": "image"}

    monkeypatch.setattr(comfygen_remote, "upload_input", cancel_during_upload)
    monkeypatch.setattr(comfygen_remote, "request_json", lambda *args, **kwargs: submitted.append(args))

    block._run_dedicated_comfy_job("local-1", str(workflow_path), {"1": str(source_path)})

    assert cancel_event.is_set()
    assert submitted == []
