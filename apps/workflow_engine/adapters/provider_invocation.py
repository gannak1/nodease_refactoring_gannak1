"""Opaque provider client lease used by Workflow execution adapters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from apps.shared.services.llm_client.base import (
    ProviderFailurePhase,
    ProviderInvocationError,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionAttribution,
    ProviderExecutionConfigurationError,
    ProviderInvocationOutcomeUnknownError,
)


class ProviderClientInvocationLease:
    """Keep the SDK client private while exposing one bounded invocation."""

    def __init__(
        self,
        *,
        client: Any,
        messages: tuple[Mapping[str, Any], ...],
        parameters: Mapping[str, Any],
        attribution: ProviderExecutionAttribution | None,
    ) -> None:
        self._client = client
        self._messages = deepcopy(tuple(dict(message) for message in messages))
        self._parameters = deepcopy(dict(parameters))
        self._attribution = attribution
        self._invoked = False

    @property
    def attribution(self) -> ProviderExecutionAttribution | None:
        return self._attribution

    def invoke(self) -> Mapping[str, Any]:
        if self._invoked:
            raise ProviderExecutionConfigurationError()
        # Consume before I/O so an unknown provider outcome cannot be replayed.
        self._invoked = True
        try:
            return self._client.invoke_sync(
                messages=deepcopy(list(self._messages)),
                **deepcopy(self._parameters),
            )
        except ProviderInvocationError as exc:
            if exc.failure_phase is ProviderFailurePhase.OUTCOME_UNKNOWN:
                raise ProviderInvocationOutcomeUnknownError() from exc
            raise


__all__ = ["ProviderClientInvocationLease"]
