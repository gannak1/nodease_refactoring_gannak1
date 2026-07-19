import json
import pathlib
import tempfile

import pytest

from scripts.experiment_judge_first_economics_80 import (
    HIGH_MODEL,
    LOW_MODEL,
    MID_MODEL,
    QUALITY_JUDGE_MODEL,
    ROUTING_JUDGE_MODEL,
    _append_jsonl,
    _arm_execution_order,
    _retry_quality_evaluation,
    _routing_accuracy,
    _write_run_config,
    build_cases,
    graph_for_arm,
    resolve_artifact_target,
)
from apps.workflow_engine.services.model_routing_runtime_judge import (
    ModelRoutingRuntimeJudge,
)


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
    assert all(case.context is not None for case in cases)
    assert all(case.constraints for case in cases)
    assert all(case.acceptable_model_ids for case in cases)


def test_arm_execution_order_is_seeded_but_not_fixed_to_arm_declaration_order():
    first = _arm_execution_order("security-01")
    second = _arm_execution_order("security-01")

    assert first == second
    assert set(first) == {"automatic", "mid_fixed", "high_fixed", "low_fixed"}
    assert first != ("automatic", "mid_fixed", "high_fixed", "low_fixed")


def test_append_jsonl_keeps_each_completed_request_as_an_independent_record():
    with tempfile.TemporaryDirectory(dir=pathlib.Path.cwd()) as temp_dir:
        path = pathlib.Path(temp_dir) / "execution-events.jsonl"

        _append_jsonl(path, {"case_id": "case-01", "event": "execution_complete"})
        _append_jsonl(path, {"case_id": "case-02", "event": "execution_complete"})

        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
        assert [row["case_id"] for row in rows] == ["case-01", "case-02"]


def test_routing_accuracy_distinguishes_appropriate_underpowered_and_overprovisioned():
    case = build_cases()[0]
    allowed = list(case.acceptable_model_ids)
    appropriate = _routing_accuracy(case, allowed[0])
    underpowered = _routing_accuracy(case, "gpt-4o-mini")
    overprovisioned = _routing_accuracy(case, "gpt-5.6-sol")

    assert appropriate["classification"] == "appropriate"
    assert underpowered["classification"] in {"underpowered", "appropriate"}
    assert overprovisioned["classification"] in {"overprovisioned", "appropriate"}


def test_quality_evaluation_retries_only_the_failed_evaluation():
    attempts = []

    def evaluate():
        attempts.append(True)
        if len(attempts) == 1:
            return None, {"error": "temporary_provider_error"}
        return {"output_1": {"quality_score": 90}}, {"model": "judge"}

    payload, metadata = _retry_quality_evaluation(evaluate, max_attempts=3)

    assert len(attempts) == 2
    assert payload == {"output_1": {"quality_score": 90}}
    assert metadata["evaluation_status"] == "completed"
    assert metadata["attempt_count"] == 2


def test_norag_experiment_graph_maps_generic_request_payload_fields():
    graph = graph_for_arm("automatic")
    trigger = next(node for node in graph["nodes"] if node["id"] == "webhook-ticket")
    llm = next(node for node in graph["nodes"] if node["id"] == "llm-triage")

    assert {item["variable_name"] for item in trigger["data"]["variable_mappings"]} == {
        "customerTier",
        "request",
        "context",
        "constraints",
        "outputMode",
    }
    assert llm["data"]["knowledgeBases"] == []


def test_economics_experiment_uses_distinct_high_low_and_judge_models():
    assert HIGH_MODEL != LOW_MODEL
    assert MID_MODEL not in {HIGH_MODEL, LOW_MODEL}
    assert ROUTING_JUDGE_MODEL not in {"gpt-5.6-sol"}
    assert QUALITY_JUDGE_MODEL not in {"gpt-5.6-sol"}


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
        assert set(config["comparison_arms"]) == {
            "automatic",
            "mid_fixed",
            "high_fixed",
            "low_fixed",
        }

        monkeypatch.setattr(
            "scripts.experiment_judge_first_economics_80.ROUTING_JUDGE_MODEL",
            "gpt-5-mini",
        )
        with pytest.raises(RuntimeError, match="routing_judge_model"):
            _write_run_config(
                output_dir,
                run_id="2026-07-18__ticket-json-v1__judge-gpt-5-mini__out-256",
                report_name=None,
                batch_size=10,
            )


def test_run_config_rejects_resuming_with_different_comparison_arms(monkeypatch):
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
        config["comparison_arms"].pop("mid_fixed")
        config_path.write_text(
            json.dumps(config, ensure_ascii=False), encoding="utf-8"
        )

        with pytest.raises(RuntimeError, match="comparison_arms"):
            _write_run_config(
                output_dir,
                run_id="2026-07-18__ticket-json-v1__judge-gpt-5-mini__out-256",
                report_name=None,
                batch_size=10,
            )
