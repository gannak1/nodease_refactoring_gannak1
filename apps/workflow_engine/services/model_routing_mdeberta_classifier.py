"""mDeBERTa 기반 자동 모델 라우팅 난이도 분류기.

새 정책은 mDeBERTa encoder가 만든 문장 표현 위에 경제형·균형형·고성능형을
직접 구분하는 작은 softmax 분류 헤드를 학습한다. 즉 가장 가까운 예문을 찾는
의미 검색이 아니라, 학습 표본의 난이도 label 경계를 이용해 확률과 난이도 점수를
계산한다.

분류 헤드만 node별로 저장하고 encoder 가중치는 공유한다. 초기 bootstrap 표본은
적기 때문에 workflow마다 transformer 전체를 재학습하지 않아도 되며, artifact에는
원문이나 prompt가 아닌 학습된 숫자 가중치만 남는다.

기존 E5 prototype artifact는 이미 배포된 policy를 읽기 위한 호환 경로로만 유지한다.
"""

from __future__ import annotations

import math
import os
import threading
from dataclasses import dataclass
from typing import Any, Iterable, Protocol


DEFAULT_MDEBERTA_MODEL_ID = "microsoft/mdeberta-v3-base"
DEFAULT_SEMANTIC_MODEL_ID = "intfloat/multilingual-e5-small"
DIFFICULTY_TIERS = ("economy", "balanced", "advanced")
DIFFICULTY_SCORE_POINTS = {"economy": 0.0, "balanced": 50.0, "advanced": 100.0}


class TextEmbedder(Protocol):
    model_id: str

    def encode(
        self,
        texts: list[str],
        *,
        mode: str = "plain",
    ) -> list[list[float]]: ...


@dataclass(frozen=True)
class DifficultyPrediction:
    difficulty: str
    confidence: float
    probabilities: dict[str, float]
    difficulty_score: float


class MDebertaEmbedder:
    """Hugging Face mDeBERTa encoder를 lazy-load하는 runtime encoder.

    import와 model download는 bootstrap/runtime worker가 실제로 classifier를
    사용할 때만 발생한다. 테스트는 ``TextEmbedder`` fake를 주입해 network 없이
    이 경계를 검증한다.

    ``MODEL_ROUTING_SEMANTIC_MODEL_ID``는 기존 E5 policy 호환용으로만 artifact가
    명시한 경우에 사용한다. 새 policy의 기본 encoder는 mDeBERTa다.
    """

    def __init__(self, model_id: str | None = None):
        self.model_id = (
            model_id
            or os.getenv("MODEL_ROUTING_DIFFICULTY_MODEL_ID")
            or os.getenv("MODEL_ROUTING_MDEBERTA_MODEL_ID")
            or DEFAULT_MDEBERTA_MODEL_ID
        )
        self._tokenizer: Any | None = None
        self._model: Any | None = None
        self._torch: Any | None = None
        self._load_lock = threading.Lock()

    @classmethod
    def legacy_semantic(cls) -> "MDebertaEmbedder":
        """기존 E5 artifact를 읽을 때만 사용하는 encoder 생성 경로다."""

        return cls(os.getenv("MODEL_ROUTING_SEMANTIC_MODEL_ID") or DEFAULT_SEMANTIC_MODEL_ID)

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._load_lock:
            if self._model is not None:
                return
            try:
                # 대용량 checkpoint를 Xet 전송 경로로 받으면 일부 컨테이너 환경에서
                # 완료되지 않은 cache 파일만 남긴 채 bootstrap이 멈출 수 있다.
                # Hugging Face의 일반 HTTP 다운로드를 기본값으로 고정한다.
                os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
                import torch
                from transformers import AutoModel, AutoTokenizer
            except ImportError as exc:  # pragma: no cover - deployment dependency guard
                raise RuntimeError(
                    "mDeBERTa 분류기 의존성이 설치되지 않았습니다. "
                    "workflow_engine image를 최신 의존성으로 다시 빌드하세요."
                ) from exc

            self._torch = torch
            # mDeBERTa/E5 계열은 container image에 따라 fast tokenizer 변환 경로가
            # 불안정할 수 있어 slow tokenizer를 명시한다.
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

        normalized_mode = str(mode or "plain").strip().casefold()
        if normalized_mode not in {"plain", "query", "passage"}:
            raise ValueError(f"지원하지 않는 embedding mode입니다: {mode}")
        prepared_texts = [str(text or "").strip() for text in texts]
        if (
            normalized_mode in {"query", "passage"}
            and self.model_id.casefold().startswith("intfloat/multilingual-e5")
        ):
            prepared_texts = [
                f"{normalized_mode}: {text}" for text in prepared_texts
            ]
        encoded = self._tokenizer(
            prepared_texts,
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


class MDebertaDifficultyClassifier:
    """mDeBERTa 표현 위에서 난이도 class를 직접 학습하는 분류기.

    Node별 bootstrap 표본 수는 수십 건 수준이므로 encoder 전체를 매번 fine-tune하면
    비용과 과적합 위험이 크다. 공유 mDeBERTa encoder는 고정하고, 각 node의 안전한
    표본으로만 작은 softmax head를 학습한다. 이 head가 난이도 label의 경계를
    학습하므로 새 요청은 가장 가까운 예문이 아니라 세 class 확률로 판정된다.
    """

    ARTIFACT_KIND = "mdeberta_linear_difficulty_v1"
    LEGACY_E5_PROTOTYPE_ARTIFACT_KIND = "multilingual_e5_prototype_v1"
    LEGACY_PROTOTYPE_ARTIFACT_KIND = "mdeberta_prototype_v2"
    LEGACY_ARTIFACT_KIND = "mdeberta_centroid_v1"
    MAX_PROTOTYPES_PER_TIER = 12
    TOP_PROTOTYPES_PER_TIER = 2
    SOFTMAX_SCALE = 16.0
    HEAD_TRAINING_EPOCHS = 240
    HEAD_LEARNING_RATE = 0.18
    HEAD_L2_REGULARIZATION = 0.001
    _embedder_cache: dict[str, MDebertaEmbedder] = {}
    _embedder_cache_lock = threading.Lock()

    @classmethod
    def _shared_embedder(cls, model_id: str | None = None) -> MDebertaEmbedder:
        """동일 worker에서 encoder 가중치를 한 번만 올려 재사용한다."""
        resolved_model_id = (
            model_id
            or os.getenv("MODEL_ROUTING_DIFFICULTY_MODEL_ID")
            or os.getenv("MODEL_ROUTING_MDEBERTA_MODEL_ID")
            or DEFAULT_MDEBERTA_MODEL_ID
        )
        with cls._embedder_cache_lock:
            embedder = cls._embedder_cache.get(resolved_model_id)
            if embedder is None:
                embedder = MDebertaEmbedder(resolved_model_id)
                cls._embedder_cache[resolved_model_id] = embedder
            return embedder

    @classmethod
    def fit(
        cls,
        examples: Iterable[tuple[str, str]],
        *,
        embedder: TextEmbedder | None = None,
    ) -> dict[str, Any]:
        normalized = [
            (str(text).strip(), str(tier).strip())
            for text, tier in examples
            if str(text).strip() and str(tier).strip() in DIFFICULTY_TIERS
        ]
        if not normalized:
            raise ValueError("난이도 분류기를 만들 표본이 없습니다.")

        runtime_embedder = embedder or cls._shared_embedder()
        vectors = cls._encode(
            runtime_embedder,
            [text for text, _ in normalized],
            mode="plain",
        )
        if len(vectors) != len(normalized):
            raise ValueError("분류기 embedding 결과 수가 표본 수와 다릅니다.")

        training_rows = [
            (cls._l2_normalize([float(value) for value in vector]), tier)
            for vector, (_, tier) in zip(vectors, normalized, strict=True)
            if vector
        ]
        if len(training_rows) != len(normalized):
            raise ValueError("유효한 난이도 embedding을 만들지 못했습니다.")
        width = len(training_rows[0][0])
        if not width or any(len(vector) != width for vector, _ in training_rows):
            raise ValueError("난이도 분류기 embedding 차원이 일치하지 않습니다.")
        tier_counts = {
            tier: sum(1 for _, row_tier in training_rows if row_tier == tier)
            for tier in DIFFICULTY_TIERS
        }
        if sum(1 for count in tier_counts.values() if count > 0) < 2:
            raise ValueError("난이도 분류기는 두 개 이상의 난이도 표본이 필요합니다.")

        weights, bias = cls._train_linear_head(training_rows, width=width)

        # 원문, raw payload, prompt는 artifact에 저장하지 않는다. node별로 학습된
        # classification head만 JSON artifact에 남긴다.
        return {
            "kind": cls.ARTIFACT_KIND,
            "encoder_model_id": runtime_embedder.model_id,
            "classification_strategy": "frozen_mdeberta_linear_softmax_v1",
            "classifier_weights": weights,
            "classifier_bias": bias,
            "tier_sample_counts": {
                tier: count for tier, count in tier_counts.items() if count
            },
            "training": {
                "epochs": cls.HEAD_TRAINING_EPOCHS,
                "learning_rate": cls.HEAD_LEARNING_RATE,
                "l2_regularization": cls.HEAD_L2_REGULARIZATION,
            },
        }

    @classmethod
    def predict(
        cls,
        artifact: dict[str, Any],
        text: str,
        *,
        embedder: TextEmbedder | None = None,
    ) -> DifficultyPrediction:
        if not isinstance(artifact, dict):
            raise ValueError("지원하지 않는 모델 라우팅 분류기 artifact입니다.")
        kind = str(artifact.get("kind") or "")
        if kind not in {
            cls.ARTIFACT_KIND,
            cls.LEGACY_E5_PROTOTYPE_ARTIFACT_KIND,
            cls.LEGACY_PROTOTYPE_ARTIFACT_KIND,
            cls.LEGACY_ARTIFACT_KIND,
        }:
            raise ValueError("지원하지 않는 모델 라우팅 분류기 artifact입니다.")

        is_legacy_e5 = kind == cls.LEGACY_E5_PROTOTYPE_ARTIFACT_KIND
        encoder_model_id = str(artifact.get("encoder_model_id") or "")
        if not encoder_model_id:
            encoder_model_id = (
                DEFAULT_SEMANTIC_MODEL_ID
                if is_legacy_e5
                else DEFAULT_MDEBERTA_MODEL_ID
            )
        runtime_embedder = embedder or cls._shared_embedder(encoder_model_id)
        vectors = cls._encode(
            runtime_embedder,
            [str(text or "").strip()],
            mode="query" if is_legacy_e5 else "plain",
        )
        if not vectors or not vectors[0]:
            raise ValueError("분류할 입력 embedding을 만들지 못했습니다.")

        if kind == cls.ARTIFACT_KIND:
            scores = cls._linear_head_scores(artifact, vectors[0])
            probability_scale = 1.0
        elif kind in {
            cls.LEGACY_E5_PROTOTYPE_ARTIFACT_KIND,
            cls.LEGACY_PROTOTYPE_ARTIFACT_KIND,
        }:
            scores = cls._prototype_scores(artifact, vectors[0])
            probability_scale = cls.SOFTMAX_SCALE
        else:
            scores = cls._legacy_centroid_scores(artifact, vectors[0])
            probability_scale = cls.SOFTMAX_SCALE
        if not scores:
            raise ValueError("유효한 난이도 분류기 가중치가 없습니다.")
        probabilities = cls._softmax(scores, scale=probability_scale)
        difficulty, confidence = max(
            probabilities.items(), key=lambda item: item[1]
        )
        return DifficultyPrediction(
            difficulty=difficulty,
            confidence=confidence,
            probabilities=probabilities,
            difficulty_score=cls._difficulty_score(probabilities),
        )

    @classmethod
    def _train_linear_head(
        cls,
        rows: list[tuple[list[float], str]],
        *,
        width: int,
    ) -> tuple[dict[str, list[float]], dict[str, float]]:
        """작은 표본에서도 재현 가능하게 동작하는 regularized softmax head 학습."""

        weights = {tier: [0.0] * width for tier in DIFFICULTY_TIERS}
        bias = {tier: 0.0 for tier in DIFFICULTY_TIERS}
        sample_count = len(rows)
        for _epoch in range(cls.HEAD_TRAINING_EPOCHS):
            # Planner가 난이도별로 표본을 묶어 반환한다. 한 건씩 즉시 갱신하면
            # epoch의 마지막 난이도 label이 더 크게 남으므로, 모든 표본의 gradient를
            # 합산한 뒤 한 번에 적용해 입력 순서와 무관한 분류기를 만든다.
            gradient_weights = {
                tier: [0.0] * width for tier in DIFFICULTY_TIERS
            }
            gradient_bias = {tier: 0.0 for tier in DIFFICULTY_TIERS}
            for vector, expected_tier in rows:
                scores = {
                    tier: cls._dot(weights[tier], vector) + bias[tier]
                    for tier in DIFFICULTY_TIERS
                }
                probabilities = cls._softmax(scores)
                for tier in DIFFICULTY_TIERS:
                    error = probabilities[tier] - float(tier == expected_tier)
                    gradient_weights[tier] = [
                        gradient + error * feature
                        for gradient, feature in zip(
                            gradient_weights[tier],
                            vector,
                            strict=True,
                        )
                    ]
                    gradient_bias[tier] += error

            for tier in DIFFICULTY_TIERS:
                weights[tier] = [
                    value
                    - cls.HEAD_LEARNING_RATE
                    * (
                        (gradient / sample_count)
                        + cls.HEAD_L2_REGULARIZATION * value
                    )
                    for value, gradient in zip(
                        weights[tier],
                        gradient_weights[tier],
                        strict=True,
                    )
                ]
                bias[tier] -= (
                    cls.HEAD_LEARNING_RATE
                    * gradient_bias[tier]
                    / sample_count
                )
        return weights, bias

    @classmethod
    def _linear_head_scores(
        cls,
        artifact: dict[str, Any],
        query_vector: list[float],
    ) -> dict[str, float]:
        weights = artifact.get("classifier_weights")
        bias = artifact.get("classifier_bias")
        if not isinstance(weights, dict) or not isinstance(bias, dict):
            return {}
        normalized_query = cls._l2_normalize(query_vector)
        scores: dict[str, float] = {}
        for tier in DIFFICULTY_TIERS:
            values = weights.get(tier)
            if not isinstance(values, list) or len(values) != len(normalized_query):
                continue
            try:
                tier_bias = float(bias.get(tier, 0.0))
                scores[tier] = cls._dot(
                    [float(value) for value in values], normalized_query
                ) + tier_bias
            except (TypeError, ValueError):
                continue
        return scores

    @staticmethod
    def _dot(left: list[float], right: list[float]) -> float:
        if len(left) != len(right):
            raise ValueError("난이도 분류기 embedding 차원이 일치하지 않습니다.")
        return sum(a * b for a, b in zip(left, right, strict=True))

    @staticmethod
    def _l2_normalize(vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(float(value) * float(value) for value in vector))
        if norm <= 0:
            raise ValueError("0 길이 embedding은 난이도 분류에 사용할 수 없습니다.")
        return [float(value) / norm for value in vector]

    @staticmethod
    def _difficulty_score(probabilities: dict[str, float]) -> float:
        """세 난이도 확률의 기대값을 0~100 점수로 표시한다."""

        return round(
            sum(
                DIFFICULTY_SCORE_POINTS[tier] * float(probabilities.get(tier, 0.0))
                for tier in DIFFICULTY_TIERS
            ),
            2,
        )

    @staticmethod
    def _encode(
        embedder: TextEmbedder,
        texts: list[str],
        *,
        mode: str,
    ) -> list[list[float]]:
        """구 test fake와 외부 embedder의 plain encode 호환성을 유지한다."""

        try:
            return embedder.encode(texts, mode=mode)
        except TypeError as exc:
            if "mode" not in str(exc):
                raise
            return embedder.encode(texts)

    @staticmethod
    def _mean_vector(vectors: list[list[float]]) -> list[float]:
        width = len(vectors[0])
        if any(len(vector) != width for vector in vectors):
            raise ValueError("embedding 차원이 일치하지 않습니다.")
        return [
            sum(vector[index] for vector in vectors) / len(vectors)
            for index in range(width)
        ]

    @classmethod
    def _prototype_scores(
        cls,
        artifact: dict[str, Any],
        query_vector: list[float],
    ) -> dict[str, float]:
        prototypes_by_tier = artifact.get("tier_prototypes")
        if not isinstance(prototypes_by_tier, dict):
            return {}
        scores: dict[str, float] = {}
        for tier, prototypes in prototypes_by_tier.items():
            if tier not in DIFFICULTY_TIERS or not isinstance(prototypes, list):
                continue
            similarities = sorted(
                (
                    cls._cosine_similarity(query_vector, prototype)
                    for prototype in prototypes
                    if isinstance(prototype, list)
                ),
                reverse=True,
            )
            if not similarities:
                continue
            top = similarities[: cls.TOP_PROTOTYPES_PER_TIER]
            scores[tier] = sum(top) / len(top)
        return scores

    @classmethod
    def _legacy_centroid_scores(
        cls,
        artifact: dict[str, Any],
        query_vector: list[float],
    ) -> dict[str, float]:
        """이미 저장된 v1 policy는 새 bootstrap을 만들기 전까지 읽을 수 있다."""
        centroids = artifact.get("tier_centroids")
        if not isinstance(centroids, dict):
            return {}
        return {
            tier: cls._cosine_similarity(query_vector, centroid)
            for tier, centroid in centroids.items()
            if tier in DIFFICULTY_TIERS and isinstance(centroid, list)
        }

    @staticmethod
    def _cosine_similarity(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return -1.0
        numerator = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return -1.0
        return numerator / (left_norm * right_norm)

    @staticmethod
    def _softmax(scores: dict[str, float], *, scale: float = 1.0) -> dict[str, float]:
        maximum = max(scores.values())
        # Sentence embedding의 cosine 차이는 작게 형성되므로 prototype 간의 의미 있는
        # 차이를 confidence에 반영할 수 있도록 적당한 온도를 적용한다.
        exponentials = {
            tier: math.exp((score - maximum) * scale)
            for tier, score in scores.items()
        }
        denominator = sum(exponentials.values()) or 1.0
        return {tier: value / denominator for tier, value in exponentials.items()}
