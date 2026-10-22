"""Shared GET helper: one place that turns HTTP/network failures into
CatalogUpstreamError. Providers pass their own `requests` module so tests can
mock each provider at its boundary."""
from __future__ import annotations

from typing import Any

from backend.catalog.errors import CatalogUpstreamError

TIMEOUT_SEC = 20


def get_json(requests: Any, source: str, url: str, *, params: dict | None = None,
             headers: dict | None = None) -> Any:
    try:
        resp = requests.get(url, params=params or {}, headers=headers or {}, timeout=TIMEOUT_SEC)
    except Exception as exc:  # curl_cffi raises its own error types
        raise CatalogUpstreamError(source, None, str(exc)) from exc
    if resp.status_code >= 400:
        raise CatalogUpstreamError(source, resp.status_code, (resp.text or "")[:300])
    try:
        return resp.json()
    except ValueError as exc:
        raise CatalogUpstreamError(source, resp.status_code, "response is not JSON") from exc


def bearer(token: str | None) -> dict:
    return {"Authorization": f"Bearer {token}"} if token else {}
