"""Judge 선택을 점진적으로 재현하는 multilingual E5 기반 local router."""

from __future__ import annotations

import json
import math
import os
import threading
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Protocol


DEFAULT_MULTILINGUAL_E5_MODEL_ID = "intfloat/multilingual-e5-base"


class TextEmbedder(Protocol):
    model_id: str

    def encode(
        self,
        texts: list[str],
        *,
        mode: str = "plain",
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class ModelChoicePrediction:
    selected_model_id: str
    confidence: float
    probabilities: dict[str, float]


@dataclass(frozen=True)
class TaskRequirementPrediction:
    requirements: dict[str, int]
    confidence: float


class MultilingualE5Embedder:
    """동일 worker에서 공유하는 lazy-loaded multilingual E5 encoder."""

    def __init__(self, model_id: str | None = None):
        self.model_id = (
            model_id
            or os.getenv("MODEL_ROUTING_EMBEDDING_MODEL_ID")
            or DEFAULT_MULTILINGUAL_E5_MODEL_ID
        )
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._load_lock = threading.Lock()

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
                import torch
                from transformers import AutoModel, AutoTokenizer
            except ImportError as exc:  # pragma: no cover - 배포 의존성 guard
                raise RuntimeError(
                    "로컬 모델 라우터 의존성이 설치되지 않았습니다. "
                    "workflow_engine image를 다시 빌드하세요."
                ) from exc

            self._torch = torch
            self._tokenizer = AutoTokenizer.from_pretrained(
                self.model_id,
                use_fast=False,
            )
            self._model = AutoModel.from_pretrained(self.model_id)
            self._model.eval()

    def encode(
        self,
        texts: list[str],
        *,
        mode: str = "plain",
    ) -> list[list[float]]:
        self._load()
        assert self._tokenizer is not None
        assert self._model is not None
        assert self._torch is not None
        if not texts:
            return []

        encoded = self._tokenizer(
            [str(text or "").strip() for text in texts],
            padding=True,
            truncation=True,
            max_length=512,
            return_tensors="pt",
        )
        with self._torch.no_grad():
            output = self._model(**encoded)
        token_embeddings = output.last_hidden_state
        attention_mask = encoded["attention_mask"].unsqueeze(-1).expand_as(
            token_embeddings
        )
        pooled = (token_embeddings * attention_mask).sum(dim=1) / attention_mask.sum(
            dim=1
        ).clamp(min=1)
        return pooled.cpu().tolist()


class MultilingualE5ModelChoiceClassifier:
    """원문을 저장하지 않고 Judge label을 online classification head에 누적한다."""

    _embedder_cache: dict[str, MultilingualE5Embedder] = {}
    _embedder_cache_lock = threading.Lock()
    _LEARNING_GROUP_WEIGHTS = {
        "primary_request": 0.75,
        "dynamic_context": 0.15,
        "structured_features": 0.10,
    }

    @classmethod
    def update(
        cls,
        artifact: dict[str, Any] | None,
        *,
        text: str,
        selected_model_id: str,
        candidate_model_ids: Iterable[str],
        embedder: TextEmbedder | None = None,
    ) -> dict[str, Any]:
        from apps.workflow_engine.services.model_routing_incremental_learning import (
            IncrementalModelChoiceClassifier,
        )

        vector, encoder_model_id = cls._vector(
            text,
            artifact=artifact,
            embedder=embedder,
        )
        updated = IncrementalModelChoiceClassifier.update(
            artifact,
            vector=vector,
            selected_model_id=selected_model_id,
            candidate_model_ids=candidate_model_ids,
        )
        updated["encoder_model_id"] = encoder_model_id
        updated["classification_strategy"] = (
            "frozen_multilingual_e5_online_model_choice_v1"
        )
        return updated

    @classmethod
    def vectorize(
        cls,
        text: str,
        *,
        artifact: dict[str, Any] | None,
        embedder: TextEmbedder | None = None,
    ) -> tuple[list[float], str]:
        """원문을 저장하지 않고 현재 요청의 학습용 vector만 만든다."""
        return cls._vector(text, artifact=artifact, embedder=embedder)

    @classmethod
    def update_from_vector(
        cls,
        artifact: dict[str, Any] | None,
        *,
        vector: Iterable[float],
        encoder_model_id: str | None,
        selected_model_id: str,
        candidate_model_ids: Iterable[str],
    ) -> dict[str, Any]:
        from apps.workflow_engine.services.model_routing_incremental_learning import (
            IncrementalModelChoiceClassifier,
        )

        updated = IncrementalModelChoiceClassifier.update(
            artifact,
            vector=vector,
            selected_model_id=selected_model_id,
            candidate_model_ids=candidate_model_ids,
        )
        updated["encoder_model_id"] = str(encoder_model_id or "")
        updated["classification_strategy"] = (
            "frozen_multilingual_e5_online_model_choice_v1"
        )
        return updated

    @classmethod
    def predict(
        cls,
        artifact: dict[str, Any],
        *,
        text: str,
        available_model_ids: Iterable[str],
        embedder: TextEmbedder | None = None,
    ) -> ModelChoicePrediction:
        from apps.workflow_engine.services.model_routing_incremental_learning import (
            IncrementalModelChoiceClassifier,
        )

        vector, _ = cls._vector(text, artifact=artifact, embedder=embedder)
        result = IncrementalModelChoiceClassifier.predict(
            artifact,
            vector=vector,
            available_model_ids=available_model_ids,
        )
        return ModelChoicePrediction(
            selected_model_id=result.selected_model_id,
            confidence=result.confidence,
            probabilities=result.probabilities,
        )

    @classmethod
    def _vector(
        cls,
        text: str,
        *,
        artifact: dict[str, Any] | None,
        embedder: TextEmbedder | None,
    ) -> tuple[list[float], str]:
        encoder_model_id = str((artifact or {}).get("encoder_model_id") or "")
        runtime_embedder = embedder or cls._shared_embedder(encoder_model_id or None)
        grouped_texts = cls._grouped_learning_texts(text)
        vectors = cls._encode(
            runtime_embedder,
            [serialized for _group, serialized in grouped_texts],
        )
        if not vectors or len(vectors) != len(grouped_texts):
            raise ValueError("모델 선택 학습용 multilingual E5 벡터를 만들지 못했습니다.")
        normalized_vectors = [cls._l2_normalize(vector) for vector in vectors]
        total_weight = sum(
            cls._LEARNING_GROUP_WEIGHTS[group] for group, _text in grouped_texts
        )
        combined = [0.0] * len(normalized_vectors[0])
        for (group, _text), vector in zip(grouped_texts, normalized_vectors):
            if len(vector) != len(combined):
                raise ValueError("학습 feature group의 embedding 차원이 다릅니다.")
            weight = cls._LEARNING_GROUP_WEIGHTS[group] / total_weight
            combined = [
                current + weight * value
                for current, value in zip(combined, vector)
            ]
        return cls._l2_normalize(combined), runtime_embedder.model_id

    @classmethod
    def _grouped_learning_texts(cls, text: str) -> list[tuple[str, str]]:
        """v3 JSON feature를 그룹별 encoder 입력으로 바꾸고 레거시는 요청으로 취급한다."""

        try:
            payload = json.loads(str(text or ""))
        except (TypeError, json.JSONDecodeError):
            payload = None
        groups: list[tuple[str, str]] = []
        if isinstance(payload, Mapping):
            for group in cls._LEARNING_GROUP_WEIGHTS:
                value = payload.get(group)
                if isinstance(value, Mapping) and value:
                    groups.append(
                        (
                            group,
                            "query: " + json.dumps(
                                {"group": group, "value": value},
                                ensure_ascii=False,
                                sort_keys=True,
                                default=str,
                            ),
                        )
                    )
        if groups:
            return groups
        return [
            (
                "primary_request",
                "query: " + json.dumps(
                    {"group": "primary_request", "value": str(text or "").strip()},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            )
        ]

    @classmethod
    def _shared_embedder(cls, model_id: str | None = None) -> MultilingualE5Embedder:
        resolved_model_id = (
            model_id
            or os.getenv("MODEL_ROUTING_EMBEDDING_MODEL_ID")
            or DEFAULT_MULTILINGUAL_E5_MODEL_ID
        )
        with cls._embedder_cache_lock:
            embedder = cls._embedder_cache.get(resolved_model_id)
            if embedder is None:
                embedder = MultilingualE5Embedder(resolved_model_id)
                cls._embedder_cache[resolved_model_id] = embedder
            return embedder

    @staticmethod
    def _encode(
        embedder: TextEmbedder,
        texts: list[str],
    ) -> list[list[float]]:
        try:
            return embedder.encode(texts, mode="plain")
        except TypeError as exc:
            if "mode" not in str(exc):
                raise
            return embedder.encode(texts)

    @staticmethod
    def _l2_normalize(vector: list[float]) -> list[float]:
        values = [float(value) for value in vector]
        norm = math.sqrt(sum(value * value for value in values))
        if norm <= 0:
            raise ValueError("0 길이 embedding은 모델 선택에 사용할 수 없습니다.")
        return [value / norm for value in values]


class MultilingualE5TaskRequirementClassifier:
    """multilingual E5 vector에서 모델 ID가 아닌 요청 요구 능력을 학습한다."""

    @classmethod
    def update_from_vector(
        cls,
        artifact: dict[str, Any] | None,
        *,
        vector: Iterable[float],
        encoder_model_id: str | None,
        task_requirements: dict[str, Any],
    ) -> dict[str, Any]:
        from apps.workflow_engine.services.model_routing_incremental_learning import (
            IncrementalTaskRequirementClassifier,
        )

        updated = IncrementalTaskRequirementClassifier.update(
            artifact,
            vector=vector,
            task_requirements=task_requirements,
        )
        updated["encoder_model_id"] = str(encoder_model_id or "")
        updated["classification_strategy"] = (
            "frozen_multilingual_e5_online_task_requirements_v1"
        )
        return updated

    @classmethod
    def predict(
        cls,
        artifact: dict[str, Any],
        *,
        text: str,
        embedder: TextEmbedder | None = None,
    ) -> TaskRequirementPrediction:
        from apps.workflow_engine.services.model_routing_incremental_learning import (
            IncrementalTaskRequirementClassifier,
        )

        vector, _ = MultilingualE5ModelChoiceClassifier._vector(
            text,
            artifact=artifact,
            embedder=embedder,
        )
        result = IncrementalTaskRequirementClassifier.predict(artifact, vector=vector)
        return TaskRequirementPrediction(
            requirements=result.requirements,
            confidence=result.confidence,
        )

    @classmethod
    def predict_from_vector(
        cls,
        artifact: dict[str, Any] | None,
        *,
        vector: Iterable[float],
    ):
        """이미 만든 안전 vector로 Judge 호출 전 요구 수준을 예측한다."""
        from apps.workflow_engine.services.model_routing_incremental_learning import (
            IncrementalTaskRequirementClassifier,
        )

        return IncrementalTaskRequirementClassifier.predict(
            artifact,
            vector=vector,
        )
