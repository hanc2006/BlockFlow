from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import services, settings_store, settings_validators, state  # noqa: E402
from backend.settings_routes import router as settings_router  # noqa: E402


def _load_block_backend(slug: str):
    path = ROOT / "custom_blocks" / slug / "backend.block.py"
    spec = importlib.util.spec_from_file_location(f"{slug}_provider_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI()
    app.include_router(module.router)
    return module, TestClient(app)


@pytest.fixture
def provider_store(monkeypatch: pytest.MonkeyPatch):
    credentials: dict[str, str] = {}
    preferences: dict[str, str] = {}
    monkeypatch.setattr(settings_store, "get_credential", lambda name: credentials.get(name))
    monkeypatch.setattr(settings_store, "get_app_pref", lambda name, default=None: preferences.get(name, default))
    return credentials, preferences


def test_provider_settings_override_environment(provider_store, monkeypatch):
    credentials, preferences = provider_store
    credentials["openai_api_key"] = "settings-key"
    preferences["openai_base_url"] = "https://settings.example/v1/"
    monkeypatch.setenv("OPENAI_API_KEY", "environment-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://environment.example/v1")

    provider = services._get_openai_compatible_config()

    assert provider == {
        "api_key": "settings-key",
        "base_url": "https://settings.example/v1",
    }


def test_provider_uses_openai_environment_before_legacy_openrouter(provider_store, monkeypatch):
    credentials, _ = provider_store
    credentials["openrouter_api_key"] = "legacy-settings-key"
    monkeypatch.setenv("OPENAI_API_KEY", "new-environment-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://new-provider.example/v1/")
    monkeypatch.setenv("OPENROUTER_API_KEY", "legacy-environment-key")
    monkeypatch.setenv("OPENROUTER_API_BASE", "https://openrouter.example/api/v1")

    provider = services._get_openai_compatible_config()

    assert provider == {
        "api_key": "new-environment-key",
        "base_url": "https://new-provider.example/v1",
    }


def test_openai_key_does_not_inherit_legacy_openrouter_base(provider_store, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "new-environment-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("OPENROUTER_API_BASE", "https://openrouter.example/api/v1")

    provider = services._get_openai_compatible_config()

    assert provider == {
        "api_key": "new-environment-key",
        "base_url": "https://api.openai.com/v1",
    }


def test_provider_falls_back_to_legacy_settings_and_environment(provider_store, monkeypatch):
    credentials, _ = provider_store
    credentials["openrouter_api_key"] = "legacy-settings-key"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.setenv("OPENROUTER_API_BASE", "https://openrouter.example/api/v1/")

    provider = services._get_openai_compatible_config()

    assert provider == {
        "api_key": "legacy-settings-key",
        "base_url": "https://openrouter.example/api/v1",
    }


def test_saved_legacy_key_uses_legacy_default_base_url(provider_store, monkeypatch):
    credentials, _ = provider_store
    credentials["openrouter_api_key"] = "legacy-settings-key"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENROUTER_API_BASE", raising=False)

    provider = services._get_openai_compatible_config()

    assert provider == {
        "api_key": "legacy-settings-key",
        "base_url": "https://openrouter.ai/api/v1",
    }


def test_provider_request_uses_configured_base_url_and_bearer_auth(provider_store, monkeypatch):
    credentials, preferences = provider_store
    credentials["openai_api_key"] = "provider-secret"
    preferences["openai_base_url"] = "https://inference.example/v1/"
    captured = {}

    def fake_request(method, url, headers, payload=None, timeout=60):
        captured.update(method=method, url=url, headers=headers, payload=payload, timeout=timeout)
        return {"ok": True}

    monkeypatch.setattr(services, "_request_json_with_headers", fake_request)

    result = services._openai_compatible_request_json(
        "POST", "/chat/completions", {"model": "vision-model"}, timeout=45
    )

    assert result == {"ok": True}
    assert captured == {
        "method": "POST",
        "url": "https://inference.example/v1/chat/completions",
        "headers": {
            "Authorization": "Bearer provider-secret",
            "Content-Type": "application/json",
        },
        "payload": {"model": "vision-model"},
        "timeout": 45,
    }


def test_provider_request_without_key_fails_with_generic_message(provider_store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    with pytest.raises(RuntimeError, match="OpenAI-compatible provider API key is missing"):
        services._openai_compatible_request_json("GET", "/models")


def test_model_listing_accepts_standard_openai_model_records(provider_store, monkeypatch):
    credentials, _ = provider_store
    credentials["openai_api_key"] = "provider-secret"
    monkeypatch.setenv("OPENAI_BASE_URL", "https://models.example/v1")
    monkeypatch.setattr(
        services,
        "_request_json_with_headers",
        lambda *args, **kwargs: {
            "data": [
                {"id": "vision-model", "owned_by": "local", "context_length": 8192},
                {"id": "text-model", "name": "Text Model"},
                {"owned_by": "invalid"},
            ]
        },
    )

    models = services._fetch_openai_compatible_models()

    assert models == [
        {
            "id": "text-model",
            "name": "Text Model",
            "context_length": None,
            "modality": None,
            "input_modalities": [],
            "output_modalities": [],
        },
        {
            "id": "vision-model",
            "name": "vision-model",
            "context_length": 8192,
            "modality": None,
            "input_modalities": [],
            "output_modalities": [],
        },
    ]


def test_model_cache_is_separated_by_base_url(provider_store, monkeypatch):
    credentials, _ = provider_store
    credentials["openai_api_key"] = "provider-secret"
    monkeypatch.setattr(state, "OPENAI_COMPATIBLE_MODELS_CACHE", {})
    monkeypatch.setattr(state, "OPENAI_COMPATIBLE_MODELS_CACHE_LOCK", threading.Lock())
    fetched_urls: list[str] = []

    def fake_fetch():
        base_url = services._get_openai_compatible_config()["base_url"]
        fetched_urls.append(base_url)
        return [{"id": f"model-{len(fetched_urls)}"}]

    monkeypatch.setattr(services, "_fetch_openai_compatible_models", fake_fetch)
    monkeypatch.setenv("OPENAI_BASE_URL", "https://first.example/v1")
    first, _, first_cached = services._get_openai_compatible_models()
    repeated, _, repeated_cached = services._get_openai_compatible_models()
    monkeypatch.setenv("OPENAI_BASE_URL", "https://second.example/v1")
    second, _, second_cached = services._get_openai_compatible_models()

    assert first == repeated == [{"id": "model-1"}]
    assert second == [{"id": "model-2"}]
    assert first_cached is False
    assert repeated_cached is True
    assert second_cached is False
    assert fetched_urls == ["https://first.example/v1", "https://second.example/v1"]


def test_provider_completion_extractor_accepts_openai_chat_response():
    response = {"choices": [{"message": {"content": "caption"}}]}

    assert services._extract_openai_compatible_completion_text(response) == "caption"


def test_validate_openai_compatible_uses_models_endpoint(provider_store, monkeypatch):
    credentials, preferences = provider_store
    credentials["openai_api_key"] = "provider-secret"
    preferences["openai_base_url"] = "https://models.example/v1"
    calls = []

    def fake_request(method, path, payload=None, timeout=60):
        calls.append((method, path))
        return {"data": [{"id": "vision-model"}, {"id": "text-model"}]}

    monkeypatch.setattr(services, "_openai_compatible_request_json", fake_request)

    result = settings_validators.validate_openai_compatible()

    assert result == {
        "ok": True,
        "error": None,
        "info": {"models_visible": 2, "base_url": "https://models.example/v1"},
    }
    assert calls == [("GET", "/models")]


def test_validate_openai_compatible_requires_api_key(provider_store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(
        services,
        "_get_openai_compatible_config",
        lambda: {"api_key": "", "base_url": "https://api.openai.com/v1"},
    )

    with pytest.raises(settings_validators.CredentialNotConfigured, match="openai_api_key"):
        settings_validators.validate_openai_compatible()


def test_provider_settings_endpoint_exposes_effective_base_url(monkeypatch):
    app = FastAPI()
    app.include_router(settings_router)
    monkeypatch.setattr(services, "_get_openai_compatible_config", lambda: {
        "api_key": "provider-secret",
        "base_url": "https://inference.example/v1",
    })

    response = TestClient(app).get("/api/settings/openai-compatible")

    assert response.json() == {
        "base_url": "https://inference.example/v1",
        "has_api_key": True,
    }


def test_prompt_writer_generation_uses_provider_neutral_payload(monkeypatch):
    module, client = _load_block_backend("prompt_writer")
    captured = {}

    def fake_request(method, path, payload, timeout=60):
        captured.update(method=method, path=path, payload=payload, timeout=timeout)
        return {"choices": [{"message": {"content": "a generated prompt"}}]}

    monkeypatch.setattr(module.services, "_openai_compatible_request_json", fake_request)
    response = client.post("/generate", json={
        "model": "compatible-model",
        "system_prompt": "Be concise",
        "user_prompt": "A quiet forest",
    })

    assert response.json() == {"ok": True, "output_text": "a generated prompt"}
    assert captured["method"] == "POST"
    assert captured["path"] == "/chat/completions"
    assert "cache_control" not in str(captured["payload"])
    assert "reasoning" not in captured["payload"]
    assert "response_format" not in captured["payload"]


def test_prompt_writer_ideas_request_json_in_system_prompt(monkeypatch):
    module, client = _load_block_backend("prompt_writer")
    captured = {}

    def fake_request(method, path, payload, timeout=60):
        captured.update(method=method, path=path, payload=payload)
        return {"choices": [{"message": {"content": '{"ideas": ["one", "two"]}'}}]}

    monkeypatch.setattr(module.services, "_openai_compatible_request_json", fake_request)
    response = client.post("/generate-ideas", json={
        "model": "compatible-model",
        "description": "A city walk",
        "count": 2,
    })

    assert response.json() == {"ok": True, "ideas": ["one", "two"], "count": 2}
    assert "JSON object" in captured["payload"]["messages"][0]["content"]
    assert "response_format" not in captured["payload"]


def test_i2v_generation_uses_provider_neutral_payload(monkeypatch):
    module, client = _load_block_backend("i2v_prompt_writer")
    captured = {}

    def fake_request(method, path, payload, timeout=60):
        captured.update(method=method, path=path, payload=payload)
        return {"choices": [{"message": {"content": "slow camera push-in"}}]}

    monkeypatch.setattr(module.services, "_openai_compatible_request_json", fake_request)
    response = client.post("/generate", json={
        "model": "vision-model",
        "user_prompt": "Add gentle motion",
        "image_url": "https://images.example/ref.png",
    })

    assert response.json() == {"ok": True, "output_text": "slow camera push-in"}
    assert captured["path"] == "/chat/completions"
    assert "reasoning" not in captured["payload"]
    assert "response_format" not in captured["payload"]
    assert "cache_control" not in str(captured["payload"])


def test_multimodal_generation_uses_provider_neutral_payload(monkeypatch):
    module, client = _load_block_backend("multimodal_prompt_writer")
    captured = {}

    def fake_request(method, path, payload, timeout=60):
        captured.update(method=method, path=path, payload=payload)
        return {"choices": [{"message": {"content": "a unified scene prompt"}}]}

    monkeypatch.setattr(module.services, "_openai_compatible_request_json", fake_request)
    response = client.post("/generate", json={
        "model": "compatible-model",
        "user_prompt": "Keep the lighting warm",
    })

    assert response.json() == {"ok": True, "output_text": "a unified scene prompt"}
    assert captured["path"] == "/chat/completions"
    assert "reasoning" not in captured["payload"]
    assert "response_format" not in captured["payload"]
    assert "cache_control" not in str(captured["payload"])


def test_multimodal_model_list_keeps_models_without_capability_metadata(monkeypatch):
    module, client = _load_block_backend("multimodal_prompt_writer")
    models = [
        {"id": "metadata-unknown", "input_modalities": [], "output_modalities": []},
        {"id": "text-only", "input_modalities": ["text"], "output_modalities": ["text"]},
    ]
    monkeypatch.setattr(module.services, "_get_openai_compatible_models", lambda refresh=False: (models, None, False))

    response = client.get("/models?require_image=1")

    assert response.json()["models"] == [models[0]]
    assert response.json()["matched"] == 1


def test_dataset_caption_uses_provider_neutral_image_payload(tmp_path, monkeypatch):
    module, _ = _load_block_backend("dataset_caption")
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"test image bytes")
    captured = {}

    def fake_request(method, path, payload, timeout=60):
        captured.update(method=method, path=path, payload=payload)
        return {"choices": [{"message": {"content": "a woman in a garden"}}]}

    monkeypatch.setattr(module.services, "_openai_compatible_request_json", fake_request)

    result = module._caption_one("vision-model", "Describe", "Caption", image_path, 256, 0.2)

    assert result == "a woman in a garden"
    assert captured["path"] == "/chat/completions"
    assert "cache_control" not in str(captured["payload"])
    assert "reasoning" not in captured["payload"]


def test_civitai_auto_tags_use_shared_provider_client(tmp_path, monkeypatch):
    module, client = _load_block_backend("civitai_share")
    image_path = tmp_path / "sample.png"
    image_path.write_bytes(b"test image bytes")
    captured = {}
    monkeypatch.setattr(module, "_resolve_media_path", lambda _: image_path)
    monkeypatch.setattr(module.services, "_get_openai_compatible_config", lambda: {
        "api_key": "provider-secret",
        "base_url": "https://inference.example/v1",
    })

    def fake_request(method, path, payload, timeout=60):
        captured.update(method=method, path=path, payload=payload)
        return {"choices": [{"message": {"content": "portrait, outdoors, daylight"}}]}

    monkeypatch.setattr(module.services, "_openai_compatible_request_json", fake_request)
    response = client.post("/auto-tags", json={
        "media_url": "/outputs/sample.png",
        "model": "generation-model",
        "tag_model": "vision-model",
    })

    assert response.json() == {"ok": True, "tags": ["portrait", "outdoors", "daylight"]}
    assert captured["path"] == "/chat/completions"
    assert captured["payload"]["model"] == "vision-model"
