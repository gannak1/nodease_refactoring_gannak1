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

    return sorted(
        {
            model_id.strip()
            for model_id in available_model_ids
            if OPENAI_ROUTING_MODEL_PATTERN.match(model_id.strip())
        }
    )


def _default_output_path() -> pathlib.Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "reports" / "model-routing" / "runtime-judge-diagnostics" / f"{timestamp}.json"


def _cases() -> list[dict[str, Any]]:
    return [
        {
            "id": "low-short-guide",
            "expected_band": "low",
            "request_feature": "사용자가 비밀번호 재설정 메뉴 위치를 한 문장으로 물었습니다.",
            "rag_context": {"used": False},
        },
        {
            "id": "low-structured-extraction",
            "expected_band": "low",
            "request_feature": (
                "짧은 고객 요청에서 주문 번호, 제품명, 희망 연락 수단 세 필드만 JSON으로 추출합니다. "
                "추론이나 정책 판단은 필요하지 않습니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "mid-multi-constraint-access",
            "expected_band": "mid",
            "request_feature": (
                "결제는 완료됐지만 초대 메일이 오지 않고 SSO 로그인만 성공합니다. "
                "계정 상태, 팀 권한, 이메일 반송 여부를 어떤 순서로 확인할지 안내해야 합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "mid-long-synthesis",
            "expected_band": "mid",
            "request_feature": (
                "세 부서가 제출한 장문의 장애 보고를 읽고 공통 원인, 이미 완료한 조치, 남은 담당자를 "
                "중복 없이 정리합니다. 다만 법무·보상·개인정보 판단은 포함하지 않습니다. "
                "보고서에는 다섯 개의 실행 항목과 담당 팀을 구조화해 작성해야 합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "mid-structured-plan",
            "expected_band": "mid",
            "request_feature": (
                "신규 협력사 계정을 읽기 전용으로 만들고 계약 종료일에 자동 회수해야 합니다. "
                "담당자 확인, 권한 범위, 예외 처리 순서를 JSON 체크리스트로 작성합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "high-short-irreversible-decision",
            "expected_band": "high",
            "request_feature": (
                "한 문장 요청이지만 지금 고객 계정을 즉시 정지할지 유지할지 결정해야 합니다. "
                "오판하면 서비스 중단 또는 보안 사고가 발생할 수 있습니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "high-ambiguous-finance-decision",
            "expected_band": "high",
            "request_feature": (
                "두 비용센터의 결산 수치가 다르고 계약 변경 승인 여부가 불분명합니다. "
                "누락 정보를 구분하고 승인 보류 또는 진행 판단의 근거를 정리해야 합니다."
            ),
            "rag_context": {"used": False},
        },
        {
            "id": "high-risk-rag-conflict",
            "expected_band": "high",
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
                    "selected_model_id": decision.selected_model_id,
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
