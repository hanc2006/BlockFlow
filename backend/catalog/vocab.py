"""Catalog vocabulary: base models, families, media kinds, model types."""
from __future__ import annotations

from backend.catalog import basemodel

# CivitAI's `baseModels` vocabulary, exact spelling (a typo in the search filter
# silently returns zero results). Copied from comfyui-tiny-model-manager
# (MIT, (c) 2026 Zellione), frontend/src/app/utils/base-models.ts @ 4438fb5,
# which documents it as harvested from and verified against the live API.
# Re-harvest rather than hand-adding when it goes stale.
CIVITAI_BASE_MODELS: list[str] = [
    # Stable Diffusion
    "SD 1.4", "SD 1.5", "SD 1.5 LCM", "SD 1.5 Hyper", "SD 2.0", "SD 2.1", "SD 2.1 768",
    "SDXL 0.9", "SDXL 1.0", "SDXL 1.0 LCM", "SDXL Lightning", "SDXL Hyper", "Stable Cascade",
    # Anime / illustration finetunes
    "Pony", "Pony V7", "Illustrious", "NoobAI", "Anima",
    # Flux
    "Flux.1 D", "Flux.1 S", "Flux.1 Kontext", "Flux.1 Krea", "Flux.2 D",
    "Flux.2 Klein 4B", "Flux.2 Klein 4B-base", "Flux.2 Klein 9B", "Flux.2 Klein 9B-base", "Krea 2",
    # Other image models
    "Qwen", "Qwen 2", "ZImageBase", "ZImageTurbo", "Chroma", "HiDream", "HiDream-O1", "Hunyuan 1",
    "Kolors", "Lumina", "PixArt a", "PixArt E", "Ernie", "Seedream", "Ideogram 4.0", "Lens",
    "MageFlow", "ODOR",
    # Video
    "LTXV", "LTXV2", "LTXV 2.3", "Wan Video", "Wan Video 1.3B t2v", "Wan Video 14B t2v",
    "Wan Video 14B i2v 480p", "Wan Video 14B i2v 720p", "Wan Video 2.2 TI2V-5B",
    "Wan Video 2.2 T2V-A14B", "Wan Video 2.2 I2V-A14B", "Wan Video 2.5 T2V", "Wan Video 2.5 I2V",
    "Wan Video 2.7", "MiniMax H3", "Hunyuan Video", "CogVideoX", "Mochi",
    # Audio and utility
    "ACE Audio", "Upscaler", "Other",
]

OTHER = "Other"
MEDIA = ("image", "video", "audio")
VIDEO_FAMILIES = {"Wan", "HunyuanVideo", "LTXV", "Mochi", "CogVideoX", "SVD"}
# Base models no family rule recognizes but whose media kind is known.
_MEDIA_OVERRIDES = {"MiniMax H3": "video", "ACE Audio": "audio"}
# Base models the generic family rules put in the wrong family. Kept separate
# so LoRAs for them are never offered as compatible with the wrong base.
_FAMILY_OVERRIDES = {
    "Hunyuan 1": "Hunyuan Image",  # image model; the "hunyuan" rule means HunyuanVideo
    "Pony V7": "Pony V7",          # different architecture from SDXL-based Pony
}

# BlockFlow type -> (CivitAI `types` values, ComfyUI models folder).
# The first CivitAI value is the canonical one when mapping back.
TYPES: dict[str, tuple[list[str], str | None]] = {
    "checkpoint": (["Checkpoint"], "checkpoints"),
    "lora": (["LORA", "LoCon", "DoRA"], "loras"),
    "embedding": (["TextualInversion"], "embeddings"),
    "vae": (["VAE"], "vae"),
    "controlnet": (["Controlnet"], "controlnet"),
    "upscaler": (["Upscaler"], "upscale_models"),
    "motion": (["MotionModule"], "animatediff_models"),
    "workflow": (["Workflows"], None),
}
_TYPE_FROM_CIVITAI = {raw: ours for ours, (raws, _) in TYPES.items() for raw in raws}


def family_of(base_model: str | None) -> str:
    """CivitAI baseModel / HF base_model / file name -> family, or 'Other'."""
    if base_model in _FAMILY_OVERRIDES:
        return _FAMILY_OVERRIDES[base_model]
    return basemodel.from_text(base_model) or OTHER


def media_of(base_model: str | None) -> str:
    if base_model in _MEDIA_OVERRIDES:
        return _MEDIA_OVERRIDES[base_model]
    return "video" if family_of(base_model) in VIDEO_FAMILIES else "image"


def base_models_for(family: str | None = None, media: str | None = None) -> list[str]:
    """CivitAI baseModel values matching a family and/or media kind."""
    return [
        b for b in CIVITAI_BASE_MODELS
        if (family is None or family_of(b) == family)
        and (media is None or media_of(b) == media)
    ]


def families() -> list[dict]:
    """[{family, media, base_models}] in vocabulary order; 'Other' last."""
    out: dict[str, dict] = {}
    for b in CIVITAI_BASE_MODELS:
        fam = family_of(b)
        entry = out.setdefault(fam, {"family": fam, "media": media_of(b), "base_models": []})
        entry["base_models"].append(b)
    other = out.pop(OTHER, None)
    return list(out.values()) + ([other] if other else [])


def civitai_types_for(type_: str) -> list[str]:
    if type_ not in TYPES:
        raise ValueError(f"unknown model type {type_!r}")
    return list(TYPES[type_][0])


def type_from_civitai(raw: str | None) -> str:
    return _TYPE_FROM_CIVITAI.get(raw or "", "other")


def dest_folder(type_: str) -> str | None:
    entry = TYPES.get(type_)
    return entry[1] if entry else None
