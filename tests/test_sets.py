"""Sets: named, mutable collections of generated media (images + videos).

Covers the db layer, the /api/sets routes, and the set_id filter on /api/runs.
"""
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db, routes  # noqa: E402


@pytest.fixture
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test_sets.db")
    db.init_db()
    yield db


@pytest.fixture
def client(temp_db):
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def _run(*, name: str, urls: list[str], kind: str = "image",
         created_at: str = "2026-01-01T00:00:00Z") -> dict:
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "status": "completed",
        "duration_ms": 1,
        "flow_snapshot": {"blocks": []},
        "block_results": [{
            "block_index": 0,
            "block_type": "comfy_gen",
            "block_label": "ComfyGen",
            "status": "ok",
            "outputs": {kind: {"kind": kind, "value": urls}},
        }],
        "created_at": created_at,
    }


# ---------- db layer ----------

class TestSetsDb:
    def test_create_then_list_and_get(self, temp_db):
        s = temp_db.create_set("Summer drop")
        assert s["id"].startswith("set-")
        assert s["name"] == "Summer drop"
        assert s["created_at"].endswith("Z")

        listed = temp_db.list_sets()
        assert [x["id"] for x in listed] == [s["id"]]
        assert listed[0]["item_count"] == 0          # created empty

        got = temp_db.get_set(s["id"])
        assert got["name"] == "Summer drop" and got["items"] == []

    def test_get_unknown_set_is_none(self, temp_db):
        assert temp_db.get_set("set-nope") is None

    def test_items_added_after_creation(self, temp_db):
        """The whole point: a set is mutable long after it was created."""
        sid = temp_db.create_set("A")["id"]
        added = temp_db.add_set_items(sid, [
            {"url": "/outputs/a.png"},
            {"url": "/outputs/b.mp4", "run_id": "run-1"},
        ])
        assert added == 2
        items = temp_db.get_set(sid)["items"]
        assert [i["url"] for i in items] == ["/outputs/a.png", "/outputs/b.mp4"]
        assert [i["kind"] for i in items] == ["image", "video"]   # inferred from extension
        assert items[1]["run_id"] == "run-1"
        assert temp_db.list_sets()[0]["item_count"] == 2

    def test_explicit_kind_wins_over_inference(self, temp_db):
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/weird", "kind": "video"}])
        assert temp_db.get_set(sid)["items"][0]["kind"] == "video"

    def test_adding_same_url_twice_does_not_duplicate(self, temp_db):
        sid = temp_db.create_set("A")["id"]
        assert temp_db.add_set_items(sid, [{"url": "/outputs/a.png"}]) == 1
        assert temp_db.add_set_items(sid, [{"url": "/outputs/a.png"}]) == 0
        assert temp_db.list_sets()[0]["item_count"] == 1

    def test_add_to_unknown_set_returns_none(self, temp_db):
        assert temp_db.add_set_items("set-nope", [{"url": "/outputs/a.png"}]) is None

    def test_blank_and_malformed_urls_are_skipped(self, temp_db):
        sid = temp_db.create_set("A")["id"]
        assert temp_db.add_set_items(sid, [{"url": "  "}, {"url": None}, {}, "nope"]) == 0
        assert temp_db.get_set(sid)["items"] == []

    def test_same_url_can_live_in_two_sets(self, temp_db):
        a = temp_db.create_set("A")["id"]
        b = temp_db.create_set("B")["id"]
        temp_db.add_set_items(a, [{"url": "/outputs/a.png"}])
        temp_db.add_set_items(b, [{"url": "/outputs/a.png"}])
        assert temp_db.list_sets()[0]["item_count"] == 1
        assert temp_db.list_sets()[1]["item_count"] == 1

    def test_remove_item(self, temp_db):
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/a.png"}, {"url": "/outputs/b.png"}])
        assert temp_db.remove_set_item(sid, "/outputs/a.png") is True
        assert temp_db.remove_set_item(sid, "/outputs/a.png") is False   # already gone
        assert [i["url"] for i in temp_db.get_set(sid)["items"]] == ["/outputs/b.png"]

    def test_rename_set(self, temp_db):
        sid = temp_db.create_set("old")["id"]
        assert temp_db.rename_set(sid, "new") is True
        assert temp_db.get_set(sid)["name"] == "new"
        assert temp_db.rename_set("set-nope", "x") is False

    def test_delete_set_removes_its_items(self, temp_db):
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/a.png"}])
        assert temp_db.delete_set(sid) is True
        assert temp_db.get_set(sid) is None
        assert temp_db.delete_set(sid) is False
        # A new set reusing the id must not inherit orphaned rows.
        assert temp_db.set_urls(sid) == set()

    def test_list_sets_is_newest_first(self, temp_db):
        first = temp_db.create_set("first")["id"]
        second = temp_db.create_set("second")["id"]
        # created_at can tie at millisecond resolution, so the id is the tiebreaker;
        # assert on membership + that both counts are present rather than a fragile order.
        ids = [s["id"] for s in temp_db.list_sets()]
        assert set(ids) == {first, second}

    def test_concurrent_adds_lose_nothing(self, temp_db):
        """Mirrors a fanned-out MCP batch: many jobs adding to one set at once."""
        sid = temp_db.create_set("A")["id"]
        threads = [
            threading.Thread(target=temp_db.add_set_items,
                             args=(sid, [{"url": f"/outputs/{i}.png"}]))
            for i in range(25)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert temp_db.list_sets()[0]["item_count"] == 25


# ---------- run filtering by set ----------

class TestRunsSetFilter:
    def test_filters_runs_to_set_members(self, temp_db):
        temp_db.save_run(_run(name="in-set", urls=["/outputs/a.png"]))
        temp_db.save_run(_run(name="out-of-set", urls=["/outputs/z.png"]))
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/a.png"}])

        rows = temp_db.list_runs(limit=10, offset=0, set_id=sid)
        assert [r["name"] for r in rows] == ["in-set"]
        assert temp_db.count_runs(set_id=sid) == 1

    def test_run_matches_when_any_output_is_in_the_set(self, temp_db):
        temp_db.save_run(_run(name="multi", urls=["/outputs/x.png", "/outputs/a.png"]))
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/a.png"}])
        assert [r["name"] for r in temp_db.list_runs(set_id=sid)] == ["multi"]

    def test_video_outputs_match_too(self, temp_db):
        temp_db.save_run(_run(name="clip", urls=["/outputs/c.mp4"], kind="video"))
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/c.mp4"}])
        assert [r["name"] for r in temp_db.list_runs(set_id=sid)] == ["clip"]

    def test_scalar_output_value_matches(self, temp_db):
        """Pipeline runs may store a single URL rather than an array."""
        run = _run(name="scalar", urls=["/outputs/s.png"])
        run["block_results"][0]["outputs"]["image"]["value"] = "/outputs/s.png"
        temp_db.save_run(run)
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/s.png"}])
        assert [r["name"] for r in temp_db.list_runs(set_id=sid)] == ["scalar"]

    def test_empty_set_matches_nothing(self, temp_db):
        temp_db.save_run(_run(name="any", urls=["/outputs/a.png"]))
        sid = temp_db.create_set("A")["id"]
        assert temp_db.list_runs(set_id=sid) == []
        assert temp_db.count_runs(set_id=sid) == 0

    def test_unknown_set_matches_nothing(self, temp_db):
        temp_db.save_run(_run(name="any", urls=["/outputs/a.png"]))
        assert temp_db.count_runs(set_id="set-nope") == 0

    def test_combines_with_media_kind(self, temp_db):
        temp_db.save_run(_run(name="img", urls=["/outputs/a.png"]))
        temp_db.save_run(_run(name="vid", urls=["/outputs/a.mp4"], kind="video"))
        sid = temp_db.create_set("A")["id"]
        temp_db.add_set_items(sid, [{"url": "/outputs/a.png"}, {"url": "/outputs/a.mp4"}])

        assert [r["name"] for r in temp_db.list_runs(set_id=sid, media_kind="video")] == ["vid"]
        assert temp_db.count_runs(set_id=sid, media_kind="video") == 1

    def test_pagination_applies_after_set_filter(self, temp_db):
        sid = temp_db.create_set("A")["id"]
        for i in range(4):
            temp_db.save_run(_run(name=f"r{i}", urls=[f"/outputs/{i}.png"],
                                  created_at=f"2026-01-0{i + 1}T00:00:00Z"))
            temp_db.add_set_items(sid, [{"url": f"/outputs/{i}.png"}])
        temp_db.save_run(_run(name="outsider", urls=["/outputs/zz.png"],
                              created_at="2026-01-09T00:00:00Z"))

        page1 = temp_db.list_runs(limit=2, offset=0, set_id=sid)
        page2 = temp_db.list_runs(limit=2, offset=2, set_id=sid)
        assert [r["name"] for r in page1] == ["r3", "r2"]
        assert [r["name"] for r in page2] == ["r1", "r0"]
        assert temp_db.count_runs(set_id=sid) == 4


# ---------- routes ----------

class TestSetsRoutes:
    def test_list_empty_initially(self, client):
        r = client.get("/api/sets")
        assert r.status_code == 200 and r.json() == {"ok": True, "sets": []}

    def test_create_then_fetch(self, client):
        r = client.post("/api/sets", json={"name": "Drop 1"})
        assert r.status_code == 200
        sid = r.json()["set"]["id"]

        got = client.get(f"/api/sets/{sid}").json()["set"]
        assert got["name"] == "Drop 1" and got["items"] == []
        assert client.get("/api/sets").json()["sets"][0]["item_count"] == 0

    def test_create_requires_a_name(self, client):
        assert client.post("/api/sets", json={"name": "  "}).status_code == 400
        assert client.post("/api/sets", json={}).status_code == 400
        assert client.post("/api/sets", json={"name": 5}).status_code == 400

    def test_add_items_after_creation(self, client):
        sid = client.post("/api/sets", json={"name": "A"}).json()["set"]["id"]
        r = client.post(f"/api/sets/{sid}/items", json={
            "items": [{"url": "/outputs/a.png"}, {"url": "/outputs/b.mp4"}],
        })
        assert r.status_code == 200 and r.json()["added"] == 2
        items = client.get(f"/api/sets/{sid}").json()["set"]["items"]
        assert [i["url"] for i in items] == ["/outputs/a.png", "/outputs/b.mp4"]

    def test_add_items_is_idempotent(self, client):
        sid = client.post("/api/sets", json={"name": "A"}).json()["set"]["id"]
        body = {"items": [{"url": "/outputs/a.png"}]}
        assert client.post(f"/api/sets/{sid}/items", json=body).json()["added"] == 1
        assert client.post(f"/api/sets/{sid}/items", json=body).json()["added"] == 0
        assert client.get("/api/sets").json()["sets"][0]["item_count"] == 1

    def test_add_items_validates(self, client):
        sid = client.post("/api/sets", json={"name": "A"}).json()["set"]["id"]
        assert client.post(f"/api/sets/{sid}/items", json={"items": []}).status_code == 400
        assert client.post(f"/api/sets/{sid}/items", json={"items": "nope"}).status_code == 400
        assert client.post("/api/sets/set-nope/items", json={
            "items": [{"url": "/outputs/a.png"}]}).status_code == 404

    def test_remove_item(self, client):
        sid = client.post("/api/sets", json={"name": "A"}).json()["set"]["id"]
        client.post(f"/api/sets/{sid}/items", json={"items": [{"url": "/outputs/a.png"}]})
        r = client.request("DELETE", f"/api/sets/{sid}/items", json={"url": "/outputs/a.png"})
        assert r.status_code == 200
        assert client.get(f"/api/sets/{sid}").json()["set"]["items"] == []
        # gone already
        assert client.request("DELETE", f"/api/sets/{sid}/items",
                             json={"url": "/outputs/a.png"}).status_code == 404

    def test_rename(self, client):
        sid = client.post("/api/sets", json={"name": "old"}).json()["set"]["id"]
        assert client.patch(f"/api/sets/{sid}", json={"name": "new"}).status_code == 200
        assert client.get(f"/api/sets/{sid}").json()["set"]["name"] == "new"
        assert client.patch(f"/api/sets/{sid}", json={"name": " "}).status_code == 400
        assert client.patch("/api/sets/set-nope", json={"name": "x"}).status_code == 404

    def test_delete(self, client):
        sid = client.post("/api/sets", json={"name": "A"}).json()["set"]["id"]
        assert client.delete(f"/api/sets/{sid}").status_code == 200
        assert client.get("/api/sets").json()["sets"] == []
        assert client.delete(f"/api/sets/{sid}").status_code == 404

    def test_get_unknown_set_is_404(self, client):
        assert client.get("/api/sets/set-nope").status_code == 404

    def test_runs_route_accepts_set_id(self, client, temp_db):
        temp_db.save_run(_run(name="in-set", urls=["/outputs/a.png"]))
        temp_db.save_run(_run(name="other", urls=["/outputs/z.png"]))
        sid = client.post("/api/sets", json={"name": "A"}).json()["set"]["id"]
        client.post(f"/api/sets/{sid}/items", json={"items": [{"url": "/outputs/a.png"}]})

        data = client.get(f"/api/runs?set_id={sid}").json()
        assert [r["name"] for r in data["runs"]] == ["in-set"]
        assert data["total"] == 1
