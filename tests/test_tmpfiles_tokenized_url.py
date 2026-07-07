"""tmpfiles.org's /dl/<id>/<file> path now returns an HTML preview page; the real
download URL is a tokenized /dl/<timestamp>.<token>/<id>/<file> link embedded in it."""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import tmpfiles

TOKENIZED = "https://tmpfiles.org/dl/1751980000.deadbeef01/wTwzvb8k77mC/dummy.png"
PREVIEW_HTML = f'<html><body><a href="{TOKENIZED}">Download</a></body></html>'.encode()


class _FakeResponse(io.BytesIO):
    def __init__(self, body: bytes, content_type: str):
        super().__init__(body)
        self.headers = {"Content-Type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_scrapes_tokenized_url_from_preview_page(monkeypatch):
    monkeypatch.setattr(
        tmpfiles.urllib.request,
        "urlopen",
        lambda req, timeout=0: _FakeResponse(PREVIEW_HTML, "text/html; charset=utf-8"),
    )
    assert (
        tmpfiles.resolve_tokenized_url("https://tmpfiles.org/dl/wTwzvb8k77mC/dummy.png")
        == TOKENIZED
    )


def test_already_tokenized_url_passes_through_without_fetch(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not fetch")

    monkeypatch.setattr(tmpfiles.urllib.request, "urlopen", boom)
    assert tmpfiles.resolve_tokenized_url(TOKENIZED) == TOKENIZED


def test_non_tmpfiles_url_passes_through(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("should not fetch")

    monkeypatch.setattr(tmpfiles.urllib.request, "urlopen", boom)
    assert tmpfiles.resolve_tokenized_url("https://example.com/x.png") == "https://example.com/x.png"


def test_falls_back_to_input_url_on_fetch_error(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")

    monkeypatch.setattr(tmpfiles.urllib.request, "urlopen", boom)
    url = "https://tmpfiles.org/dl/wTwzvb8k77mC/dummy.png"
    assert tmpfiles.resolve_tokenized_url(url) == url


def test_direct_file_response_returns_url_unchanged(monkeypatch):
    monkeypatch.setattr(
        tmpfiles.urllib.request,
        "urlopen",
        lambda req, timeout=0: _FakeResponse(b"\x89PNG...", "image/png"),
    )
    url = "https://tmpfiles.org/dl/wTwzvb8k77mC/dummy.png"
    assert tmpfiles.resolve_tokenized_url(url) == url
