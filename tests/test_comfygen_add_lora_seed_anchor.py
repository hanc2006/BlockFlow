"""Runtime-added LoRAs must be able to seed the FIRST loader onto a workflow that
has no existing LoRA loader, by anchoring onto the base model loader
(UNETLoader/CheckpointLoader). Previously add-LoRA hard-errored ("no LoRA loader
to anchor onto"), which made clean no-LoRA presets unable to add LoRAs in-app.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_spec = importlib.util.spec_from_file_location(
    "comfy_gen_block_seed", ROOT / "custom_blocks" / "comfy_gen" / "backend.block.py"
)
comfy_gen = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(comfy_gen)

_resolve = comfy_gen._resolve_added_loras
_insert = comfy_gen._insert_lora_nodes


def _no_lora_wf() -> dict:
    """UNETLoader -> KSampler, no LoRA loader (the Krea2-without-LoRAs shape)."""
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "krea2.safetensors"}},
        "2": {"class_type": "KSampler", "inputs": {"model": ["1", 0], "seed": 1}},
    }


def _ckpt_wf() -> dict:
    return {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": "x.safetensors"}},
        "3": {"class_type": "KSampler", "inputs": {"model": ["4", 0]}},
    }


def _with_lora_wf() -> dict:
    return {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "base.safetensors"}},
        "16": {"class_type": "LoraLoaderModelOnly",
               "inputs": {"lora_name": "a.safetensors", "strength_model": 1.0, "model": ["1", 0]}},
        "2": {"class_type": "KSampler", "inputs": {"model": ["16", 0]}},
    }


def test_resolve_auto_anchors_onto_model_loader_when_no_lora():
    resolved, err = _resolve(_no_lora_wf(), [{"lora_name": "extra.safetensors"}])
    assert err is None, err
    assert resolved[0]["chain_anchor"] == "1"  # the UNETLoader
    assert resolved[0]["class_type"] == "LoraLoaderModelOnly"


def test_insert_splices_first_loader_after_model_loader():
    wf = _no_lora_wf()
    resolved, err = _resolve(wf, [{"lora_name": "extra.safetensors", "strength_model": 0.8}])
    assert err is None
    out = _insert(wf, resolved)
    # a new LoraLoaderModelOnly now exists, fed by the UNETLoader's MODEL
    new = [nid for nid, n in out.items()
           if n.get("class_type") == "LoraLoaderModelOnly"]
    assert len(new) == 1
    nid = new[0]
    assert out[nid]["inputs"]["model"] == ["1", 0]
    assert out[nid]["inputs"]["lora_name"] == "extra.safetensors"
    assert out[nid]["inputs"]["strength_model"] == 0.8
    # the KSampler now consumes the LoRA's MODEL, not the raw UNET
    assert out["2"]["inputs"]["model"] == [nid, 0]


def test_checkpoint_loader_is_a_valid_seed_anchor():
    wf = _ckpt_wf()
    resolved, err = _resolve(wf, [{"lora_name": "y.safetensors"}])
    assert err is None
    assert resolved[0]["chain_anchor"] == "4"
    out = _insert(wf, resolved)
    nid = next(n for n, v in out.items() if v.get("class_type") == "LoraLoaderModelOnly")
    assert out["3"]["inputs"]["model"] == [nid, 0]


def test_explicit_model_loader_anchor_accepted():
    wf = _no_lora_wf()
    resolved, err = _resolve(wf, [{"lora_name": "z.safetensors", "anchor": "1"}])
    assert err is None
    assert resolved[0]["chain_anchor"] == "1"


def test_existing_lora_still_wins_as_default_anchor():
    """Regression: when a LoRA loader exists, auto-anchor stays on it (not the
    model root), preserving prior behavior."""
    resolved, err = _resolve(_with_lora_wf(), [{"lora_name": "new.safetensors"}])
    assert err is None
    assert resolved[0]["chain_anchor"] == "16"


def test_stacks_at_tail_when_seeding_with_existing_chain_via_model_anchor():
    """Anchor explicitly on the model loader but a LoRA chain already hangs off
    it -> new loader splices at the chain tail, not between model and LoRA."""
    wf = _with_lora_wf()
    resolved, err = _resolve(wf, [{"lora_name": "tail.safetensors", "anchor": "1"}])
    assert err is None
    out = _insert(wf, resolved)
    nid = next(n for n, v in out.items()
               if v.get("class_type") == "LoraLoaderModelOnly" and v["inputs"]["lora_name"] == "tail.safetensors")
    assert out[nid]["inputs"]["model"] == ["16", 0]   # after the existing LoRA
    assert out["2"]["inputs"]["model"] == [nid, 0]     # sampler now reads the new tail


def test_truly_modelless_workflow_still_errors():
    resolved, err = _resolve({"9": {"class_type": "SaveImage", "inputs": {}}},
                             [{"lora_name": "x.safetensors"}])
    assert resolved is None
    assert err and "anchor" in err.lower()
