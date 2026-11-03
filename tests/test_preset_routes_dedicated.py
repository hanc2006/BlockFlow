"""Preset install / cancel / uninstall / disk budget against an attached
persistent ComfyGen server ("dedicated" runtime).

In dedicated mode BlockFlow does not spawn a RunPod installer pod or use a
serverless endpoint: it asks the pod server (ComfyGen server.py) to download
the preset's model files into its ComfyUI models folder via /models/*.

The pod server is replaced by FakePod at the comfygen_remote.request_json
boundary; the BlockFlow logic under test (payload building, progress mapping,
Settings persistence, shared-file protection) runs for real.
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

from backend import comfygen_remote, preset_routes, settings_store  # noqa: E402

BASE_URL = "https://pod-8787.proxy.runpod.net"
TOKEN = "pod-token"

PRESET = {
    "id": "hidream-o1",
    "comfygen_min_version": "0.2.0",
    "disk_size_estimate_gb": 18,
    "workflows": [{"name": "Image Gen", "workflow": {"1": {"class_type": "SaveImage", "inputs": {}}}}],
    "models": [
        {"source": "huggingface", "url": "https://huggingface.co/a/resolve/main/ckpt.safetensors",
         "dest": "checkpoints/ckpt.safetensors", "sha256": "a" * 64, "size_gb": 15.24},
        {"source": "huggingface", "url": "https://huggingface.co/a/resolve/main/vae.safetensors",
         "dest": "vae.safetensors", "size_gb": 0.3},
    ],
}
MANIFEST = {"manifest_version": 1, "presets": [{
    "id": "hidream-o1", "name": "HiDream", "comfygen_min_version": "0.2.0",
    "disk_size_estimate_gb": 18, "preset_url": "https://example/preset.json",
}]}


def _resp(body: dict, status: int = 200) -> MagicMock:
    m = MagicMock()
    m.status_code = status
    m.json = lambda: body
    m.text = json.dumps(body)
    return m


class FakePod:
    """Records calls and plays back /models/* responses."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.statuses: list[dict] = []
        self.start_error: Exception | None = None
        self.delete_result: dict | None = None
        self.disk = {"models_dir": "/workspace/ComfyUI/models", "total_bytes": 200 * 1024 ** 3,
                     "free_bytes": 50 * 1024 ** 3}

    def __call__(self, base_url, token, method, path, payload=None, *, timeout=30):
        assert base_url == BASE_URL and token == TOKEN
        self.calls.append((method, path, payload))
        if (method, path) == ("POST", "/models/download"):
            if self.start_error:
                raise self.start_error
            return {"id": "dl-1", "status": "running", "files": [], "bytes_done": 0, "bytes_total": 0}
        if method == "GET" and path == "/models/download/dl-1":
            return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]
        if (method, path) == ("POST", "/models/download/dl-1/cancel"):
            self.statuses = [_status("cancelled", message="Cancelled by user")]
            return self.statuses[0]
        if (method, path) == ("POST", "/models/delete"):
            if self.delete_result is not None:
                return self.delete_result
            return {"ok": True, "results": [{"path": p, "deleted": True} for p in payload["paths"]]}
        if (method, path) == ("GET", "/models/disk"):
            return self.disk
        raise AssertionError(f"unexpected call {method} {path}")

    def paths(self, method: str, path: str) -> list[dict | None]:
        return [p for (m, pa, p) in self.calls if (m, pa) == (method, path)]


def _status(status: str, files: list[dict] | None = None, message: str | None = None, **extra) -> dict:
    files = files if files is not None else [
        {"index": 0, "dest": "checkpoints/ckpt.safetensors", "status": "done", "cached": False,
         "bytes_done": 100, "bytes_total": 100, "speed_bps": 0},
        {"index": 1, "dest": "vae/vae.safetensors", "status": "done", "cached": True,
         "bytes_done": 10, "bytes_total": 10, "speed_bps": 0},
    ]
    body = {
        "id": "dl-1", "status": status, "files": files, "files_total": len(files),
        "files_done": sum(1 for f in files if f["status"] == "done"),
        "bytes_done": sum(f["bytes_done"] for f in files), "bytes_total": sum(f["bytes_total"] for f in files),
        **extra,
    }
    if message:
        body["message"] = message
    return body


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "dedicated.db")
    settings_store.init_db()
    monkeypatch.setattr(preset_routes, "_CACHE_PATH", tmp_path / "manifest_cache.json")
    monkeypatch.setattr(preset_routes, "_DEDICATED_POLL_SEC", 0.01)
    preset_routes._cache_reset()
    preset_routes._reset_install_state()
    fastapi_app = FastAPI()
    fastapi_app.include_router(preset_routes.router)
    return fastapi_app


@pytest.fixture
def client(app):
    return TestClient(app)


@pytest.fixture
def pod(monkeypatch):
    fake = FakePod()
    monkeypatch.setattr(comfygen_remote, "request_json", fake)
    settings_store.set_comfygen_runtime(runtime_kind="dedicated", base_url=BASE_URL)
    settings_store.set_credential("comfygen_remote_token", TOKEN)
    return fake


@pytest.fixture
def registry(mocker):
    return mocker.patch.object(
        preset_routes._cffi_requests, "get",
        MagicMock(side_effect=lambda url, **kw: _resp(MANIFEST if "manifest" in url else PRESET)),
    )


def _wait_state(*targets: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if preset_routes._install_state["state"] in targets:
            return dict(preset_routes._install_state)
        time.sleep(0.01)
    raise AssertionError(f"install never reached {targets}: {preset_routes._install_state}")


# === install ================================================================

def test_install_downloads_through_pod_without_runpod_key_or_endpoint(client, pod, registry):
    settings_store.set_credential("hf_token", "hf_abc")
    settings_store.set_credential("civitai_api_key", "cv_xyz")
    pod.statuses = [_status("completed")]

    r = client.post("/api/presets/install", json={"preset_id": "hidream-o1"})

    assert r.status_code == 202, r.text
    assert r.json()["files_total"] == 2
    (start,) = pod.paths("POST", "/models/download")
    assert start == {
        "models": [
            {"url": "https://huggingface.co/a/resolve/main/ckpt.safetensors",
             "dest": "checkpoints/ckpt.safetensors", "sha256": "a" * 64, "size_gb": 15.24},
            # legacy dest without a folder lands in checkpoints/, like the serverless flow
            {"url": "https://huggingface.co/a/resolve/main/vae.safetensors",
             "dest": "checkpoints/vae.safetensors", "size_gb": 0.3},
        ],
        "hf_token": "hf_abc",
        "civitai_token": "cv_xyz",
    }

    state = _wait_state("completed")
    assert state["install_mode"] == "dedicated" and state["phase"] == "done"
    row = settings_store.get_installed_preset("hidream-o1")
    assert row["install_mode"] == "dedicated"
    assert row["installed_paths"] == ["checkpoints/ckpt.safetensors", "checkpoints/vae.safetensors"]
    assert row["version"] == "0.2.0" and row["disk_size_gb"] == 18
    blob = json.loads(row["workflow_json"])
    assert [w["name"] for w in blob["workflows"]] == ["Image Gen"]


def test_install_progress_maps_pod_status_to_ui_fields(client, pod, registry):
    running = _status("running", files=[
        {"index": 0, "dest": "checkpoints/ckpt.safetensors", "status": "downloading", "cached": False,
         "bytes_done": 25, "bytes_total": 100, "speed_bps": 2 * 1024 ** 2},
        {"index": 1, "dest": "checkpoints/vae.safetensors", "status": "verifying", "cached": False,
         "bytes_done": 5, "bytes_total": 10, "speed_bps": 0},
    ])
    pod.statuses = [running, running, running, _status("completed")]
    preset_routes._DEDICATED_POLL_SEC = 0.2

    client.post("/api/presets/install", json={"preset_id": "hidream-o1"})
    deadline = time.time() + 3
    while time.time() < deadline and not preset_routes._install_state["files"]:
        time.sleep(0.01)
    p = client.get("/api/presets/install/progress").json()

    assert p["state"] == "running" and p["phase"] == "download" and p["install_mode"] == "dedicated"
    assert p["total_download_bytes"] == 110
    assert p["bytes_done"] == 25  # verifying bytes are hashing, not downloading
    assert p["files_done"] == 0
    assert p["files"][0] == {
        "index": 0, "path": "checkpoints/ckpt.safetensors", "status": "downloading",
        "percent": 25.0, "speed": "2.0 MB/s", "cached": False, "bytes": 100, "sha256": None,
    }
    assert p["files"][1]["status"] == "downloading" and p["files"][1]["percent"] == 50.0
    _wait_state("completed")


def test_install_failure_on_pod_sets_error_and_records_nothing(client, pod, registry):
    pod.statuses = [_status("failed", message="checkpoints/ckpt.safetensors: HTTP 401 from huggingface.co")]

    client.post("/api/presets/install", json={"preset_id": "hidream-o1"})
    state = _wait_state("error")

    assert "HTTP 401" in state["error"]
    assert state["error_kind"] == "unknown"  # no GPU-fallback prompt for pod installs
    assert settings_store.get_installed_preset("hidream-o1") is None


def test_install_rejected_by_pod_returns_error_immediately(client, pod, registry):
    pod.start_error = RuntimeError('Compatibility server returned HTTP 507: {"error": "Not enough disk space"}')

    r = client.post("/api/presets/install", json={"preset_id": "hidream-o1"})

    assert r.status_code == 502
    assert "Not enough disk space" in r.json()["detail"]
    assert preset_routes._install_state["state"] == "idle"


def test_install_poll_errors_are_retried_then_fail(client, pod, registry, monkeypatch):
    monkeypatch.setattr(preset_routes, "_DEDICATED_MAX_POLL_ERRORS", 3)
    real = pod.__call__

    def flaky(base_url, token, method, path, payload=None, *, timeout=30):
        if method == "GET" and path.startswith("/models/download/"):
            raise RuntimeError("Could not reach compatibility server: timed out")
        return real(base_url, token, method, path, payload, timeout=timeout)

    monkeypatch.setattr(comfygen_remote, "request_json", flaky)
    client.post("/api/presets/install", json={"preset_id": "hidream-o1"})
    state = _wait_state("error")
    assert "Lost contact with the pod" in state["error"] and "timed out" in state["error"]


def test_install_requires_pod_url_and_token(client, registry):
    settings_store.set_comfygen_runtime(runtime_kind="dedicated", base_url=BASE_URL)
    # no comfygen_remote_token
    r = client.post("/api/presets/install", json={"preset_id": "hidream-o1"})
    assert r.status_code == 400
    assert "bearer token" in r.json()["detail"]


def test_install_still_requires_civitai_key_for_civitai_models(client, pod, mocker):
    civitai_preset = {**PRESET, "models": [{"source": "civitai", "url": "https://civitai.com/api/download/models/1",
                                            "dest": "loras/x.safetensors"}]}
    mocker.patch.object(preset_routes._cffi_requests, "get", MagicMock(
        side_effect=lambda url, **kw: _resp(MANIFEST if "manifest" in url else civitai_preset)))
    r = client.post("/api/presets/install", json={"preset_id": "hidream-o1"})
    assert r.status_code == 400
    assert r.json()["detail"]["credential"] == "civitai_api_key"
    assert pod.paths("POST", "/models/download") == []


def test_install_rejects_gpu_mode_in_dedicated(client, pod, registry):
    r = client.post("/api/presets/install?mode=gpu", json={"preset_id": "hidream-o1"})
    assert r.status_code == 400
    assert pod.calls == []


def test_install_409_while_another_install_runs(client, pod, registry):
    preset_routes._install_state.update({"state": "running", "preset_id": "other"})
    r = client.post("/api/presets/install", json={"preset_id": "hidream-o1"})
    assert r.status_code == 409
    assert pod.paths("POST", "/models/download") == []


# === cancel =================================================================

def test_cancel_stops_pod_download(client, pod, registry):
    running = _status("running", files=[{"index": 0, "dest": "checkpoints/ckpt.safetensors", "status": "downloading",
                                         "cached": False, "bytes_done": 1, "bytes_total": 100, "speed_bps": 0}])
    pod.statuses = [running]
    client.post("/api/presets/install", json={"preset_id": "hidream-o1"})
    _wait_state("running")

    r = client.post("/api/presets/install/cancel")

    assert r.status_code == 200 and r.json()["state"] == "cancelling"
    assert pod.paths("POST", "/models/download/dl-1/cancel") == [None]
    state = _wait_state("cancelled")
    assert state["error"] == "install cancelled by user"
    assert settings_store.get_installed_preset("hidream-o1") is None


# === uninstall ==============================================================

def _record(preset_id: str, paths: list[str], mode: str | None = "dedicated") -> None:
    settings_store.record_installed_preset(
        preset_id=preset_id, version="0.2.0", workflow_json="{}", disk_size_gb=5,
        installed_paths=paths, install_mode=mode,
    )


def test_uninstall_deletes_on_pod_and_keeps_files_shared_with_other_presets(client, pod):
    _record("a", ["checkpoints/a.safetensors", "vae/shared.safetensors"])
    _record("b", ["checkpoints/b.safetensors", "vae/shared.safetensors"])

    r = client.post("/api/presets/uninstall/a")

    assert r.status_code == 200, r.text
    assert pod.paths("POST", "/models/delete") == [{"paths": ["checkpoints/a.safetensors"]}]
    assert r.json() == {"ok": True, "preset_id": "a", "deleted_count": 1, "errors": [],
                        "kept_shared": ["vae/shared.safetensors"]}
    assert settings_store.get_installed_preset("a") is None
    assert settings_store.get_installed_preset("b") is not None


def test_uninstall_partial_failure_keeps_row(client, pod):
    _record("a", ["checkpoints/a.safetensors", "loras/x.safetensors"])
    pod.delete_result = {"ok": False, "results": [
        {"path": "checkpoints/a.safetensors", "deleted": True},
        {"path": "loras/x.safetensors", "deleted": False, "reason": "permission denied"},
    ]}
    r = client.post("/api/presets/uninstall/a")
    assert r.status_code == 207
    assert r.json()["deleted_count"] == 1 and r.json()["errors"][0]["path"] == "loras/x.safetensors"
    assert settings_store.get_installed_preset("a") is not None


def test_uninstall_only_shared_files_skips_delete_call(client, pod):
    _record("a", ["vae/shared.safetensors"])
    _record("b", ["vae/shared.safetensors"])
    r = client.post("/api/presets/uninstall/a")
    assert r.status_code == 200 and r.json()["deleted_count"] == 0
    assert pod.paths("POST", "/models/delete") == []
    assert settings_store.get_installed_preset("a") is None


def test_uninstall_dedicated_row_needs_attached_server(client):
    _record("a", ["checkpoints/a.safetensors"])
    r = client.post("/api/presets/uninstall/a")
    assert r.status_code == 409
    assert "persistent ComfyGen server" in r.json()["detail"]
    assert settings_store.get_installed_preset("a") is not None


def test_uninstall_pod_unreachable_keeps_row(client, pod, monkeypatch):
    _record("a", ["checkpoints/a.safetensors"])

    def down(*a, **kw):
        raise RuntimeError("Could not reach compatibility server: refused")

    monkeypatch.setattr(comfygen_remote, "request_json", down)
    r = client.post("/api/presets/uninstall/a")
    assert r.status_code == 502 and "refused" in r.json()["detail"]
    assert settings_store.get_installed_preset("a") is not None


# === disk budget ============================================================

def test_disk_budget_uses_pod_disk(client, pod):
    _record("a", ["checkpoints/a.safetensors"])
    r = client.get("/api/presets/disk-budget")
    assert r.status_code == 200
    assert r.json() == {"total_gb": 200, "used_estimate_gb": 150, "free_estimate_gb": 50}


def test_disk_budget_pod_unreachable_returns_unknown(client, pod, monkeypatch):
    def down(*a, **kw):
        raise RuntimeError("Could not reach compatibility server")

    monkeypatch.setattr(comfygen_remote, "request_json", down)
    _record("a", ["checkpoints/a.safetensors"])
    assert client.get("/api/presets/disk-budget").json() == {
        "total_gb": None, "used_estimate_gb": 5, "free_estimate_gb": None,
    }


# === refresh keeps install_mode ============================================

def test_refresh_installed_presets_preserves_install_mode(app, mocker):
    settings_store.record_installed_preset(
        preset_id="hidream-o1", version="0.1.0", workflow_json="{}", disk_size_gb=18,
        installed_paths=["checkpoints/ckpt.safetensors"], install_mode="dedicated",
    )
    mocker.patch.object(preset_routes._cffi_requests, "get", MagicMock(
        side_effect=lambda url, **kw: _resp(MANIFEST if "manifest" in url else PRESET)))

    result = preset_routes.refresh_installed_presets()

    assert result["refreshed"] == [{"preset_id": "hidream-o1"}]
    row = settings_store.get_installed_preset("hidream-o1")
    assert row["install_mode"] == "dedicated"
    assert row["installed_paths"] == ["checkpoints/ckpt.safetensors"]
