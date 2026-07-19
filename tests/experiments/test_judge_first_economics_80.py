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
    _write_run_config,
    build_cases,
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
            "gpt-5.4-mini",
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
