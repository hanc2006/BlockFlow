from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CREDENTIAL_NAMES = {
    "runpod_api_key",
    "openrouter_api_key",
    "civitai_api_key",
    "hf_token",
    "imgbb_api_key",
    "tmpfiles_api_key",
    "topaz_api_key",
    "elevenlabs_api_key",
    "piapi_api_key",
    "r2_endpoint_url",
    "r2_access_key_id",
    "r2_secret_access_key",
    "r2_bucket",
    "r2_region",
}

CONST_RE = re.compile(r"\bconst\s+([A-Z0-9_]+)\s*=\s*['\"]([^'\"]+)['\"]")
STORAGE_RE = re.compile(r"\blocalStorage\.(?:getItem|setItem|removeItem)\(([^),]+)")


def _frontend_sources() -> list[Path]:
    roots = [ROOT / "frontend" / "src", ROOT / "custom_blocks"]
    return [
        path
        for root in roots
        for path in root.rglob("*")
        if path.suffix in {".ts", ".tsx"}
        and "node_modules" not in path.parts
    ]


def test_credentials_are_not_read_or_written_from_browser_local_storage() -> None:
    violations: list[str] = []
    for path in _frontend_sources():
        text = path.read_text()
        constants = dict(CONST_RE.findall(text))
        for line_no, line in enumerate(text.splitlines(), start=1):
            match = STORAGE_RE.search(line)
            if not match:
                continue
            key_expr = match.group(1).strip()
            key = key_expr.strip("'\"") if key_expr[:1] in {"'", '"'} else constants.get(key_expr)
            if key in CREDENTIAL_NAMES:
                rel = path.relative_to(ROOT)
                violations.append(f"{rel}:{line_no}: {line.strip()}")

    assert violations == []
