"""Local preset registry (BLOCKFLOW_USE_LOCAL_PRESETS).

A folder with manifest.json + <id>/preset.json (+ workflow files) in the
public registry's format. Enabled with BLOCKFLOW_USE_LOCAL_PRESETS=1, local
presets replace registry presets with the same id and add new ones; with
=only the public registry is not used. Relative preset_url / workflow url
values resolve inside the folder, and nothing outside it can be read.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import preset_routes, settings_store  # noqa: E402

REMOTE = {"manifest_version": 1, "presets": [
    {"id": "ltx-2-3", "name": "LTX remote", "preset_url": "https://reg/ltx.json", "disk_size_estimate_gb": 55},
    {"id": "wan", "name": "Wan remote", "preset_url": "https://reg/wan.json", "disk_size_estimate_gb": 40},
]}


def _resp(body, status=200):
    m = MagicMock()
    m.status_code = status
    m.json = lambda: body
    return m


@pytest.fixture
def local_dir(tmp_path):
    d = tmp_path / "local_presets"
    (d / "ltx-2-3").mkdir(parents=True)
    (d / "mine").mkdir()
    (d / "manifest.json").write_text(json.dumps({"manifest_version": 1, "presets": [
        {"id": "ltx-2-3", "name": "LTX local", "preset_url": "ltx-2-3/preset.json", "disk_size_estimate_gb": 55},
        {"id": "mine", "name": "My preset", "preset_url": "mine/preset.json", "disk_size_estimate_gb": 1},
    ]}))
    (d / "ltx-2-3" / "preset.json").write_text(json.dumps({
        "id": "ltx-2-3", "comfygen_min_version": "0.2.0", "disk_size_estimate_gb": 55,
        "workflows": [
            {"name": "T2V", "url": "workflow_t2v.json"},
            {"name": "I2V", "url": "https://reg/wf_i2v.json"},
        ],
        "models": [{"url": "https://huggingface.co/x/resolve/main/up-1.1.safetensors",
                    "dest": "upscale_models/up-1.1.safetensors"}],
    }))
    (d / "ltx-2-3" / "workflow_t2v.json").write_text(json.dumps({"1": {"class_type": "LatentUpscaleModelLoader",
                                                                        "inputs": {"model_name": "up-1.1.safetensors"}}}))
    (d / "mine" / "preset.json").write_text(json.dumps({"id": "mine", "workflows": [], "models": []}))
    return d


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(settings_store, "DB_PATH", tmp_path / "s.db")
    settings_store.init_db()
    monkeypatch.setattr(preset_routes, "_CACHE_PATH", tmp_path / "manifest_cache.json")
    monkeypatch.delenv("BLOCKFLOW_USE_LOCAL_PRESETS", raising=False)
    monkeypatch.delenv("BLOCKFLOW_LOCAL_PRESETS_DIR", raising=False)
    preset_routes._cache_reset()
    app = FastAPI()
    app.include_router(preset_routes.router)
    return TestClient(app)


@pytest.fixture
def remote(mocker):
    calls: list[str] = []

    def get(url, **kw):
        calls.append(url)
        if url == preset_routes._MANIFEST_URL:
            return _resp(REMOTE)
        if url == "https://reg/wf_i2v.json":
            return _resp({"9": {"class_type": "SaveVideo", "inputs": {}}})
        return _resp({"id": "remote-detail", "models": []})

    mocker.patch.object(preset_routes._cffi_requests, "get", side_effect=get)
    return calls


def _ids(manifest: dict) -> list[tuple[str, str]]:
    return [(p["id"], p["name"]) for p in manifest["presets"]]


def test_disabled_by_default_uses_registry_only(client, remote, local_dir, monkeypatch):
    monkeypatch.setenv("BLOCKFLOW_LOCAL_PRESETS_DIR", str(local_dir))
    m = client.get("/api/presets/manifest").json()
    assert _ids(m) == [("ltx-2-3", "LTX remote"), ("wan", "Wan remote")]


def test_enabled_local_replaces_same_id_and_adds_new(client, remote, local_dir, monkeypatch):
    monkeypatch.setenv("BLOCKFLOW_USE_LOCAL_PRESETS", "1")
    monkeypatch.setenv("BLOCKFLOW_LOCAL_PRESETS_DIR", str(local_dir))
    m = client.get("/api/presets/manifest").json()
    assert _ids(m) == [("ltx-2-3", "LTX local"), ("wan", "Wan remote"), ("mine", "My preset")]
    ltx = m["presets"][0]
    assert ltx["local"] is True
    assert ltx["preset_url"] == (local_dir / "ltx-2-3" / "preset.json").resolve().as_uri()
    assert "local" not in m["presets"][1]


def test_only_mode_skips_registry(client, remote, local_dir, monkeypatch):
    monkeypatch.setenv("BLOCKFLOW_USE_LOCAL_PRESETS", "only")
    monkeypatch.setenv("BLOCKFLOW_LOCAL_PRESETS_DIR", str(local_dir))
    m = client.get("/api/presets/manifest").json()
    assert _ids(m) == [("ltx-2-3", "LTX local"), ("mine", "My preset")]
    assert remote == []


def test_registry_down_still_serves_local_presets(client, local_dir, monkeypatch, mocker):
    monkeypatch.setenv("BLOCKFLOW_USE_LOCAL_PRESETS", "1")
    monkeypatch.setenv("BLOCKFLOW_LOCAL_PRESETS_DIR", str(local_dir))
    mocker.patch.object(preset_routes._cffi_requests, "get", side_effect=OSError("offline"))
    r = client.get("/api/presets/manifest")
    assert r.status_code == 200
    assert [p["id"] for p in r.json()["presets"]] == ["ltx-2-3", "mine"]


def test_local_preset_detail_and_workflows_load_from_files(client, remote, local_dir, monkeypatch):
    monkeypatch.setenv("BLOCKFLOW_USE_LOCAL_PRESETS", "1")
    monkeypatch.setenv("BLOCKFLOW_LOCAL_PRESETS_DIR", str(local_dir))
    detail = client.get("/api/presets/manifest/ltx-2-3").json()
    assert detail["models"][0]["dest"] == "upscale_models/up-1.1.safetensors"
    # relative workflow url resolved inside the preset folder; absolute ones untouched
    assert detail["workflows"][0]["url"] == (local_dir / "ltx-2-3" / "workflow_t2v.json").resolve().as_uri()
    assert detail["workflows"][1]["url"] == "https://reg/wf_i2v.json"

    workflows = preset_routes._fetch_workflows_for_preset(detail)
    assert workflows[0]["json"]["1"]["inputs"]["model_name"] == "up-1.1.safetensors"
    assert workflows[1]["json"] == {"9": {"class_type": "SaveVideo", "inputs": {}}}


def test_file_urls_outside_local_dir_are_refused(client, local_dir, tmp_path, monkeypatch, mocker):
    secret = tmp_path / "secret.json"
    secret.write_text(json.dumps({"token": "x"}))
    monkeypatch.setenv("BLOCKFLOW_USE_LOCAL_PRESETS", "1")
    monkeypatch.setenv("BLOCKFLOW_LOCAL_PRESETS_DIR", str(local_dir))
    # a (malicious or broken) registry entry pointing at a local file
    evil = {"manifest_version": 1, "presets": [{"id": "evil", "name": "e", "preset_url": secret.as_uri()}]}
    mocker.patch.object(preset_routes._cffi_requests, "get", side_effect=lambda url, **kw: _resp(evil))
    r = client.get("/api/presets/manifest/evil")
    assert r.status_code == 502
    assert "token" not in r.text
    # ../ escapes in a local manifest are refused too
    (local_dir / "manifest.json").write_text(json.dumps({"presets": [
        {"id": "esc", "name": "e", "preset_url": "../secret.json"}]}))
    preset_routes._cache_reset()
    assert client.get("/api/presets/manifest/esc").status_code == 502


def test_broken_local_manifest_keeps_registry_and_reports_it(client, remote, local_dir, monkeypatch):
    (local_dir / "manifest.json").write_text("{not json")
    monkeypatch.setenv("BLOCKFLOW_USE_LOCAL_PRESETS", "1")
    monkeypatch.setenv("BLOCKFLOW_LOCAL_PRESETS_DIR", str(local_dir))
    m = client.get("/api/presets/manifest").json()
    assert [p["id"] for p in m["presets"]] == ["ltx-2-3", "wan"]
    assert "manifest.json" in m["local_presets_error"]


def test_shipped_local_presets_are_valid():
    """The repo's own local_presets/ folder: every manifest entry resolves,
    and the ltx-2-3 fix points the 2x upscaler at the 1.1 release."""
    d = ROOT / "local_presets"
    manifest = json.loads((d / "manifest.json").read_text())
    for entry in manifest["presets"]:
        preset = json.loads((d / entry["preset_url"]).read_text())
        assert preset["id"] == entry["id"]
        for wf in preset.get("workflows", []):
            if not wf["url"].startswith("https://"):
                json.loads((d / Path(entry["preset_url"]).parent / wf["url"]).read_text())
    ltx = json.loads((d / "ltx-2-3" / "preset.json").read_text())
    dests = [m["dest"] for m in ltx["models"]]
    assert "upscale_models/ltx-2.3-spatial-upscaler-x2-1.1.safetensors" in dests
    assert not any("x2-1.0" in m["url"] or "x2-1.0" in m["dest"] for m in ltx["models"])
    t2v = (d / "ltx-2-3" / "workflow_t2v.json").read_text()
    assert "ltx-2.3-spatial-upscaler-x2-1.1.safetensors" in t2v and "x2-1.0" not in t2v


def test_shipped_wan22_svi_preset_adds_the_missing_upscaler():
    """The registry's wan22-svi-4pass workflow loads 2xLiveActionV1_SPAN_490000.pth
    through UpscaleModelLoader (upscale_models/) but the preset never downloaded it."""
    d = ROOT / "local_presets"
    entry = next(e for e in json.loads((d / "manifest.json").read_text())["presets"] if e["id"] == "wan22-svi-4pass")
    preset = json.loads((d / entry["preset_url"]).read_text())
    (spec,) = [m for m in preset["models"] if m["dest"].endswith("2xLiveActionV1_SPAN_490000.pth")]
    assert spec["dest"] == "upscale_models/2xLiveActionV1_SPAN_490000.pth"
    assert spec["url"].startswith("https://raw.githubusercontent.com/jcj83429/upscaling/f73a3a02874360ec6ced18f8bdd8e43b5d7bba57/")
    assert spec["sha256"] == "8b166c75831ea7f694d9058ee9c8df8148af8cc1d2b57e69e6581b15cab572f7"
    # the registry's own files are all still there
    assert len(preset["models"]) == 9


def test_shipped_wan22_svi_preset_uses_wan22_lightning_on_high_model():
    """The high-noise lightning LoRA is the Wan 2.2 Lightning (Seko V1) one, not the
    Wan 2.1 lightx2v LoRA whose img_emb keys cannot load into Wan 2.2."""
    d = ROOT / "local_presets" / "wan22-svi-4pass"
    preset = json.loads((d / "preset.json").read_text())
    (wf,) = preset["workflows"]
    assert not wf["url"].startswith("https://")
    workflow = json.loads((d / wf["url"]).read_text())
    high = workflow["883"]["inputs"]
    assert high["lora_name"] == "i2v_lightx2v_high_noise_model.safetensors"
    assert high["model"] == ["881", 0]
    dests = [m["dest"] for m in preset["models"]]
    assert "loras/i2v_lightx2v_high_noise_model.safetensors" in dests
    assert not any("lightx2v_I2V_14B_480p" in x for x in dests)
    assert "lightx2v_I2V_14B_480p" not in json.dumps(workflow)
    assert len(preset["models"]) == 9
