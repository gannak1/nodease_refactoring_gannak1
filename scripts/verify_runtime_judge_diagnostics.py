"""Runtime Judge의 모델 선택 근거를 세 요청으로 직접 확인하는 수동 검증 도구.

실제 provider 호출이 발생하므로 기본값은 dry-run이다. ``--execute``를 명시해야
현재 조직의 실행 가능 모델과 credential을 사용해 Judge를 호출한다.
"""

# 이 스크립트는 repo root를 sys.path에 추가한 뒤 애플리케이션 모듈을 import한다.
# ruff: noqa: E402

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import pathlib
import re
import sys
import uuid
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
for candidate_path in (ROOT, ROOT.parent):
    if str(candidate_path) not in sys.path:
        sys.path.append(str(candidate_path))

from apps.shared.db.session import SessionLocal
from apps.shared.services.model_routing_global_profile_catalog import (
    deduplicate_model_routing_ids,
)
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_routing_runtime_judge import (
    ModelRoutingRuntimeJudge,
)
from apps.workflow_engine.workflow.nodes.llm.llm_node import LLMNode


DEFAULT_ORGANIZATION_ID = uuid.UUID("10200000-0000-0000-0000-000000000100")
DEFAULT_USER_ID = uuid.UUID("10200000-0000-0000-0000-000000000001")
OPENAI_ROUTING_MODEL_PATTERN = re.compile(
    r"^(?:gpt-(?:4\.1|4o|5(?:\.\d+)?)(?:-[a-z0-9.-]+)?|o3(?:-pro)?)$",
    re.IGNORECASE,
)


def _diagnostic_candidates(available_model_ids: list[str]) -> list[str]:
    """현재 credential으로 실행 가능한 GPT-4.1~5.x 및 O3 후보를 모두 진단한다."""

    return deduplicate_model_routing_ids(
        sorted(
            {
            model_id.strip()
            for model_id in available_model_ids
            if OPENAI_ROUTING_MODEL_PATTERN.match(model_id.strip())
            }
        )
    )


def _default_output_path() -> pathlib.Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "reports" / "model-routing" / "runtime-judge-diagnostics" / f"{timestamp}.json"


def _cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "low-short-guide",
            "expected_band": "low",
            "expected_model_ids": ["gpt-4o-mini", "gpt-5-mini", "gpt-5.6-luna"],
            "hypothesis": "단일 안내는 비용 효율적인 범용 모델이면 충분하다.",
            "request_feature": "사용자가 비밀번호 재설정 메뉴 위치를 한 문장으로 물었습니다.",
            "rag_context": {"used": False},
        },
        {
            "id": "low-structured-extraction",
            "expected_band": "low",
            "expected_model_ids": ["gpt-4o-mini", "gpt-5-mini", "gpt-5.6-luna"],
            "hypothesis": "추론 없는 정형 추출은 저비용·고량 처리 모델이 적합하다.",
            "request_feature": (
                "짧은 고객 요청에서 주문 번호, 제품명, 희망 연락 수단 세 필드만 JSON으로 추출합니다. "
                "추론이나 정책 판단은 필요하지 않습니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "mid-multi-constraint-access",
            "expected_band": "mid",
            "expected_model_ids": ["gpt-4o-mini", "gpt-5-mini", "gpt-4.1-mini", "gpt-5.4-mini", "gpt-5.6-terra"],
            "hypothesis": "독립적인 점검 절차는 저비용 또는 균형형 범용 모델이면 충분하다.",
            "request_feature": (
                "결제는 완료됐지만 초대 메일이 오지 않고 SSO 로그인만 성공합니다. "
                "계정 상태, 팀 권한, 이메일 반송 여부를 어떤 순서로 확인할지 안내해야 합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "high-professional-executive-synthesis",
            "expected_band": "high",
            "expected_model_ids": ["gpt-5.4", "gpt-5.6-sol"],
            "hypothesis": "형식 논증보다 전문 결과물 완성도가 핵심인 복합 업무는 frontier generalist가 적합하다.",
            "request_feature": (
                "세 부서의 장문 분기 보고서와 고객 영향 분석을 통합해 완성도 높은 경영진 보고서를 작성합니다. "
                "사업 영향, 완료 조치, 남은 책임자와 다음 분기 우선순위를 일관된 서술과 표로 구성하고, "
                "임원 독자를 위한 간결한 요약과 의사결정 요청을 포함해야 합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "mid-structured-plan",
            "expected_band": "mid",
            "expected_model_ids": ["gpt-5-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-5.4-mini", "gpt-5.6-terra"],
            "hypothesis": "명확한 지시와 구조화된 체크리스트는 mini 또는 비추론 범용 모델이 적합하다.",
            "request_feature": (
                "신규 협력사 계정을 읽기 전용으로 만들고 계약 종료일에 자동 회수해야 합니다. "
                "담당자 확인, 권한 범위, 예외 처리 순서를 JSON 체크리스트로 작성합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "high-formal-constraint-reasoning",
            "expected_band": "high",
            "expected_model_ids": ["o3"],
            "hypothesis": "해 탐색과 반례 검사가 핵심인 형식 제약 문제는 reasoning specialist가 적합하다.",
            "request_feature": (
                "서로 의존하는 여섯 개 제약과 세 가지 예외 조건을 만족하는 배치 순서를 찾아야 합니다. "
                "각 선택이 다음 단계의 가능성을 바꾸므로 반례를 검사하고 모순이 없는 해를 증명해야 합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "high-scientific-causal-reasoning",
            "expected_band": "high",
            "expected_model_ids": ["o3"],
            "hypothesis": "인과 가설과 반증 실험 설계는 과학 추론 특화 모델이 적합하다.",
            "request_feature": (
                "서로 다른 세 실험에서 관찰된 결과가 일부 충돌합니다. 교란 변수를 분리하고 "
                "가능한 인과 가설을 비교한 뒤, 각 가설을 반증할 후속 실험을 설계해야 합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "high-risk-rag-conflict",
            "expected_band": "high",
            "expected_model_ids": ["gpt-5.4", "gpt-5.6-sol", "o3"],
            "hypothesis": "충돌 규정과 고위험 판단은 고성능 일반 모델 또는 전문 추론 모델이 필요하다.",
            "request_feature": (
                "개인정보 삭제 요청과 법적 보존 요청이 충돌합니다. "
                "검색된 내부 규정을 종합해 자동 삭제를 중지할지 판단해야 합니다."
            ),
            "rag_context": {
                "used": True,
                "retrieved_context_token_estimate": 4200,
                "retrieved_context_chars": 14800,
                "source_count": 3,
            },
        },
        {
            "id": "high-rag-multi-document-synthesis",
            "expected_band": "high",
            "expected_model_ids": ["gpt-5.4", "gpt-5.6-sol", "o3"],
            "hypothesis": "긴 다문서 정책 판단은 고성능 일반 모델이나 전문 추론 모델이 적합하다.",
            "request_feature": (
                "검색된 보안 운영 규정, 장애 대응 절차, 고객 공지 기준을 함께 읽고 "
                "현재 상황에 맞는 조치 순서와 외부 공지 가능 여부를 판단합니다."
            ),
            "rag_context": {
                "used": True,
                "retrieved_context_token_estimate": 6800,
                "retrieved_context_chars": 23800,
                "source_count": 5,
            },
        },
        {
            "id": "low-formatting-rewrite",
            "expected_band": "low",
            "expected_model_ids": ["gpt-4o-mini", "gpt-5-mini", "gpt-5.6-luna"],
            "hypothesis": "의미 추가 없는 형식 변환은 저비용 모델이 적합하다.",
            "request_feature": (
                "이미 작성된 한 문단을 존댓말 세 문장으로만 다듬고 의미를 추가하지 않습니다."
            ),
            "rag_context": {"used": False},
        },
    ]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true", help="실제 Judge provider 호출을 허용합니다.")
    parser.add_argument("--organization-id", default=str(DEFAULT_ORGANIZATION_ID))
    parser.add_argument("--user-id", default=str(DEFAULT_USER_ID))
    parser.add_argument("--judge-model", default="gpt-5.4-mini")
    parser.add_argument(
        "--output",
        help="진단 결과 JSON 저장 경로입니다. 기본값은 reports/model-routing 아래 UTC 파일명입니다.",
    )
    args = parser.parse_args()

    if not args.execute:
        print(json.dumps({"mode": "dry_run", "cases": _cases()}, ensure_ascii=False, indent=2))
        return

    organization_id = uuid.UUID(args.organization_id)
    user_id = uuid.UUID(args.user_id)
    db = SessionLocal()
    try:
        available = LLMService.get_runtime_available_model_ids_for_user(
            db,
            user_id=user_id,
            organization_id=organization_id,
        )
        candidates = _diagnostic_candidates(available)
        if len(candidates) < 2:
            raise RuntimeError(f"비교 가능한 후보 모델이 부족합니다: {candidates}")
        if args.judge_model not in available:
            raise RuntimeError(f"Judge 모델을 실행할 수 없습니다: {args.judge_model}")

        client = LLMService.get_runtime_client_for_user(
            db,
            user_id=user_id,
            model_id=args.judge_model,
            organization_id=organization_id,
        ).client
        profiles = LLMNode._routing_candidate_profiles(db, candidates)
        results = []
        for case in _cases():
            decision = ModelRoutingRuntimeJudge.decide(
                client=client,
                candidate_model_ids=candidates,
                routing_feature_text=case["request_feature"],
                rag_context=case["rag_context"],
                candidate_profiles=profiles,
                diagnostic_mode=True,
            )
            results.append(
                {
                    "case_id": case["id"],
                    "expected_band": case["expected_band"],
                    "expected_model_ids": case["expected_model_ids"],
                    "hypothesis": case["hypothesis"],
                    "selected_model_id": decision.selected_model_id,
                    "hypothesis_matched": decision.selected_model_id
                    in case["expected_model_ids"],
                    "confidence": decision.confidence,
                    "reason_short": decision.reason_short,
                    "reason_code": decision.reason_code,
                    "decision_detail": decision.decision_detail,
                    "usage": decision.usage,
                }
            )
        report = {
            "diagnostic_max_output_tokens": ModelRoutingRuntimeJudge.DIAGNOSTIC_MAX_OUTPUT_TOKENS,
            "judge_model": args.judge_model,
            "candidates": candidates,
            "results": results,
            "case_count": len(results),
            "hypothesis_match_count": sum(
                1 for result in results if result["hypothesis_matched"]
            ),
        }
        output_path = pathlib.Path(args.output) if args.output else _default_output_path()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps({"output_path": str(output_path), **report}, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
