"""Legacy user-scoped query embedding behind an application port."""

from __future__ import annotations

import uuid
from threading import Lock

from apps.shared.services.retrieval_embedding_model_projection import (
    EmbeddingModelBinding,
)
from apps.workflow_engine.application.query_embedding_execution import (
    QueryEmbeddingConfigurationError,
    QueryEmbeddingInvocationLease,
    QueryEmbeddingPlan,
    QueryEmbeddingPreflight,
    QueryEmbeddingProviderResult,
    QueryEmbeddingRequest,
)
from apps.workflow_engine.services.llm_service import LLMService


class _LegacyQueryEmbeddingLease(QueryEmbeddingInvocationLease):
    def __init__(self, *, client, query: str) -> None:
        self._client = client
        self._query = query
        self._lock = Lock()
        self._consumed = False

    @property
    def attribution(self):
        return None

    def invoke(self) -> QueryEmbeddingProviderResult:
        with self._lock:
            if self._consumed:
                raise QueryEmbeddingConfigurationError()
            self._consumed = True
        try:
            vector = tuple(float(value) for value in self._client.embed_sync(self._query))
        except Exception:
            raise QueryEmbeddingConfigurationError() from None
        return QueryEmbeddingProviderResult(
            vector=vector,
            input_tokens=len(self._query.encode("utf-8")),
        )


class LegacyQueryEmbeddingAdapter:
    def preflight(self, request: QueryEmbeddingPreflight) -> QueryEmbeddingPlan:
        if (
            request.execution_context.get(
                "provider_execution_capability_required",
                False,
            )
            is not False
            or not isinstance(request.organization_id, uuid.UUID)
            or not isinstance(request.legacy_credential_user_id, uuid.UUID)
        ):
            raise QueryEmbeddingConfigurationError()
        return QueryEmbeddingPlan(
            capability_required=False,
            state=(request.organization_id, request.legacy_credential_user_id),
        )

    def resolve(
        self,
        request: QueryEmbeddingRequest,
    ) -> QueryEmbeddingInvocationLease:
        state = request.plan.state
        if (
            not isinstance(state, tuple)
            or len(state) != 2
            or not isinstance(state[0], uuid.UUID)
            or not isinstance(state[1], uuid.UUID)
            or request.shared_session is None
            or not isinstance(request.query, str)
            or not request.query
        ):
            raise QueryEmbeddingConfigurationError()
        binding = request.model_binding
        try:
            shared_binding = EmbeddingModelBinding(
                model_id=binding.model_id,
                provider_id=binding.provider_id,
                model_identifier=binding.model_identifier,
            )
            client = LLMService.get_client_for_model_binding(
                request.shared_session,
                state[1],
                shared_binding,
                organization_id=state[0],
            )
        except Exception:
            raise QueryEmbeddingConfigurationError() from None
        return _LegacyQueryEmbeddingLease(client=client, query=request.query)


__all__ = ["LegacyQueryEmbeddingAdapter"]
