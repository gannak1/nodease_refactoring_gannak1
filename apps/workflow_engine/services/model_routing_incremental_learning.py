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
MIN_SUCCESS_RATE = 0.95
MIN_SCHEMA_PASS_RATE = 0.95
MIN_DOWNSTREAM_SUCCESS_RATE = 0.95
MAX_FALLBACK_RATE = 0.05


@dataclass(frozen=True)
class LocalModelChoicePrediction:
    selected_model_id: str
    confidence: float
    probabilities: dict[str, float]


class IncrementalModelChoiceClassifier:
    """고정 encoder 위에서 online softmax head만 갱신한다."""

    ARTIFACT_KIND = "mdeberta_model_choice_online_v1"
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
    distinct_selected_model_count: int,
    success_rate: float | None,
    schema_pass_rate: float | None,
    downstream_success_rate: float | None,
    fallback_rate: float | None,
) -> str:
    """정확한 표본과 운영 결과가 모였을 때만 local-first로 바꾼다."""

    if judged_request_count < MIN_JUDGED_REQUESTS:
        return "judge_first"
    if distinct_selected_model_count < MIN_DISTINCT_SELECTED_MODELS:
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
