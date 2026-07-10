from uuid import UUID

from fastapi import APIRouter, Depends, Header, Request
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.agent_builder_intent_service import (
    LLMAgentBuilderIntentExtractor,
)
from apps.gateway.services.agent_builder_service import AgentBuilderService
from apps.gateway.services.llm_service import LLMService
from apps.gateway.services.organization_context import resolve_active_organization_id
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.agent_builder import (
    AgentBuilderApplyRequest,
    AgentBuilderApplyResponse,
    AgentBuilderMessageRequest,
    AgentBuilderMessageResponse,
    AgentBuilderSessionCreateRequest,
    AgentBuilderSessionResponse,
)
from apps.shared.schemas.llm import LLMIntentModelProviderResponse


router = APIRouter()


def _service(
    *,
    db: Session,
    request: Request,
    raw_organization_id: str | None,
    current_user: User,
    intent_credential_id: UUID | None = None,
    intent_model_id: UUID | None = None,
) -> AgentBuilderService:
    organization_id = resolve_active_organization_id(
        db,
        request,
        raw_organization_id,
        current_user.id,
    )
    return AgentBuilderService(
        db,
        user=current_user,
        organization_id=organization_id,
        intent_extractor=LLMAgentBuilderIntentExtractor(
            db=db,
            user_id=current_user.id,
            organization_id=organization_id,
            credential_id=intent_credential_id,
            model_id=intent_model_id,
        ),
    )


@router.get(
    "/model-options",
    response_model=list[LLMIntentModelProviderResponse],
)
def get_agent_builder_model_options(
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    organization_id = resolve_active_organization_id(
        db,
        request,
        x_organization_id,
        current_user.id,
    )
    return LLMService.get_agent_builder_model_option_groups(
        db,
        current_user.id,
        organization_id,
    )


@router.post("/sessions", response_model=AgentBuilderSessionResponse)
def create_or_restore_session(
    payload: AgentBuilderSessionCreateRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _service(
        db=db,
        request=request,
        raw_organization_id=x_organization_id,
        current_user=current_user,
    ).create_or_restore_session(payload)


@router.get("/sessions/{session_id}", response_model=AgentBuilderSessionResponse)
def get_session(
    session_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _service(
        db=db,
        request=request,
        raw_organization_id=x_organization_id,
        current_user=current_user,
    ).get_session(session_id)


@router.post(
    "/sessions/{session_id}/messages",
    response_model=AgentBuilderMessageResponse,
)
def submit_message(
    session_id: UUID,
    payload: AgentBuilderMessageRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model_selection = payload.intent_model_selection
    return _service(
        db=db,
        request=request,
        raw_organization_id=x_organization_id,
        current_user=current_user,
        intent_credential_id=(
            model_selection.credential_id if model_selection else None
        ),
        intent_model_id=model_selection.model_id if model_selection else None,
    ).submit_message(session_id, payload)


@router.post("/requests/{request_id}/cancel", response_model=AgentBuilderMessageResponse)
def cancel_request(
    request_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _service(
        db=db,
        request=request,
        raw_organization_id=x_organization_id,
        current_user=current_user,
    ).cancel_request(request_id)


@router.post("/drafts/{draft_id}/preview-opened")
def record_preview_opened(
    draft_id: UUID,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _service(
        db=db,
        request=request,
        raw_organization_id=x_organization_id,
        current_user=current_user,
    ).record_preview_opened(draft_id)
    return {"ok": True}


@router.post("/drafts/{draft_id}/apply", response_model=AgentBuilderApplyResponse)
def apply_draft(
    draft_id: UUID,
    payload: AgentBuilderApplyRequest,
    request: Request,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return _service(
        db=db,
        request=request,
        raw_organization_id=x_organization_id,
        current_user=current_user,
    ).apply_draft(draft_id, payload)
