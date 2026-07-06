"""
OpenAIClient 단위 테스트.
- 성공 시 HTTP 응답을 그대로 반환하는지
- 4xx/5xx일 때 ValueError를 발생시키는지
- 토큰 카운트가 최소 1 이상으로 계산되는지 검증
"""

import pathlib
import sys

import pytest

# pytest 실행 시 모듈 검색 경로에 프로젝트 루트를 추가
ROOT = pathlib.Path(__file__).resolve().parents[4]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from apps.shared.services.llm_client import OpenAIClient


@pytest.mark.asyncio
async def test_openai_invoke_success(monkeypatch):
    """invoke 성공 시 응답 반환 확인"""
    messages = [{"role": "user", "content": "hi"}]
    dummy_response = {"id": "abc", "choices": []}

    class MockResponse:
        status_code = 200
        text = ""
        
        def json(self):
            return dummy_response

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            pass
        
        async def post(self, url, **kwargs):
            return MockResponse()

    monkeypatch.setattr(
        "apps.shared.services.llm_client.openai_client.httpx.AsyncClient",
        lambda **kw: MockAsyncClient()
    )

    client = OpenAIClient(
        model_id="gpt-4o",
        credentials={"apiKey": "sk-test", "baseUrl": "https://api.openai.com/v1"},
    )
    resp = await client.invoke(messages)
    assert resp == dummy_response


@pytest.mark.asyncio
async def test_openai_invoke_uses_responses_for_new_model_families(monkeypatch):
    """Responses 전용 모델군은 chat/completions를 거치지 않고 responses를 호출한다."""
    messages = [{"role": "user", "content": "hi"}]
    requested_urls = []
    requested_payloads = []

    class MockResponse:
        status_code = 200
        text = ""

        def json(self):
            return {
                "error": None,
                "output_text": "hello",
                "usage": {"input_tokens": 2, "output_tokens": 3},
            }

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            requested_urls.append(url)
            requested_payloads.append(kwargs.get("json", {}))
            return MockResponse()

    monkeypatch.setattr(
        "apps.shared.services.llm_client.openai_client.httpx.AsyncClient",
        lambda **kw: MockAsyncClient()
    )

    client = OpenAIClient(
        model_id="gpt-5",
        credentials={"apiKey": "sk-test", "baseUrl": "https://api.openai.com/v1"},
    )

    resp = await client.invoke(messages, max_tokens=10)

    assert requested_urls == ["https://api.openai.com/v1/responses"]
    assert requested_payloads[0]["max_output_tokens"] == 10
    assert "max_tokens" not in requested_payloads[0]
    assert "max_completion_tokens" not in requested_payloads[0]
    assert resp["choices"][0]["message"]["content"] == "hello"
    assert resp["usage"]["prompt_tokens"] == 2
    assert resp["usage"]["completion_tokens"] == 3
    assert resp["usage"]["total_tokens"] == 5


@pytest.mark.asyncio
async def test_openai_invoke_does_not_fallback_to_completions_for_responses_models(monkeypatch):
    """Responses 모델군은 responses 실패 후 legacy completions로 내려가지 않는다."""
    messages = [{"role": "user", "content": "hi"}]
    requested_urls = []

    class MockResponse:
        status_code = 404
        text = '{"error":{"message":"model not found","type":"invalid_request_error"}}'

        def json(self):
            return {
                "error": {
                    "message": "model not found",
                    "type": "invalid_request_error",
                }
            }

    class MockAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, url, **kwargs):
            requested_urls.append(url)
            return MockResponse()

    monkeypatch.setattr(
        "apps.shared.services.llm_client.openai_client.httpx.AsyncClient",
        lambda **kw: MockAsyncClient()
    )

    client = OpenAIClient(
        model_id="o1-pro",
        credentials={"apiKey": "sk-test", "baseUrl": "https://api.openai.com/v1"},
    )

    with pytest.raises(ValueError, match="model not found"):
        await client.invoke(messages)

    assert requested_urls == ["https://api.openai.com/v1/responses"]


@pytest.mark.asyncio
async def test_openai_invoke_failure(monkeypatch):
    """invoke 실패 시 ValueError 발생 확인"""
    messages = [{"role": "user", "content": "hi"}]

    class MockResponse:
        status_code = 401
        text = "unauthorized"

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        
        async def __aexit__(self, *args):
            pass
        
        async def post(self, url, **kwargs):
            return MockResponse()

    monkeypatch.setattr(
        "apps.shared.services.llm_client.openai_client.httpx.AsyncClient",
        lambda **kw: MockAsyncClient()
    )

    client = OpenAIClient(
        model_id="gpt-4o",
        credentials={"apiKey": "sk-test", "baseUrl": "https://api.openai.com/v1"},
    )
    with pytest.raises(ValueError):
        await client.invoke(messages)


def test_openai_token_estimate():
    """토큰 수 추정 동작 확인"""
    # tiktoken 모킹
    class DummyEnc:
        def encode(self, text):
            return list(text)

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(
        "apps.shared.services.llm_client.openai_client.tiktoken.encoding_for_model",
        lambda *_args, **_kwargs: DummyEnc(),
    )
    monkeypatch.setattr(
        "apps.shared.services.llm_client.openai_client.tiktoken.get_encoding",
        lambda *_args, **_kwargs: DummyEnc(),
    )

    client = OpenAIClient(
        model_id="gpt-4o",
        credentials={"apiKey": "sk-test", "baseUrl": "https://api.openai.com/v1"},
    )
    messages = [{"role": "user", "content": "hello world"}]
    tokens = client.get_num_tokens(messages)
    assert tokens >= 1
