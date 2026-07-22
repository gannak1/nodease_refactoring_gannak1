"""Opaque provider client lease used by Workflow execution adapters."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionAttribution,
    ProviderExecutionConfigurationError,
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

    def apply_json_schema_response_format(
        self,
        *,
        name: str,
        schema: Mapping[str, Any],
    ) -> bool:
        """지원 provider에만 node JSON schema를 엄격한 응답 형식으로 전달한다."""
        builder = getattr(self._client, "build_json_schema_response_format", None)
        if not callable(builder):
            return False
        try:
            response_format = builder(name=name, schema=dict(schema))
        except Exception:
            return False
        if not isinstance(response_format, dict):
            return False
        self._parameters["response_format"] = response_format
        return True

    def invoke(self) -> Mapping[str, Any]:
        if self._invoked:
            raise ProviderExecutionConfigurationError()
        # Consume before I/O so an unknown provider outcome cannot be replayed.
        self._invoked = True
        return self._client.invoke_sync(
            messages=deepcopy(list(self._messages)),
            **deepcopy(self._parameters),
        )


__all__ = ["ProviderClientInvocationLease"]
