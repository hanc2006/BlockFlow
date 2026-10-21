## Plan: OpenAI-Compatible Provider

Replace the hard-coded OpenRouter dependency with a configurable provider that speaks the OpenAI Chat Completions API. Put the API key and base URL in Settings, use shared backend transport and model discovery, and migrate every OpenRouter-dependent block while preserving existing block output contracts.

**Steps**

1. **Set provider and compatibility policy.** Use an editable base URL, defaulting to `https://api.openai.com/v1`, and store it as an app preference. Store the API key in the existing credential store. Support `OPENAI_API_KEY` and `OPENAI_BASE_URL` for environment-based setup. For existing users, retain a temporary fallback to saved OpenRouter credentials and `OPENROUTER_*` environment values.
2. **Add failing backend tests first.** Cover URL normalization, bearer auth, missing credentials, generic `/models` responses, completion extraction, and model-cache isolation by base URL. Add Settings validation tests using a mocked `/models` request.
3. **Implement shared provider configuration and transport.** Consolidate provider settings and requests in [backend/services.py](backend/services.py), with environment and Settings precedence. Update [backend/config.py](backend/config.py) and [backend/state.py](backend/state.py) for generic configuration and endpoint-aware model caching. Keep provider secrets out of frontend storage.
4. **Migrate all provider call sites.** Update generation, model listing, and health checks in [custom_blocks/prompt_writer/backend.block.py](custom_blocks/prompt_writer/backend.block.py), [custom_blocks/i2v_prompt_writer/backend.block.py](custom_blocks/i2v_prompt_writer/backend.block.py), [custom_blocks/multimodal_prompt_writer/backend.block.py](custom_blocks/multimodal_prompt_writer/backend.block.py), and [custom_blocks/dataset_caption/backend.block.py](custom_blocks/dataset_caption/backend.block.py). Route CivitAI auto-tag generation through the shared client too; its current hard-coded Gemini model may need to become configurable in [custom_blocks/civitai_share/backend.block.py](custom_blocks/civitai_share/backend.block.py).
5. **Update Settings and block UI.** Add the base URL setting and generic API-key entry in [frontend/src/components/settings/credentials-tab.tsx](frontend/src/components/settings/credentials-tab.tsx), reusing `getAppPref` and `setAppPref` from [frontend/src/lib/settings/client.ts](frontend/src/lib/settings/client.ts). Replace OpenRouter labels and credential warnings across the affected block frontends. Preserve current block output shapes.
6. **Handle API differences explicitly.** Remove OpenRouter-only request headers and avoid assuming that `reasoning`, `cache_control`, strict JSON schema, video parts, or audio parts are supported by every compatible server. Keep image and text behavior covered; treat video/audio and advertised model modalities as provider-dependent rather than claiming universal support.
7. **Update documentation and generated sources.** Revise [README.md](README.md), [.env.example](.env.example), [frontend/README.md](frontend/README.md), [docs/architecture.md](docs/architecture.md), and [docs/generate-ideas.md](docs/generate-ideas.md). Update affected frontend tests, then regenerate custom-block copies with `npm --prefix frontend run gen:custom-blocks`.

**Relevant Files**

- [backend/services.py](backend/services.py) — shared request, model-list, cache, and response helpers.
- [backend/settings_validators.py](backend/settings_validators.py) — validate the configured endpoint using a mocked models request.
- [backend/settings_store.py](backend/settings_store.py) and [backend/settings_routes.py](backend/settings_routes.py) — existing credential and app-preference persistence.
- [frontend/src/components/settings/credentials-tab.tsx](frontend/src/components/settings/credentials-tab.tsx) — provider configuration UI.
- The five block backend files listed in steps 4 and 5, plus their corresponding `custom_blocks/*/frontend.block.tsx` files.
- Existing Settings tests in [tests/test_settings_validators.py](tests/test_settings_validators.py) and [frontend/src/components/settings/__tests__/credentials-tab.test.tsx](frontend/src/components/settings/__tests__/credentials-tab.test.tsx); add focused transport and block-payload tests alongside the existing backend tests.

**Verification**

1. Write tests first and confirm they fail for the expected missing generic-provider behavior.
2. Run focused backend and frontend tests for transport, configuration, validation, and migrated call sites.
3. Run custom-block codegen, then the repository-required gates: Ruff, `pytest tests/ -ra`, frontend TypeScript, lint, tests, and build.
4. Confirm generated files and `git status --short`; do not push.

**Decisions and Boundaries**

- Recommended default: Settings values take precedence over environment values; legacy OpenRouter configuration remains a migration fallback, not the new default.
- The compatibility target is Chat Completions plus `/models`. A provider that lacks `/models` may require a manual model-ID entry; that is not included unless you want the migration to support it.
- CivitAI auto-tags are included because they make a direct OpenRouter request today. CivitAI publishing itself is unchanged.
- The supplied code references show OpenRouter-specific payload behavior, but do not establish that video/audio request shapes are portable across OpenAI-compatible servers. Those capabilities need an explicit support boundary.

I couldn’t persist this to `/memories/session/plan.md` because the session’s memory tool isn’t available. The complete plan is here for review.
