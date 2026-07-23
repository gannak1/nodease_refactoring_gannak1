from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.evaluation.run_agent_builder_cache_latency_benchmark import (
    load_private_scenarios,
    runtime_from_environment,
    validate_private_scenario_capacity,
)


def _scenarios() -> dict:
    def strings(count: int, prefix: str) -> list[str]:
        return [f"{prefix}-{index}" for index in range(count)]

    def phase(count: int) -> dict:
        return {
            "cold_miss": strings(count, "cold"),
            "exact_warm_hit": strings(count, "exact"),
            "normalization_warm_hit": [
                {"prime": f"normalized-{index}", "measure": f"normalized  -{index}"}
                for index in range(count)
            ],
            "semantic_bypass": strings(count, "bypass"),
            "negative_control": strings(count, "negative"),
        }

    return {
        "schema_version": "mba-350-live-scenarios-v1",
        "development": phase(11),
        "final": phase(31),
    }


def _environment() -> dict[str, str]:
    return {
        "NODEASE_EVAL_CACHE_OFF_URL": "http://127.0.0.1:8010/api/v1/agent-builder",
        "NODEASE_EVAL_CACHE_ON_URL": "http://127.0.0.1:8011/api/v1/agent-builder",
        "NODEASE_EVAL_AUTHORIZATION": "Bearer private-test-token",
        "NODEASE_EVAL_ORGANIZATION_ID": "00000000-0000-0000-0000-000000000001",
        "NODEASE_EVAL_WORKFLOW_ID": "00000000-0000-0000-0000-000000000002",
        "NODEASE_EVAL_CREDENTIAL_ID": "00000000-0000-0000-0000-000000000003",
        "NODEASE_EVAL_MODEL_ID": "00000000-0000-0000-0000-000000000004",
        "NODEASE_EVAL_FINGERPRINT_KEY": "private-fingerprint-key",
    }


def test_private_scenario_loader_and_phase_capacity_reject_short_inputs(tmp_path: Path):
    path = tmp_path / "scenarios.json"
    path.write_text(json.dumps(_scenarios()), encoding="utf-8")

    scenarios = load_private_scenarios(path)

    validate_private_scenario_capacity(scenarios, "development")
    validate_private_scenario_capacity(scenarios, "final")
    scenarios["final"]["cold_miss"].pop()
    with pytest.raises(ValueError, match="scenario"):
        validate_private_scenario_capacity(scenarios, "final")


def test_runtime_environment_is_complete_and_never_uses_non_loopback_urls():
    runtime = runtime_from_environment(_environment(), _scenarios())
    assert runtime is not None

    broken = _environment()
    broken["NODEASE_EVAL_CACHE_ON_URL"] = "https://example.test/api"
    with pytest.raises(ValueError, match="loopback"):
        runtime_from_environment(broken, _scenarios())
