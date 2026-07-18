"""가격군별 모델 대표를 선발하는 실제 workflow 예선 실험.

현재 실행 주체가 사용할 수 있는 일반 chat model을 가격으로 저가·중가·고가로
나눈다. Pro 모델은 초고가 관찰군으로 분리하고 기본 예선에서는 호출하지 않는다.
각 후보는 최종 80건과 겹치지 않는 16개 요청을 같은 workflow로 처리하며, 별도
품질 Judge가 모델명·가격·순서를 숨긴 출력 묶음을 평가한다.

기본 모드는 provider를 호출하지 않는 dry-run이다. 실제 호출은 ``--execute``가
필요하며 결과는 case마다 저장해 ``--resume``으로 이어갈 수 있다.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import random
import statistics
import sys
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from typing import Any, Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
PARENT_OF_ROOT = ROOT.parent
for path in (ROOT, PARENT_OF_ROOT):
    if str(path) not in sys.path:
        sys.path.append(str(path))

# 이 스크립트는 repo root를 sys.path에 추가한 뒤 애플리케이션 모듈을 import한다.
# ruff: noqa: E402

from apps.shared.db.session import SessionLocal
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_router import ModelCandidate, ModelRouter
from scripts import experiment_judge_first_economics_80 as base


LOW_TIER = "low"
MID_TIER = "mid"
HIGH_TIER = "high"
PRO_TIER = "pro_observation"
EXECUTED_TIERS = (LOW_TIER, MID_TIER, HIGH_TIER)
ALL_TIERS = (*EXECUTED_TIERS, PRO_TIER)

INPUT_TO_OUTPUT_RATIO = 4
LOW_MAX_REFERENCE_COST_USD = 0.0032
MID_MAX_REFERENCE_COST_USD = 0.025
QUALITY_MARGIN_POINTS = 3.0
MIN_WORKFLOW_SUCCESS_RATE = 0.90
MIN_SCHEMA_PASS_RATE = 0.90
MIN_QUALITY_PASS_RATE = 0.80
QUALITY_JUDGE_BATCH_SIZE = 5
QUALITY_JUDGE_MODEL = "gpt-5-mini"
QUALITY_JUDGE_MAX_OUTPUT_TOKENS = 2000
QUALITY_JUDGE_RETRY_MAX_OUTPUT_TOKENS = 2800
RUNS_ROOT = pathlib.Path("reports/model-routing/runs/price-tier-qualification")


QUALIFICATION_REQUESTS: tuple[tuple[str, str, str, str], ...] = (
    (
        "workspace_onboarding",
        "economy",
        "business",
        "신규 입사자가 프로젝트 알림을 이메일로 받도록 설정하는 짧은 안내를 작성해 주세요.",
    ),
    (
        "billing_document",
        "balanced",
        "business",
        "지난달 세금계산서 사본을 재발급하려고 합니다. 본인 확인과 전달 절차를 단계별로 알려 주세요.",
    ),
    (
        "access_governance",
        "balanced",
        "enterprise",
        "협력사 직원에게 분석 대시보드 읽기 권한만 2주 동안 부여하려고 합니다. 필요한 확인과 승인 절차를 정리해 주세요.",
    ),
    (
        "security_device_loss",
        "advanced",
        "enterprise",
        "관리자 계정이 로그인된 업무용 노트북을 분실했습니다. 현재 위치는 알 수 없고 개인정보 파일을 내려받았을 가능성이 있습니다. 즉시 조치와 보고 순서를 작성해 주세요.",
    ),
    (
        "product_export",
        "economy",
        "business",
        "월간 사용량 보고서를 CSV로 내려받는 방법과 파일에 포함되는 기본 열을 간단히 안내해 주세요.",
    ),
    (
        "webhook_recovery",
        "balanced",
        "business",
        "결제 완료 webhook이 간헐적으로 두 번 전달됩니다. 중복 처리를 막으면서 실패 이벤트를 재시도하는 점검 계획을 작성해 주세요.",
    ),
    (
        "refund_approval",
        "advanced",
        "enterprise",
        "분기 마감 후 대형 고객이 계약에 없는 전액 환불을 요구했습니다. 영업 담당자는 오늘 안에 약속하길 원합니다. 재무·법무 승인과 고객 답변 원칙을 정리해 주세요.",
    ),
    (
        "retention_deletion",
        "advanced",
        "enterprise",
        "퇴사자가 자신의 활동 기록 전체 삭제를 요청했습니다. 일부 기록은 감사 보존 대상이고 백업에도 남아 있습니다. 삭제 범위와 보존 예외, 확인 절차를 작성해 주세요.",
    ),
    (
        "service_latency",
        "advanced",
        "enterprise",
        "아시아 지역 API 지연이 평소의 네 배로 늘었지만 오류율은 정상입니다. 배포 변경과 외부 장애가 동시에 의심될 때 조사·완화·공지 순서를 제시해 주세요.",
    ),
    (
        "contract_review",
        "advanced",
        "enterprise",
        "고객이 표준 SLA보다 강한 손해배상 조항과 무제한 책임을 계약서에 추가했습니다. 담당자가 임의로 수락하지 않도록 위험과 검토 경로를 정리해 주세요.",
    ),
    (
        "analytics_summary",
        "economy",
        "business",
        "팀별 주간 활성 사용자 수와 전주 대비 증감률을 보여 주는 보고서 요청을 데이터 담당자에게 전달할 수 있게 정리해 주세요.",
    ),
    (
        "vendor_risk",
        "advanced",
        "enterprise",
        "새 외부 분석 업체가 운영 DB의 고객 식별자와 접속 로그를 직접 조회해야 한다고 주장합니다. 도입 전에 확인할 보안·개인정보·계약 조건과 대안을 정리해 주세요.",
    ),
    (
        "mfa_recovery",
        "balanced",
        "business",
        "휴대전화를 교체한 사용자가 MFA 복구 코드도 잃어버렸습니다. 계정을 안전하게 복구하기 위한 본인 확인과 관리자 조치 절차를 작성해 주세요.",
    ),
    (
        "notification_settings",
        "economy",
        "business",
        "완료된 workflow 알림만 Slack으로 받고 실패 알림은 이메일과 Slack 모두로 받는 설정 방법을 설명해 주세요.",
    ),
    (
        "closing_mismatch",
        "advanced",
        "enterprise",
        "결산 승인 직전에 원장 합계와 청구 시스템 합계가 맞지 않고 차이가 특정 고객의 수동 조정 건에 몰려 있습니다. 승인 보류 여부와 조사 증거, 책임자 보고 순서를 정리해 주세요.",
    ),
    (
        "cross_border_transfer",
        "advanced",
        "enterprise",
        "한국 고객 지원 데이터를 미국 리전에 복제해 해외 지원팀이 검색하도록 하려 합니다. 개인정보 국외 이전 동의 여부가 불명확할 때 필요한 검토와 차단 조건을 작성해 주세요.",
    ),
)


def reference_request_cost(candidate: ModelCandidate) -> float | None:
    if candidate.input_price_1k is None or candidate.output_price_1k is None:
        return None
    return (
        INPUT_TO_OUTPUT_RATIO * float(candidate.input_price_1k)
        + float(candidate.output_price_1k)
    )


def partition_price_tiers(
    candidates: Iterable[ModelCandidate],
) -> dict[str, list[ModelCandidate]]:
    tiers = {tier: [] for tier in ALL_TIERS}
    for candidate in candidates:
        cost = reference_request_cost(candidate)
        if cost is None:
            continue
        model_id = candidate.model_id.lower()
        if model_id.endswith("-pro"):
            tier = PRO_TIER
        elif cost <= LOW_MAX_REFERENCE_COST_USD:
            tier = LOW_TIER
        elif cost <= MID_MAX_REFERENCE_COST_USD:
            tier = MID_TIER
        else:
            tier = HIGH_TIER
        tiers[tier].append(candidate)
    for tier in tiers:
        tiers[tier].sort(
            key=lambda item: (reference_request_cost(item) or float("inf"), item.model_id)
        )
    return tiers


def build_qualification_cases() -> list[base.ExperimentCase]:
    if len(QUALIFICATION_REQUESTS) != 16:
        raise AssertionError("qualification dataset must contain 16 requests")
    cases: list[base.ExperimentCase] = []
    for index, (category, difficulty, customer_tier, message) in enumerate(
        QUALIFICATION_REQUESTS
    ):
        input_structure = base.INPUT_STRUCTURES[index % 4]
        input_length_bucket = base.INPUT_LENGTH_BUCKETS[index // 4]
        context = base._supporting_context(category, input_length_bucket, 1000 + index)
        payload = base._payload_for_case(
            input_structure=input_structure,
            customer_tier=customer_tier,
            message=message,
            context=context,
        )
        cases.append(
            base.ExperimentCase(
                case_id=f"qualification-{index + 1:02d}-{category}",
                category=category,
                expected_difficulty=difficulty,
                customer_tier=customer_tier,
                message=message,
                input_structure=input_structure,
                input_length_bucket=input_length_bucket,
                input_text=json.dumps(payload, ensure_ascii=False, sort_keys=True),
                payload=payload,
            )
        )
    return cases


def build_qualification_dry_run(
    tiers: dict[str, list[ModelCandidate]], *, case_count: int
) -> dict[str, Any]:
    candidate_count = sum(len(tiers.get(tier, [])) for tier in EXECUTED_TIERS)
    judge_batches_per_case = sum(
        math.ceil(len(tiers.get(tier, [])) / QUALITY_JUDGE_BATCH_SIZE)
        for tier in EXECUTED_TIERS
    )
    return {
        "dry_run": True,
        "case_count": case_count,
        "candidate_model_count": candidate_count,
        "workflow_execution_count": case_count * candidate_count,
        "quality_judge_call_count": case_count * judge_batches_per_case,
        "quality_judge_batch_size": QUALITY_JUDGE_BATCH_SIZE,
        "excluded_pro_model_count": len(tiers.get(PRO_TIER, [])),
        "tiers": {
            tier: [candidate.model_id for candidate in tiers.get(tier, [])]
            for tier in ALL_TIERS
        },
    }


def select_tier_representative(
    summaries: list[dict[str, Any]], *, expected_run_count: int
) -> dict[str, Any]:
    eligible = [
        item
        for item in summaries
        if int(item.get("run_count") or 0) >= expected_run_count
        and float(item.get("workflow_success_rate") or 0) >= MIN_WORKFLOW_SUCCESS_RATE
        and float(item.get("schema_pass_rate") or 0) >= MIN_SCHEMA_PASS_RATE
        and float(item.get("quality_pass_rate") or 0) >= MIN_QUALITY_PASS_RATE
    ]
    if not eligible:
        return {
            "selected_model_id": None,
            "reason": "reliability_gate_failed",
            "eligible_model_ids": [],
            "quality_margin_points": QUALITY_MARGIN_POINTS,
        }
    best_quality = max(float(item["quality_score_average"]) for item in eligible)
    shortlist = [
        item
        for item in eligible
        if float(item["quality_score_average"])
        >= best_quality - QUALITY_MARGIN_POINTS
    ]
    selected = min(
        shortlist,
        key=lambda item: (
            float(item.get("average_cost_usd") or float("inf")),
            float(item.get("average_latency_ms") or float("inf")),
            -float(item.get("quality_score_average") or 0),
            str(item.get("model_id") or ""),
        ),
    )
    return {
        "selected_model_id": str(selected["model_id"]),
        "best_quality_score": best_quality,
        "selected_quality_score": float(selected["quality_score_average"]),
        "quality_margin_points": QUALITY_MARGIN_POINTS,
        "eligible_model_ids": [str(item["model_id"]) for item in eligible],
        "shortlisted_model_ids": [str(item["model_id"]) for item in shortlist],
        "reason": "cheapest_within_quality_margin",
    }


def _available_tiers(db) -> dict[str, list[ModelCandidate]]:
    permitted = set(
        LLMService.get_runtime_available_model_ids_for_user(
            db, user_id=base.USER_ID, organization_id=base.ORG_ID
        )
    )
    candidates = [
        candidate
        for candidate in ModelRouter.collect_candidates(db, organization_id=base.ORG_ID)
        if candidate.model_id in permitted
    ]
    tiers = partition_price_tiers(candidates)
    for tier in EXECUTED_TIERS:
        if not tiers[tier]:
            raise RuntimeError(f"가격군 후보가 없습니다: {tier}")
    return tiers


def _model_case(case: base.ExperimentCase, model_id: str) -> base.ExperimentCase:
    safe_model = model_id.replace("/", "-").replace(":", "-")
    return replace(case, case_id=f"{case.case_id}--{safe_model}")


def _execute_model(case: base.ExperimentCase, model_id: str) -> base.ArmResult:
    original_high_model = base.HIGH_MODEL
    try:
        base.HIGH_MODEL = model_id
        result = base._execute_case(base.HIGH_ARM, _model_case(case, model_id))
    finally:
        base.HIGH_MODEL = original_high_model
    result.arm = model_id
    return result


def _chunks(values: list[str], size: int) -> Iterable[list[str]]:
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _judge_batch(
    case: base.ExperimentCase,
    *,
    tier: str,
    batch_index: int,
    model_ids: list[str],
    results: dict[str, base.ArmResult],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    mapping = list(model_ids)
    random.Random(f"{case.case_id}:{tier}:{batch_index}").shuffle(mapping)
    anonymous = {
        f"output_{index + 1}": results[model_id].output_text
        for index, model_id in enumerate(mapping)
    }
    prompt = {
        "task": "같은 기업 운영 요청을 처리한 익명 JSON 출력의 품질을 절대 기준으로 평가하세요.",
        "input": {
            "structure": case.input_structure,
            "length_bucket": case.input_length_bucket,
            "payload": case.payload,
        },
        "required_contract": {
            "fields": ["분류", "우선순위", "승인필요", "대응계획", "답변초안"],
            "rules": [
                "요청의 핵심 의도와 위험을 정확히 분류해야 합니다.",
                "확인되지 않은 제품 기능, 정책, 법률 판단을 사실처럼 만들면 안 됩니다.",
                "보안, 개인정보, 금전, 계약 위험은 필요한 승인과 차단 조건을 포함해야 합니다.",
                "대응계획은 실행 가능하고 답변초안은 사용자가 이해할 수 있어야 합니다.",
                "모델 이름, 비용, 속도, 출력 순서를 추측하거나 평가에 반영하지 마세요.",
            ],
        },
        "anonymous_outputs": anonymous,
        "response_schema": {
            key: {
                "quality_score": "0..100",
                "contract_pass": "boolean",
                "reason": "short Korean",
            }
            for key in anonymous
        },
    }
    with SessionLocal() as db:
        selection = LLMService.get_runtime_client_for_user(
            db, base.USER_ID, QUALITY_JUDGE_MODEL, base.ORG_ID
        )
        messages = [
            {
                "role": "system",
                "content": "당신은 엄격하고 공정한 workflow output 품질 평가자입니다. 반드시 JSON object 하나만 반환하세요.",
            },
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ]
        started = datetime.now(timezone.utc)
        try:
            response = selection.client.invoke_sync(
                messages,
                temperature=0,
                max_tokens=QUALITY_JUDGE_MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
            )
            attempt_count = 1
        except Exception as exc:
            if str(getattr(exc, "reason_code", "")) != "responses_incomplete":
                raise
            response = selection.client.invoke_sync(
                messages,
                temperature=0,
                max_tokens=QUALITY_JUDGE_RETRY_MAX_OUTPUT_TOKENS,
                response_format={"type": "json_object"},
            )
            attempt_count = 2
        elapsed_ms = int(
            (datetime.now(timezone.utc) - started).total_seconds() * 1000
        )
        payload = base._json_from_text(
            str(response.get("choices", [{}])[0].get("message", {}).get("content", ""))
        )
        usage = response.get("usage") if isinstance(response, dict) else {}
        prompt_tokens = int((usage or {}).get("prompt_tokens") or 0)
        completion_tokens = int((usage or {}).get("completion_tokens") or 0)
        cost = LLMService.calculate_cost(
            db, QUALITY_JUDGE_MODEL, prompt_tokens, completion_tokens
        )

    judged: dict[str, dict[str, Any]] = {}
    for index, model_id in enumerate(mapping):
        row = payload.get(f"output_{index + 1}")
        row = row if isinstance(row, dict) else {}
        try:
            score = max(0.0, min(100.0, float(row.get("quality_score"))))
        except (TypeError, ValueError):
            score = 0.0
        judged[model_id] = {
            "quality_score": score,
            "contract_pass": bool(row.get("contract_pass")),
            "reason": str(row.get("reason") or "품질 Judge 응답 없음")[:240],
        }
    return judged, {
        "tier": tier,
        "batch_index": batch_index,
        "model_ids": model_ids,
        "judge_model": QUALITY_JUDGE_MODEL,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost_usd": cost,
        "latency_ms": elapsed_ms,
        "attempt_count": attempt_count,
    }


def _judge_case(
    case: base.ExperimentCase,
    tiers: dict[str, list[ModelCandidate]],
    results: dict[str, base.ArmResult],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    quality: dict[str, dict[str, Any]] = {}
    metrics: list[dict[str, Any]] = []
    for tier in EXECUTED_TIERS:
        model_ids = [candidate.model_id for candidate in tiers[tier]]
        for batch_index, batch in enumerate(
            _chunks(model_ids, QUALITY_JUDGE_BATCH_SIZE), start=1
        ):
            try:
                judged, metric = _judge_batch(
                    case,
                    tier=tier,
                    batch_index=batch_index,
                    model_ids=batch,
                    results=results,
                )
            except Exception as exc:
                error = f"{type(exc).__name__}:{str(exc)[:180]}"
                judged = {
                    model_id: {
                        "quality_score": 0.0,
                        "contract_pass": False,
                        "reason": f"quality_judge_error:{error}",
                    }
                    for model_id in batch
                }
                metric = {
                    "tier": tier,
                    "batch_index": batch_index,
                    "model_ids": batch,
                    "error": error,
                }
            quality.update(judged)
            metrics.append(metric)
    return quality, metrics


def _mean(values: Iterable[float | int | None]) -> float | None:
    normalized = [float(value) for value in values if value is not None]
    return statistics.mean(normalized) if normalized else None


def _model_summary(rows: list[dict[str, Any]], model_id: str) -> dict[str, Any]:
    model_rows = [row["models"][model_id] for row in rows if model_id in row["models"]]
    quality_rows = [
        row["quality"][model_id] for row in rows if model_id in row.get("quality", {})
    ]
    run_count = len(model_rows)
    return {
        "model_id": model_id,
        "run_count": run_count,
        "workflow_success_rate": (
            sum(bool(row.get("workflow_success")) for row in model_rows) / run_count
            if run_count
            else 0.0
        ),
        "schema_pass_rate": (
            sum(bool(row.get("schema_pass")) for row in model_rows) / run_count
            if run_count
            else 0.0
        ),
        "quality_score_average": _mean(
            row.get("quality_score") for row in quality_rows
        )
        or 0.0,
        "quality_pass_rate": (
            sum(bool(row.get("contract_pass")) for row in quality_rows) / run_count
            if run_count
            else 0.0
        ),
        "average_cost_usd": _mean(row.get("task_cost_usd") for row in model_rows)
        or 0.0,
        "total_cost_usd": sum(float(row.get("task_cost_usd") or 0) for row in model_rows),
        "average_latency_ms": _mean(
            row.get("workflow_latency_ms") for row in model_rows
        )
        or 0.0,
        "total_tokens": sum(int(row.get("total_tokens") or 0) for row in model_rows),
    }


def _build_report(
    *,
    tiers: dict[str, list[ModelCandidate]],
    rows: list[dict[str, Any]],
    judge_metrics: list[dict[str, Any]],
) -> dict[str, Any]:
    tier_summaries: dict[str, list[dict[str, Any]]] = {}
    decisions: dict[str, dict[str, Any]] = {}
    complete = len(rows) == len(build_qualification_cases())
    for tier in EXECUTED_TIERS:
        summaries = [
            _model_summary(rows, candidate.model_id) for candidate in tiers[tier]
        ]
        tier_summaries[tier] = summaries
        decisions[tier] = (
            select_tier_representative(
                summaries, expected_run_count=len(build_qualification_cases())
            )
            if complete
            else {
                "selected_model_id": None,
                "reason": "qualification_incomplete",
            }
        )
    return {
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(rows),
        "expected_case_count": len(build_qualification_cases()),
        "complete": complete,
        "tiers": {
            tier: [
                {
                    "model_id": item.model_id,
                    "input_price_1k": item.input_price_1k,
                    "output_price_1k": item.output_price_1k,
                    "reference_request_cost_usd": reference_request_cost(item),
                }
                for item in tiers[tier]
            ]
            for tier in ALL_TIERS
        },
        "runs": rows,
        "tier_summaries": tier_summaries,
        "representative_decisions": decisions,
        "quality_judge_model": QUALITY_JUDGE_MODEL,
        "quality_judge_call_count": sum(
            1 for item in judge_metrics if not item.get("error")
        ),
        "quality_judge_errors": [item for item in judge_metrics if item.get("error")],
        "quality_judge_total_cost_usd": sum(
            float(item.get("cost_usd") or 0) for item in judge_metrics
        ),
        "all_model_execution_cost_usd": sum(
            float(model.get("task_cost_usd") or 0)
            for row in rows
            for model in row["models"].values()
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 모델 가격군 대표 선발 결과",
        "",
        f"- 완료: {'예' if report['complete'] else '아니오'} ({report['case_count']}/{report['expected_case_count']}건)",
        f"- 모델 실행 비용: ${report['all_model_execution_cost_usd']:.6f}",
        f"- 품질 Judge 비용: ${report['quality_judge_total_cost_usd']:.6f}",
        f"- 품질 Judge 오류: {len(report['quality_judge_errors'])}건",
        "",
        "## 대표 선발",
        "",
        "| 가격군 | 대표 | 판정 |",
        "| --- | --- | --- |",
    ]
    for tier in EXECUTED_TIERS:
        decision = report["representative_decisions"][tier]
        lines.append(
            f"| {tier} | {decision.get('selected_model_id') or '-'} | {decision.get('reason') or '-'} |"
        )
    for tier in EXECUTED_TIERS:
        lines.extend(
            [
                "",
                f"## {tier} 가격군",
                "",
                "| 모델 | 평균 품질 | 품질 통과 | workflow 성공 | schema 통과 | 평균 비용 | 평균 시간 |",
                "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
            ]
        )
        for item in report["tier_summaries"][tier]:
            lines.append(
                f"| {item['model_id']} | {item['quality_score_average']:.2f} | "
                f"{item['quality_pass_rate'] * 100:.1f}% | {item['workflow_success_rate'] * 100:.1f}% | "
                f"{item['schema_pass_rate'] * 100:.1f}% | ${item['average_cost_usd']:.6f} | "
                f"{item['average_latency_ms']:.0f}ms |"
            )
    lines.extend(
        [
            "",
            "## 주의",
            "",
            "품질 점수는 LLM Judge의 상대 지표다. 최종 운영 적용 전 사람 검수와 실제 업무 실패 비용을 함께 확인해야 한다.",
            "",
        ]
    )
    return "\n".join(lines)


def _write_report(output_dir: pathlib.Path, report: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "result.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "report.md").write_text(_markdown(report), encoding="utf-8")


def _read_report(output_dir: pathlib.Path) -> dict[str, Any]:
    path = output_dir / "result.json"
    if not path.exists():
        raise RuntimeError(f"resume 결과가 없습니다: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("resume 결과 형식이 올바르지 않습니다.")
    return payload


def run_qualification(
    *,
    tiers: dict[str, list[ModelCandidate]],
    selected_cases: list[base.ExperimentCase],
    output_dir: pathlib.Path,
    resume: bool,
) -> dict[str, Any]:
    candidate_ids = [
        candidate.model_id for tier in EXECUTED_TIERS for candidate in tiers[tier]
    ]
    if resume:
        previous = _read_report(output_dir)
        rows = list(previous.get("runs") or [])
        judge_metrics = list(previous.get("quality_judge_metrics") or [])
        completed_case_ids = {str(row.get("case_id")) for row in rows}
    else:
        rows = []
        judge_metrics: list[dict[str, Any]] = []
        completed_case_ids: set[str] = set()
        with SessionLocal() as db:
            for model_id in [*candidate_ids, QUALITY_JUDGE_MODEL]:
                LLMService.get_runtime_client_for_user(
                    db, base.USER_ID, model_id, base.ORG_ID
                )
            base._upsert_workflow_and_deployments(db, candidate_ids)
            db.commit()

    with base.synchronous_experiment_tasks():
        for index, case in enumerate(selected_cases, start=1):
            if case.case_id in completed_case_ids:
                continue
            model_cases = [_model_case(case, model_id) for model_id in candidate_ids]
            with SessionLocal() as db:
                base._clear_case_runs(db, model_cases)
                db.commit()
            execution_order = list(candidate_ids)
            random.Random(case.case_id).shuffle(execution_order)
            results = {
                model_id: _execute_model(case, model_id)
                for model_id in execution_order
            }
            quality, case_judge_metrics = _judge_case(case, tiers, results)
            judge_metrics.extend(
                {"case_id": case.case_id, **item} for item in case_judge_metrics
            )
            rows.append(
                {
                    "case_id": case.case_id,
                    "category": case.category,
                    "expected_difficulty": case.expected_difficulty,
                    "input_structure": case.input_structure,
                    "input_length_bucket": case.input_length_bucket,
                    "payload": case.payload,
                    "execution_order": execution_order,
                    "models": {
                        model_id: asdict(result) for model_id, result in results.items()
                    },
                    "quality": quality,
                }
            )
            rows.sort(key=lambda item: str(item["case_id"]))
            report = _build_report(tiers=tiers, rows=rows, judge_metrics=judge_metrics)
            report["quality_judge_metrics"] = judge_metrics
            _write_report(output_dir, report)
            print(
                f"[progress] qualification {len(rows)}/{len(build_qualification_cases())} "
                f"(batch {index}/{len(selected_cases)}) completed",
                flush=True,
            )

    report = _build_report(tiers=tiers, rows=rows, judge_metrics=judge_metrics)
    report["quality_judge_metrics"] = judge_metrics
    _write_report(output_dir, report)
    print(
        json.dumps(
            {
                "json": str((output_dir / "result.json").resolve()),
                "markdown": str((output_dir / "report.md").resolve()),
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="모델 가격군 대표 16건 예선")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--count", type=int, default=16)
    parser.add_argument(
        "--run-id",
        default="2026-07-18__price-tier-qualification-v1__judge-gpt-5-mini",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    cases = build_qualification_cases()
    if args.count < 1 or args.offset < 0 or args.offset + args.count > len(cases):
        raise SystemExit(f"--offset/--count 범위는 0~{len(cases)} 안이어야 합니다.")
    selected_cases = cases[args.offset : args.offset + args.count]
    with SessionLocal() as db:
        tiers = _available_tiers(db)
    dry_run = build_qualification_dry_run(tiers, case_count=len(selected_cases))
    dry_run.update(
        {
            "categories": dict(Counter(case.category for case in selected_cases)),
            "difficulty": dict(
                Counter(case.expected_difficulty for case in selected_cases)
            ),
            "input_structures": dict(
                Counter(case.input_structure for case in selected_cases)
            ),
            "input_length_buckets": dict(
                Counter(case.input_length_bucket for case in selected_cases)
            ),
        }
    )
    if not args.execute:
        print(json.dumps(dry_run, ensure_ascii=False, indent=2))
        return
    output_dir = RUNS_ROOT / str(args.run_id)
    run_qualification(
        tiers=tiers,
        selected_cases=selected_cases,
        output_dir=output_dir,
        resume=bool(args.resume),
    )


if __name__ == "__main__":
    main()
