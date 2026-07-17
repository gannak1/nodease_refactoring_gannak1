import pytest

from apps.workflow_engine.services import model_routing_mdeberta_classifier
from apps.workflow_engine.services.model_routing_mdeberta_classifier import (
    DEFAULT_MDEBERTA_MODEL_ID,
    MDebertaEmbedder,
    MDebertaDifficultyClassifier,
)


class _Embedding:
    model_id = "microsoft/mdeberta-v3-base"

    def encode(self, texts, *, mode="plain"):
        _ = mode
        vectors = {
            "economy-a": [1.0, 0.0, 0.0],
            "economy-b": [0.96, 0.04, 0.0],
            "balanced-a": [0.0, 1.0, 0.0],
            "balanced-b": [0.04, 0.96, 0.0],
            "advanced-a": [0.0, 0.0, 1.0],
            "advanced-b": [0.02, 0.04, 0.94],
            "economy input": [0.92, 0.08, 0.0],
            "balanced input": [0.05, 0.91, 0.04],
            "advanced input": [0.02, 0.06, 0.92],
        }
        return [vectors[text] for text in texts]


def test_classifier_trains_a_difficulty_head_and_returns_a_numeric_score():
    artifact = MDebertaDifficultyClassifier.fit(
        [
            ("economy-a", "economy"),
            ("economy-b", "economy"),
            ("balanced-a", "balanced"),
            ("balanced-b", "balanced"),
            ("advanced-a", "advanced"),
            ("advanced-b", "advanced"),
        ],
        embedder=_Embedding(),
    )

    economy = MDebertaDifficultyClassifier.predict(
        artifact,
        "economy input",
        embedder=_Embedding(),
    )
    balanced = MDebertaDifficultyClassifier.predict(
        artifact,
        "balanced input",
        embedder=_Embedding(),
    )
    advanced = MDebertaDifficultyClassifier.predict(
        artifact,
        "advanced input",
        embedder=_Embedding(),
    )

    assert artifact["kind"] == "mdeberta_linear_difficulty_v1"
    assert artifact["encoder_model_id"] == "microsoft/mdeberta-v3-base"
    assert set(artifact["classifier_weights"]) == {"economy", "balanced", "advanced"}
    assert "tier_prototypes" not in artifact
    assert "economy-a" not in str(artifact)
    assert economy.difficulty == "economy"
    assert balanced.difficulty == "balanced"
    assert advanced.difficulty == "advanced"
    assert economy.difficulty_score < balanced.difficulty_score < advanced.difficulty_score
    assert all(0 <= item.difficulty_score <= 100 for item in (economy, balanced, advanced))


def test_classifier_training_is_independent_of_bootstrap_sample_order():
    """Planner가 난이도별로 표본을 묶어도 마지막 class로 편향되면 안 된다."""
    examples = [
        ("economy-a", "economy"),
        ("economy-b", "economy"),
        ("balanced-a", "balanced"),
        ("balanced-b", "balanced"),
        ("advanced-a", "advanced"),
        ("advanced-b", "advanced"),
    ]

    grouped_artifact = MDebertaDifficultyClassifier.fit(
        examples,
        embedder=_Embedding(),
    )
    interleaved_artifact = MDebertaDifficultyClassifier.fit(
        [examples[index] for index in (0, 2, 4, 1, 3, 5)],
        embedder=_Embedding(),
    )

    for tier in ("economy", "balanced", "advanced"):
        assert grouped_artifact["classifier_weights"][tier] == pytest.approx(
            interleaved_artifact["classifier_weights"][tier]
        )
        assert grouped_artifact["classifier_bias"][tier] == pytest.approx(
            interleaved_artifact["classifier_bias"][tier]
        )


def test_classifier_keeps_existing_e5_prototype_artifacts_readable():
    """이미 생성된 정책은 재생성 전까지 기존 E5 artifact를 계속 읽을 수 있다."""
    artifact = {
        "kind": "multilingual_e5_prototype_v1",
        "encoder_model_id": "microsoft/mdeberta-v3-base",
        "tier_prototypes": {
            "economy": [[1.0, 0.0, 0.0]],
            "balanced": [[0.0, 1.0, 0.0]],
            "advanced": [[0.0, 0.0, 1.0]],
        },
    }

    decision = MDebertaDifficultyClassifier.predict(
        artifact,
        "economy input",
        embedder=_Embedding(),
    )

    assert decision.difficulty == "economy"
    assert decision.difficulty_score < 50


def test_classifier_keeps_legacy_prototype_top_two_scoring_for_existing_policies():
    """재생성 전 기존 E5 정책은 가까운 예문 둘을 계속 비교할 수 있어야 한다."""

    class _PrototypeEmbedding:
        model_id = "test-mdeberta"

        def encode(self, texts):
            vectors = {
                "economy-a": [1.0, 0.0, 0.0],
                "economy-b": [0.98, 0.02, 0.0],
                # economy와 무관한 예문 하나가 있어도 tier 평균 중심점으로 품질이
                # 희석되지 않아야 한다.
                "economy-outlier": [0.0, 0.0, 1.0],
                "balanced-a": [0.0, 1.0, 0.0],
                "balanced-b": [0.0, 0.98, 0.02],
                "advanced-a": [0.0, 0.0, 1.0],
                "advanced-b": [0.02, 0.0, 0.98],
                "economy-request": [0.99, 0.01, 0.0],
            }
            return [vectors[text] for text in texts]

    artifact = {
        "kind": "multilingual_e5_prototype_v1",
        "encoder_model_id": "test-mdeberta",
        "tier_prototypes": {
            "economy": [[1.0, 0.0, 0.0], [0.98, 0.02, 0.0], [0.0, 0.0, 1.0]],
            "balanced": [[0.0, 1.0, 0.0], [0.0, 0.98, 0.02]],
            "advanced": [[0.0, 0.0, 1.0], [0.02, 0.0, 0.98]],
        },
    }

    decision = MDebertaDifficultyClassifier.predict(
        artifact,
        "economy-request",
        embedder=_PrototypeEmbedding(),
    )

    assert decision.difficulty == "economy"
    assert decision.confidence >= 0.55


def test_new_classifier_defaults_to_the_mdeberta_encoder(monkeypatch):
    monkeypatch.delenv("MODEL_ROUTING_DIFFICULTY_MODEL_ID", raising=False)
    monkeypatch.delenv("MODEL_ROUTING_SEMANTIC_MODEL_ID", raising=False)
    monkeypatch.delenv("MODEL_ROUTING_MDEBERTA_MODEL_ID", raising=False)

    assert MDebertaEmbedder().model_id == DEFAULT_MDEBERTA_MODEL_ID


def test_classifier_reuses_the_same_process_embedder_for_the_same_model(monkeypatch):
    created = []

    class _CachedEmbedding:
        def __init__(self, model_id):
            self.model_id = model_id
            created.append(model_id)

    monkeypatch.setattr(
        model_routing_mdeberta_classifier,
        "MDebertaEmbedder",
        _CachedEmbedding,
    )
    MDebertaDifficultyClassifier._embedder_cache.clear()

    first = MDebertaDifficultyClassifier._shared_embedder("mdeberta-test")
    second = MDebertaDifficultyClassifier._shared_embedder("mdeberta-test")

    assert first is second
    assert created == ["mdeberta-test"]


def test_embedder_loads_model_once_when_first_requests_arrive_concurrently(monkeypatch):
    import sys
    import threading
    from types import SimpleNamespace

    calls = {"tokenizer": 0, "model": 0}

    class _Model:
        def eval(self):
            return None

    class _AutoTokenizer:
        @staticmethod
        def from_pretrained(_model_id, **_kwargs):
            calls["tokenizer"] += 1
            return object()

    class _AutoModel:
        @staticmethod
        def from_pretrained(_model_id):
            calls["model"] += 1
            return _Model()

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoModel=_AutoModel, AutoTokenizer=_AutoTokenizer),
    )
    embedder = MDebertaEmbedder("test-model")
    threads = [threading.Thread(target=embedder._load) for _ in range(4)]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert calls == {"tokenizer": 1, "model": 1}


def test_embedder_uses_slow_tokenizer_for_mdeberta_sentencepiece_models(monkeypatch):
    """mDeBERTa는 fast 변환 오류를 피하기 위해 SentencePiece slow tokenizer를 사용한다."""
    import sys
    from types import SimpleNamespace

    received_kwargs = {}

    class _Model:
        def eval(self):
            return None

    class _AutoTokenizer:
        @staticmethod
        def from_pretrained(_model_id, **kwargs):
            received_kwargs.update(kwargs)
            return object()

    class _AutoModel:
        @staticmethod
        def from_pretrained(_model_id):
            return _Model()

    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoModel=_AutoModel, AutoTokenizer=_AutoTokenizer),
    )

    MDebertaEmbedder("microsoft/mdeberta-v3-base")._load()

    assert received_kwargs == {"use_fast": False}


def test_embedder_disables_xet_before_huggingface_model_load(monkeypatch):
    """첫 bootstrap이 Xet 전송 환경에 묶여 멈추지 않도록 직접 다운로드를 기본으로 쓴다."""
    import os
    import sys
    from types import SimpleNamespace

    class _Model:
        def eval(self):
            return None

    class _AutoTokenizer:
        @staticmethod
        def from_pretrained(_model_id, **_kwargs):
            return object()

    class _AutoModel:
        @staticmethod
        def from_pretrained(_model_id):
            return _Model()

    monkeypatch.delenv("HF_HUB_DISABLE_XET", raising=False)
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace())
    monkeypatch.setitem(
        sys.modules,
        "transformers",
        SimpleNamespace(AutoModel=_AutoModel, AutoTokenizer=_AutoTokenizer),
    )

    MDebertaEmbedder("microsoft/mdeberta-v3-base")._load()

    assert os.environ["HF_HUB_DISABLE_XET"] == "1"
