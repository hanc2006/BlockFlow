"""Regression coverage for `_download_output` filename construction.

Locks in audit item B.2.2 (sgs-ui-h1c.1.5): the extension must be extracted
from the URL *path*, not naively from the trailing chars — otherwise S3
presigned-URL query strings (`?X-Amz-Signature=...&Expires=...`) bleed into
the saved filename as `<id>.mp4?X-Amz-Signature=...`.
"""
from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "comfy_gen_block_dl", ROOT / "custom_blocks" / "comfy_gen" / "backend.block.py"
)
comfy_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(comfy_gen)


class _FakeResp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False


@pytest.fixture
def patched_io(monkeypatch, tmp_path):
    monkeypatch.setattr(comfy_gen.config, "LOCAL_OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(
        comfy_gen.urllib.request,
        "urlopen",
        lambda *_a, **_k: _FakeResp(b"\x00" * 16),
    )
    return tmp_path


def test_extension_stripped_of_query_string(patched_io):
    url = "https://s3.example.com/outputs/clip.mp4?X-Amz-Signature=abcd&Expires=999"
    path = comfy_gen._download_output(url, "abcdef01-rest-of-id")
    assert path.suffix == ".mp4"
    assert "?" not in path.name
    assert "X-Amz" not in path.name
    assert path.name.endswith(".mp4")


def test_known_video_and_image_exts_pass_through(patched_io):
    for ext in ("png", "jpg", "jpeg", "webp", "mp4", "webm", "gif"):
        url = f"https://s3.example.com/foo.{ext}?sig=x"
        path = comfy_gen._download_output(url, "deadbeef-job")
        assert path.suffix == f".{ext}"


def test_unknown_extension_falls_back_to_png(patched_io):
    url = "https://s3.example.com/weird.bin?sig=x"
    path = comfy_gen._download_output(url, "abcdef01-rest")
    assert path.suffix == ".png"


def test_no_query_string_still_works(patched_io):
    path = comfy_gen._download_output("https://s3.example.com/a.png", "abcdef01-rest")
    assert path.suffix == ".png"
