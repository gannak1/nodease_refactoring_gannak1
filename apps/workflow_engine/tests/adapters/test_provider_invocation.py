from __future__ import annotations

import pytest

from apps.workflow_engine.adapters.provider_invocation import (
    ProviderClientInvocationLease,
)
from apps.workflow_engine.application.provider_execution import (
    ProviderExecutionConfigurationError,
)


class _Client:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    def invoke_sync(self, *, messages, **parameters):
        self.calls.append({"messages": messages, "parameters": parameters})
        return {"choices": [{"message": {"content": "ok"}}]}


def test_invocation_lease_seals_request_and_allows_only_one_attempt():
    client = _Client()
    messages = [{"role": "user", "content": [{"text": "before"}]}]
    parameters = {"tools": [{"function": {"name": "safe_tool"}}]}
    lease = ProviderClientInvocationLease(
        client=client,
        messages=tuple(messages),
        parameters=parameters,
        attribution=None,
    )

    messages[0]["content"][0]["text"] = "after"
    parameters["tools"][0]["function"]["name"] = "changed_tool"

    lease.invoke()

    assert client.calls == [
        {
            "messages": [{"role": "user", "content": [{"text": "before"}]}],
            "parameters": {"tools": [{"function": {"name": "safe_tool"}}]},
        }
    ]
    with pytest.raises(ProviderExecutionConfigurationError):
        lease.invoke()
    assert len(client.calls) == 1
