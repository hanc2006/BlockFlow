"""LIVE integration test for the RunPod API client.

Skipped by default — run with `BLOCKFLOW_LIVE_TESTS=1 uv run pytest
tests/test_runpod_api_live.py -v -s`. Reads `RUNPOD_API_KEY` from env.

Performs the full round-trip:
  1. Validate API key
  2. Create 10GB network volume in EU-RO-1
  3. Create template
  4. Create endpoint (workersMin=0 so no GPU is ever assigned → $0 compute)
  5. Get endpoint health (proves /v2 contract)
  6. PATCH workers to 0 (proves the drain call works; already at 0)
  7. DELETE endpoint
  8. deleteTemplate (mutation)
  9. DELETE network volume

Cost: essentially $0 because workers_min=0 means no GPU is ever provisioned.
Storage cost for the 10GB volume is fractions of a cent for the seconds it
exists. Template + endpoint creation/deletion are metadata-only.

Robust cleanup via try/finally — even on assertion failure, resources are
torn down.
"""
from __future__ import annotations

import os
import sys
import time
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import runpod_api  # noqa: E402

LIVE_ENABLED = os.environ.get("BLOCKFLOW_LIVE_TESTS") == "1"
API_KEY = os.environ.get("RUNPOD_API_KEY", "")

pytestmark = pytest.mark.skipif(
    not LIVE_ENABLED,
    reason="Live RunPod tests gated by BLOCKFLOW_LIVE_TESTS=1 (consumes credits + creates real resources)",
)


@pytest.fixture(scope="module")
def api_key() -> str:
    if not API_KEY:
        pytest.skip("RUNPOD_API_KEY not set in environment")
    return API_KEY


def test_live_validate_api_key(api_key: str) -> None:
    """Cheapest live call — read-only gpuTypes query."""
    assert runpod_api.validate_api_key(api_key) is True


def test_live_list_gpu_types(api_key: str) -> None:
    gpus = runpod_api.list_gpu_types(api_key)
    assert isinstance(gpus, list)
    assert len(gpus) > 0
    first = gpus[0]
    assert "id" in first


def test_live_full_provision_and_teardown_round_trip(api_key: str) -> None:
    """End-to-end: create + tear down a real ComfyGen endpoint without ever
    starting a worker.

    This is the integration smoke that proves the client's URL/auth/body
    shapes are correct against the real RunPod API. Mock tests catch the
    contract we expect; this catches the contract that actually exists.
    """
    suffix = uuid.uuid4().hex[:8]
    volume_name = f"blockflow-live-test-{suffix}"
    template_name = f"blockflow-live-test-{suffix}"
    endpoint_name = f"blockflow-live-test-{suffix}"
    datacenter_id = "EU-RO-1"

    volume_id: str | None = None
    template_id: str | None = None
    endpoint_id: str | None = None

    try:
        # 1. Create 10GB network volume
        volume = runpod_api.create_network_volume(
            api_key,
            name=volume_name,
            size_gb=10,
            datacenter_id=datacenter_id,
        )
        assert "id" in volume, f"volume creation returned: {volume}"
        volume_id = volume["id"]
        print(f"[live] created volume {volume_id}")

        # 2. Create template (use ComfyGen's published image since we're not
        # actually running anything — just validating the API)
        template = runpod_api.create_template(
            api_key,
            name=template_name,
            image_name=runpod_api.BASE_DOCKER_IMAGE,
            env={
                "RUNTIME_REPO_URL": runpod_api.RUNTIME_REPO_URL,
                "RUNTIME_REPO_REF": "main",
                "AWS_ACCESS_KEY_ID": "fake-not-used",
                "AWS_SECRET_ACCESS_KEY": "fake-not-used",
            },
        )
        assert "id" in template, f"template creation returned: {template}"
        template_id = template["id"]
        print(f"[live] created template {template_id}")

        # 3. Create endpoint with workersMin=0 — NO GPU is ever assigned, NO cost.
        # GPU IDs are an ENUM at the REST /endpoints layer (stricter than
        # what GraphQL gpuTypes returns — live test caught the prior bug).
        # Using known-valid consumer cards. Workers stay at 0 so no GPU is
        # actually assigned.
        gpu_ids = ["NVIDIA GeForce RTX 4090", "NVIDIA GeForce RTX 5090"]
        endpoint = runpod_api.create_endpoint(
            api_key,
            name=endpoint_name,
            template_id=template_id,
            gpu_type_ids=gpu_ids,
            network_volume_id=volume_id,
            workers_min=0,
            workers_max=1,
        )
        assert "id" in endpoint, f"endpoint creation returned: {endpoint}"
        endpoint_id = endpoint["id"]
        print(f"[live] created endpoint {endpoint_id}")

        # 4. Get endpoint health — should return the worker counts struct
        health = runpod_api.get_endpoint_health(api_key, endpoint_id)
        assert "workers" in health, f"unexpected health shape: {health}"
        print(f"[live] endpoint health: {health['workers']}")

        # 5. Drain workers to 0 (already 0; verifies PATCH endpoint works)
        runpod_api.update_endpoint_workers(api_key, endpoint_id, workers_min=0, workers_max=0)
        print(f"[live] drained endpoint {endpoint_id}")

    finally:
        # Cleanup in reverse order. Each step swallows failures so subsequent
        # cleanup still attempts. Resources we couldn't delete here will need
        # manual cleanup in the RunPod console, but the test should at least
        # make a best effort.
        if endpoint_id:
            try:
                runpod_api.delete_endpoint(api_key, endpoint_id)
                print(f"[live] deleted endpoint {endpoint_id}")
            except Exception as exc:
                print(f"[live] WARN: endpoint {endpoint_id} cleanup failed: {exc}")

        if template_id:
            # Template deletion can take up to 2min after last use. We need to
            # supply the template NAME (not ID) per the research.
            for attempt in range(6):
                try:
                    runpod_api.delete_template(api_key, template_name=template_name)
                    print(f"[live] deleted template {template_name}")
                    break
                except Exception as exc:
                    if attempt == 5:
                        print(f"[live] WARN: template {template_name} cleanup failed after retries: {exc}")
                        break
                    time.sleep(5)

        if volume_id:
            try:
                runpod_api.delete_network_volume(api_key, volume_id)
                print(f"[live] deleted volume {volume_id}")
            except Exception as exc:
                print(f"[live] WARN: volume {volume_id} cleanup failed: {exc}")
