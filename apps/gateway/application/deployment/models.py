from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

PreflightStatus = Literal["passed", "warning", "blocked"]
PreflightAudience = Literal[
    "anonymous_public",
    "authenticated_user",
    "workflow_node_inherited",
]


@dataclass(frozen=True)
class KnowledgeBaseSnapshot:
    id: uuid.UUID
    source_managed: bool


@dataclass(frozen=True)
class WorkflowNodeTargetSnapshot:
    app_id: uuid.UUID
    active_graph_snapshot: dict | None


@dataclass(frozen=True)
class PreflightRequiredAction:
    action: str
    label: str


@dataclass(frozen=True)
class PreflightNodeResult:
    node_id: str | None
    node_type: str
    status: PreflightStatus
    reason_codes: tuple[str, ...]
    knowledge_base_count_bucket: str


@dataclass(frozen=True)
class PreflightSummary:
    blocked_reason: str | None
    affected_node_count: int
    affected_kb_count_bucket: str


@dataclass(frozen=True)
class DeploymentPreflightResult:
    status: PreflightStatus
    audience: PreflightAudience
    safe_summary: PreflightSummary
    required_actions: tuple[PreflightRequiredAction, ...]
    warnings: tuple[str, ...]
    nodes: tuple[PreflightNodeResult, ...]
