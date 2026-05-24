"""BlockFlow-local metadata for LoRAs on the ComfyGen volume.

Volume listing (via `comfy-gen list loras`) is source of truth for what
exists. This table is enrichment: where each file came from, its trigger
words, base model, etc. Rows whose files are no longer on the volume are
pruned at reconcile time.

Keyed by filename (single-endpoint by design — BlockFlow does not support
multiple ComfyGen endpoints today).
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any

from backend import config

DB_PATH = config.ROOT_DIR / "run_history.db"
_lock = threading.Lock()

VALID_SOURCES = {"civitai", "hf", "url", "unknown"}


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def init_db() -> None:
    with _lock:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = _get_conn()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS lora_metadata (
                    filename TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    source_id TEXT,
                    base_model TEXT,
                    trigger_words TEXT NOT NULL DEFAULT '[]',
                    size_bytes INTEGER,
                    downloaded_at TEXT,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.commit()
        finally:
            conn.close()


def upsert(
    *,
    filename: str,
    source: str,
    source_id: str | None = None,
    base_model: str | None = None,
    trigger_words: list[str] | None = None,
    size_bytes: int | None = None,
    downloaded_at: str | None = None,
) -> None:
    if source not in VALID_SOURCES:
        raise ValueError(f"source must be one of {VALID_SOURCES}, got {source!r}")
    words_json = json.dumps(trigger_words or [], ensure_ascii=False)
    dl = downloaded_at or _now_iso()
    now = _now_iso()
    with _lock:
        conn = _get_conn()
        try:
            conn.execute(
                """
                INSERT INTO lora_metadata (
                    filename, source, source_id, base_model, trigger_words,
                    size_bytes, downloaded_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filename) DO UPDATE SET
                    source=excluded.source,
                    source_id=excluded.source_id,
                    base_model=excluded.base_model,
                    trigger_words=excluded.trigger_words,
                    size_bytes=excluded.size_bytes,
                    downloaded_at=COALESCE(excluded.downloaded_at, lora_metadata.downloaded_at),
                    updated_at=excluded.updated_at
                """,
                (filename, source, source_id, base_model, words_json, size_bytes, dl, now),
            )
            conn.commit()
        finally:
            conn.close()


def get(filename: str) -> dict[str, Any] | None:
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM lora_metadata WHERE filename = ?", (filename,)
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


def get_all() -> dict[str, dict[str, Any]]:
    conn = _get_conn()
    try:
        rows = conn.execute("SELECT * FROM lora_metadata").fetchall()
    finally:
        conn.close()
    return {r["filename"]: _row_to_dict(r) for r in rows}


def delete(filename: str) -> bool:
    with _lock:
        conn = _get_conn()
        try:
            cur = conn.execute("DELETE FROM lora_metadata WHERE filename = ?", (filename,))
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()


def delete_many(filenames: list[str]) -> int:
    if not filenames:
        return 0
    with _lock:
        conn = _get_conn()
        try:
            placeholders = ",".join("?" * len(filenames))
            cur = conn.execute(
                f"DELETE FROM lora_metadata WHERE filename IN ({placeholders})", tuple(filenames)
            )
            conn.commit()
            return int(cur.rowcount)
        finally:
            conn.close()


def reconcile(volume_filenames: list[str]) -> dict[str, Any]:
    """Merge volume listing with DB rows, pruning orphans.

    Returns {merged: [row, ...], pruned: [filename, ...]}. Files on the
    volume with no DB row appear in merged with source='unknown'.
    """
    db_rows = get_all()
    volume_set = set(volume_filenames)
    db_set = set(db_rows.keys())

    orphans = sorted(db_set - volume_set)
    if orphans:
        delete_many(orphans)

    merged: list[dict[str, Any]] = []
    for fname in volume_filenames:
        if fname in db_rows:
            merged.append(db_rows[fname])
        else:
            merged.append(_unknown_row(fname))
    return {"merged": merged, "pruned": orphans}


def _unknown_row(filename: str) -> dict[str, Any]:
    return {
        "filename": filename,
        "source": "unknown",
        "source_id": None,
        "base_model": None,
        "trigger_words": [],
        "size_bytes": None,
        "downloaded_at": None,
        "updated_at": None,
    }


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    d = dict(row)
    raw = d.get("trigger_words") or "[]"
    try:
        d["trigger_words"] = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        d["trigger_words"] = []
    return d
