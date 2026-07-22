"""Composition boundary for Workflow provider execution dependencies."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session

from apps.workflow_engine.adapters.provider_execution import (
    ProviderExecutionRuntimeRouter,
)
from apps.workflow_engine.adapters.provider_execution_capability import (
    CapabilityProviderExecutionAdapter,
)
from apps.workflow_engine.adapters.provider_execution_legacy import (
    LegacyProviderExecutionAdapter,
)
from apps.workflow_engine.adapters.provider_usage import (
    PostgresProviderUsageRecorder,
)
from apps.workflow_engine.adapters.query_embedding import (
    QueryEmbeddingExecutionRuntimeRouter,
)
from apps.workflow_engine.adapters.query_embedding_capability import (
    CapabilityQueryEmbeddingAdapter,
)
from apps.workflow_engine.adapters.query_embedding_legacy import (
    LegacyQueryEmbeddingAdapter,
)
from apps.workflow_engine.application.query_embedding_execution import (
    QueryEmbeddingEgressRuntime,
    QueryEmbeddingOperationLedger,
)


def build_provider_execution_runtime(
    *,
    session_factory: Callable[[], Session] | None = None,
) -> ProviderExecutionRuntimeRouter:
    if session_factory is None:
        from apps.shared.db.session import SessionLocal

        session_factory = SessionLocal
    return ProviderExecutionRuntimeRouter(
        legacy_strategy=LegacyProviderExecutionAdapter(
            session_factory=session_factory,
        ),
        capability_strategy=CapabilityProviderExecutionAdapter(
            session_factory=session_factory,
        ),
    )


def build_provider_usage_recorder(
    *,
    session_factory: Callable[[], Session] | None = None,
) -> PostgresProviderUsageRecorder:
    if session_factory is None:
        from apps.shared.db.session import SessionLocal

        session_factory = SessionLocal
    return PostgresProviderUsageRecorder(session_factory=session_factory)


def build_query_embedding_runtime(
    *,
    session_factory: Callable[[], Session] | None = None,
    operation_ledger: QueryEmbeddingOperationLedger | None = None,
    egress_runtime: QueryEmbeddingEgressRuntime | None = None,
) -> QueryEmbeddingExecutionRuntimeRouter:
    if session_factory is None:
        from apps.shared.db.session import SessionLocal

        session_factory = SessionLocal
    return QueryEmbeddingExecutionRuntimeRouter(
        legacy_strategy=LegacyQueryEmbeddingAdapter(),
        capability_strategy=CapabilityQueryEmbeddingAdapter(
            session_factory=session_factory,
            operation_ledger=operation_ledger,
            egress_runtime=egress_runtime,
        ),
    )


__all__ = [
    "build_provider_execution_runtime",
    "build_provider_usage_recorder",
    "build_query_embedding_runtime",
]
