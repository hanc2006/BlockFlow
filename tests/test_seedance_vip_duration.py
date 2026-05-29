"""Tests for the seedance VIP `duration` ⇄ `video_urls` interaction.

PiAPI VIP models (`seedance-2-preview-vip`, `seedance-2-fast-preview-vip`)
set output length = input video length when the request uses the auto-length
sentinel `duration: 0`. The PiAPI VIP video-reference request example omits
`duration`, but completed VIP video-reference responses echo `duration: 0`.

Our backend used to send `duration: 5`, then briefly omitted `duration`.
PiAPI answered those runs with "invalid duration, use '5' as default", capping
a 9s input video's output to 5s. These tests pin the corrected behavior: send
`duration: 0` when `video_urls` is present, keep enum durations otherwise.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "seedance_block_duration",
    ROOT / "custom_blocks" / "seedance" / "backend.block.py",
)
mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = mod
_spec.loader.exec_module(mod)

VIP_TYPES = ["seedance-2-preview-vip", "seedance-2-fast-preview-vip"]


@pytest.mark.parametrize("task_type", VIP_TYPES)
def test_vip_with_video_sends_auto_duration_zero(task_type):
    """With a video reference, duration must be the auto-length sentinel."""
    payload = mod._validate_and_build_input(
        {
            "prompt": "make it cinematic",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "video_urls": ["https://tmpfiles.org/dl/abc/clip.mp4"],
        },
        task_type,
    )
    assert payload["duration"] == 0
    assert payload["video_urls"] == ["https://tmpfiles.org/dl/abc/clip.mp4"]


@pytest.mark.parametrize("task_type", VIP_TYPES)
def test_vip_without_video_keeps_duration(task_type):
    """Image/text VIP runs still carry the chosen duration enum (5/10/15)."""
    payload = mod._validate_and_build_input(
        {
            "prompt": "a woman walks",
            "duration": 10,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "image_urls": ["https://tmpfiles.org/dl/abc/face.png"],
        },
        task_type,
    )
    assert payload["duration"] == 10


@pytest.mark.parametrize("task_type", VIP_TYPES)
def test_vip_with_video_skips_duration_enum_validation(task_type):
    """A non-enum duration is harmless when a video ref is present (it's ignored),
    so it must not raise — the value is irrelevant upstream."""
    payload = mod._validate_and_build_input(
        {
            "prompt": "x",
            "duration": 9,  # not in {5,10,15}; ignored because video_urls present
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "video_urls": ["https://tmpfiles.org/dl/abc/clip.mp4"],
        },
        task_type,
    )
    assert payload["duration"] == 0


def test_run_route_passes_auto_duration_zero_to_job(monkeypatch):
    """The HTTP route must pass the corrected PiAPI payload to the job runner."""
    captured: dict[str, object] = {}

    def fake_run_job(job_id, api_key, task_type, input_payload):
        captured.update({
            "job_id": job_id,
            "api_key": api_key,
            "task_type": task_type,
            "input_payload": input_payload,
        })
        return object()

    def fake_create_task(awaitable):
        captured["scheduled"] = awaitable
        return object()

    monkeypatch.setattr(mod, "_run_job", fake_run_job)
    monkeypatch.setattr(mod.asyncio, "create_task", fake_create_task)
    mod.JOBS.clear()

    app = FastAPI()
    app.include_router(mod.router)
    client = TestClient(app)

    resp = client.post(
        "/run",
        json={
            "piapi_api_key": "test-key",
            "task_type": "seedance-2-preview-vip",
            "prompt": "make it cinematic",
            "duration": 5,
            "resolution": "720p",
            "aspect_ratio": "16:9",
            "video_urls": ["https://tmpfiles.org/dl/abc/clip.mp4"],
        },
    )

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert captured["task_type"] == "seedance-2-preview-vip"
    assert captured["input_payload"] == {
        "prompt": "make it cinematic",
        "aspect_ratio": "16:9",
        "resolution": "720p",
        "video_urls": ["https://tmpfiles.org/dl/abc/clip.mp4"],
        "duration": 0,
    }
