from apps.workflow_engine.services.model_routing_mdeberta_classifier import (
    MDebertaComplexityRegressor,
)


class _Embedding:
    model_id = "microsoft/mdeberta-v3-base"

    def encode(self, texts, *, mode="plain"):
        _ = mode
        vectors = {
            "simple-a": [1.0, 0.0, 0.0],
            "simple-b": [0.96, 0.04, 0.0],
            "medium-a": [0.0, 1.0, 0.0],
            "medium-b": [0.04, 0.96, 0.0],
            "complex-a": [0.0, 0.0, 1.0],
            "complex-b": [0.02, 0.04, 0.94],
            "simple request": [0.92, 0.08, 0.0],
            "medium request": [0.05, 0.91, 0.04],
            "complex request": [0.02, 0.06, 0.92],
        }
        return [vectors[text] for text in texts]


def test_regressor_returns_continuous_request_complexity_without_tier_labels():
    artifact = MDebertaComplexityRegressor.fit(
        [
            ("simple-a", 12.0),
            ("simple-b", 20.0),
            ("medium-a", 48.0),
            ("medium-b", 61.0),
            ("complex-a", 84.0),
            ("complex-b", 94.0),
        ],
        embedder=_Embedding(),
    )

    simple = MDebertaComplexityRegressor.predict(
        artifact, "simple request", embedder=_Embedding()
    )
    medium = MDebertaComplexityRegressor.predict(
        artifact, "medium request", embedder=_Embedding()
    )
    complex_request = MDebertaComplexityRegressor.predict(
        artifact, "complex request", embedder=_Embedding()
    )

    assert artifact["kind"] == "mdeberta_complexity_regression_v2"
    assert "classifier_weights" not in artifact
    assert 0 <= simple.complexity_score <= 100
    assert simple.complexity_score < medium.complexity_score < complex_request.complexity_score
    assert complex_request.uncertainty >= 0
