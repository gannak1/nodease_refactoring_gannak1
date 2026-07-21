"""Requirement Judge의 3축 판정을 직접 확인하는 수동 도구.

실제 provider 호출은 ``--execute``에서만 발생한다. 이 도구는 모델을 고르지 않고
요구 수준·불확실성·usage만 보고한다.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import pathlib
import sys
import uuid
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from apps.shared.db.session import SessionLocal  # noqa: E402
from apps.workflow_engine.services.llm_service import LLMService  # noqa: E402
from apps.workflow_engine.services.model_routing_runtime_judge import (  # noqa: E402
    ModelRoutingRuntimeJudge,
)


DEFAULT_CASES = ROOT / "tests" / "fixtures" / "model_routing" / "requirement_judge_review_v1.json"
DEFAULT_ORGANIZATION_ID = uuid.UUID("10200000-0000-0000-0000-000000000100")
DEFAULT_USER_ID = uuid.UUID("10200000-0000-0000-0000-000000000001")


def _default_output_path() -> pathlib.Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return ROOT / "reports" / "model-routing" / "requirement-judge" / f"{timestamp}.json"


def _read_cases(path: pathlib.Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    cases = payload.get("cases") if isinstance(payload, dict) else None
    if not isinstance(cases, list):
        raise ValueError("cases fixture에 cases 배열이 필요합니다")
    return [case for case in cases if isinstance(case, dict)]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--organization-id", default=str(DEFAULT_ORGANIZATION_ID))
    parser.add_argument("--user-id", default=str(DEFAULT_USER_ID))
    parser.add_argument("--judge-model", default="gpt-5.4-mini")
    parser.add_argument("--cases", type=pathlib.Path, default=DEFAULT_CASES)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--output", type=pathlib.Path)
    args = parser.parse_args()

    cases = _read_cases(args.cases)[: max(1, args.limit)]
    if not args.execute:
        print(json.dumps({"mode": "dry_run", "cases": cases}, ensure_ascii=False, indent=2))
        return

    db = SessionLocal()
    try:
        organization_id = uuid.UUID(args.organization_id)
        user_id = uuid.UUID(args.user_id)
        client = LLMService.get_runtime_client_for_user(
            db,
            user_id=user_id,
            model_id=args.judge_model,
            organization_id=organization_id,
        ).client
        results = []
        for case in cases:
            assessment = ModelRoutingRuntimeJudge.assess_requirements(
                client=client,
                routing_feature_text=str(case.get("request_feature") or ""),
                structural_facts=case.get("structural_facts"),
                rag_context=case.get("rag_context"),
            )
            results.append(
                {
                    "case_id": case.get("case_id"),
                    "task_requirements": assessment.task_requirements,
                    "confidence": assessment.confidence,
                    "ambiguity_flags": assessment.ambiguity_flags,
                    "reason_codes": assessment.reason_codes,
                    "usage": assessment.usage,
                }
            )
        report = {
            "rubric_version": ModelRoutingRuntimeJudge.REQUIREMENT_RUBRIC_VERSION,
            "judge_model": args.judge_model,
            "case_count": len(results),
            "results": results,
        }
        output_path = args.output or _default_output_path()
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
