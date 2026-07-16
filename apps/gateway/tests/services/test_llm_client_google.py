from apps.shared.services.llm_client.google_client import GoogleClient


def test_google_client_strips_internal_request_timeout_from_payload_kwargs():
    client = GoogleClient(
        model_id="gemini-2.5-flash",
        credentials={
            "apiKey": "redacted-test-key",
            "baseUrl": "https://generativelanguage.googleapis.com/v1beta/openai",
        },
    )

    assert client._sanitize_kwargs(
        {
            "temperature": 0,
            "request_timeout_seconds": 90,
        }
    ) == {"temperature": 0}
