"""
Database seed helpers for startup.

- Seeds a placeholder user for local/dev
- Seeds system LLM providers (idempotent)
"""

import hashlib
import logging
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session

from apps.shared.db.models.app import App
from apps.shared.db.models.knowledge import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    SourceType,
)
from apps.shared.db.models.llm import LLMProvider
from apps.shared.db.models.team import Team, TeamKnowledgePermission, TeamMembership
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    RunTriggerMode,
    WorkflowNodeRun,
    WorkflowRun,
)

PLACEHOLDER_USER_ID = uuid.UUID("12345678-1234-5678-1234-567812345678")
DEMO_FAMILY_CARE_NAMESPACE_ID = uuid.UUID("30000000-0000-0000-0000-000000000100")
DEMO_FAMILY_CARE_KB_ID = uuid.UUID("30000000-0000-0000-0000-000000000101")
DEMO_FAMILY_CARE_DOC_ID = uuid.UUID("30000000-0000-0000-0000-000000000102")
DEMO_FAMILY_CARE_CHUNK_IDS = [
    uuid.UUID("30000000-0000-0000-0000-000000000103"),
    uuid.UUID("30000000-0000-0000-0000-000000000104"),
]
DEV_WORKFLOW_APP_IDS = {
    "template": uuid.UUID("20000000-0000-0000-0000-000000000001"),
    "llm": uuid.UUID("20000000-0000-0000-0000-000000000002"),
    "branch": uuid.UUID("20000000-0000-0000-0000-000000000003"),
}
DEV_WORKFLOW_IDS = {
    "template": uuid.UUID("21000000-0000-0000-0000-000000000001"),
    "llm": uuid.UUID("21000000-0000-0000-0000-000000000002"),
    "branch": uuid.UUID("21000000-0000-0000-0000-000000000003"),
}
DEV_DEPLOYMENT_IDS = {
    "template": uuid.UUID("22000000-0000-0000-0000-000000000001"),
    "llm": uuid.UUID("22000000-0000-0000-0000-000000000002"),
    "branch": uuid.UUID("22000000-0000-0000-0000-000000000003"),
}

logger = logging.getLogger(__name__)


def seed_placeholder_user(db: Session) -> None:
    """Ensure the dev placeholder user exists."""
    user = db.query(User).filter(User.id == PLACEHOLDER_USER_ID).first()
    if user:
        return

    from services.auth_service import AuthService

    dev_user = User(
        id=PLACEHOLDER_USER_ID,
        email="dev@moduly.app",
        name="Dev User",
        password=AuthService.hash_password("dev-password"),
        social_provider="none",
    )
    db.add(dev_user)
    db.commit()
    logger.info(
        "✅ 기본 user유저 (id: dev@moduly.app / password: dev-password ) 생성완료!"
    )


def _default_providers() -> Iterable[LLMProvider]:
    """Return the default LLM provider rows to seed."""
    return [
        LLMProvider(
            name="openai",
            description="OpenAI default provider",
            base_url="https://api.openai.com/v1",
            type="system",
            auth_type="api_key",
            doc_url="https://platform.openai.com/api-keys",
        ),
        LLMProvider(
            name="anthropic",
            description="Anthropic Claude provider",
            base_url="https://api.anthropic.com/v1",
            type="system",
            auth_type="api_key",
            doc_url="https://console.anthropic.com/settings/keys",
        ),
        LLMProvider(
            name="google",
            description="Google Gemini provider",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
            type="system",
            auth_type="api_key",
            doc_url="https://aistudio.google.com/",
        ),
        LLMProvider(
            name="llamaparse",
            description="LlamaParse high-quality document parser (LlamaIndex Cloud)",
            base_url="https://api.cloud.llamaindex.ai",
            type="system",
            auth_type="api_key",
            doc_url="https://cloud.llamaindex.ai/api-key",
        ),
    ]


def seed_default_llm_providers(db: Session) -> None:
    """Insert default providers if missing; idempotent per name."""
    existing_providers = db.query(LLMProvider).all()
    existing_names = {p.name for p in existing_providers}

    providers_to_add = [p for p in _default_providers() if p.name not in existing_names]
    if not providers_to_add:
        logger.warning(
            f"ℹ️ LLM providers already exist ({len(existing_providers)}). Skipping seed."
        )
        return

    db.add_all(providers_to_add)
    db.commit()
    logger.info("✅ Default LLM providers seeded!")


def seed_default_llm_models(db: Session) -> None:
    """
    KNOWN_MODEL_PRICES를 기반으로 기본 LLM 모델을 시드합니다.
    gpt-4.1, o3-mini와 같은 모델이 DB에 존재하도록 보장합니다.
    또한, 해당 모델이 UI에 표시되도록 기존 Credential과 연결합니다.
    """
    from apps.gateway.services.llm_service import LLMService
    from apps.shared.db.models.llm import (
        LLMModel,
        LLMProvider,
    )

    # 1. 모든 Provider 조회 후 맵핑 생성
    providers = db.query(LLMProvider).all()
    provider_map = {p.name: p for p in providers}

    # 2. 기존 생성된 모델 조회
    existing_models = db.query(LLMModel).all()
    existing_model_ids = {m.model_id_for_api_call for m in existing_models}

    # Provider 매핑 규칙 (휴리스틱)
    def get_provider_name(model_id: str) -> str:
        if model_id.startswith("claude"):
            return "anthropic"
        elif model_id.startswith("gemini"):
            return "google"
        elif model_id.startswith("llamaparse"):
            return "llamaparse"
        else:
            return "openai"  # gpt, o1, o3, dall-e, tts, whisper 등은 기본적으로 OpenAI로 처리

    models_seeded_count = 0
    models_updated_count = 0

    # 3. KNOWN_MODEL_PRICES 순회하며 모델 생성 또는 가격 업데이트
    for model_id, pricing in LLMService.KNOWN_MODEL_PRICES.items():
        provider_name = get_provider_name(model_id)
        provider = provider_map.get(provider_name)

        if not provider:
            continue

        # 모델 찾기 또는 생성
        model = None
        if model_id in existing_model_ids:
            # 기존 모델 객체 찾기
            model = next(
                (m for m in existing_models if m.model_id_for_api_call == model_id),
                None,
            )
            # [NEW] 기존 모델이지만 가격 정보가 없으면 업데이트
            if model and (
                model.input_price_1k is None or model.output_price_1k is None
            ):
                model.input_price_1k = pricing["input"]
                model.output_price_1k = pricing["output"]
                db.add(model)
                models_updated_count += 1
        else:
            # 새 모델 생성
            new_model_uuid = uuid.uuid4()
            model = LLMModel(
                id=new_model_uuid,
                provider_id=provider.id,
                model_id_for_api_call=model_id,
                name=model_id,
                type="embedding" if "embedding" in model_id else "chat",
                context_window=128000
                if "gpt-4" in model_id or "o1" in model_id or "claude" in model_id
                else 8192,
                input_price_1k=pricing["input"],
                output_price_1k=pricing["output"],
                is_active=True,
            )
            db.add(model)
            models_seeded_count += 1
            # 중복 방지를 위해 캐시 업데이트
            existing_model_ids.add(model_id)
            existing_models.append(model)

        if not model:
            continue

    if models_seeded_count > 0 or models_updated_count > 0:
        if models_seeded_count > 0:
            logger.info(f"🌱 Seeded {models_seeded_count} new LLM models.")
        if models_updated_count > 0:
            logger.info(
                f"💰 Updated pricing for {models_updated_count} existing models."
            )
        db.commit()
        logger.info("✅ LLM models sync complete!")
    else:
        logger.warning("ℹ️ LLM models up to date.")


def _demo_embedding(seed: int) -> list[float]:
    """Return a stable non-zero vector for demo KB chunks."""
    value = 0.001 + (seed * 0.0001)
    return [value] * 1536


def _agent_demo_id(user_id: uuid.UUID, organization_id: uuid.UUID, label: str) -> uuid.UUID:
    if user_id == PLACEHOLDER_USER_ID:
        fixed_ids = {
            "kb": DEMO_FAMILY_CARE_KB_ID,
            "doc": DEMO_FAMILY_CARE_DOC_ID,
            "chunk-0": DEMO_FAMILY_CARE_CHUNK_IDS[0],
            "chunk-1": DEMO_FAMILY_CARE_CHUNK_IDS[1],
        }
        if label in fixed_ids:
            return fixed_ids[label]
    return uuid.uuid5(
        DEMO_FAMILY_CARE_NAMESPACE_ID,
        f"{organization_id}:{user_id}:{label}",
    )


def _family_care_demo_chunks() -> list[tuple[str, str]]:
    return [
        (
            "가족돌봄휴가 사용 및 연차 연속 사용",
            (
                "데모용 사내 정책 예시: 가족돌봄휴가는 가족의 질병, 사고, 노령 "
                "또는 자녀 양육 등 가족 돌봄 사유가 있을 때 신청할 수 있다. "
                "가족돌봄휴가와 연차휴가는 서로 다른 휴가 유형이므로 같은 날짜에 "
                "중복 사용할 수는 없지만, 승인 절차를 각각 완료하면 가족돌봄휴가 "
                "전후로 연차휴가를 이어서 사용할 수 있다. 예를 들어 월요일과 "
                "화요일은 가족돌봄휴가, 수요일은 연차휴가로 이어서 신청할 수 있다."
            ),
        ),
        (
            "가족돌봄휴가 신청 위치와 증빙자료",
            (
                "가족돌봄휴가는 사내 HR 포털의 근태/휴가 메뉴에서 휴가 신청을 "
                "선택한 뒤 휴가 유형을 가족돌봄휴가로 지정해 신청한다. 이어서 "
                "사용할 연차가 있으면 별도의 연차휴가 신청으로 등록한다. 회사는 "
                "필요 시 병원 예약 확인서, 진료 일정표, 가족관계 확인 자료처럼 "
                "돌봄 사유와 가족 관계를 확인할 수 있는 증빙자료를 요청할 수 있다. "
                "증빙자료는 신청 화면에 첨부하거나 HR 담당자에게 제출한다."
            ),
        ),
    ]


def _ensure_demo_team_memberships(
    db: Session,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
) -> list[TeamMembership]:
    memberships = (
        db.query(TeamMembership)
        .join(Team, Team.id == TeamMembership.team_id)
        .filter(
            TeamMembership.user_id == user_id,
            TeamMembership.grantee_organization_id == organization_id,
            Team.organization_id == organization_id,
            Team.is_active.is_(True),
        )
        .all()
    )
    if memberships:
        return memberships

    team = (
        db.query(Team)
        .filter(Team.organization_id == organization_id, Team.name == "Default")
        .first()
    )
    if team is None:
        team = Team(
            id=uuid.uuid4(),
            organization_id=organization_id,
            name="Default",
            created_by=user_id,
            managed_by=user_id,
            is_auto_add=True,
        )
        db.add(team)
        db.flush()

    membership = TeamMembership(
        grantee_organization_id=organization_id,
        user_id=user_id,
        team_id=team.id,
        assigned_by=user_id,
    )
    db.add(membership)
    db.flush()
    return [membership]


def _grant_demo_knowledge_base_use(
    db: Session,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    knowledge_base_id: uuid.UUID,
) -> None:
    for membership in _ensure_demo_team_memberships(db, user_id, organization_id):
        permission = (
            db.query(TeamKnowledgePermission)
            .filter(
                TeamKnowledgePermission.grantee_organization_id == organization_id,
                TeamKnowledgePermission.knowledge_base_id == knowledge_base_id,
                TeamKnowledgePermission.team_id == membership.team_id,
            )
            .first()
        )
        if permission is None:
            permission = TeamKnowledgePermission(
                grantee_organization_id=organization_id,
                knowledge_base_id=knowledge_base_id,
                team_id=membership.team_id,
                assigned_by=user_id,
            )
            db.add(permission)
        permission.auth_state = "operator"


def ensure_agent_family_care_knowledge_base(
    db: Session,
    user_id: uuid.UUID,
    organization_id: uuid.UUID | None = None,
) -> KnowledgeBase:
    """Ensure a family-care-leave demo KB for the active agent user/org."""

    from apps.gateway.services.organization_context import (
        ensure_user_default_organization,
    )

    user_id = uuid.UUID(str(user_id))
    organization_id = (
        uuid.UUID(str(organization_id))
        if organization_id
        else ensure_user_default_organization(db, user_id)
    )
    kb_id = _agent_demo_id(user_id, organization_id, "kb")
    doc_id = _agent_demo_id(user_id, organization_id, "doc")
    chunk_ids = [
        _agent_demo_id(user_id, organization_id, "chunk-0"),
        _agent_demo_id(user_id, organization_id, "chunk-1"),
    ]
    now = datetime.now(timezone.utc)
    chunks = _family_care_demo_chunks()
    full_content = "\n\n".join(content for _, content in chunks)
    content_hash = hashlib.sha256(full_content.encode("utf-8")).hexdigest()

    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id).first()
    if kb is None:
        kb = KnowledgeBase(id=kb_id)
        db.add(kb)

    kb.name = "가족돌봄휴가 안내"
    kb.description = (
        "Workflow Builder Agent 시연용 가족돌봄휴가 정책 예시 문서입니다."
    )
    kb.embedding_model = "text-embedding-3-small"
    kb.top_k = 5
    kb.similarity_threshold = 0.15
    kb.user_id = user_id
    kb.organization_id = organization_id
    kb.updated_at = now

    document = db.query(Document).filter(Document.id == doc_id).first()
    if document is None:
        document = Document(
            id=doc_id,
            knowledge_base_id=kb_id,
            filename="demo-family-care-leave-policy.md",
        )
        db.add(document)

    document.knowledge_base_id = kb_id
    document.filename = "demo-family-care-leave-policy.md"
    document.file_path = None
    document.source_type = SourceType.FILE
    document.content_hash = content_hash
    document.status = "completed"
    document.error_message = None
    document.chunk_size = 1000
    document.chunk_overlap = 120
    document.embedding_model = kb.embedding_model
    document.meta_info = {
        "demo": True,
        "agent_created": True,
        "domain": "hr",
        "topics": ["family_care_leave", "annual_leave", "evidence"],
        "source": "workflow_builder_agent",
    }
    document.updated_at = now

    db.flush()
    (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == doc_id)
        .delete(synchronize_session=False)
    )
    for index, (heading, content) in enumerate(chunks):
        db.add(
            DocumentChunk(
                id=chunk_ids[index],
                document_id=doc_id,
                knowledge_base_id=kb_id,
                content=content,
                embedding=_demo_embedding(index),
                chunk_index=index,
                chunk_level="section",
                section_path=["가족돌봄휴가 안내", heading],
                heading=heading,
                token_count=max(1, len(content) // 3),
                metadata_={
                    "demo": True,
                    "agent_created": True,
                    "domain": "hr",
                    "heading": heading,
                    "keywords": [
                        "가족돌봄휴가",
                        "연차",
                        "신청",
                        "증빙자료",
                        "HR 포털",
                    ],
                },
            )
        )

    _grant_demo_knowledge_base_use(db, user_id, organization_id, kb_id)
    db.commit()
    db.refresh(kb)
    return kb


def seed_demo_family_care_knowledge_base(db: Session) -> None:
    """Seed the family-care-leave demo KB used by the workflow builder agent."""

    from apps.gateway.services.organization_context import (
        ensure_user_default_organization,
    )

    organization_id = ensure_user_default_organization(db, PLACEHOLDER_USER_ID)
    now = datetime.now(timezone.utc)
    chunks = [
        (
            DEMO_FAMILY_CARE_CHUNK_IDS[0],
            "가족돌봄휴가 사용 및 연차 연속 사용",
            (
                "데모용 사내 정책 예시: 가족돌봄휴가는 가족의 질병, 사고, 노령 "
                "또는 자녀 양육 등 가족 돌봄 사유가 있을 때 신청할 수 있다. "
                "가족돌봄휴가와 연차휴가는 서로 다른 휴가 유형이므로 같은 날짜에 "
                "중복 사용할 수는 없지만, 승인 절차를 각각 완료하면 가족돌봄휴가 "
                "전후로 연차휴가를 이어서 사용할 수 있다. 예를 들어 월요일과 "
                "화요일은 가족돌봄휴가, 수요일은 연차휴가로 이어서 신청할 수 있다."
            ),
        ),
        (
            DEMO_FAMILY_CARE_CHUNK_IDS[1],
            "가족돌봄휴가 신청 위치와 증빙자료",
            (
                "가족돌봄휴가는 사내 HR 포털의 근태/휴가 메뉴에서 휴가 신청을 "
                "선택한 뒤 휴가 유형을 가족돌봄휴가로 지정해 신청한다. 이어서 "
                "사용할 연차가 있으면 별도의 연차휴가 신청으로 등록한다. 회사는 "
                "필요 시 병원 예약 확인서, 진료 일정표, 가족관계 확인 자료처럼 "
                "돌봄 사유와 가족 관계를 확인할 수 있는 증빙자료를 요청할 수 있다. "
                "증빙자료는 신청 화면에 첨부하거나 HR 담당자에게 제출한다."
            ),
        ),
    ]
    full_content = "\n\n".join(content for _, _, content in chunks)
    content_hash = hashlib.sha256(full_content.encode("utf-8")).hexdigest()

    kb = (
        db.query(KnowledgeBase)
        .filter(KnowledgeBase.id == DEMO_FAMILY_CARE_KB_ID)
        .first()
    )
    if kb is None:
        kb = KnowledgeBase(
            id=DEMO_FAMILY_CARE_KB_ID,
            user_id=PLACEHOLDER_USER_ID,
            organization_id=organization_id,
        )
        db.add(kb)

    kb.name = "가족돌봄휴가 안내"
    kb.description = (
        "Workflow Builder Agent 시연용 가족돌봄휴가 정책 예시 문서입니다."
    )
    kb.embedding_model = "text-embedding-3-small"
    kb.top_k = 5
    kb.similarity_threshold = 0.15
    kb.user_id = PLACEHOLDER_USER_ID
    kb.organization_id = organization_id
    kb.updated_at = now

    document = (
        db.query(Document).filter(Document.id == DEMO_FAMILY_CARE_DOC_ID).first()
    )
    if document is None:
        document = Document(
            id=DEMO_FAMILY_CARE_DOC_ID,
            knowledge_base_id=DEMO_FAMILY_CARE_KB_ID,
            filename="demo-family-care-leave-policy.md",
        )
        db.add(document)

    document.knowledge_base_id = DEMO_FAMILY_CARE_KB_ID
    document.filename = "demo-family-care-leave-policy.md"
    document.file_path = None
    document.source_type = SourceType.FILE
    document.content_hash = content_hash
    document.status = "completed"
    document.error_message = None
    document.chunk_size = 1000
    document.chunk_overlap = 120
    document.embedding_model = kb.embedding_model
    document.meta_info = {
        "demo": True,
        "domain": "hr",
        "topics": ["family_care_leave", "annual_leave", "evidence"],
        "source": "seed",
    }
    document.updated_at = now

    db.flush()
    (
        db.query(DocumentChunk)
        .filter(DocumentChunk.document_id == DEMO_FAMILY_CARE_DOC_ID)
        .delete(synchronize_session=False)
    )
    for index, (chunk_id, heading, content) in enumerate(chunks):
        db.add(
            DocumentChunk(
                id=chunk_id,
                document_id=DEMO_FAMILY_CARE_DOC_ID,
                knowledge_base_id=DEMO_FAMILY_CARE_KB_ID,
                content=content,
                embedding=_demo_embedding(index),
                chunk_index=index,
                chunk_level="section",
                section_path=["가족돌봄휴가 안내", heading],
                heading=heading,
                token_count=max(1, len(content) // 3),
                metadata_={
                    "demo": True,
                    "domain": "hr",
                    "heading": heading,
                    "keywords": [
                        "가족돌봄휴가",
                        "연차",
                        "신청",
                        "증빙자료",
                        "HR 포털",
                    ],
                },
            )
        )

    db.commit()
    logger.info("Family care leave demo knowledge base seeded.")


def _node(
    node_id: str,
    node_type: str,
    x: int,
    y: int,
    data: dict,
) -> dict:
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
    target_handle: str | None = None,
) -> dict:
    edge = {"id": edge_id, "source": source, "target": target}
    if source_handle is not None:
        edge["sourceHandle"] = source_handle
    if target_handle is not None:
        edge["targetHandle"] = target_handle
    return edge


def _base_data(
    title: str,
    description: str,
    display_number: int,
    visible_properties: list[str] | None = None,
) -> dict:
    return {
        "title": title,
        "description": description,
        "displayNumber": display_number,
        "visibleProperties": visible_properties or [],
    }


def _start_data(
    title: str,
    description: str,
    display_number: int,
    variables: list[dict],
) -> dict:
    data = _base_data(title, description, display_number)
    # 프론트는 triggerType, 엔진은 trigger_type을 사용하므로 dev seed에는 둘 다 둔다.
    data.update(
        {
            "triggerType": "manual",
            "trigger_type": "manual",
            "variables": variables,
        }
    )
    return data


def _input_variable(
    variable_id: str,
    name: str,
    label: str,
    variable_type: str,
    required: bool = True,
    **extra,
) -> dict:
    return {
        "id": variable_id,
        "name": name,
        "label": label,
        "type": variable_type,
        "required": required,
        **extra,
    }


def _template_quick_reply_graph() -> dict:
    nodes = [
        _node(
            "start-customer",
            "startNode",
            0,
            120,
            _start_data(
                "고객 문의 입력",
                "고객 문의와 우선순위를 입력받습니다.",
                1,
                [
                    _input_variable(
                        "customer_message",
                        "customer_message",
                        "고객 문의",
                        "paragraph",
                        maxLength=1000,
                        max_length=1000,
                    ),
                    _input_variable(
                        "priority",
                        "priority",
                        "우선순위",
                        "select",
                        options=[
                            {"label": "일반", "value": "normal"},
                            {"label": "긴급", "value": "urgent"},
                        ],
                    ),
                ],
            ),
        ),
        _node(
            "template-reply",
            "templateNode",
            420,
            120,
            {
                **_base_data(
                    "응답 초안 생성",
                    "문의와 우선순위를 조합해 답변 초안을 만듭니다.",
                    2,
                    ["template", "variables"],
                ),
                "template": (
                    "문의 요약:\n"
                    "- 고객 문의: {{ customer_message }}\n"
                    "- 우선순위: {{ priority }}\n\n"
                    "답변 초안:\n"
                    "안녕하세요. 문의 주신 내용을 확인했습니다. "
                    "우선순위는 {{ priority }}로 접수되었고, 담당자가 순차적으로 확인하겠습니다."
                ),
                "variables": [
                    {
                        "name": "customer_message",
                        "value_selector": ["start-customer", "customer_message"],
                    },
                    {
                        "name": "priority",
                        "value_selector": ["start-customer", "priority"],
                    },
                ],
            },
        ),
        _node(
            "answer-reply",
            "answerNode",
            840,
            120,
            {
                **_base_data("최종 응답", "템플릿 결과를 최종 출력합니다.", 3),
                "outputs": [
                    {
                        "variable": "reply",
                        "label": "답변 초안",
                        "value_selector": ["template-reply", "text"],
                    }
                ],
            },
        ),
    ]
    return {
        "nodes": nodes,
        "edges": [
            _edge("edge-start-template", "start-customer", "template-reply"),
            _edge("edge-template-answer", "template-reply", "answer-reply"),
        ],
        "viewport": {"x": 120, "y": 80, "zoom": 0.9},
    }


def _llm_intent_graph() -> dict:
    nodes = [
        _node(
            "start-inquiry",
            "startNode",
            0,
            120,
            _start_data(
                "문의 입력",
                "LLM 의도 분류에 사용할 고객 문의를 입력받습니다.",
                1,
                [
                    _input_variable(
                        "customer_message",
                        "customer_message",
                        "고객 문의",
                        "paragraph",
                        maxLength=1200,
                        max_length=1200,
                    )
                ],
            ),
        ),
        _node(
            "llm-intent",
            "llmNode",
            420,
            120,
            {
                **_base_data(
                    "문의 의도 분석",
                    "고객 문의의 의도와 감정을 분류합니다.",
                    2,
                    ["model_id", "user_prompt"],
                ),
                "provider": "openai",
                "model_id": "gpt-4.1-mini",
                "fallback_model_id": "gpt-4o-mini",
                "system_prompt": "고객센터 문의를 분류하는 상담 운영 도우미입니다.",
                "user_prompt": (
                    "다음 고객 문의를 읽고 의도, 감정, 긴급도를 JSON으로 답하세요.\n"
                    "고객 문의: {{ customer_message }}"
                ),
                "assistant_prompt": "",
                "referenced_variables": [
                    {
                        "name": "customer_message",
                        "value_selector": ["start-inquiry", "customer_message"],
                    }
                ],
                "context_variable": "",
                "parameters": {"temperature": 0.2, "max_tokens": 500},
                "knowledgeBases": [],
            },
        ),
        _node(
            "answer-intent",
            "answerNode",
            840,
            120,
            {
                **_base_data("분석 결과", "LLM 분석 결과를 최종 출력합니다.", 3),
                "outputs": [
                    {
                        "variable": "analysis",
                        "label": "의도 분석",
                        "value_selector": ["llm-intent", "text"],
                    }
                ],
            },
        ),
    ]
    return {
        "nodes": nodes,
        "edges": [
            _edge("edge-start-llm", "start-inquiry", "llm-intent"),
            _edge("edge-llm-answer", "llm-intent", "answer-intent"),
        ],
        "viewport": {"x": 120, "y": 80, "zoom": 0.9},
    }


def _priority_branch_graph() -> dict:
    nodes = [
        _node(
            "start-priority",
            "startNode",
            0,
            160,
            _start_data(
                "문의 입력",
                "고객 문의와 우선순위를 입력받아 분기합니다.",
                1,
                [
                    _input_variable(
                        "customer_message",
                        "customer_message",
                        "고객 문의",
                        "paragraph",
                        maxLength=1000,
                        max_length=1000,
                    ),
                    _input_variable(
                        "priority",
                        "priority",
                        "우선순위",
                        "select",
                        options=[
                            {"label": "일반", "value": "normal"},
                            {"label": "긴급", "value": "urgent"},
                        ],
                    ),
                ],
            ),
        ),
        _node(
            "condition-priority",
            "conditionNode",
            420,
            160,
            {
                **_base_data(
                    "긴급 여부 분기",
                    "우선순위가 urgent면 긴급 응답으로 분기합니다.",
                    2,
                    ["cases"],
                ),
                "cases": [
                    {
                        "id": "urgent",
                        "case_name": "긴급",
                        "logical_operator": "and",
                        "conditions": [
                            {
                                "id": "cond-priority-urgent",
                                "variable_selector": ["start-priority", "priority"],
                                "operator": "equals",
                                "value": "urgent",
                            }
                        ],
                    }
                ],
            },
        ),
        _node(
            "template-urgent",
            "templateNode",
            840,
            40,
            {
                **_base_data("긴급 응답", "긴급 문의용 답변을 생성합니다.", 3),
                "template": (
                    "[긴급 접수]\n"
                    "문의 내용: {{ customer_message }}\n"
                    "담당자에게 즉시 전달하고 우선 처리하겠습니다."
                ),
                "variables": [
                    {
                        "name": "customer_message",
                        "value_selector": ["start-priority", "customer_message"],
                    }
                ],
            },
        ),
        _node(
            "template-default",
            "templateNode",
            840,
            300,
            {
                **_base_data("일반 응답", "일반 문의용 답변을 생성합니다.", 4),
                "template": (
                    "[일반 접수]\n"
                    "문의 내용: {{ customer_message }}\n"
                    "접수 순서에 따라 확인 후 답변드리겠습니다."
                ),
                "variables": [
                    {
                        "name": "customer_message",
                        "value_selector": ["start-priority", "customer_message"],
                    }
                ],
            },
        ),
        _node(
            "answer-urgent",
            "answerNode",
            1260,
            40,
            {
                **_base_data("긴급 최종 응답", "긴급 분기 출력을 반환합니다.", 5),
                "outputs": [
                    {
                        "variable": "reply",
                        "label": "답변",
                        "value_selector": ["template-urgent", "text"],
                    }
                ],
            },
        ),
        _node(
            "answer-default",
            "answerNode",
            1260,
            300,
            {
                **_base_data("일반 최종 응답", "기본 분기 출력을 반환합니다.", 6),
                "outputs": [
                    {
                        "variable": "reply",
                        "label": "답변",
                        "value_selector": ["template-default", "text"],
                    }
                ],
            },
        ),
    ]
    return {
        "nodes": nodes,
        "edges": [
            _edge("edge-start-condition", "start-priority", "condition-priority"),
            _edge(
                "edge-condition-urgent",
                "condition-priority",
                "template-urgent",
                source_handle="urgent",
            ),
            _edge(
                "edge-condition-default",
                "condition-priority",
                "template-default",
                source_handle="default",
            ),
            _edge("edge-urgent-answer", "template-urgent", "answer-urgent"),
            _edge("edge-default-answer", "template-default", "answer-default"),
        ],
        "viewport": {"x": 80, "y": 40, "zoom": 0.75},
    }


def _extract_input_schema(graph: dict) -> dict | None:
    for node in graph.get("nodes", []):
        if node.get("type") != "startNode":
            continue
        variables = node.get("data", {}).get("variables", [])
        return {
            "variables": [
                {
                    "name": variable["name"],
                    "type": variable.get("type", "text"),
                    "label": variable.get("label", variable["name"]),
                }
                for variable in variables
                if variable.get("name")
            ]
        }
    return None


def _extract_output_schema(graph: dict) -> dict | None:
    outputs = []
    for node in graph.get("nodes", []):
        if node.get("type") != "answerNode":
            continue
        for output in node.get("data", {}).get("outputs", []):
            if output.get("variable"):
                outputs.append(
                    {
                        "variable": output["variable"],
                        "label": output.get("label", output["variable"]),
                    }
                )
    return {"outputs": outputs} if outputs else None


def _upsert_dev_app_workflow(
    db: Session,
    key: str,
    name: str,
    description: str,
    icon: str,
    graph: dict,
) -> Workflow:
    app_id = DEV_WORKFLOW_APP_IDS[key]
    workflow_id = DEV_WORKFLOW_IDS[key]
    deployment_id = DEV_DEPLOYMENT_IDS[key]

    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        app = App(
            id=app_id,
            tenant_id=PLACEHOLDER_USER_ID,
            name=name,
            description=description,
            icon={
                "type": "emoji",
                "content": icon,
                "background_color": "#EFF6FF",
            },
            url_slug=f"dev-{key}-workflow",
            auth_secret=f"sk-dev-{key}",
            is_market=False,
            created_by=PLACEHOLDER_USER_ID,
        )
        db.add(app)
        db.flush()
    else:
        app.name = name
        app.description = description
        app.icon = {
            "type": "emoji",
            "content": icon,
            "background_color": "#EFF6FF",
        }

    workflow = db.query(Workflow).filter(Workflow.id == workflow_id).first()
    if not workflow:
        workflow = Workflow(
            id=workflow_id,
            tenant_id=PLACEHOLDER_USER_ID,
            app_id=app.id,
            created_by=PLACEHOLDER_USER_ID,
        )
        db.add(workflow)
        db.flush()

    workflow.app_id = app.id
    workflow.tenant_id = PLACEHOLDER_USER_ID
    workflow.created_by = PLACEHOLDER_USER_ID
    workflow.updated_by = PLACEHOLDER_USER_ID
    workflow.graph = graph
    workflow.features = {}
    workflow.env_variables = []
    workflow.runtime_variables = []
    app.workflow_id = workflow.id

    deployment = db.query(WorkflowDeployment).filter(
        WorkflowDeployment.id == deployment_id
    ).first()
    if not deployment:
        deployment = WorkflowDeployment(
            id=deployment_id,
            app_id=app.id,
            version=1,
            type=DeploymentType.API,
            graph_snapshot=graph,
            created_by=PLACEHOLDER_USER_ID,
            is_active=True,
        )
        db.add(deployment)

    deployment.app_id = app.id
    deployment.version = 1
    deployment.type = DeploymentType.API
    deployment.graph_snapshot = graph
    deployment.config = {"dev_seed": True}
    deployment.input_schema = _extract_input_schema(graph)
    deployment.output_schema = _extract_output_schema(graph)
    deployment.description = "Dev seed deployment"
    deployment.created_by = PLACEHOLDER_USER_ID
    deployment.is_active = True
    app.active_deployment_id = deployment.id

    return workflow


def _seed_template_run_logs(db: Session, workflow: Workflow) -> None:
    db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow.id).delete(
        synchronize_session=False
    )

    now = datetime.now(timezone.utc)
    run_specs = [
        ("normal", RunStatus.SUCCESS, "normal", 0.0012, 0, None),
        ("urgent", RunStatus.SUCCESS, "urgent", 0.0015, 0, None),
        (
            "missing",
            RunStatus.FAILED,
            "",
            0,
            0,
            "변수 'priority' 값이 비어 있습니다.",
        ),
    ]

    for index, (suffix, status, priority, cost, tokens, error) in enumerate(run_specs):
        started_at = now - timedelta(days=index + 1, minutes=index * 11)
        run = WorkflowRun(
            workflow_id=workflow.id,
            user_id=PLACEHOLDER_USER_ID,
            deployment_id=DEV_DEPLOYMENT_IDS["template"],
            workflow_version=1,
            status=status,
            trigger_mode=RunTriggerMode.MANUAL,
            inputs={
                "customer_message": f"배송 상태를 확인하고 싶습니다. ({suffix})",
                "priority": priority,
            },
            outputs=None
            if status == RunStatus.FAILED
            else {
                "reply": f"문의 요약:\n- 고객 문의: 배송 상태를 확인하고 싶습니다. ({suffix})\n- 우선순위: {priority}"
            },
            error_message=error,
            started_at=started_at,
            finished_at=started_at + timedelta(seconds=1.2 + index),
            duration=1.2 + index,
            meta_info={"seed": "dev_workflows"},
            total_tokens=tokens,
            total_cost=Decimal(str(cost)),
        )
        db.add(run)
        db.flush()

        node_status = (
            NodeRunStatus.FAILED
            if status == RunStatus.FAILED
            else NodeRunStatus.SUCCESS
        )
        db.add_all(
            [
                WorkflowNodeRun(
                    workflow_run_id=run.id,
                    node_id="start-customer",
                    node_type="startNode",
                    status=NodeRunStatus.SUCCESS,
                    inputs=run.inputs,
                    process_data={},
                    outputs=run.inputs,
                    started_at=started_at,
                    finished_at=started_at + timedelta(milliseconds=80),
                ),
                WorkflowNodeRun(
                    workflow_run_id=run.id,
                    node_id="template-reply",
                    node_type="templateNode",
                    status=node_status,
                    inputs={"start-customer": run.inputs},
                    process_data={},
                    outputs=run.outputs,
                    error_message=error,
                    started_at=started_at + timedelta(milliseconds=100),
                    finished_at=started_at + timedelta(milliseconds=300),
                ),
            ]
        )


def seed_dev_workflow_examples(db: Session) -> None:
    """
    Seed local/dev workflow examples for real backend testing.

    - Does not create credentials or API keys.
    - Idempotently updates the same fixed apps/workflows/deployments.
    - Adds lightweight run logs for monitoring UI.
    """

    seed_placeholder_user(db)
    seed_default_llm_providers(db)
    seed_default_llm_models(db)
    seed_demo_family_care_knowledge_base(db)

    template_workflow = _upsert_dev_app_workflow(
        db,
        key="template",
        name="[DEV] 템플릿 응답 워크플로우",
        description="credentials 없이 실행 가능한 Start → Template → Answer 예제",
        icon="🧩",
        graph=_template_quick_reply_graph(),
    )
    _upsert_dev_app_workflow(
        db,
        key="llm",
        name="[DEV] LLM 문의 의도 분석",
        description="사용자가 OpenAI credentials를 채운 뒤 실제 LLM 호출을 확인하는 예제",
        icon="🤖",
        graph=_llm_intent_graph(),
    )
    _upsert_dev_app_workflow(
        db,
        key="branch",
        name="[DEV] 우선순위 분기 워크플로우",
        description="Start → Condition → Template → Answer 분기 실행 예제",
        icon="🔀",
        graph=_priority_branch_graph(),
    )
    _seed_template_run_logs(db, template_workflow)

    db.commit()
    logger.info("✅ Dev workflow examples seeded.")
