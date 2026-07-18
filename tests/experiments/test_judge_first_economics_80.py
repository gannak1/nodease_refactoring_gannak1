import json
import pathlib
import tempfile

import pytest

from scripts.experiment_judge_first_economics_80 import (
    ARMS,
    AUTO_ARM,
    HIGH_MODEL,
    LOW_MODEL,
    MID_MODEL,
    QUALITY_JUDGE_MAX_OUTPUT_TOKENS,
    QUALITY_JUDGE_MODEL,
    ROUTING_JUDGE_MODEL,
    _tradeoff_assessment,
    _write_run_config,
    build_cases,
    graph_for_arm,
    resolve_artifact_target,
)
from apps.workflow_engine.services.model_routing_runtime_judge import (
    ModelRoutingRuntimeJudge,
)
from apps.workflow_engine.workflow.nodes.webhook.entities import WebhookTriggerNodeData
from apps.workflow_engine.workflow.nodes.webhook.webhook_node import WebhookTriggerNode


def test_economics_dataset_has_80_unique_diverse_cases():
    cases = build_cases()

    assert len(cases) == 80
    assert len({case.message for case in cases}) == 80
    assert {case.expected_difficulty for case in cases} == {
        "economy",
        "balanced",
        "advanced",
    }
    assert len({case.category for case in cases}) >= 8
    assert set(ARMS) == {"automatic", "high_fixed", "mid_fixed", "low_fixed"}
    assert {case.input_structure for case in cases} == {
        "flat_text",
        "nested_ticket",
        "conversation",
        "batch_record",
    }
    assert {case.input_length_bucket for case in cases} == {
        "short",
        "medium",
        "long",
        "very_long",
    }
    assert all(case.payload for case in cases)
    assert all(
        case.message in json.dumps(case.payload, ensure_ascii=False) for case in cases
    )
    assert min(
        len(case.input_text)
        for case in cases
        if case.input_length_bucket == "very_long"
    ) > max(
        len(case.input_text) for case in cases if case.input_length_bucket == "short"
    )


def test_economics_experiment_uses_distinct_high_mid_low_and_judge_models():
    assert len({HIGH_MODEL, MID_MODEL, LOW_MODEL}) == 3
    assert ROUTING_JUDGE_MODEL not in {"gpt-5.6-sol"}
    assert QUALITY_JUDGE_MODEL not in {"gpt-5.6-sol"}


def test_each_fixed_arm_uses_its_declared_model():
    expected = {
        "high_fixed": HIGH_MODEL,
        "mid_fixed": MID_MODEL,
        "low_fixed": LOW_MODEL,
    }
    for arm, model_id in expected.items():
        graph = graph_for_arm(arm)
        llm_node = next(node for node in graph["nodes"] if node["id"] == "llm-triage")
        assert llm_node["data"]["model_id"] == model_id
        assert llm_node["data"]["auto_model_routing"] is False


def test_workflow_normalizes_each_input_structure_without_losing_the_request():
    graph = graph_for_arm(AUTO_ARM)
    webhook_data = next(
        node["data"] for node in graph["nodes"] if node["id"] == "webhook-ticket"
    )
    webhook = WebhookTriggerNode(
        id="webhook-ticket",
        data=WebhookTriggerNodeData(**webhook_data),
    )

    for case in build_cases():
        normalized = webhook.execute(case.payload)
        assert case.message in normalized.values()


def test_tradeoff_compares_saved_cost_with_quality_and_latency_loss():
    rows = []
    for index in range(4):
        rows.append(
            {
                "arms": {
                    AUTO_ARM: {
                        "task_cost_usd": 0.6,
                        "routing_judge_cost_usd": 0.1,
                        "workflow_latency_ms": 1200,
                        "schema_pass": True,
                        "workflow_success": True,
                    },
                    "high_fixed": {
                        "task_cost_usd": 1.0,
                        "routing_judge_cost_usd": 0.0,
                        "workflow_latency_ms": 1000,
                        "schema_pass": True,
                        "workflow_success": True,
                    },
                    "mid_fixed": {},
                    "low_fixed": {},
                },
                "quality": {
                    AUTO_ARM: {"quality_score": 93.0, "contract_pass": True},
                    "high_fixed": {"quality_score": 95.0, "contract_pass": True},
                    "mid_fixed": {},
                    "low_fixed": {},
                },
            }
        )

    assessment = _tradeoff_assessment(rows)

    assert assessment["cost_saved_vs_high_usd"] == pytest.approx(1.2)
    assert assessment["cost_savings_rate_vs_high"] == pytest.approx(0.3)
    assert assessment["quality_loss_vs_high_points"] == pytest.approx(2.0)
    assert assessment["latency_change_vs_high_ms"] == pytest.approx(200.0)
    assert assessment["latency_change_rate_vs_high"] == pytest.approx(0.2)
    assert assessment["saved_cost_per_quality_point_usd"] == pytest.approx(0.6)
    assert assessment["reasonable_tradeoff"] is True


def test_run_id_creates_a_self_contained_judge_first_artifact_folder():
    output_dir, report_name = resolve_artifact_target(
        output_dir="reports/model-routing/legacy",
        run_id="2026-07-18__ticket-json-v1__judge-gpt-5.4-mini__out-256",
    )

    assert output_dir.as_posix() == (
        "reports/model-routing/runs/judge-first/"
        "2026-07-18__ticket-json-v1__judge-gpt-5.4-mini__out-256"
    )
    assert report_name is None


def test_run_config_records_models_and_rejects_a_different_judge(monkeypatch):
    monkeypatch.setattr(
        "scripts.experiment_judge_first_economics_80.build_cases",
        lambda: [object()] * 80,
    )
    with tempfile.TemporaryDirectory(dir=pathlib.Path.cwd()) as temp_dir:
        output_dir = pathlib.Path(temp_dir) / "judge-run"
        config_path = _write_run_config(
            output_dir,
            run_id="2026-07-18__ticket-json-v1__judge-gpt-5-mini__out-256",
            report_name=None,
            batch_size=10,
        )

        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["routing_judge_model"] == ROUTING_JUDGE_MODEL
        assert (
            config["routing_judge_max_output_tokens"]
            == ModelRoutingRuntimeJudge.MAX_OUTPUT_TOKENS
        )
        assert config["artifact_files"]["result"] == "result.json"
        assert config["quality_judge_max_output_tokens"] == 1600
        assert QUALITY_JUDGE_MAX_OUTPUT_TOKENS == 1600
        assert set(config["comparison_arms"]) == set(ARMS)
        assert config["comparison_arms"]["mid_fixed"] == MID_MODEL
        assert config["dataset"]["input_structure_count"] == 4
        assert config["dataset"]["input_length_bucket_count"] == 4

        monkeypatch.setattr(
            "scripts.experiment_judge_first_economics_80.ROUTING_JUDGE_MODEL",
            "gpt-5.4-mini",
        )
        with pytest.raises(RuntimeError, match="routing_judge_model"):
            _write_run_config(
                output_dir,
                run_id="2026-07-18__ticket-json-v1__judge-gpt-5-mini__out-256",
                report_name=None,
                batch_size=10,
            )
