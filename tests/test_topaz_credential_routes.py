from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import settings_store  # noqa: E402


def _load_sidecar(slug: str):
    path = ROOT / "custom_blocks" / slug / "backend.block.py"
    spec = importlib.util.spec_from_file_location(f"{slug}_backend_for_topaz_credential_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[Any, tuple[Any, ...]]] = []

    def submit(self, fn, *args):
        self.calls.append((fn, args))


@pytest.fixture
def settings_db(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "settings.db")
    settings_store.init_db()
    settings_store.set_credential("topaz_api_key", "topaz_saved")


def test_video_upscale_uses_saved_topaz_credential(settings_db, monkeypatch):
    monkeypatch.delenv("TOPAZ_API_KEY", raising=False)
    mod = _load_sidecar("upscale")
    executor = FakeExecutor()
    monkeypatch.setattr(mod.state, "EXECUTOR", executor)

    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app)

    resp = client.post("/upscale", json={"source_videos": ["/outputs/source.mp4"]})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert executor.calls[0][1][2] == "topaz_saved"


def test_image_upscale_uses_saved_topaz_credential(settings_db, monkeypatch):
    monkeypatch.delenv("TOPAZ_API_KEY", raising=False)
    mod = _load_sidecar("image_upscale")
    executor = FakeExecutor()
    monkeypatch.setattr(mod.state, "EXECUTOR", executor)

    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app)

    resp = client.post("/upscale", json={"source_images": ["/outputs/source.png"]})

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert executor.calls[0][1][2] == "topaz_saved"
