from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.auth.permissions import ensure_workflow_permission
from apps.gateway.services.organization_context import ensure_user_default_organization
from apps.gateway.services.workflow_builder_agent import (
    build_workflow_agent_response,
    is_family_care_leave_demo_request,
)
from apps.shared.db.seed import ensure_agent_family_care_knowledge_base
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db

router = APIRouter()


class WorkflowBuilderGraph(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    viewport: dict[str, Any] | None = None


class WorkflowBuilderRequest(BaseModel):
    prompt: str
    workflowId: str | None = None
    graph: WorkflowBuilderGraph | None = None
    selectedNodeId: str | None = None


class WorkflowBuilderResponse(BaseModel):
    status: str
    mode: str
    message: str
    graph_preview: dict[str, Any] | None
    selected_nodes: list[dict[str, str]]
    missing_fields: list[str]
    questions: list[str]
    validation_errors: list[str]
    validation_warnings: list[str]
    warnings: list[str]


@router.post("", response_model=WorkflowBuilderResponse)
async def build_workflow(
    request: WorkflowBuilderRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    prompt = request.prompt.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="Prompt is required.")

    workflow = None
    if request.workflowId and request.workflowId != "default":
        workflow = ensure_workflow_permission(
            db,
            current_user,
            request.workflowId,
            "write",
        )

    demo_knowledge_base = None
    if is_family_care_leave_demo_request(prompt):
        organization_id = (
            workflow.organization_id
            if workflow and workflow.organization_id
            else ensure_user_default_organization(db, current_user)
        )
        kb = ensure_agent_family_care_knowledge_base(
            db,
            current_user.id,
            organization_id,
        )
        demo_knowledge_base = {"id": str(kb.id), "name": kb.name}

    return await build_workflow_agent_response(
        prompt,
        request.graph.model_dump() if request.graph else None,
        request.selectedNodeId,
        demo_knowledge_base=demo_knowledge_base,
    )
