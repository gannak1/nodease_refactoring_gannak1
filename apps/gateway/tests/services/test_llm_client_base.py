import asyncio
import pathlib
import sys
from typing import Any, Dict, List

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from apps.shared.services.llm_client.base import BaseLLMClient  # noqa: E402


class DummyClient(BaseLLMClient):
    async def invoke(self, messages: List[Dict[str, Any]], **kwargs) -> Dict[str, Any]:
        return {"messages": messages, "kwargs": kwargs}

    async def embed(self, text: str) -> List[float]:
        return [float(len(text))]

    def get_num_tokens(self, messages: List[Dict[str, Any]]) -> int:
        return len(messages)


@pytest.mark.asyncio
async def test_invoke_sync_runs_inside_active_event_loop():
    client = DummyClient(model_id="dummy")
    messages = [{"role": "user", "content": "hello"}]

    result = client.invoke_sync(messages, temperature=0.2)

    assert result == {"messages": messages, "kwargs": {"temperature": 0.2}}


@pytest.mark.asyncio
async def test_embed_sync_runs_inside_active_event_loop():
    client = DummyClient(model_id="dummy")

    assert client.embed_sync("hello") == [5.0]


def test_embed_sync_bounds_async_provider_call():
    cancellation_observed = False

    class SlowClient(DummyClient):
        async def embed(self, text: str) -> List[float]:
            nonlocal cancellation_observed
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancellation_observed = True
                raise

    with pytest.raises(TimeoutError):
        SlowClient(model_id="slow").embed_sync(
            "hello",
            timeout_seconds=0.001,
        )

    assert cancellation_observed is True
