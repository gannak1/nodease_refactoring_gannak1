"""팀별 온보딩 RAG와 적응형 모델 라우팅을 원격 API로 검증한다.

이 스크립트는 서버 DB에 직접 접근하지 않는다. 로그인, 인증 배포 실행, 실행 로그
조회, 정책 조회 API만 사용하므로 로컬과 원격 서버에서 같은 절차로 재현할 수 있다.
실제 provider 호출은 ``--confirm-live``를 명시한 경우에만 수행한다.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORKFLOW_ID = "10200000-0000-0000-0000-000000000508"
DEFAULT_DEPLOYMENT_ID = "10200000-0000-0000-0000-000000000608"
DEFAULT_NODE_ID = "llm-answer"
DEFAULT_ORGANIZATION_ID = "10200000-0000-0000-0000-000000000100"
DEFAULT_EMAIL = "jimin.park@nodease.demo"
DEFAULT_PASSWORD_ENV = "NODEASE_DEMO_PASSWORD"
DEFAULT_MAX_PROVIDER_CALLS = 500
DEFAULT_DEADLINE_MINUTES = 120
POLICY_SETTLE_CHECKPOINTS = frozenset({16, 36, 56, 76})


@dataclass(frozen=True)
class ExperimentCase:
    case_id: str
    phase: str
    expected_cohort_key: str
    expected_source_filename: str
    question: str
    rationale: str


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
    semantic_scores: list[dict[str, Any]]
    fallback_used: bool
    policy_version: str | None
    total_cost: float | None
    total_tokens: int | None
    duration_seconds: float | None
    rag_source_filenames: list[str]
    expected_rag_source_found: bool
    policy_status: str | None
    cohort_states: list[dict[str, Any]]
    latest_validation_batch: dict[str, Any] | None
    error_code: str | None = None


SALES_SEED_QUESTIONS = (
    "영업팀 신입이 CRM 계정을 신청하고 첫 로그인에서 담당 고객만 보이는지 확인하는 순서를 알려 주세요.",
    "고객 데이터 취급 교육을 마친 뒤 CRM 최소 권한을 받으려면 어떤 내용을 신청서에 적어야 하나요?",
    "새 영업 담당자가 배정 전 고객 레코드를 열지 않고 제품 학습을 시작하는 올바른 절차가 궁금합니다.",
    "비표준 할인 조건이 들어간 견적 초안을 만들었을 때 고객에게 보내기 전 누구의 승인을 받아야 하나요?",
    "공동 담당 고객의 미팅 메모를 CRM에 남길 때 허용되는 범위와 금지되는 행동을 정리해 주세요.",
    "영업 첫 주 금요일까지 완료해야 하는 교육, CRM, 견적 실습과 리뷰 항목을 알려 주세요.",
)

FINANCE_EMERGENCE_QUESTIONS = (
    "재무팀 월말 결산 담당자가 회계 시스템 조회 권한을 신청할 때 업무 범위와 법인 정보를 어떻게 적어야 하나요?",
    "재무팀 월말 결산 담당자는 마감 3일 전부터 마감 후 3일까지 어떤 순서로 잔액을 점검하고 기록하나요?",
    "재무팀 월말 결산에서 지급 증빙을 올린 뒤 작성자, 승인자, 실행자가 각각 무엇을 확인하나요?",
    "재무팀 월말 결산 전표의 작성 권한과 최종 승인 권한을 한 사람이 동시에 가져도 되나요?",
    "재무팀 월말 결산을 처음 맡은 신입은 조회와 가상 입력 뒤 언제 실제 처리 권한을 승인받나요?",
    "재무팀 월말 결산 마감일에 승인 전표 반영 후 잔액 차이가 발견되면 어떤 기록을 남겨야 하나요?",
    "재무팀 월말 결산 지급 실습에서 증빙 검토와 중복 지급 확인을 어떤 순서로 진행하나요?",
    "재무팀 월말 결산 자료를 개인 메일로 옮기지 않고 허용된 위치에서 처리하는 기준은 무엇인가요?",
    "재무팀 월말 결산에서 조회, 전표 작성, 검토, 승인, 지급 실행 권한은 어떻게 분리되나요?",
    "재무팀 월말 결산 온보딩 완료로 인정받으려면 교육과 역할 분리 검토 중 무엇을 제출해야 하나요?",
)

FINANCE_VALIDATION_QUESTIONS = (
    "재무팀 월말 결산 담당자가 승인된 전표와 증빙 금액이 다를 때 어떤 순서로 재검토해야 하나요?",
    "재무팀 월말 결산 중 지급 승인자와 실행자의 역할이 겹친 것을 발견하면 어떻게 조정해야 하나요?",
)

COMMON_DECLINE_QUESTIONS = (
    "입사 첫날 8시 50분부터 16시 30분까지 진행하는 공통 일정과 완료 기준을 순서대로 알려 주세요.",
    "회사 SSO 계정을 활성화한 뒤 다중 인증과 복구 절차는 어떤 장비에서 설정해야 하나요?",
    "개인 이메일을 업무 계정 복구 수단으로 쓰면 안 되는 이유와 인증 오류 시 요청 경로를 알려 주세요.",
    "필수 보안 교육 중 계정 보안, 정보 분류, 피싱 대응, AI 사용에서 각각 지켜야 할 행동은 무엇인가요?",
    "사내 메신저 공통 공지 채널과 소속 팀 채널에 참여하는 순서를 알려 주세요.",
    "첫날이 끝났는데 보안 교육이나 인사 정보 확인이 남았다면 팀 시스템 권한 신청을 진행해도 되나요?",
    "업무 장비에 문제가 생겼을 때 자가 분해하지 않고 지원 요청에 포함해야 할 정보를 알려 주세요.",
    "휴가를 신청할 때 팀 일정 확인부터 인사 시스템 승인 상태 확인까지 절차를 설명해 주세요.",
    "고객 데이터나 API 키를 AI 프롬프트와 메신저에 남기지 말라는 공통 보안 원칙을 정리해 주세요.",
    "공통 온보딩 완료로 인정되는 SSO, 교육, 인사 정보, 메신저, 팀 리드 리뷰 조건을 알려 주세요.",
    "인사 시스템의 연락처와 급여 정보를 수정할 때 이력을 남기는 올바른 방법은 무엇인가요?",
    "의심스러운 링크나 첨부 파일을 발견했을 때 어떤 신고 경로로 전달해야 하나요?",
    "팀별 업무 권한을 요청할 때 소속 팀 리드에게 업무 목적과 최소 권한을 어떻게 설명해야 하나요?",
    "직무 교육 지원을 신청하기 전에 팀 리드와 합의해야 하는 내용이 무엇인지 알려 주세요.",
    "첫날 장비, SSO, 보안 교육, 메신저 중 미완료 항목이 있으면 누구에게 진행 상태를 공유하나요?",
    "공개, 내부, 제한 정보의 취급 방식을 구분하는 교육은 어떻게 완료 여부를 확인하나요?",
    "업무 계정의 비밀번호와 복구 코드를 문서에 적지 않고 안전하게 관리하는 원칙을 알려 주세요.",
    "공통 온보딩 문서만 완료하면 운영 배포나 고객 데이터 접근 권한도 자동으로 생기나요?",
    "원격 근무 기준을 확인할 위치와 최신 안내를 다시 확인해야 하는 이유를 알려 주세요.",
    "계정 인증 오류를 문의할 때 Identity 지원에 전달해도 되는 안전한 정보가 무엇인가요?",
)

PLATFORM_DECLINE_QUESTIONS = (
    "플랫폼개발팀 신입이 화요일에 Git 저장소와 이슈 트래커 접근을 신청하는 절차를 알려 주세요.",
    "로컬 개발환경 구성을 완료했다고 인정받으려면 런타임, 샘플 서비스, 테스트를 어떻게 확인하나요?",
    "개발 장비에서 credential과 환경 비밀값을 파일에 직접 기록하지 않는 설정 원칙을 알려 주세요.",
    "Git 접근 신청서에 업무 목적을 적고 팀 리드와 관리자가 확인하는 단계를 설명해 주세요.",
    "첫 로그인 뒤 허용된 프로젝트보다 더 많은 저장소가 보이면 어떤 조치를 해야 하나요?",
    "신입 개발자에게 기본으로 주는 저장소 권한과 기본으로 주지 않는 관리자 권한을 구분해 주세요.",
    "VPN 신청에 필요한 보안 교육과 관리 장비 확인 조건을 알려 주세요.",
    "운영 로그와 상태를 읽기 전용으로 조회하려면 팀 리드와 DevOps에게 어떤 승인을 받아야 하나요?",
    "운영 배포 권한을 신청하기 전에 배포 파이프라인 실습과 업무 목적을 어떻게 증명해야 하나요?",
    "다른 구성원의 토큰이나 공유 계정으로 운영 환경에 접속하면 안 되는 이유를 알려 주세요.",
    "플랫폼개발팀 월요일부터 금요일까지 핵심 일정과 각 산출물을 요약해 주세요.",
    "샘플 서비스는 어떤 데이터와 환경에서 실행해야 하며 운영 데이터를 쓰면 안 되는 이유가 무엇인가요?",
    "환경 구성 오류를 지원팀에 요청하기 전에 표준 체크리스트로 무엇을 재현해야 하나요?",
    "운영 조회 권한과 실제 운영 변경 권한이 왜 분리되어 있는지 온보딩 기준으로 설명해 주세요.",
    "배포 권한 요청에 필요한 환경과 기간을 적은 뒤 어떤 순서로 검토가 진행되나요?",
    "신입에게 우선 운영 조회 권한만 주고 배포 권한을 나중에 활성화하는 절차를 알려 주세요.",
    "플랫폼개발팀 첫 주 완료 기준에서 Git, 개발환경, 운영 접근, 회고 항목을 알려 주세요.",
    "비운영 환경에서 배포 파이프라인을 실습한 기록은 어느 요일 산출물에 해당하나요?",
    "팀 업무에 필요한 제한된 기여 권한과 조직 전체 관리자 권한의 차이를 설명해 주세요.",
    "역할이 바뀌거나 운영 배포 권한이 만료될 때 접근 권한을 다시 검토해야 하는 이유가 무엇인가요?",
)

SALES_RETURN_QUESTIONS = (
    "영업팀 신입이 담당 고객을 배정받은 뒤 CRM에서 처음 확인할 최소 범위를 알려 주세요.",
    "영업팀 신입이 CRM 견적에 할인 예외를 넣을 때 고객 전송 전 어떤 승인을 받아야 하나요?",
    "영업팀 신입이 CRM 활동 기록에 고객 개인정보 대신 남겨야 할 안전한 업무 요약 범위를 알려 주세요.",
    "영업팀 신입의 담당 고객이 바뀐 뒤 CRM 접근이 남아 있으면 누구에게 회수를 요청해야 하나요?",
    "영업팀 신입의 첫 주 리뷰에서 CRM 최소 권한과 연습 견적을 어떻게 확인하나요?",
)


COMMON_POST_VALIDATION_QUESTIONS = (
    "신규 입사자가 공통 온보딩 첫 주에 SSO, 다중 인증, 보안 교육을 어떤 순서로 끝내야 하는지 알려 주세요.",
    "업무용 노트북을 분실했을 때 계정 잠금과 보안 신고를 어디에 어떤 정보와 함께 요청해야 하나요?",
    "피싱으로 의심되는 메일의 링크를 열지 않은 상태에서 신고하고 삭제하는 절차를 정리해 주세요.",
    "팀 채널에 합류하기 전에 완료해야 하는 공통 교육과 인사 시스템 확인 항목을 알려 주세요.",
    "개인 기기에서 회사 파일을 내려받지 않아야 하는 이유와 원격 근무 시 지켜야 할 기준을 설명해 주세요.",
    "입사자 연락처 정보가 바뀌었을 때 인사 시스템에서 수정하고 확인해야 할 절차가 무엇인가요?",
    "SSO 로그인에 실패할 때 비밀번호나 복구 코드를 공유하지 않고 지원팀에 전달할 수 있는 정보는 무엇인가요?",
    "사내 AI 도구에 고객 정보나 비밀값을 넣지 않기 위해 공통 온보딩에서 안내하는 원칙을 알려 주세요.",
    "첫 주 공통 온보딩의 완료 여부를 팀 리드에게 공유할 때 어떤 항목을 점검해야 하나요?",
    "휴가를 신청하기 전에 팀 일정과 인사 시스템에서 확인해야 할 순서를 알려 주세요.",
)


PLATFORM_POST_VALIDATION_QUESTIONS = (
    "플랫폼개발팀 신입이 Git 저장소 권한을 받은 뒤 샘플 서비스를 안전한 개발 환경에서 검증하는 절차를 알려 주세요.",
    "운영 로그 읽기 권한을 신청할 때 업무 목적과 필요한 기간을 어떻게 적고 누가 검토하는지 알려 주세요.",
    "로컬 개발환경에 API 키를 파일로 남기지 않고 표준 방식으로 설정하는 기준을 설명해 주세요.",
    "새 개발자가 배포 파이프라인 실습을 하기 전에 비운영 환경과 운영 환경을 어떻게 구분해야 하나요?",
    "Git 프로젝트 접근이 필요 이상으로 열려 보일 때 어떤 증거를 남기고 누구에게 권한 조정을 요청해야 하나요?",
    "플랫폼개발팀 첫 주에 완료해야 하는 런타임 설치, 테스트 실행, 회고 기록 항목을 정리해 주세요.",
    "운영 변경 권한 없이 장애 로그를 확인해야 할 때 읽기 전용 접근을 요청하는 절차를 알려 주세요.",
    "공유 계정이나 다른 팀원의 토큰을 사용하지 않고 개발 도구 권한을 신청하는 원칙을 설명해 주세요.",
    "역할 변경으로 배포 권한이 만료될 때 저장소와 운영 접근을 함께 재검토해야 하는 이유를 알려 주세요.",
)


def _cases_for_questions(
    questions: Iterable[str],
    *,
    phase: str,
    cohort_key: str,
    source_filename: str,
    rationale: str,
    prefix: str,
) -> list[ExperimentCase]:
    return [
        ExperimentCase(
            case_id=f"{prefix}-{index:02d}",
            phase=phase,
            expected_cohort_key=cohort_key,
            expected_source_filename=source_filename,
            question=question,
            rationale=rationale,
        )
        for index, question in enumerate(questions, start=1)
    ]


def build_experiment_cases(*, shuffle_seed: int = 270) -> list[ExperimentCase]:
    """트렌드 상태 전이를 만들되 각 phase 내부 순서는 재현 가능하게 섞는다."""
    sales_seed = _cases_for_questions(
        SALES_SEED_QUESTIONS,
        phase="sales_seed",
        cohort_key="sales_enablement",
        source_filename="sales_team_onboarding_v2.pdf",
        rationale="초기 영업 입력군에 관찰값을 쌓아 이후 휴면과 재활성화를 판정한다.",
        prefix="sales-seed",
    )
    finance = _cases_for_questions(
        FINANCE_EMERGENCE_QUESTIONS,
        phase="finance_emergence",
        cohort_key="finance_operations",
        source_filename="finance_team_onboarding_v3.pdf",
        rationale="초안에 없는 재무 문의가 두 점검 구간에 반복되어 자동 입력군으로 발견되는지 본다.",
        prefix="finance-new",
    )
    finance_validation = _cases_for_questions(
        FINANCE_VALIDATION_QUESTIONS,
        phase="finance_validation",
        cohort_key="finance_operations",
        source_filename="finance_team_onboarding_v3.pdf",
        rationale="검증 완료 뒤 동일한 재무 트렌드가 더 저렴한 검증 모델로 라우팅되는지 확인한다.",
        prefix="finance-verify",
    )
    common = _cases_for_questions(
        COMMON_DECLINE_QUESTIONS[:19],
        phase="sales_decline",
        cohort_key="common_security",
        source_filename="company_common_onboarding.pdf",
        rationale="기존 공통 입력군을 유지하면서 영업 입력 비중을 최근 40건에서 낮춘다.",
        prefix="common",
    )
    platform = _cases_for_questions(
        PLATFORM_DECLINE_QUESTIONS[:19],
        phase="sales_decline",
        cohort_key="platform_access",
        source_filename="platform_team_onboarding_v4.pdf",
        rationale="플랫폼 입력군을 유지하면서 영업 입력군의 연속 저비중 구간을 만든다.",
        prefix="platform",
    )
    sales_return = _cases_for_questions(
        SALES_RETURN_QUESTIONS,
        phase="sales_return",
        cohort_key="sales_enablement",
        source_filename="sales_team_onboarding_v2.pdf",
        rationale="최근 40건 중 영업 비중을 10% 이상으로 회복시켜 휴면 입력군의 재활성화를 본다.",
        prefix="sales-return",
    )
    common_post_validation = _cases_for_questions(
        COMMON_POST_VALIDATION_QUESTIONS,
        phase="post_validation",
        cohort_key="common_security",
        source_filename="company_common_onboarding.pdf",
        rationale="검증 뒤에도 공통 보안·온보딩 문의가 같은 입력군과 RAG 근거로 안정적으로 처리되는지 확인한다.",
        prefix="common-post",
    )
    platform_post_validation = _cases_for_questions(
        PLATFORM_POST_VALIDATION_QUESTIONS,
        phase="post_validation",
        cohort_key="platform_access",
        source_filename="platform_team_onboarding_v4.pdf",
        rationale="검증 뒤에도 플랫폼 접근·개발환경 문의가 같은 입력군과 RAG 근거로 안정적으로 처리되는지 확인한다.",
        prefix="platform-post",
    )

    rng = random.Random(shuffle_seed)
    rng.shuffle(finance)
    decline = common + platform
    rng.shuffle(decline)
    post_validation = common_post_validation + platform_post_validation
    rng.shuffle(post_validation)
    return sales_seed + finance + finance_validation + decline + sales_return + post_validation


def estimate_provider_call_ceiling(
    cases: Iterable[ExperimentCase],
    *,
    max_cohorts: int,
    candidate_models_per_cohort: int,
    replays_per_candidate: int,
    refresh_every_runs: int = 5,
) -> int:
    """실행 전에 보수적인 호출 상한을 계산한다.

    운영 1건은 embedding 1회와 답변 LLM 1회로 계산한다. 후보 검증은 후보
    replay와 judge를 각각 1회로 잡고, 정책 갱신 judge 및 여유분을 추가한다.
    """
    count = len(list(cases))
    operational = count * 2
    validation = max_cohorts * candidate_models_per_cohort * replays_per_candidate * 2
    refresh_judges = math.ceil(count / max(1, refresh_every_runs))
    return operational + validation + refresh_judges + 10


def _safe_detail(response: Any) -> str:
    try:
        body = response.json()
    except Exception:
        return f"HTTP {response.status_code}"
    detail = body.get("detail") if isinstance(body, dict) else None
    if isinstance(detail, str) and len(detail) <= 160:
        return f"HTTP {response.status_code}: {detail}"
    return f"HTTP {response.status_code}"


class RemoteExperimentClient:
    def __init__(
        self,
        *,
        base_url: str,
        organization_id: str,
        email: str,
        password: str,
        timeout_seconds: int,
    ) -> None:
        import requests

        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()
        response = self.session.post(
            f"{self.base_url}/api/v1/auth/login",
            json={"email": email, "password": password},
            timeout=30,
        )
        if response.status_code != 200:
            raise RuntimeError(f"데모 계정 로그인 실패: {_safe_detail(response)}")
        self.session.headers.update({"X-Organization-Id": organization_id})

    def get_json(self, path: str, *, timeout: int | None = None) -> dict[str, Any]:
        response = self.session.get(
            f"{self.base_url}{path}",
            timeout=timeout or self.timeout_seconds,
        )
        if response.status_code != 200:
            raise RuntimeError(f"GET {path} 실패: {_safe_detail(response)}")
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError(f"GET {path} 응답이 object가 아닙니다.")
        return body

    def run_deployment(self, deployment_id: str, question: str) -> dict[str, Any]:
        response = self.session.post(
            f"{self.base_url}/api/v1/deployments/{deployment_id}/run",
            json={"inputs": {"question": question}},
            timeout=max(600, self.timeout_seconds),
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"인증 배포 실행 실패: {_safe_detail(response)}"
            )
        body = response.json()
        if not isinstance(body, dict) or not body.get("run_id"):
            raise RuntimeError("배포 실행 응답에 run_id가 없습니다.")
        return body


def _policy_summary(policy: dict[str, Any]) -> dict[str, Any]:
    adaptive = policy.get("adaptive")
    adaptive = adaptive if isinstance(adaptive, dict) else {}
    refresh = policy.get("refresh")
    refresh = refresh if isinstance(refresh, dict) else {}
    cohorts = adaptive.get("cohorts")
    cohorts = cohorts if isinstance(cohorts, list) else []
    return {
        "status": policy.get("status"),
        "policy_id": policy.get("policy_id"),
        "policy_version": policy.get("policy_version"),
        "refresh": {
            "refresh_every_runs": refresh.get("refresh_every_runs"),
            "eligible_runs_since_last_refresh": refresh.get(
                "eligible_runs_since_last_refresh"
            ),
            "last_refresh_result": refresh.get("last_refresh_result"),
        },
        "budget": {
            "limit_usd": adaptive.get("validation_budget_usd"),
            "spent_usd": adaptive.get("spent_usd"),
            "reserved_usd": adaptive.get("reserved_usd"),
            "remaining_usd": adaptive.get("remaining_usd"),
        },
        "cohorts": [
            {
                "id": item.get("id"),
                "key": item.get("key"),
                "label": item.get("label"),
                "source": item.get("source"),
                "status": item.get("status"),
                "required": item.get("required"),
                "observation_count": item.get("observation_count"),
                "review_window_count": item.get("review_window_count"),
                "traffic_share": item.get("traffic_share"),
                "validated_model_id": item.get("validated_model_id"),
            }
            for item in cohorts
            if isinstance(item, dict)
        ],
        "latest_batch": adaptive.get("latest_batch")
        if isinstance(adaptive.get("latest_batch"), dict)
        else None,
    }


def _find_source_filenames(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"filename", "source_filename"} and isinstance(item, str):
                if item.lower().endswith((".pdf", ".md", ".txt")):
                    found.add(Path(item).name)
            else:
                found.update(_find_source_filenames(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_find_source_filenames(item))
    elif isinstance(value, str):
        for match in re.finditer(
            r"(?<![\w.-])([\w.-]+\.(?:pdf|md|txt))(?![\w.-])",
            value,
            flags=re.IGNORECASE,
        ):
            found.add(Path(match.group(1)).name)
    return found


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer(value: Any) -> int | None:
    number = _number(value)
    return int(number) if number is not None else None


def _cohort_lookup(policy: dict[str, Any]) -> dict[str, dict[str, Any]]:
    adaptive = policy.get("adaptive")
    adaptive = adaptive if isinstance(adaptive, dict) else {}
    cohorts = adaptive.get("cohorts")
    cohorts = cohorts if isinstance(cohorts, list) else []
    lookup: dict[str, dict[str, Any]] = {}
    for item in cohorts:
        if not isinstance(item, dict):
            continue
        for value in (item.get("id"), item.get("key")):
            key = str(value or "").strip()
            if key:
                lookup[key] = item
    return lookup


def _wait_for_run_detail(
    client: RemoteExperimentClient,
    *,
    workflow_id: str,
    run_id: str,
    node_id: str,
    timeout_seconds: int,
    poll_interval_seconds: float = 1.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    last_status = "unknown"
    while time.monotonic() < deadline:
        try:
            run = client.get_json(
                f"/api/v1/workflows/{workflow_id}/runs/{run_id}", timeout=30
            )
            node_runs = run.get("node_runs")
            node_runs = node_runs if isinstance(node_runs, list) else []
            node_run = next(
                (
                    item
                    for item in node_runs
                    if isinstance(item, dict) and item.get("node_id") == node_id
                ),
                None,
            )
            run_status = str(run.get("status") or "").lower()
            node_status = str((node_run or {}).get("status") or "").lower()
            last_status = f"run={run_status or 'unknown'}, node={node_status or 'missing'}"
            terminal = {"success", "failed", "cancelled", "canceled", "skipped"}
            if node_run is not None and node_status in terminal and run_status in terminal:
                return run
            if run_status in {"failed", "cancelled", "canceled"} and node_run is None:
                return run
        except RuntimeError as exc:
            last_error = exc
        time.sleep(max(0.0, poll_interval_seconds))
    detail = str(last_error) if last_error is not None else last_status
    raise TimeoutError(f"run detail 최종 상태 대기 시간 초과: {detail}")


def _wait_for_policy_settle(
    client: RemoteExperimentClient,
    *,
    workflow_id: str,
    node_id: str,
    timeout_seconds: int,
    poll_interval_seconds: float = 2.0,
    minimum_wait_seconds: float = 5.0,
) -> dict[str, Any]:
    """비동기 refresh와 Replay 검증이 끝난 정책을 반환한다."""
    if minimum_wait_seconds > 0:
        time.sleep(minimum_wait_seconds)
    deadline = time.monotonic() + max(1, timeout_seconds)
    path = f"/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/model-routing/policy"
    pending_batch_states = {"queued", "pending", "running", "refreshing"}
    while time.monotonic() < deadline:
        policy = client.get_json(path)
        adaptive = policy.get("adaptive")
        adaptive = adaptive if isinstance(adaptive, dict) else {}
        latest_batch = adaptive.get("latest_batch")
        latest_batch = latest_batch if isinstance(latest_batch, dict) else {}
        policy_status = str(policy.get("status") or "")
        batch_status = str(latest_batch.get("status") or "")
        settled_policy = policy_status in {"active", "pending_review", "failed"}
        completed_collecting = (
            policy_status == "collecting"
            and bool(latest_batch)
            and batch_status not in pending_batch_states
        )
        if batch_status not in pending_batch_states and (
            settled_policy or completed_collecting
        ):
            return policy
        time.sleep(max(0.0, poll_interval_seconds))
    raise TimeoutError("모델 라우팅 정책 검증 완료를 기다리다 시간 초과했습니다.")


def _rehydrate_observation(
    client: RemoteExperimentClient,
    *,
    observation: RunObservation,
    workflow_id: str,
    node_id: str,
    timeout_seconds: int,
) -> RunObservation:
    """비동기 로그 저장 전에 기록된 checkpoint를 provider 재호출 없이 보정한다."""
    run = _wait_for_run_detail(
        client,
        workflow_id=workflow_id,
        run_id=observation.run_id,
        node_id=node_id,
        timeout_seconds=timeout_seconds,
    )
    policy_snapshot = {
        "status": observation.policy_status,
        "adaptive": {
            "cohorts": observation.cohort_states,
            "latest_batch": observation.latest_validation_batch,
        },
    }
    return _build_observation(
        sequence=observation.sequence,
        case=observation.case,
        run=run,
        node_id=node_id,
        policy=policy_snapshot,
    )


def _build_observation(
    *,
    sequence: int,
    case: ExperimentCase,
    run: dict[str, Any],
    node_id: str,
    policy: dict[str, Any],
) -> RunObservation:
    node_runs = run.get("node_runs")
    node_runs = node_runs if isinstance(node_runs, list) else []
    node_run = next(
        (
            item
            for item in node_runs
            if isinstance(item, dict) and item.get("node_id") == node_id
        ),
        None,
    )
    if node_run is None:
        raise RuntimeError(f"run {run.get('id')}에 {node_id} node log가 없습니다.")
    outputs = node_run.get("outputs")
    outputs = outputs if isinstance(outputs, dict) else {}
    trace = node_run.get("trace_metadata")
    trace = trace if isinstance(trace, dict) else {}
    llm = trace.get("llm")
    llm = llm if isinstance(llm, dict) else {}
    matched_id = str(llm.get("matched_cohort_id") or "") or None
    cohorts = _cohort_lookup(policy)
    matched = cohorts.get(matched_id or "", {})
    source_filenames = sorted(_find_source_filenames({"outputs": outputs, "trace": trace}))
    return RunObservation(
        sequence=sequence,
        case=case,
        run_id=str(run.get("id") or ""),
        run_status=str(run.get("status") or ""),
        node_status=str(node_run.get("status") or ""),
        selected_model=str(llm.get("model") or outputs.get("model") or "") or None,
        matched_cohort_id=matched_id,
        matched_cohort_key=str(matched.get("key") or "") or None,
        matched_cohort_label=str(matched.get("label") or "") or None,
        semantic_match_status=str(llm.get("semantic_match_status") or "") or None,
        semantic_similarity=_number(llm.get("semantic_similarity")),
        semantic_scores=[
            dict(item)
            for item in llm.get("semantic_cohort_scores", [])
            if isinstance(item, dict)
        ],
        fallback_used=bool(llm.get("fallback_used")),
        policy_version=str(llm.get("policy_version") or "") or None,
        total_cost=_number(llm.get("total_cost")),
        total_tokens=_integer(llm.get("total_tokens")),
        duration_seconds=_number(node_run.get("duration")),
        rag_source_filenames=source_filenames,
        expected_rag_source_found=case.expected_source_filename in source_filenames,
        policy_status=str(policy.get("status") or "") or None,
        cohort_states=_policy_summary(policy)["cohorts"],
        latest_validation_batch=_policy_summary(policy)["latest_batch"],
    )


def _failed_observation(
    *,
    sequence: int,
    case: ExperimentCase,
    policy: dict[str, Any],
) -> RunObservation:
    """배포 API 실패를 safe summary로 남기고 다음 합성 입력을 계속한다."""
    summary = _policy_summary(policy)
    return RunObservation(
        sequence=sequence,
        case=case,
        run_id="",
        run_status="failed",
        node_status="unknown",
        selected_model=None,
        matched_cohort_id=None,
        matched_cohort_key=None,
        matched_cohort_label=None,
        semantic_match_status=None,
        semantic_similarity=None,
        semantic_scores=[],
        fallback_used=False,
        policy_version=None,
        total_cost=None,
        total_tokens=None,
        duration_seconds=None,
        rag_source_filenames=[],
        expected_rag_source_found=False,
        policy_status=str(policy.get("status") or "") or None,
        cohort_states=summary["cohorts"],
        latest_validation_batch=summary["latest_batch"],
        error_code="deployment_run_failed",
    )


def _write_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _observation_from_dict(value: dict[str, Any]) -> RunObservation:
    return RunObservation(
        **{
            **value,
            "case": ExperimentCase(**value["case"]),
        }
    )


def build_markdown_report(
    observations: list[RunObservation],
    *,
    metadata: dict[str, Any],
) -> str:
    total = len(observations)
    succeeded = sum(row.run_status.upper() == "SUCCESS" for row in observations)
    exact_key_matches = sum(
        row.matched_cohort_key == row.case.expected_cohort_key for row in observations
    )
    routed_matches = sum(
        row.semantic_match_status == "matched" for row in observations
    )
    rag_hits = sum(row.expected_rag_source_found for row in observations)
    models = Counter(row.selected_model or "확인 불가" for row in observations)
    discovered = {
        cohort.get("key"): cohort
        for row in observations
        for cohort in row.cohort_states
        if cohort.get("source") == "auto"
    }
    sales_states = [
        cohort.get("status")
        for row in observations
        for cohort in row.cohort_states
        if cohort.get("key") == "sales_enablement"
    ]
    sales_dormant = "dormant" in sales_states
    sales_reactivated = sales_dormant and bool(sales_states) and sales_states[-1] == "active"

    lines = [
        "# 팀별 온보딩 적응형 모델 라우팅 실험 결과",
        "",
        "## 한눈에 보는 결론",
        "",
        f"- 실행 성공: **{succeeded}/{total}건**",
        f"- 사전 정의 입력군 key와 정확히 일치: **{exact_key_matches}/{total}건**",
        f"- 검증된 입력군 rule로 실제 라우팅: **{routed_matches}/{total}건**",
        f"- 기대한 RAG 문서 확인: **{rag_hits}/{total}건**",
        f"- 자동 발견 입력군 수: **{len(discovered)}개**",
        f"- 영업 입력군 휴면 확인: **{'예' if sales_dormant else '아니오'}**",
        f"- 영업 입력군 재활성화 확인: **{'예' if sales_reactivated else '아니오'}**",
        f"- 사용 모델 분포: **{dict(models)}**",
        "",
        "이 실험은 입력 원문이나 답변 원문을 DB 보고서에서 복제하지 않고, 합성 질문의 ID와 "
        "라우팅·RAG·비용 요약만 기록한다. 실제 비밀값과 credential은 기록하지 않는다.",
        "",
        "## 실험 환경",
        "",
        f"- 대상 서버: `{metadata.get('base_url')}`",
        f"- workflow: `{metadata.get('workflow_id')}`",
        f"- deployment: `{metadata.get('deployment_id')}`",
        f"- LLM node: `{metadata.get('node_id')}`",
        f"- 실행 계정: `{metadata.get('email')}` (비밀번호는 환경변수에서만 읽음)",
        f"- 데이터 순서 seed: `{metadata.get('shuffle_seed')}`",
        f"- 실제 시작: `{metadata.get('started_at')}`",
        f"- 실제 종료: `{metadata.get('finished_at')}`",
        "",
        "## 실험이 확인하는 흐름",
        "",
            "1. 1~6회 영업 문의로 기존 영업 입력군의 초기 관찰을 만든다.",
            "2. 7~16회 재무 문의로 초안에 없던 트렌드가 자동 입력군으로 발견되는지 본다.",
            "3. 19~56회는 공통·플랫폼 문의만 보내 영업 입력군 비중을 낮춰 휴면 판정을 확인한다.",
            "4. 57~61회에 영업 문의를 다시 보내 최근 입력 비중이 회복되면 재활성화되는지 본다.",
            "5. 62~80회는 공통·플랫폼 문의를 추가해 검증된 입력군 rule과 RAG 근거가 안정적으로 유지되는지 본다.",
            "6. 각 실행에서 실제 선택 모델, 입력군 유사도, fallback, RAG 출처, 정책 버전을 확인한다.",
        "",
        "## 실행별 결과",
        "",
        "| # | phase | 질문 ID | 예상 입력군 | 실제 입력군 | 모델 | 유사도 | RAG 출처 | 비용 | 상태 |",
        "| ---: | --- | --- | --- | --- | --- | ---: | --- | ---: | --- |",
    ]
    for row in observations:
        lines.append(
            "| {sequence} | {phase} | {case_id} | {expected} | {actual} | {model} | "
            "{similarity} | {sources} | {cost} | {status} |".format(
                sequence=row.sequence,
                phase=row.case.phase,
                case_id=row.case.case_id,
                expected=row.case.expected_cohort_key,
                actual=row.matched_cohort_key or row.semantic_match_status or "기본 모델",
                model=row.selected_model or "-",
                similarity=(
                    f"{row.semantic_similarity:.3f}"
                    if row.semantic_similarity is not None
                    else "-"
                ),
                sources=", ".join(row.rag_source_filenames) or "확인 불가",
                cost=(f"${row.total_cost:.6f}" if row.total_cost is not None else "-"),
                status=row.run_status,
            )
        )
    lines.extend(
        [
            "",
            "## 입력 데이터와 RAG 근거",
            "",
            "| 질문 ID | 실제 질문 | 기대 문서 | 기대 이유 |",
            "| --- | --- | --- | --- |",
        ]
    )
    for row in observations:
        lines.append(
            f"| {row.case.case_id} | {row.case.question.replace('|', '&#124;')} | "
            f"{row.case.expected_source_filename} | {row.case.rationale} |"
        )
    lines.extend(
        [
            "",
            "## 정책 및 입력군 변화",
            "",
            "| 실행 # | 정책 버전 | 정책 상태 | 입력군 상태 | 검증 batch |",
            "| ---: | --- | --- | --- | --- |",
        ]
    )
    previous_signature = None
    for row in observations:
        signature = json.dumps(
            {"version": row.policy_version, "cohorts": row.cohort_states},
            ensure_ascii=False,
            sort_keys=True,
        )
        if signature == previous_signature:
            continue
        previous_signature = signature
        cohort_text = ", ".join(
            f"{item.get('key')}={item.get('status')}"
            for item in row.cohort_states
        )
        batch = row.latest_validation_batch or {}
        batch_text = (
            f"{batch.get('status')} ({batch.get('completed_items')}/{batch.get('total_items')})"
            if batch
            else "없음"
        )
        lines.append(
            f"| {row.sequence} | {row.policy_version or '-'} | {row.policy_status or '-'} | "
            f"{cohort_text or '-'} | {batch_text} |"
        )
    lines.extend(
        [
            "",
            "## 판정 기준과 한계",
            "",
            "- 자동 입력군은 최근 40개 관찰 중 서로 다른 입력 5개가 최소 두 점검 구간에 나타나야 제안된다.",
            "- 비고정 입력군은 최근 비중 5% 이하가 세 번 연속 확인되면 휴면, 이후 10% 이상이면 재활성화된다.",
            "- 모델 검증은 월간 $3 한도 안에서 Replay와 Judge를 실행한다. 한도나 사용 가능한 credential이 부족하면 후보가 늘지 않을 수 있다.",
            "- 기대 RAG 문서가 로그에 없으면 답변이 틀렸다는 뜻으로 단정하지 않는다. 현재 trace가 출처 파일명을 제공했는지를 별도 확인해야 한다.",
            "- 이 결과는 실행 당시 서버 코드, 배포 snapshot, 모델 catalog와 credential 권한에 종속된다.",
            "",
        ]
    )
    return "\n".join(lines)


def _preflight(
    client: RemoteExperimentClient,
    *,
    workflow_id: str,
    deployment_id: str,
    node_id: str,
    cases: list[ExperimentCase],
    max_provider_calls: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    estimate = estimate_provider_call_ceiling(
        cases,
        max_cohorts=6,
        candidate_models_per_cohort=4,
        replays_per_candidate=2,
    )
    if estimate > max_provider_calls:
        raise RuntimeError(
            f"보수적 provider 호출 상한 {estimate}회가 제한 {max_provider_calls}회를 넘습니다."
        )
    run_info = client.get_json(f"/api/v1/deployments/{deployment_id}/run-info")
    if str(run_info.get("workflow_id")) != workflow_id:
        raise RuntimeError("배포가 기대한 workflow를 가리키지 않습니다.")
    input_schema = run_info.get("input_schema")
    input_schema = input_schema if isinstance(input_schema, dict) else {}
    serialized = json.dumps(input_schema, ensure_ascii=False)
    if "question" not in serialized:
        raise RuntimeError("배포 입력 schema에 question 필드가 없습니다.")
    policy = client.get_json(
        f"/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/model-routing/policy"
    )
    adaptive = policy.get("adaptive")
    adaptive = adaptive if isinstance(adaptive, dict) else {}
    cohort_keys = {
        str(item.get("key"))
        for item in adaptive.get("cohorts", [])
        if isinstance(item, dict)
    }
    required = {"common_security", "platform_access", "sales_enablement"}
    if not required.issubset(cohort_keys):
        raise RuntimeError(
            "시드 입력군 3개가 보이지 않습니다. demo seed와 draft cohort 저장을 확인하세요."
        )
    return run_info, policy


def execute_experiment(args: argparse.Namespace) -> tuple[Path, Path]:
    if not args.confirm_live:
        raise RuntimeError("실제 호출은 --confirm-live를 명시해야 시작됩니다.")
    password = os.getenv(args.password_env)
    if not password:
        raise RuntimeError(f"{args.password_env} 환경변수가 필요합니다.")
    cases = build_experiment_cases(shuffle_seed=args.shuffle_seed)
    client = RemoteExperimentClient(
        base_url=args.base_url,
        organization_id=args.organization_id,
        email=args.email,
        password=password,
        timeout_seconds=args.timeout_seconds,
    )
    _preflight(
        client,
        workflow_id=args.workflow_id,
        deployment_id=args.deployment_id,
        node_id=args.node_id,
        cases=cases,
        max_provider_calls=args.max_provider_calls,
    )

    run_name = args.run_name or (
        "team-onboarding-adaptive-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    output_dir = args.output_dir / run_name
    state_path = output_dir / "state.json"
    json_path = output_dir / "result.json"
    markdown_path = output_dir / "report.md"
    started_at = datetime.now(timezone.utc)
    metadata = {
        "run_name": run_name,
        "base_url": args.base_url,
        "workflow_id": args.workflow_id,
        "deployment_id": args.deployment_id,
        "node_id": args.node_id,
        "organization_id": args.organization_id,
        "email": args.email,
        "shuffle_seed": args.shuffle_seed,
        "started_at": started_at.isoformat(),
        "finished_at": None,
        "max_provider_calls": args.max_provider_calls,
        "deadline_minutes": args.deadline_minutes,
    }
    observations: list[RunObservation] = []
    if args.resume and state_path.exists():
        state = json.loads(state_path.read_text(encoding="utf-8"))
        metadata.update(state.get("metadata") or {})
        observations = [
            _observation_from_dict(item) for item in state.get("observations", [])
        ]
        started_at = datetime.fromisoformat(metadata["started_at"])
        repaired_observations: list[RunObservation] = []
        for observation in observations:
            if observation.node_status.lower() in {
                "success",
                "failed",
                "cancelled",
                "canceled",
                "skipped",
            } and observation.selected_model:
                repaired_observations.append(observation)
                continue
            repaired_observations.append(
                _rehydrate_observation(
                    client,
                    observation=observation,
                    workflow_id=args.workflow_id,
                    node_id=args.node_id,
                    timeout_seconds=args.timeout_seconds,
                )
            )
        observations = repaired_observations
        _write_state(
            state_path,
            {
                "metadata": metadata,
                "observations": [asdict(item) for item in observations],
            },
        )

    completed_ids = {row.case.case_id for row in observations}
    deadline = time.monotonic() + args.deadline_minutes * 60
    for sequence, case in enumerate(cases, start=1):
        if case.case_id in completed_ids:
            continue
        if time.monotonic() >= deadline:
            raise TimeoutError("실험 제한 시간을 넘기기 전에 실행을 중단했습니다.")
        try:
            response = client.run_deployment(args.deployment_id, case.question)
        except RuntimeError:
            policy = client.get_json(
                f"/api/v1/workflows/{args.workflow_id}/llm-nodes/{args.node_id}/model-routing/policy"
            )
            observation = _failed_observation(
                sequence=sequence,
                case=case,
                policy=policy,
            )
            observations.append(observation)
            _write_state(
                state_path,
                {
                    "metadata": metadata,
                    "observations": [asdict(item) for item in observations],
                },
            )
            print(
                f"[{sequence:02d}/{len(cases)}] {case.case_id}: deployment run failed",
                flush=True,
            )
            continue
        run_id = str(response["run_id"])
        run = _wait_for_run_detail(
            client,
            workflow_id=args.workflow_id,
            run_id=run_id,
            node_id=args.node_id,
            timeout_seconds=args.timeout_seconds,
        )
        if sequence % 5 == 0:
            time.sleep(args.refresh_settle_seconds)
        policy = client.get_json(
            f"/api/v1/workflows/{args.workflow_id}/llm-nodes/{args.node_id}/model-routing/policy"
        )
        if sequence in POLICY_SETTLE_CHECKPOINTS:
            policy = _wait_for_policy_settle(
                client,
                workflow_id=args.workflow_id,
                node_id=args.node_id,
                timeout_seconds=args.policy_settle_timeout_seconds,
            )
        observation = _build_observation(
            sequence=sequence,
            case=case,
            run=run,
            node_id=args.node_id,
            policy=policy,
        )
        observations.append(observation)
        _write_state(
            state_path,
            {
                "metadata": metadata,
                "observations": [asdict(item) for item in observations],
            },
        )
        print(
            f"[{sequence:02d}/{len(cases)}] {case.case_id}: "
            f"{observation.matched_cohort_key or observation.semantic_match_status or 'default'} "
            f"-> {observation.selected_model or 'unknown'}",
            flush=True,
        )

    if observations:
        final_policy = _wait_for_policy_settle(
            client,
            workflow_id=args.workflow_id,
            node_id=args.node_id,
            timeout_seconds=args.policy_settle_timeout_seconds,
            minimum_wait_seconds=args.post_run_settle_seconds,
        )
        final_adaptive = final_policy.get("adaptive")
        final_adaptive = final_adaptive if isinstance(final_adaptive, dict) else {}
        observations[-1].policy_status = str(final_policy.get("status") or "") or None
        observations[-1].cohort_states = list(final_adaptive.get("cohorts") or [])
        final_batch = final_adaptive.get("latest_batch")
        observations[-1].latest_validation_batch = (
            final_batch if isinstance(final_batch, dict) else None
        )

    metadata["finished_at"] = datetime.now(timezone.utc).isoformat()
    payload = {
        "metadata": metadata,
        "observations": [asdict(item) for item in observations],
    }
    _write_state(json_path, payload)
    markdown_path.write_text(
        build_markdown_report(observations, metadata=metadata), encoding="utf-8"
    )
    _write_state(state_path, payload)
    return json_path, markdown_path


def render_existing(path: Path) -> Path:
    payload = json.loads(path.read_text(encoding="utf-8"))
    observations = [
        _observation_from_dict(item) for item in payload.get("observations", [])
    ]
    target = path.parent / "report.md"
    target.write_text(
        build_markdown_report(observations, metadata=payload.get("metadata") or {}),
        encoding="utf-8",
    )
    return target


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
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--refresh-settle-seconds", type=float, default=3.0)
    parser.add_argument("--policy-settle-timeout-seconds", type=int, default=300)
    parser.add_argument("--post-run-settle-seconds", type=float, default=15.0)
    parser.add_argument("--max-provider-calls", type=int, default=DEFAULT_MAX_PROVIDER_CALLS)
    parser.add_argument("--deadline-minutes", type=int, default=DEFAULT_DEADLINE_MINUTES)
    parser.add_argument("--confirm-live", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--run-name")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "model-routing" / "team-onboarding",
    )
    parser.add_argument("--state-file", type=Path)
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
        client = RemoteExperimentClient(
            base_url=args.base_url,
            organization_id=args.organization_id,
            email=args.email,
            password=password,
            timeout_seconds=args.timeout_seconds,
        )
        cases = build_experiment_cases(shuffle_seed=args.shuffle_seed)
        if args.mode == "preflight":
            run_info, policy = _preflight(
                client,
                workflow_id=args.workflow_id,
                deployment_id=args.deployment_id,
                node_id=args.node_id,
                cases=cases,
                max_provider_calls=args.max_provider_calls,
            )
            print(f"deployment={run_info.get('name')} v{run_info.get('version')}")
            print(f"policy_status={policy.get('status')}")
            print(
                "provider_call_ceiling="
                + str(
                    estimate_provider_call_ceiling(
                        cases,
                        max_cohorts=6,
                        candidate_models_per_cohort=4,
                        replays_per_candidate=2,
                    )
                )
            )
            return 0
        json_path, markdown_path = execute_experiment(args)
        print(f"json_report={json_path}")
        print(f"markdown_report={markdown_path}")
        return 0
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
