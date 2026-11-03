"""ComfyGen block with an attached persistent ComfyGen server.

/run must hand the job to _run_dedicated_comfy_job (the pod's compatibility
API) instead of the serverless comfy-gen CLI, and /download-models must
download missing models onto the pod.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import comfygen_pod_models, comfygen_remote, config, db, services, settings_store, state  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "comfy_gen_block_dedicated_dispatch",
    ROOT / "custom_blocks" / "comfy_gen" / "backend.block.py",
)
block = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = block
_spec.loader.exec_module(block)

WORKFLOW = {
    "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    "2": {"class_type": "SaveImage", "inputs": {"images": ["1", 0]}},
}


class RecordingExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def submit(self, fn, *args, **kwargs):
        self.calls.append((fn, args, kwargs))


@pytest.fixture
def env(monkeypatch, tmp_path):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "settings.db")
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "jobs.db")
    settings_store.init_db()
    db.init_db()
    monkeypatch.setattr(config, "JOB_HISTORY_PATH", tmp_path / "job_history.json")
    monkeypatch.setattr(state, "JOBS", {})
    monkeypatch.setattr(state, "JOBS_LOCK", threading.Lock())
    executor = RecordingExecutor()
    monkeypatch.setattr(state, "EXECUTOR", executor)
    app = FastAPI()
    app.include_router(block.router)
    return TestClient(app), executor, tmp_path


def _attach() -> None:
    settings_store.set_comfygen_runtime(runtime_kind="dedicated", base_url="http://127.0.0.1:8787")
    settings_store.set_credential("comfygen_remote_token", "tok")


def test_run_dispatches_to_dedicated_runner_without_endpoint(env):
    client, executor, tmp_path = env
    _attach()
    image = tmp_path / "ref.png"
    image.write_bytes(b"img")

    r = client.post("/run", json={
        "workflow": WORKFLOW,
        "file_inputs": {"1": {"media_url": str(image)}},
        "overrides": {"2.filename_prefix": "x"},
        "lock_seed": True,
    })

    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    ((fn, args, _kw),) = executor.calls
    assert fn is block._run_dedicated_comfy_job
    job_id, workflow_path, file_inputs, overrides, source, batch_id = args
    assert job_id == r.json()["job_id"]
    assert json.loads(Path(workflow_path).read_text()) == WORKFLOW
    assert file_inputs == {"1": str(image)}
    assert overrides == {"2.filename_prefix": "x"}
    assert (source, batch_id) == ("", "")


def test_run_uses_serverless_cli_when_no_server_attached(env):
    client, executor, _ = env
    r = client.post("/run", json={"workflow": WORKFLOW, "endpoint_id": "ep-1", "lock_seed": True})
    assert r.status_code == 200
    ((fn, args, _kw),) = executor.calls
    assert fn is block._run_comfy_job
    assert args[4] == "ep-1"


def test_download_models_goes_to_pod_in_dedicated_mode(env, monkeypatch):
    client, _, _ = env
    _attach()
    calls: list[tuple] = []

    def fake_download(models, on_progress=None):
        calls.append(models)
        if on_progress:
            on_progress({"status": "running", "files": [
                {"status": "downloading", "bytes_done": 50, "bytes_total": 100},
                {"status": "pending", "bytes_done": 0, "bytes_total": 100},
            ]})
        return (True, {"status": "completed"})

    monkeypatch.setattr(comfygen_pod_models, "download", fake_download)
    monkeypatch.setattr(block.comfy_gen_cli, "resolve_comfy_gen",
                        lambda: (_ for _ in ()).throw(AssertionError("CLI must not be used")))

    r = client.post("/download-models", json={"models": [
        {"download_url": "https://huggingface.co/o/r/resolve/main/up.safetensors", "save_path": "upscale_models"},
        {"download_url": "https://example.com/x/model.bin", "save_path": "default", "filename": "named.safetensors"},
        {"download_url": "", "save_path": "loras"},
    ]})

    assert r.json() == {"ok": True, "started": True, "count": 2}
    deadline = time.time() + 3
    while time.time() < deadline and not client.get("/download-status").json()["done"]:
        time.sleep(0.01)
    status = client.get("/download-status").json()
    assert status["done"] is True and status["error"] == ""
    assert status["status"] == "Downloaded 2 model(s)"
    assert calls == [[
        {"url": "https://huggingface.co/o/r/resolve/main/up.safetensors", "dest": "upscale_models/up.safetensors"},
        {"url": "https://example.com/x/model.bin", "dest": "checkpoints/named.safetensors"},
    ]]


def test_download_models_pod_failure_is_reported(env, monkeypatch):
    client, _, _ = env
    _attach()
    monkeypatch.setattr(comfygen_pod_models, "download", lambda models, on_progress=None: (False, "HTTP 404 from x"))
    client.post("/download-models", json={"models": [{"download_url": "https://x/a.safetensors", "save_path": "vae"}]})
    deadline = time.time() + 3
    while time.time() < deadline and not client.get("/download-status").json()["done"]:
        time.sleep(0.01)
    assert client.get("/download-status").json()["error"] == "HTTP 404 from x"


def test_dedicated_runner_is_what_run_schedules_end_to_end(env, monkeypatch):
    """The scheduled call really runs: execute it and check the job completes
    through the compatibility server (fakes at the HTTP-client boundary)."""
    client, executor, tmp_path = env
    _attach()
    monkeypatch.setattr(config, "LOCAL_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(block.time, "sleep", lambda _s: None)
    monkeypatch.setattr(block.media_meta, "embed_metadata", lambda *_a, **_k: None)

    def fake_json(base_url, token, method, path, payload=None, **kw):
        if path == "/run":
            return {"id": "pod-1"}
        if path == "/status/pod-1":
            return {"status": "COMPLETED", "output": {"ok": True, "output": {"files": [
                {"index": 0, "filename": "out.png", "media_type": "image"}]}}}
        raise AssertionError(path)

    monkeypatch.setattr(comfygen_remote, "request_json", fake_json)
    monkeypatch.setattr(comfygen_remote, "download_output", lambda *a: (b"PNG", "image/png"))

    job_id = client.post("/run", json={"workflow": WORKFLOW, "lock_seed": True}).json()["job_id"]
    ((fn, args, kw),) = executor.calls
    fn(*args, **kw)

    job = services._job_snapshot(job_id)
    assert job["status"] == "COMPLETED", job.get("error")
    assert Path(job["local_file"]).read_bytes() == b"PNG"
