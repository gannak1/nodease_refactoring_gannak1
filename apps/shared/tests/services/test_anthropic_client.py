from apps.shared.services.llm_client.anthropic_client import AnthropicClient


def _client() -> AnthropicClient:
    return AnthropicClient(
        model_id="claude-example",
        credentials={
            "apiKey": "test-placeholder",
            "baseUrl": "https://example.invalid",
        },
    )


def test_anthropic_conversion_preserves_valid_usage():
    response = _client()._convert_to_openai_format(
        {
            "content": [{"type": "text", "text": "ok"}],
            "usage": {"input_tokens": 12, "output_tokens": 3},
        }
    )

    assert response["usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 3,
        "total_tokens": 15,
    }


def test_anthropic_conversion_does_not_synthesize_missing_usage():
    response = _client()._convert_to_openai_format(
        {"content": [{"type": "text", "text": "ok"}]}
    )

    assert response["usage"] == {}
