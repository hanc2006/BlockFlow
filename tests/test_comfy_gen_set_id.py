"""set_id on a generation job: the output lands in that set automatically.

This is what makes "an agent creates a set and everything it generates goes in"
work without a second call from the caller.
"""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "comfy_gen_block", ROOT / "custom_blocks" / "comfy_gen" / "backend.block.py"
)
cg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cg)


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "t.db")
    db.init_db()
    yield db


@pytest.fixture
def client(temp_db, monkeypatch):
    monkeypatch.setattr(cg.state, "EXECUTOR", type("E", (), {"submit": lambda *a, **k: None})())
    monkeypatch.setattr(cg.state, "_persist_jobs_locked", lambda: None)
    monkeypatch.setattr(cg, "_publish_event", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(cg.router, prefix="/api/blocks/comfy_gen")
    return TestClient(app)


_WF = {"1": {"class_type": "X", "inputs": {}}}


def test_run_route_records_set_id_on_the_job(client, temp_db):
    """The worker reads set_id off the job record, so /run must persist it."""
    sid = temp_db.create_set("A")["id"]
    resp = client.post("/api/blocks/comfy_gen/run", json={
        "workflow": _WF, "source": "mcp", "batch_id": "b1", "set_id": sid,
    })
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    assert cg.state.JOBS[job_id]["set_id"] == sid


def test_run_route_without_set_id_stores_nothing(client, temp_db):
    resp = client.post("/api/blocks/comfy_gen/run", json={"workflow": _WF})
    job_id = resp.json()["job_id"]
    assert "set_id" not in cg.state.JOBS[job_id]


def test_completed_output_is_added_to_the_set(temp_db):
    sid = temp_db.create_set("Drop")["id"]
    cg._add_output_to_set(sid, "/outputs/a.png", run_id="run-mcp-b1")

    items = temp_db.get_set(sid)["items"]
    assert [i["url"] for i in items] == ["/outputs/a.png"]
    assert items[0]["kind"] == "image"
    assert items[0]["run_id"] == "run-mcp-b1"


def test_video_output_is_added_as_video(temp_db):
    sid = temp_db.create_set("Drop")["id"]
    cg._add_output_to_set(sid, "/outputs/clip.mp4", run_id=None)
    assert temp_db.get_set(sid)["items"][0]["kind"] == "video"


def test_many_jobs_of_one_batch_all_land_in_the_set(temp_db):
    sid = temp_db.create_set("Drop")["id"]
    for i in range(5):
        cg._add_output_to_set(sid, f"/outputs/{i}.png", run_id="run-mcp-b1")
    assert temp_db.list_sets()[0]["item_count"] == 5


def test_unknown_set_does_not_raise(temp_db):
    """A deleted set must never fail an otherwise-successful generation."""
    cg._add_output_to_set("set-gone", "/outputs/a.png", run_id=None)   # no exception


def test_db_failure_does_not_raise(temp_db, monkeypatch, capsys):
    def boom(*a, **k):
        raise RuntimeError("disk gone")

    monkeypatch.setattr(cg.db, "add_set_items", boom)
    cg._add_output_to_set("set-x", "/outputs/a.png", run_id=None)
    assert "set" in capsys.readouterr().out.lower()   # logged, not swallowed silently
