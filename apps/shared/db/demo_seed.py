"""Final demo database seed helpers.

이 모듈은 최종 시연용 로컬 DB 상태를 재현하기 위한 전용 seed다.
기본 실행은 upsert로 동작하고, reset 실행은 demo seed가 관리하는 row만
삭제/복원한다.
"""

from __future__ import annotations

import copy
import gzip
import json
import os
import re
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.agent_builder import (
    AgentBuilderDraft,
    AgentBuilderRequest,
    AgentBuilderSession,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.audit_log import (
    ActorType,
    AuditCategory,
    AuditLog,
    AuditStatus,
)
from apps.shared.db.models.knowledge import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
    KnowledgeDocumentIngestionJob,
    KnowledgeIngestionOutbox,
    SourceType,
)
from apps.shared.db.models.llm import (
    LLMCredential,
    LLMModel,
    LLMProvider,
    LLMRelCredentialModel,
    LLMUsageLog,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    ORGANIZATION_MEMBERSHIP_INVITED,
    ORGANIZATION_MEMBERSHIP_REMOVED,
    ORGANIZATION_MEMBERSHIP_SUSPENDED,
    OrganizationMembership,
)
from apps.shared.db.models.permission_request import (
    PERMISSION_REQUEST_APPROVED,
    REQUESTED_PERMISSION_APP_CREATE,
    PermissionRequest,
)
from apps.shared.db.models.team import (
    Team,
    TeamAuditPermission,
    TeamKnowledgeCollectionPermission,
    TeamKnowledgePermission,
    TeamLLMPermission,
    TeamMembership,
    TeamWorkflowPermission,
    UserKnowledgePermission,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.user_app_creation_permission import (
    UserAppCreationPermission,
)
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    RunTriggerMode,
    TracePayload,
    TracePayloadAccessEvent,
    WorkflowNodeRun,
    WorkflowRun,
)
from apps.shared.domain.app_auth_secret import (
    APP_AUTH_SECRET_VERIFIER_VERSION,
    app_auth_secret_verifier,
    app_auth_secret_verifier_state_is_valid,
)
from apps.shared.services.password_hashing import hash_password
from sqlalchemy import inspect as sa_inspect
from sqlalchemy import or_, text
from sqlalchemy.orm import Session

DEMO_SEED_VERSION = "final-demo-2026-07"
DEMO_PASSWORD = "123123"
DEMO_CHAT_MODEL = "gpt-5.4"
DEMO_CHAT_MINI_MODEL = "gpt-5.4-mini"
DEMO_MODEL_ROUTER_BASE_MODEL = "gpt-5-mini"
DEMO_MODEL_ROUTER_FALLBACK_MODEL = "gpt-4.1"
DEMO_MODEL_ROUTER_CHEAP_MODEL = "gpt-4o-mini"
DEMO_MODEL_ROUTER_BALANCED_MODEL = "gpt-4.1-mini"
# 이 RAG 실험은 낮은 비용 후보를 검증하는 흐름이 목적이다. Responses API의
# reasoning token이 900 token 출력 예산을 먼저 소진하지 않는 안정적인 기준 모델로
# 시작해, 후보 품질 gate와 입력군 routing 자체를 검증한다.
DEMO_ONBOARDING_ROUTER_MODEL = "gpt-4.1"
DEMO_EMBEDDING_MODEL = "text-embedding-3-small"
DEMO_EMBEDDING_DIMENSION = 1536
ENTERPRISE_REQUEST_ROUTING_NAME = "엔터프라이즈 통합 업무 요청 처리"
ENTERPRISE_REQUEST_ROUTING_DESCRIPTION = (
    "사내 문서 RAG와 난이도 기반 자동 모델 라우팅으로 다양한 업무 요청을 처리하는 workflow"
)
DEMO_REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_LEGAL_DOCS_LABOR_DIR = DEMO_REPO_ROOT / "local" / "legal-docs-labor"
DEMO_INTERNAL_DOCS_DIR = (
    DEMO_REPO_ROOT / "local" / "demo-scenario-2026-07-08" / "internal-docs"
)
DEMO_ONBOARDING_PDF_DIR = DEMO_REPO_ROOT / "demodata"
DEMO_KNOWLEDGE_FIXTURE_PATH = (
    DEMO_REPO_ROOT / "apps" / "shared" / "db" / "fixtures" / "demo_knowledge_chunks.jsonl.gz"
)
DEMO_REGENERATE_KNOWLEDGE_FIXTURE_ENV = "NODEASE_DEMO_REGENERATE_KNOWLEDGE_FIXTURE"
DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL_ENV = (
    "NODEASE_DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL"
)
# Docker gateway 컨테이너 경로를 우선하고, 로컬 venv 실행에서는 repo 루트의
# gitignore된 uploads/ 아래로 폴백한다 (docs/demo/local-demo-db.md 실행 방식 참고).
DEMO_UPLOAD_DIRS = (
    Path("/app/uploads/demo_seed"),
    DEMO_REPO_ROOT / "uploads" / "demo_seed",
)


def _uuid(suffix: int) -> uuid.UUID:
    return uuid.UUID(f"10200000-0000-0000-0000-{suffix:012d}")


ORG_ID = _uuid(100)

USER_IDS = {
    "admin": _uuid(1),
    "rookie": _uuid(2),
    "author": _uuid(3),
    "tester_manager": _uuid(4),
    "tester_builder": _uuid(5),
    "tester_member": _uuid(6),
    "invited": _uuid(7),
    "suspended": _uuid(8),
    "removed": _uuid(9),
    "developer": _uuid(10),
    "planning": _uuid(11),
    "onboarding_platform_rookie": _uuid(12),
    "onboarding_sales_rookie": _uuid(13),
    "onboarding_people_manager": _uuid(14),
}

TEAM_IDS = {
    "platform_admin": _uuid(200),
    "ai_builder_onboarding": _uuid(201),
    "customer_support_ops": _uuid(202),
    "hr_knowledge_users": _uuid(203),
    "finance_restricted": _uuid(204),
    "tester_builder": _uuid(205),
    "tester_member": _uuid(206),
    "department_development": _uuid(207),
    "department_planning": _uuid(208),
    "onboarding_platform": _uuid(209),
    "onboarding_sales": _uuid(210),
    "onboarding_people": _uuid(211),
    "onboarding_finance": _uuid(212),
}

KB_IDS = {
    "hr": _uuid(300),
    "finance": _uuid(301),
    "legal_labor_standards": _uuid(320),
    "legal_equal_employment": _uuid(321),
    "legal_equal_employment_enforcement_decree": _uuid(322),
    "legal_privacy": _uuid(323),
    "legal_occupational_safety": _uuid(324),
    "legal_retirement_benefits": _uuid(325),
    "legal_fair_hiring": _uuid(326),
    "internal_onboarding": _uuid(327),
    "internal_leave_attendance": _uuid(328),
    "internal_benefits": _uuid(329),
    "internal_privacy_hr_records": _uuid(330),
    "internal_budget_alert_runbook": _uuid(331),
    "internal_cost_optimization_playbook": _uuid(332),
    "internal_developer_onboarding_rules": _uuid(333),
    "internal_developer_commit_convention": _uuid(334),
    "internal_developer_compensation_band": _uuid(335),
    "internal_compensation_access_policy": _uuid(336),
    "internal_planning_onboarding_guide": _uuid(337),
    "onboarding_company_common": _uuid(338),
    "onboarding_platform": _uuid(339),
    "onboarding_sales": _uuid(340),
    "onboarding_finance": _uuid(341),
    "hr_welfare": _uuid(342),
}

COLLECTION_IDS = {
    "legal_public": _uuid(360),
    "internal_onboarding": _uuid(361),
    "team_onboarding_access_control": _uuid(362),
    "hr_policies": _uuid(363),
}

# author의 승인된 App 생성 권한 신청 이력 (ADR-0016).
# rookie 신청은 라이브 데모(시나리오 1)의 제출 흐름과 충돌하므로 seed하지 않는다.
PERMISSION_REQUEST_IDS = {
    "author_app_create": _uuid(900),
}

APP_CREATION_PERMISSION_IDS = {
    "author": _uuid(910),
}

# 데모 조직 공용 LLM credential. 스키마상 credential은 user_id 소유가 필수이고
# organization_id는 nullable scope라(data_model.md), 라이브 생성 경로와 같게
# org manager(admin) 소유 + 데모 조직 scope로 만든다. apiKey는 실제 키가 아닌
# 명백한 더미 값이다 — 비용 탭/요약 카드 집계용이며 provider 호출은 실패한다.
# LEGACY_DEMO_LLM_CREDENTIAL_ID(_uuid(700))는 과거 seed 정리 대상이라 재사용하지 않는다.
LLM_CREDENTIAL_IDS = {
    "demo_openai": _uuid(920),
}

CREDENTIAL_MODEL_REL_IDS = {
    DEMO_CHAT_MODEL: _uuid(921),
    DEMO_CHAT_MINI_MODEL: _uuid(922),
    DEMO_EMBEDDING_MODEL: _uuid(923),
    DEMO_MODEL_ROUTER_BASE_MODEL: _uuid(924),
    DEMO_MODEL_ROUTER_FALLBACK_MODEL: _uuid(925),
    DEMO_MODEL_ROUTER_CHEAP_MODEL: _uuid(926),
    DEMO_MODEL_ROUTER_BALANCED_MODEL: _uuid(927),
    DEMO_ONBOARDING_ROUTER_MODEL: _uuid(929),
}

TEAM_LLM_PERMISSION_IDS = {
    "platform_admin": _uuid(930),
    "ai_builder_onboarding": _uuid(931),
    "hr_knowledge_users": _uuid(932),
    "customer_support_ops": _uuid(933),
    "department_development": _uuid(934),
    "department_planning": _uuid(935),
    "onboarding_platform": _uuid(936),
    "onboarding_sales": _uuid(937),
    "onboarding_people": _uuid(938),
    "onboarding_finance": _uuid(939),
}

USER_LLM_PERMISSION_IDS = {
    "author": _uuid(940),
    "tester_builder": _uuid(941),
}

DOCUMENT_IDS = {
    "hr_leave": _uuid(310),
    "hr_welfare": _uuid(311),
    "finance_sensitive": _uuid(312),
    "legal_labor_standards": _uuid(340),
    "legal_equal_employment": _uuid(341),
    "legal_equal_employment_enforcement_decree": _uuid(342),
    "legal_privacy": _uuid(343),
    "legal_occupational_safety": _uuid(344),
    "legal_retirement_benefits": _uuid(345),
    "legal_fair_hiring": _uuid(346),
    "internal_onboarding": _uuid(347),
    "internal_leave_attendance": _uuid(348),
    "internal_benefits": _uuid(349),
    "internal_privacy_hr_records": _uuid(350),
    "internal_budget_alert_runbook": _uuid(351),
    "internal_cost_optimization_playbook": _uuid(352),
    "internal_developer_onboarding_rules": _uuid(353),
    "internal_developer_commit_convention": _uuid(354),
    "internal_developer_compensation_band": _uuid(355),
    "internal_compensation_access_policy": _uuid(356),
    "internal_planning_onboarding_guide": _uuid(357),
    "onboarding_company_common": _uuid(358),
    "onboarding_platform": _uuid(359),
    "onboarding_sales": _uuid(360),
    "onboarding_finance": _uuid(361),
}

COLLECTION_ITEM_IDS = {
    "legal_labor_standards": _uuid(370),
    "legal_equal_employment": _uuid(371),
    "legal_equal_employment_enforcement_decree": _uuid(372),
    "legal_privacy": _uuid(373),
    "legal_occupational_safety": _uuid(374),
    "legal_retirement_benefits": _uuid(375),
    "legal_fair_hiring": _uuid(376),
    "internal_onboarding": _uuid(377),
    "internal_leave_attendance": _uuid(378),
    "internal_benefits": _uuid(379),
    "internal_privacy_hr_records": _uuid(380),
    "internal_budget_alert_runbook": _uuid(381),
    "internal_cost_optimization_playbook": _uuid(382),
    "internal_developer_onboarding_rules": _uuid(383),
    "internal_developer_commit_convention": _uuid(384),
    "internal_developer_compensation_band": _uuid(385),
    "internal_compensation_access_policy": _uuid(386),
    "internal_planning_onboarding_guide": _uuid(387),
    "onboarding_company_common": _uuid(388),
    "onboarding_platform": _uuid(389),
    "onboarding_sales": _uuid(390),
    "onboarding_finance": _uuid(391),
    "hr_leave": _uuid(392),
    "hr_welfare": _uuid(393),
}

LEGACY_DEMO_DOCUMENT_KB_KEYS = {
    "hr_leave": "hr",
    "hr_welfare": "hr_welfare",
    "finance_sensitive": "finance",
}

HR_POLICY_COLLECTION_ITEMS = (
    ("hr_leave", "internal_leave_attendance"),
    ("hr_welfare", "internal_benefits"),
)

APP_IDS = {
    "hr_bot_example": _uuid(400),
    "ticket_ops": _uuid(401),
    "ticket_ops_warning": _uuid(402),
    "ticket_ops_risk": _uuid(403),
    "ticket_ops_paused": _uuid(404),
    "test_inquiry": _uuid(405),
    "department_onboarding_chatbot": _uuid(406),
    "team_onboarding_access_control": _uuid(407),
    "model_router_ticket_ops": uuid.UUID("91000000-0000-0000-0000-000000000001"),
    "team_onboarding_adaptive_routing": _uuid(408),
    "enterprise_request_routing": _uuid(409),
}

WORKFLOW_IDS = {
    key: _uuid(500 + index)
    for index, key in enumerate(APP_IDS.keys())
}
WORKFLOW_IDS["model_router_ticket_ops"] = uuid.UUID(
    "91000000-0000-0000-0000-000000000002"
)
WORKFLOW_IDS["team_onboarding_adaptive_routing"] = _uuid(508)

DEPLOYMENT_IDS = {
    key: _uuid(600 + index)
    for index, key in enumerate(APP_IDS.keys())
}
DEPLOYMENT_IDS["model_router_ticket_ops"] = uuid.UUID(
    "91000000-0000-0000-0000-000000000003"
)
DEPLOYMENT_IDS["team_onboarding_adaptive_routing"] = _uuid(608)

LEGACY_DEMO_LLM_CREDENTIAL_ID = _uuid(700)

TEAM_PERMISSION_IDS = {
    "customer_ticket": _uuid(800),
    "hr_bot": _uuid(801),
    "test_builder": _uuid(802),
    "test_member": _uuid(803),
    "model_router_ticket": _uuid(804),
    "department_onboarding_development": _uuid(805),
    "department_onboarding_planning": _uuid(806),
    "team_onboarding_platform": _uuid(807),
    "team_onboarding_sales": _uuid(808),
    "team_onboarding_people": _uuid(809),
    "team_onboarding_adaptive_platform": _uuid(810),
    "team_onboarding_adaptive_sales": _uuid(811),
    "team_onboarding_adaptive_people": _uuid(812),
    "enterprise_request_routing": _uuid(813),
}


@dataclass(frozen=True)
class DemoUserSpec:
    key: str
    email: str
    name: str
    membership_state: str
    organization_auth_state: str
    teams: tuple[str, ...]


@dataclass(frozen=True)
class DemoKnowledgeSeedSpec:
    key: str
    name: str
    description: str
    filename: str
    summary: str
    source_tier: str
    classification: str
    tags: tuple[str, ...]
    keywords: tuple[str, ...]
    collection_key: str | None
    content: str | None = None
    legal_filename_pattern: str | None = None
    legal_required_tokens: tuple[str, ...] = ()
    chunk_size: int = 1000
    chunk_overlap: int = 150
    source_page_indexes: tuple[int, ...] | None = None


ONBOARDING_PDF_SPECS = (
    DemoKnowledgeSeedSpec(
        key="onboarding_company_common",
        name="온보딩 문서: 회사 공통",
        description="전 직원이 조회하는 공통 온보딩 절차",
        filename="company_common_onboarding.pdf",
        summary="첫날 일정, 공통 계정 설정, 보안 교육과 완료 기준",
        source_tier="private",
        classification="internal",
        tags=("온보딩", "회사 공통", "보안 교육"),
        keywords=("첫날 일정", "SSO", "보안 교육", "메신저"),
        collection_key="team_onboarding_access_control",
        chunk_size=800,
        chunk_overlap=100,
    ),
    DemoKnowledgeSeedSpec(
        key="onboarding_platform",
        name="온보딩 문서: 플랫폼개발팀",
        description="플랫폼개발팀 개발환경과 접근 신청 절차",
        filename="platform_team_onboarding_v4.pdf",
        summary="플랫폼개발팀 첫 주 일정, Git, VPN과 운영 조회 권한 신청",
        source_tier="private",
        classification="internal",
        tags=("온보딩", "플랫폼", "개발환경", "접근 권한"),
        keywords=("Git", "VPN", "운영 조회", "배포 권한"),
        collection_key="team_onboarding_access_control",
        chunk_size=800,
        chunk_overlap=100,
        # 마지막 페이지는 role_acl=manager다. 현재 runtime은 chunk ACL을
        # 강제하지 않으므로 employee KB 복사본에서는 제외한다.
        source_page_indexes=(0, 1, 2),
    ),
    DemoKnowledgeSeedSpec(
        key="onboarding_sales",
        name="온보딩 문서: 영업팀",
        description="영업팀 CRM과 고객 데이터 취급 온보딩 절차",
        filename="sales_team_onboarding_v2.pdf",
        summary="영업팀 첫 주 일정, CRM 접근, 견적 승인과 고객 데이터 취급",
        source_tier="private",
        classification="internal",
        tags=("온보딩", "영업", "CRM", "고객 데이터"),
        keywords=("CRM", "고객 계정", "견적 승인", "세일즈 플레이북"),
        collection_key="team_onboarding_access_control",
        chunk_size=800,
        chunk_overlap=100,
    ),
    DemoKnowledgeSeedSpec(
        key="onboarding_finance",
        name="온보딩 문서: 재무팀",
        description="재무팀 회계 시스템과 지급 승인 온보딩 절차",
        filename="finance_team_onboarding_v3.pdf",
        summary="재무팀 첫 주 일정, 회계 시스템, 결산과 지급 승인 절차",
        source_tier="private",
        classification="confidential",
        tags=("온보딩", "재무", "회계", "지급 승인"),
        keywords=("회계 시스템", "결산", "지급 요청", "업무 분리"),
        collection_key="team_onboarding_access_control",
        chunk_size=800,
        chunk_overlap=100,
    ),
)

ONBOARDING_KB_SPECS = {
    spec.key: (spec.name, spec.filename) for spec in ONBOARDING_PDF_SPECS
}


USER_SPECS = [
    DemoUserSpec(
        "admin",
        "admin@nodease.demo",
        "관리자 김도윤",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MANAGER,
        ("platform_admin",),
    ),
    DemoUserSpec(
        "rookie",
        "rookie@nodease.demo",
        "신입사원 이서연",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("ai_builder_onboarding", "hr_knowledge_users"),
    ),
    DemoUserSpec(
        "author",
        "author@nodease.demo",
        "운영자 박민준",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("customer_support_ops",),
    ),
    DemoUserSpec(
        "tester_manager",
        "tester.manager@nodease.demo",
        "테스트 관리자",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MANAGER,
        ("platform_admin",),
    ),
    DemoUserSpec(
        "tester_builder",
        "tester.builder@nodease.demo",
        "테스트 빌더",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("tester_builder",),
    ),
    DemoUserSpec(
        "tester_member",
        "tester.member@nodease.demo",
        "테스트 멤버",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("tester_member",),
    ),
    DemoUserSpec(
        "developer",
        "dev@nodease.demo",
        "개발팀 사용자 정개발",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("department_development",),
    ),
    DemoUserSpec(
        "planning",
        "planning@nodease.demo",
        "기획팀 사용자 김기획",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("department_planning",),
    ),
    DemoUserSpec(
        "invited",
        "invited@nodease.demo",
        "초대대기 한지민",
        ORGANIZATION_MEMBERSHIP_INVITED,
        ORGANIZATION_AUTH_MEMBER,
        (),
    ),
    DemoUserSpec(
        "suspended",
        "suspended@nodease.demo",
        "정지회원 최유진",
        ORGANIZATION_MEMBERSHIP_SUSPENDED,
        ORGANIZATION_AUTH_MEMBER,
        (),
    ),
    DemoUserSpec(
        "removed",
        "removed@nodease.demo",
        "제거회원 정하늘",
        ORGANIZATION_MEMBERSHIP_REMOVED,
        ORGANIZATION_AUTH_MEMBER,
        (),
    ),
    DemoUserSpec(
        "onboarding_platform_rookie",
        "seoyeon.kim@nodease.demo",
        "김서연",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("onboarding_platform",),
    ),
    DemoUserSpec(
        "onboarding_sales_rookie",
        "junho.lee@nodease.demo",
        "이준호",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("onboarding_sales",),
    ),
    DemoUserSpec(
        "onboarding_people_manager",
        "jimin.park@nodease.demo",
        "박지민",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MANAGER,
        ("onboarding_people",),
    ),
]

DEMO_EMAILS = tuple(spec.email for spec in USER_SPECS)

TEAM_SPECS = {
    "platform_admin": ("플랫폼 관리팀", "관리자 권한, 감사 로그, 운영 지표를 확인하는 팀"),
    "ai_builder_onboarding": (
        "AI 빌더 온보딩팀",
        "신입사원이 권한 신청 후 AI 빌더를 사용하는 온보딩 팀",
    ),
    "customer_support_ops": (
        "고객지원 운영팀",
        "고객 티켓 처리 워크플로우를 운영하고 비용 최적화를 수행하는 팀",
    ),
    "hr_knowledge_users": (
        "인사 지식 활용팀",
        "휴가, 복지, 인사 정책 문서를 검색해 답변을 받는 팀",
    ),
    "finance_restricted": ("재무 제한 문서팀", "민감 재무 문서 권한 대조용 팀"),
    "tester_builder": ("테스트 빌더팀", "자유 기능 확인용 빌더 팀"),
    "tester_member": ("테스트 일반팀", "일반 멤버 권한 제한 확인용 팀"),
    "department_development": (
        "개발팀",
        "공통 온보딩과 개발팀 전용 Knowledge를 사용하는 데모 팀",
    ),
    "department_planning": (
        "기획팀",
        "공통 온보딩과 기획팀 전용 Knowledge를 사용하는 데모 팀",
    ),
    "onboarding_platform": (
        "플랫폼개발팀",
        "회사 공통 및 플랫폼개발팀 온보딩 문서를 사용하는 데모 팀",
    ),
    "onboarding_sales": (
        "영업팀",
        "회사 공통 및 영업팀 온보딩 문서를 사용하는 데모 팀",
    ),
    "onboarding_people": (
        "People 팀",
        "팀별 온보딩 문서와 권한 및 감사 로그를 관리하는 데모 팀",
    ),
    "onboarding_finance": (
        "재무팀",
        "회사 공통 및 재무팀 온보딩 문서를 사용하는 권한 경계 데모 팀",
    ),
}


TEST_ORG_ID = _uuid(9000)
TEST_USER_IDS = {
    "admin": _uuid(9001),
    "builder": _uuid(9002),
    "member": _uuid(9003),
    "invited": _uuid(9004),
    "suspended": _uuid(9005),
}
TEST_TEAM_IDS = {
    "qa_admin": _uuid(9010),
    "qa_builder": _uuid(9011),
    "qa_member": _uuid(9012),
}
TEST_APP_ID = _uuid(9020)
TEST_WORKFLOW_ID = _uuid(9021)
TEST_DEPLOYMENT_ID = _uuid(9022)
TEST_PERMISSION_IDS = {
    "builder": _uuid(9030),
    "member": _uuid(9031),
}

TEST_USER_SPECS = [
    DemoUserSpec(
        "admin",
        "test.admin@test.nodease.demo",
        "테스트 관리자",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MANAGER,
        ("qa_admin",),
    ),
    DemoUserSpec(
        "builder",
        "test.builder@test.nodease.demo",
        "테스트 빌더",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("qa_builder",),
    ),
    DemoUserSpec(
        "member",
        "test.member@test.nodease.demo",
        "테스트 멤버",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("qa_member",),
    ),
    DemoUserSpec(
        "invited",
        "test.invited@test.nodease.demo",
        "테스트 초대대기",
        ORGANIZATION_MEMBERSHIP_INVITED,
        ORGANIZATION_AUTH_MEMBER,
        (),
    ),
    DemoUserSpec(
        "suspended",
        "test.suspended@test.nodease.demo",
        "테스트 정지회원",
        ORGANIZATION_MEMBERSHIP_SUSPENDED,
        ORGANIZATION_AUTH_MEMBER,
        (),
    ),
]

TEST_EMAILS = {spec.email for spec in TEST_USER_SPECS}
TEST_TEAM_SPECS = {
    "qa_admin": ("QA 관리자팀", "테스트 manager 권한 확인용 팀"),
    "qa_builder": ("QA 빌더팀", "테스트 workflow 생성/편집 확인용 팀"),
    "qa_member": ("QA 일반팀", "테스트 viewer 권한 확인용 팀"),
}

INTERNAL_DOCUMENT_CONTENT = {
    "internal_onboarding": """# 신입사원 공통 인사·휴가 정책

## 첫 주 진행 순서

신입사원은 입사 첫날 관리자 대시보드에서 조직 초대와 기본 권한을 확인한다.
AI 빌더 사용이 필요한 경우 App 생성 권한 신청을 제출하고, 관리자가 승인한 뒤 온보딩 워크플로우를 만들 수 있다.

## 필수 확인 항목

1. 회사 계정 로그인과 2단계 인증 등록
2. 인사 포털 프로필 확인
3. 보안 서약과 개인정보 처리 안내 확인
4. 사내 문서 질문 응답 봇 테스트 실행

## 공통 휴가 절차

휴가는 사내 인사 포털의 근태/휴가 메뉴에서 신청한다.
긴급하지 않은 휴가는 사용 기간, 사유, 대체 업무 담당자를 입력하고 팀 리더 승인을 받는다.
가족돌봄휴가는 연차휴가와 이어서 사용할 수 있으며 개인별 병가 기록이나 휴직 사유는 일반 RAG에서 조회하지 않는다.

## 휴가와 프로젝트 운영 규정이 충돌할 때

휴가 제도와 승인 절차를 먼저 확인하고 프로젝트 일정은 대체 담당자, 인수인계 범위와 변경 일정을 정해 조정한다.
팀 내부 프로젝트 규정만으로 승인된 휴가 제도를 무효화하지 않는다.
판단이 어려우면 팀 리더와 HR 담당자에게 함께 확인하고 합의한 담당자, 일정 변경과 후속 조치를 프로젝트 기록에 남긴다.
긴급한 휴가는 업무 복귀 후 인수인계와 일정 변경 기록을 보완할 수 있다.

## RAG 사용 안내

사내 문서 질문 응답 봇은 인사, 복지, 휴가, 법령 공개 자료를 검색해 답변한다.
개인별 병가 기록, 인사평가, 급여 원장처럼 개인 식별 정보가 포함된 자료는 일반 RAG 후보에 포함하지 않는다.
""",
    "internal_leave_attendance": """# 휴가·근태·가족돌봄휴가 운영 정책

## 가족돌봄휴가

가족의 질병, 사고, 노령 또는 자녀 양육으로 돌봄이 필요한 경우 가족돌봄휴가를 신청할 수 있다.
사내 기준상 가족돌봄휴가는 연차휴가와 이어서 사용할 수 있으며, 긴급하지 않은 경우 사용 예정일 전까지 팀 리더 승인을 받아야 한다.

## 신청 경로

휴가는 사내 인사 포털 > 근태/휴가 > 휴가 신청 메뉴에서 신청한다.
신청자는 휴가 종류, 사용 기간, 사유, 대체 업무 담당자를 입력한다.

## 검색 제한

동료의 병가 기록, 휴직 사유, 개인 인사평가 결과는 일반 사용자에게 공개되지 않는다.
LLM 답변은 제도 설명과 신청 절차 안내로 제한한다.
""",
    "internal_benefits": """# 복지·교육비 지원 정책

## 복지 포인트

복지 포인트는 매년 초 재직 상태와 근속 조건에 따라 지급된다.
사용 가능 항목은 건강관리, 자기계발, 가족 지원, 문화생활로 구분한다.

## 교육비 지원

업무 관련 교육, 자격증, 컨퍼런스 참가비는 팀 리더 승인 후 지원할 수 있다.
교육비 지원 신청에는 교육명, 목적, 예상 비용, 업무 관련성을 기재한다.

## 경조사 지원

경조사 지원은 복지 포털에서 신청하며, 증빙 서류가 필요한 항목은 신청 후 7일 이내 제출한다.
""",
    "internal_privacy_hr_records": """# 개인정보 및 인사기록 접근 정책

## 기본 원칙

인사기록, 병가 기록, 평가 결과, 급여 정보는 최소 권한 원칙에 따라 접근한다.
일반 RAG 검색은 제도 문서와 절차 문서만 노출하며, 개인별 원장이나 민감 원문은 후보에서 제외한다.

## 허용되는 답변 범위

LLM은 개인정보 처리 기준, 접근 신청 절차, 보존 기간 같은 정책 설명을 제공할 수 있다.
특정 구성원의 건강 정보, 징계 정보, 급여, 평가 등 개인 식별 가능한 내용은 답변하지 않는다.

## 운영자 조치

민감 정보 접근 요청이 탐지되면 audit trace에 정책 차단 이벤트를 남기고 관리자 검토 대상으로 분류한다.
""",
    "internal_budget_alert_runbook": """# 워크플로우 예산 80% 알림 운영 Runbook

## 알림 기준

관리자 운영 콘솔은 월 예산 사용률이 80% 이상인 워크플로우를 비용 위험 대상으로 표시한다.
관리자는 대상 워크플로우를 일괄 선택해 운영자에게 비용 점검 알림을 보낼 수 있다.

## 알림 내용

알림에는 워크플로우 이름, 최근 실행 비용, LLM 노드 비용 비중, 최근 7일 실패율, 권장 점검 항목을 포함한다.
운영자는 알림에서 바로 워크플로우 분석 화면으로 이동한다.

## 후속 조치

운영자는 LLM 노드별 token 사용량, RAG 검색 건수, 모델별 비용을 비교하고 필요하면 모델 변경 또는 top_k 조정을 검토한다.
""",
    "internal_cost_optimization_playbook": """# Workflow LLM 비용 최적화 Playbook

## 분석 순서

운영자는 워크플로우 분석 화면에서 노드별 비용 비중을 먼저 확인한다.
LLM 노드 비용이 높으면 prompt 길이, RAG evidence 수, 모델 단가, 재시도 횟수를 순서대로 점검한다.

## 권장 조치

반복 질의는 캐시 후보로 분류하고, 단순 분류 노드는 더 작은 모델을 검토한다.
RAG 노드는 관련성이 낮은 문서가 많이 들어오면 top_k를 낮추거나 metadata filter를 적용한다.
근거 문서는 trace에서 요약과 참조 ID만 남기고 원문을 durable trace에 중복 저장하지 않는다.

## 승인 필요 조건

고객 보상, 법무 검토, 개인정보 포함 답변은 자동 발송하지 않고 승인 노드로 넘긴다.
""",
    "internal_developer_onboarding_rules": """# 개발팀 신입 온보딩 및 업무 내규

## 적용 대상

이 문서는 개발팀에 입사한 신입사원이 첫 달에 따라야 할 업무 내규와 온보딩 절차를 설명한다.
개발팀 신입사원은 입사 첫 주에 개발 환경 세팅, 보안 교육, 코드 저장소 접근 권한, PR 리뷰 흐름을 확인한다.

## 첫 주 체크리스트

1. 회사 계정, VPN, 2단계 인증을 등록한다.
2. GitHub 조직 초대와 개발팀 repository 접근 권한을 확인한다.
3. 기본 브랜치 정책, commit convention, PR template, 리뷰 승인 기준을 읽는다.
4. 사내 문서 질문 응답 봇에서 온보딩 문서와 개발팀 내규를 검색해 확인한다.
5. 운영 데이터, 고객 데이터, 개인 인사정보는 승인된 시스템에서만 접근한다.

## 개발 업무 원칙

신입 개발자는 첫 달 동안 production 직접 배포를 수행하지 않는다.
모든 변경은 feature branch에서 작업하고, PR 리뷰와 CI 통과 후 merge한다.
긴급 장애 대응 참여는 멘토 또는 운영 담당자와 함께 진행한다.

## 질문 채널

개발 환경, 브랜치, 커밋 메시지, PR 리뷰 질문은 개발팀 온보딩 채널에 남긴다.
보상, 평가, 개인 인사정보 관련 질문은 인사 포털의 공개 정책 범위 안에서만 안내받을 수 있다.
""",
    "internal_developer_commit_convention": """# 개발팀 커밋·브랜치·PR 컨벤션

## 브랜치 이름

Linear 이슈가 있는 기능 작업은 `feature/mba-번호` 형식의 브랜치를 사용한다.
버그 수정은 같은 이슈 번호를 기준으로 `fix/mba-번호`를 사용할 수 있다.
실험성 작업이나 개인 임시 브랜치는 PR 대상 브랜치로 사용하지 않는다.

## 커밋 메시지

커밋 메시지는 `type: 한국어 설명` 형식을 따른다.
type은 영어 소문자로 작성하며 대표 값은 `feat`, `fix`, `docs`, `test`, `refactor`, `chore`다.
예시는 다음과 같다.

- `feat: 개발팀 온보딩 RAG 문서 추가`
- `fix: Knowledge 목록 legacy schema 오류 방어`
- `docs: 데모 DB 재생성 절차 보강`
- `test: Workflow RAG 권한 경계 회귀 테스트 추가`

## PR 작성 기준

PR 본문에는 변경 사항, 관련 이슈, 테스트 결과, UI 변경 여부를 적는다.
권한, credential, RAG, audit, trace, 비용 최적화 경계를 건드린 경우 관련 문서와 테스트를 함께 갱신한다.
리뷰 요청 전에는 `git diff --check`와 변경 범위에 맞는 테스트를 실행한다.

## 금지 사항

secret, API key, token, `.env` 내용, 암호화 전 credential 원문을 커밋 메시지, PR 본문, 로그, fixture에 남기지 않는다.
민감 원문을 trace나 demo fixture에 넣어야 하는 경우 별도 승인 없이 진행하지 않는다.
""",
    "internal_developer_compensation_band": """# 개발 직군 신입 보상 밴드 및 공개 가능 범위

## 공개 가능한 안내 범위

이 문서는 개발팀 신입사원이 질문할 수 있는 보상 기준의 공개 가능 범위를 설명한다.
사내 문서 질문 응답 봇은 개인별 실제 연봉이 아니라 직군·레벨별 보상 밴드, 산정 요소, 문의 경로만 답변할 수 있다.

## 신입 개발자 보상 밴드

2026년 데모 기준 개발 직군 신입 레벨은 `DEV-L1`로 분류한다.
`DEV-L1` 기준 연간 기본급 밴드는 4,800만 원에서 5,600만 원 사이로 안내한다.
최종 제안 금액은 경력 인정, 직무 적합도, 채용 평가, 근무 지역, 입사 시점의 내부 보상 정책에 따라 달라질 수 있다.

## 보상 구성

기본급 외 항목은 성과급, 복지 포인트, 교육비 지원, 장비 지원으로 구분한다.
성과급은 회사 성과와 개인 평가에 따라 달라지므로 사전 확정 금액으로 안내하지 않는다.
복지 포인트와 교육비 지원은 복지·교육비 지원 정책 문서를 함께 참조한다.

## 답변 제한

동료, 특정 팀원, 특정 후보자, 특정 사번의 실제 연봉·성과급·평가등급은 답변하지 않는다.
개인별 보상정보가 필요한 경우 인사 포털의 권한 승인 절차를 통해 HR 담당자에게 문의한다.
""",
    "internal_compensation_access_policy": """# 개인 보상정보 및 인사기록 조회 제한 정책

## 정책 목적

개인 보상정보는 급여, 연봉, 성과급, 스톡옵션, 평가등급, 보상 조정 이력을 포함한다.
이 정보는 개인정보 및 인사기록 접근 정책에 따라 최소 권한 원칙으로 보호한다.

## RAG 답변 허용 범위

RAG 기반 사내 문서 질문 응답 봇은 공개 가능한 보상 밴드, 보상 산정 원칙, 문의 경로만 답변할 수 있다.
특정 임직원, 동료, 팀원, 후보자, 사번, 실명과 연결된 실제 보상정보는 답변하지 않는다.
질문자가 본인이라고 주장해도 본인 확인과 HR 권한 확인이 없는 채팅 경로에서는 개인별 금액을 제공하지 않는다.

## 차단해야 하는 질문 예시

- `개발팀 동료 김OO의 연봉을 알려줘`
- `우리 팀 백엔드 개발자들의 실제 연봉 리스트를 보여줘`
- `박OO의 성과급과 평가등급을 알려줘`
- `내 옆자리 개발자의 보상 조정 이력을 알려줘`

## 안내 문구

개인별 연봉이나 평가 정보 요청을 받으면 다음과 같이 안내한다.
`개인 보상정보는 접근 권한이 필요한 민감 정보라 이 채팅에서 제공할 수 없습니다. 공개 가능한 보상 밴드나 문의 경로는 안내할 수 있습니다.`

## 운영자 처리

개인 보상정보 조회 시도는 audit log에 정책 차단 이벤트로 남긴다.
반복적인 민감정보 요청은 관리자 검토 대상으로 분류한다.
""",
    "internal_planning_onboarding_guide": """# 기획팀 신입 온보딩 가이드

## 첫 주 진행 순서

기획팀 신입사원은 담당 제품의 목표, 사용자 문제, 핵심 지표와 현재 로드맵을 확인한다.
첫 주에는 제품 브리프를 읽고 담당 PM과 함께 사용자 여정, 주요 가설, 의사결정 이력을 검토한다.

## 기획 문서 작성 기준

PRD에는 문제 정의, 대상 사용자, 가설, 성공 지표, 비목표, 출시 범위와 검증 계획을 포함한다.
요구사항은 구현 방법보다 검증 가능한 사용자 행동과 완료 조건을 먼저 작성한다.
중요한 범위 변경은 회의 메모에만 남기지 않고 PRD 결정 로그와 Linear 이슈에 함께 반영한다.

## 협업 절차

개발 착수 전 디자인·개발 담당자와 acceptance criteria를 합의한다.
출시 전에는 분석 이벤트, 권한별 사용자 흐름, 오류·빈 상태와 롤백 기준을 점검한다.
고객 인터뷰 원문과 개인 식별 정보는 승인된 저장소에만 보관하며 일반 RAG 문서에 복사하지 않는다.

## 첫 달 완료 기준

첫 달에는 작은 개선 과제 하나를 문제 정의부터 출시 후 지표 확인까지 수행한다.
결과 보고서는 `가설-근거-결정-결과-후속 조치` 순서로 정리한다.
""",
}

LEGAL_DOCUMENT_SPECS = (
    DemoKnowledgeSeedSpec(
        key="legal_labor_standards",
        name="공개 법령: 근로기준법",
        description="휴가, 근로시간, 임금 등 온보딩 질의에 참조하는 공개 법령 KB",
        filename="근로기준법.pdf",
        summary="근로기준법 공개 법령 PDF",
        source_tier="public",
        classification="public_law",
        tags=("law", "labor", "onboarding"),
        keywords=("근로기준법", "연차", "휴가", "근로시간", "임금", "가족돌봄"),
        collection_key="legal_public",
        legal_filename_pattern="근로기준법",
    ),
    DemoKnowledgeSeedSpec(
        key="legal_equal_employment",
        name="공개 법령: 남녀고용평등법",
        description="일·가정 양립, 가족돌봄 제도 질의에 참조하는 공개 법령 KB",
        filename="남녀고용평등과 일가정 양립 지원에 관한 법률.pdf",
        summary="남녀고용평등과 일·가정 양립 지원에 관한 법률 공개 PDF",
        source_tier="public",
        classification="public_law",
        tags=("law", "labor", "family-care"),
        keywords=("남녀고용평등", "일가정", "가족돌봄휴가", "육아휴직", "배우자 출산휴가"),
        collection_key="legal_public",
        legal_filename_pattern="지원에 관한 법률(",
        legal_required_tokens=("남녀고용평등",),
    ),
    DemoKnowledgeSeedSpec(
        key="legal_equal_employment_enforcement_decree",
        name="공개 법령: 남녀고용평등법 시행령",
        description="일·가정 양립 제도 세부 기준 질의에 참조하는 공개 시행령 KB",
        filename="남녀고용평등과 일가정 양립 지원에 관한 법률 시행령.pdf",
        summary="남녀고용평등과 일·가정 양립 지원에 관한 법률 시행령 공개 PDF",
        source_tier="public",
        classification="public_law",
        tags=("law", "labor", "family-care", "decree"),
        keywords=("시행령", "가족돌봄", "육아기", "근로시간 단축", "일가정"),
        collection_key="legal_public",
        legal_filename_pattern="지원에 관한 법률 시행령",
        legal_required_tokens=("남녀고용평등",),
    ),
    DemoKnowledgeSeedSpec(
        key="legal_privacy",
        name="공개 법령: 개인정보 보호법",
        description="인사기록과 개인정보 처리 기준 질의에 참조하는 공개 법령 KB",
        filename="개인정보 보호법.pdf",
        summary="개인정보 보호법 공개 법령 PDF",
        source_tier="public",
        classification="public_law",
        tags=("law", "privacy", "hr-records"),
        keywords=("개인정보", "민감정보", "처리", "보존", "접근권한", "동의"),
        collection_key="legal_public",
        legal_filename_pattern="개인정보 보호법",
    ),
    DemoKnowledgeSeedSpec(
        key="legal_occupational_safety",
        name="공개 법령: 산업안전보건법",
        description="안전보건 교육과 작업장 안전 질의에 참조하는 공개 법령 KB",
        filename="산업안전보건법.pdf",
        summary="산업안전보건법 공개 법령 PDF",
        source_tier="public",
        classification="public_law",
        tags=("law", "safety", "onboarding"),
        keywords=("산업안전보건", "안전교육", "보건", "위험성", "근로자"),
        collection_key="legal_public",
        legal_filename_pattern="산업안전보건법",
    ),
    DemoKnowledgeSeedSpec(
        key="legal_retirement_benefits",
        name="공개 법령: 근로자퇴직급여 보장법",
        description="퇴직급여 제도 질의에 참조하는 공개 법령 KB",
        filename="근로자퇴직급여 보장법.pdf",
        summary="근로자퇴직급여 보장법 공개 법령 PDF",
        source_tier="public",
        classification="public_law",
        tags=("law", "retirement", "benefits"),
        keywords=("퇴직급여", "퇴직연금", "근로자", "급여", "보장"),
        collection_key="legal_public",
        legal_filename_pattern="근로자퇴직급여 보장법",
    ),
    DemoKnowledgeSeedSpec(
        key="legal_fair_hiring",
        name="공개 법령: 채용절차의 공정화에 관한 법률",
        description="채용 절차와 입사 서류 질의에 참조하는 공개 법령 KB",
        filename="채용절차의 공정화에 관한 법률.pdf",
        summary="채용절차의 공정화에 관한 법률 공개 PDF",
        source_tier="public",
        classification="public_law",
        tags=("law", "hiring", "onboarding"),
        keywords=("채용절차", "공정화", "입사지원", "채용서류", "구직자"),
        collection_key="legal_public",
        legal_filename_pattern="채용절차의 공정화에 관한 법률",
    ),
)

INTERNAL_DOCUMENT_SPECS = (
    DemoKnowledgeSeedSpec(
        key="internal_onboarding",
        name="사내문서: 신입사원 공통 인사·휴가 정책",
        description="신입사원 공통 온보딩, 휴가 신청과 프로젝트 일정 충돌 절차를 안내하는 사내문서 KB",
        filename="신입사원 공통 인사 휴가 정책.md",
        summary="입사 첫 주, 휴가 신청, 프로젝트 일정 충돌과 RAG 사용 범위를 안내합니다.",
        source_tier="internal",
        classification="internal_policy",
        tags=("internal", "onboarding", "hr", "leave", "ai-builder"),
        keywords=(
            "신입사원",
            "온보딩",
            "인사",
            "휴가",
            "프로젝트 운영 규정",
            "권한 신청",
            "AI 빌더",
        ),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_onboarding"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_leave_attendance",
        name="사내문서: 휴가·근태·가족돌봄휴가 운영 정책",
        description="휴가 신청 절차와 가족돌봄휴가 운영 기준을 안내하는 사내문서 KB",
        filename="휴가 근태 가족돌봄휴가 운영 정책.md",
        summary="가족돌봄휴가, 연차 연계 사용, 신청 경로를 안내합니다.",
        source_tier="internal",
        classification="internal_policy",
        tags=("internal", "hr", "leave"),
        keywords=("가족돌봄휴가", "연차", "휴가 신청", "근태", "팀 리더 승인"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_leave_attendance"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_benefits",
        name="사내문서: 복지·교육비 지원 정책",
        description="복지 포인트, 교육비, 경조사 지원을 설명하는 사내문서 KB",
        filename="복지 교육비 지원 정책.md",
        summary="복지 포인트, 교육비 지원, 경조사 지원 기준을 안내합니다.",
        source_tier="internal",
        classification="internal_policy",
        tags=("internal", "hr", "benefits"),
        keywords=("복지 포인트", "교육비", "경조사", "자기계발", "복지 포털"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_benefits"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_privacy_hr_records",
        name="사내문서: 개인정보 및 인사기록 접근 정책",
        description="인사기록과 민감정보 접근 제한을 설명하는 사내문서 KB",
        filename="개인정보 및 인사기록 접근 정책.md",
        summary="개인정보, 병가 기록, 평가 정보의 RAG 노출 제한을 안내합니다.",
        source_tier="restricted_internal",
        classification="restricted_policy",
        tags=("internal", "privacy", "hr-records"),
        keywords=("개인정보", "인사기록", "병가 기록", "인사평가", "정책 차단", "최소 권한"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_privacy_hr_records"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_budget_alert_runbook",
        name="사내문서: 워크플로우 예산 80% 알림 Runbook",
        description="관리자 예산 알림과 운영자 후속 분석 절차를 설명하는 운영문서 KB",
        filename="워크플로우 예산 80퍼센트 알림 Runbook.md",
        summary="예산 80% 이상 워크플로우 알림과 운영자 분석 진입 절차를 안내합니다.",
        source_tier="internal_ops",
        classification="internal_runbook",
        tags=("internal", "llmops", "budget"),
        keywords=("예산 80%", "일괄 알림", "운영자", "워크플로우 분석", "LLM 노드 비용"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_budget_alert_runbook"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_cost_optimization_playbook",
        name="사내문서: Workflow LLM 비용 최적화 Playbook",
        description="LLM 노드 비용 분석과 RAG 비용 최적화 절차를 설명하는 운영문서 KB",
        filename="Workflow LLM 비용 최적화 Playbook.md",
        summary="노드별 비용, RAG evidence 수, 모델 단가를 점검하는 절차를 안내합니다.",
        source_tier="internal_ops",
        classification="internal_runbook",
        tags=("internal", "llmops", "cost-optimization"),
        keywords=("비용 최적화", "LLM 노드", "top_k", "RAG evidence", "모델 변경", "trace"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_cost_optimization_playbook"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_developer_onboarding_rules",
        name="사내문서: 개발팀 온보딩 가이드",
        description="개발팀 신입사원의 첫 달 업무 내규, 권한, PR 흐름을 안내하는 사내문서 KB",
        filename="개발팀 신입 온보딩 및 업무 내규.md",
        summary="개발팀 신입 온보딩, repository 접근, PR 리뷰 흐름을 안내합니다.",
        source_tier="internal",
        classification="internal_policy",
        tags=("internal", "developer", "onboarding"),
        keywords=("개발팀", "신입", "온보딩", "내규", "repository", "PR", "멘토"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_developer_onboarding_rules"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_developer_commit_convention",
        name="사내문서: 개발팀 커밋·브랜치·PR 컨벤션",
        description="개발팀 commit convention, branch naming, PR 작성 기준을 안내하는 사내문서 KB",
        filename="개발팀 커밋 브랜치 PR 컨벤션.md",
        summary="feature/mba-번호 브랜치와 type: 한국어 설명 커밋 규칙을 안내합니다.",
        source_tier="internal",
        classification="internal_policy",
        tags=("internal", "developer", "git", "commit", "pr"),
        keywords=("커밋", "commit convention", "브랜치", "feature/mba", "PR", "type", "한국어 설명"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_developer_commit_convention"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_developer_compensation_band",
        name="사내문서: 개발 직군 신입 보상 밴드 및 공개 가능 범위",
        description="개발 직군 신입 보상 밴드와 공개 가능한 답변 범위를 안내하는 사내문서 KB",
        filename="개발 직군 신입 보상 밴드 및 공개 가능 범위.md",
        summary="DEV-L1 신입 개발자 보상 밴드와 공개 가능 범위를 안내합니다.",
        source_tier="internal",
        classification="internal_policy",
        tags=("internal", "developer", "compensation", "onboarding"),
        keywords=("개발자", "신입", "연봉", "보상 밴드", "DEV-L1", "기본급", "공개 가능 범위"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_developer_compensation_band"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_compensation_access_policy",
        name="사내문서: 개인 보상정보 및 인사기록 조회 제한 정책",
        description="개인별 연봉, 성과급, 평가정보 질의 차단 기준을 설명하는 사내문서 KB",
        filename="개인 보상정보 및 인사기록 조회 제한 정책.md",
        summary="개인별 보상정보 조회 제한과 민감 질문 차단 문구를 안내합니다.",
        source_tier="restricted_internal",
        classification="restricted_policy",
        tags=("internal", "privacy", "compensation", "policy-block"),
        keywords=("개인 보상정보", "동료 연봉", "성과급", "평가등급", "정책 차단", "민감정보"),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_compensation_access_policy"],
    ),
    DemoKnowledgeSeedSpec(
        key="internal_planning_onboarding_guide",
        name="사내문서: 기획팀 온보딩 가이드",
        description="기획팀 신입사원의 PRD, 지표, 협업과 출시 검증 절차를 안내하는 사내문서 KB",
        filename="기획팀 신입 온보딩 가이드.md",
        summary="기획팀 신입사원의 PRD 작성, 협업, 지표 검증과 정보 취급 기준을 안내합니다.",
        source_tier="internal",
        classification="internal_policy",
        tags=("internal", "planning", "onboarding", "prd"),
        keywords=(
            "기획팀",
            "신입",
            "온보딩",
            "PRD",
            "성공 지표",
            "acceptance criteria",
            "로드맵",
        ),
        collection_key="internal_onboarding",
        content=INTERNAL_DOCUMENT_CONTENT["internal_planning_onboarding_guide"],
    ),
)

DEMO_DOCUMENT_SPECS = LEGAL_DOCUMENT_SPECS + INTERNAL_DOCUMENT_SPECS


def demo_summary(profile: str = "demo") -> dict[str, Any]:
    """Return a lightweight summary for --dry-run output."""
    if profile == "test":
        return {
            "profile": "test",
            "seed_version": DEMO_SEED_VERSION,
            "organization": "노디즈 테스트 조직",
            "users": [spec.email for spec in TEST_USER_SPECS],
            "teams": [name for name, _ in TEST_TEAM_SPECS.values()],
            "apps": ["테스트용 기능 검증 워크플로우"],
            "reset_scope": "test profile fixed UUID rows only",
            "credentials": "not seeded",
            "knowledge_documents": "not seeded",
        }
    return {
        "profile": "demo",
        "seed_version": DEMO_SEED_VERSION,
        "organization": "노디즈 데모 조직",
        "users": [spec.email for spec in USER_SPECS],
        "teams": [name for name, _ in TEAM_SPECS.values()],
        "apps": [
            "사내 문서 질문 응답 봇",
            "부서별 온보딩 RAG 챗봇",
            "팀별 온보딩 문서 접근 제어 데모",
            ENTERPRISE_REQUEST_ROUTING_NAME,
            "Enterprise 고객 티켓 처리",
            "테스트용 문의 응답 워크플로우",
        ],
        "reset_scope": "demo seed fixed UUID rows only",
        "credentials": (
            "non-secret demo metadata row by default; pass "
            "--enable-runtime-openai-credential to validate OPENAI_API_KEY or "
            "prompt securely before seeding a runtime credential"
        ),
        "knowledge_documents": {
            "public_law_pdfs": len(LEGAL_DOCUMENT_SPECS),
            "internal_markdown_docs": len(INTERNAL_DOCUMENT_SPECS),
            "bundled_onboarding_pdfs": len(ONBOARDING_PDF_SPECS),
            "embedding_model": DEMO_EMBEDDING_MODEL,
            "fixture": DEMO_KNOWLEDGE_FIXTURE_PATH.as_posix(),
        },
        "bundled_onboarding_pdf_sources": {
            spec.key: (DEMO_ONBOARDING_PDF_DIR / spec.filename).as_posix()
            for spec in ONBOARDING_PDF_SPECS
        },
    }


def _adopt_existing_demo_user_ids(db: Session) -> None:
    """Reuse existing local users with the demo emails instead of deleting them."""
    for spec in USER_SPECS:
        existing = db.query(User).filter(User.email == spec.email).first()
        if existing is not None:
            USER_IDS[spec.key] = existing.id


def _demo_options(key: str) -> dict[str, Any]:
    return {
        "demo_seed": True,
        "demo_seed_version": DEMO_SEED_VERSION,
        "demo_seed_key": key,
    }


def _write_demo_document(filename: str, content: str) -> str:
    last_error: OSError | None = None
    for base_dir in DEMO_UPLOAD_DIRS:
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            path = base_dir / filename
            path.write_text(content, encoding="utf-8")
            return path.as_posix()
        except OSError as error:
            last_error = error
    raise RuntimeError(
        f"demo 문서를 저장할 수 있는 upload 경로가 없습니다: {DEMO_UPLOAD_DIRS}"
    ) from last_error


def _copy_demo_source_file(source_path: Path, target_filename: str) -> str:
    last_error: OSError | None = None
    for base_dir in DEMO_UPLOAD_DIRS:
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            target_path = base_dir / target_filename
            shutil.copyfile(source_path, target_path)
            return target_path.as_posix()
        except OSError as error:
            last_error = error
    raise RuntimeError(
        f"demo 원본 파일을 저장할 수 있는 upload 경로가 없습니다: {DEMO_UPLOAD_DIRS}"
    ) from last_error


def _copy_onboarding_pdf(spec: DemoKnowledgeSeedSpec, source_path: Path) -> str:
    if spec.source_page_indexes is None:
        return _copy_demo_source_file(source_path, spec.filename)

    try:
        import fitz
    except ImportError as error:
        raise RuntimeError(
            "페이지 제한 온보딩 PDF를 만들려면 PyMuPDF가 필요합니다."
        ) from error

    last_error: OSError | None = None
    for base_dir in DEMO_UPLOAD_DIRS:
        try:
            base_dir.mkdir(parents=True, exist_ok=True)
            target_path = base_dir / spec.filename
            with fitz.open(source_path) as source_document, fitz.open() as target_document:
                for page_index in spec.source_page_indexes:
                    if page_index < 0 or page_index >= source_document.page_count:
                        raise ValueError(
                            f"{spec.filename} page index가 범위를 벗어났습니다: {page_index}"
                        )
                    target_document.insert_pdf(
                        source_document,
                        from_page=page_index,
                        to_page=page_index,
                    )
                target_path.write_bytes(target_document.tobytes())
            return target_path.as_posix()
        except OSError as error:
            last_error = error
    raise RuntimeError(
        f"demo 온보딩 PDF를 저장할 수 있는 upload 경로가 없습니다: {DEMO_UPLOAD_DIRS}"
    ) from last_error


def _resolve_legal_pdf(spec: DemoKnowledgeSeedSpec) -> Path:
    if not DEMO_LEGAL_DOCS_LABOR_DIR.exists():
        raise FileNotFoundError(
            "법령 PDF 디렉터리가 없습니다: "
            f"{DEMO_LEGAL_DOCS_LABOR_DIR.as_posix()}"
        )
    pattern = spec.legal_filename_pattern or spec.name
    candidates = []
    for candidate in sorted(DEMO_LEGAL_DOCS_LABOR_DIR.glob("*.pdf")):
        name = candidate.name
        if pattern not in name:
            continue
        if all(token in name for token in spec.legal_required_tokens):
            candidates.append(candidate)
    if candidates:
        return max(candidates, key=lambda candidate: (_legal_pdf_date(candidate), candidate.name))
    available = ", ".join(candidate.name for candidate in DEMO_LEGAL_DOCS_LABOR_DIR.glob("*.pdf")) or "none"
    raise FileNotFoundError(
        f"{spec.name} PDF를 찾지 못했습니다. pattern={pattern!r}, available={available}"
    )


def _resolve_onboarding_pdf(spec: DemoKnowledgeSeedSpec) -> Path:
    source_path = DEMO_ONBOARDING_PDF_DIR / spec.filename
    if not source_path.is_file():
        raise FileNotFoundError(
            f"온보딩 PDF를 찾지 못했습니다: {source_path.as_posix()}"
        )
    return source_path


def _legal_pdf_date(path: Path) -> str:
    matches = re.findall(r"\((\d{8})\)", path.name)
    return matches[-1] if matches else "00000000"


def _regenerate_knowledge_fixture_requested() -> bool:
    return os.getenv(DEMO_REGENERATE_KNOWLEDGE_FIXTURE_ENV) == "1"


def _runtime_openai_credential_requested() -> bool:
    return os.getenv(DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL_ENV) == "1"


def _should_index_onboarding_pdfs() -> bool:
    return (
        _regenerate_knowledge_fixture_requested()
        or _runtime_openai_credential_requested()
    )


def _demo_knowledge_fixture_exists() -> bool:
    return DEMO_KNOWLEDGE_FIXTURE_PATH.exists()


def _read_demo_knowledge_fixture() -> dict[str, Any]:
    if not _demo_knowledge_fixture_exists():
        raise FileNotFoundError(
            f"demo Knowledge fixture가 없습니다: {DEMO_KNOWLEDGE_FIXTURE_PATH.as_posix()}"
        )

    header: dict[str, Any] | None = None
    documents: dict[str, dict[str, Any]] = {}
    chunks_by_document: dict[str, list[dict[str, Any]]] = {}

    with gzip.open(DEMO_KNOWLEDGE_FIXTURE_PATH, "rt", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            record_type = record.get("record_type")
            if record_type == "header":
                header = record
            elif record_type == "document":
                key = str(record["key"])
                documents[key] = record
            elif record_type == "chunk":
                key = str(record["document_key"])
                chunks_by_document.setdefault(key, []).append(record)
            else:
                raise ValueError(
                    f"Unknown demo Knowledge fixture record at line {line_number}: {record_type}"
                )

    if header is None:
        raise ValueError("demo Knowledge fixture header가 없습니다.")
    if header.get("embedding_model") != DEMO_EMBEDDING_MODEL:
        raise ValueError(
            "demo Knowledge fixture embedding_model이 seed 설정과 다릅니다: "
            f"{header.get('embedding_model')}"
        )
    if header.get("embedding_dimension") != DEMO_EMBEDDING_DIMENSION:
        raise ValueError(
            "demo Knowledge fixture embedding_dimension이 seed 설정과 다릅니다: "
            f"{header.get('embedding_dimension')}"
        )

    expected_keys = {spec.key for spec in DEMO_DOCUMENT_SPECS}
    missing_documents = sorted(expected_keys - set(documents))
    if missing_documents:
        raise ValueError(
            f"demo Knowledge fixture document 누락: {', '.join(missing_documents)}"
        )
    missing_chunks = sorted(
        key for key in expected_keys if not chunks_by_document.get(key)
    )
    if missing_chunks:
        raise ValueError(
            f"demo Knowledge fixture chunk 누락: {', '.join(missing_chunks)}"
        )

    for key, chunks in chunks_by_document.items():
        chunks.sort(key=lambda item: int(item.get("chunk_index", 0)))
        for chunk in chunks:
            embedding = chunk.get("embedding")
            if not isinstance(embedding, list) or len(embedding) != DEMO_EMBEDDING_DIMENSION:
                raise ValueError(
                    f"demo Knowledge fixture embedding 차원 오류: {key}#{chunk.get('chunk_index')}"
                )

    return {
        "header": header,
        "documents": documents,
        "chunks_by_document": chunks_by_document,
    }


def _demo_knowledge_fixture_or_none() -> dict[str, Any] | None:
    if _regenerate_knowledge_fixture_requested():
        return None
    if not _demo_knowledge_fixture_exists():
        return None
    return _read_demo_knowledge_fixture()


def _write_demo_knowledge_fixture(records: list[dict[str, Any]]) -> None:
    DEMO_KNOWLEDGE_FIXTURE_PATH.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "record_type": "header",
        "fixture_version": DEMO_SEED_VERSION,
        "embedding_model": DEMO_EMBEDDING_MODEL,
        "embedding_dimension": DEMO_EMBEDDING_DIMENSION,
        "document_keys": [spec.key for spec in DEMO_DOCUMENT_SPECS],
        "storage": "plaintext_chunks_with_precomputed_embeddings",
    }
    with gzip.open(DEMO_KNOWLEDGE_FIXTURE_PATH, "wt", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(header, ensure_ascii=False, separators=(",", ":")))
        handle.write("\n")
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            handle.write("\n")


def _load_seed_env() -> None:
    env_path = DEMO_REPO_ROOT / ".env"
    if env_path.exists():
        try:
            from dotenv import load_dotenv

            load_dotenv(dotenv_path=env_path, override=False)
        except ImportError:
            pass


def _require_seed_env(name: str) -> str:
    _load_seed_env()
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} 환경변수가 필요합니다. repo root .env 또는 실행 환경에 설정하세요."
        )
    return value


def _mask_demo_api_key(api_key: str) -> str:
    if len(api_key) <= 10:
        return "****"
    return f"{api_key[:3]}****{api_key[-4:]}"


def _embed_text_batches(texts: list[str]) -> list[list[float]]:
    api_key = _require_seed_env("OPENAI_API_KEY")
    try:
        import openai
    except ImportError as error:
        raise RuntimeError("openai 패키지가 설치되어 있어야 demo seed embedding을 만들 수 있습니다.") from error

    client = openai.OpenAI(api_key=api_key, timeout=60.0)
    embeddings: list[list[float]] = []
    batch_size = 64
    for start in range(0, len(texts), batch_size):
        batch = [text if text and text.strip() else " " for text in texts[start : start + batch_size]]
        response = client.embeddings.create(input=batch, model=DEMO_EMBEDDING_MODEL)
        ordered = sorted(response.data, key=lambda item: item.index)
        for item in ordered:
            vector = list(item.embedding)
            if len(vector) != DEMO_EMBEDDING_DIMENSION:
                raise RuntimeError(
                    f"{DEMO_EMBEDDING_MODEL} embedding 차원이 {DEMO_EMBEDDING_DIMENSION}이 아닙니다: {len(vector)}"
                )
            embeddings.append(vector)
    if len(embeddings) != len(texts):
        raise RuntimeError(
            f"embedding 응답 개수가 입력과 다릅니다: expected={len(texts)}, actual={len(embeddings)}"
        )
    return embeddings


def _document_meta_base(
    spec: DemoKnowledgeSeedSpec,
    source_path: str,
    *,
    source_available: bool = True,
) -> dict[str, Any]:
    legal_effective_date = None
    if spec.source_tier == "public":
        match = re.search(r"\((\d{8})\)", Path(source_path).name)
        legal_effective_date = match.group(1) if match else None
    metadata = {
        **_demo_options(f"document-{spec.key}"),
        "summary": spec.summary,
        "classification": spec.classification,
        "tags": list(spec.tags),
        "source_tier": spec.source_tier,
        "source_type": "FILE",
        "source_filename": Path(source_path).name,
        "source_available": source_available,
        "legal_effective_date": legal_effective_date,
        "remove_whitespace": True,
        "selection_mode": "all",
    }
    if spec.source_page_indexes is not None:
        metadata["included_source_pages"] = [
            page_index + 1 for page_index in spec.source_page_indexes
        ]
        metadata["page_filter_reason"] = "unsupported_chunk_role_acl"
    return metadata


def _preserve_indexing_meta(
    existing: Document | None,
    base_meta: dict[str, Any],
) -> dict[str, Any]:
    if existing is None or not isinstance(existing.meta_info, dict):
        return base_meta
    preserved = {
        key: existing.meta_info[key]
        for key in ("chunking_mode", "chunking_fingerprint_hash", "hierarchy_version")
        if key in existing.meta_info
    }
    return {**base_meta, **preserved}


def _extract_raw_blocks(db: Session, doc: Document) -> list[dict[str, Any]]:
    from apps.gateway.services.ingestion.processors.file_processor import FileProcessor

    processor = FileProcessor(db, USER_IDS["admin"])
    result = processor.process({"document_id": str(doc.id), "file_path": doc.file_path})
    if result.metadata.get("error"):
        raise RuntimeError(f"{doc.filename} 파싱 실패: {result.metadata['error']}")
    if not result.chunks:
        raise RuntimeError(f"{doc.filename}에서 추출 가능한 텍스트가 없습니다.")
    return result.chunks


def _insert_demo_chunks_from_fixture(
    db: Session,
    specs: tuple[DemoKnowledgeSeedSpec, ...],
    fixture: dict[str, Any],
) -> None:
    _require_seed_env("ENCRYPTION_KEY")

    from apps.shared.utils.encryption import encryption_manager

    documents = fixture["documents"]
    chunks_by_document = fixture["chunks_by_document"]
    for spec in specs:
        doc = db.get(Document, DOCUMENT_IDS[spec.key])
        if doc is None:
            raise RuntimeError(f"demo 문서 row가 없습니다: {spec.key}")
        fixture_doc = documents[spec.key]
        chunks = chunks_by_document[spec.key]

        existing_chunk_count = (
            db.query(DocumentChunk)
            .filter(DocumentChunk.document_id == doc.id)
            .count()
        )
        if (
            existing_chunk_count > 0
            and doc.status == "completed"
            and doc.content_hash == fixture_doc["content_hash"]
            and doc.embedding_model == DEMO_EMBEDDING_MODEL
            and (doc.meta_info or {}).get("chunking_fingerprint_hash")
            == fixture_doc["chunking_fingerprint_hash"]
        ):
            continue

        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete(
            synchronize_session=False
        )
        for chunk in chunks:
            content = str(chunk["content"])
            metadata = dict(chunk.get("metadata") or {})
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    knowledge_base_id=doc.knowledge_base_id,
                    content=encryption_manager.encrypt(content),
                    embedding=chunk["embedding"],
                    chunk_index=int(chunk["chunk_index"]),
                    chunk_level=chunk.get("chunk_level") or "flat",
                    section_path=chunk.get("section_path"),
                    heading=chunk.get("heading"),
                    token_count=int(chunk.get("token_count") or 0),
                    metadata_=metadata,
                )
            )

        doc.status = "completed"
        doc.error_message = None
        doc.content_hash = fixture_doc["content_hash"]
        doc.embedding_model = DEMO_EMBEDDING_MODEL
        doc.updated_at = _now()
        meta = dict(doc.meta_info or {})
        meta["chunking_mode"] = fixture_doc["chunking_mode"]
        meta["chunking_fingerprint_hash"] = fixture_doc["chunking_fingerprint_hash"]
        meta["fixture_source"] = DEMO_KNOWLEDGE_FIXTURE_PATH.name
        doc.meta_info = meta
        db.add(doc)
        db.flush()


def _index_demo_documents_from_sources(
    db: Session,
    specs: tuple[DemoKnowledgeSeedSpec, ...],
    *,
    persist_fixture: bool = True,
) -> None:
    _require_seed_env("ENCRYPTION_KEY")

    from apps.gateway.services.ingestion.service import IngestionOrchestrator
    from apps.shared.utils.encryption import encryption_manager
    from apps.shared.utils.template_utils import count_tokens

    fixture_records: list[dict[str, Any]] = []
    for spec in specs:
        doc = db.get(Document, DOCUMENT_IDS[spec.key])
        if doc is None:
            raise RuntimeError(f"demo 문서 row가 없습니다: {spec.key}")

        orchestrator = IngestionOrchestrator(
            db,
            user_id=USER_IDS["admin"],
            chunk_size=doc.chunk_size,
            chunk_overlap=doc.chunk_overlap,
            ai_model=DEMO_EMBEDDING_MODEL,
        )
        raw_blocks = _extract_raw_blocks(db, doc)
        chunking_result = orchestrator._build_document_chunks(doc, raw_blocks)
        texts = [chunk["content"] for chunk in chunking_result.chunks]
        embeddings = _embed_text_batches(texts)

        db.query(DocumentChunk).filter(DocumentChunk.document_id == doc.id).delete(
            synchronize_session=False
        )
        fixture_records.append(
            {
                "record_type": "document",
                "key": spec.key,
                "filename": doc.filename,
                "content_hash": chunking_result.content_hash,
                "chunking_mode": chunking_result.chunking_mode,
                "chunking_fingerprint_hash": chunking_result.chunking_fingerprint,
                "chunk_size": doc.chunk_size,
                "chunk_overlap": doc.chunk_overlap,
                "source_filename": (doc.meta_info or {}).get("source_filename"),
                "source_available": bool((doc.meta_info or {}).get("source_available")),
                "legal_effective_date": (doc.meta_info or {}).get("legal_effective_date"),
            }
        )
        for index, (chunk, embedding) in enumerate(
            zip(chunking_result.chunks, embeddings)
        ):
            content = chunk["content"]
            metadata = dict(chunk.get("metadata") or {})
            metadata.update(
                {
                    "classification": spec.classification,
                    "tags": list(spec.tags),
                    "keywords": list(dict.fromkeys((*spec.keywords, spec.name))),
                    "source_type": "FILE",
                    "source_tier": spec.source_tier,
                    "source_hash": chunking_result.content_hash,
                    "chunk_level": chunk.get("chunk_level") or "flat",
                }
            )
            token_count = chunk.get("token_count") or count_tokens(content)
            db.add(
                DocumentChunk(
                    document_id=doc.id,
                    knowledge_base_id=doc.knowledge_base_id,
                    content=encryption_manager.encrypt(content),
                    embedding=embedding,
                    chunk_index=index,
                    chunk_level=chunk.get("chunk_level") or "flat",
                    section_path=chunk.get("section_path"),
                    heading=chunk.get("heading"),
                    token_count=token_count,
                    metadata_=metadata,
                )
            )
            fixture_records.append(
                {
                    "record_type": "chunk",
                    "document_key": spec.key,
                    "chunk_index": index,
                    "content": content,
                    "embedding": embedding,
                    "token_count": token_count,
                    "metadata": metadata,
                    "chunk_level": chunk.get("chunk_level") or "flat",
                    "section_path": chunk.get("section_path"),
                    "heading": chunk.get("heading"),
                }
            )

        doc.status = "completed"
        doc.error_message = None
        doc.content_hash = chunking_result.content_hash
        doc.embedding_model = DEMO_EMBEDDING_MODEL
        doc.updated_at = _now()
        meta = dict(doc.meta_info or {})
        meta["chunking_mode"] = chunking_result.chunking_mode
        meta["chunking_fingerprint_hash"] = chunking_result.chunking_fingerprint
        if persist_fixture:
            meta["fixture_source"] = DEMO_KNOWLEDGE_FIXTURE_PATH.name
        else:
            meta.pop("fixture_source", None)
            meta["indexed_from_bundled_source"] = True
        doc.meta_info = meta
        db.add(doc)
        db.flush()

    if persist_fixture:
        _write_demo_knowledge_fixture(fixture_records)


def _index_demo_documents(
    db: Session,
    specs: tuple[DemoKnowledgeSeedSpec, ...],
    fixture: dict[str, Any] | None,
) -> None:
    if fixture is not None:
        _insert_demo_chunks_from_fixture(db, specs, fixture)
        return
    _index_demo_documents_from_sources(db, specs)


def validate_demo_seed_prerequisites() -> None:
    _require_seed_env("ENCRYPTION_KEY")
    for spec in ONBOARDING_PDF_SPECS:
        _resolve_onboarding_pdf(spec)
    if _runtime_openai_credential_requested():
        _require_seed_env("OPENAI_API_KEY")
    if _demo_knowledge_fixture_or_none() is not None:
        return
    _require_seed_env("OPENAI_API_KEY")
    for spec in LEGAL_DOCUMENT_SPECS:
        _resolve_legal_pdf(spec)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _upsert_by_id(db: Session, model: type, row_id: uuid.UUID, values: dict[str, Any]):
    # setattr는 모델에 없는 key도 조용히 받아들이므로 seed 오타를 여기서 즉시 실패시킨다.
    unknown_keys = sorted(set(values) - set(sa_inspect(model).attrs.keys()))
    if unknown_keys:
        raise ValueError(
            f"{model.__name__} seed values contain unmapped attributes: {unknown_keys}"
        )
    row = db.get(model, row_id)
    if row is None:
        row = model(id=row_id)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    return row


_MANAGED_APP_SECRET_STATE_FIELDS = (
    "auth_secret_verifier",
    "auth_secret_verifier_version",
    "auth_secret_generation",
    "auth_secret_previous_verifier",
    "auth_secret_previous_verifier_version",
    "auth_secret_previous_valid_until",
    "auth_secret_rotated_at",
)


def _has_valid_managed_app_secret_state(app: App) -> bool:
    generation = app.auth_secret_generation
    if (
        not isinstance(generation, int)
        or isinstance(generation, bool)
        or generation <= 0
        or not app_auth_secret_verifier_state_is_valid(
            app.auth_secret_verifier,
            app.auth_secret_verifier_version,
        )
        or not isinstance(app.auth_secret_rotated_at, datetime)
        or app.auth_secret_rotated_at.tzinfo is None
    ):
        return False

    previous_fields = (
        app.auth_secret_previous_verifier,
        app.auth_secret_previous_verifier_version,
        app.auth_secret_previous_valid_until,
    )
    if all(value is None for value in previous_fields):
        return True
    return (
        app_auth_secret_verifier_state_is_valid(
            app.auth_secret_previous_verifier,
            app.auth_secret_previous_verifier_version,
        )
        and isinstance(app.auth_secret_previous_valid_until, datetime)
        and app.auth_secret_previous_valid_until.tzinfo is not None
    )


def _app_seed_values(
    existing_app: App | None,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Keep a user-rotated verifier state when a normal seed upsert reruns."""

    if existing_app is None or not _has_valid_managed_app_secret_state(existing_app):
        return values

    preserved = values.copy()
    for field in _MANAGED_APP_SECRET_STATE_FIELDS:
        preserved.pop(field, None)
    # A valid verifier is the authority. Clearing a leftover legacy raw value is safe.
    preserved["auth_secret"] = None
    return preserved


def _icon(content: str, background_color: str = "#EFF6FF") -> dict[str, str]:
    return {
        "type": "emoji",
        "content": content,
        "background_color": background_color,
    }


def _base_node_data(
    title: str,
    description: str,
    display_number: int,
    visible_properties: list[str] | None = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "displayNumber": display_number,
        "visibleProperties": visible_properties or [],
    }


def _node(
    node_id: str,
    node_type: str,
    x: int,
    y: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": node_type,
        "position": {"x": x, "y": y},
        "data": data,
    }


def _edge(
    edge_id: str,
    source: str,
    target: str,
    source_handle: str | None = None,
) -> dict[str, Any]:
    edge = {"id": edge_id, "source": source, "target": target}
    if source_handle:
        edge["sourceHandle"] = source_handle
    return edge


def _knowledge_base_ref(key: str) -> dict[str, str]:
    if key == "hr":
        return {"id": str(KB_IDS[key]), "name": "사내 휴가 정책 지식베이스"}
    if key == "hr_welfare":
        return {"id": str(KB_IDS[key]), "name": "사내 복지 정책 지식베이스"}
    onboarding_spec = ONBOARDING_KB_SPECS.get(key)
    if onboarding_spec is not None:
        return {"id": str(KB_IDS[key]), "name": onboarding_spec[0]}
    spec = next((item for item in DEMO_DOCUMENT_SPECS if item.key == key), None)
    if spec is None:
        raise KeyError(f"Unknown demo knowledge base key: {key}")
    return {"id": str(KB_IDS[key]), "name": spec.name}


def _hr_bot_knowledge_base_refs() -> list[dict[str, str]]:
    return [
        _knowledge_base_ref(key)
        for key in (
            "internal_onboarding",
            "internal_leave_attendance",
            "internal_benefits",
            "internal_privacy_hr_records",
            "internal_developer_onboarding_rules",
            "internal_developer_commit_convention",
            "internal_developer_compensation_band",
            "internal_compensation_access_policy",
            "legal_labor_standards",
            "legal_equal_employment",
            "legal_equal_employment_enforcement_decree",
            "legal_privacy",
        )
    ]


def _hr_bot_graph() -> dict[str, Any]:
    return {
        "nodes": [
            _node(
                "start-question",
                "startNode",
                120,
                120,
                {
                    **_base_node_data("직원 질문 입력", "직원의 사내 문서 질문을 입력받습니다.", 1),
                    "triggerType": "manual",
                    "trigger_type": "manual",
                    "variables": [
                        {
                            "id": "question",
                            "name": "question",
                            "label": "질문",
                            "type": "paragraph",
                            "required": True,
                            "maxLength": 1200,
                            "max_length": 1200,
                        }
                    ],
                },
            ),
            _node(
                "llm-answer",
                "llmNode",
                540,
                120,
                {
                    **_base_node_data(
                        "사내 문서 기반 답변",
                        "인사 지식베이스를 참고해 답변을 생성합니다.",
                        2,
                        ["model_id", "knowledgeBases", "user_prompt"],
                    ),
                    "provider": "openai",
                    "model_id": DEMO_CHAT_MINI_MODEL,
                    "system_prompt": "사내 복지, 휴가, 인사 정책 문서를 근거로 간결하게 답변합니다.",
                    "user_prompt": "질문: {{ question }}",
                    "referenced_variables": [
                        {
                            "name": "question",
                            "value_selector": ["start-question", "question"],
                        }
                    ],
                    "knowledgeBases": _hr_bot_knowledge_base_refs(),
                    "scoreThreshold": 0.3,
                    "topK": 4,
                    "parameters": {"temperature": 0.2, "max_tokens": 800},
                },
            ),
            _node(
                "answer",
                "answerNode",
                960,
                120,
                {
                    **_base_node_data("응답", "최종 답변을 반환합니다.", 3),
                    "outputs": [
                        {
                            "variable": "answer_text",
                            "label": "답변",
                            "value_selector": ["llm-answer", "text"],
                        }
                    ],
                },
            ),
        ],
        "edges": [
            _edge("edge-start-llm", "start-question", "llm-answer"),
            _edge("edge-llm-answer", "llm-answer", "answer"),
        ],
        "viewport": {"x": 40, "y": 80, "zoom": 0.85},
    }


def _department_onboarding_knowledge_base_refs() -> list[dict[str, str]]:
    return [
        _knowledge_base_ref(key)
        for key in (
            "internal_onboarding",
            "internal_developer_onboarding_rules",
            "internal_planning_onboarding_guide",
        )
    ]


def _department_onboarding_chatbot_graph() -> dict[str, Any]:
    return {
        "nodes": [
            _node(
                "start-question",
                "startNode",
                120,
                120,
                {
                    **_base_node_data(
                        "온보딩 질문 입력",
                        "로그인 사용자의 부서별 온보딩 질문을 입력받습니다.",
                        1,
                    ),
                    "triggerType": "manual",
                    "trigger_type": "manual",
                    "variables": [
                        {
                            "id": "question",
                            "name": "question",
                            "label": "질문",
                            "type": "paragraph",
                            "required": True,
                            "maxLength": 1200,
                            "max_length": 1200,
                        }
                    ],
                },
            ),
            _node(
                "llm-answer",
                "llmNode",
                540,
                120,
                {
                    **_base_node_data(
                        "권한 기반 온보딩 답변",
                        "현재 사용자가 사용할 수 있는 공통·부서 문서만 근거로 답변합니다.",
                        2,
                        ["model_id", "knowledgeBases", "user_prompt"],
                    ),
                    "provider": "openai",
                    "model_id": DEMO_CHAT_MINI_MODEL,
                    "system_prompt": (
                        "현재 사용자에게 허용된 온보딩 문서만 근거로 간결하게 답변합니다. "
                        "근거가 없으면 추측하지 말고 확인 가능한 문서가 없다고 안내합니다."
                    ),
                    "user_prompt": "질문: {{ question }}",
                    "referenced_variables": [
                        {
                            "name": "question",
                            "value_selector": ["start-question", "question"],
                        }
                    ],
                    "knowledgeBases": _department_onboarding_knowledge_base_refs(),
                    "scoreThreshold": 0.3,
                    "topK": 3,
                    "answerGroundingCheck": "basic",
                    "parameters": {"temperature": 0.2, "max_tokens": 700},
                },
            ),
            _node(
                "answer",
                "answerNode",
                960,
                120,
                {
                    **_base_node_data("응답", "최종 답변을 반환합니다.", 3),
                    "outputs": [
                        {
                            "variable": "answer_text",
                            "label": "답변",
                            "value_selector": ["llm-answer", "text"],
                        }
                    ],
                },
            ),
        ],
        "edges": [
            _edge("edge-start-llm", "start-question", "llm-answer"),
            _edge("edge-llm-answer", "llm-answer", "answer"),
        ],
        "viewport": {"x": 40, "y": 80, "zoom": 0.85},
    }


def _team_onboarding_access_control_graph() -> dict[str, Any]:
    knowledge_bases = [
        _knowledge_base_ref(spec.key) for spec in ONBOARDING_PDF_SPECS
    ]
    return {
        "nodes": [
            _node(
                "start-question",
                "startNode",
                120,
                120,
                {
                    **_base_node_data(
                        "온보딩 질문 입력",
                        "로그인한 사용자의 팀별 온보딩 질문을 입력받습니다.",
                        1,
                    ),
                    "triggerType": "manual",
                    "trigger_type": "manual",
                    "variables": [
                        {
                            "id": "question",
                            "name": "question",
                            "label": "질문",
                            "type": "paragraph",
                            "required": True,
                            "maxLength": 1200,
                            "max_length": 1200,
                        }
                    ],
                },
            ),
            _node(
                "llm-answer",
                "llmNode",
                540,
                120,
                {
                    **_base_node_data(
                        "권한 기반 온보딩 검색 및 답변",
                        "실행 사용자의 KB 권한으로 검색 후보를 제한한 뒤 답변합니다.",
                        2,
                        ["model_id", "knowledgeBases", "user_prompt"],
                    ),
                    "provider": "openai",
                    "model_id": DEMO_CHAT_MINI_MODEL,
                    "system_prompt": (
                        "현재 로그인한 사용자에게 허용된 온보딩 문서만 근거로 답변합니다. "
                        "첫 주 일정과 접근 권한 신청 절차를 구분하고, 사용한 문서의 파일명을 "
                        "출처로 표시합니다. 검색 근거가 없으면 추측하지 말고 현재 권한으로 "
                        "확인 가능한 문서가 없다고 안전하게 안내합니다. 권한이 없는 다른 팀 "
                        "문서의 존재나 세부 내용을 추론하거나 노출하지 않습니다."
                    ),
                    "user_prompt": "질문: {{ question }}",
                    "referenced_variables": [
                        {
                            "name": "question",
                            "value_selector": ["start-question", "question"],
                        }
                    ],
                    "knowledgeBases": knowledge_bases,
                    "scoreThreshold": 0.3,
                    "topK": 4,
                    "parameters": {"temperature": 0.1, "max_tokens": 900},
                },
            ),
            _node(
                "answer",
                "answerNode",
                960,
                120,
                {
                    **_base_node_data("응답", "권한이 적용된 최종 답변을 반환합니다.", 3),
                    "outputs": [
                        {
                            "variable": "answer_text",
                            "label": "답변",
                            "value_selector": ["llm-answer", "text"],
                        }
                    ],
                },
            ),
        ],
        "edges": [
            _edge("edge-start-llm", "start-question", "llm-answer"),
            _edge("edge-llm-answer", "llm-answer", "answer"),
        ],
        "viewport": {"x": 40, "y": 80, "zoom": 0.85},
    }


def _team_onboarding_adaptive_routing_graph() -> dict[str, Any]:
    """??? RAG workflow? ?? ?? ?? ??? ??? ????."""
    graph = copy.deepcopy(_team_onboarding_access_control_graph())
    llm_node = next(node for node in graph["nodes"] if node["id"] == "llm-answer")
    data = llm_node["data"]
    data["model_id"] = DEMO_ONBOARDING_ROUTER_MODEL
    data["fallback_model_id"] = None
    data["auto_model_routing"] = True
    data["model_routing_context"] = {
        "customer_facing": False,
        "node_task": "employee_onboarding_guidance",
        "risk_level": "low",
    }
    data["model_routing_policy"] = {
        "refresh": {"refresh_every_runs": 5},
        "validation_budget_usd": 3.0,
        "excluded_model_ids": ["gpt-5.6-sol"],
    }
    return graph



def _ticket_ops_graph() -> dict[str, Any]:
    return {
        "nodes": [
            _node(
                "webhook-ticket",
                "webhookTrigger",
                120,
                220,
                {
                    **_base_node_data("고객 티켓 수신", "고객지원 티켓 payload를 수신합니다.", 1),
                    "variable_mappings": [
                        {"json_path": "message", "variable_name": "message"},
                        {"json_path": "customerTier", "variable_name": "customerTier"},
                    ],
                },
            ),
            _node(
                "llm-triage",
                "llmNode",
                540,
                220,
                {
                    **_base_node_data("티켓 처리 판단", "티켓 유형, 심각도, 승인 필요 여부를 판단합니다.", 2),
                    "provider": "openai",
                    "model_id": DEMO_CHAT_MODEL,
                    "system_prompt": (
                        "고객지원 티켓을 처리하는 AI입니다. 반드시 JSON object 하나만 출력하세요. "
                        "필드는 \"긴급도\" boolean, \"답변 초안\" string 두 개만 사용합니다. "
                        "답변 초안은 고객에게 보낼 수 있는 3문장 이내의 간결한 문장으로 작성하세요."
                    ),
                    "user_prompt": (
                        "고객 등급: {{ customerTier }}\n"
                        "문의: {{ message }}\n"
                        "승인 필요 여부와 고객 답변 초안을 작성하세요."
                    ),
                    "referenced_variables": [
                        {
                            "name": "customerTier",
                            "value_selector": ["webhook-ticket", "customerTier"],
                        },
                        {
                            "name": "message",
                            "value_selector": ["webhook-ticket", "message"],
                        },
                    ],
                    "knowledgeBases": [
                        _knowledge_base_ref("internal_cost_optimization_playbook")
                    ],
                    "parameters": {"temperature": 0.2, "max_tokens": 700},
                    "output_format": {
                        "type": "json",
                        "schema": {
                            "type": "object",
                            "properties": {
                                "긴급도": {"type": "boolean"},
                                "답변 초안": {"type": "string"},
                            },
                            "required": ["긴급도", "답변 초안"],
                        },
                    },
                },
            ),
            _node(
                "extract-ticket",
                "variableExtractionNode",
                960,
                220,
                {
                    **_base_node_data("처리 결과 추출", "LLM JSON 문자열을 후속 분기 변수로 추출합니다.", 3),
                    "source_selector": ["llm-triage", "text"],
                    "mappings": [
                        {"name": "approvalRequired", "json_path": "긴급도"},
                        {"name": "mailDraft", "json_path": "답변 초안"},
                    ],
                },
            ),
            _node(
                "condition-approval",
                "conditionNode",
                1380,
                220,
                {
                    **_base_node_data("승인 필요 분기", "승인 요청 여부로 분기합니다.", 4),
                    "cases": [
                        {
                            "id": "approval",
                            "case_name": "승인 필요",
                            "logical_operator": "or",
                            "conditions": [
                                {
                                    "id": "cond-approval-required",
                                    "variable_selector": [
                                        "extract-ticket",
                                        "approvalRequired",
                                    ],
                                    "operator": "equals",
                                    "value": True,
                                }
                            ],
                        }
                    ],
                },
            ),
            _node(
                "template-approval",
                "templateNode",
                1800,
                80,
                {
                    **_base_node_data("승인 요청 메시지", "CS 리드 승인 요청 메시지를 만듭니다.", 5),
                    "template": (
                        "안녕하세요,\n\n"
                        "아래 고객 요청에 대한 확인을 부탁드립니다.\n\n"
                        "**고객 등급:** {{ customerTier }}  \n"
                        "**고객 문의:** {{ message }}  \n"
                        "**고객 초안:**  \n"
                        "{{ mailDraft }}\n\n"
                        "감사합니다."
                    ),
                    "variables": [
                        {
                            "name": "mailDraft",
                            "value_selector": ["extract-ticket", "mailDraft"],
                        },
                        {
                            "name": "customerTier",
                            "value_selector": ["webhook-ticket", "customerTier"],
                        },
                        {
                            "name": "message",
                            "value_selector": ["webhook-ticket", "message"],
                        },
                    ],
                },
            ),
            _node(
                "template-reply",
                "templateNode",
                1800,
                360,
                {
                    **_base_node_data("고객 답변 초안", "고객에게 보낼 답변을 정리합니다.", 6),
                    "template": (
                        "안녕하세요,\n\n"
                        "고객님의 소중한 의견에 감사드립니다. 저희는 항상 고객님의 목소리를 귀 기울여 듣고 있습니다.\n\n"
                        "아래 내용을 확인하시고, 추가적인 질문이나 요청사항이 있으시면 언제든지 연락 주시기 바랍니다.\n\n"
                        "{{ mailDraft }}\n\n"
                        "감사합니다.\n\n"
                        "좋은 하루 되세요!"
                    ),
                    "variables": [
                        {
                            "name": "mailDraft",
                            "value_selector": ["extract-ticket", "mailDraft"],
                        }
                    ],
                },
            ),
            _node(
                "answer-approval",
                "answerNode",
                2220,
                80,
                {
                    **_base_node_data("승인 요청 결과", "승인 요청 branch 결과를 반환합니다.", 7),
                    "outputs": [
                        {
                            "variable": "answer_text",
                            "label": "처리 결과",
                            "value_selector": ["template-approval", "text"],
                        }
                    ],
                },
            ),
            _node(
                "answer-reply",
                "answerNode",
                2220,
                360,
                {
                    **_base_node_data("고객 답변 결과", "고객 답변 branch 결과를 반환합니다.", 8),
                    "outputs": [
                        {
                            "variable": "answer_text",
                            "label": "처리 결과",
                            "value_selector": ["template-reply", "text"],
                        }
                    ],
                },
            ),
        ],
        "edges": [
            _edge("edge-webhook-llm", "webhook-ticket", "llm-triage"),
            _edge("edge-llm-extract", "llm-triage", "extract-ticket"),
            _edge("edge-extract-condition", "extract-ticket", "condition-approval"),
            _edge(
                "edge-condition-approval",
                "condition-approval",
                "template-approval",
                "approval",
            ),
            _edge("edge-condition-reply", "condition-approval", "template-reply", "default"),
            _edge("edge-approval-answer", "template-approval", "answer-approval"),
            _edge("edge-reply-answer", "template-reply", "answer-reply"),
        ],
        "viewport": {"x": 20, "y": 70, "zoom": 0.48},
    }


def _model_router_ticket_ops_graph() -> dict[str, Any]:
    """?? ?? workflow? ?? ??? ?? ?? ??? ??? ????."""
    graph = _ticket_ops_graph()
    for node in graph["nodes"]:
        if node["id"] != "llm-triage":
            continue
        node["data"].update(
            {
                "title": "??/SLA ?? ??",
                "description": "?? ??, SLA, ?? ?? ??? ????? ?????.",
                "model_id": DEMO_MODEL_ROUTER_FALLBACK_MODEL,
                "fallback_model_id": DEMO_MODEL_ROUTER_BALANCED_MODEL,
                "auto_model_routing": True,
                "model_routing_context": {
                    "customer_facing": True,
                    "node_task": "customer_support_triage",
                    "risk_level": "medium",
                },
                "model_routing_policy": {
                    "refresh": {"refresh_every_runs": 10},
                    "validation_budget_usd": 3.0,
                    "excluded_model_ids": ["gpt-5.6-sol"],
                },
            }
        )
    return graph



def _enterprise_request_routing_graph() -> dict[str, Any]:
    """사내 업무 요청을 RAG와 입력군별 자동 모델 라우팅으로 처리한다."""
    graph = copy.deepcopy(_ticket_ops_graph())
    webhook_node = next(
        node for node in graph["nodes"] if node["id"] == "webhook-ticket"
    )
    webhook_node["id"] = "webhook-request"
    webhook_node["data"].update(
        {
            "title": "사내 업무 요청 수신",
            "description": "부서, 요청자 역할과 업무 문의를 수신합니다.",
            "variable_mappings": [
                {"json_path": "query", "variable_name": "query"},
                {"json_path": "department", "variable_name": "department"},
                {"json_path": "requesterRole", "variable_name": "requesterRole"},
                {"json_path": "locale", "variable_name": "locale"},
            ],
        }
    )

    llm_node = next(node for node in graph["nodes"] if node["id"] == "llm-triage")
    llm_node["id"] = "llm-request"
    llm_node["data"].update(
        {
            "title": "업무 요청 분류 및 답변",
            "description": "사내 문서를 검색하고 요청 위험도에 맞는 모델로 답변합니다.",
            "model_id": DEMO_ONBOARDING_ROUTER_MODEL,
            "fallback_model_id": None,
            "auto_model_routing": True,
            "model_routing_context": {
                "customer_facing": False,
                "node_task": "enterprise_internal_request",
                "risk_level": "medium",
            },
            "model_routing_policy": {
                "refresh": {"refresh_every_runs": 10},
                "validation_budget_usd": 3.0,
                "excluded_model_ids": ["gpt-5.6-sol"],
            },
            "knowledgeBases": [
                _knowledge_base_ref(key)
                for key in (
                    "internal_onboarding",
                    "internal_privacy_hr_records",
                    "internal_budget_alert_runbook",
                    "internal_cost_optimization_playbook",
                    "internal_developer_onboarding_rules",
                    "onboarding_finance",
                )
            ],
            "scoreThreshold": 0.3,
            "topK": 5,
            "system_prompt": (
                "기업 내부 업무 요청을 처리하는 AI입니다. 현재 실행 주체에게 허용된 사내 문서만 "
                "근거로 답변하고, 근거가 없으면 추측하지 않습니다. 반드시 JSON object 하나만 "
                "출력하며 필드는 '입력군', '승인 필요', '답변'만 사용합니다. 보안·개인정보 사고와 "
                "재무 지급 승인은 보수적으로 판단합니다."
            ),
            "user_prompt": (
                "부서: {{ department }}\n"
                "요청자 역할: {{ requesterRole }}\n"
                "언어: {{ locale }}\n"
                "업무 요청: {{ query }}\n"
                "요청 유형을 분류하고 승인 필요 여부와 실행 가능한 답변을 작성하세요."
            ),
            "referenced_variables": [
                {
                    "name": name,
                    "value_selector": ["webhook-request", name],
                }
                for name in ("department", "requesterRole", "locale", "query")
            ],
            "parameters": {"temperature": 0.15, "max_tokens": 900},
            "output_format": {
                "type": "json",
                "schema": {
                    "type": "object",
                    "properties": {
                        "입력군": {"type": "string"},
                        "승인 필요": {"type": "boolean"},
                        "답변": {"type": "string"},
                    },
                    "required": ["입력군", "승인 필요", "답변"],
                },
            },
        }
    )

    extract_node = next(
        node for node in graph["nodes"] if node["id"] == "extract-ticket"
    )
    extract_node["data"].update(
        {
            "title": "업무 처리 결과 추출",
            "description": "LLM JSON에서 승인 여부와 답변을 추출합니다.",
            "source_selector": ["llm-request", "text"],
            "mappings": [
                {"name": "approvalRequired", "json_path": "승인 필요"},
                {"name": "mailDraft", "json_path": "답변"},
            ],
        }
    )

    condition_node = next(
        node for node in graph["nodes"] if node["id"] == "condition-approval"
    )
    condition_node["data"].update(
        {
            "title": "검토 필요 분기",
            "description": "보안·재무 등 승인 필요 요청을 검토 경로로 분기합니다.",
        }
    )

    approval_template = next(
        node for node in graph["nodes"] if node["id"] == "template-approval"
    )
    approval_template["data"].update(
        {
            "title": "담당 부서 검토 요청",
            "description": "승인이 필요한 업무 요청을 담당 부서에 전달합니다.",
            "template": (
                "담당 부서 검토가 필요한 요청입니다.\n\n"
                "부서: {{ department }}\n"
                "요청자 역할: {{ requesterRole }}\n"
                "요청: {{ query }}\n\n"
                "AI 검토 결과:\n{{ mailDraft }}"
            ),
            "variables": [
                {"name": "mailDraft", "value_selector": ["extract-ticket", "mailDraft"]},
                {"name": "department", "value_selector": ["webhook-request", "department"]},
                {
                    "name": "requesterRole",
                    "value_selector": ["webhook-request", "requesterRole"],
                },
                {"name": "query", "value_selector": ["webhook-request", "query"]},
            ],
        }
    )

    reply_template = next(
        node for node in graph["nodes"] if node["id"] == "template-reply"
    )
    reply_template["data"].update(
        {
            "title": "사내 업무 안내",
            "description": "승인 없이 처리할 수 있는 업무 답변을 정리합니다.",
            "template": "{{ mailDraft }}",
        }
    )

    for edge in graph["edges"]:
        if edge["source"] == "webhook-ticket":
            edge["source"] = "webhook-request"
        if edge["source"] == "llm-triage":
            edge["source"] = "llm-request"
        if edge["target"] == "llm-triage":
            edge["target"] = "llm-request"
    return graph


def _test_inquiry_graph() -> dict[str, Any]:
    return {
        "nodes": [
            _node(
                "start-test",
                "startNode",
                120,
                120,
                {
                    **_base_node_data("테스트 입력", "자유 테스트용 문의를 입력받습니다.", 1),
                    "triggerType": "manual",
                    "trigger_type": "manual",
                    "variables": [
                        {
                            "id": "message",
                            "name": "message",
                            "label": "메시지",
                            "type": "paragraph",
                            "required": True,
                        }
                    ],
                },
            ),
            _node(
                "template-test",
                "templateNode",
                540,
                120,
                {
                    **_base_node_data("테스트 응답", "입력 내용을 응답으로 정리합니다.", 2),
                    "template": "테스트 응답입니다.\n입력: {{ message }}",
                    "variables": [
                        {
                            "name": "message",
                            "value_selector": ["start-test", "message"],
                        }
                    ],
                },
            ),
            _node(
                "answer-test",
                "answerNode",
                960,
                120,
                {
                    **_base_node_data("응답", "테스트 응답을 반환합니다.", 3),
                    "outputs": [
                        {
                            "variable": "answer_text",
                            "label": "답변",
                            "value_selector": ["template-test", "text"],
                        }
                    ],
                },
            ),
        ],
        "edges": [
            _edge("edge-start-template", "start-test", "template-test"),
            _edge("edge-template-answer", "template-test", "answer-test"),
        ],
        "viewport": {"x": 40, "y": 80, "zoom": 0.85},
    }


def _input_schema(variable_name: str, label: str = "입력") -> dict[str, Any]:
    return {"variables": [{"name": variable_name, "type": "text", "label": label}]}


def _input_schema_from_graph(graph: dict[str, Any]) -> dict[str, Any] | None:
    """배포 입력 schema가 graph의 시작 노드 계약과 어긋나지 않게 생성한다."""
    for node in graph.get("nodes", []) if isinstance(graph, dict) else []:
        if not isinstance(node, dict):
            continue
        node_data = node.get("data")
        if not isinstance(node_data, dict):
            continue

        if node.get("type") == "startNode":
            variables = node_data.get("variables") or []
            normalized = [
                {
                    "name": variable.get("name", ""),
                    "type": variable.get("type", "string"),
                    "label": variable.get("label", variable.get("name", "")),
                }
                for variable in variables
                if isinstance(variable, dict) and variable.get("name")
            ]
            return {"variables": normalized} if normalized else None

        if node.get("type") == "webhookTrigger":
            mappings = node_data.get("variable_mappings") or []
            normalized = [
                {
                    "name": mapping.get("variable_name", ""),
                    "type": "text",
                    "label": mapping.get("label", mapping.get("variable_name", "")),
                }
                for mapping in mappings
                if isinstance(mapping, dict) and mapping.get("variable_name")
            ]
            return {"variables": normalized} if normalized else None

    return None


def _output_schema() -> dict[str, Any]:
    return {"outputs": [{"variable": "answer_text", "label": "답변"}]}


def _seed_users_and_org(db: Session) -> None:
    _adopt_existing_demo_user_ids(db)
    hashed_password = hash_password(DEMO_PASSWORD)
    for spec in USER_SPECS:
        user = _upsert_by_id(
            db,
            User,
            USER_IDS[spec.key],
            {
                "email": spec.email,
                "name": spec.name,
                "password": hashed_password,
                "social_provider": "none",
                "social_id": None,
                "avatar_url": None,
                "deactivated_at": None,
            },
        )
        if spec.membership_state == ORGANIZATION_MEMBERSHIP_SUSPENDED:
            user.deactivated_at = None

    _upsert_by_id(
        db,
        Organization,
        ORG_ID,
        {
            "name": "노디즈 데모 조직",
            "options": _demo_options("organization"),
            "flags": 0,
            "created_by": USER_IDS["admin"],
            "managed_by": USER_IDS["admin"],
            "is_active": True,
            "deactivated_at": None,
        },
    )
    db.flush()

    for spec in USER_SPECS:
        membership_id = _uuid(1000 + list(USER_IDS).index(spec.key))
        accepted_at = (
            _now()
            if spec.membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE
            else None
        )
        removed_at = (
            _now()
            if spec.membership_state == ORGANIZATION_MEMBERSHIP_REMOVED
            else None
        )
        _upsert_by_id(
            db,
            OrganizationMembership,
            membership_id,
            {
                "organization_id": ORG_ID,
                "user_id": USER_IDS[spec.key],
                "membership_state": spec.membership_state,
                "organization_auth_state": spec.organization_auth_state,
                "invited_by": USER_IDS["admin"],
                "invited_at": _now() - timedelta(days=7),
                "accepted_at": accepted_at,
                "removed_at": removed_at,
                "options": _demo_options(f"organization-membership-{spec.key}"),
                "flags": 0,
            },
        )


def _seed_teams_and_memberships(db: Session) -> None:
    for key, (name, description) in TEAM_SPECS.items():
        _upsert_by_id(
            db,
            Team,
            TEAM_IDS[key],
            {
                "organization_id": ORG_ID,
                "name": name,
                "description": description,
                "created_by": USER_IDS["admin"],
                "managed_by": USER_IDS["admin"],
                "is_active": True,
                "is_auto_add": False,
                "deactivated_at": None,
                "options": _demo_options(f"team-{key}"),
                "flags": 0,
            },
        )
    db.flush()

    membership_index = 0
    for spec in USER_SPECS:
        for team_key in spec.teams:
            _upsert_by_id(
                db,
                TeamMembership,
                _uuid(1100 + membership_index),
                {
                    "grantee_organization_id": ORG_ID,
                    "team_id": TEAM_IDS[team_key],
                    "user_id": USER_IDS[spec.key],
                    "assigned_by": USER_IDS["admin"],
                    "options": _demo_options(f"team-membership-{spec.key}-{team_key}"),
                    "flags": 0,
                },
            )
            membership_index += 1


def _demo_team_knowledge_permission_specs() -> list[tuple[str, str, str]]:
    knowledge_permission_specs: list[tuple[str, str, str]] = []
    for kb_key in (
        "legal_labor_standards",
        "legal_equal_employment",
        "legal_equal_employment_enforcement_decree",
        "legal_privacy",
        "legal_occupational_safety",
        "legal_retirement_benefits",
        "legal_fair_hiring",
    ):
        knowledge_permission_specs.extend(
            [
                (kb_key, "platform_admin", "manager"),
                (kb_key, "hr_knowledge_users", "operator"),
                (kb_key, "ai_builder_onboarding", "operator"),
                (kb_key, "customer_support_ops", "operator"),
            ]
        )
    for kb_key in (
        "internal_onboarding",
        "internal_leave_attendance",
        "internal_benefits",
        "internal_developer_onboarding_rules",
        "internal_developer_commit_convention",
        "internal_developer_compensation_band",
    ):
        knowledge_permission_specs.extend(
            [
                (kb_key, "platform_admin", "manager"),
                (kb_key, "hr_knowledge_users", "operator"),
                (kb_key, "ai_builder_onboarding", "operator"),
            ]
        )
    knowledge_permission_specs.extend(
        [
            ("internal_privacy_hr_records", "platform_admin", "manager"),
            ("internal_privacy_hr_records", "hr_knowledge_users", "operator"),
            ("internal_compensation_access_policy", "platform_admin", "manager"),
            ("internal_compensation_access_policy", "hr_knowledge_users", "operator"),
            ("internal_compensation_access_policy", "ai_builder_onboarding", "operator"),
            ("internal_budget_alert_runbook", "platform_admin", "manager"),
            ("internal_budget_alert_runbook", "customer_support_ops", "operator"),
            ("internal_cost_optimization_playbook", "platform_admin", "manager"),
            ("internal_cost_optimization_playbook", "customer_support_ops", "operator"),
            ("internal_onboarding", "department_development", "operator"),
            ("internal_onboarding", "department_planning", "operator"),
            (
                "internal_developer_onboarding_rules",
                "department_development",
                "operator",
            ),
            (
                "internal_planning_onboarding_guide",
                "platform_admin",
                "manager",
            ),
            (
                "internal_planning_onboarding_guide",
                "department_planning",
                "operator",
            ),
        ]
    )
    knowledge_permission_specs.extend(
        (kb_key, "tester_builder", "operator")
        for kb_key in (
            "internal_onboarding",
            "internal_leave_attendance",
            "internal_benefits",
        )
    )
    knowledge_permission_specs.extend(
        [
            ("onboarding_company_common", "onboarding_platform", "operator"),
            ("onboarding_company_common", "onboarding_sales", "operator"),
            ("onboarding_company_common", "onboarding_finance", "operator"),
            ("onboarding_company_common", "onboarding_people", "manager"),
            ("onboarding_platform", "onboarding_platform", "operator"),
            ("onboarding_platform", "onboarding_people", "manager"),
            ("onboarding_sales", "onboarding_sales", "operator"),
            ("onboarding_sales", "onboarding_people", "manager"),
            ("onboarding_finance", "onboarding_finance", "operator"),
            ("onboarding_finance", "onboarding_people", "manager"),
        ]
    )
    knowledge_permission_specs.extend(
        [
            ("hr_welfare", "hr_knowledge_users", "operator"),
            ("hr_welfare", "platform_admin", "manager"),
        ]
    )
    return knowledge_permission_specs


def _demo_team_knowledge_collection_permission_specs() -> list[tuple[str, str, str]]:
    collection_permission_specs: list[tuple[str, str, str]] = []
    for collection_key in ("legal_public", "internal_onboarding"):
        for team_key in (
            "platform_admin",
            "hr_knowledge_users",
            "ai_builder_onboarding",
            "customer_support_ops",
        ):
            for action in ("read", "route"):
                collection_permission_specs.append((collection_key, team_key, action))
    collection_permission_specs.extend(
        ("internal_onboarding", "tester_builder", action)
        for action in ("read", "route")
    )
    for team_key in (
        "onboarding_platform",
        "onboarding_sales",
        "onboarding_finance",
    ):
        collection_permission_specs.extend(
            ("team_onboarding_access_control", team_key, action)
            for action in ("read", "route")
        )
    collection_permission_specs.extend(
        ("team_onboarding_access_control", "onboarding_people", action)
        for action in ("read", "route", "manage", "sync")
    )
    for team_key in ("hr_knowledge_users", "platform_admin"):
        collection_permission_specs.extend(
            ("hr_policies", team_key, action) for action in ("read", "route")
        )
    return collection_permission_specs


def _seed_knowledge(db: Session) -> None:
    knowledge_fixture = _demo_knowledge_fixture_or_none()
    fixture_documents = (
        knowledge_fixture["documents"] if knowledge_fixture is not None else {}
    )

    _upsert_by_id(
        db,
        KnowledgeBase,
        KB_IDS["hr"],
        {
            "organization_id": ORG_ID,
            "name": "사내 휴가 정책 지식베이스",
            "description": "휴가 신청과 근태 유의 사항을 담은 데모 지식베이스",
            "embedding_model": "text-embedding-3-small",
            "top_k": 5,
            "similarity_threshold": 0.7,
            "sync_state": "manual",
            "lifecycle_state": "active",
            "user_id": USER_IDS["admin"],
        },
    )
    _upsert_by_id(
        db,
        KnowledgeBase,
        KB_IDS["hr_welfare"],
        {
            "organization_id": ORG_ID,
            "name": "사내 복지 정책 지식베이스",
            "description": "복지 포인트와 경조사 지원을 담은 데모 지식베이스",
            "embedding_model": "text-embedding-3-small",
            "top_k": 5,
            "similarity_threshold": 0.7,
            "sync_state": "manual",
            "lifecycle_state": "active",
            "user_id": USER_IDS["admin"],
        },
    )
    _upsert_by_id(
        db,
        KnowledgeBase,
        KB_IDS["finance"],
        {
            "organization_id": ORG_ID,
            "name": "재무 민감 문서 지식베이스",
            "description": "권한 대조를 위한 민감 문서 지식베이스",
            "embedding_model": "text-embedding-3-small",
            "top_k": 5,
            "similarity_threshold": 0.7,
            "user_id": USER_IDS["admin"],
        },
    )
    for spec in DEMO_DOCUMENT_SPECS:
        _upsert_by_id(
            db,
            KnowledgeBase,
            KB_IDS[spec.key],
            {
                "organization_id": ORG_ID,
                "name": spec.name,
                "description": spec.description,
                "embedding_model": DEMO_EMBEDDING_MODEL,
                "top_k": 5,
                "similarity_threshold": 0.7,
                "sync_state": "manual",
                "lifecycle_state": "active",
                "user_id": USER_IDS["admin"],
            },
        )
    for spec in ONBOARDING_PDF_SPECS:
        _upsert_by_id(
            db,
            KnowledgeBase,
            KB_IDS[spec.key],
            {
                "organization_id": ORG_ID,
                "name": spec.name,
                "description": spec.description,
                "safe_metadata": {
                    **_demo_options(f"bundled-onboarding-kb-{spec.key}"),
                    "source_filename": spec.filename,
                    "document_seed_mode": "bundled_pdf",
                },
                "embedding_model": DEMO_EMBEDDING_MODEL,
                "top_k": 5,
                "similarity_threshold": 0.3,
                "sync_state": "manual",
                "lifecycle_state": "active",
                "user_id": USER_IDS["onboarding_people_manager"],
            },
        )
    db.flush()

    _upsert_by_id(
        db,
        KnowledgeCollection,
        COLLECTION_IDS["legal_public"],
        {
            "organization_id": ORG_ID,
            "name": "공개 노동·온보딩 법령 컬렉션",
            "description": "익명 public-only 후보로 노출 가능한 국가법령정보센터 PDF 모음",
            "source_identity_id": None,
            "source_connector_ref": "local.legal-docs-labor",
            "is_system_managed": True,
            "sync_state": "manual",
            "lifecycle_state": "active",
            "safe_metadata": {
                **_demo_options("collection-legal-public"),
                "visibility": "public",
                "approved_by": str(USER_IDS["admin"]),
                "approved_source": "demo_seed",
                "revocation_behavior": "remove_from_public_collection",
            },
            "created_by": USER_IDS["admin"],
        },
    )
    _upsert_by_id(
        db,
        KnowledgeCollection,
        COLLECTION_IDS["internal_onboarding"],
        {
            "organization_id": ORG_ID,
            "name": "사내 온보딩·운영 문서 컬렉션",
            "description": "온보딩, HR 정책, LLMOps 운영 절차를 묶은 private 데모 컬렉션",
            "source_identity_id": None,
            "source_connector_ref": "local.demo-scenario-2026-07-08.internal-docs",
            "is_system_managed": True,
            "sync_state": "manual",
            "lifecycle_state": "active",
            "safe_metadata": {
                **_demo_options("collection-internal-onboarding"),
                "visibility": "private",
            },
            "created_by": USER_IDS["admin"],
        },
    )
    _upsert_by_id(
        db,
        KnowledgeCollection,
        COLLECTION_IDS["team_onboarding_access_control"],
        {
            "organization_id": ORG_ID,
            "name": "팀별 온보딩 접근 제어 문서",
            "description": "회사 공통 및 팀별 온보딩 PDF를 권한 경계별로 묶은 데모 컬렉션",
            "source_identity_id": None,
            "source_connector_ref": "local.demodata.team-onboarding-access-control",
            "is_system_managed": False,
            "sync_state": "manual",
            "lifecycle_state": "active",
            "safe_metadata": {
                **_demo_options("collection-team-onboarding-access-control"),
                "visibility": "private",
                "document_seed_mode": "bundled_pdf",
            },
            "created_by": USER_IDS["onboarding_people_manager"],
        },
    )
    _upsert_by_id(
        db,
        KnowledgeCollection,
        COLLECTION_IDS["hr_policies"],
        {
            "organization_id": ORG_ID,
            "name": "사내 휴가·복지 정책 컬렉션",
            "description": "독립된 휴가 정책과 복지 정책 지식베이스를 함께 검색하는 데모 컬렉션",
            "source_identity_id": None,
            "source_connector_ref": "local.demo.hr-policies",
            "is_system_managed": True,
            "sync_state": "manual",
            "lifecycle_state": "active",
            "safe_metadata": {
                **_demo_options("collection-hr-policies"),
                "visibility": "private",
            },
            "created_by": USER_IDS["admin"],
        },
    )
    db.flush()

    for rank, (item_key, kb_key) in enumerate(HR_POLICY_COLLECTION_ITEMS):
        _upsert_by_id(
            db,
            KnowledgeCollectionItem,
            COLLECTION_ITEM_IDS[item_key],
            {
                "organization_id": ORG_ID,
                "collection_id": COLLECTION_IDS["hr_policies"],
                "knowledge_base_id": KB_IDS[kb_key],
                "safe_source_path_ref": f"demo://hr-policies/{item_key}",
                "rank": rank,
                "safe_metadata": {
                    **_demo_options(f"collection-item-{item_key}"),
                    "source_tier": "private",
                },
            },
        )

    for rank, spec in enumerate(DEMO_DOCUMENT_SPECS):
        if spec.collection_key is None:
            continue
        _upsert_by_id(
            db,
            KnowledgeCollectionItem,
            COLLECTION_ITEM_IDS[spec.key],
            {
                "organization_id": ORG_ID,
                "collection_id": COLLECTION_IDS[spec.collection_key],
                "knowledge_base_id": KB_IDS[spec.key],
                "safe_source_path_ref": spec.filename,
                "rank": rank,
                "safe_metadata": {
                    **_demo_options(f"collection-item-{spec.key}"),
                    "classification": spec.classification,
                    "source_tier": spec.source_tier,
                },
            },
        )

    for rank, spec in enumerate(ONBOARDING_PDF_SPECS):
        _upsert_by_id(
            db,
            KnowledgeCollectionItem,
            COLLECTION_ITEM_IDS[spec.key],
            {
                "organization_id": ORG_ID,
                "collection_id": COLLECTION_IDS[
                    "team_onboarding_access_control"
                ],
                "knowledge_base_id": KB_IDS[spec.key],
                "safe_source_path_ref": spec.filename,
                "rank": rank,
                "safe_metadata": {
                    **_demo_options(f"collection-item-{spec.key}"),
                    "source_filename": spec.filename,
                    "document_seed_mode": "bundled_pdf",
                },
            },
        )

    document_specs = {
        "hr_leave": (
            KB_IDS[LEGACY_DEMO_DOCUMENT_KB_KEYS["hr_leave"]],
            "휴가 제도 안내.md",
            "가족돌봄휴가는 연차와 이어서 사용할 수 있으며, 사내 인사 포털에서 신청합니다.",
            """# 휴가 제도 안내

## 가족돌봄휴가

가족의 질병, 사고, 노령 또는 자녀 양육으로 돌봄이 필요한 경우 가족돌봄휴가를 신청할 수 있습니다.
가족돌봄휴가는 연차휴가와 이어서 사용할 수 있으며, 신청 시 사유와 예상 사용 기간을 함께 입력합니다.

## 신청 경로

휴가는 사내 인사 포털 > 근태/휴가 > 휴가 신청 메뉴에서 신청합니다.
긴급한 사유가 아니라면 사용 예정일 전까지 팀 리더 승인을 받아야 합니다.

## 유의 사항

개인의 병가 기록, 타인의 근태 현황, 인사평가 결과는 일반 사내 문서 검색 권한으로 조회할 수 없습니다.
""",
        ),
        "hr_welfare": (
            KB_IDS[LEGACY_DEMO_DOCUMENT_KB_KEYS["hr_welfare"]],
            "복지 제도 안내.md",
            "복지 포인트와 경조사 지원은 인사 지식 활용팀 권한으로 조회할 수 있습니다.",
            """# 복지 제도 안내

## 복지 포인트

복지 포인트는 매년 초 재직 상태와 근속 조건에 따라 지급됩니다.
사용 가능 항목은 건강관리, 자기계발, 가족 지원, 문화생활로 구분됩니다.

## 경조사 지원

경조사 지원은 사내 복지 포털에서 신청하며, 증빙 서류가 필요한 항목은 신청 후 7일 이내에 제출해야 합니다.

## 문의

복지 제도 일반 문의는 인사 지식 활용팀 채널을 통해 접수합니다.
""",
        ),
        "finance_sensitive": (
            KB_IDS[LEGACY_DEMO_DOCUMENT_KB_KEYS["finance_sensitive"]],
            "임원 보상 정책.md",
            "민감 재무 문서 예시입니다. 일반 팀에는 검색 권한을 부여하지 않습니다.",
            """# 임원 보상 정책

이 문서는 재무 제한 문서팀 전용 민감 문서 예시입니다.
임원 보상, 보너스 산정 기준, 비공개 예산 항목은 일반 구성원에게 공개하지 않습니다.

## 접근 정책

재무 제한 문서팀 권한이 없는 사용자는 이 문서의 원문과 검색 결과를 조회할 수 없습니다.
""",
        ),
    }
    for key, (knowledge_base_id, filename, summary, content) in document_specs.items():
        file_path = _write_demo_document(filename, content)
        _upsert_by_id(
            db,
            Document,
            DOCUMENT_IDS[key],
            {
                "knowledge_base_id": knowledge_base_id,
                "filename": filename,
                "file_path": file_path,
                "source_type": SourceType.FILE,
                "content_hash": f"demo-{key}",
                "status": "completed",
                "error_message": None,
                "chunk_size": 500,
                "chunk_overlap": 50,
                "meta_info": {
                    **_demo_options(f"document-{key}"),
                    "summary": summary,
                },
                "embedding_model": DEMO_EMBEDDING_MODEL,
            },
        )

    for spec in DEMO_DOCUMENT_SPECS:
        existing = db.get(Document, DOCUMENT_IDS[spec.key])
        if spec.content is not None:
            file_path = _write_demo_document(spec.filename, spec.content)
            document_filename = spec.filename
            source_path_for_meta = file_path
            source_available = True
        elif knowledge_fixture is not None:
            fixture_doc = fixture_documents[spec.key]
            file_path = None
            document_filename = fixture_doc["filename"]
            source_path_for_meta = fixture_doc.get("source_filename") or document_filename
            source_available = False
        else:
            legal_source_path = _resolve_legal_pdf(spec)
            file_path = _copy_demo_source_file(legal_source_path, legal_source_path.name)
            document_filename = legal_source_path.name
            source_path_for_meta = legal_source_path.as_posix()
            source_available = True
        _upsert_by_id(
            db,
            Document,
            DOCUMENT_IDS[spec.key],
            {
                "knowledge_base_id": KB_IDS[spec.key],
                "filename": document_filename,
                "file_path": file_path,
                "source_type": SourceType.FILE,
                "content_hash": existing.content_hash if existing else None,
                "status": "completed",
                "error_message": None,
                "chunk_size": spec.chunk_size,
                "chunk_overlap": spec.chunk_overlap,
                "meta_info": _preserve_indexing_meta(
                    existing,
                    _document_meta_base(
                        spec,
                        source_path_for_meta,
                        source_available=source_available,
                    ),
                ),
                "embedding_model": existing.embedding_model
                if existing and existing.embedding_model
                else DEMO_EMBEDDING_MODEL,
            },
        )

    for spec in ONBOARDING_PDF_SPECS:
        existing = db.get(Document, DOCUMENT_IDS[spec.key])
        source_path = _resolve_onboarding_pdf(spec)
        file_path = _copy_onboarding_pdf(spec, source_path)
        _upsert_by_id(
            db,
            Document,
            DOCUMENT_IDS[spec.key],
            {
                "knowledge_base_id": KB_IDS[spec.key],
                "filename": spec.filename,
                "file_path": file_path,
                "source_type": SourceType.FILE,
                "content_hash": existing.content_hash if existing else None,
                "status": existing.status if existing else "pending",
                "error_message": None,
                "chunk_size": spec.chunk_size,
                "chunk_overlap": spec.chunk_overlap,
                "meta_info": _preserve_indexing_meta(
                    existing,
                    _document_meta_base(spec, source_path.as_posix()),
                ),
                "embedding_model": existing.embedding_model
                if existing and existing.embedding_model
                else DEMO_EMBEDDING_MODEL,
            },
        )

    db.flush()
    _index_demo_documents(db, DEMO_DOCUMENT_SPECS, knowledge_fixture)
    if _should_index_onboarding_pdfs():
        _index_demo_documents_from_sources(
            db,
            ONBOARDING_PDF_SPECS,
            persist_fixture=False,
        )


def _ensure_openai_provider_and_models(db: Session) -> tuple[LLMProvider, dict[str, LLMModel]]:
    provider = db.query(LLMProvider).filter(LLMProvider.name == "openai").first()
    if provider is None:
        provider = LLMProvider(
            name="openai",
            description="OpenAI default provider",
            base_url="https://api.openai.com/v1",
            type="system",
            auth_type="api_key",
            doc_url="https://platform.openai.com/api-keys",
        )
        db.add(provider)
        db.flush()

    model_specs = {
        DEMO_CHAT_MODEL: ("chat", Decimal("0.002500"), Decimal("0.015000"), 400000),
        DEMO_CHAT_MINI_MODEL: (
            "chat",
            Decimal("0.000750"),
            Decimal("0.004500"),
            400000,
        ),
        DEMO_MODEL_ROUTER_BASE_MODEL: (
            "chat",
            Decimal("0.000250"),
            Decimal("0.002000"),
            400000,
        ),
        DEMO_MODEL_ROUTER_FALLBACK_MODEL: (
            "chat",
            Decimal("0.002000"),
            Decimal("0.008000"),
            1000000,
        ),
        DEMO_MODEL_ROUTER_CHEAP_MODEL: (
            "chat",
            Decimal("0.000150"),
            Decimal("0.000600"),
            128000,
        ),
        DEMO_MODEL_ROUTER_BALANCED_MODEL: (
            "chat",
            Decimal("0.000400"),
            Decimal("0.001600"),
            1000000,
        ),
        DEMO_ONBOARDING_ROUTER_MODEL: (
            "chat",
            Decimal("0.001000"),
            Decimal("0.006000"),
            400000,
        ),
        DEMO_EMBEDDING_MODEL: (
            "embedding",
            Decimal("0.000020"),
            Decimal("0.000000"),
            8191,
        ),
    }
    models: dict[str, LLMModel] = {}
    for model_id, (
        model_type,
        input_price,
        output_price,
        context_window,
    ) in model_specs.items():
        model = (
            db.query(LLMModel)
            .filter(
                LLMModel.provider_id == provider.id,
                LLMModel.model_id_for_api_call == model_id,
            )
            .first()
        )
        if model is None:
            model = LLMModel(
                provider_id=provider.id,
                model_id_for_api_call=model_id,
                name=model_id,
                type=model_type,
                context_window=context_window,
                input_price_1k=input_price,
                output_price_1k=output_price,
                is_active=True,
                model_metadata={"demo_seed": True},
            )
            db.add(model)
            db.flush()
        else:
            model.name = model_id
            model.type = model_type
            model.context_window = context_window
            model.input_price_1k = input_price
            model.output_price_1k = output_price
            model.is_active = True
        models[model_id] = model
    return provider, models


def _upsert_app_workflow(
    db: Session,
    key: str,
    name: str,
    description: str,
    owner_key: str,
    graph: dict[str, Any],
    *,
    deployed: bool,
    deployment_type: DeploymentType = DeploymentType.API,
) -> Workflow:
    app_secret = f"sk-demo-{key}"
    app_values = {
        "organization_id": ORG_ID,
        "name": name,
        "description": description,
        "icon": _icon(
            "🧭"
            if key in {"ticket_ops", "model_router_ticket_ops"}
            else "📘"
        ),
        "url_slug": f"demo-{key.replace('_', '-')}",
        "auth_secret": None,
        "auth_secret_verifier": app_auth_secret_verifier(app_secret),
        "auth_secret_verifier_version": APP_AUTH_SECRET_VERIFIER_VERSION,
        "auth_secret_generation": 1,
        "auth_secret_previous_verifier": None,
        "auth_secret_previous_verifier_version": None,
        "auth_secret_previous_valid_until": None,
        "auth_secret_rotated_at": _now(),
        "is_api_enabled": True,
        "api_req_per_minute": 60,
        "api_req_per_hour": 3600,
        "is_market": False,
        "forked_from": None,
        "created_by": USER_IDS[owner_key],
        "workflow_id": None,
        "active_deployment_id": None,
    }
    app = _upsert_by_id(
        db,
        App,
        APP_IDS[key],
        _app_seed_values(db.get(App, APP_IDS[key]), app_values),
    )
    db.flush()

    workflow = _upsert_by_id(
        db,
        Workflow,
        WORKFLOW_IDS[key],
        {
            "organization_id": ORG_ID,
            "app_id": app.id,
            "graph": graph,
            "features": _demo_options(f"workflow-{key}"),
            "env_variables": [],
            "runtime_variables": [],
            "created_by": USER_IDS[owner_key],
            "updated_by": USER_IDS[owner_key],
        },
    )
    db.flush()
    app.workflow_id = workflow.id

    if deployed:
        deployment = _upsert_by_id(
            db,
            WorkflowDeployment,
            DEPLOYMENT_IDS[key],
            {
                "app_id": app.id,
                "version": 1,
                "type": deployment_type,
                "graph_snapshot": graph,
                "config": _demo_options(f"deployment-{key}"),
                "input_schema": _input_schema_from_graph(graph),
                "output_schema": _output_schema(),
                "description": "최종 시연용 배포 버전",
                "created_by": USER_IDS[owner_key],
                "is_active": True,
            },
        )
        db.flush()
        app.active_deployment_id = deployment.id
    else:
        app.active_deployment_id = None
    db.flush()

    return workflow


def _seed_apps_and_workflows(db: Session) -> dict[str, Workflow]:
    workflows = {
        "hr_bot_example": _upsert_app_workflow(
            db,
            "hr_bot_example",
            "사내 문서 질문 응답 봇",
            "신입사원 이서연이 권한 승인 후 직접 만들 workflow의 완성 예시",
            "rookie",
            _hr_bot_graph(),
            deployed=False,
        ),
        "department_onboarding_chatbot": _upsert_app_workflow(
            db,
            "department_onboarding_chatbot",
            "부서별 온보딩 RAG 챗봇",
            "개발팀과 기획팀 사용자의 Knowledge 권한 차이를 확인하는 내부 챗봇",
            "admin",
            _department_onboarding_chatbot_graph(),
            deployed=True,
            deployment_type=DeploymentType.INTERNAL_CHATBOT,
        ),
        "team_onboarding_access_control": _upsert_app_workflow(
            db,
            "team_onboarding_access_control",
            "팀별 온보딩 문서 접근 제어 데모",
            "플랫폼개발팀·영업팀·People 팀 사용자의 Knowledge 권한 차이를 보여주는 내부 챗봇",
            "onboarding_people_manager",
            _team_onboarding_access_control_graph(),
            deployed=True,
            deployment_type=DeploymentType.INTERNAL_CHATBOT,
        ),
        "team_onboarding_adaptive_routing": _upsert_app_workflow(
            db,
            "team_onboarding_adaptive_routing",
            "팀별 온보딩 자동 모델 라우팅 검증",
            "팀 권한 RAG와 입력 추세 변화에 따른 자동 모델 라우팅을 검증하는 내부 챗봇",
            "onboarding_people_manager",
            _team_onboarding_adaptive_routing_graph(),
            deployed=True,
            deployment_type=DeploymentType.INTERNAL_CHATBOT,
        ),
        "enterprise_request_routing": _upsert_app_workflow(
            db,
            "enterprise_request_routing",
            ENTERPRISE_REQUEST_ROUTING_NAME,
            ENTERPRISE_REQUEST_ROUTING_DESCRIPTION,
            "admin",
            _enterprise_request_routing_graph(),
            deployed=True,
            deployment_type=DeploymentType.WEBHOOK,
        ),
        "ticket_ops": _upsert_app_workflow(
            db,
            "ticket_ops",
            "Enterprise 고객 티켓 처리",
            "비용 최적화 시연을 위한 고객지원 운영 workflow",
            "author",
            _ticket_ops_graph(),
            deployed=True,
            deployment_type=DeploymentType.WEBHOOK,
        ),
        "model_router_ticket_ops": _upsert_app_workflow(
            db,
            "model_router_ticket_ops",
            "모델 라우팅 검증용 고객 티켓 처리",
            "자동 모델 라우팅과 비용 최적화 A/B 검증을 시연하기 위한 고객지원 workflow",
            "author",
            _model_router_ticket_ops_graph(),
            deployed=True,
            deployment_type=DeploymentType.WEBHOOK,
        ),
        "test_inquiry": _upsert_app_workflow(
            db,
            "test_inquiry",
            "테스트용 문의 응답 워크플로우",
            "팀원이 자유롭게 기능을 확인하는 테스트 workflow",
            "tester_builder",
            _test_inquiry_graph(),
            deployed=True,
        ),
    }

    # 운영 현황 상단 위험 패널 확인용 추가 앱.
    for key, name, owner in [
        ("ticket_ops_warning", "예산 80% 근접 티켓 처리 A", "author"),
        ("ticket_ops_risk", "예산 80% 근접 티켓 처리 B", "author"),
        ("ticket_ops_paused", "예산 초과로 정지된 워크플로우", "author"),
    ]:
        workflows[key] = _upsert_app_workflow(
            db,
            key,
            name,
            "운영 현황 비용 위험 표시용 데모 workflow",
            owner,
            _ticket_ops_graph(),
            deployed=key != "ticket_ops_paused",
            deployment_type=DeploymentType.WEBHOOK,
        )

    return workflows


def _seed_permissions(db: Session) -> None:
    permission_specs = [
        (
            TEAM_PERMISSION_IDS["customer_ticket"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["customer_support_ops"],
                "workflow_id": WORKFLOW_IDS["ticket_ops"],
                "auth_state": "manager",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-customer-ticket"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["model_router_ticket"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["customer_support_ops"],
                "workflow_id": WORKFLOW_IDS["model_router_ticket_ops"],
                "auth_state": "manager",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-model-router-ticket"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["enterprise_request_routing"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["platform_admin"],
                "workflow_id": WORKFLOW_IDS["enterprise_request_routing"],
                "auth_state": "manager",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-enterprise-request-routing"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["hr_bot"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["hr_knowledge_users"],
                "workflow_id": WORKFLOW_IDS["hr_bot_example"],
                "auth_state": "operator",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-hr-bot"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["department_onboarding_development"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["department_development"],
                "workflow_id": WORKFLOW_IDS["department_onboarding_chatbot"],
                "auth_state": "operator",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options(
                    "permission-department-onboarding-development"
                ),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["department_onboarding_planning"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["department_planning"],
                "workflow_id": WORKFLOW_IDS["department_onboarding_chatbot"],
                "auth_state": "operator",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-department-onboarding-planning"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["team_onboarding_platform"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["onboarding_platform"],
                "workflow_id": WORKFLOW_IDS["team_onboarding_access_control"],
                "auth_state": "operator",
                "assigned_by": USER_IDS["onboarding_people_manager"],
                "options": _demo_options("permission-team-onboarding-platform"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["team_onboarding_sales"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["onboarding_sales"],
                "workflow_id": WORKFLOW_IDS["team_onboarding_access_control"],
                "auth_state": "operator",
                "assigned_by": USER_IDS["onboarding_people_manager"],
                "options": _demo_options("permission-team-onboarding-sales"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["team_onboarding_people"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["onboarding_people"],
                "workflow_id": WORKFLOW_IDS["team_onboarding_access_control"],
                "auth_state": "manager",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-team-onboarding-people"),
                "flags": 0,
            },
        ),
        *[
            (
                TEAM_PERMISSION_IDS[f"team_onboarding_adaptive_{team_suffix}"],
                TeamWorkflowPermission,
                {
                    "grantee_organization_id": ORG_ID,
                    "team_id": TEAM_IDS[f"onboarding_{team_suffix}"],
                    "workflow_id": WORKFLOW_IDS[
                        "team_onboarding_adaptive_routing"
                    ],
                    "auth_state": auth_state,
                    "assigned_by": USER_IDS["onboarding_people_manager"],
                    "options": _demo_options(
                        f"permission-team-onboarding-adaptive-{team_suffix}"
                    ),
                    "flags": 0,
                },
            )
            for team_suffix, auth_state in (
                ("platform", "operator"),
                ("sales", "operator"),
                ("people", "manager"),
            )
        ],
        (
            TEAM_PERMISSION_IDS["test_builder"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["tester_builder"],
                "workflow_id": WORKFLOW_IDS["test_inquiry"],
                "auth_state": "manager",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-test-builder"),
                "flags": 0,
            },
        ),
        (
            TEAM_PERMISSION_IDS["test_member"],
            TeamWorkflowPermission,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS["tester_member"],
                "workflow_id": WORKFLOW_IDS["test_inquiry"],
                "auth_state": "viewer",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options("permission-test-member"),
                "flags": 0,
            },
        ),
    ]
    for row_id, model, values in permission_specs:
        _upsert_by_id(db, model, row_id, values)

    # 운영자에게 위험 패널용 workflow도 직접 manager 권한을 준다.
    for index, workflow_key in enumerate(["ticket_ops_warning", "ticket_ops_risk", "ticket_ops_paused"]):
        _upsert_by_id(
            db,
            UserWorkflowPermission,
            _uuid(830 + index),
            {
                "grantee_organization_id": ORG_ID,
                "user_id": USER_IDS["author"],
                "workflow_id": WORKFLOW_IDS[workflow_key],
                "auth_state": "manager",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options(f"direct-permission-{workflow_key}"),
                "flags": 0,
            },
        )

    for index, team_key in enumerate(["hr_knowledge_users", "platform_admin"]):
        _upsert_by_id(
            db,
            TeamKnowledgePermission,
            _uuid(850 + index),
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS[team_key],
                "knowledge_base_id": KB_IDS["hr"],
                "auth_state": "manager" if team_key == "platform_admin" else "operator",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options(f"knowledge-permission-{team_key}"),
                "flags": 0,
            },
        )

    _upsert_by_id(
        db,
        TeamKnowledgePermission,
        _uuid(852),
        {
            "grantee_organization_id": ORG_ID,
            "team_id": TEAM_IDS["finance_restricted"],
            "knowledge_base_id": KB_IDS["finance"],
            "auth_state": "viewer",
            "assigned_by": USER_IDS["admin"],
            "options": _demo_options("knowledge-permission-finance"),
            "flags": 0,
        },
    )

    for index, (kb_key, team_key, auth_state) in enumerate(
        _demo_team_knowledge_permission_specs()
    ):
        _upsert_by_id(
            db,
            TeamKnowledgePermission,
            _uuid(853 + index),
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS[team_key],
                "knowledge_base_id": KB_IDS[kb_key],
                "auth_state": auth_state,
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options(f"knowledge-permission-{kb_key}-{team_key}"),
                "flags": 0,
            },
        )

    for index, (collection_key, team_key, action) in enumerate(
        _demo_team_knowledge_collection_permission_specs()
    ):
        _upsert_by_id(
            db,
            TeamKnowledgeCollectionPermission,
            _uuid(880 + index),
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS[team_key],
                "knowledge_collection_id": COLLECTION_IDS[collection_key],
                "permission_action": action,
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options(
                    f"collection-permission-{collection_key}-{team_key}-{action}"
                ),
                "flags": 0,
            },
        )

    _upsert_by_id(
        db,
        TeamAuditPermission,
        _uuid(870),
        {
            "grantee_organization_id": ORG_ID,
            "team_id": TEAM_IDS["platform_admin"],
            "target_organization_id": ORG_ID,
            "auth_state": "manager",
            "assigned_by": USER_IDS["admin"],
            "options": _demo_options("audit-permission-admin"),
            "flags": 0,
        },
    )
    _upsert_by_id(
        db,
        TeamAuditPermission,
        _uuid(871),
        {
            "grantee_organization_id": ORG_ID,
            "team_id": TEAM_IDS["onboarding_people"],
            "target_organization_id": ORG_ID,
            "auth_state": "manager",
            "assigned_by": USER_IDS["admin"],
            "options": _demo_options("audit-permission-onboarding-people"),
            "flags": 0,
        },
    )


def _seed_run(
    db: Session,
    *,
    run_id: uuid.UUID,
    workflow_key: str,
    user_key: str,
    status: RunStatus,
    started_at: datetime,
    duration: float,
    total_tokens: int,
    total_cost: Decimal,
    output_text: str | None,
    error_message: str | None = None,
    model_name: str = DEMO_CHAT_MODEL,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    latency_ms: int = 0,
    node_prefix: int = 0,
) -> None:
    workflow_id = WORKFLOW_IDS[workflow_key]
    app_id = APP_IDS[workflow_key]
    app = db.get(App, app_id)
    deployment_id = app.active_deployment_id if app else None
    finished_at = started_at + timedelta(seconds=duration)
    outputs = {"answer_text": output_text} if output_text else None
    run = _upsert_by_id(
        db,
        WorkflowRun,
        run_id,
        {
            "workflow_id": workflow_id,
            "user_id": USER_IDS[user_key],
            "app_id": app_id,
            "deployment_id": deployment_id,
            "workflow_version": 1,
            "status": status,
            "trigger_mode": RunTriggerMode.WEBHOOK,
            "inputs": {
                "customerTier": "enterprise",
                "message": "결제 API 장애로 크레딧 보상 가능 여부를 확인해 주세요.",
            },
            "outputs": outputs,
            "error_message": error_message,
            "started_at": started_at,
            "finished_at": finished_at if status != RunStatus.RUNNING else None,
            "duration": duration,
            "meta_info": _demo_options(f"run-{workflow_key}-{node_prefix}"),
            "total_tokens": total_tokens,
            "total_cost": total_cost,
            "trace_metadata": {
                "demo_seed": True,
                "budget_ratio": 0.92 if workflow_key != "ticket_ops_paused" else 1.08,
            },
            "redaction_applied": False,
            "pii_detected": False,
            "payload_storage_mode": "redacted_only",
        },
    )
    db.flush()

    node_specs = [
        ("webhook-ticket", "webhookTrigger", 0.02, {"message": run.inputs["message"]}),
        (
            "llm-triage",
            "llmNode",
            max(duration - 0.15, 0.5),
            {
                "text": output_text or "실행 실패",
                "model": model_name,
                "usage": {
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                },
            },
        ),
        (
            "extract-ticket",
            "variableExtractionNode",
            0.03,
            {"approvalRequired": True, "mailDraft": output_text},
        ),
        ("condition-approval", "conditionNode", 0.01, {"selected_handle": "approval"}),
        ("template-approval", "templateNode", 0.01, {"text": output_text}),
        ("answer-approval", "answerNode", 0.01, outputs),
    ]
    for index, (node_id, node_type, node_duration, node_outputs) in enumerate(node_specs):
        node_run_id = _uuid(3000 + node_prefix * 10 + index)
        _upsert_by_id(
            db,
            WorkflowNodeRun,
            node_run_id,
            {
                "workflow_run_id": run.id,
                "node_id": node_id,
                "node_type": node_type,
                "status": NodeRunStatus.FAILED
                if status == RunStatus.FAILED and node_id == "llm-triage"
                else NodeRunStatus.SUCCESS,
                "inputs": run.inputs if node_id == "webhook-ticket" else {"previous": "redacted"},
                "process_data": _demo_options(f"node-run-{node_prefix}-{index}"),
                "outputs": node_outputs,
                "error_message": error_message if node_id == "llm-triage" else None,
                "started_at": started_at + timedelta(milliseconds=100 * index),
                "finished_at": started_at
                + timedelta(milliseconds=100 * index)
                + timedelta(seconds=node_duration),
                "duration": node_duration,
                "trace_metadata": {
                    "demo_seed": True,
                    "cost_hotspot": node_id == "llm-triage",
                },
                "redaction_applied": False,
                "pii_detected": False,
                "sequence": index + 1,
                "retry_count": 0,
            },
        )


def _seed_llm_credential(
    db: Session, provider: LLMProvider, models: dict[str, LLMModel]
) -> LLMCredential:
    """데모 조직 공용 credential과 verified model relation (FR-012 비용 집계용)."""
    from apps.shared.services.llm_credential_config import (
        protect_llm_credential_config,
    )

    runtime_credential_enabled = _runtime_openai_credential_requested()
    api_key = (
        _require_seed_env("OPENAI_API_KEY")
        if runtime_credential_enabled
        else "sk-demo-not-a-real-key"
    )
    envelope = protect_llm_credential_config(
        {"apiKey": api_key, "baseUrl": provider.base_url}
    )
    credential = _upsert_by_id(
        db,
        LLMCredential,
        LLM_CREDENTIAL_IDS["demo_openai"],
        {
            "provider_id": provider.id,
            "user_id": USER_IDS["admin"],
            "organization_id": ORG_ID,
            "credential_name": (
                "시연 OpenAI Runtime Credential"
                if runtime_credential_enabled
                else "데모 OpenAI Credential"
            ),
            "encrypted_config": envelope.ciphertext,
            "encryption_key_version": envelope.key_version,
            "encryption_algorithm": envelope.algorithm,
            "config_preview": (
                _mask_demo_api_key(api_key)
                if runtime_credential_enabled
                else "sk-****demo"
            ),
            "is_valid": True,
            "quota_type": "unlimited",
            "quota_limit": 0,
            "quota_used": 0,
        },
    )
    relation_model_names = [
        DEMO_CHAT_MODEL,
        DEMO_CHAT_MINI_MODEL,
        DEMO_MODEL_ROUTER_BASE_MODEL,
        DEMO_MODEL_ROUTER_FALLBACK_MODEL,
        DEMO_MODEL_ROUTER_CHEAP_MODEL,
        DEMO_MODEL_ROUTER_BALANCED_MODEL,
        DEMO_ONBOARDING_ROUTER_MODEL,
    ]
    if runtime_credential_enabled:
        relation_model_names.append(DEMO_EMBEDDING_MODEL)
    else:
        db.query(LLMRelCredentialModel).filter(
            LLMRelCredentialModel.id.in_(
                [
                    CREDENTIAL_MODEL_REL_IDS[DEMO_EMBEDDING_MODEL],
                ]
            )
        ).delete(synchronize_session=False)
        _delete_demo_runtime_llm_permissions(db)

    for model_name in relation_model_names:
        _upsert_by_id(
            db,
            LLMRelCredentialModel,
            CREDENTIAL_MODEL_REL_IDS[model_name],
            {
                "credential_id": LLM_CREDENTIAL_IDS["demo_openai"],
                "model_id": models[model_name].id,
                "is_verified": True,
                "priority": 0,
            },
        )
    if runtime_credential_enabled:
        _seed_runtime_llm_permissions(db)
    return credential


def _delete_demo_runtime_llm_permissions(db: Session) -> None:
    db.query(TeamLLMPermission).filter(
        TeamLLMPermission.id.in_(list(TEAM_LLM_PERMISSION_IDS.values()))
    ).delete(synchronize_session=False)
    db.query(UserLLMPermission).filter(
        UserLLMPermission.id.in_(list(USER_LLM_PERMISSION_IDS.values()))
    ).delete(synchronize_session=False)


def _seed_runtime_llm_permissions(db: Session) -> None:
    for team_key, permission_id in TEAM_LLM_PERMISSION_IDS.items():
        _upsert_by_id(
            db,
            TeamLLMPermission,
            permission_id,
            {
                "grantee_organization_id": ORG_ID,
                "team_id": TEAM_IDS[team_key],
                "llm_credential_id": LLM_CREDENTIAL_IDS["demo_openai"],
                "auth_state": "manager" if team_key == "platform_admin" else "operator",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options(f"llm-permission-{team_key}"),
                "flags": 0,
            },
        )

    for user_key, permission_id in USER_LLM_PERMISSION_IDS.items():
        _upsert_by_id(
            db,
            UserLLMPermission,
            permission_id,
            {
                "grantee_organization_id": ORG_ID,
                "user_id": USER_IDS[user_key],
                "llm_credential_id": LLM_CREDENTIAL_IDS["demo_openai"],
                "auth_state": "operator",
                "assigned_by": USER_IDS["admin"],
                "options": _demo_options(f"llm-permission-{user_key}"),
                "flags": 0,
            },
        )


def _seed_runs_and_usage(db: Session, models: dict[str, LLMModel]) -> None:
    now = _now()
    run_specs = [
        ("ticket_ops", "author", RunStatus.SUCCESS, 4.8, 10120, Decimal("0.0820"), "CS 리드 승인 요청이 필요합니다.", DEMO_CHAT_MODEL, 8200, 1920, 4800),
        ("ticket_ops", "author", RunStatus.SUCCESS, 4.1, 9800, Decimal("0.0780"), "Enterprise 고객 장애 티켓으로 우선 처리합니다.", DEMO_CHAT_MODEL, 7900, 1900, 4100),
        ("ticket_ops", "author", RunStatus.SUCCESS, 1.9, 3280, Decimal("0.0220"), "권한 기반 RAG와 중간 모델로 처리했습니다.", DEMO_CHAT_MINI_MODEL, 2600, 680, 1900),
        ("ticket_ops", "author", RunStatus.SUCCESS, 2.2, 3410, Decimal("0.0240"), "승인 필요 여부를 판단했습니다.", DEMO_CHAT_MINI_MODEL, 2700, 710, 2200),
        ("ticket_ops", "author", RunStatus.SUCCESS, 2.4, 3650, Decimal("0.0260"), "고객 답변 초안을 생성했습니다.", DEMO_CHAT_MINI_MODEL, 2890, 760, 2400),
        ("ticket_ops", "author", RunStatus.SUCCESS, 2.1, 3400, Decimal("0.0230"), "SLA 기준에 따라 기술지원팀으로 배정했습니다.", DEMO_CHAT_MINI_MODEL, 2720, 680, 2100),
        ("ticket_ops", "author", RunStatus.FAILED, 1.3, 1200, Decimal("0.0060"), None, DEMO_CHAT_MINI_MODEL, 1000, 200, 1300),
        ("ticket_ops_warning", "author", RunStatus.SUCCESS, 5.2, 11200, Decimal("0.0910"), "비용 위험 workflow 실행입니다.", DEMO_CHAT_MODEL, 9100, 2100, 5200),
        ("ticket_ops_risk", "author", RunStatus.SUCCESS, 4.9, 10800, Decimal("0.0880"), "비용 위험 workflow 실행입니다.", DEMO_CHAT_MODEL, 8700, 2100, 4900),
        ("ticket_ops_paused", "author", RunStatus.FAILED, 0.4, 0, Decimal("0.0000"), None, DEMO_CHAT_MODEL, 0, 0, 0),
        (
            "model_router_ticket_ops",
            "author",
            RunStatus.SUCCESS,
            3.2,
            1218,
            Decimal("0.001920"),
            '{"긴급도": true, "답변 초안": "먼저 불편을 드린 점 진심으로 사과드립니다. 현재 해당 장애가 SLA 위반 가능성이 있어 크레딧 보상 검토가 필요하며, 승인 결과는 48시간 내 안내드리겠습니다. 추가 영향 범위 확인을 위해 실패한 정산 파일 생성 시각과 요청 ID를 공유해 주세요."}',
            DEMO_MODEL_ROUTER_BASE_MODEL,
            295,
            923,
            3200,
        ),
        (
            "model_router_ticket_ops",
            "author",
            RunStatus.SUCCESS,
            2.7,
            1045,
            Decimal("0.001740"),
            '{"긴급도": false, "답변 초안": "문의하신 정산 파일 재생성 방법과 다운로드 위치를 안내드리겠습니다. 관리자 페이지의 정산 메뉴에서 파일을 다시 생성한 뒤 완료 알림 후 다운로드할 수 있습니다. 추가 오류가 발생하면 요청 ID와 발생 시각을 함께 알려 주세요."}',
            DEMO_MODEL_ROUTER_BASE_MODEL,
            280,
            765,
            2700,
        ),
    ]

    for index, spec in enumerate(run_specs):
        workflow_key, user_key, status, duration, tokens, cost, output, model_name, prompt, completion, latency = spec
        run_id = _uuid(2000 + index)
        _seed_run(
            db,
            run_id=run_id,
            workflow_key=workflow_key,
            user_key=user_key,
            status=status,
            started_at=now - timedelta(hours=index + 1),
            duration=duration,
            total_tokens=tokens,
            total_cost=cost,
            output_text=output,
            error_message="provider_timeout" if status == RunStatus.FAILED else None,
            model_name=model_name,
            prompt_tokens=prompt,
            completion_tokens=completion,
            latency_ms=latency,
            node_prefix=index,
        )

        # 관리자 비용 탭/월간 요약(FR-012/FR-015)의 원천은 llm_usage_logs라
        # run과 같은 시각/토큰/비용으로 usage row를 만든다. 실패 run은 provider
        # 응답이 없어 usage를 기록하지 않는 실제 경로를 따른다.
        if status == RunStatus.SUCCESS:
            _upsert_by_id(
                db,
                LLMUsageLog,
                _uuid(5000 + index),
                {
                    "user_id": USER_IDS[user_key],
                    "organization_id": ORG_ID,
                    "credential_id": LLM_CREDENTIAL_IDS["demo_openai"],
                    "model_id": models[model_name].id,
                    "workflow_id": WORKFLOW_IDS[workflow_key],
                    "workflow_run_id": run_id,
                    "node_id": "llm-triage",
                    "prompt_tokens": prompt,
                    "completion_tokens": completion,
                    "total_cost": cost,
                    "latency_ms": latency,
                    "status": "success",
                    "created_at": now - timedelta(hours=index + 1),
                },
            )


def _seed_permission_requests(db: Session) -> None:
    """author의 승인된 App 생성 권한 신청과 부여 결과 (ADR-0016, FR-014)."""
    now = _now()
    requested_at = now - timedelta(days=7)
    decided_at = requested_at + timedelta(hours=1)
    _upsert_by_id(
        db,
        PermissionRequest,
        PERMISSION_REQUEST_IDS["author_app_create"],
        {
            "organization_id": ORG_ID,
            "user_id": USER_IDS["author"],
            "requested_permission": REQUESTED_PERMISSION_APP_CREATE,
            "reason": "고객지원 운영 workflow를 직접 만들고 배포해야 합니다.",
            "status": PERMISSION_REQUEST_APPROVED,
            "created_at": requested_at,
            "decided_by": USER_IDS["admin"],
            "decided_at": decided_at,
            "options": _demo_options("permission-request-author"),
        },
    )
    _upsert_by_id(
        db,
        UserAppCreationPermission,
        APP_CREATION_PERMISSION_IDS["author"],
        {
            "grantee_organization_id": ORG_ID,
            "user_id": USER_IDS["author"],
            "assigned_by": USER_IDS["admin"],
            "assigned_at": decided_at,
            "options": _demo_options("app-creation-permission-author"),
        },
    )


def _seed_audit_logs(db: Session) -> None:
    now = _now()
    # ADR-0008 canonical action 기준. occurred_at은 index가 클수록 과거이므로
    # 최신 이벤트를 앞에 둔다 (신청 -> 승인 -> 권한 부여가 시간순이 되도록).
    logs = [
        (AuditAction.USER_LOGIN, "rookie", "user", USER_IDS["rookie"], "신입사원 로그인"),
        (AuditAction.LLM_CALL, "author", "workflow", str(WORKFLOW_IDS["ticket_ops"]), "LLM 비용 사용 기록"),
        (AuditAction.WORKFLOW_EXECUTE, "author", "workflow", str(WORKFLOW_IDS["ticket_ops"]), "고객 티켓 workflow 실행"),
        (AuditAction.WORKFLOW_DEPLOY, "author", "workflow", str(WORKFLOW_IDS["ticket_ops"]), "Enterprise 고객 티켓 처리 배포"),
        (AuditAction.POLICY_BLOCK, "admin", "knowledge", str(KB_IDS["finance"]), "민감 문서 접근 정책 차단"),
        (AuditAction.PERMISSION_DENIED, "author", "workflow", str(WORKFLOW_IDS["ticket_ops"]), "권한 없는 workflow 접근 차단"),
        (AuditAction.WORKFLOW_CREATE, "rookie", "workflow", str(WORKFLOW_IDS["hr_bot_example"]), "사내 문서 질문 응답 봇 생성"),
        (AuditAction.USER_APP_CREATION_PERMISSION_CREATED, "admin", "user_app_creation_permission", str(APP_CREATION_PERMISSION_IDS["author"]), "운영자 App 생성 권한 부여"),
        (AuditAction.PERMISSION_REQUEST_APPROVED, "admin", "permission_request", str(PERMISSION_REQUEST_IDS["author_app_create"]), "운영자 권한 신청 승인"),
        (AuditAction.PERMISSION_REQUEST_CREATED, "author", "permission_request", str(PERMISSION_REQUEST_IDS["author_app_create"]), "운영자 workflow 생성/배포 권한 신청"),
    ]
    for index, (action, actor_key, target_type, target_id, summary) in enumerate(
        logs
    ):
        _upsert_by_id(
            db,
            AuditLog,
            _uuid(4000 + index),
            {
                "occurred_at": now - timedelta(minutes=index * 7),
                "actor_id": USER_IDS[actor_key],
                "actor_type": ActorType.USER,
                "category": AuditCategory.ACTION,
                "action": action,
                "target_type": target_type,
                "target_id": target_id,
                "before": None,
                "after": None,
                "status": AuditStatus.SUCCESS
                if action != AuditAction.PERMISSION_DENIED
                else AuditStatus.FAILURE,
                "audit_metadata": {
                    **_demo_options(f"audit-{index}"),
                    "summary": summary,
                    "organization_id": str(ORG_ID),
                },
            },
        )


def _adopt_existing_test_user_ids(db: Session) -> None:
    """Reuse existing local users with the test profile emails."""
    for spec in TEST_USER_SPECS:
        existing = db.query(User).filter(User.email == spec.email).first()
        if existing is not None:
            TEST_USER_IDS[spec.key] = existing.id


def _test_feature_graph() -> dict[str, Any]:
    return {
        "nodes": [
            _node(
                "start-test",
                "startNode",
                120,
                120,
                {
                    **_base_node_data("테스트 입력", "기능 검증용 입력을 받습니다.", 1),
                    "triggerType": "manual",
                    "trigger_type": "manual",
                    "variables": [
                        {
                            "id": "message",
                            "name": "message",
                            "label": "테스트 메시지",
                            "type": "paragraph",
                            "required": True,
                            "maxLength": 1000,
                            "max_length": 1000,
                        }
                    ],
                },
            ),
            _node(
                "template-test",
                "templateNode",
                540,
                120,
                {
                    **_base_node_data("테스트 응답 생성", "입력 값을 템플릿으로 반환합니다.", 2),
                    "template": "테스트 응답: {{ message }}",
                    "variables": [
                        {
                            "name": "message",
                            "value_selector": ["start-test", "message"],
                        }
                    ],
                },
            ),
            _node(
                "answer-test",
                "answerNode",
                960,
                120,
                {
                    **_base_node_data("응답", "테스트 결과를 반환합니다.", 3),
                    "outputs": [
                        {
                            "variable": "answer_text",
                            "label": "답변",
                            "value_selector": ["template-test", "text"],
                        }
                    ],
                },
            ),
        ],
        "edges": [
            _edge("edge-test-start-template", "start-test", "template-test"),
            _edge("edge-test-template-answer", "template-test", "answer-test"),
        ],
        "viewport": {"x": 40, "y": 80, "zoom": 0.85},
    }


def seed_test_data(db: Session) -> None:
    """Upsert mutable local QA seed data without touching final demo rows."""
    _adopt_existing_test_user_ids(db)
    hashed_password = hash_password(DEMO_PASSWORD)

    for spec in TEST_USER_SPECS:
        _upsert_by_id(
            db,
            User,
            TEST_USER_IDS[spec.key],
            {
                "email": spec.email,
                "name": spec.name,
                "password": hashed_password,
                "social_provider": "none",
                "social_id": None,
                "avatar_url": None,
                "deactivated_at": None,
            },
        )
    db.flush()

    _upsert_by_id(
        db,
        Organization,
        TEST_ORG_ID,
        {
            "name": "노디즈 테스트 조직",
            "options": _demo_options("test-organization"),
            "flags": 0,
            "created_by": TEST_USER_IDS["admin"],
            "managed_by": TEST_USER_IDS["admin"],
            "is_active": True,
            "deactivated_at": None,
        },
    )
    db.flush()

    for index, spec in enumerate(TEST_USER_SPECS):
        _upsert_by_id(
            db,
            OrganizationMembership,
            _uuid(9040 + index),
            {
                "organization_id": TEST_ORG_ID,
                "user_id": TEST_USER_IDS[spec.key],
                "membership_state": spec.membership_state,
                "organization_auth_state": spec.organization_auth_state,
                "invited_by": TEST_USER_IDS["admin"],
                "invited_at": _now() - timedelta(days=7),
                "accepted_at": _now()
                if spec.membership_state == ORGANIZATION_MEMBERSHIP_ACTIVE
                else None,
                "removed_at": _now()
                if spec.membership_state == ORGANIZATION_MEMBERSHIP_REMOVED
                else None,
                "options": _demo_options(f"test-org-membership-{spec.key}"),
                "flags": 0,
            },
        )

    for key, (name, description) in TEST_TEAM_SPECS.items():
        _upsert_by_id(
            db,
            Team,
            TEST_TEAM_IDS[key],
            {
                "organization_id": TEST_ORG_ID,
                "name": name,
                "description": description,
                "is_active": True,
                "created_by": TEST_USER_IDS["admin"],
                "options": _demo_options(f"test-team-{key}"),
                "flags": 0,
            },
        )

    membership_index = 0
    for spec in TEST_USER_SPECS:
        for team_key in spec.teams:
            _upsert_by_id(
                db,
                TeamMembership,
                _uuid(9050 + membership_index),
                {
                    "grantee_organization_id": TEST_ORG_ID,
                    "team_id": TEST_TEAM_IDS[team_key],
                    "user_id": TEST_USER_IDS[spec.key],
                    "assigned_by": TEST_USER_IDS["admin"],
                    "options": _demo_options(
                        f"test-team-membership-{spec.key}-{team_key}"
                    ),
                    "flags": 0,
                },
            )
            membership_index += 1

    graph = _test_feature_graph()
    test_app_secret = "sk-test-feature-workflow"
    test_app_values = {
        "organization_id": TEST_ORG_ID,
        "name": "테스트용 기능 검증 워크플로우",
        "description": "팀원이 기능 구현 중 자유롭게 변경해도 되는 테스트 workflow",
        "icon": _icon("🧪"),
        "url_slug": "test-feature-workflow",
        "auth_secret": None,
        "auth_secret_verifier": app_auth_secret_verifier(test_app_secret),
        "auth_secret_verifier_version": APP_AUTH_SECRET_VERIFIER_VERSION,
        "auth_secret_generation": 1,
        "auth_secret_previous_verifier": None,
        "auth_secret_previous_verifier_version": None,
        "auth_secret_previous_valid_until": None,
        "auth_secret_rotated_at": _now(),
        "is_api_enabled": True,
        "api_req_per_minute": 60,
        "api_req_per_hour": 3600,
        "is_market": False,
        "forked_from": None,
        "created_by": TEST_USER_IDS["builder"],
        "workflow_id": None,
        "active_deployment_id": None,
    }
    app = _upsert_by_id(
        db,
        App,
        TEST_APP_ID,
        _app_seed_values(db.get(App, TEST_APP_ID), test_app_values),
    )
    db.flush()
    workflow = _upsert_by_id(
        db,
        Workflow,
        TEST_WORKFLOW_ID,
        {
            "organization_id": TEST_ORG_ID,
            "app_id": app.id,
            "graph": graph,
            "features": _demo_options("test-workflow"),
            "env_variables": [],
            "runtime_variables": [],
            "created_by": TEST_USER_IDS["builder"],
            "updated_by": TEST_USER_IDS["builder"],
        },
    )
    db.flush()
    app.workflow_id = workflow.id

    deployment = _upsert_by_id(
        db,
        WorkflowDeployment,
        TEST_DEPLOYMENT_ID,
        {
            "app_id": app.id,
            "version": 1,
            "type": DeploymentType.API,
            "graph_snapshot": graph,
            "config": _demo_options("test-deployment"),
            "input_schema": _input_schema("message", "테스트 메시지"),
            "output_schema": _output_schema(),
            "description": "테스트 프로파일 기본 배포",
            "created_by": TEST_USER_IDS["builder"],
            "is_active": True,
        },
    )
    db.flush()
    app.active_deployment_id = deployment.id

    _upsert_by_id(
        db,
        TeamWorkflowPermission,
        TEST_PERMISSION_IDS["builder"],
        {
            "grantee_organization_id": TEST_ORG_ID,
            "team_id": TEST_TEAM_IDS["qa_builder"],
            "workflow_id": TEST_WORKFLOW_ID,
            "auth_state": "manager",
            "assigned_by": TEST_USER_IDS["admin"],
            "options": _demo_options("test-permission-builder"),
            "flags": 0,
        },
    )
    _upsert_by_id(
        db,
        TeamWorkflowPermission,
        TEST_PERMISSION_IDS["member"],
        {
            "grantee_organization_id": TEST_ORG_ID,
            "team_id": TEST_TEAM_IDS["qa_member"],
            "workflow_id": TEST_WORKFLOW_ID,
            "auth_state": "viewer",
            "assigned_by": TEST_USER_IDS["admin"],
            "options": _demo_options("test-permission-member"),
            "flags": 0,
        },
    )
    db.commit()


def reset_test_data(db: Session) -> None:
    """Delete fixed test profile rows, then recreate mutable QA seed data."""
    _adopt_existing_test_user_ids(db)
    user_ids = [
        row[0]
        for row in db.query(User.id)
        .filter(
            or_(User.id.in_(list(TEST_USER_IDS.values())), User.email.in_(TEST_EMAILS))
        )
        .all()
    ] or list(TEST_USER_IDS.values())

    # Test reset clears transient builder state child-first while preserving
    # demo and unrelated organizations.
    for model in (AgentBuilderDraft, AgentBuilderRequest, AgentBuilderSession):
        db.query(model).filter(model.organization_id == TEST_ORG_ID).delete(
            synchronize_session=False
        )

    db.query(AuditLog).filter(
        AuditLog.audit_metadata["demo_seed_key"].astext.like("test-%")
    ).delete(synchronize_session=False)
    db.query(LLMUsageLog).filter(LLMUsageLog.user_id.in_(user_ids)).delete(
        synchronize_session=False
    )
    db.query(App).filter(App.id == TEST_APP_ID).update(
        {"workflow_id": None, "active_deployment_id": None},
        synchronize_session=False,
    )
    db.flush()
    db.query(TeamWorkflowPermission).filter(
        TeamWorkflowPermission.id.in_(list(TEST_PERMISSION_IDS.values()))
    ).delete(synchronize_session=False)
    db.query(WorkflowDeployment).filter(
        WorkflowDeployment.id == TEST_DEPLOYMENT_ID
    ).delete(synchronize_session=False)
    db.query(Workflow).filter(Workflow.id == TEST_WORKFLOW_ID).delete(
        synchronize_session=False
    )
    db.query(App).filter(App.id == TEST_APP_ID).delete(synchronize_session=False)
    db.query(PermissionRequest).filter(
        or_(
            PermissionRequest.organization_id == TEST_ORG_ID,
            PermissionRequest.user_id.in_(user_ids),
            PermissionRequest.decided_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    db.query(UserAppCreationPermission).filter(
        or_(
            UserAppCreationPermission.grantee_organization_id == TEST_ORG_ID,
            UserAppCreationPermission.user_id.in_(user_ids),
            UserAppCreationPermission.assigned_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    db.query(TeamMembership).filter(
        or_(
            TeamMembership.grantee_organization_id == TEST_ORG_ID,
            TeamMembership.user_id.in_(user_ids),
            TeamMembership.assigned_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    db.query(OrganizationMembership).filter(
        or_(
            OrganizationMembership.organization_id == TEST_ORG_ID,
            OrganizationMembership.user_id.in_(user_ids),
            OrganizationMembership.invited_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    db.query(Team).filter(Team.id.in_(list(TEST_TEAM_IDS.values()))).delete(
        synchronize_session=False
    )
    db.commit()
    seed_test_data(db)


def seed_demo_data(db: Session) -> None:
    """Upsert final demo data without deleting unrelated local data."""
    validate_demo_seed_prerequisites()
    _seed_users_and_org(db)
    _seed_teams_and_memberships(db)
    _seed_knowledge(db)
    provider, models = _ensure_openai_provider_and_models(db)
    _seed_apps_and_workflows(db)
    db.flush()
    _seed_permissions(db)
    _seed_permission_requests(db)
    _seed_llm_credential(db, provider, models)
    db.flush()
    _seed_runs_and_usage(db, models)
    _seed_audit_logs(db)
    db.commit()


def reset_demo_data(db: Session) -> None:
    """Delete fixed demo rows, then recreate the final demo state."""
    validate_demo_seed_prerequisites()
    _adopt_existing_demo_user_ids(db)
    app_ids = list(APP_IDS.values())
    workflow_ids = list(WORKFLOW_IDS.values())
    team_ids = list(TEAM_IDS.values())
    kb_ids = list(KB_IDS.values())
    credential_ids = [
        row[0]
        for row in db.query(LLMCredential.id)
        .filter(LLMCredential.organization_id == ORG_ID)
        .all()
    ]
    existing_demo_user_ids = [
        row[0]
        for row in db.query(User.id)
        .filter(or_(User.id.in_(list(USER_IDS.values())), User.email.in_(DEMO_EMAILS)))
        .all()
    ]
    user_ids = existing_demo_user_ids or list(USER_IDS.values())

    db.query(TracePayloadAccessEvent).filter(
        TracePayloadAccessEvent.workflow_run_id.in_([_uuid(2000 + i) for i in range(20)])
    ).delete(synchronize_session=False)
    db.query(TracePayload).filter(
        TracePayload.workflow_run_id.in_([_uuid(2000 + i) for i in range(20)])
    ).delete(synchronize_session=False)
    db.query(LLMUsageLog).filter(
        (LLMUsageLog.workflow_id.in_(workflow_ids))
        | (LLMUsageLog.user_id.in_(user_ids))
        | (LLMUsageLog.credential_id.in_(credential_ids))
    ).delete(synchronize_session=False)
    db.query(WorkflowNodeRun).filter(
        WorkflowNodeRun.workflow_run_id.in_([_uuid(2000 + i) for i in range(20)])
    ).delete(synchronize_session=False)
    db.query(WorkflowRun).filter(WorkflowRun.workflow_id.in_(workflow_ids)).delete(
        synchronize_session=False
    )
    db.query(AuditLog).filter(
        AuditLog.audit_metadata["demo_seed"].astext == "true"
    ).delete(synchronize_session=False)

    # Break App <-> Workflow/Deployment references before deleting either side.
    db.query(App).filter(App.id.in_(app_ids)).update(
        {"workflow_id": None, "active_deployment_id": None},
        synchronize_session=False,
    )
    db.flush()

    for model in (
        TeamWorkflowPermission,
        UserWorkflowPermission,
        TeamKnowledgePermission,
        TeamKnowledgeCollectionPermission,
        TeamLLMPermission,
        TeamAuditPermission,
        UserLLMPermission,
    ):
        db.query(model).filter(
            or_(
                model.grantee_organization_id == ORG_ID,
                model.assigned_by.in_(user_ids),
            )
        ).delete(synchronize_session=False)

    db.query(UserKnowledgePermission).filter(
        or_(
            UserKnowledgePermission.knowledge_base_id.in_(kb_ids),
            UserKnowledgePermission.user_id.in_(user_ids),
            UserKnowledgePermission.assigned_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    # 시연 중 라이브로 만든 권한 신청/App 생성 권한도 함께 지워
    # 시나리오 1(차단 -> 신청 -> 승인)을 반복 시연할 수 있게 한다 (ADR-0016).
    db.query(PermissionRequest).filter(
        or_(
            PermissionRequest.organization_id == ORG_ID,
            PermissionRequest.user_id.in_(user_ids),
            PermissionRequest.decided_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    db.query(UserAppCreationPermission).filter(
        or_(
            UserAppCreationPermission.grantee_organization_id == ORG_ID,
            UserAppCreationPermission.user_id.in_(user_ids),
            UserAppCreationPermission.assigned_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)

    if credential_ids:
        db.query(TeamLLMPermission).filter(
            TeamLLMPermission.llm_credential_id.in_(credential_ids)
        ).delete(synchronize_session=False)
        db.query(UserLLMPermission).filter(
            UserLLMPermission.llm_credential_id.in_(credential_ids)
        ).delete(synchronize_session=False)
        if sa_inspect(db.bind).has_table("rag_answer_runs"):
            for credential_id in credential_ids:
                db.execute(
                    text(
                        "UPDATE rag_answer_runs "
                        "SET generation_credential_id = NULL, "
                        "generation_credential_ref = NULL "
                        "WHERE generation_credential_id = :credential_id"
                    ),
                    {"credential_id": credential_id},
                )
        db.query(LLMRelCredentialModel).filter(
            LLMRelCredentialModel.credential_id.in_(credential_ids)
        ).delete(synchronize_session=False)
        db.query(LLMCredential).filter(
            LLMCredential.id.in_(credential_ids)
        ).delete(synchronize_session=False)

    db.query(WorkflowDeployment).filter(
        or_(
            WorkflowDeployment.id.in_(list(DEPLOYMENT_IDS.values())),
            WorkflowDeployment.app_id.in_(app_ids),
        )
    ).delete(synchronize_session=False)
    db.query(Workflow).filter(Workflow.id.in_(workflow_ids)).delete(
        synchronize_session=False
    )
    db.query(App).filter(App.id.in_(app_ids)).delete(synchronize_session=False)

    db.query(LLMRelCredentialModel).filter(
        LLMRelCredentialModel.credential_id == LEGACY_DEMO_LLM_CREDENTIAL_ID
    ).delete(synchronize_session=False)
    db.query(LLMCredential).filter(
        LLMCredential.id == LEGACY_DEMO_LLM_CREDENTIAL_ID
    ).delete(synchronize_session=False)

    db.query(KnowledgeDocumentIngestionJob).filter(
        KnowledgeDocumentIngestionJob.knowledge_base_id.in_(kb_ids)
    ).delete(synchronize_session=False)
    db.query(KnowledgeIngestionOutbox).filter(
        KnowledgeIngestionOutbox.knowledge_base_id.in_(kb_ids)
    ).delete(synchronize_session=False)
    db.query(KnowledgeCollectionItem).filter(
        KnowledgeCollectionItem.collection_id.in_(list(COLLECTION_IDS.values()))
    ).delete(synchronize_session=False)
    db.query(KnowledgeCollection).filter(
        KnowledgeCollection.id.in_(list(COLLECTION_IDS.values()))
    ).delete(synchronize_session=False)
    db.query(DocumentChunk).filter(DocumentChunk.knowledge_base_id.in_(kb_ids)).delete(
        synchronize_session=False
    )
    db.query(Document).filter(Document.knowledge_base_id.in_(kb_ids)).delete(
        synchronize_session=False
    )
    db.query(KnowledgeBase).filter(KnowledgeBase.id.in_(kb_ids)).delete(
        synchronize_session=False
    )

    db.query(TeamMembership).filter(
        or_(
            TeamMembership.grantee_organization_id == ORG_ID,
            TeamMembership.user_id.in_(user_ids),
            TeamMembership.assigned_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    db.query(OrganizationMembership).filter(
        or_(
            OrganizationMembership.organization_id == ORG_ID,
            OrganizationMembership.user_id.in_(user_ids),
            OrganizationMembership.invited_by.in_(user_ids),
        )
    ).delete(synchronize_session=False)
    db.query(Team).filter(Team.id.in_(team_ids)).delete(synchronize_session=False)

    db.commit()
    seed_demo_data(db)
