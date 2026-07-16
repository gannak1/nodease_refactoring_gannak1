from __future__ import annotations

from collections import Counter
from dataclasses import replace

from apps.workflow_engine.services.model_routing_constraint_difficulty import (
    ConstraintDifficultyFeatureExtractor,
    ConstraintDifficultyRequest,
    ConstraintModelCandidate,
    ConstraintValidationEvidence,
)
from apps.workflow_engine.services.model_routing_constraint_experiment import (
    ConstraintRoutingExperimentCase,
    ConstraintRoutingExperimentRunner,
    ExperimentModelResult,
    ExperimentRow,
    ExperimentStrategySelection,
    ReusableExperimentResultMatrix,
    SemanticCohortExperimentStrategy,
)
from apps.workflow_engine.services.model_routing_semantic_router import (
    SemanticRouteCatalog,
    SemanticRouteDefinition,
)


def _candidates() -> list[ConstraintModelCandidate]:
    return [
        ConstraintModelCandidate(
            model_id="low-model",
            context_window=32_000,
            input_price_1k=0.0001,
            output_price_1k=0.0004,
            capability_tier="low",
        ),
        ConstraintModelCandidate(
            model_id="balanced-model",
            context_window=128_000,
            input_price_1k=0.0004,
            output_price_1k=0.0016,
            capability_tier="balanced",
            supports_strict_structured_output=True,
        ),
        ConstraintModelCandidate(
            model_id="high-model",
            context_window=256_000,
            input_price_1k=0.002,
            output_price_1k=0.008,
            capability_tier="high",
            supports_strict_structured_output=True,
        ),
    ]


def _request(workflow_type: str, index: int) -> ConstraintDifficultyRequest:
    common = {
        "system_prompt": "Follow the output contract.",
        "user_prompt": "{{ request }}",
        "assistant_prompt": "",
        "referenced_variables": [
            {"name": "request", "value_selector": ["start", "request"]}
        ],
        "parameters": {"max_tokens": 400},
        "knowledgeBases": [],
    }
    if workflow_type == "simple_json_strict_downstream":
        common["output_format"] = {
            "type": "json",
            "schema": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "priority": {"type": "number"},
                },
                "required": ["category", "priority"],
            },
        }
        return ConstraintDifficultyRequest(
            node_data=common,
            inputs={"start": {"request": f"classify payload {index}"}},
            available_model_ids={item.model_id for item in _candidates()},
            downstream_requirements=(
                {"field": "category", "type": "string", "required": True},
                {"field": "priority", "type": "number", "required": True},
            ),
        )
    if workflow_type == "rag_answer":
        common["output_format"] = {"type": "text"}
        common["knowledgeBases"] = [{"id": "kb-1", "name": "Policy"}]
        common["retrievedContextMaxChars"] = 30_000
        return ConstraintDifficultyRequest(
            node_data=common,
            inputs={"start": {"request": f"answer from policy evidence {index}"}},
            available_model_ids={item.model_id for item in _candidates()},
        )
    common["output_format"] = {"type": "text"}
    return ConstraintDifficultyRequest(
        node_data=common,
        inputs={"start": {"request": ("long freeform request " * 900) + str(index)}},
        available_model_ids={item.model_id for item in _candidates()},
        estimated_input_tokens=18_000 + index,
    )


def _evidence(cases: list[ConstraintRoutingExperimentCase]):
    evidence: list[ConstraintValidationEvidence] = []
    seen = set()
    for case in cases:
        signature = ConstraintDifficultyFeatureExtractor.extract(case.request).signature
        if signature in seen:
            continue
        seen.add(signature)
        model_id = (
            "balanced-model"
            if case.workflow_type == "simple_json_strict_downstream"
            else "high-model"
        )
        evidence.append(
            ConstraintValidationEvidence(
                model_id=model_id,
                signature=signature,
                sample_count=20,
                success_rate=1.0,
                schema_pass_rate=1.0,
                downstream_success_rate=1.0,
                fallback_rate=0.0,
                quality_score=0.95,
            )
        )
    return evidence


def _fake_result(case, model_id, rag_context_tokens):
    base_cost = {
        "low-model": 0.001,
        "balanced-model": 0.004,
        "high-model": 0.02,
    }[model_id]
    latency = {"low-model": 350, "balanced-model": 700, "high-model": 1_400}[model_id]
    schema_passed = not (
        case.workflow_type == "simple_json_strict_downstream"
        and model_id == "low-model"
        and int(case.case_id.rsplit("-", 1)[-1]) % 5 == 0
    )
    downstream_passed = schema_passed
    quality_score = {
        "low-model": 0.72,
        "balanced-model": 0.88,
        "high-model": 0.96,
    }[model_id]
    if case.workflow_type == "rag_answer" and model_id == "low-model":
        quality_score = 0.65
    return ExperimentModelResult(
        success=schema_passed,
        schema_passed=schema_passed,
        downstream_passed=downstream_passed,
        fallback_used=False,
        cost_usd=base_cost + (rag_context_tokens / 10_000_000),
        total_tokens=700 + rag_context_tokens,
        latency_ms=latency,
        quality_score=quality_score,
    )


def _semantic_strategy() -> SemanticCohortExperimentStrategy:
    catalog = SemanticRouteCatalog(
        version="fixture-semantic-v1",
        encoder_model_id="fixture-encoder",
        routes=(
            SemanticRouteDefinition(
                cohort_id="structured",
                label="Structured",
                threshold=0.7,
                representative_vectors=((1.0, 0.0, 0.0),),
            ),
            SemanticRouteDefinition(
                cohort_id="rag",
                label="RAG",
                threshold=0.7,
                representative_vectors=((0.0, 1.0, 0.0),),
            ),
            SemanticRouteDefinition(
                cohort_id="freeform",
                label="Freeform",
                threshold=0.7,
                representative_vectors=((0.0, 0.0, 1.0),),
            ),
        ),
        aggregation="max",
        min_margin=0.05,
    )

    def query_vector(case: ConstraintRoutingExperimentCase):
        return {
            "simple_json_strict_downstream": (1.0, 0.0, 0.0),
            "rag_answer": (0.0, 1.0, 0.0),
            "long_input_freeform": (0.0, 0.0, 1.0),
        }[case.workflow_type]

    return SemanticCohortExperimentStrategy(
        catalog=catalog,
        query_vector_provider=query_vector,
        model_by_cohort={
            "structured": "low-model",
            "rag": "balanced-model",
            "freeform": "balanced-model",
        },
        default_model_id="high-model",
    )


def test_four_strategies_reuse_model_results_and_rag_retrieval():
    cases = [
        ConstraintRoutingExperimentCase(
            case_id=f"{workflow_type}-{index}",
            workflow_type=workflow_type,
            request=_request(workflow_type, index),
        )
        for workflow_type in (
            "simple_json_strict_downstream",
            "rag_answer",
            "long_input_freeform",
        )
        for index in range(20)
    ]
    provider_calls = Counter()
    retrieval_calls = Counter()

    def result_provider(case, model_id, rag_context_tokens):
        provider_calls[(case.case_id, model_id)] += 1
        return _fake_result(case, model_id, rag_context_tokens)

    def retrieval_provider(case):
        retrieval_calls[case.case_id] += 1
        return 9_000 + int(case.case_id.rsplit("-", 1)[-1])

    matrix = ReusableExperimentResultMatrix(result_provider=result_provider)
    report = ConstraintRoutingExperimentRunner(
        candidates=_candidates(),
        evidence=_evidence(cases),
        result_matrix=matrix,
        retrieval_provider=retrieval_provider,
        high_model_id="high-model",
        low_model_id="low-model",
        safe_default_model_id="high-model",
        semantic_strategy=_semantic_strategy(),
    ).run(cases)

    assert len(cases) == 60
    assert set(report.strategy_summaries) == {
        "fixed_high",
        "fixed_low",
        "semantic_cohort_v1",
        "constraint_difficulty_v1",
    }
    assert all(count == 1 for count in provider_calls.values())
    assert sum(provider_calls.values()) < len(cases) * 4
    assert report.provider_result_estimated_cost_usd > 0
    assert len(retrieval_calls) == 20
    assert all(count == 1 for count in retrieval_calls.values())
    assert set(
        report.strategy_summaries["constraint_difficulty_v1"].selected_models
    ) >= {
        "balanced-model",
        "high-model",
    }
    assessment = report.adoption_assessment
    assert assessment.criteria["selects_at_least_two_models"].passed is True
    assert assessment.criteria["blind_quality_non_inferior"].passed is None
    assert assessment.criteria["break_even_before_1000_runs"].passed is not None
    assert assessment.replacement_candidate is False


def test_report_exposes_required_metrics_and_selection_reasons():
    cases = [
        ConstraintRoutingExperimentCase(
            case_id=f"simple-json-{index}",
            workflow_type="simple_json_strict_downstream",
            request=_request("simple_json_strict_downstream", index),
        )
        for index in range(20)
    ]
    matrix = ReusableExperimentResultMatrix(result_provider=_fake_result)
    report = ConstraintRoutingExperimentRunner(
        candidates=_candidates(),
        evidence=_evidence(cases),
        result_matrix=matrix,
        retrieval_provider=lambda _case: 0,
        high_model_id="high-model",
        low_model_id="low-model",
        safe_default_model_id="high-model",
        semantic_strategy=_semantic_strategy(),
    ).run(cases)

    summary = report.strategy_summaries["constraint_difficulty_v1"]
    assert summary.run_count == 20
    assert summary.success_rate == 1.0
    assert summary.schema_pass_rate == 1.0
    assert summary.downstream_success_rate == 1.0
    assert summary.fallback_rate == 0.0
    assert summary.total_cost_usd > 0
    assert summary.total_tokens > 0
    assert summary.avg_latency_ms > 0
    assert summary.p95_latency_ms > 0
    assert summary.avg_quality_score > 0
    assert all(row.reason_code for row in report.rows)
    assert (
        "schema_downstream_not_degraded"
        in report.as_dict()["adoption_assessment"]["criteria"]
    )


def test_semantic_fixture_uses_the_real_semantic_matcher_contract():
    case = ConstraintRoutingExperimentCase(
        case_id="semantic-1",
        workflow_type="rag_answer",
        request=_request("rag_answer", 1),
    )

    selection = _semantic_strategy().select(case)

    assert selection == ExperimentStrategySelection(
        model_id="balanced-model",
        reason_code="semantic_cohort_matched:rag",
    )


def test_schema_and_downstream_failures_are_not_dropped_from_metric_denominators():
    rows = (
        ExperimentRow(
            case_id="ok",
            workflow_type="json",
            strategy_id="constraint_difficulty_v1",
            selected_model_id="high-model",
            reason_code="validated",
            schema_required=True,
            downstream_required=True,
            result=ExperimentModelResult(
                success=True,
                schema_passed=True,
                downstream_passed=True,
                fallback_used=False,
                cost_usd=0.01,
                total_tokens=100,
                latency_ms=100,
                quality_score=0.9,
            ),
        ),
        ExperimentRow(
            case_id="failed-before-validation",
            workflow_type="json",
            strategy_id="constraint_difficulty_v1",
            selected_model_id="low-model",
            reason_code="validated",
            schema_required=True,
            downstream_required=True,
            result=ExperimentModelResult(
                success=False,
                schema_passed=None,
                downstream_passed=None,
                fallback_used=False,
                cost_usd=0.001,
                total_tokens=10,
                latency_ms=50,
                quality_score=None,
            ),
        ),
    )

    summary = ConstraintRoutingExperimentRunner._summarize(rows)

    assert summary.success_rate == 0.5
    assert summary.schema_pass_rate == 0.5
    assert summary.downstream_success_rate == 0.5
    assert summary.quality_evaluation_rate == 0.5


def test_result_matrix_does_not_reuse_a_result_after_the_input_changes():
    calls = Counter()

    def provider(case, model_id, rag_context_tokens):
        calls[(case.case_id, model_id)] += 1
        return _fake_result(case, model_id, rag_context_tokens)

    matrix = ReusableExperimentResultMatrix(result_provider=provider)
    first = ConstraintRoutingExperimentCase(
        case_id="same-id",
        workflow_type="simple_json_strict_downstream",
        request=_request("simple_json_strict_downstream", 1),
    )
    changed = ConstraintRoutingExperimentCase(
        case_id="same-id",
        workflow_type="simple_json_strict_downstream",
        request=ConstraintDifficultyRequest(
            **{
                **_request("simple_json_strict_downstream", 1).__dict__,
                "inputs": {"start": {"request": "a different payload"}},
            }
        ),
    )

    matrix.get_or_run(case=first, model_id="high-model", rag_context_tokens=0)
    matrix.get_or_run(case=changed, model_id="high-model", rag_context_tokens=0)

    assert calls[("same-id", "high-model")] == 2


def test_one_critically_low_quality_result_blocks_adoption():
    cases = [
        ConstraintRoutingExperimentCase(
            case_id=f"simple-json-{index}",
            workflow_type="simple_json_strict_downstream",
            request=_request("simple_json_strict_downstream", index),
        )
        for index in range(20)
    ]

    def result_with_one_critical_quality_failure(case, model_id, rag_context_tokens):
        result = _fake_result(case, model_id, rag_context_tokens)
        if model_id == "balanced-model" and case.case_id == "simple-json-0":
            return replace(
                result,
                quality_score=0.1,
                critical_quality_failure=True,
            )
        return result

    report = ConstraintRoutingExperimentRunner(
        candidates=_candidates(),
        evidence=_evidence(cases),
        result_matrix=ReusableExperimentResultMatrix(
            result_provider=result_with_one_critical_quality_failure
        ),
        retrieval_provider=lambda _case: 0,
        high_model_id="high-model",
        low_model_id="low-model",
        safe_default_model_id="high-model",
        semantic_strategy=_semantic_strategy(),
    ).run(cases)

    criterion = report.adoption_assessment.criteria["no_critical_single_failure"]

    assert criterion.passed is False
    assert "critical_rows=1" in criterion.detail
