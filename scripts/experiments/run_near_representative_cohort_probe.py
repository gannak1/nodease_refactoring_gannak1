"""대표 문의와 거의 같은 배포 요청으로 입력군 관찰 저장을 점검한다.

이 스크립트는 실제 배포 API와 provider를 호출한다. 한글 payload가 셸 인코딩으로
손상되지 않도록 대표 문의와 변형 문장을 UTF-8 Python 소스에 고정한다.
"""

from __future__ import annotations

import argparse
import os
import time
import uuid
from collections import Counter

from scripts.experiment_enterprise_request_routing import (
    DEFAULT_DEPLOYMENT_ID,
    DEFAULT_EMAIL,
    DEFAULT_NODE_ID,
    DEFAULT_ORGANIZATION_ID,
    DEFAULT_PASSWORD_ENV,
    DEFAULT_WORKFLOW_ID,
    EnterpriseExperimentClient,
    _policy_path,
    _wait_for_run_detail,
)


REPRESENTATIVE_QUERIES: dict[str, tuple[str, ...]] = {
    "routine_usage_guidance": (
        "사내 시스템에서 증명서를 내려받는 위치와 절차를 알려 주세요.",
        "사내 시스템에서 증명서를 내려받는 위치와 절차를 알려 주세요. 간단히 안내해 주세요.",
        "사내 시스템에서 증명서를 내려받는 위치와 절차를 알려 주세요. 메뉴 이름도 알려 주세요.",
        "사내 시스템에서 증명서를 내려받는 위치와 절차를 알려 주세요. 순서대로 설명해 주세요.",
        "사내 시스템에서 증명서를 내려받는 위치와 절차를 알려 주세요. 현재 계정 기준으로 알려 주세요.",
        "사내 시스템에서 증명서를 내려받는 위치와 절차를 알려 주세요. 필요한 권한도 함께 알려 주세요.",
    ),
    "account_access_request": (
        "퇴사자 Git 저장소와 VPN 접근 권한을 회수하는 절차를 알려 주세요.",
        "퇴사자 Git 저장소와 VPN 접근 권한을 회수하는 절차를 알려 주세요. 순서대로 안내해 주세요.",
        "퇴사자 Git 저장소와 VPN 접근 권한을 회수하는 절차를 알려 주세요. 오늘 처리해야 합니다.",
        "퇴사자 Git 저장소와 VPN 접근 권한을 회수하는 절차를 알려 주세요. 확인 항목도 알려 주세요.",
        "퇴사자 Git 저장소와 VPN 접근 권한을 회수하는 절차를 알려 주세요. 최소 권한 기준으로 설명해 주세요.",
        "퇴사자 Git 저장소와 VPN 접근 권한을 회수하는 절차를 알려 주세요. 처리 후 점검도 필요합니다.",
    ),
    "finance_closing_approval": (
        "해외 지급 건의 증빙과 월말 결산 승인 절차를 확인해 주세요.",
        "해외 지급 건의 증빙과 월말 결산 승인 절차를 확인해 주세요. 필요한 자료를 알려 주세요.",
        "해외 지급 건의 증빙과 월말 결산 승인 절차를 확인해 주세요. 승인 순서도 알려 주세요.",
        "해외 지급 건의 증빙과 월말 결산 승인 절차를 확인해 주세요. 누락 자료를 점검해 주세요.",
        "해외 지급 건의 증빙과 월말 결산 승인 절차를 확인해 주세요. 마감 전에 처리해야 합니다.",
        "해외 지급 건의 증빙과 월말 결산 승인 절차를 확인해 주세요. 우선순위도 알려 주세요.",
    ),
    "security_privacy_incident": (
        "고객 개인정보가 외부 메일로 전송됐을 때 즉시 해야 할 조치를 알려 주세요.",
        "고객 개인정보가 외부 메일로 전송됐을 때 즉시 해야 할 조치를 알려 주세요. 긴급 대응 순서를 알려 주세요.",
        "고객 개인정보가 외부 메일로 전송됐을 때 즉시 해야 할 조치를 알려 주세요. 지금 바로 조치해야 합니다.",
        "고객 개인정보가 외부 메일로 전송됐을 때 즉시 해야 할 조치를 알려 주세요. 사고 대응 절차를 알려 주세요.",
        "고객 개인정보가 외부 메일로 전송됐을 때 즉시 해야 할 조치를 알려 주세요. 외부 전송을 차단해야 합니다.",
        "고객 개인정보가 외부 메일로 전송됐을 때 즉시 해야 할 조치를 알려 주세요. 초기 대응 순서를 알려 주세요.",
    ),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    parser.add_argument("--deployment-id", default=DEFAULT_DEPLOYMENT_ID)
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID)
    parser.add_argument("--organization-id", default=DEFAULT_ORGANIZATION_ID)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    parser.add_argument(
        "--cohort",
        action="append",
        choices=tuple(REPRESENTATIVE_QUERIES),
        help="실행할 입력군 key. 생략하면 모든 입력군을 실행합니다.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=5,
        help="입력군별 실행 수. 대표 문의와 가까운 변형 문장 수를 넘을 수 없습니다.",
    )
    parser.add_argument("--confirm-live", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.confirm_live:
        raise RuntimeError("실제 provider 호출은 --confirm-live를 명시해야 합니다.")
    password = os.getenv(args.password_env)
    if not password:
        raise RuntimeError(f"{args.password_env} 환경변수가 필요합니다.")
    if args.count < 1:
        raise RuntimeError("--count는 1 이상이어야 합니다.")

    client = EnterpriseExperimentClient(
        base_url=args.base_url,
        organization_id=args.organization_id,
        email=args.email,
        password=password,
        timeout_seconds=240,
    )
    results: list[tuple[str, str, str, str | None]] = []
    cohort_keys = args.cohort or list(REPRESENTATIVE_QUERIES)
    for cohort_key in cohort_keys:
        queries = REPRESENTATIVE_QUERIES[cohort_key]
        if args.count > len(queries):
            raise RuntimeError(f"{cohort_key}은(는) 최대 {len(queries)}건까지 실행할 수 있습니다.")
        for index, query in enumerate(queries[:args.count], start=1):
            response = client.session.post(
                f"{args.base_url}/api/v1/deployments/{args.deployment_id}/run",
                json={"inputs": {"query": query, "department": "모델 라우팅 검증", "requesterRole": "운영 담당자", "locale": "ko-KR"}},
                headers={"X-Correlation-Id": f"near-cohort-{cohort_key}-{index}-{uuid.uuid4().hex[:8]}"},
                timeout=600,
            )
            response.raise_for_status()
            run_id = str(response.json()["run_id"])
            run = _wait_for_run_detail(
                client,
                workflow_id=args.workflow_id,
                run_id=run_id,
                node_id=args.node_id,
                timeout_seconds=240,
            )
            node_run = next(item for item in run["node_runs"] if item.get("node_id") == args.node_id)
            routing = (node_run.get("trace_metadata") or {}).get("model_routing") or {}
            results.append((cohort_key, str(index), str(routing.get("decision_source") or "unknown"), routing.get("matched_cohort_key")))
            print(f"{cohort_key} #{index}: {routing.get('decision_source') or 'unknown'} -> {routing.get('matched_cohort_key') or 'default'}", flush=True)
            time.sleep(0.2)

    print("summary:", dict(Counter(f"{expected}:{actual or 'default'}" for expected, _, _, actual in results)))
    print("policy:", client.get_json(_policy_path(args.workflow_id, args.node_id)).get("adaptive", {}).get("cohorts", []))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
