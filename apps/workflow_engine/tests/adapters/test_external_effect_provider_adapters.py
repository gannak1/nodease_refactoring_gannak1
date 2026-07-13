from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import Mock, patch

import httpx
import pytest
import requests

from apps.workflow_engine.adapters.providers.generic_http import (
    GenericHttpEffectAdapter,
    GenericHttpRequest,
)
from apps.workflow_engine.adapters.providers.github import (
    GithubCommentEffectAdapter,
    GithubCommentRequest,
)
from apps.workflow_engine.domain.external_effect import (
    EffectInvocationFailure,
    EffectOutcome,
    ProviderContractRegistry,
    ProviderReplayCapability,
)


class _HttpClient:
    def __init__(self, *, error: Exception, **_kwargs) -> None:
        self.error = error

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def request(self, **_kwargs):
        raise self.error


class _CaptureHttpClient:
    def __init__(self, calls: list[dict], **_kwargs) -> None:
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def request(self, **kwargs):
        self.calls.append(kwargs)
        return httpx.Response(200, json={"ok": True})


class _ResponseHttpClient:
    def __init__(self, response: httpx.Response, **_kwargs) -> None:
        self.response = response

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def request(self, **_kwargs):
        return self.response


def test_generic_http_local_protocol_error_is_safe_stop() -> None:
    adapter = GenericHttpEffectAdapter(
        client_factory=lambda **kwargs: _HttpClient(
            error=httpx.InvalidURL("invalid URL"),
            **kwargs,
        )
    )
    prepared = adapter.prepare_effect(
        GenericHttpRequest("POST", "not-a-url", {}, None, 1.0)
    )

    assert prepared.error_code == "invalid_prepared_request"

    with pytest.raises(EffectInvocationFailure) as captured:
        adapter.invoke_effect(adapter.finalize_provider_call(prepared, None))

    assert captured.value.outcome is EffectOutcome.FAILED_BEFORE_EFFECT
    assert captured.value.error_code == "invalid_prepared_request"
    assert captured.value.retry_before_effect is False


def test_generic_http_response_loss_is_outcome_unknown() -> None:
    request = httpx.Request("POST", "https://example.test")
    adapter = GenericHttpEffectAdapter(
        client_factory=lambda **kwargs: _HttpClient(
            error=httpx.ReadTimeout("read timed out", request=request),
            **kwargs,
        )
    )
    prepared = adapter.prepare_effect(
        GenericHttpRequest("POST", "https://example.test", {}, None, 1.0)
    )

    with pytest.raises(EffectInvocationFailure) as captured:
        adapter.invoke_effect(adapter.finalize_provider_call(prepared, None))

    assert captured.value.outcome is EffectOutcome.EFFECT_OUTCOME_UNKNOWN
    assert captured.value.error_code == "response_lost"


@pytest.mark.parametrize(
    ("content", "content_type"),
    [
        (b"\xff", "application/json; charset=utf-8"),
        (b"not-json", "application/json; charset=not-a-codec"),
    ],
)
def test_generic_http_invalid_text_encoding_falls_back_to_text_output(
    content,
    content_type,
) -> None:
    response = httpx.Response(
        200,
        content=content,
        headers={"content-type": content_type},
    )
    adapter = GenericHttpEffectAdapter(
        client_factory=lambda **kwargs: _ResponseHttpClient(response, **kwargs)
    )
    prepared = adapter.prepare_effect(
        GenericHttpRequest("POST", "https://example.test", {}, None, 1.0)
    )

    result = adapter.invoke_effect(adapter.finalize_provider_call(prepared, None))

    assert result.output["status"] == 200
    assert isinstance(result.output["data"], str)
    assert result.output["data"]


@pytest.mark.parametrize(
    ("body", "expected_mode", "expected_content_type", "payload_key"),
    [
        (None, "no_body", "text/plain", "content"),
        ("", "no_body", "text/plain", "content"),
        ("null", "json_null_no_body", None, "content"),
        ('{"b":2,"a":1}', "json", "application/json", "json"),
    ],
)
def test_generic_http_prepares_and_invokes_frozen_wire_mode(
    body,
    expected_mode,
    expected_content_type,
    payload_key,
) -> None:
    calls: list[dict] = []
    adapter = GenericHttpEffectAdapter(
        client_factory=lambda **kwargs: _CaptureHttpClient(calls, **kwargs)
    )
    prepared = adapter.prepare_effect(
        GenericHttpRequest(
            "POST",
            "https://example.test/items",
            {"Content-Type": "text/plain"},
            body,
            1.0,
        )
    )

    adapter.invoke_effect(adapter.finalize_provider_call(prepared, None))

    frozen = prepared.request
    assert frozen.body_mode == expected_mode
    headers = dict(calls[0]["headers"])
    assert headers.get("content-type") == expected_content_type
    assert payload_key in calls[0]
    if payload_key == "json":
        assert list(calls[0]["json"]) == ["b", "a"]
    else:
        assert calls[0]["content"] is None


def test_generic_http_digest_normalizes_json_object_key_order() -> None:
    adapter = GenericHttpEffectAdapter()

    first = adapter.prepare_effect(
        GenericHttpRequest("POST", "https://example.test", {}, '{"a":1,"b":2}', 1.0)
    )
    reordered = adapter.prepare_effect(
        GenericHttpRequest("POST", "https://example.test", {}, '{"b":2,"a":1}', 1.0)
    )

    assert first.effect_input_digest == reordered.effect_input_digest
    assert list(first.request.json_body) == ["a", "b"]
    assert list(reordered.request.json_body) == ["b", "a"]


def test_generic_http_request_v1_matches_frozen_length_delimited_digest() -> None:
    adapter = GenericHttpEffectAdapter()

    prepared = adapter.prepare_effect(
        GenericHttpRequest(
            "POST",
            "https://example.test/items?b=2&a=1",
            httpx.Headers(
                [
                    ("X-Trace", "first"),
                    ("X-Trace", "second"),
                    ("Content-Type", "text/plain"),
                ]
            ),
            '{"b":2,"a":1}',
            1.0,
        )
    )

    assert prepared.effect_input_digest == (
        "1c84d9f5aa88406bbdb077f7dac7e6f6f7b661d03c9236baceac8c8fe03f1c4b"
    )


def test_supported_http_profile_rejects_reserved_key_field_before_network() -> None:
    base_profile = GenericHttpEffectAdapter().profile
    supported = replace(
        base_profile,
        provider_replay=ProviderReplayCapability.SUPPORTED,
        key_transport="header",
        key_field="Idempotency-Key",
        key_format="hmac-b64url-v1",
        key_max_length=64,
        retention=timedelta(hours=24),
    )
    adapter = GenericHttpEffectAdapter(active_profile=supported)

    prepared = adapter.prepare_effect(
        GenericHttpRequest(
            "POST",
            "https://example.test",
            {"idempotency-key": "caller-value"},
            None,
            1.0,
        ),
        profile=supported,
    )

    assert prepared.error_code == "provider_key_field_conflict"


def test_supported_body_profile_rejects_reserved_json_pointer_before_network() -> None:
    base_profile = GenericHttpEffectAdapter().profile
    supported = replace(
        base_profile,
        provider_replay=ProviderReplayCapability.SUPPORTED,
        key_transport="body",
        key_field="/request_id",
        key_format="hmac-b64url-v1",
        key_max_length=64,
        retention=timedelta(hours=24),
    )
    adapter = GenericHttpEffectAdapter(active_profile=supported)
    prepared = adapter.prepare_effect(
        GenericHttpRequest(
            "POST",
            "https://example.test",
            {},
            '{"request_id":"caller-value"}',
            1.0,
        ),
        profile=supported,
    )

    assert prepared.error_code == "provider_key_field_conflict"


def test_supported_body_profile_injects_key_at_json_pointer_only() -> None:
    base_profile = GenericHttpEffectAdapter().profile
    supported = replace(
        base_profile,
        provider_replay=ProviderReplayCapability.SUPPORTED,
        key_transport="body",
        key_field="/metadata/request_id",
        key_format="hmac-b64url-v1",
        key_max_length=64,
        retention=timedelta(hours=24),
    )
    adapter = GenericHttpEffectAdapter(active_profile=supported)
    prepared = adapter.prepare_effect(
        GenericHttpRequest(
            "POST",
            "https://example.test",
            {},
            '{"metadata":{"value":1}}',
            1.0,
        ),
        profile=supported,
    )

    call = adapter.finalize_provider_call(prepared, "generated-key")

    assert call.request.json_body == {
        "metadata": {"value": 1, "request_id": "generated-key"}
    }
    assert call.request.headers == (("content-type", "application/json"),)


def test_http_adapter_can_prepare_frozen_v1_after_active_v2_switch() -> None:
    v1 = GenericHttpEffectAdapter().profile
    v2 = replace(v1, contract_version="generic_http.request.v2")
    contracts = ProviderContractRegistry(
        (v1, v2),
        active_versions={(v1.provider, v1.operation): v2.contract_version},
    )
    adapter = GenericHttpEffectAdapter(contracts=contracts)

    prepared = adapter.prepare_effect(
        GenericHttpRequest("POST", "https://example.test", {}, None, 1.0),
        profile=v1,
    )

    assert adapter.profile == v2
    assert prepared.profile == v1

    call = adapter.finalize_provider_call(prepared, None)
    assert call.profile == v1


def test_github_adapter_can_prepare_frozen_v1_after_active_v2_switch() -> None:
    v1 = GithubCommentEffectAdapter().profile
    v2 = replace(v1, contract_version="github.issue_comment.create.v2")
    contracts = ProviderContractRegistry(
        (v1, v2),
        active_versions={(v1.provider, v1.operation): v2.contract_version},
    )
    adapter = GithubCommentEffectAdapter(contracts=contracts)

    prepared = adapter.prepare_effect(
        GithubCommentRequest("fixture-value", "owner", "repo", 1, "comment"),
        profile=v1,
    )

    assert adapter.profile == v2
    assert prepared.profile == v1

    call = adapter.finalize_provider_call(prepared, None)
    assert call.profile == v1


def test_http_adapter_rejects_contract_with_unknown_request_semantics() -> None:
    v1 = GenericHttpEffectAdapter().profile
    unsupported = replace(
        v1,
        contract_version="generic_http.request.v2",
        request_semantics="generic_http.request.missing",
    )
    contracts = ProviderContractRegistry(
        (v1, unsupported),
        active_versions={
            (v1.provider, v1.operation): unsupported.contract_version,
        },
    )

    with pytest.raises(ValueError, match="request semantics"):
        GenericHttpEffectAdapter(contracts=contracts)


def test_github_adapter_rejects_contract_with_unknown_response_semantics() -> None:
    v1 = GithubCommentEffectAdapter().profile
    unsupported = replace(
        v1,
        contract_version="github.issue_comment.create.v2",
        response_semantics="github.issue_comment.response.missing",
    )
    contracts = ProviderContractRegistry(
        (v1, unsupported),
        active_versions={
            (v1.provider, v1.operation): unsupported.contract_version,
        },
    )

    with pytest.raises(ValueError, match="response semantics"):
        GithubCommentEffectAdapter(contracts=contracts)


def test_github_invalid_url_is_safe_stop() -> None:
    adapter = GithubCommentEffectAdapter()
    prepared = adapter.prepare_effect(
        GithubCommentRequest("fixture-value", "owner", "repo", 1, "comment")
    )

    with patch(
        "apps.workflow_engine.adapters.providers.github.requests.post",
        side_effect=requests.exceptions.InvalidURL("invalid URL"),
    ):
        with pytest.raises(EffectInvocationFailure) as captured:
            adapter.invoke_effect(adapter.finalize_provider_call(prepared, None))

    assert captured.value.outcome is EffectOutcome.FAILED_BEFORE_EFFECT
    assert captured.value.error_code == "invalid_prepared_request"
    assert captured.value.retry_before_effect is False


@pytest.mark.parametrize("status_code", [401, 403, 404, 410, 422])
def test_github_explicit_rejection_is_failed_before_effect(status_code) -> None:
    adapter = GithubCommentEffectAdapter()
    prepared = adapter.prepare_effect(
        GithubCommentRequest("fixture-value", "owner", "repo", 1, "comment")
    )
    response = Mock(status_code=status_code, content=b"{}")

    with patch(
        "apps.workflow_engine.adapters.providers.github.requests.post",
        return_value=response,
    ):
        with pytest.raises(EffectInvocationFailure) as captured:
            adapter.invoke_effect(adapter.finalize_provider_call(prepared, None))

    assert captured.value.outcome is EffectOutcome.FAILED_BEFORE_EFFECT
    assert captured.value.error_code == "provider_rejected_request"
    assert captured.value.provider_status_code == status_code
    assert captured.value.retry_before_effect is False


@pytest.mark.parametrize(
    "payload",
    [
        {"id": None, "html_url": "https://example.test/comment", "body": "ok"},
        {"id": True, "html_url": "https://example.test/comment", "body": "ok"},
        {"id": 1, "html_url": "", "body": "ok"},
        {"id": 1, "html_url": "https://example.test/comment", "body": {}},
    ],
)
def test_github_201_requires_schema_valid_comment(payload) -> None:
    adapter = GithubCommentEffectAdapter()
    prepared = adapter.prepare_effect(
        GithubCommentRequest("fixture-value", "owner", "repo", 1, "comment")
    )
    response = Mock(status_code=201, content=b"{}")
    response.json.return_value = payload

    with patch(
        "apps.workflow_engine.adapters.providers.github.requests.post",
        return_value=response,
    ):
        with pytest.raises(EffectInvocationFailure) as captured:
            adapter.invoke_effect(adapter.finalize_provider_call(prepared, None))

    assert captured.value.outcome is EffectOutcome.EFFECT_OUTCOME_UNKNOWN
    assert captured.value.error_code == "response_malformed"
