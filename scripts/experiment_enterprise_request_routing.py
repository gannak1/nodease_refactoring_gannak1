"""엔터프라이즈 통합 업무 요청의 배포 모델 라우팅을 50건으로 검증한다.

DB에 직접 접근하지 않고 인증 API, 배포 실행 API, 실행 로그 API, 모델 라우팅
정책 API만 사용한다. 실제 provider 호출은 ``--confirm-live``를 명시한 경우에만
수행한다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
import uuid
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiment_team_onboarding_adaptive_routing import (
    RemoteExperimentClient,
    _find_source_filenames,
    _integer,
    _number,
    _policy_summary,
    _safe_detail,
    _wait_for_run_detail,
)


DEFAULT_WORKFLOW_ID = "10200000-0000-0000-0000-000000000510"
DEFAULT_DEPLOYMENT_ID = "10200000-0000-0000-0000-000000000610"
DEFAULT_NODE_ID = "llm-request"
DEFAULT_ORGANIZATION_ID = "10200000-0000-0000-0000-000000000100"
DEFAULT_EMAIL = "admin@nodease.demo"
DEFAULT_PASSWORD_ENV = "NODEASE_DEMO_PASSWORD"
DEFAULT_REFRESH_EVERY_RUNS = 10
DEFAULT_MAX_PROVIDER_CALLS = 500
DEFAULT_DEADLINE_MINUTES = 120
VALIDATION_CANDIDATES_PER_COHORT = 2
VALIDATION_REPLAYS_PER_CANDIDATE = 5
CHECKPOINTS = frozenset({10, 20, 30, 40, 50})
EXPECTED_COHORT_COUNTS = {
    "routine_usage_guidance": 12,
    "account_access_request": 12,
    "finance_closing_approval": 13,
    "security_privacy_incident": 13,
}


@dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    expected_cohort_key: str
    query: str
    department: str
    requester_role: str
    locale: str
    rationale: str
    expected_knowledge: str


@dataclass
class RunObservation:
    sequence: int
    case: ExperimentCase
    run_id: str
    run_status: str
    node_status: str
    selected_model: str | None
    matched_cohort_id: str | None
    matched_cohort_key: str | None
    matched_cohort_label: str | None
    semantic_match_status: str | None
    semantic_similarity: float | None
    semantic_margin: float | None
    semantic_scores: list[dict[str, Any]]
    decision_source: str | None
    reason_code: str | None
    fallback_used: bool
    fallback_model: str | None
    policy_version: str | None
    judge_called: bool
    total_cost: float | None
    total_tokens: int | None
    duration_seconds: float | None
    schema_status: str | None
    downstream_status: str | None
    rag_document_count: int
    rag_chunk_count: int
    rag_source_filenames: list[str]
    error_code: str | None = None


@dataclass
class CheckpointSnapshot:
    sequence: int
    policy_status: str | None
    policy_version: str | None
    eligible_runs_since_last_refresh: int | None
    last_refresh_result: str | None
    budget_spent_usd: float | None
    cohort_states: list[dict[str, Any]]
    latest_validation_batch: dict[str, Any] | None
    wait_error: str | None = None


ROUTINE_USAGE_GUIDANCE = (
    ("사용자 대시보드의 카드 순서를 초기 상태로 되돌리는 메뉴가 어디인지 알려 주세요.", "제품운영", "일반 사용자"),
    ("지난달에 보관한 워크플로우를 다시 열어 편집하려면 어떤 화면으로 이동해야 하나요?", "사업기획", "워크플로우 편집자"),
    ("매주 월요일 아침에 받는 사용량 보고서의 발송 시간을 오후로 바꾸고 싶습니다.", "데이터전략", "리포트 구독자"),
    ("조직 화면에 표시되는 언어와 시간대를 서울 기준으로 변경하는 방법을 안내해 주세요.", "글로벌운영", "멤버"),
    ("기존 자동화 흐름을 복사해서 별도 테스트용 모듈로 저장하는 순서가 궁금합니다.", "서비스기획", "빌더"),
    ("내보내기를 눌러 만든 CSV 파일을 브라우저에서 다시 찾을 수 있는 위치가 있나요?", "고객성공", "분석 담당자"),
    ("사내 API를 처음 호출해 보려는데 요청 예제와 필드 설명 문서는 어디에서 확인합니까?", "개발지원", "주니어 개발자"),
    ("실수로 닫은 알림 배너를 다시 표시하고 이메일 알림만 끄는 설정을 찾고 있습니다.", "마케팅", "캠페인 담당자"),
    ("휴가 사용 내역 증명서를 PDF로 내려받아 제출하는 절차를 간단히 정리해 주세요.", "인사", "구성원"),
    ("목록 화면에서 담당자 열을 맨 앞으로 옮기고 그 정렬을 저장할 수 있나요?", "영업운영", "사용자"),
    ("삭제하지 않고 숨겨 둔 보고서를 보관함에서 원래 폴더로 복원하고 싶습니다.", "재무기획", "리포트 작성자"),
    ("반복해서 쓰는 고객 안내 문구를 새 템플릿으로 등록하는 경로만 알려 주세요.", "고객지원", "상담원"),
)

ACCOUNT_ACCESS_REQUEST = (
    ("오늘 퇴사 처리된 외주 인력의 VPN과 Git 저장소 권한을 어느 순서로 회수해야 합니까?", "플랫폼", "접근 권한 관리자"),
    ("신규 입사자가 SSO 로그인은 되지만 소속 팀 워크스페이스가 보이지 않는다고 합니다.", "인사운영", "온보딩 담당자"),
    ("휴대전화를 교체한 임원의 MFA 수단을 안전하게 재등록하려면 어떤 확인이 필요하나요?", "정보기술", "헬프데스크"),
    ("프로젝트가 끝난 협력사 계정을 이번 주까지만 읽기 전용으로 연장하고 싶습니다.", "조달", "협력사 관리자"),
    ("서비스 계정의 소유 부서를 바꾸면서 기존 토큰을 폐기하는 절차를 확인해 주세요.", "SRE", "서비스 오너"),
    ("결재 담당자가 휴가라서 이틀 동안만 대리 승인 권한을 부여해도 되는지 궁금합니다.", "총무", "업무 관리자"),
    ("팀을 옮긴 개발자가 예전 저장소를 계속 볼 수 있어 최소 권한 기준으로 정리하려 합니다.", "개발본부", "팀 리드"),
    ("공용 메일함 관리자를 다른 직원으로 변경할 때 감사 기록에 무엇을 남겨야 하나요?", "법무지원", "메일 관리자"),
    ("해외 지사 직원에게 국내 고객 문서 폴더 접근을 요청받았는데 승인 경로가 필요합니다.", "글로벌사업", "지사 운영자"),
    ("분기 권한 검토에서 90일 동안 사용하지 않은 관리자 역할을 발견했습니다.", "보안거버넌스", "권한 검토자"),
    ("운영 장애 대응을 위해 한 시간짜리 임시 관리자 권한을 신청하려면 누가 승인해야 합니까?", "클라우드운영", "당직 엔지니어"),
    ("조직 소유자가 퇴사 예정이라 워크스페이스 관리 권한을 후임에게 넘기려 합니다.", "경영지원", "조직 관리자"),
)

FINANCE_CLOSING_APPROVAL = (
    ("해외 공급사 지급 요청에 계약서와 검수 확인서는 있는데 환율 증빙이 빠졌습니다.", "재무", "지급 담당자"),
    ("월말 결산 전표의 작성자와 승인자가 같은 사람으로 지정된 건을 어떻게 바로잡아야 하나요?", "회계", "결산 책임자"),
    ("법인카드 영수증 금액과 회계 시스템에 입력된 금액이 3만 원 차이 납니다.", "재무운영", "경비 검토자"),
    ("고객 환불액이 부서 승인 한도를 넘어 추가 결재가 필요한지 확인해 주세요.", "고객정산", "환불 담당자"),
    ("이미 승인된 예산을 두 프로젝트 사이에서 옮길 때 필요한 근거와 승인 단계를 알려 주세요.", "FP&A", "예산 관리자"),
    ("거래처가 계좌 변경을 요청했는데 지급 직전에 어떤 독립 확인을 거쳐야 합니까?", "구매재무", "지급 승인자"),
    ("같은 세금계산서 번호로 두 건의 지급 요청이 올라와 중복 여부를 점검하고 있습니다.", "회계감사", "내부 감사자"),
    ("이번 달 매출 인식 시점이 계약서의 서비스 개시일과 달라 조정 분개가 필요합니다.", "재무회계", "매출 회계 담당자"),
    ("급여 마감 후 수당 누락이 발견됐을 때 추가 지급을 어느 결산 기간에 반영해야 하나요?", "급여운영", "급여 담당자"),
    ("예산 사용률이 90%를 넘은 부서가 새 소프트웨어 구매 승인을 요청했습니다.", "경영기획", "예산 통제자"),
    ("외화 송금 수수료가 청구서와 달라 지급 확정 전에 재검토하려고 합니다.", "자금", "자금 집행자"),
    ("사업자 정보가 변경돼 지난달 세금계산서를 정정 발행할 때 필요한 승인 기록이 궁금합니다.", "세무", "세무 담당자"),
    ("분기 마감일에 미결제 매입채무가 남았는데 증빙을 확인하고 이월하는 기준을 알려 주세요.", "회계", "결산 검토자"),
)

SECURITY_PRIVACY_INCIDENT = (
    ("고객 명단이 첨부된 파일을 직원이 외부 개인 메일로 잘못 전송했습니다. 즉시 조치가 필요합니다.", "개인정보보호", "사고 대응자"),
    ("관리자 계정이 낯선 국가에서 로그인한 뒤 여러 사용자의 권한을 변경한 흔적이 있습니다.", "보안관제", "SOC 분석가"),
    ("공개 저장소 커밋에서 운영 API 키로 보이는 문자열이 발견됐습니다.", "개발보안", "보안 엔지니어"),
    ("재무 담당자가 결제 승인 화면과 똑같이 생긴 링크에 회사 비밀번호를 입력했습니다.", "보안운영", "피싱 대응 담당자"),
    ("공유 드라이브의 인사 파일이 링크를 가진 외부인에게 열리는 상태로 확인됐습니다.", "인사보안", "개인정보 담당자"),
    ("운영 서버 여러 대에서 파일 확장자가 바뀌고 금전 요구 메시지가 표시되고 있습니다.", "인프라", "침해사고 책임자"),
    ("감사 로그 일부가 관리자 권한으로 삭제된 정황이 있어 보존 절차를 시작하려 합니다.", "감사", "포렌식 담당자"),
    ("업무와 무관한 계정이 고객 데이터베이스를 대량 조회한 기록을 발견했습니다.", "데이터보안", "DB 보안 관리자"),
    ("DLP 경보에서 주민등록번호가 포함된 문서가 외부 공유 서비스로 업로드됐다고 나옵니다.", "컴플라이언스", "DLP 운영자"),
    ("협력사 노트북의 악성코드 감염 이후 우리 VPN 접속 기록이 남아 있습니다.", "협력사보안", "서드파티 위험 담당자"),
    ("법정 보존 대상인 고객 기록에 삭제 요청이 들어와 바로 지워도 되는지 판단이 필요합니다.", "법무", "개인정보 법무 담당자"),
    ("외부 SaaS 업체가 침해 사고를 통보했고 우리 직원 계정 정보가 포함됐을 수 있다고 합니다.", "벤더관리", "위험 관리자"),
    ("일반 개발자 계정이 승인 없이 최고 관리자 역할을 얻어 운영 설정을 변경했습니다.", "클라우드보안", "IAM 대응자"),
)


CASE_POOLS = {
    "routine_usage_guidance": ROUTINE_USAGE_GUIDANCE,
    "account_access_request": ACCOUNT_ACCESS_REQUEST,
    "finance_closing_approval": FINANCE_CLOSING_APPROVAL,
    "security_privacy_incident": SECURITY_PRIVACY_INCIDENT,
}

COHORT_METADATA = {
    "routine_usage_guidance": ("일상적인 사용 경로와 설정을 묻는 저위험 요청", "사내 온보딩·사용 안내"),
    "account_access_request": ("계정 생성·회수·임시 권한과 승인 경계를 묻는 요청", "접근 권한·개발 온보딩 규칙"),
    "finance_closing_approval": ("금액, 결산, 지급, 증빙과 승인 분리를 다루는 요청", "재무 온보딩·예산 운영 문서"),
    "security_privacy_incident": ("침해, 개인정보 노출, 악성 행위에 즉시 대응해야 하는 요청", "개인정보·보안 사고 대응 문서"),
}

BLOCK_PLANS = (
    {"routine_usage_guidance": 3, "account_access_request": 3, "finance_closing_approval": 2, "security_privacy_incident": 2},
    {"routine_usage_guidance": 2, "account_access_request": 2, "finance_closing_approval": 3, "security_privacy_incident": 3},
    {"routine_usage_guidance": 3, "account_access_request": 2, "finance_closing_approval": 3, "security_privacy_incident": 2},
    {"routine_usage_guidance": 2, "account_access_request": 3, "finance_closing_approval": 2, "security_privacy_incident": 3},
    {"routine_usage_guidance": 2, "account_access_request": 2, "finance_closing_approval": 3, "security_privacy_incident": 3},
)


def build_experiment_cases(*, shuffle_seed: int = 270) -> list[ExperimentCase]:
    """각 10건 구간을 균형 있게 유지하면서 순서는 재현 가능하게 섞는다."""
    rng = random.Random(shuffle_seed)
    queues: dict[str, list[ExperimentCase]] = {}
    for cohort_key, rows in CASE_POOLS.items():
        rationale, expected_knowledge = COHORT_METADATA[cohort_key]
        prefix = {
            "routine_usage_guidance": "routine",
            "account_access_request": "access",
            "finance_closing_approval": "finance",
            "security_privacy_incident": "security",
        }[cohort_key]
        cases = [
            ExperimentCase(
                case_id=f"{prefix}-{index:02d}",
                expected_cohort_key=cohort_key,
                query=query,
                department=department,
                requester_role=requester_role,
                locale="ko-KR",
                rationale=rationale,
                expected_knowledge=expected_knowledge,
            )
            for index, (query, department, requester_role) in enumerate(rows, start=1)
        ]
        rng.shuffle(cases)
        queues[cohort_key] = cases

    ordered: list[ExperimentCase] = []
    for block_plan in BLOCK_PLANS:
        block: list[ExperimentCase] = []
        for cohort_key, count in block_plan.items():
            block.extend(queues[cohort_key][:count])
            del queues[cohort_key][:count]
        rng.shuffle(block)
        ordered.extend(block)
    return ordered


def build_run_payload(case: ExperimentCase) -> dict[str, Any]:
    return {
        "inputs": {
            "query": case.query,
            "department": case.department,
            "requesterRole": case.requester_role,
            "locale": case.locale,
        }
    }


def estimate_provider_call_ceiling(cases: Iterable[ExperimentCase]) -> int:
    count = len(list(cases))
    operational_calls = count * 2  # embedding + answer LLM
    replay_and_judge = (
        len(EXPECTED_COHORT_COUNTS)
        * VALIDATION_CANDIDATES_PER_COHORT
        * VALIDATION_REPLAYS_PER_CANDIDATE
        * 2  # candidate Replay + 품질 Judge
    )
    refresh_judges = math.ceil(count / DEFAULT_REFRESH_EVERY_RUNS)
    return operational_calls + replay_and_judge + refresh_judges + 20


class EnterpriseExperimentClient(RemoteExperimentClient):
    def run_deployment(self, deployment_id: str, case: ExperimentCase) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/api/v1/deployments/{deployment_id}/run",
            json=build_run_payload(case),
            headers={"X-Correlation-Id": f"enterprise-routing-{case.case_id}-{uuid.uuid4().hex[:8]}"},
            timeout=max(600, self.timeout_seconds),
        )
        if response.status_code != 200:
            raise RuntimeError(f"인증 배포 실행 실패: {_safe_detail(response)}")
        body = response.json()
        if not isinstance(body, dict) or not body.get("run_id"):
            raise RuntimeError("배포 실행 응답에 run_id가 없습니다.")
        return body

    def post_json(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}{path}", json=body, timeout=max(60, self.timeout_seconds)
        )
        if response.status_code != 200:
            raise RuntimeError(f"POST {path} 실패: {_safe_detail(response)}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"POST {path} 응답이 object가 아닙니다.")
        return payload


def _policy_path(workflow_id: str, node_id: str) -> str:
    return f"/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/model-routing/policy"


def _cohort_lookup(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    adaptive = policy.get("adaptive") if isinstance(policy.get("adaptive"), dict) else {}
    cohorts = adaptive.get("cohorts") if isinstance(adaptive.get("cohorts"), list) else []
    lookup: dict[str, dict[str, Any]] = {}
    for cohort in cohorts:
        if not isinstance(cohort, dict):
            continue
        for value in (cohort.get("id"), cohort.get("key")):
            if value:
                lookup[str(value)] = cohort
    return lookup


def _build_observation(
    *, sequence: int, case: ExperimentCase, run: dict[str, Any], node_id: str, policy: dict[str, Any]
) -> RunObservation:
    node_runs = run.get("node_runs") if isinstance(run.get("node_runs"), list) else []
    node_run = next(
        (item for item in node_runs if isinstance(item, dict) and item.get("node_id") == node_id),
        None,
    )
    if node_run is None:
        raise RuntimeError(f"run {run.get('id')}에 {node_id} node log가 없습니다.")
    outputs = node_run.get("outputs") if isinstance(node_run.get("outputs"), dict) else {}
    trace = node_run.get("trace_metadata") if isinstance(node_run.get("trace_metadata"), dict) else {}
    llm = trace.get("llm") if isinstance(trace.get("llm"), dict) else {}
    routing = llm.get("model_routing") if isinstance(llm.get("model_routing"), dict) else llm
    rag = trace.get("rag") if isinstance(trace.get("rag"), dict) else {}
    matched_id = str(routing.get("matched_cohort_id") or "") or None
    cohorts = _cohort_lookup(policy)
    matched = cohorts.get(matched_id or "", {})
    source_names = sorted(_find_source_filenames({"outputs": outputs, "trace": trace}))
    return RunObservation(
        sequence=sequence,
        case=case,
        run_id=str(run.get("id") or ""),
        run_status=str(run.get("status") or ""),
        node_status=str(node_run.get("status") or ""),
        selected_model=str(routing.get("selected_model") or llm.get("model") or outputs.get("model") or "") or None,
        matched_cohort_id=matched_id,
        matched_cohort_key=str(matched.get("key") or "") or None,
        matched_cohort_label=str(matched.get("label") or routing.get("semantic_candidate_label") or "") or None,
        semantic_match_status=str(routing.get("semantic_match_status") or "") or None,
        semantic_similarity=_number(routing.get("semantic_similarity")),
        semantic_margin=_number(routing.get("semantic_margin")),
        semantic_scores=[dict(item) for item in routing.get("semantic_cohort_scores", []) if isinstance(item, dict)],
        decision_source=str(routing.get("decision_source") or "") or None,
        reason_code=str(routing.get("reason_code") or "") or None,
        fallback_used=bool(routing.get("fallback_used")),
        fallback_model=str(routing.get("fallback_model") or routing.get("fallback_model_id") or "") or None,
        policy_version=str(routing.get("policy_version") or "") or None,
        judge_called=bool(routing.get("judge_called")),
        total_cost=_number(llm.get("total_cost") or outputs.get("cost")),
        total_tokens=_integer(llm.get("total_tokens") or (outputs.get("usage") or {}).get("total_tokens")),
        duration_seconds=_number(node_run.get("duration")),
        schema_status=str(llm.get("schema_status") or "") or None,
        downstream_status=str(llm.get("downstream_status") or trace.get("downstream_status") or "") or None,
        rag_document_count=len(rag.get("document_ids") or []),
        rag_chunk_count=int(rag.get("retrieved_chunk_count") or 0),
        rag_source_filenames=source_names,
    )


def _failed_observation(sequence: int, case: ExperimentCase, error_code: str) -> RunObservation:
    return RunObservation(
        sequence=sequence, case=case, run_id="", run_status="failed", node_status="unknown",
        selected_model=None, matched_cohort_id=None, matched_cohort_key=None,
        matched_cohort_label=None, semantic_match_status=None, semantic_similarity=None,
        semantic_margin=None, semantic_scores=[], decision_source=None, reason_code=None,
        fallback_used=False, fallback_model=None, policy_version=None, judge_called=False,
        total_cost=None, total_tokens=None, duration_seconds=None, schema_status=None,
        downstream_status=None, rag_document_count=0, rag_chunk_count=0,
        rag_source_filenames=[], error_code=error_code,
    )


def _snapshot(sequence: int, policy: dict[str, Any], wait_error: str | None = None) -> CheckpointSnapshot:
    summary = _policy_summary(policy)
    refresh = summary["refresh"]
    budget = summary["budget"]
    return CheckpointSnapshot(
        sequence=sequence,
        policy_status=str(policy.get("status") or "") or None,
        policy_version=str(policy.get("policy_version") or "") or None,
        eligible_runs_since_last_refresh=_integer(refresh.get("eligible_runs_since_last_refresh")),
        last_refresh_result=str(refresh.get("last_refresh_result") or "") or None,
        budget_spent_usd=_number(budget.get("spent_usd")),
        cohort_states=summary["cohorts"],
        latest_validation_batch=summary["latest_batch"],
        wait_error=wait_error,
    )


def _wait_for_checkpoint(
    client: EnterpriseExperimentClient,
    *, workflow_id: str, node_id: str, sequence: int, timeout_seconds: int,
) -> CheckpointSnapshot:
    time.sleep(8)
    deadline = time.monotonic() + timeout_seconds
    last_policy: dict[str, Any] = {}
    stable_signature: tuple[Any, ...] | None = None
    stable_count = 0
    while time.monotonic() < deadline:
        last_policy = client.get_json(_policy_path(workflow_id, node_id))
        summary = _policy_summary(last_policy)
        refresh = summary["refresh"]
        batch = summary["latest_batch"] or {}
        signature = (
            last_policy.get("status"),
            last_policy.get("policy_version"),
            refresh.get("eligible_runs_since_last_refresh"),
            refresh.get("last_refresh_result"),
            batch.get("status"),
            batch.get("completed_items"),
        )
        pending = str(last_policy.get("status") or "") == "refreshing" or str(batch.get("status") or "") in {
            "queued", "pending", "running", "refreshing"
        }
        counter = _integer(refresh.get("eligible_runs_since_last_refresh"))
        settled = not pending and (counter is None or counter < DEFAULT_REFRESH_EVERY_RUNS)
        stable_count = stable_count + 1 if signature == stable_signature else 1
        stable_signature = signature
        if settled and stable_count >= 2:
            return _snapshot(sequence, last_policy)
        time.sleep(3)
    return _snapshot(sequence, last_policy, "정책 갱신 완료 대기 시간 초과")


def _preflight(
    client: EnterpriseExperimentClient,
    *, workflow_id: str, deployment_id: str, node_id: str, cases: list[ExperimentCase], max_provider_calls: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    ceiling = estimate_provider_call_ceiling(cases)
    if ceiling > max_provider_calls:
        raise RuntimeError(f"provider 호출 상한 {ceiling}회가 제한 {max_provider_calls}회를 넘습니다.")
    run_info = client.get_json(f"/api/v1/deployments/{deployment_id}/run-info")
    if str(run_info.get("workflow_id")) != workflow_id:
        raise RuntimeError("배포가 기대한 workflow를 가리키지 않습니다.")
    serialized = json.dumps(run_info.get("input_schema") or {}, ensure_ascii=False)
    for field in ("query", "department", "requesterRole", "locale"):
        if field not in serialized:
            raise RuntimeError(f"배포 입력 schema에 {field} 필드가 없습니다.")
    policy = client.get_json(_policy_path(workflow_id, node_id))
    refresh = policy.get("refresh") if isinstance(policy.get("refresh"), dict) else {}
    actual_interval = refresh.get("refresh_every_runs")
    if policy.get("policy_id") and actual_interval != DEFAULT_REFRESH_EVERY_RUNS:
        raise RuntimeError(f"정책 점검 주기가 10회가 아닙니다: {actual_interval}")
    cohorts = _cohort_lookup(policy)
    existing_keys = {str(item.get("key")) for item in cohorts.values() if item.get("key")}
    if existing_keys and not set(EXPECTED_COHORT_COUNTS).issubset(existing_keys):
        raise RuntimeError(f"필수 입력군이 누락됐습니다: {set(EXPECTED_COHORT_COUNTS) - existing_keys}")
    return run_info, policy


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _format_number(value: float | int | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def build_markdown_report(
    observations: list[RunObservation], checkpoints: list[CheckpointSnapshot],
    *, metadata: dict[str, Any], final_previews: dict[str, Any],
) -> str:
    total = len(observations)
    success = sum(row.run_status.lower() == "success" for row in observations)
    exact = sum(row.matched_cohort_key == row.case.expected_cohort_key for row in observations)
    security_misses = sum(
        row.case.expected_cohort_key == "security_privacy_incident"
        and row.matched_cohort_key != "security_privacy_incident"
        for row in observations
    )
    models = Counter(row.selected_model or "확인 불가" for row in observations)
    runtime_judges = sum(row.judge_called for row in observations)
    auto_cohorts = {
        item.get("key") for snapshot in checkpoints for item in snapshot.cohort_states
        if item.get("source") == "auto" and item.get("key")
    }
    checkpoint_ok = len(checkpoints) == 5 and not any(row.wait_error for row in checkpoints)
    provider_call_ceiling = estimate_provider_call_ceiling(
        row.case for row in observations
    )
    final_cohort_states = checkpoints[-1].cohort_states if checkpoints else []
    matched_observation_count = sum(
        int(item.get("observation_count") or 0) for item in final_cohort_states
    )
    validation_batch_count = sum(
        1 for row in checkpoints if isinstance(row.latest_validation_batch, dict)
    )
    accuracy = (exact / total * 100) if total else 0
    passed = {
        "50건 실행 성공": success == 50,
        "입력군 정확도 90% 이상": accuracy >= 90,
        "보안 입력군 미매칭·오분류 0건": security_misses == 0,
        "10회 단위 정책 점검 완료": checkpoint_ok,
        "실행 중 Judge 호출 0건": runtime_judges == 0,
        "두 개 이상 모델 사용": len([key for key in models if key != "확인 불가"]) >= 2,
        "예상 밖 자동 입력군 없음": not auto_cohorts,
    }
    confusion: dict[str, Counter[str]] = defaultdict(Counter)
    per_cohort_models: dict[str, Counter[str]] = defaultdict(Counter)
    for row in observations:
        actual = row.matched_cohort_key or row.semantic_match_status or "default"
        confusion[row.case.expected_cohort_key][actual] += 1
        per_cohort_models[row.case.expected_cohort_key][row.selected_model or "확인 불가"] += 1

    lines = [
        "# 엔터프라이즈 통합 업무 요청 모델 라우팅 50회 실험 결과", "",
        "## 한눈에 보는 결론", "",
        f"- 성공 실행: **{success}/{total}건**",
        f"- 기대 입력군과 정확히 일치: **{exact}/{total}건 ({accuracy:.1f}%)**",
        f"- 보안·개인정보 입력군 미매칭·오분류: **{security_misses}건**",
        f"- DB 입력군에 연결된 운영 관찰: **{matched_observation_count}/{total}건**",
        f"- 생성된 후보 Replay 검증 batch: **{validation_batch_count}건**",
        f"- 실제 선택 모델 분포: **{dict(models)}**",
        f"- 실행 중 Judge 호출: **{runtime_judges}건**",
        f"- 예상하지 않은 자동 입력군: **{sorted(auto_cohorts) if auto_cohorts else '없음'}**", "",
        "이 실험은 배포 후 운영 실행만 사용한다. 각 요청의 순서는 고정 seed로 무작위화했고, "
        "각 10건 구간에 네 입력군이 최소 2건씩 들어가도록 균형을 맞췄다.", "",
        "## 합격 기준", "", "| 기준 | 결과 |", "| --- | --- |",
    ]
    lines.extend(f"| {name} | {'통과' if ok else '실패'} |" for name, ok in passed.items())
    if total and success == total and matched_observation_count < VALIDATION_REPLAYS_PER_CANDIDATE:
        lines.extend([
            "", "## 자동 진단", "",
            "실행과 운영 로그 수집은 성공했지만 입력군에 연결된 관찰이 후보 검증 최소값인 "
            f"**입력군당 {VALIDATION_REPLAYS_PER_CANDIDATE}건**에 도달하지 못했다. 따라서 정책 점검 task는 "
            "실행됐어도 후보 Replay batch를 만들 수 없었고, 활성 입력군 rule도 생성되지 않았다.", "",
            "이 상태에서 모든 요청은 `active_policy.default_model_id`를 사용한다. 즉 한 모델만 사용된 원인은 "
            "후보 모델 카탈로그 부족이 아니라 입력군 매칭 증거 부족이다.", "",
        ])
    lines.extend([
        "", "## 실험 환경", "",
        f"- 서버: `{metadata.get('base_url')}`",
        f"- workflow: `{metadata.get('workflow_id')}`",
        f"- deployment: `{metadata.get('deployment_id')}`",
        f"- LLM node: `{metadata.get('node_id')}`",
        f"- 정책 점검 주기: **{DEFAULT_REFRESH_EVERY_RUNS}회**",
        f"- 순서 seed: `{metadata.get('shuffle_seed')}`",
        f"- 시작: `{metadata.get('started_at')}`",
        f"- 종료: `{metadata.get('finished_at')}`",
        f"- 보수적 provider 호출 상한: **{provider_call_ceiling}회**", "",
        "## 정책 점검 결과", "",
        "| 실행 # | 상태 | 정책 버전 | 다음 점검까지 누적 | 갱신 결과 | 검증 비용 | 검증 batch | 대기 오류 |",
        "| ---: | --- | --- | ---: | --- | ---: | --- | --- |",
    ])
    for row in checkpoints:
        batch = row.latest_validation_batch or {}
        batch_text = str(batch.get("status") or "없음")
        if batch:
            batch_text += f" ({batch.get('completed_items', '-')}/{batch.get('total_items', '-')})"
        lines.append(
            f"| {row.sequence} | {row.policy_status or '-'} | {row.policy_version or '-'} | "
            f"{row.eligible_runs_since_last_refresh if row.eligible_runs_since_last_refresh is not None else '-'} | "
            f"{row.last_refresh_result or '-'} | {_format_number(row.budget_spent_usd, 6)} | {batch_text} | {row.wait_error or '-'} |"
        )
    lines.extend(["", "## 입력군별 실제 모델", "", "| 기대 입력군 | 모델 분포 |", "| --- | --- |"])
    for cohort_key in EXPECTED_COHORT_COUNTS:
        lines.append(f"| `{cohort_key}` | `{dict(per_cohort_models[cohort_key])}` |")
    lines.extend(["", "## 입력군 판정표", "", "| 기대 입력군 | 실제 판정 분포 |", "| --- | --- |"])
    for cohort_key in EXPECTED_COHORT_COUNTS:
        lines.append(f"| `{cohort_key}` | `{dict(confusion[cohort_key])}` |")
    lines.extend([
        "", "## 실행별 결과", "",
        "| # | 요청 ID | 기대 입력군 | 실제 입력군 | 판정 | 유사도 | margin | 모델 | 근거 | fallback | 비용 | 토큰 | 시간 | schema | RAG 문서/청크 | 상태 |",
        "| ---: | --- | --- | --- | --- | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- | --- |",
    ])
    for row in observations:
        lines.append(
            f"| {row.sequence} | {row.case.case_id} | {row.case.expected_cohort_key} | "
            f"{row.matched_cohort_key or row.matched_cohort_label or '-'} | {row.semantic_match_status or '-'} | "
            f"{_format_number(row.semantic_similarity)} | {_format_number(row.semantic_margin)} | {row.selected_model or '-'} | "
            f"{row.reason_code or row.decision_source or '-'} | {'예' if row.fallback_used else '아니오'} | "
            f"{_format_number(row.total_cost, 6)} | {row.total_tokens or '-'} | {_format_number(row.duration_seconds)} | "
            f"{row.schema_status or '-'} | {row.rag_document_count}/{row.rag_chunk_count} | {row.run_status} |"
        )
    lines.extend(["", "## 최종 정책 미리보기", "", "| 입력군 | 선택 모델 | 판정 출처 | 매칭 입력군 | 이유 |", "| --- | --- | --- | --- | --- |"])
    for key, preview in final_previews.items():
        matched = preview.get("matched_cohort") if isinstance(preview.get("matched_cohort"), dict) else {}
        lines.append(
            f"| `{key}` | {preview.get('selected_model_id', '-')} | {preview.get('decision_source', '-')} | "
            f"{matched.get('label') or matched.get('id') or '-'} | {preview.get('reason_code', '-')} |"
        )
    lines.extend(["", "## 사용한 합성 입력", "", "| # | ID | 기대 입력군 | 부서 | 역할 | 요청 | 분류 근거 | 기대 지식 영역 |", "| ---: | --- | --- | --- | --- | --- | --- | --- |"])
    for row in observations:
        case = row.case
        lines.append(
            f"| {row.sequence} | {case.case_id} | {case.expected_cohort_key} | {case.department} | "
            f"{case.requester_role} | {case.query.replace('|', '&#124;')} | {case.rationale} | {case.expected_knowledge} |"
        )
    lines.extend([
        "", "## 해석 시 주의사항", "",
        "- `matched`가 아니면 의미가 비슷해 보여도 검증된 입력군 rule이 적용된 것은 아니다.",
        "- 모델이 한 종류만 사용됐다면 50회 실행 성공과 별개로 적응형 모델 선택은 실패로 본다.",
        f"- 후보 모델 하나를 검증하려면 같은 입력군에 연결된 운영 관찰이 최소 {VALIDATION_REPLAYS_PER_CANDIDATE}건 필요하다.",
        "- 실행 중 `judge_called=true`가 있으면 runtime과 정책 갱신 경계가 깨진 것이다.",
        "- 이 실험은 합성 요청을 사용하며 실제 고객·직원 데이터나 credential 원문을 기록하지 않는다.", "",
    ])
    return "\n".join(lines)


def _preview_cases(client: EnterpriseExperimentClient, workflow_id: str, node_id: str) -> dict[str, Any]:
    previews: dict[str, Any] = {}
    path = f"/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/model-routing/preview"
    first_by_cohort = {case.expected_cohort_key: case for case in build_experiment_cases(shuffle_seed=270)}
    for cohort_key, case in first_by_cohort.items():
        try:
            previews[cohort_key] = client.post_json(path, build_run_payload(case))
        except RuntimeError as exc:
            previews[cohort_key] = {"error": str(exc)}
    return previews


def execute_experiment(args: argparse.Namespace) -> tuple[Path, Path]:
    if not args.confirm_live:
        raise RuntimeError("실제 호출은 --confirm-live를 명시해야 시작됩니다.")
    password = os.getenv(args.password_env)
    if not password:
        raise RuntimeError(f"{args.password_env} 환경변수가 필요합니다.")
    cases = build_experiment_cases(shuffle_seed=args.shuffle_seed)
    client = EnterpriseExperimentClient(
        base_url=args.base_url, organization_id=args.organization_id,
        email=args.email, password=password, timeout_seconds=args.timeout_seconds,
    )
    _preflight(
        client, workflow_id=args.workflow_id, deployment_id=args.deployment_id,
        node_id=args.node_id, cases=cases, max_provider_calls=args.max_provider_calls,
    )
    run_name = args.run_name or "enterprise-request-routing-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = args.output_dir / run_name
    state_path = output_dir / "state.json"
    json_path = output_dir / "result.json"
    report_path = output_dir / "report.md"
    started_at = datetime.now(timezone.utc)
    metadata = {
        "run_name": run_name, "base_url": args.base_url, "workflow_id": args.workflow_id,
        "deployment_id": args.deployment_id, "node_id": args.node_id,
        "organization_id": args.organization_id, "email": args.email,
        "shuffle_seed": args.shuffle_seed, "started_at": started_at.isoformat(),
        "finished_at": None, "provider_call_ceiling": estimate_provider_call_ceiling(cases),
    }
    observations: list[RunObservation] = []
    checkpoints: list[CheckpointSnapshot] = []
    if args.resume and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        metadata.update(state.get("metadata") or {})
        observations = [RunObservation(**{**row, "case": ExperimentCase(**row["case"])}) for row in state.get("observations", [])]
        checkpoints = [CheckpointSnapshot(**row) for row in state.get("checkpoints", [])]
    completed_ids = {row.case.case_id for row in observations}
    deadline = time.monotonic() + args.deadline_minutes * 60
    for sequence, case in enumerate(cases, start=1):
        if case.case_id in completed_ids:
            continue
        if time.monotonic() >= deadline:
            raise TimeoutError("실험 제한 시간을 넘기기 전에 실행을 중단했습니다.")
        try:
            response = client.run_deployment(args.deployment_id, case)
            run = _wait_for_run_detail(
                client, workflow_id=args.workflow_id, run_id=str(response["run_id"]),
                node_id=args.node_id, timeout_seconds=args.timeout_seconds,
            )
            if sequence == 1:
                time.sleep(5)
            policy = client.get_json(_policy_path(args.workflow_id, args.node_id))
            if sequence == 1:
                refresh = policy.get("refresh") if isinstance(policy.get("refresh"), dict) else {}
                if (
                    not policy.get("policy_id")
                    or refresh.get("refresh_every_runs") != DEFAULT_REFRESH_EVERY_RUNS
                ):
                    raise RuntimeError("첫 운영 실행 뒤 10회 주기의 persisted policy가 생성되지 않았습니다.")
            observation = _build_observation(
                sequence=sequence, case=case, run=run, node_id=args.node_id, policy=policy,
            )
        except Exception as exc:
            observation = _failed_observation(sequence, case, type(exc).__name__)
        observations.append(observation)
        if sequence in CHECKPOINTS:
            checkpoints.append(
                _wait_for_checkpoint(
                    client, workflow_id=args.workflow_id, node_id=args.node_id,
                    sequence=sequence, timeout_seconds=args.policy_settle_timeout_seconds,
                )
            )
        _write_json(state_path, {
            "metadata": metadata,
            "observations": [asdict(item) for item in observations],
            "checkpoints": [asdict(item) for item in checkpoints],
        })
        print(
            f"[{sequence:02d}/50] {case.case_id}: "
            f"{observation.matched_cohort_key or observation.semantic_match_status or 'default'} "
            f"-> {observation.selected_model or 'unknown'} ({observation.run_status})",
            flush=True,
        )
    final_previews = _preview_cases(client, args.workflow_id, args.node_id)
    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
    payload = {
        "metadata": metadata,
        "observations": [asdict(item) for item in observations],
        "checkpoints": [asdict(item) for item in checkpoints],
        "final_previews": final_previews,
    }
    _write_json(json_path, payload)
    _write_json(state_path, payload)
    report_path.write_text(
        build_markdown_report(
            observations, checkpoints, metadata=metadata, final_previews=final_previews,
        ),
        encoding="utf-8",
    )
    return json_path, report_path


def render_existing(state_file: Path) -> Path:
    payload = json.loads(state_file.read_text(encoding="utf-8"))
    observations = [RunObservation(**{**row, "case": ExperimentCase(**row["case"])}) for row in payload.get("observations", [])]
    checkpoints = [CheckpointSnapshot(**row) for row in payload.get("checkpoints", [])]
    report_path = state_file.with_name("report.md")
    report_path.write_text(
        build_markdown_report(
            observations, checkpoints, metadata=payload.get("metadata") or {},
            final_previews=payload.get("final_previews") or {},
        ),
        encoding="utf-8",
    )
    return report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("preflight", "execute", "render"), default="preflight")
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--workflow-id", default=DEFAULT_WORKFLOW_ID)
    parser.add_argument("--deployment-id", default=DEFAULT_DEPLOYMENT_ID)
    parser.add_argument("--node-id", default=DEFAULT_NODE_ID)
    parser.add_argument("--organization-id", default=DEFAULT_ORGANIZATION_ID)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    parser.add_argument("--shuffle-seed", type=int, default=270)
    parser.add_argument("--timeout-seconds", type=int, default=240)
    parser.add_argument("--policy-settle-timeout-seconds", type=int, default=300)
    parser.add_argument("--max-provider-calls", type=int, default=DEFAULT_MAX_PROVIDER_CALLS)
    parser.add_argument("--deadline-minutes", type=int, default=DEFAULT_DEADLINE_MINUTES)
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-name")
    parser.add_argument("--state-file", type=Path)
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "reports" / "model-routing" / "enterprise-request-routing",
    )
    args = parser.parse_args()
    try:
        if args.mode == "render":
            if args.state_file is None:
                parser.error("render 모드에는 --state-file이 필요합니다.")
            print(f"markdown_report={render_existing(args.state_file)}")
            return 0
        password = os.getenv(args.password_env)
        if not password:
            parser.error(f"{args.password_env} 환경변수가 필요합니다.")
        client = EnterpriseExperimentClient(
            base_url=args.base_url, organization_id=args.organization_id,
            email=args.email, password=password, timeout_seconds=args.timeout_seconds,
        )
        cases = build_experiment_cases(shuffle_seed=args.shuffle_seed)
        if args.mode == "preflight":
            run_info, policy = _preflight(
                client, workflow_id=args.workflow_id, deployment_id=args.deployment_id,
                node_id=args.node_id, cases=cases, max_provider_calls=args.max_provider_calls,
            )
            print(f"deployment={run_info.get('name')} v{run_info.get('version')}")
            print(f"policy_status={policy.get('status')}")
            print(f"provider_call_ceiling={estimate_provider_call_ceiling(cases)}")
            return 0
        json_path, report_path = execute_experiment(args)
        print(f"json_report={json_path}")
        print(f"markdown_report={report_path}")
        return 0
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
