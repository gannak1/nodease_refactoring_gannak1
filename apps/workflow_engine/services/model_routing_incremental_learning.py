"""Judge 선택을 점진적으로 재현하는 작은 다중 모델 분류기.

이 모듈은 임베더가 만든 숫자 벡터만 받는다. 원문 요청은 저장하지 않으며, policy
JSON에는 모델 ID, 선형 head 가중치, 표본 수만 남는다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable


# Local routing begins only after enough deployed, contract-passing Judge labels
# have accumulated to make its first autonomous choice meaningful.
MIN_JUDGED_REQUESTS = 50
MIN_DISTINCT_SELECTED_MODELS = 2
MAX_SELECTED_MODEL_SHARE = 0.70
MIN_SUCCESS_RATE = 0.95
MIN_SCHEMA_PASS_RATE = 0.95
MIN_DOWNSTREAM_SUCCESS_RATE = 0.95
MAX_FALLBACK_RATE = 0.05
TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION = "grouped_runtime_variables_v4_e5"


@dataclass(frozen=True)
class LocalModelChoicePrediction:
    selected_model_id: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class LocalTaskRequirementPrediction:
    """현재 요청이 요구하는 능력 수준의 local 추정값."""

    requirements: dict[str, int]
    confidence: float
    raw_requirements: dict[str, float]
    distance_score: float
    margin: float


class IncrementalTaskRequirementClassifier:
    """Judge가 판정한 요청 요구 수준을 독립적으로 누적한다.

    이 head는 모델 ID를 목표값으로 사용하지 않는다. 따라서 특정 모델이 많이
    선택됐다는 사실만으로 다음 요청도 같은 모델을 고르는 편향을 만들지 않는다.
    """

    ARTIFACT_KIND = "multilingual_e5_task_requirements_online_v1"
    REQUIREMENT_KEYS = (
        "task_complexity",
        "decision_impact",
        "evidence_synthesis",
    )
    LEARNING_RATE = 0.10
    L2 = 0.0005

    @classmethod
    def update(
        cls,
        artifact: dict[str, Any] | None,
        *,
        vector: Iterable[float],
        task_requirements: dict[str, Any],
    ) -> dict[str, Any]:
        values = cls._vector(vector)
        targets = cls._requirements(task_requirements)
        state = cls._state(artifact, len(values))
        total_error = 0.0
        for key in cls.REQUIREMENT_KEYS:
            prediction = cls._predict_value(state, key, values)
            error = float(targets[key]) - prediction
            total_error += abs(error)
            weights = state["weights"][key]
            state["weights"][key] = [
                weight + cls.LEARNING_RATE * (error * feature - cls.L2 * weight)
                for weight, feature in zip(weights, values)
            ]
            state["bias"][key] = float(state["bias"][key]) + cls.LEARNING_RATE * error

        count = int(state["trained_example_count"]) + 1
        previous_error = float(state.get("training_error_ema") or 0.0)
        state["training_error_ema"] = (
            total_error / len(cls.REQUIREMENT_KEYS)
            if count == 1
            else previous_error * 0.9
            + (total_error / len(cls.REQUIREMENT_KEYS)) * 0.1
        )
        state["trained_example_count"] = count
        state["feature_schema_version"] = TASK_REQUIREMENT_FEATURE_SCHEMA_VERSION
        cls._update_centroid(state, values, targets)
        return state

    @classmethod
    def predict(
        cls,
        artifact: dict[str, Any] | None,
        *,
        vector: Iterable[float],
    ) -> LocalTaskRequirementPrediction:
        values = cls._vector(vector)
        state = cls._state(artifact, len(values))
        raw_requirements = {
            key: max(0.0, min(3.0, cls._predict_value(state, key, values)))
            for key in cls.REQUIREMENT_KEYS
        }
        requirements = {
            key: int(round(value)) for key, value in raw_requirements.items()
        }
        distance_score = cls._distance_score(state, values)
        margin = min(cls._ordinal_margin(value) for value in raw_requirements.values())
        recent_match_rate = max(
            0.0, min(1.0, float(state.get("recent_judge_match_rate") or 0.0))
        )
        recent_contract_rate = max(
            0.0, min(1.0, float(state.get("recent_contract_pass_rate") or 0.0))
        )
        return LocalTaskRequirementPrediction(
            requirements=requirements,
            confidence=round(
                recent_match_rate
                * distance_score
                * margin
                * recent_contract_rate,
                4,
            ),
            raw_requirements={
                key: round(value, 4) for key, value in raw_requirements.items()
            },
            distance_score=round(distance_score, 4),
            margin=round(margin, 4),
        )

    @classmethod
    def _state(cls, artifact: dict[str, Any] | None, dimensions: int) -> dict[str, Any]:
        previous = artifact if isinstance(artifact, dict) else {}
        weights = previous.get("weights") if isinstance(previous.get("weights"), dict) else {}
        bias = previous.get("bias") if isinstance(previous.get("bias"), dict) else {}
        return {
            "kind": cls.ARTIFACT_KIND,
            "weights": {
                key: [float(value) for value in weights.get(key, [])]
                if isinstance(weights.get(key), list) and len(weights.get(key)) == dimensions
                else [0.0] * dimensions
                for key in cls.REQUIREMENT_KEYS
            },
            "bias": {key: float(bias.get(key) or 0.0) for key in cls.REQUIREMENT_KEYS},
            "trained_example_count": int(previous.get("trained_example_count") or 0),
            "training_error_ema": float(previous.get("training_error_ema") or 0.0),
            "requirement_centroids": dict(previous.get("requirement_centroids") or {}),
            "recent_judge_match_rate": float(
                previous.get("recent_judge_match_rate") or 0.0
            ),
            "recent_contract_pass_rate": float(
                previous.get("recent_contract_pass_rate") or 0.0
            ),
        }

    @staticmethod
    def _vector(vector: Iterable[float]) -> list[float]:
        values = [float(value) for value in vector]
        if not values:
            raise ValueError("vector is required")
        return values

    @classmethod
    def _requirements(cls, value: dict[str, Any]) -> dict[str, int]:
        if not isinstance(value, dict):
            raise ValueError("task_requirements is required")
        result: dict[str, int] = {}
        for key in cls.REQUIREMENT_KEYS:
            raw = value.get(key)
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                raise ValueError(f"{key} is required")
            if isinstance(raw, float) and not raw.is_integer():
                raise ValueError(f"{key} must be an integer")
            result[key] = max(0, min(3, int(raw)))
        return result

    @staticmethod
    def _predict_value(state: dict[str, Any], key: str, vector: list[float]) -> float:
        return sum(
            weight * value
            for weight, value in zip(state["weights"][key], vector)
        ) + float(state["bias"][key])

    @classmethod
    def _update_centroid(
        cls,
        state: dict[str, Any],
        vector: list[float],
        targets: dict[str, int],
    ) -> None:
        key = ":".join(str(targets[name]) for name in cls.REQUIREMENT_KEYS)
        centroids = state["requirement_centroids"]
        current = centroids.get(key) if isinstance(centroids.get(key), dict) else {}
        count = int(current.get("count") or 0)
        previous = current.get("vector") if isinstance(current.get("vector"), list) else []
        if len(previous) != len(vector):
            previous = [0.0] * len(vector)
            count = 0
        next_count = count + 1
        centroids[key] = {
            "count": next_count,
            "vector": [
                ((float(old) * count) + value) / next_count
                for old, value in zip(previous, vector)
            ],
        }

    @staticmethod
    def _distance_score(state: dict[str, Any], vector: list[float]) -> float:
        centroids = state.get("requirement_centroids")
        if not isinstance(centroids, dict) or not centroids:
            return 0.0
        vector_norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        similarities: list[float] = []
        for centroid in centroids.values():
            row = centroid.get("vector") if isinstance(centroid, dict) else None
            if not isinstance(row, list) or len(row) != len(vector):
                continue
            row_values = [float(value) for value in row]
            row_norm = math.sqrt(sum(value * value for value in row_values)) or 1.0
            cosine = sum(a * b for a, b in zip(vector, row_values)) / (
                vector_norm * row_norm
            )
            similarities.append(max(0.0, min(1.0, cosine)))
        return max(similarities, default=0.0)

    @staticmethod
    def _ordinal_margin(value: float) -> float:
        rounded = max(0, min(3, int(round(value))))
        distance_to_center = abs(value - rounded)
        return max(0.0, min(1.0, 1.0 - distance_to_center * 2.0))


class IncrementalModelChoiceClassifier:
    """고정 encoder 위에서 online softmax head만 갱신한다."""

    ARTIFACT_KIND = "multilingual_e5_model_choice_online_v1"
    LEARNING_RATE = 0.16
    L2 = 0.0005

    @classmethod
    def update(
        cls,
        artifact: dict[str, Any] | None,
        *,
        vector: Iterable[float],
        selected_model_id: str,
        candidate_model_ids: Iterable[str],
    ) -> dict[str, Any]:
        values = cls._vector(vector)
        candidates = cls._models(candidate_model_ids, selected_model_id)
        state = cls._state(artifact, candidates, len(values))
        model_ids = state["model_ids"]
        probabilities = cls._probabilities(state, values, model_ids)

        for model_id in model_ids:
            target = 1.0 if model_id == selected_model_id else 0.0
            error = target - probabilities[model_id]
            weights = state["weights"][model_id]
            state["weights"][model_id] = [
                weight + cls.LEARNING_RATE * (error * feature - cls.L2 * weight)
                for weight, feature in zip(weights, values)
            ]
            state["bias"][model_id] = float(state["bias"][model_id]) + cls.LEARNING_RATE * error

        state["trained_example_count"] = int(state["trained_example_count"]) + 1
        labels = set(state.get("selected_model_ids") or [])
        labels.add(selected_model_id)
        state["selected_model_ids"] = sorted(labels)
        return state

    @classmethod
    def predict(
        cls,
        artifact: dict[str, Any] | None,
        *,
        vector: Iterable[float],
        available_model_ids: Iterable[str],
    ) -> LocalModelChoicePrediction:
        values = cls._vector(vector)
        allowed = cls._models(available_model_ids)
        if not allowed:
            raise ValueError("available_model_ids is required")
        state = cls._state(artifact, allowed, len(values))
        candidates = [model_id for model_id in allowed if model_id in state["model_ids"]]
        if not candidates:
            candidates = allowed
        probabilities = cls._probabilities(state, values, candidates)
        selected = max(candidates, key=lambda model_id: probabilities[model_id])
        return LocalModelChoicePrediction(
            selected_model_id=selected,
            confidence=probabilities[selected],
            probabilities=probabilities,
        )

    @classmethod
    def _state(
        cls,
        artifact: dict[str, Any] | None,
        model_ids: list[str],
        dimensions: int,
    ) -> dict[str, Any]:
        previous = artifact if isinstance(artifact, dict) else {}
        prior_ids = cls._models(previous.get("model_ids") or [])
        all_ids = cls._models([*prior_ids, *model_ids])
        weights = previous.get("weights") if isinstance(previous.get("weights"), dict) else {}
        bias = previous.get("bias") if isinstance(previous.get("bias"), dict) else {}
        normalized_weights: dict[str, list[float]] = {}
        normalized_bias: dict[str, float] = {}
        for model_id in all_ids:
            row = weights.get(model_id)
            normalized_weights[model_id] = (
                [float(value) for value in row]
                if isinstance(row, list) and len(row) == dimensions
                else [0.0] * dimensions
            )
            normalized_bias[model_id] = float(bias.get(model_id) or 0.0)
        return {
            "kind": cls.ARTIFACT_KIND,
            "model_ids": all_ids,
            "weights": normalized_weights,
            "bias": normalized_bias,
            "trained_example_count": int(previous.get("trained_example_count") or 0),
            "selected_model_ids": cls._models(previous.get("selected_model_ids") or []),
        }

    @staticmethod
    def _vector(vector: Iterable[float]) -> list[float]:
        values = [float(value) for value in vector]
        if not values:
            raise ValueError("vector is required")
        return values

    @staticmethod
    def _models(model_ids: Iterable[str], extra: str | None = None) -> list[str]:
        result: list[str] = []
        for raw in [*model_ids, extra]:
            model_id = str(raw or "").strip()
            if model_id and model_id not in result:
                result.append(model_id)
        return result

    @staticmethod
    def _probabilities(state: dict[str, Any], vector: list[float], model_ids: list[str]) -> dict[str, float]:
        logits = {
            model_id: sum(weight * value for weight, value in zip(state["weights"].get(model_id, []), vector))
            + float(state["bias"].get(model_id) or 0.0)
            for model_id in model_ids
        }
        max_logit = max(logits.values())
        exp_values = {model_id: math.exp(logit - max_logit) for model_id, logit in logits.items()}
        denominator = sum(exp_values.values()) or 1.0
        return {model_id: value / denominator for model_id, value in exp_values.items()}


def learning_mode_for(
    *,
    judged_request_count: int,
    distinct_selected_model_count: int | None = None,
    success_rate: float | None,
    schema_pass_rate: float | None,
    downstream_success_rate: float | None,
    fallback_rate: float | None,
    largest_selected_model_share: float | None = None,
    recent_judge_match_rate: float | None = None,
    recent_axis_mean_errors: dict[str, float] | None = None,
    recent_judge_label_diversity: int | None = None,
    recent_local_prediction_diversity: int | None = None,
    recent_contract_pass_rate: float | None = None,
    recent_evaluation_sample_count: int | None = None,
) -> str:
    """정확한 표본과 운영 결과가 모였을 때만 local-first로 바꾼다."""

    if judged_request_count < MIN_JUDGED_REQUESTS:
        return "judge_first"
    if (recent_evaluation_sample_count or 0) < 20:
        return "judge_first"
    if recent_judge_match_rate is None or recent_judge_match_rate < 0.80:
        return "judge_first"
    axis_errors = recent_axis_mean_errors or {}
    if any(
        axis_errors.get(key) is None or float(axis_errors[key]) > 0.5
        for key in IncrementalTaskRequirementClassifier.REQUIREMENT_KEYS
    ):
        return "judge_first"
    if (
        (recent_judge_label_diversity or 0) > 1
        and (recent_local_prediction_diversity or 0) <= 1
    ):
        return "judge_first"
    if recent_contract_pass_rate is None or recent_contract_pass_rate < 0.95:
        return "judge_first"
    if (success_rate or 0.0) < MIN_SUCCESS_RATE:
        return "judge_first"
    if (schema_pass_rate or 0.0) < MIN_SCHEMA_PASS_RATE:
        return "judge_first"
    if (downstream_success_rate or 0.0) < MIN_DOWNSTREAM_SUCCESS_RATE:
        return "judge_first"
    if (fallback_rate or 0.0) > MAX_FALLBACK_RATE:
        return "judge_first"
    return "local_first"
