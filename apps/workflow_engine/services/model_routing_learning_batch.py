"""Judge label을 실행 경로 밖에서 순서대로 평가하고 학습한다."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterable

from apps.workflow_engine.services.model_routing_incremental_learning import (
    IncrementalTaskRequirementClassifier,
    TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION,
)
from apps.workflow_engine.services.model_routing_decision_cache import (
    remember_accepted_decision,
)


EVALUATION_WINDOW_SIZE = 20
DEFAULT_LEARNING_BATCH_SIZE = 10
MAX_BATCH_WAIT_SECONDS = 300


@dataclass(frozen=True)
class ModelRoutingLearningBatchResult:
    active_policy: dict[str, Any]
    processed_count: int
    remaining_count: int
    deferred_seconds: int | None = None


class ModelRoutingLearningBatchService:
    """학습 전 예측과 Judge 정답을 비교한 뒤 candidate artifact를 갱신한다."""

    @classmethod
    def train_labels(
        cls,
        *,
        active_policy: dict[str, Any],
        labels: Iterable[Any],
        batch_size: int = DEFAULT_LEARNING_BATCH_SIZE,
        processed_at: datetime | None = None,
    ) -> ModelRoutingLearningBatchResult:
        policy = deepcopy(active_policy)
        learning = (
            deepcopy(policy.get("learning"))
            if isinstance(policy.get("learning"), dict)
            else {}
        )
        pending = [
            label
            for label in labels
            if getattr(label, "learning_processed_at", None) is None
            and str(getattr(label, "status", "")) in {"accepted", "rejected"}
        ]
        batch = pending[: max(1, int(batch_size))]
        stored_artifact = deepcopy(
            learning.get("candidate_requirement_artifact")
            or learning.get("local_requirement_artifact")
            or {}
        )
        window = list(learning.get("evaluation_window") or [])
        judged_request_count = int(learning.get("judged_request_count") or 0)
        selected_model_ids = set(learning.get("selected_model_ids") or [])
        selected_model_counts = dict(learning.get("selected_model_counts") or {})
        if (
            stored_artifact.get("feature_schema_version")
            != TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION
        ):
            artifact: dict[str, Any] = {}
            window = []
            judged_request_count = 0
            selected_model_ids = set()
            selected_model_counts = {}
        else:
            artifact = stored_artifact
        timestamp = processed_at or datetime.now(timezone.utc)

        for label in batch:
            try:
                truth = cls._requirements(getattr(label, "task_requirements", None))
            except (KeyError, TypeError, ValueError):
                label.learning_processed_at = timestamp
                continue
            prediction = IncrementalTaskRequirementClassifier.predict(
                artifact,
                vector=getattr(label, "feature_vector", None) or [],
            )
            if getattr(label, "local_prediction", None) is None:
                label.local_prediction = dict(prediction.requirements)
                label.local_confidence = prediction.confidence
                label.local_distance_score = prediction.distance_score
                label.local_margin = prediction.margin

            contract_passed = str(getattr(label, "status", "")) == "accepted"
            window.append(
                cls._evaluation_entry(
                    prediction=dict(label.local_prediction),
                    truth=truth,
                    contract_passed=contract_passed,
                )
            )
            if contract_passed:
                encoder_model_id = str(
                    getattr(label, "encoder_model_id", "") or ""
                ).strip()
                artifact_encoder = str(artifact.get("encoder_model_id") or "").strip()
                if artifact_encoder and encoder_model_id != artifact_encoder:
                    label.learning_processed_at = timestamp
                    continue
                artifact = IncrementalTaskRequirementClassifier.update(
                    artifact,
                    vector=getattr(label, "feature_vector", None) or [],
                    task_requirements=truth,
                )
                if encoder_model_id:
                    artifact["encoder_model_id"] = encoder_model_id
                artifact["feature_schema_version"] = (
                    TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION
                )
                judged_request_count += 1
                selected_model_id = str(
                    getattr(label, "selected_model_id", "") or ""
                ).strip()
                if selected_model_id:
                    selected_model_ids.add(selected_model_id)
                    selected_model_counts[selected_model_id] = (
                        int(selected_model_counts.get(selected_model_id) or 0) + 1
                    )
                    remember_accepted_decision(
                        learning,
                        feature_hash=getattr(label, "routing_feature_hash", None),
                        selected_model_id=selected_model_id,
                        confidence=getattr(label, "confidence", None),
                        reason_code=getattr(label, "reason_code", None),
                    )
            label.learning_processed_at = timestamp

        window = window[-EVALUATION_WINDOW_SIZE:]
        evaluation = cls._evaluation_summary(window)
        artifact["recent_judge_match_rate"] = evaluation["judge_match_rate"]
        artifact["recent_contract_pass_rate"] = evaluation["contract_pass_rate"]
        learning["candidate_requirement_artifact"] = artifact
        learning["judged_request_count"] = judged_request_count
        learning["selected_model_ids"] = sorted(selected_model_ids)
        learning["selected_model_counts"] = selected_model_counts
        learning["evaluation_window"] = window
        learning["recent_evaluation"] = evaluation
        policy["learning"] = learning
        return ModelRoutingLearningBatchResult(
            active_policy=policy,
            processed_count=len(batch),
            remaining_count=max(0, len(pending) - len(batch)),
        )

    @classmethod
    def train_pending(
        cls,
        db,
        *,
        policy_id: str,
        force: bool = False,
        now: datetime | None = None,
    ) -> ModelRoutingLearningBatchResult:
        """정책별 대기 label을 잠근 뒤 10건 또는 최대 5분 단위로 학습한다."""

        from apps.shared.db.models.model_routing_policy import (
            LLMNodeModelRoutingLearningLabel,
            LLMNodeModelRoutingPolicy,
        )
        from apps.workflow_engine.services.model_routing_policy_store import (
            ModelRoutingPolicyStore,
        )

        timestamp = now or datetime.now(timezone.utc)
        policy = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.id == policy_id)
            .populate_existing()
            .with_for_update()
            .first()
        )
        if policy is None:
            return ModelRoutingLearningBatchResult({}, 0, 0)

        labels = (
            db.query(LLMNodeModelRoutingLearningLabel)
            .filter(LLMNodeModelRoutingLearningLabel.policy_id == policy.id)
            .filter(LLMNodeModelRoutingLearningLabel.status.in_(("accepted", "rejected")))
            .filter(LLMNodeModelRoutingLearningLabel.learning_processed_at.is_(None))
            .order_by(LLMNodeModelRoutingLearningLabel.created_at.asc())
            .all()
        )
        if not labels:
            return ModelRoutingLearningBatchResult(
                dict(policy.active_policy or {}), 0, 0
            )

        if len(labels) < DEFAULT_LEARNING_BATCH_SIZE and not force:
            oldest = getattr(labels[0], "finalized_at", None) or labels[0].created_at
            if oldest.tzinfo is None:
                oldest = oldest.replace(tzinfo=timezone.utc)
            elapsed = max(0, int((timestamp - oldest).total_seconds()))
            remaining_wait = max(0, MAX_BATCH_WAIT_SECONDS - elapsed)
            if remaining_wait:
                return ModelRoutingLearningBatchResult(
                    dict(policy.active_policy or {}),
                    0,
                    len(labels),
                    deferred_seconds=remaining_wait,
                )

        result = cls.train_labels(
            active_policy=dict(policy.active_policy or {}),
            labels=labels,
            batch_size=DEFAULT_LEARNING_BATCH_SIZE,
            processed_at=timestamp,
        )
        policy.active_policy = result.active_policy
        ModelRoutingPolicyStore.reconcile_incremental_learning_mode(db, policy=policy)
        db.flush()
        return ModelRoutingLearningBatchResult(
            active_policy=dict(policy.active_policy or {}),
            processed_count=result.processed_count,
            remaining_count=result.remaining_count,
        )

    @staticmethod
    def _requirements(value: Any) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValueError("task_requirements is required")
        return {
            key: max(0, min(3, int(value[key])))
            for key in IncrementalTaskRequirementClassifier.REQUIREMENT_KEYS
        }

    @classmethod
    def _evaluation_entry(
        cls,
        *,
        prediction: dict[str, int],
        truth: dict[str, int],
        contract_passed: bool,
    ) -> dict[str, Any]:
        errors = {
            key: abs(int(prediction[key]) - int(truth[key]))
            for key in IncrementalTaskRequirementClassifier.REQUIREMENT_KEYS
        }
        return {
            "prediction": prediction,
            "judge": truth,
            "exact_match": all(error == 0 for error in errors.values()),
            "axis_errors": errors,
            "contract_passed": contract_passed,
        }

    @classmethod
    def _evaluation_summary(cls, window: list[dict[str, Any]]) -> dict[str, Any]:
        count = len(window)
        keys = IncrementalTaskRequirementClassifier.REQUIREMENT_KEYS
        if not count:
            return {
                "sample_count": 0,
                "judge_match_rate": 0.0,
                "axis_mean_errors": {key: 0.0 for key in keys},
                "judge_label_diversity": 0,
                "local_prediction_diversity": 0,
                "contract_pass_rate": 0.0,
            }
        judge_labels = {
            tuple(int(row["judge"][key]) for key in keys) for row in window
        }
        predictions = {
            tuple(int(row["prediction"][key]) for key in keys) for row in window
        }
        return {
            "sample_count": count,
            "judge_match_rate": round(
                sum(bool(row["exact_match"]) for row in window) / count, 4
            ),
            "axis_mean_errors": {
                key: round(
                    sum(float(row["axis_errors"][key]) for row in window) / count,
                    4,
                )
                for key in keys
            },
            "judge_label_diversity": len(judge_labels),
            "local_prediction_diversity": len(predictions),
            "contract_pass_rate": round(
                sum(bool(row["contract_passed"]) for row in window) / count,
                4,
            ),
        }
