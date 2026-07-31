"""MCP Sets tools: create/list/add, and the set_id passthrough on job submission
that makes every generated output land in the set automatically."""

import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

pytest.importorskip("fastmcp", reason="MCP server tests require fastmcp (run with `uv run --with fastmcp`)")

import mcp_server  # noqa: E402


class _Resp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload


class _FakeClient:
    """Records every call; replies from a {(method, path): payload} map, falling
    back to a generic ok so submit paths don't need every route spelled out."""

    def __init__(self, replies, calls):
        self._replies = replies
        self._calls = calls

    def _reply(self, method, path, default):
        return _Resp(self._replies.get((method, path), default))

    def get(self, path, params=None):
        self._calls.append(("GET", path, params))
        return self._reply("GET", path, {"ok": True})

    def post(self, path, json=None):
        self._calls.append(("POST", path, json))
        return self._reply("POST", path, {"ok": True, "job_id": "j1"})

    def request(self, method, path, json=None):
        self._calls.append((method, path, json))
        return self._reply(method, path, {"ok": True})


@contextmanager
def _patched(replies, calls):
    @contextmanager
    def fake():
        yield _FakeClient(replies, calls)

    orig = mcp_server._client
    mcp_server._client = fake
    try:
        yield
    finally:
        mcp_server._client = orig


def test_create_set_posts_name_and_returns_id():
    calls = []
    replies = {("POST", "/api/sets"): {"ok": True, "set": {
        "id": "set-abc", "name": "Summer drop", "created_at": "2026-07-31T10:00:00Z"}}}
    with _patched(replies, calls):
        out = mcp_server.create_set("Summer drop")
    assert calls[0] == ("POST", "/api/sets", {"name": "Summer drop"})
    assert out["set_id"] == "set-abc"
    assert out["name"] == "Summer drop"


def test_create_set_surfaces_backend_error():
    with _patched({("POST", "/api/sets"): {"ok": False, "error": "name is required"}}, []):
        with pytest.raises(RuntimeError, match="name is required"):
            mcp_server.create_set("")


def test_list_sets_returns_names_with_counts():
    replies = {("GET", "/api/sets"): {"ok": True, "sets": [
        {"id": "set-b", "name": "B", "created_at": "2026-07-31T10:00:00Z", "item_count": 3},
        {"id": "set-a", "name": "A", "created_at": "2026-07-30T10:00:00Z", "item_count": 0},
    ]}}
    with _patched(replies, []):
        out = mcp_server.list_sets()
    assert out["count"] == 2
    assert [s["name"] for s in out["sets"]] == ["B", "A"]
    assert out["sets"][0]["item_count"] == 3


def test_add_to_set_posts_items():
    calls = []
    replies = {("POST", "/api/sets/set-abc/items"): {"ok": True, "added": 2}}
    with _patched(replies, calls):
        out = mcp_server.add_to_set("set-abc", ["/outputs/a.png", "/outputs/b.mp4"])
    assert calls[0] == ("POST", "/api/sets/set-abc/items",
                       {"items": [{"url": "/outputs/a.png"}, {"url": "/outputs/b.mp4"}]})
    assert out["added"] == 2


def test_add_to_set_requires_urls():
    with pytest.raises(ValueError, match="urls"):
        mcp_server.add_to_set("set-abc", [])


def test_add_to_set_unknown_set_raises():
    replies = {("POST", "/api/sets/set-nope/items"): {"ok": False, "error": "set not found"}}
    with _patched(replies, []):
        with pytest.raises(RuntimeError, match="set not found"):
            mcp_server.add_to_set("set-nope", ["/outputs/a.png"])


def test_submit_jobs_forwards_set_id():
    calls = []
    with _patched({}, calls):
        mcp_server.submit_jobs({"1": {"class_type": "X", "inputs": {}}},
                               count=2, set_id="set-abc")
    bodies = [c[2] for c in calls if c[1].endswith("/run")]
    assert len(bodies) == 2
    assert all(b["set_id"] == "set-abc" for b in bodies)


def test_submit_jobs_without_set_id_sends_none():
    calls = []
    with _patched({}, calls):
        mcp_server.submit_jobs({"1": {"class_type": "X", "inputs": {}}})
    assert calls[0][2]["set_id"] is None


def test_submit_batch_forwards_set_id_to_every_job():
    calls = []
    with _patched({}, calls):
        mcp_server.submit_batch(
            {"1": {"class_type": "X", "inputs": {}}},
            jobs=[{"overrides": {"6.text": "a"}}, {"overrides": {"6.text": "b"}}],
            set_id="set-abc",
        )
    bodies = [c[2] for c in calls if c[1].endswith("/run")]
    assert [b["set_id"] for b in bodies] == ["set-abc", "set-abc"]
