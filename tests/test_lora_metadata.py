"""DB tests for the lora_metadata table (sgs-ui-eqc.1).

The table tracks BlockFlow's local memory of where each LoRA on the
ComfyGen volume came from. Volume listing is source of truth; this table
is enrichment + reconcile state.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402


@pytest.fixture
def lora_meta(tmp_path, monkeypatch):
    """Fresh DB per test, isolated from the developer's run_history.db."""
    from backend import config  # noqa: PLC0415

    monkeypatch.setattr(config, "ROOT_DIR", tmp_path)
    from backend import lora_metadata as mod  # noqa: PLC0415

    monkeypatch.setattr(mod, "DB_PATH", tmp_path / "run_history.db")
    mod.init_db()
    return mod


def test_init_db_is_idempotent(lora_meta) -> None:
    lora_meta.init_db()
    lora_meta.init_db()  # second call must not raise


def test_upsert_then_get_round_trips(lora_meta) -> None:
    lora_meta.upsert(
        filename="char_v2.safetensors",
        source="civitai",
        source_id="67890",
        base_model="Flux.1 D",
        trigger_words=["trigger one", "trigger two"],
        size_bytes=147483648,
    )
    row = lora_meta.get("char_v2.safetensors")
    assert row is not None
    assert row["filename"] == "char_v2.safetensors"
    assert row["source"] == "civitai"
    assert row["source_id"] == "67890"
    assert row["base_model"] == "Flux.1 D"
    assert row["trigger_words"] == ["trigger one", "trigger two"]
    assert row["size_bytes"] == 147483648
    assert row["downloaded_at"] is not None


def test_upsert_overwrites_existing(lora_meta) -> None:
    lora_meta.upsert(filename="a.safetensors", source="url", source_id="https://x/a")
    lora_meta.upsert(
        filename="a.safetensors", source="civitai", source_id="999",
        trigger_words=["w"],
    )
    row = lora_meta.get("a.safetensors")
    assert row["source"] == "civitai"
    assert row["source_id"] == "999"
    assert row["trigger_words"] == ["w"]


def test_get_missing_returns_none(lora_meta) -> None:
    assert lora_meta.get("nonexistent.safetensors") is None


def test_get_all_returns_dict_by_filename(lora_meta) -> None:
    lora_meta.upsert(filename="a.safetensors", source="civitai", source_id="1")
    lora_meta.upsert(filename="b.safetensors", source="hf", source_id="https://hf/b")
    rows = lora_meta.get_all()
    assert set(rows.keys()) == {"a.safetensors", "b.safetensors"}
    assert rows["a.safetensors"]["source"] == "civitai"
    assert rows["b.safetensors"]["source"] == "hf"


def test_delete_existing_returns_true(lora_meta) -> None:
    lora_meta.upsert(filename="a.safetensors", source="civitai", source_id="1")
    assert lora_meta.delete("a.safetensors") is True
    assert lora_meta.get("a.safetensors") is None


def test_delete_missing_returns_false(lora_meta) -> None:
    assert lora_meta.delete("ghost.safetensors") is False


def test_delete_many_returns_count_of_dropped(lora_meta) -> None:
    lora_meta.upsert(filename="a.safetensors", source="civitai", source_id="1")
    lora_meta.upsert(filename="b.safetensors", source="civitai", source_id="2")
    lora_meta.upsert(filename="c.safetensors", source="civitai", source_id="3")
    n = lora_meta.delete_many(["a.safetensors", "c.safetensors", "ghost.safetensors"])
    assert n == 2
    assert lora_meta.get("b.safetensors") is not None
    assert lora_meta.get("a.safetensors") is None


def test_trigger_words_default_empty_list(lora_meta) -> None:
    lora_meta.upsert(filename="a.safetensors", source="url", source_id="https://x")
    row = lora_meta.get("a.safetensors")
    assert row["trigger_words"] == []


# ---- reconcile ----

def test_reconcile_merges_volume_and_db(lora_meta) -> None:
    lora_meta.upsert(filename="a.safetensors", source="civitai", source_id="1",
                     trigger_words=["w"])
    result = lora_meta.reconcile(["a.safetensors"])
    assert len(result["merged"]) == 1
    assert result["merged"][0]["filename"] == "a.safetensors"
    assert result["merged"][0]["source"] == "civitai"
    assert result["pruned"] == []


def test_reconcile_file_only_yields_unknown_source(lora_meta) -> None:
    result = lora_meta.reconcile(["legacy.safetensors"])
    assert len(result["merged"]) == 1
    row = result["merged"][0]
    assert row["filename"] == "legacy.safetensors"
    assert row["source"] == "unknown"
    assert row["source_id"] is None
    assert row["trigger_words"] == []
    assert result["pruned"] == []


def test_reconcile_orphan_db_rows_are_pruned(lora_meta) -> None:
    lora_meta.upsert(filename="gone.safetensors", source="civitai", source_id="1")
    lora_meta.upsert(filename="here.safetensors", source="civitai", source_id="2")
    result = lora_meta.reconcile(["here.safetensors"])
    assert {r["filename"] for r in result["merged"]} == {"here.safetensors"}
    assert result["pruned"] == ["gone.safetensors"]
    # DB row actually dropped
    assert lora_meta.get("gone.safetensors") is None


def test_reconcile_empty_volume_prunes_all_rows(lora_meta) -> None:
    lora_meta.upsert(filename="a.safetensors", source="civitai", source_id="1")
    lora_meta.upsert(filename="b.safetensors", source="civitai", source_id="2")
    result = lora_meta.reconcile([])
    assert result["merged"] == []
    assert set(result["pruned"]) == {"a.safetensors", "b.safetensors"}


def test_reconcile_empty_db_yields_all_unknown(lora_meta) -> None:
    result = lora_meta.reconcile(["a.safetensors", "b.safetensors"])
    assert len(result["merged"]) == 2
    assert all(r["source"] == "unknown" for r in result["merged"])
    assert result["pruned"] == []
