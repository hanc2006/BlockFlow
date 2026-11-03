"""Catalog vocabulary: CivitAI base models -> family / media, type mapping."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from backend.catalog import vocab  # noqa: E402


@pytest.mark.parametrize(
    ("raw", "family"),
    [
        ("Flux.1 D", "Flux"),
        ("Flux.1 Kontext", "Flux Kontext"),
        ("Flux.2 Klein 4B", "Flux.2"),
        ("Pony", "Pony"),
        ("Illustrious", "Illustrious"),
        ("SDXL 1.0", "SDXL"),
        ("SD 1.5", "SD1.5"),
        ("Wan Video 2.2 I2V-A14B", "Wan"),
        ("LTXV 2.3", "LTXV"),
        ("ZImageTurbo", "Z-Image"),
        ("HiDream-O1", "HiDream"),
        ("Hunyuan Video", "HunyuanVideo"),
    ],
)
def test_family_of_known_base_models(raw: str, family: str) -> None:
    assert vocab.family_of(raw) == family


def test_family_overrides_keep_incompatible_bases_apart() -> None:
    assert vocab.family_of("Hunyuan 1") == "Hunyuan Image"
    assert vocab.media_of("Hunyuan 1") == "image"
    assert vocab.family_of("Pony V7") == "Pony V7"
    assert "Pony V7" not in vocab.base_models_for(family="Pony")


@pytest.mark.parametrize("raw", ["", None, "Seedream", "Other"])
def test_family_of_unknown_is_other(raw) -> None:
    assert vocab.family_of(raw) == "Other"


@pytest.mark.parametrize(
    ("raw", "media"),
    [
        ("Wan Video 14B i2v 480p", "video"),
        ("LTXV2", "video"),
        ("Hunyuan Video", "video"),
        ("MiniMax H3", "video"),
        ("Flux.1 D", "image"),
        ("ACE Audio", "audio"),
        (None, "image"),
    ],
)
def test_media_of(raw, media: str) -> None:
    assert vocab.media_of(raw) == media


def test_base_models_for_family_returns_exact_civitai_spellings() -> None:
    flux = vocab.base_models_for(family="Flux")
    assert "Flux.1 D" in flux and "Flux.1 S" in flux
    # Kontext and Flux.2 are separate families, not plain Flux.
    assert "Flux.1 Kontext" not in flux
    assert "Flux.2 D" not in flux
    assert all(b in vocab.CIVITAI_BASE_MODELS for b in flux)


def test_base_models_for_media_video_only_contains_video() -> None:
    video = vocab.base_models_for(media="video")
    assert "Wan Video 2.2 I2V-A14B" in video
    assert "SDXL 1.0" not in video
    assert all(vocab.media_of(b) == "video" for b in video)


def test_base_models_for_unknown_family_is_empty() -> None:
    assert vocab.base_models_for(family="NoSuchFamily") == []


def test_families_lists_each_family_once_with_media() -> None:
    fams = vocab.families()
    names = [f["family"] for f in fams]
    assert len(names) == len(set(names))
    wan = next(f for f in fams if f["family"] == "Wan")
    assert wan["media"] == "video"
    assert "Wan Video 2.2 T2V-A14B" in wan["base_models"]


def test_type_mapping_round_trip() -> None:
    assert vocab.civitai_types_for("lora") == ["LORA", "LoCon", "DoRA"]
    assert vocab.civitai_types_for("checkpoint") == ["Checkpoint"]
    assert vocab.type_from_civitai("LoCon") == "lora"
    assert vocab.type_from_civitai("Checkpoint") == "checkpoint"
    assert vocab.type_from_civitai("SomethingNew") == "other"
    with pytest.raises(ValueError):
        vocab.civitai_types_for("nope")


def test_dest_folder_for_type() -> None:
    assert vocab.dest_folder("lora") == "loras"
    assert vocab.dest_folder("checkpoint") == "checkpoints"
    assert vocab.dest_folder("upscaler") == "upscale_models"
    assert vocab.dest_folder("other") is None
