"""Models and LoRA pages against an attached persistent ComfyGen server
("dedicated" runtime).

Without a serverless endpoint these routes used to answer 409. With a pod
server attached they list, download and delete through its /models/* routes.
FakePod replaces the pod at the comfygen_remote.request_json boundary and
civitai_client is stubbed; the route logic, cache and LoRA metadata run for real.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import (  # noqa: E402
    civitai_client,
    comfygen_pod_models,
    comfygen_remote,
    config,
    lora_metadata,
    lora_routes,
    model_routes,
    settings_store,
)

BASE_URL = "http://127.0.0.1:8787"
TOKEN = "pod-token"


class FakePod:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.listing: dict[str, list[dict]] = {}
        self.final_status = "completed"
        self.final_message: str | None = None
        self.start_error: Exception | None = None
        self.polls_before_done = 1

    def __call__(self, base_url, token, method, path, payload=None, *, timeout=30):
        assert (base_url, token) == (BASE_URL, TOKEN)
        self.calls.append((method, path, payload))
        route = urlsplit(path).path
        if (method, route) == ("GET", "/models/list"):
            folders = parse_qs(urlsplit(path).query)["folders"][0].split(",")
            return {"models_dir": "/workspace/models",
                    "folders": {f: self.listing.get(f, []) for f in folders}}
        if (method, route) == ("POST", "/models/download"):
            if self.start_error:
                raise self.start_error
            self._dest = payload["models"][0]["dest"]
            self._polls = 0
            return {"id": "dl-9", "status": "running"}
        if (method, route) == ("GET", "/models/download/dl-9"):
            self._polls += 1
            done = self._polls > self.polls_before_done
            f = {"index": 0, "dest": self._dest, "status": "done" if done else "downloading",
                 "cached": False, "bytes_done": 100 if done else 40, "bytes_total": 100, "speed_bps": 0}
            body = {"id": "dl-9", "status": self.final_status if done else "running", "files": [f]}
            if done and self.final_message:
                body["message"] = self.final_message
            return body
        if (method, route) == ("POST", "/models/delete"):
            return {"ok": True, "results": [
                {"path": p, "deleted": "locked" not in p, **({"reason": "permission denied"} if "locked" in p else {})}
                for p in payload["paths"]
            ]}
        raise AssertionError(f"unexpected call {method} {path}")

    def payloads(self, method: str, route: str) -> list:
        return [p for (m, pa, p) in self.calls if m == method and urlsplit(pa).path == route]


@pytest.fixture
def pod(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    monkeypatch.setattr(config, "COMFY_GEN_INFO_CACHE_PATH", tmp_path / "comfy_gen_info_cache.json")
    monkeypatch.setattr(config, "CIVITAI_API_KEY", None, raising=False)
    monkeypatch.setattr(lora_metadata, "DB_PATH", tmp_path / "run_history.db")
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "run_history.db")
    settings_store.init_db()
    lora_metadata.init_db()
    monkeypatch.setattr(comfygen_pod_models, "POLL_SEC", 0.01)
    fake = FakePod()
    monkeypatch.setattr(comfygen_remote, "request_json", fake)
    settings_store.set_comfygen_runtime(runtime_kind="dedicated", base_url=BASE_URL)
    settings_store.set_credential("comfygen_remote_token", TOKEN)
    model_routes._reset_download_state()
    lora_routes._reset_download_state()
    return fake


@pytest.fixture
def client(pod):
    app = FastAPI()
    app.include_router(model_routes.router)
    app.include_router(lora_routes.router)
    return TestClient(app)


def _wait(state: dict, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if state["state"] in ("completed", "error"):
            return dict(state)
        time.sleep(0.01)
    raise AssertionError(f"download did not finish: {state}")


class _Meta:
    primary_file_name = "char_v2.safetensors"
    primary_file_size_kb = 2048
    base_model = "Wan 2.2"
    trigger_words = ["ch4r"]


# === Models page ============================================================

def test_models_list_and_sync_work_without_serverless_endpoint(client, pod, tmp_path):
    assert client.get("/api/models").status_code == 200  # was 409

    pod.listing = {
        "checkpoints": [{"filename": "base.safetensors", "path": "checkpoints/base.safetensors", "size_bytes": 1234}],
        "loras": [{"filename": "style.safetensors", "path": "loras/style.safetensors", "size_bytes": 55}],
    }
    r = client.post("/api/models/sync")

    assert r.status_code == 200, r.text
    (listed,) = [path for (m, path, p) in pod.calls if path.startswith("/models/list")]
    assert parse_qs(urlsplit(listed).query)["folders"][0].split(",") == list(model_routes.ALLOWED_MODEL_FOLDERS)
    rows = {(row["folder"], row["filename"]): row for row in r.json()["models"]}
    assert rows[("checkpoints", "base.safetensors")]["size_bytes"] == 1234
    assert rows[("checkpoints", "base.safetensors")]["path"] == "checkpoints/base.safetensors"
    assert ("loras", "style.safetensors") in rows
    # shared cache used by the ComfyGen block dropdown
    cache = json.loads((tmp_path / "comfy_gen_info_cache.json").read_text())
    assert [i["filename"] for i in cache["loras"]] == ["style.safetensors"]


def test_models_download_url_goes_to_pod(client, pod):
    settings_store.set_credential("hf_token", "hf_1")
    r = client.post("/api/models/download", json={
        "source": "url", "folder": "checkpoints",
        "url": "https://huggingface.co/org/repo/resolve/main/model.safetensors",
    })
    assert r.status_code == 202, r.text
    state = _wait(model_routes._download_state)

    assert state["state"] == "completed" and state["progress_percent"] == 100
    assert pod.payloads("POST", "/models/download") == [{
        "models": [{"url": "https://huggingface.co/org/repo/resolve/main/model.safetensors",
                    "dest": "checkpoints/model.safetensors"}],
        "hf_token": "hf_1", "civitai_token": "",
    }]
    rows = client.get("/api/models").json()["models"]
    assert {"folder": "checkpoints", "filename": "model.safetensors"}.items() <= rows[0].items()
    assert rows[0]["path"] == "checkpoints/model.safetensors"


def test_models_download_civitai_resolves_url_and_filename(client, pod, monkeypatch):
    settings_store.set_credential("civitai_api_key", "cv_9")
    monkeypatch.setattr(civitai_client, "fetch_version_metadata", lambda vid, api_key=None: _Meta())
    client.post("/api/models/download", json={"source": "civitai", "folder": "loras", "version_id": 4242})
    state = _wait(model_routes._download_state)

    assert state["state"] == "completed", state
    (start,) = pod.payloads("POST", "/models/download")
    assert start["models"] == [{"url": "https://civitai.com/api/download/models/4242",
                                "dest": "loras/char_v2.safetensors"}]
    assert start["civitai_token"] == "cv_9"


def test_models_download_failure_on_pod_is_reported(client, pod):
    pod.final_status, pod.final_message = "failed", "checkpoints/x.safetensors: HTTP 404 from example.com"
    client.post("/api/models/download", json={"source": "url", "folder": "checkpoints",
                                              "url": "https://example.com/x.safetensors"})
    state = _wait(model_routes._download_state)
    assert state["state"] == "error" and "HTTP 404" in state["error"]
    assert client.get("/api/models").json()["models"] == []


def test_models_download_rejected_by_busy_pod(client, pod):
    pod.start_error = RuntimeError('Compatibility server returned HTTP 409: {"error": "Another download is running"}')
    client.post("/api/models/download", json={"source": "url", "folder": "vae",
                                              "url": "https://example.com/v.safetensors"})
    state = _wait(model_routes._download_state)
    assert state["state"] == "error" and "Another download is running" in state["error"]


def test_models_download_progress_is_reported(client, pod, monkeypatch):
    pod.polls_before_done = 30
    monkeypatch.setattr(comfygen_pod_models, "POLL_SEC", 0.05)
    client.post("/api/models/download", json={"source": "url", "folder": "vae",
                                              "url": "https://example.com/v.safetensors"})
    deadline = time.time() + 3
    while time.time() < deadline and model_routes._download_state.get("progress_percent") != 40:
        time.sleep(0.01)
    assert model_routes._download_state["progress_percent"] == 40
    assert _wait(model_routes._download_state)["state"] == "completed"


def test_models_delete_goes_to_pod(client, pod):
    pod.listing = {"checkpoints": [{"filename": "a.safetensors", "path": "checkpoints/a.safetensors", "size_bytes": 1},
                                   {"filename": "locked.safetensors", "path": "checkpoints/locked.safetensors", "size_bytes": 1}]}
    client.post("/api/models/sync")
    r = client.post("/api/models/delete", json={"items": [
        {"folder": "checkpoints", "filename": "a.safetensors"},
        {"folder": "checkpoints", "filename": "locked.safetensors"},
    ]})
    assert r.status_code == 207
    assert pod.payloads("POST", "/models/delete") == [{"paths": ["checkpoints/a.safetensors",
                                                                 "checkpoints/locked.safetensors"]}]
    results = {x["filename"]: x for x in r.json()["results"]}
    assert results["a.safetensors"]["deleted"] is True
    assert results["locked.safetensors"]["deleted"] is False
    assert results["locked.safetensors"]["error"] == "permission denied"
    remaining = [row["filename"] for row in client.get("/api/models").json()["models"]]
    assert remaining == ["locked.safetensors"]


def test_models_need_pod_token(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "x.db")
    monkeypatch.setattr(lora_metadata, "DB_PATH", tmp_path / "x.db")
    monkeypatch.setattr(config, "COMFY_GEN_INFO_CACHE_PATH", tmp_path / "c.json")
    settings_store.init_db()
    lora_metadata.init_db()
    settings_store.set_comfygen_runtime(runtime_kind="dedicated", base_url=BASE_URL)
    app = FastAPI()
    app.include_router(model_routes.router)
    app.include_router(lora_routes.router)
    c = TestClient(app)
    for method, url in (("get", "/api/models"), ("post", "/api/models/sync"), ("get", "/api/loras")):
        r = getattr(c, method)(url)
        assert r.status_code == 400 and "bearer token" in r.json()["detail"]


def test_serverless_mode_unchanged_still_409(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "y.db")
    settings_store.init_db()
    app = FastAPI()
    app.include_router(model_routes.router)
    app.include_router(lora_routes.router)
    c = TestClient(app)
    assert c.get("/api/models").status_code == 409
    assert c.get("/api/loras").status_code == 409


# === LoRA page ==============================================================

def test_loras_sync_lists_pod_loras(client, pod):
    assert client.get("/api/loras").status_code == 200  # was 409
    pod.listing = {"loras": [{"filename": "a.safetensors", "path": "loras/a.safetensors", "size_bytes": 9},
                             {"filename": "sub/b.safetensors", "path": "loras/sub/b.safetensors", "size_bytes": 9}]}
    r = client.post("/api/loras/sync")
    assert r.status_code == 200, r.text
    assert sorted(x["filename"] for x in r.json()["loras"]) == ["a.safetensors", "sub/b.safetensors"]
    assert [path for (m, path, p) in pod.calls if path.startswith("/models/list")] == ["/models/list?folders=loras"]


def test_loras_download_civitai_records_metadata(client, pod, monkeypatch):
    settings_store.set_credential("civitai_api_key", "cv_9")
    monkeypatch.setattr(civitai_client, "fetch_version_metadata", lambda vid, api_key=None: _Meta())
    r = client.post("/api/loras/download", json={"source": "civitai", "version_id": 777})
    assert r.status_code == 202, r.text
    state = _wait(lora_routes._download_state)

    assert state["state"] == "completed", state
    (start,) = pod.payloads("POST", "/models/download")
    assert start["models"] == [{"url": "https://civitai.com/api/download/models/777",
                                "dest": "loras/char_v2.safetensors"}]
    (lora,) = client.get("/api/loras").json()["loras"]
    assert lora["filename"] == "char_v2.safetensors"
    assert lora["source"] == "civitai" and lora["source_id"] == "777"
    assert lora["trigger_words"] == ["ch4r"] and lora["base_model"] == "Wan 2.2"


def test_loras_download_url(client, pod):
    client.post("/api/loras/download", json={"source": "url",
                                             "url": "https://huggingface.co/o/r/resolve/main/x.safetensors"})
    assert _wait(lora_routes._download_state)["state"] == "completed"
    (start,) = pod.payloads("POST", "/models/download")
    assert start["models"][0]["dest"] == "loras/x.safetensors"


def test_loras_delete_goes_to_pod(client, pod):
    lora_metadata.upsert(filename="a.safetensors", source="url", source_id="u", base_model=None, trigger_words=[])
    r = client.post("/api/loras/delete", json={"filenames": ["a.safetensors"]})
    assert r.status_code == 200, r.text
    assert pod.payloads("POST", "/models/delete") == [{"paths": ["loras/a.safetensors"]}]
    assert r.json()["results"] == [{"filename": "a.safetensors", "deleted": True, "error": None}]
