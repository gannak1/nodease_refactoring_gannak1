from copy import deepcopy
from types import SimpleNamespace


def _label(index: int, *, accepted: bool = True):
    simple = index % 2 == 0
    requirements = {
        "task_complexity": 0 if simple else 3,
        "decision_impact": 0 if simple else 3,
        "evidence_synthesis": 0 if simple else 2,
    }
    return SimpleNamespace(
        id=f"label-{index}",
        status="accepted" if accepted else "rejected",
        feature_vector=[1.0, 0.0] if simple else [0.0, 1.0],
        encoder_model_id="test-encoder",
        selected_model_id="gpt-4o-mini" if simple else "gpt-5-mini",
        candidate_model_ids=["gpt-4o-mini", "gpt-5-mini"],
        confidence=0.9,
        reason_code="judge_selected",
        task_requirements=requirements,
        local_prediction=None,
        local_confidence=None,
        local_distance_score=None,
        local_margin=None,
        learning_processed_at=None,
    )


def test_async_batch_predicts_before_learning_and_processes_at_most_ten_labels():
    from apps.workflow_engine.services.model_routing_learning_batch import (
        ModelRoutingLearningBatchService,
    )

    labels = [_label(index) for index in range(12)]
    active_policy = {
        "strategy_id": "judge_bootstrap_incremental_v1",
        "learning": {"mode": "judge_first"},
    }

    result = ModelRoutingLearningBatchService.train_labels(
        active_policy=deepcopy(active_policy),
        labels=labels,
        batch_size=10,
    )

    assert result.processed_count == 10
    assert result.remaining_count == 2
    assert all(label.learning_processed_at is not None for label in labels[:10])
    assert all(label.learning_processed_at is None for label in labels[10:])
    assert labels[0].local_prediction is not None
    assert labels[1].local_prediction is not None
    assert result.active_policy["learning"]["judged_request_count"] == 10
    assert result.active_policy["learning"]["candidate_requirement_artifact"][
        "trained_example_count"
    ] == 10
    assert result.active_policy["learning"]["candidate_requirement_artifact"][
        "encoder_model_id"
    ] == "test-encoder"


def test_async_batch_uses_last_twenty_pre_learning_comparisons_for_readiness():
    from apps.workflow_engine.services.model_routing_learning_batch import (
        ModelRoutingLearningBatchService,
    )

    labels = [_label(index) for index in range(20)]
    active_policy = {
        "strategy_id": "judge_bootstrap_incremental_v1",
        "learning": {"mode": "judge_first", "judged_request_count": 30},
    }

    first = ModelRoutingLearningBatchService.train_labels(
        active_policy=active_policy,
        labels=labels,
        batch_size=10,
    )
    second = ModelRoutingLearningBatchService.train_labels(
        active_policy=first.active_policy,
        labels=labels,
        batch_size=10,
    )

    evaluation = second.active_policy["learning"]["recent_evaluation"]
    assert evaluation["sample_count"] == 20
    assert set(evaluation["axis_mean_errors"]) == {
        "task_complexity",
        "decision_impact",
        "evidence_synthesis",
    }
    assert evaluation["judge_label_diversity"] == 2
    assert evaluation["local_prediction_diversity"] >= 1
    assert len(second.active_policy["learning"]["evaluation_window"]) == 20


def test_async_batch_restarts_learning_when_feature_schema_changes():
    from apps.workflow_engine.services.model_routing_incremental_learning import (
        TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION,
    )
    from apps.workflow_engine.services.model_routing_learning_batch import (
        ModelRoutingLearningBatchService,
    )

    active_policy = {
        "strategy_id": "judge_bootstrap_incremental_v1",
        "learning": {
            "mode": "local_first",
            "judged_request_count": 79,
            "evaluation_window": [{"old": True}],
            "local_requirement_artifact": {
                "feature_schema_version": "prompt_context_v1",
                "trained_example_count": 79,
                "weights": {},
            },
        },
    }

    result = ModelRoutingLearningBatchService.train_labels(
        active_policy=active_policy,
        labels=[_label(0)],
        batch_size=1,
    )

    learning = result.active_policy["learning"]
    artifact = learning["candidate_requirement_artifact"]
    assert artifact["feature_schema_version"] == TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION
    assert artifact["trained_example_count"] == 1
    assert learning["judged_request_count"] == 1
    assert learning["recent_evaluation"]["sample_count"] == 1


def test_batch_result_can_report_deferred_training():
    from apps.workflow_engine.services.model_routing_learning_batch import (
        ModelRoutingLearningBatchResult,
    )

    result = ModelRoutingLearningBatchResult(
        active_policy={},
        processed_count=0,
        remaining_count=3,
        deferred_seconds=300,
    )

    assert result.deferred_seconds == 300


def test_batch_skips_an_invalid_rejected_label_without_blocking_other_learning():
    from apps.workflow_engine.services.model_routing_learning_batch import (
        ModelRoutingLearningBatchService,
    )

    invalid = _label(0, accepted=False)
    invalid.task_requirements = None
    valid = _label(1)

    result = ModelRoutingLearningBatchService.train_labels(
        active_policy={
            "strategy_id": "judge_bootstrap_incremental_v1",
            "learning": {"mode": "judge_first"},
        },
        labels=[invalid, valid],
    )

    assert result.processed_count == 2
    assert invalid.learning_processed_at is not None
    assert valid.learning_processed_at is not None
    assert result.active_policy["learning"]["judged_request_count"] == 1
    assert result.active_policy["learning"]["recent_evaluation"]["sample_count"] == 1
