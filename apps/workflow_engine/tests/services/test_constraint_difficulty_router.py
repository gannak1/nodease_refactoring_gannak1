from __future__ import annotations

import pytest

from apps.workflow_engine.services.model_routing_constraint_difficulty import (
    ConstraintDifficultyCandidateFilter,
    ConstraintDifficultyFeatureExtractor,
    ConstraintDifficultyRequest,
    ConstraintDifficultyRouter,
    ConstraintModelCandidate,
    ConstraintRoutingUnavailableError,
    ConstraintRoutingStrategyDispatcher,
    ConstraintValidationEvidence,
)


def _candidate(
    model_id: str,
    *,
    tier: str,
    context_window: int = 128_000,
    input_price: float,
    output_price: float,
    structured_output: bool = True,
) -> ConstraintModelCandidate:
    return ConstraintModelCandidate(
        model_id=model_id,
        context_window=context_window,
        input_price_1k=input_price,
        output_price_1k=output_price,
        capability_tier=tier,
        supports_strict_structured_output=structured_output,
    )


LOW = _candidate(
    "low-model",
    tier="low",
    context_window=16_000,
    input_price=0.0001,
    output_price=0.0004,
    structured_output=False,
)
BALANCED = _candidate(
    "balanced-model",
    tier="balanced",
    input_price=0.0004,
    output_price=0.0016,
)
HIGH = _candidate(
    "high-model",
    tier="high",
    input_price=0.002,
    output_price=0.008,
)


def _request(**overrides) -> ConstraintDifficultyRequest:
    values = {
        "node_data": {
            "system_prompt": "Return a compact result.",
            "user_prompt": "{{ request }}",
            "assistant_prompt": "",
            "referenced_variables": [
                {"name": "request", "value_selector": ["start", "request"]}
            ],
            "parameters": {"max_tokens": 300},
            "output_format": {"type": "json"},
            "knowledgeBases": [],
            # 기존 의미 기반 필드는 신규 전략의 입력이 아니어야 한다.
            "model_routing_context": {
                "intent": "legal",
                "task_type": "security",
                "customer_facing": True,
            },
        },
        "inputs": {"start": {"request": "summarize this payload"}},
        "available_model_ids": {"low-model", "balanced-model", "high-model"},
        "downstream_requirements": (),
    }
    values.update(overrides)
    return ConstraintDifficultyRequest(**values)


def _passing_evidence(model_id: str, signature) -> ConstraintValidationEvidence:
    return ConstraintValidationEvidence(
        model_id=model_id,
        signature=signature,
        sample_count=10,
        success_rate=1.0,
        schema_pass_rate=1.0,
        downstream_success_rate=1.0,
        fallback_rate=0.0,
        quality_score=0.95,
    )


def test_feature_extractor_uses_constraints_not_semantic_fields():
    features = ConstraintDifficultyFeatureExtractor.extract(_request())

    assert features.signature.output_contract == "json"
    assert features.signature.rag_context_bucket == "none"
    assert features.signature.schema_complexity == "none"
    assert features.signature.downstream_strictness == "none"
    assert "intent" not in features.signature.as_metadata()
    assert "task_type" not in features.signature.as_metadata()
    assert "semantic_cohort_id" not in features.signature.as_metadata()


def test_candidate_filter_excludes_models_without_execution_subject_access():
    request = _request(available_model_ids={"balanced-model", "high-model"})
    features = ConstraintDifficultyFeatureExtractor.extract(request)

    result = ConstraintDifficultyCandidateFilter.filter(
        candidates=[LOW, BALANCED, HIGH],
        request=request,
        features=features,
    )

    assert [candidate.model_id for candidate in result.eligible] == [
        "balanced-model",
        "high-model",
    ]
    assert result.excluded_by_model["low-model"] == ("model_not_available",)


def test_candidate_filter_excludes_models_over_context_window():
    request = _request(estimated_input_tokens=20_000)
    features = ConstraintDifficultyFeatureExtractor.extract(request)

    result = ConstraintDifficultyCandidateFilter.filter(
        candidates=[LOW, HIGH],
        request=request,
        features=features,
    )

    assert [candidate.model_id for candidate in result.eligible] == ["high-model"]
    assert "context_window_insufficient" in result.excluded_by_model["low-model"]


def test_strict_structured_output_is_a_hard_gate_but_plain_json_is_not():
    strict_node = {
        **_request().node_data,
        "output_format": {
            "type": "json",
            "strict": True,
            "schema": {
                "type": "object",
                "properties": {"answer": {"type": "string"}},
                "required": ["answer"],
            },
        },
    }
    strict_request = _request(node_data=strict_node)
    strict_features = ConstraintDifficultyFeatureExtractor.extract(strict_request)

    strict_result = ConstraintDifficultyCandidateFilter.filter(
        candidates=[LOW, HIGH],
        request=strict_request,
        features=strict_features,
    )
    plain_request = _request()
    plain_result = ConstraintDifficultyCandidateFilter.filter(
        candidates=[LOW, HIGH],
        request=plain_request,
        features=ConstraintDifficultyFeatureExtractor.extract(plain_request),
    )

    assert [candidate.model_id for candidate in strict_result.eligible] == [
        "high-model"
    ]
    assert strict_result.excluded_by_model["low-model"] == (
        "strict_structured_output_unsupported",
    )
    assert [candidate.model_id for candidate in plain_result.eligible] == [
        "low-model",
        "high-model",
    ]


def test_string_false_does_not_enable_strict_structured_output():
    request = _request(
        node_data={
            **_request().node_data,
            "output_format": {
                "type": "json",
                "strict": "false",
                "schema": {
                    "type": "object",
                    "properties": {"answer": {"type": "string"}},
                },
            },
        }
    )

    features = ConstraintDifficultyFeatureExtractor.extract(request)
    result = ConstraintDifficultyCandidateFilter.filter(
        candidates=[LOW, HIGH],
        request=request,
        features=features,
    )

    assert features.signature.output_contract == "json"
    assert [candidate.model_id for candidate in result.eligible] == [
        "low-model",
        "high-model",
    ]


def test_simple_json_exposes_low_cost_models_as_validation_candidates():
    router = ConstraintDifficultyRouter()
    request = _request()

    decision = router.route(
        request=request,
        candidates=[LOW, BALANCED, HIGH],
        evidence=[],
        safe_default_model_id="high-model",
    )

    assert decision.selected_model_id == "high-model"
    assert decision.reason_code == "validated_evidence_insufficient_safe_default"
    assert decision.validation_candidate_ids == ("low-model", "balanced-model")


def test_model_without_price_is_not_selected_as_an_economic_candidate():
    unpriced = ConstraintModelCandidate(
        model_id="unpriced-model",
        context_window=128_000,
        input_price_1k=None,
        output_price_1k=None,
        capability_tier="low",
    )
    request = _request(available_model_ids={"unpriced-model", "high-model"})
    signature = ConstraintDifficultyFeatureExtractor.extract(request).signature

    decision = ConstraintDifficultyRouter().route(
        request=request,
        candidates=[unpriced, HIGH],
        evidence=[_passing_evidence("unpriced-model", signature)],
        safe_default_model_id="high-model",
    )

    assert decision.selected_model_id == "high-model"
    assert decision.reason_code == "validated_evidence_insufficient_safe_default"


def test_long_rag_complex_schema_and_strict_downstream_require_high_tier():
    complex_schema = {
        "type": "object",
        "properties": {
            "decision": {"type": "string"},
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "score": {"type": "number"},
                    },
                    "required": ["id", "score"],
                },
            },
        },
        "required": ["decision", "items"],
    }
    request = _request(
        node_data={
            **_request().node_data,
            "output_format": {"type": "json", "schema": complex_schema},
            "knowledgeBases": [{"id": "kb-1", "name": "Policy"}],
            "retrievedContextMaxChars": 40_000,
        },
        actual_rag_context_tokens=12_000,
        downstream_requirements=(
            {"field": "decision", "type": "string", "required": True},
            {"field": "items", "type": "array", "required": True},
        ),
    )
    signature = ConstraintDifficultyFeatureExtractor.extract(request).signature

    decision = ConstraintDifficultyRouter().route(
        request=request,
        candidates=[LOW, BALANCED, HIGH],
        evidence=[
            _passing_evidence("low-model", signature),
            _passing_evidence("balanced-model", signature),
            _passing_evidence("high-model", signature),
        ],
        safe_default_model_id="high-model",
    )

    assert decision.matched_signature.required_capability_tier == "high"
    assert decision.selected_model_id == "high-model"
    assert decision.reason_code == "validated_high_constraint_model_selected"


def test_high_constraint_never_uses_a_low_tier_safe_default_without_evidence():
    request = _request(
        node_data={
            **_request().node_data,
            "knowledgeBases": [{"id": "kb-1", "name": "Policy"}],
            "retrievedContextMaxChars": 40_000,
        },
        actual_rag_context_tokens=12_000,
    )

    decision = ConstraintDifficultyRouter().route(
        request=request,
        candidates=[LOW, HIGH],
        evidence=[],
        safe_default_model_id="low-model",
    )

    assert decision.matched_signature.required_capability_tier == "high"
    assert decision.selected_model_id == "high-model"
    assert decision.fallback_model_id is None
    assert decision.reason_code == "validated_evidence_insufficient_safe_default"


def test_fallback_model_also_satisfies_the_required_capability_tier():
    request = _request(
        node_data={
            **_request().node_data,
            "knowledgeBases": [{"id": "kb-1", "name": "Policy"}],
            "retrievedContextMaxChars": 40_000,
        },
        actual_rag_context_tokens=12_000,
        available_model_ids={"low-model", "high-model", "alternate-high"},
    )
    signature = ConstraintDifficultyFeatureExtractor.extract(request).signature
    alternate_high = _candidate(
        "alternate-high",
        tier="high",
        input_price=0.0015,
        output_price=0.006,
    )

    decision = ConstraintDifficultyRouter().route(
        request=request,
        candidates=[LOW, alternate_high, HIGH],
        evidence=[_passing_evidence("alternate-high", signature)],
        safe_default_model_id="low-model",
    )

    assert decision.selected_model_id == "alternate-high"
    assert decision.fallback_model_id == "high-model"


def test_missing_required_input_closes_routing_instead_of_calling_a_model():
    request = _request(inputs={"start": {}})

    with pytest.raises(ConstraintRoutingUnavailableError):
        ConstraintDifficultyRouter().route(
            request=request,
            candidates=[LOW, BALANCED, HIGH],
            evidence=[],
            safe_default_model_id="high-model",
        )


def test_file_input_is_kept_as_an_independent_constraint_dimension():
    request = _request(inputs={"start": {"request": "summarize", "file_id": "f-1"}})

    decision = ConstraintDifficultyRouter().route(
        request=request,
        candidates=[LOW, BALANCED, HIGH],
        evidence=[],
        safe_default_model_id="low-model",
    )

    assert decision.matched_signature.file_input is True
    assert decision.matched_signature.required_capability_tier == "balanced"
    assert decision.selected_model_id == "high-model"
    assert "balanced-model" in decision.validation_candidate_ids


def test_empty_file_fields_do_not_raise_the_capability_tier():
    features = ConstraintDifficultyFeatureExtractor.extract(
        _request(
            inputs={
                "start": {
                    "request": "summarize",
                    "file_id": None,
                    "attachments": [],
                }
            }
        )
    )

    assert features.signature.file_input is False
    assert features.signature.required_capability_tier == "low"


def test_string_false_does_not_make_downstream_contract_strict():
    features = ConstraintDifficultyFeatureExtractor.extract(
        _request(
            downstream_requirements=(
                {"field": "answer", "type": "string", "required": "false"},
            )
        )
    )

    assert features.signature.downstream_strictness == "lenient"


def test_unbounded_rag_uses_conservative_top_k_and_kb_count_estimate():
    features = ConstraintDifficultyFeatureExtractor.extract(
        _request(
            node_data={
                **_request().node_data,
                "knowledgeBases": [
                    {"id": "kb-1", "name": "Policy"},
                    {"id": "kb-2", "name": "Runbook"},
                ],
                "topK": 3,
                "retrievedContextMaxChars": None,
            }
        )
    )

    assert features.estimated_rag_context_tokens == 24_000
    assert features.signature.rag_context_bucket == "large"
    assert features.signature.required_capability_tier == "high"


def test_freeform_output_without_quality_evidence_keeps_safe_default():
    request = _request(
        node_data={
            **_request().node_data,
            "output_format": {"type": "text"},
        }
    )

    decision = ConstraintDifficultyRouter().route(
        request=request,
        candidates=[LOW, BALANCED, HIGH],
        evidence=[],
        safe_default_model_id="high-model",
    )

    assert decision.selected_model_id == "high-model"
    assert decision.reason_code == "freeform_quality_evidence_insufficient"


def test_evidence_from_easier_signature_is_not_reused_for_harder_request():
    easy_request = _request()
    easy_signature = ConstraintDifficultyFeatureExtractor.extract(
        easy_request
    ).signature
    hard_request = _request(
        node_data={
            **_request().node_data,
            "knowledgeBases": [{"id": "kb-1", "name": "Policy"}],
            "retrievedContextMaxChars": 40_000,
        },
        actual_rag_context_tokens=12_000,
    )

    decision = ConstraintDifficultyRouter().route(
        request=hard_request,
        candidates=[LOW, HIGH],
        evidence=[_passing_evidence("low-model", easy_signature)],
        safe_default_model_id="high-model",
    )

    assert decision.selected_model_id == "high-model"
    assert decision.reason_code == "validated_evidence_insufficient_safe_default"


def test_decision_trace_contains_strategy_signature_exclusions_and_no_judge():
    request = _request(
        available_model_ids={"balanced-model", "high-model"},
        estimated_input_tokens=20_000,
    )

    decision = ConstraintDifficultyRouter().route(
        request=request,
        candidates=[LOW, BALANCED, HIGH],
        evidence=[],
        safe_default_model_id="high-model",
    )
    trace = decision.as_trace_metadata()

    assert trace["strategy_id"] == "constraint_difficulty_v1"
    assert trace["selected_model_id"] == "high-model"
    assert trace["fallback_model_id"] is None
    assert trace["matched_constraint_signature"]["output_contract"] == "json"
    assert set(trace["excluded_models"]["low-model"]) == {
        "model_not_available",
        "context_window_insufficient",
    }
    assert trace["judge_called"] is False


def test_strategy_dispatch_keeps_semantic_and_constraint_strategies_separate():
    semantic_calls = []

    def semantic_strategy(**kwargs):
        semantic_calls.append(kwargs)
        return "semantic-result"

    dispatcher = ConstraintRoutingStrategyDispatcher(
        semantic_strategy=semantic_strategy,
        constraint_strategy=ConstraintDifficultyRouter(),
    )

    assert dispatcher.dispatch("semantic_cohort_v1", marker="existing") == (
        "semantic-result"
    )
    assert semantic_calls == [{"marker": "existing"}]

    request = _request()
    signature = ConstraintDifficultyFeatureExtractor.extract(request).signature
    decision = dispatcher.dispatch(
        "constraint_difficulty_v1",
        request=request,
        candidates=[LOW, HIGH],
        evidence=[_passing_evidence("low-model", signature)],
        safe_default_model_id="high-model",
    )

    assert decision.strategy_id == "constraint_difficulty_v1"
    assert decision.selected_model_id == "low-model"
