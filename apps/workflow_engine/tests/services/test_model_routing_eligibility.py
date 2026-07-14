from types import SimpleNamespace

from apps.workflow_engine.services.model_routing_evidence import RoutingEvidenceBatch
from apps.workflow_engine.services.model_routing_eligibility import (
    ModelRoutingEligibilityService,
)


def _catalog(*cohort_ids: str):
    return {
        "route_catalog_version": "ticket-routing-v1",
        "encoder_model_id": "text-embedding-3-small",
        "routes": [
            {
                "cohort_id": cohort_id,
                "label": cohort_id,
                "threshold": 0.7,
                "representatives": [{"embedding": [1.0, 0.0]}],
            }
            for cohort_id in cohort_ids
        ],
    }


def _batch(*model_ids: str) -> RoutingEvidenceBatch:
    return RoutingEvidenceBatch(
        samples=tuple(
            SimpleNamespace(model_id=model_id, semantic_cohort_id="routine_support")
            for model_id in model_ids
        ),
        excluded_reason_counts={},
    )


def test_eligibility_recommends_fixed_model_when_only_one_model_is_executable():
    result = ModelRoutingEligibilityService.evaluate(
        candidate_model_ids=["gpt-4.1"],
        available_model_ids={"gpt-4.1"},
        semantic_catalog=_catalog("routine_support"),
        evidence_batch=_batch("gpt-4.1"),
        current_model_id="gpt-4.1",
    )

    assert result.status == "fixed_model_recommended"
    assert result.reason_code == "executable_candidates_insufficient"


def test_eligibility_rejects_candidate_without_execution_subject_permission():
    result = ModelRoutingEligibilityService.evaluate(
        candidate_model_ids=["gpt-4.1", "gpt-4o-mini"],
        available_model_ids={"gpt-4.1"},
        semantic_catalog=_catalog("routine_support"),
        evidence_batch=_batch("gpt-4o-mini"),
        current_model_id="gpt-4.1",
    )

    assert result.status == "fixed_model_recommended"
    assert result.eligible_model_ids == ("gpt-4.1",)
    assert result.excluded_model_ids == ("gpt-4o-mini",)


def test_eligibility_requires_versioned_semantic_catalog():
    result = ModelRoutingEligibilityService.evaluate(
        candidate_model_ids=["gpt-4.1", "gpt-4o-mini"],
        available_model_ids={"gpt-4.1", "gpt-4o-mini"},
        semantic_catalog={},
        evidence_batch=_batch("gpt-4o-mini"),
        current_model_id="gpt-4.1",
    )

    assert result.status == "fixed_model_recommended"
    assert result.reason_code == "semantic_catalog_unavailable"


def test_eligibility_reports_evidence_gap_before_candidate_is_validated():
    result = ModelRoutingEligibilityService.evaluate(
        candidate_model_ids=["gpt-4.1", "gpt-4o-mini"],
        available_model_ids={"gpt-4.1", "gpt-4o-mini"},
        semantic_catalog=_catalog("routine_support"),
        evidence_batch=_batch(),
        current_model_id="gpt-4.1",
    )

    assert result.status == "needs_evidence"
    assert result.reason_code == "validated_candidate_evidence_unavailable"


def test_eligibility_accepts_alternate_model_with_replay_evidence():
    result = ModelRoutingEligibilityService.evaluate(
        candidate_model_ids=["gpt-4.1", "gpt-4o-mini"],
        available_model_ids={"gpt-4.1", "gpt-4o-mini"},
        semantic_catalog=_catalog("routine_support", "high_risk"),
        evidence_batch=_batch("gpt-4o-mini"),
        current_model_id="gpt-4.1",
    )

    assert result.status == "eligible"
    assert result.reason_code == "semantic_routing_evidence_available"
    assert result.evidence_model_ids == ("gpt-4o-mini",)
