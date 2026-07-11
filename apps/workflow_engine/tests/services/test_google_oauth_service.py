import httpx
import pytest

from apps.shared.domain.mail_oauth import GMAIL_MODIFY_SCOPE, GmailOAuthSecret
from apps.workflow_engine.application.mail_processing import (
    GmailDraftRejectedBeforeEffect,
)
from apps.workflow_engine.services.google_oauth_service import (
    GoogleOAuthTokenService,
)


def _secret():
    return GmailOAuthSecret(
        refresh_token="synthetic-refresh-token",
        scopes=(GMAIL_MODIFY_SCOPE,),
    ).serialize()


def test_refresh_returns_redacted_access_token_wrapper():
    def handler(request):
        assert request.url.host == "oauth2.googleapis.com"
        assert b"synthetic-refresh-token" in request.content
        return httpx.Response(200, json={"access_token": "synthetic-access-token"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = GoogleOAuthTokenService(
        client_id="client-id",
        client_secret="client-secret",
        client=client,
    ).refresh(_secret())

    assert token.value == "synthetic-access-token"
    assert "synthetic-access-token" not in repr(token)


def test_refresh_fails_safe_without_configuration():
    with pytest.raises(GmailDraftRejectedBeforeEffect) as exc_info:
        GoogleOAuthTokenService(client_id="", client_secret="").refresh(_secret())
    assert exc_info.value.reason_code == "mail.oauth_configuration_missing"


def test_refresh_does_not_expose_provider_error_body():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(400, json={"error": "raw-provider-detail"})
        )
    )
    with pytest.raises(GmailDraftRejectedBeforeEffect) as exc_info:
        GoogleOAuthTokenService(
            client_id="client-id",
            client_secret="client-secret",
            client=client,
        ).refresh(_secret())
    assert str(exc_info.value) == "mail.oauth_token_exchange_failed"
    assert "raw-provider-detail" not in str(exc_info.value)


def test_refresh_returns_validated_replacement_secret_for_atomic_rotation():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(
                200,
                json={
                    "access_token": "synthetic-access-token",
                    "refresh_token": "replacement-refresh-token",
                },
            )
        )
    )

    token = GoogleOAuthTokenService(
        client_id="client-id",
        client_secret="client-secret",
        client=client,
    ).refresh(_secret())

    rotated = GmailOAuthSecret.parse(token.rotated_secret_payload)
    assert rotated.refresh_token == "replacement-refresh-token"
    assert GMAIL_MODIFY_SCOPE in rotated.scopes
    assert "replacement-refresh-token" not in repr(token)


def test_invalid_grant_is_the_only_provider_error_requiring_reauthorization():
    token_service = GoogleOAuthTokenService(
        client_id="client-id",
        client_secret="client-secret",
        client=httpx.Client(
            transport=httpx.MockTransport(
                lambda _request: httpx.Response(400, json={"error": "invalid_grant"})
            )
        ),
    )

    with pytest.raises(GmailDraftRejectedBeforeEffect) as exc_info:
        token_service.refresh(_secret())

    assert exc_info.value.reason_code == "mail.oauth_reauthorization_required"
