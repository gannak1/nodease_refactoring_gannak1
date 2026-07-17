from apps.workflow_engine.services.model_routing_constraint_difficulty import (
    ConstraintModelCandidate,
    ConstraintModelPrior,
    PRIOR_GUIDED_STRATEGY_ID,
)
from apps.workflow_engine.services.model_routing_prior_guided_policy import (
    PriorGuidedPolicyCompiler,
)
from apps.workflow_engine.services.model_router import ModelPerformance, NodeRunProfile


def _candidate(
    model_id: str,
    *,
    tier: str,
    input_price: float,
    output_price: float,
) -> ConstraintModelCandidate:
    return ConstraintModelCandidate(
        model_id=model_id,
        context_window=128_000,
        input_price_1k=input_price,
        output_price_1k=output_price,
        capability_tier=tier,
        supports_strict_structured_output=True,
    )


def _prior(
    model_id: str,
    *,
    quality: float,
    uncertainty: float,
    latency_ms: int,
) -> ConstraintModelPrior:
    return ConstraintModelPrior(
        model_id=model_id,
        quality_mean=quality,
        quality_uncertainty=uncertainty,
        expected_latency_ms=latency_ms,
        source="test_catalog",
    )


def test_prior_guided_compiler_builds_non_semantic_constraint_rules():
    result = PriorGuidedPolicyCompiler.compile(
        node_data={
            "model_id": "gpt-4.1",
            "system_prompt": "Return a concise answer.",
            "user_prompt": "{{message}}",
            "parameters": {"max_tokens": 512},
            "output_format": {"type": "text"},
        },
        candidates=(
            _candidate(
                "gpt-4.1",
                tier="high",
                input_price=0.002,
                output_price=0.008,
            ),
            _candidate(
                "gpt-4.1-mini",
                tier="balanced",
                input_price=0.0004,
                output_price=0.0016,
            ),
            _candidate(
                "gpt-4o-mini",
                tier="low",
                input_price=0.00015,
                output_price=0.0006,
            ),
        ),
        priors=(
            _prior("gpt-4.1", quality=0.97, uncertainty=0.02, latency_ms=1_400),
            _prior(
                "gpt-4.1-mini",
                quality=0.91,
                uncertainty=0.03,
                latency_ms=750,
            ),
            _prior(
                "gpt-4o-mini",
                quality=0.84,
                uncertainty=0.04,
                latency_ms=450,
            ),
        ),
        evidence=(),
        available_model_ids={"gpt-4.1", "gpt-4.1-mini", "gpt-4o-mini"},
        safe_default_model_id="gpt-4.1",
    )

    policy = result.active_policy
    assert policy["strategy_id"] == PRIOR_GUIDED_STRATEGY_ID
    assert policy["decision_profiles"]
    assert {rule["when"]["input_length_bucket"] for rule in policy["rules"]} <= {
        "short",
        "medium",
        "long",
    }


def test_prior_guided_compiler_keeps_configured_model_as_fallback():
    result = PriorGuidedPolicyCompiler.compile(
        node_data={
            "model_id": "gpt-4.1",
            "parameters": {"max_tokens": 256},
            "output_format": {"type": "text"},
        },
        candidates=(
            _candidate(
                "gpt-4.1",
                tier="high",
                input_price=0.002,
                output_price=0.008,
            ),
            _candidate(
                "gpt-4.1-mini",
                tier="balanced",
                input_price=0.0004,
                output_price=0.0016,
            ),
        ),
        priors=(
            _prior("gpt-4.1", quality=0.97, uncertainty=0.02, latency_ms=1_400),
            _prior(
                "gpt-4.1-mini",
                quality=0.91,
                uncertainty=0.03,
                latency_ms=750,
            ),
        ),
        evidence=(),
        available_model_ids={"gpt-4.1", "gpt-4.1-mini"},
        safe_default_model_id="gpt-4.1",
    )

    assert result.active_policy["fallback_model_id"] == "gpt-4.1"
    assert result.active_policy["default_model_id"] in {
        "gpt-4.1",
        "gpt-4.1-mini",
    }


def test_prior_guided_compiler_keeps_other_profiles_when_long_input_has_no_candidate():
    short_context_candidate = ConstraintModelCandidate(
        model_id="gpt-4.1-mini",
        context_window=4_096,
        input_price_1k=0.0004,
        output_price_1k=0.0016,
        capability_tier="balanced",
        supports_strict_structured_output=True,
    )

    result = PriorGuidedPolicyCompiler.compile(
        node_data={
            "model_id": "gpt-4.1-mini",
            "parameters": {"max_tokens": 256},
            "output_format": {"type": "text"},
        },
        candidates=(short_context_candidate,),
        priors=(
            _prior(
                "gpt-4.1-mini",
                quality=0.91,
                uncertainty=0.03,
                latency_ms=750,
            ),
        ),
        evidence=(),
        available_model_ids={"gpt-4.1-mini"},
        safe_default_model_id="gpt-4.1-mini",
    )

    long_profile = next(
        profile
        for profile in result.active_policy["decision_profiles"]
        if profile["profile"] == "long"
    )
    assert long_profile["selected_model_id"] == "gpt-4.1-mini"
    assert long_profile["reason_code"] == "prior_guided_constraints_safe_default"
    assert len(result.active_policy["rules"]) == 3


def test_prior_guided_compiler_uses_only_matching_input_profile_evidence():
    """짧은 입력의 성공 표본을 중간 입력 정책의 증거로 재사용하지 않는다."""
    short_performance = ModelPerformance(
        model_id="gpt-4.1-mini",
        run_count=10,
        success_count=10,
        schema_pass_count=10,
        schema_eval_count=10,
        downstream_success_count=10,
        downstream_eval_count=10,
        total_cost=0.01,
        total_latency_ms=1_000,
    )
    profile = NodeRunProfile(
        operational_usable_runs=10,
        model_performance={"gpt-4.1-mini": short_performance},
        segment_performance={
            "short": {
                "conditions": {"input_length_bucket": "short"},
                "model_performance": {"gpt-4.1-mini": short_performance},
            }
        },
    )

    result = PriorGuidedPolicyCompiler.compile(
        node_data={
            "model_id": "gpt-4.1",
            "parameters": {"max_tokens": 256},
            "output_format": {"type": "text"},
        },
        candidates=(
            _candidate(
                "gpt-4.1",
                tier="high",
                input_price=0.002,
                output_price=0.008,
            ),
            _candidate(
                "gpt-4.1-mini",
                tier="balanced",
                input_price=0.0004,
                output_price=0.0016,
            ),
        ),
        priors=(
            _prior("gpt-4.1", quality=0.97, uncertainty=0.02, latency_ms=1_400),
            _prior(
                "gpt-4.1-mini",
                quality=0.91,
                uncertainty=0.03,
                latency_ms=750,
            ),
        ),
        evidence=(),
        available_model_ids={"gpt-4.1", "gpt-4.1-mini"},
        safe_default_model_id="gpt-4.1",
        profile=profile,
    )

    by_profile = {
        item["profile"]: item for item in result.active_policy["decision_profiles"]
    }
    assert (
        by_profile["short"]["candidate_scores"]["gpt-4.1-mini"][
            "effective_evidence_samples"
        ]
        == 10.0
    )
    assert (
        by_profile["short"]["candidate_scores"]["gpt-4.1-mini"]["expected_latency_ms"]
        == 100
    )
    assert (
        by_profile["medium"]["candidate_scores"]["gpt-4.1-mini"][
            "effective_evidence_samples"
        ]
        == 0.0
    )
    assert (
        by_profile["medium"]["candidate_scores"]["gpt-4.1-mini"]["expected_latency_ms"]
        == 750
    )


def test_prior_guided_compiler_applies_json_schema_and_rag_constraints_to_every_profile():
    """출력 계약과 RAG 제약은 배포 정책의 모든 입력 길이 profile에 반영된다."""
    complex_schema = {
        "type": "object",
        "properties": {
            "answer": {"type": "string"},
            "sources": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "string"}},
                },
            },
        },
        "required": ["answer", "sources"],
    }
    result = PriorGuidedPolicyCompiler.compile(
        node_data={
            "model_id": "high-model",
            "parameters": {"max_tokens": 512},
            "output_format": {
                "type": "json",
                "strict": True,
                "schema": complex_schema,
            },
            "knowledgeBases": [{"id": "kb-1"}],
            "retrievedContextMaxChars": 40_000,
        },
        candidates=(
            _candidate(
                "low-model",
                tier="low",
                input_price=0.0001,
                output_price=0.0004,
            ),
            _candidate(
                "high-model",
                tier="high",
                input_price=0.002,
                output_price=0.008,
            ),
        ),
        priors=(
            _prior("low-model", quality=0.84, uncertainty=0.04, latency_ms=400),
            _prior("high-model", quality=0.97, uncertainty=0.02, latency_ms=1_400),
        ),
        evidence=(),
        available_model_ids={"low-model", "high-model"},
        safe_default_model_id="high-model",
    )

    for profile in result.active_policy["decision_profiles"]:
        signature = profile["constraint_signature"]
        assert signature["output_contract"] == "strict_json_schema"
        assert signature["schema_complexity"] == "complex"
        assert signature["rag_context_bucket"] == "large"
        assert signature["required_capability_tier"] == "high"
        assert profile["selected_model_id"] == "high-model"
