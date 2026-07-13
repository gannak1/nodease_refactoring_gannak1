from types import SimpleNamespace
from uuid import uuid4

from apps.workflow_engine.services.model_routing_evidence import (
    ReplayEvidenceAdapter,
)


def _experiment(*, fingerprint: str = "node-fingerprint", cohort_id: str = "routine"):
    return SimpleNamespace(
        id=uuid4(),
        baseline_trace_summary={
            "model_routing": {
                "matched_cohort_id": cohort_id,
                "route_catalog_version": "ticket-routing-v1",
            }
        },
        baseline_node_options={"model_id": "gpt-4.1"},
        baseline_usage_summary={
            "model": "gpt-4.1",
            "cost": 0.003,
            "latency_ms": 1800,
        },
    )


def _candidate(
    *,
    fingerprint: str = "node-fingerprint",
    status: str = "success",
    schema_status: str = "pass",
    downstream_state: str = "compatible",
    quality_status: str = "completed",
):
    return SimpleNamespace(
        id=uuid4(),
        model_id="gpt-4o-mini",
        status=status,
        schema_status=schema_status,
        downstream_state=downstream_state,
        total_cost=0.0005,
        latency_ms=450,
        candidate_settings={
            "_baseline_node_config_fingerprint": fingerprint,
        },
        diff_summary={
            "quality_evaluation": {
                "status": quality_status,
                "baseline": {"score": 88},
                "candidate": {"score": 86},
                "confidence": "high",
                "confidence_score": 0.91,
                "judge_cost": 0.0001,
            },
            "routing_evidence": {
                "schema_required": True,
            },
        },
    )


def test_replay_adapter_accepts_comparable_candidate_with_all_quality_gates():
    candidate = _candidate()
    experiment = _experiment()

    batch = ReplayEvidenceAdapter.from_rows(
        [(candidate, experiment)],
        current_node_fingerprint="node-fingerprint",
    )

    assert batch.excluded_reason_counts == {}
    assert len(batch.samples) == 1
    sample = batch.samples[0]
    assert sample.source == "replay"
    assert sample.model_id == "gpt-4o-mini"
    assert sample.semantic_cohort_id == "routine"
    assert sample.baseline_model_id == "gpt-4.1"
    assert sample.baseline_execution_cost == 0.003
    assert sample.baseline_latency_ms == 1800
    assert sample.execution_succeeded is True
    assert sample.schema_passed is True
    assert sample.downstream_passed is True
    assert sample.quality_score == 86
    assert sample.baseline_quality_score == 88
    assert sample.quality_confidence == 0.91
    assert sample.execution_cost == 0.0005
    assert sample.evaluation_cost == 0.0001


def test_replay_adapter_excludes_stale_but_keeps_failures_as_negative_evidence():
    stale = _candidate(fingerprint="old-fingerprint")
    schema_failed = _candidate(schema_status="failed")
    no_quality = _candidate(quality_status="unavailable")

    batch = ReplayEvidenceAdapter.from_rows(
        [
            (stale, _experiment()),
            (schema_failed, _experiment()),
            (no_quality, _experiment()),
        ],
        current_node_fingerprint="node-fingerprint",
    )

    assert len(batch.samples) == 2
    assert batch.excluded_reason_counts == {"node_fingerprint_mismatch": 1}
    assert batch.samples[0].schema_passed is False
    assert batch.samples[0].quality_score == 86
    assert batch.samples[1].schema_passed is True
    assert batch.samples[1].quality_score is None
