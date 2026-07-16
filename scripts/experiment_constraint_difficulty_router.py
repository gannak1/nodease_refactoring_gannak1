"""Run the constraint_difficulty_v1 fixed-fixture comparison experiment.

This script never calls a real LLM provider. It validates routing mechanics,
result-matrix reuse, and report generation with deterministic fixtures first.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from apps.workflow_engine.services.model_routing_constraint_difficulty import (  # noqa: E402
    ConstraintDifficultyFeatureExtractor,
    ConstraintDifficultyRequest,
    ConstraintModelCandidate,
    ConstraintValidationEvidence,
)
from apps.workflow_engine.services.model_routing_constraint_experiment import (  # noqa: E402
    ConstraintRoutingExperimentCase,
    ConstraintRoutingExperimentReport,
    ConstraintRoutingExperimentRunner,
    ExperimentModelResult,
    ReusableExperimentResultMatrix,
    SemanticCohortExperimentStrategy,
)
from apps.workflow_engine.services.model_routing_semantic_router import (  # noqa: E402
    SemanticRouteCatalog,
    SemanticRouteDefinition,
)


HIGH_MODEL = "gpt-4.1"
BALANCED_MODEL = "gpt-4.1-mini"
LOW_MODEL = "gpt-4o-mini"
WORKFLOW_TYPES = (
    "simple_json_strict_downstream",
    "rag_answer",
    "long_input_freeform",
)


def candidates() -> list[ConstraintModelCandidate]:
    return [
        ConstraintModelCandidate(
            model_id=LOW_MODEL,
            context_window=128_000,
            input_price_1k=0.00015,
            output_price_1k=0.0006,
            capability_tier="low",
        ),
        ConstraintModelCandidate(
            model_id=BALANCED_MODEL,
            context_window=128_000,
            input_price_1k=0.0004,
            output_price_1k=0.0016,
            capability_tier="balanced",
            supports_strict_structured_output=True,
        ),
        ConstraintModelCandidate(
            model_id=HIGH_MODEL,
            context_window=1_000_000,
            input_price_1k=0.002,
            output_price_1k=0.008,
            capability_tier="high",
            supports_strict_structured_output=True,
        ),
    ]


def build_cases() -> list[ConstraintRoutingExperimentCase]:
    cases: list[ConstraintRoutingExperimentCase] = []
    for workflow_type in WORKFLOW_TYPES:
        for index in range(1, 21):
            common = {
                "system_prompt": "Follow the configured output contract.",
                "user_prompt": "{{ request }}",
                "assistant_prompt": "",
                "referenced_variables": [
                    {"name": "request", "value_selector": ["start", "request"]}
                ],
                "parameters": {"max_tokens": 500},
                "knowledgeBases": [],
            }
            downstream = ()
            estimated_input_tokens = None
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
                query = f"fixture-{index}: classify the compact structured payload"
                downstream = (
                    {"field": "category", "type": "string", "required": True},
                    {"field": "priority", "type": "number", "required": True},
                )
            elif workflow_type == "rag_answer":
                common["output_format"] = {"type": "text"}
                common["knowledgeBases"] = [{"id": "kb-policy", "name": "Policy"}]
                common["retrievedContextMaxChars"] = 30_000
                query = f"fixture-{index}: answer using the retrieved policy evidence"
            else:
                common["output_format"] = {"type": "text"}
                query = f"fixture-{index}: synthesize this long freeform input. " * 500
                estimated_input_tokens = 18_000 + index
            request = ConstraintDifficultyRequest(
                node_data=common,
                inputs={"start": {"request": query}},
                available_model_ids={item.model_id for item in candidates()},
                downstream_requirements=downstream,
                estimated_input_tokens=estimated_input_tokens,
            )
            cases.append(
                ConstraintRoutingExperimentCase(
                    case_id=f"{workflow_type}-{index:02d}",
                    workflow_type=workflow_type,
                    request=request,
                )
            )
    return cases


def build_evidence(
    cases: list[ConstraintRoutingExperimentCase],
) -> list[ConstraintValidationEvidence]:
    evidence: list[ConstraintValidationEvidence] = []
    seen = set()
    for case in cases:
        request = case.request
        if request.node_data.get("knowledgeBases") or request.node_data.get(
            "knowledgeCollections"
        ):
            request = replace(
                request,
                actual_rag_context_tokens=fixture_rag_context_tokens(case),
            )
        signature = ConstraintDifficultyFeatureExtractor.extract(request).signature
        if signature in seen:
            continue
        seen.add(signature)
        model_id = (
            BALANCED_MODEL
            if case.workflow_type == "simple_json_strict_downstream"
            else HIGH_MODEL
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


def fake_result(
    case: ConstraintRoutingExperimentCase,
    model_id: str,
    rag_context_tokens: int,
) -> ExperimentModelResult:
    index = int(case.case_id.rsplit("-", 1)[-1])
    input_tokens = {
        "simple_json_strict_downstream": 900,
        "rag_answer": 1_300 + rag_context_tokens,
        "long_input_freeform": 18_000 + index,
    }[case.workflow_type]
    output_tokens = {
        "simple_json_strict_downstream": 180,
        "rag_answer": 500,
        "long_input_freeform": 750,
    }[case.workflow_type]
    model = next(item for item in candidates() if item.model_id == model_id)
    cost = input_tokens / 1_000 * float(
        model.input_price_1k or 0
    ) + output_tokens / 1_000 * float(model.output_price_1k or 0)
    schema_passed = None
    downstream_passed = None
    success = True
    if case.workflow_type == "simple_json_strict_downstream":
        schema_passed = not (model_id == LOW_MODEL and index % 5 == 0)
        downstream_passed = schema_passed
        success = schema_passed
    quality = {
        LOW_MODEL: 0.73,
        BALANCED_MODEL: 0.88,
        HIGH_MODEL: 0.96,
    }[model_id]
    if case.workflow_type == "rag_answer" and model_id == LOW_MODEL:
        quality = 0.64
    latency = {
        LOW_MODEL: 350,
        BALANCED_MODEL: 700,
        HIGH_MODEL: 1_400,
    }[model_id] + index
    return ExperimentModelResult(
        success=success,
        schema_passed=schema_passed,
        downstream_passed=downstream_passed,
        fallback_used=False,
        cost_usd=cost,
        total_tokens=input_tokens + output_tokens,
        latency_ms=latency,
        quality_score=quality,
    )


def fixture_rag_context_tokens(case: ConstraintRoutingExperimentCase) -> int:
    return 9_000 + int(case.case_id.rsplit("-", 1)[-1])


def semantic_strategy() -> SemanticCohortExperimentStrategy:
    catalog = SemanticRouteCatalog(
        version="fixture-semantic-v1",
        encoder_model_id="fixture-encoder",
        routes=(
            SemanticRouteDefinition(
                cohort_id="structured",
                label="Structured output",
                threshold=0.7,
                representative_vectors=((1.0, 0.0, 0.0),),
            ),
            SemanticRouteDefinition(
                cohort_id="rag",
                label="RAG answer",
                threshold=0.7,
                representative_vectors=((0.0, 1.0, 0.0),),
            ),
            SemanticRouteDefinition(
                cohort_id="freeform",
                label="Long freeform",
                threshold=0.7,
                representative_vectors=((0.0, 0.0, 1.0),),
            ),
        ),
        aggregation="max",
        min_margin=0.05,
    )

    def fixture_query_vector(case: ConstraintRoutingExperimentCase):
        return {
            "simple_json_strict_downstream": (1.0, 0.0, 0.0),
            "rag_answer": (0.0, 1.0, 0.0),
            "long_input_freeform": (0.0, 0.0, 1.0),
        }[case.workflow_type]

    return SemanticCohortExperimentStrategy(
        catalog=catalog,
        query_vector_provider=fixture_query_vector,
        model_by_cohort={
            "structured": LOW_MODEL,
            "rag": BALANCED_MODEL,
            "freeform": BALANCED_MODEL,
        },
        default_model_id=HIGH_MODEL,
    )


def run_experiment() -> ConstraintRoutingExperimentReport:
    cases = build_cases()
    matrix = ReusableExperimentResultMatrix(result_provider=fake_result)
    return ConstraintRoutingExperimentRunner(
        candidates=candidates(),
        evidence=build_evidence(cases),
        result_matrix=matrix,
        retrieval_provider=fixture_rag_context_tokens,
        high_model_id=HIGH_MODEL,
        low_model_id=LOW_MODEL,
        safe_default_model_id=HIGH_MODEL,
        semantic_strategy=semantic_strategy(),
    ).run(cases)


def _percent(value: float | None) -> str:
    return "-" if value is None else f"{value * 100:.1f}%"


def _score(value: float | None) -> str:
    return "-" if value is None else f"{value:.3f}"


def render_markdown(report: ConstraintRoutingExperimentReport) -> str:
    lines = [
        "# Constraint-Difficulty Router Fixed-Fixture Experiment",
        "",
        "실제 Provider를 호출하지 않고 고정 fixture로 라우팅 알고리즘과 결과 재사용 계약을 검증했다.",
        "기존 `semantic_cohort_v1` 운영 정책은 변경하지 않았다.",
        "",
        "## 실험 설계",
        "",
        "- 비교 전략: 고가 고정, 저가 고정, 실제 SemanticRouteMatcher+fixture embedding, 신규 제약·난이도 기반",
        "- 워크플로우: 단순 JSON+엄격 downstream, RAG 답변, 긴 입력+자유형 출력",
        "- 입력 수: 워크플로우별 20개, 총 60개",
        "- RAG retrieval: RAG 입력마다 1회 수행 후 모든 전략이 같은 결과 사용",
        "- 모델 실행 결과: `(입력, 모델)` result matrix로 전략 간 재사용",
        "- Judge: 런타임에는 호출하지 않으며 fixture 품질 점수만 사용",
        "",
        "## 결과",
        "",
        "| 전략 | 모델 | 성공률 | Schema | Downstream | Fallback | 비용 | 평균 지연 | p95 지연 | 품질 |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    labels = {
        "fixed_high": "고가 모델 고정",
        "fixed_low": "저가 모델 고정",
        "semantic_cohort_v1": "현재 semantic matcher (fixture embedding)",
        "constraint_difficulty_v1": "신규 제약·난이도 기반",
    }
    for key, summary in report.strategy_summaries.items():
        lines.append(
            f"| {labels[key]} | {', '.join(summary.selected_models)} | "
            f"{_percent(summary.success_rate)} | {_percent(summary.schema_pass_rate)} | "
            f"{_percent(summary.downstream_success_rate)} | {_percent(summary.fallback_rate)} | "
            f"${summary.total_cost_usd:.6f} | {summary.avg_latency_ms:.1f}ms | "
            f"{summary.p95_latency_ms}ms | "
            f"{_score(summary.avg_quality_score)} |"
        )
    lines.extend(
        [
            "",
            "## 채택 기준 자동 판정",
            "",
            "| 기준 | 결과 | 근거 |",
            "| --- | --- | --- |",
        ]
    )
    for key, criterion in report.adoption_assessment.criteria.items():
        status = (
            "통과"
            if criterion.passed is True
            else "실패"
            if criterion.passed is False
            else "실제 검증 필요"
        )
        lines.append(f"| `{key}` | {status} | {criterion.detail} |")
    lines.extend(
        [
            "",
            "- 운영 교체 후보: "
            + ("예" if report.adoption_assessment.replacement_candidate else "아니오"),
        ]
    )
    lines.extend(
        [
            "",
            "## 재사용 검증",
            "",
            f"- 전략별 독립 실행이라면 최대 240회지만 실제 result matrix row는 **{report.provider_result_count}개**다.",
            f"- 현재 token fixture와 catalog 가격으로 계산한 provider 결과 생성 예상 비용은 **${report.provider_result_estimated_cost_usd:.6f}**다.",
            f"- RAG retrieval 결과는 **{report.retrieval_result_count}개**이며 RAG 입력 20개와 일치한다.",
            "",
            "## 채택 기준에 대한 현재 결론",
            "",
            "이 결과는 알고리즘·재사용 구조의 결정적 fixture 검증일 뿐 실제 품질 증거가 아니다. "
            "실제 Provider blind 평가, 치명적 단일 실패, 1,000회 손익분기 검증 전에는 운영 교체 후보로 판단할 수 없다.",
            "",
            "## 실제 Provider 실험 예상",
            "",
            "- result matrix를 그대로 사용하면 동일 모델 중복 호출을 제거할 수 있다.",
            "- 현재 fixture 기준 unique `(입력, 모델)` 수는 위 provider result count와 같다.",
            "- 실험 전 실제 모델 가격과 입력 token preflight로 다시 계산해야 하며, 유료 실행은 별도 승인 후 수행한다.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT
        / "reports"
        / "model-routing"
        / "constraint-difficulty-v1-fixed-fixture",
    )
    args = parser.parse_args()
    report = run_experiment()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    json_path = args.output_dir / "result.json"
    markdown_path = args.output_dir / "report.md"
    json_path.write_text(
        json.dumps(report.as_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    print(f"result={json_path}")
    print(f"report={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
