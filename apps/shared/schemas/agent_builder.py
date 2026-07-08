from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


AgentBuilderRequestStatus = Literal[
    "draft_ready",
    "clarification_required",
    "validation_failed",
    "unsupported",
    "configuration_required",
    "failed",
    "canceled",
]
AgentBuilderDraftMode = Literal["new_workflow", "modify_workflow", "replace_workflow"]
AgentBuilderApplyAction = Literal["apply_and_save", "cancel"]
AgentBuilderApplyOutcome = Literal["saved", "blocked", "canceled", "failed"]
AgentBuilderPendingSlotType = Literal["knowledge_base", "target", "capability", "other"]


class AgentBuilderSessionCreateRequest(BaseModel):
    workflow_id: UUID | None = None
    app_id: UUID | None = None


class AgentBuilderSessionResponse(BaseModel):
    session_id: UUID
    workflow_id: UUID | None = None
    app_id: UUID | None = None
    status: str
    messages: list[dict[str, Any]] = Field(default_factory=list)
    pending_request: dict[str, Any] | None = None
    draft_preview: dict[str, Any] | None = None


class AgentBuilderKnowledgeCandidateSelection(BaseModel):
    candidate_id: str = Field(min_length=1, max_length=255)
    resolution_id: str | None = Field(default=None, max_length=255)
    requirement_id: str | None = Field(default=None, max_length=255)


class AgentBuilderMessageRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    message: str = Field(min_length=1, max_length=4000)
    workflow_id: UUID | None = None
    app_id: UUID | None = None
    selected_node_id: str | None = Field(default=None, max_length=255)
    selected_edge_id: str | None = Field(default=None, max_length=255)
    conversation_context_id: str | None = Field(default=None, max_length=255)
    selected_knowledge_candidate: AgentBuilderKnowledgeCandidateSelection | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_raw_client_graph_snapshot(cls, data: Any):
        raw_graph_keys = {
            "client_graph_snapshot",
            "clientGraphSnapshot",
            "graph",
            "nodes",
            "edges",
            "preview_graph",
            "previewGraph",
            "workflow_graph",
            "workflowGraph",
            "raw_graph",
            "rawGraph",
        }
        if isinstance(data, dict) and raw_graph_keys.intersection(data):
            raise ValueError("raw workflow graph payload is not accepted")
        return data

class AgentBuilderPlannedStep(BaseModel):
    step_id: str
    capability: str
    purpose: str
    depends_on: list[str] = Field(default_factory=list)


class AgentBuilderKnowledgeRequirement(BaseModel):
    requirement_id: str
    query_topics: list[str] = Field(default_factory=list)
    expected_evidence_type: str = "policy_or_reference"
    required: bool = True
    target_step_ref: str | None = None


class AgentBuilderPendingResolution(BaseModel):
    resolution_id: str
    slot_type: AgentBuilderPendingSlotType
    slot_key: str
    blocking: bool = True
    target_step_ref: str | None = None


class AgentBuilderStructuredRequest(BaseModel):
    request_type: Literal[
        "new_workflow",
        "modify_workflow",
        "clarification",
        "unsupported",
        "validation_failure",
    ]
    draft_mode: AgentBuilderDraftMode
    intent_summary: str
    planned_steps: list[AgentBuilderPlannedStep] = Field(default_factory=list)
    knowledge_requirements: list[AgentBuilderKnowledgeRequirement] = Field(
        default_factory=list
    )
    required_capabilities: list[str] = Field(default_factory=list)
    pending_resolution: list[AgentBuilderPendingResolution] = Field(
        default_factory=list
    )
    missing_information: list[str] = Field(default_factory=list)
    unsupported_requests: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class AgentBuilderValidationIssue(BaseModel):
    code: str
    message: str
    path: str | None = None


class AgentBuilderValidationResult(BaseModel):
    valid: bool
    issues: list[AgentBuilderValidationIssue] = Field(default_factory=list)


class AgentBuilderDraftPreview(BaseModel):
    draft_id: UUID
    preview_graph: dict[str, Any]
    base_graph_hash: str | None = None
    base_workflow_updated_at: datetime | None = None
    draft_mode: AgentBuilderDraftMode
    node_detail_previews: list[dict[str, Any]] = Field(default_factory=list)
    validation_result: AgentBuilderValidationResult
    safety_notices: list[str] = Field(default_factory=list)


class AgentBuilderMessageResponse(BaseModel):
    request_id: UUID
    status: AgentBuilderRequestStatus
    structured_request: AgentBuilderStructuredRequest | None = None
    clarification_questions: list[str] = Field(default_factory=list)
    clarification_options: list[dict[str, Any]] = Field(default_factory=list)
    draft_preview: AgentBuilderDraftPreview | None = None
    validation_result: AgentBuilderValidationResult | None = None
    preview_prompt: str | None = None
    warnings: list[str] = Field(default_factory=list)


class AgentBuilderApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: AgentBuilderApplyAction
    client_preview_graph_hash: str | None = None
    client_latest_graph_hash: str | None = None
    client_workflow_version: str | None = None
    client_workflow_updated_at: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_raw_client_graph_snapshot(cls, data: Any):
        raw_graph_keys = {
            "client_graph_snapshot",
            "clientGraphSnapshot",
            "graph",
            "nodes",
            "edges",
            "preview_graph",
            "previewGraph",
            "workflow_graph",
            "workflowGraph",
            "raw_graph",
            "rawGraph",
        }
        if isinstance(data, dict) and raw_graph_keys.intersection(data):
            raise ValueError("raw workflow graph payload is not accepted")
        return data


class AgentBuilderApplyResponse(BaseModel):
    apply_id: UUID
    outcome: AgentBuilderApplyOutcome
    saved_workflow_id: UUID | None = None
    latest_graph_hash: str | None = None
    latest_workflow_version: str | None = None
    latest_workflow_updated_at: datetime | None = None
    block_reason: str | None = None
    failure_reason: str | None = None
    stale_state: str = "not_stale"
    permission_recheck_outcome: str = "not_checked"
    validation_state: str = "not_checked"
    audit_recorded: bool = False
    layout_optimization_applied: bool = False
    notices: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def saved_requires_audit_recorded(self):
        if self.outcome == "saved" and not self.audit_recorded:
            raise ValueError("outcome=saved requires audit_recorded=true")
        return self
