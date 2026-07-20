"""Application contract for recording one completed provider invocation."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionAttribution,
)


@dataclass(frozen=True, slots=True)
class ProviderUsageRecord:
    attribution: ProviderExecutionAttribution
    usage: Mapping[str, Any]
    workflow_id: uuid.UUID | None
    workflow_run_id: uuid.UUID | None
    node_id: str
    cost_optimizer_candidate_id: uuid.UUID | None = None


class ProviderUsageRecorder(Protocol):
    def record(self, request: ProviderUsageRecord) -> float: ...


__all__ = ["ProviderUsageRecord", "ProviderUsageRecorder"]
