"""HTTP client for the authenticated ComfyGen dedicated-host server."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import quote, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def normalize_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url.strip())
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Server URL must be HTTP(S) without embedded credentials, query, or fragment")
    try:
        parsed.port
    except ValueError as exc:
        raise ValueError("Server URL has an invalid port") from exc
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", ""))


def _urlopen(req: Request, timeout: int):
    return build_opener(_NoRedirect).open(req, timeout=timeout)


def _request_bytes(
    base_url: str,
    token: str,
    method: str,
    path: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[bytes, str]:
    url = f"{normalize_base_url(base_url)}/{path.lstrip('/')}"
    request_headers = {"Authorization": f"Bearer {token}"}
    request_headers.update(headers or {})
    req = Request(url, data=body, headers=request_headers, method=method.upper())
    try:
        with _urlopen(req, timeout=timeout) as response:
            return response.read(), response.headers.get("Content-Type", "")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Compatibility server returned HTTP {exc.code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Could not reach compatibility server: {exc}") from exc


def request_json(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 30,
) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    response, _ = _request_bytes(
        base_url, token, method, path, body=body, headers=headers, timeout=timeout,
    )
    try:
        parsed = json.loads(response)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Compatibility server returned invalid JSON") from exc
    if not isinstance(parsed, dict):
        raise RuntimeError("Compatibility server returned a non-object JSON response")
    if "error" in parsed:
        raise RuntimeError(str(parsed["error"]))
    return parsed


def upload_input(
    base_url: str,
    token: str,
    field: str,
    local_path: str | Path,
) -> dict[str, str]:
    if field not in {"image", "video"}:
        raise ValueError("Input field must be image or video")
    path = Path(local_path)
    body, _ = _request_bytes(
        base_url,
        token,
        "PUT",
        f"/upload/{field}",
        body=path.read_bytes(),
        headers={"Content-Type": "application/octet-stream", "X-Filename": path.name},
        timeout=120,
    )
    try:
        result = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RuntimeError("Compatibility server returned invalid upload JSON") from exc
    if (
        not isinstance(result, dict)
        or not isinstance(result.get("name"), str)
        or result.get("field") != field
    ):
        raise RuntimeError("Compatibility server returned an invalid upload descriptor")
    return {
        "name": result["name"],
        "subfolder": str(result.get("subfolder") or ""),
        "field": field,
    }


def download_output(
    base_url: str,
    token: str,
    job_id: str,
    index: int,
) -> tuple[bytes, str]:
    if index < 0:
        raise ValueError("Output index must not be negative")
    return _request_bytes(
        base_url,
        token,
        "GET",
        f"/outputs/{quote(job_id, safe='')}/{index}",
        timeout=120,
    )
