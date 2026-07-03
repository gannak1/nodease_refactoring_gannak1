"""Final demo database seed helpers.

이 모듈은 최종 시연용 로컬 DB 상태를 재현하기 위한 전용 seed다.
기본 실행은 upsert로 동작하고, reset 실행은 demo seed가 관리하는 row만
삭제/복원한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from apps.gateway.services.auth_service import AuthService
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.app import App
from apps.shared.db.models.audit_log import (
    ActorType,
    AuditCategory,
    AuditLog,
    AuditStatus,
)
from apps.shared.db.models.knowledge import KnowledgeBase, SourceType
from apps.shared.db.models.knowledge import Document
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
from apps.shared.db.models.team import (
    Team,
    TeamAuditPermission,
    TeamKnowledgePermission,
    TeamLLMPermission,
    TeamMembership,
    TeamWorkflowPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
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

DEMO_SEED_VERSION = "final-demo-2026-07"
DEMO_PASSWORD = "123123"
DEMO_UPLOAD_DIR = Path("/app/uploads/demo_seed")


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
}

TEAM_IDS = {
    "platform_admin": _uuid(200),
    "ai_builder_onboarding": _uuid(201),
    "customer_support_ops": _uuid(202),
    "hr_knowledge_users": _uuid(203),
    "finance_restricted": _uuid(204),
    "tester_builder": _uuid(205),
    "tester_member": _uuid(206),
}

KB_IDS = {
    "hr": _uuid(300),
    "finance": _uuid(301),
}

DOCUMENT_IDS = {
    "hr_leave": _uuid(310),
    "hr_welfare": _uuid(311),
    "finance_sensitive": _uuid(312),
}

APP_IDS = {
    "hr_bot_example": _uuid(400),
    "ticket_ops": _uuid(401),
    "ticket_ops_warning": _uuid(402),
    "ticket_ops_risk": _uuid(403),
    "ticket_ops_paused": _uuid(404),
    "test_inquiry": _uuid(405),
}

WORKFLOW_IDS = {
    key: _uuid(500 + index)
    for index, key in enumerate(APP_IDS.keys())
}

DEPLOYMENT_IDS = {
    key: _uuid(600 + index)
    for index, key in enumerate(APP_IDS.keys())
}

LEGACY_DEMO_LLM_CREDENTIAL_ID = _uuid(700)

TEAM_PERMISSION_IDS = {
    "customer_ticket": _uuid(800),
    "hr_bot": _uuid(801),
    "test_builder": _uuid(802),
    "test_member": _uuid(803),
}


@dataclass(frozen=True)
class DemoUserSpec:
    key: str
    email: str
    name: str
    membership_state: str
    organization_auth_state: str
    teams: tuple[str, ...]


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
        "test.admin@nodease.local",
        "테스트 관리자",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MANAGER,
        ("qa_admin",),
    ),
    DemoUserSpec(
        "builder",
        "test.builder@nodease.local",
        "테스트 빌더",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("qa_builder",),
    ),
    DemoUserSpec(
        "member",
        "test.member@nodease.local",
        "테스트 멤버",
        ORGANIZATION_MEMBERSHIP_ACTIVE,
        ORGANIZATION_AUTH_MEMBER,
        ("qa_member",),
    ),
    DemoUserSpec(
        "invited",
        "test.invited@nodease.local",
        "테스트 초대대기",
        ORGANIZATION_MEMBERSHIP_INVITED,
        ORGANIZATION_AUTH_MEMBER,
        (),
    ),
    DemoUserSpec(
        "suspended",
        "test.suspended@nodease.local",
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
        }
    return {
        "profile": "demo",
        "seed_version": DEMO_SEED_VERSION,
        "organization": "노디즈 데모 조직",
        "users": [spec.email for spec in USER_SPECS],
        "teams": [name for name, _ in TEAM_SPECS.values()],
        "apps": [
            "사내 문서 질문 응답 봇",
            "Enterprise 고객 티켓 처리",
            "테스트용 문의 응답 워크플로우",
        ],
        "reset_scope": "demo seed fixed UUID rows only",
        "credentials": "not seeded",
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
    DEMO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    path = DEMO_UPLOAD_DIR / filename
    path.write_text(content, encoding="utf-8")
    return path.as_posix()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _upsert_by_id(db: Session, model: type, row_id: uuid.UUID, values: dict[str, Any]):
    row = db.get(model, row_id)
    if row is None:
        row = model(id=row_id)
        db.add(row)
    for key, value in values.items():
        setattr(row, key, value)
    return row


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
                    "model_id": "gpt-4.1-mini",
                    "system_prompt": "사내 복지, 휴가, 인사 정책 문서를 근거로 간결하게 답변합니다.",
                    "user_prompt": "질문: {{ question }}",
                    "referenced_variables": [
                        {
                            "name": "question",
                            "value_selector": ["start-question", "question"],
                        }
                    ],
                    "knowledgeBases": [str(KB_IDS["hr"])],
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
                    "path": "enterprise-ticket-demo",
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
                    "model_id": "gpt-4.1",
                    "system_prompt": "고객지원 티켓을 정책 기반 JSON으로 분류합니다.",
                    "user_prompt": "고객 등급: {{ customerTier }}\n문의: {{ message }}",
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
                    "knowledgeBases": [str(KB_IDS["hr"])],
                    "parameters": {"temperature": 0.2, "max_tokens": 2000},
                },
            ),
            _node(
                "extract-ticket",
                "variableExtractionNode",
                960,
                220,
                {
                    **_base_node_data("처리 결과 추출", "LLM JSON 문자열을 후속 분기 변수로 추출합니다.", 3),
                    "source": {"node_id": "llm-triage", "field": "text"},
                    "variables": [
                        {"name": "severity", "type": "string"},
                        {"name": "approvalRequired", "type": "boolean"},
                        {"name": "customerReplyDraft", "type": "string"},
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
                    "template": "승인 요청: Enterprise 고객 보상 검토가 필요합니다.",
                    "variables": [],
                },
            ),
            _node(
                "template-reply",
                "templateNode",
                1800,
                360,
                {
                    **_base_node_data("고객 답변 초안", "고객에게 보낼 답변을 정리합니다.", 6),
                    "template": "{{ customerReplyDraft }}",
                    "variables": [
                        {
                            "name": "customerReplyDraft",
                            "value_selector": [
                                "extract-ticket",
                                "customerReplyDraft",
                            ],
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


def _output_schema() -> dict[str, Any]:
    return {"outputs": [{"variable": "answer_text", "label": "답변"}]}


def _seed_users_and_org(db: Session) -> None:
    _adopt_existing_demo_user_ids(db)
    hashed_password = AuthService.hash_password(DEMO_PASSWORD)
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


def _seed_knowledge(db: Session) -> None:
    _upsert_by_id(
        db,
        KnowledgeBase,
        KB_IDS["hr"],
        {
            "organization_id": ORG_ID,
            "name": "사내 인사·복지 지식베이스",
            "description": "휴가, 복지, 인사 정책 문서를 모은 데모 지식베이스",
            "embedding_model": "text-embedding-3-small",
            "top_k": 5,
            "similarity_threshold": 0.7,
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
    db.flush()

    document_specs = {
        "hr_leave": (
            KB_IDS["hr"],
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
            KB_IDS["hr"],
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
            KB_IDS["finance"],
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
                "embedding_model": "text-embedding-3-small",
            },
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
        "gpt-4.1": (Decimal("0.002000"), Decimal("0.008000"), 128000),
        "gpt-4.1-mini": (Decimal("0.000400"), Decimal("0.001600"), 128000),
    }
    models: dict[str, LLMModel] = {}
    for model_id, (input_price, output_price, context_window) in model_specs.items():
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
                type="chat",
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
            model.type = "chat"
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
    app = _upsert_by_id(
        db,
        App,
        APP_IDS[key],
        {
            "organization_id": ORG_ID,
            "name": name,
            "description": description,
            "icon": _icon("🧭" if key == "ticket_ops" else "📘"),
            "url_slug": f"demo-{key}",
            "auth_secret": f"sk-demo-{key}",
            "is_api_enabled": True,
            "api_req_per_minute": 60,
            "api_req_per_hour": 3600,
            "is_market": False,
            "forked_from": None,
            "created_by": USER_IDS[owner_key],
            "workflow_id": None,
            "active_deployment_id": None,
        },
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
                "input_schema": _input_schema("message", "문의"),
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
        ("ticket_ops_warning", "예산 90% 근접 티켓 처리 A", "author"),
        ("ticket_ops_risk", "예산 90% 근접 티켓 처리 B", "author"),
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
    model_name: str = "gpt-4.1",
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
        ("webhook-ticket", "webhookTriggerNode", 0.02, {"message": run.inputs["message"]}),
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
        ("extract-ticket", "variableExtractionNode", 0.03, {"approvalRequired": True}),
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


def _seed_runs_and_usage(db: Session, models: dict[str, LLMModel]) -> None:
    now = _now()
    run_specs = [
        ("ticket_ops", "author", RunStatus.SUCCESS, 4.8, 10120, Decimal("0.0820"), "CS 리드 승인 요청이 필요합니다.", "gpt-4.1", 8200, 1920, 4800),
        ("ticket_ops", "author", RunStatus.SUCCESS, 4.1, 9800, Decimal("0.0780"), "Enterprise 고객 장애 티켓으로 우선 처리합니다.", "gpt-4.1", 7900, 1900, 4100),
        ("ticket_ops", "author", RunStatus.SUCCESS, 1.9, 3280, Decimal("0.0220"), "권한 기반 RAG와 중간 모델로 처리했습니다.", "gpt-4.1-mini", 2600, 680, 1900),
        ("ticket_ops", "author", RunStatus.SUCCESS, 2.2, 3410, Decimal("0.0240"), "승인 필요 여부를 판단했습니다.", "gpt-4.1-mini", 2700, 710, 2200),
        ("ticket_ops", "author", RunStatus.SUCCESS, 2.4, 3650, Decimal("0.0260"), "고객 답변 초안을 생성했습니다.", "gpt-4.1-mini", 2890, 760, 2400),
        ("ticket_ops", "author", RunStatus.SUCCESS, 2.1, 3400, Decimal("0.0230"), "SLA 기준에 따라 기술지원팀으로 배정했습니다.", "gpt-4.1-mini", 2720, 680, 2100),
        ("ticket_ops", "author", RunStatus.FAILED, 1.3, 1200, Decimal("0.0060"), None, "gpt-4.1-mini", 1000, 200, 1300),
        ("ticket_ops_warning", "author", RunStatus.SUCCESS, 5.2, 11200, Decimal("0.0910"), "비용 위험 workflow 실행입니다.", "gpt-4.1", 9100, 2100, 5200),
        ("ticket_ops_risk", "author", RunStatus.SUCCESS, 4.9, 10800, Decimal("0.0880"), "비용 위험 workflow 실행입니다.", "gpt-4.1", 8700, 2100, 4900),
        ("ticket_ops_paused", "author", RunStatus.FAILED, 0.4, 0, Decimal("0.0000"), None, "gpt-4.1", 0, 0, 0),
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

        # Credential은 팀원이 직접 등록해 실험해야 하므로 seed하지 않는다.
        # LLMUsageLog.credential_id가 non-null이라 더미 credential 없이 usage row도 만들지 않는다.


def _seed_audit_logs(db: Session) -> None:
    now = _now()
    logs = [
        (AuditAction.USER_LOGIN, "user", USER_IDS["rookie"], "신입사원 로그인"),
        ("permission.request", "workflow", str(WORKFLOW_IDS["hr_bot_example"]), "신입사원 workflow 생성 권한 신청"),
        (AuditAction.PERMISSION_GRANT, "workflow", str(WORKFLOW_IDS["hr_bot_example"]), "관리자 권한 승인"),
        (AuditAction.WORKFLOW_CREATE, "workflow", str(WORKFLOW_IDS["hr_bot_example"]), "사내 문서 질문 응답 봇 생성"),
        (AuditAction.WORKFLOW_DEPLOY, "workflow", str(WORKFLOW_IDS["ticket_ops"]), "Enterprise 고객 티켓 처리 배포"),
        (AuditAction.WORKFLOW_EXECUTE, "workflow", str(WORKFLOW_IDS["ticket_ops"]), "고객 티켓 workflow 실행"),
        (AuditAction.PERMISSION_DENIED, "workflow", str(WORKFLOW_IDS["ticket_ops"]), "권한 없는 workflow 접근 차단"),
        (AuditAction.POLICY_BLOCK, "knowledge", str(KB_IDS["finance"]), "민감 문서 접근 정책 차단"),
        (AuditAction.LLM_CALL, "workflow", str(WORKFLOW_IDS["ticket_ops"]), "LLM 비용 사용 기록"),
    ]
    for index, (action, target_type, target_id, summary) in enumerate(logs):
        _upsert_by_id(
            db,
            AuditLog,
            _uuid(4000 + index),
            {
                "occurred_at": now - timedelta(minutes=index * 7),
                "actor_id": USER_IDS["admin"] if index in {2, 7} else USER_IDS["rookie" if index < 4 else "author"],
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
    hashed_password = AuthService.hash_password(DEMO_PASSWORD)

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
                "state": spec.membership_state,
                "auth_state": spec.organization_auth_state,
                "invited_by": TEST_USER_IDS["admin"],
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
    app = _upsert_by_id(
        db,
        App,
        TEST_APP_ID,
        {
            "organization_id": TEST_ORG_ID,
            "name": "테스트용 기능 검증 워크플로우",
            "description": "팀원이 기능 구현 중 자유롭게 변경해도 되는 테스트 workflow",
            "icon": _icon("🧪"),
            "url_slug": "test-feature-workflow",
            "auth_secret": "sk-test-feature-workflow",
            "is_api_enabled": True,
            "api_req_per_minute": 60,
            "api_req_per_hour": 3600,
            "is_market": False,
            "forked_from": None,
            "created_by": TEST_USER_IDS["builder"],
            "workflow_id": None,
            "active_deployment_id": None,
        },
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
    db.query(Organization).filter(Organization.id == TEST_ORG_ID).delete(
        synchronize_session=False
    )
    db.commit()
    seed_test_data(db)


def seed_demo_data(db: Session) -> None:
    """Upsert final demo data without deleting unrelated local data."""
    _seed_users_and_org(db)
    _seed_teams_and_memberships(db)
    _seed_knowledge(db)
    _, models = _ensure_openai_provider_and_models(db)
    _seed_apps_and_workflows(db)
    db.flush()
    _seed_permissions(db)
    _seed_runs_and_usage(db, models)
    _seed_audit_logs(db)
    db.commit()


def reset_demo_data(db: Session) -> None:
    """Delete fixed demo rows, then recreate the final demo state."""
    _adopt_existing_demo_user_ids(db)
    app_ids = list(APP_IDS.values())
    workflow_ids = list(WORKFLOW_IDS.values())
    team_ids = list(TEAM_IDS.values())
    kb_ids = list(KB_IDS.values())
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
        TeamLLMPermission,
        TeamAuditPermission,
    ):
        db.query(model).filter(
            or_(
                model.grantee_organization_id == ORG_ID,
                model.assigned_by.in_(user_ids),
            )
        ).delete(synchronize_session=False)

    db.query(WorkflowDeployment).filter(
        WorkflowDeployment.id.in_(list(DEPLOYMENT_IDS.values()))
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
    db.query(Organization).filter(Organization.id == ORG_ID).delete(
        synchronize_session=False
    )

    db.commit()
    seed_demo_data(db)
