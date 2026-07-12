from __future__ import annotations

import os
from dataclasses import dataclass, field

import httpx

from apps.shared.domain.mail_oauth import GmailOAuthSecret, MailOAuthSecretError
from apps.workflow_engine.application.mail_processing import (
    GmailDraftRejectedBeforeEffect,
)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True)
class GoogleAccessToken:
    value: str
    rotated_secret_payload: str | None = field(default=None, repr=False)

    def __repr__(self) -> str:
        return "GoogleAccessToken(value=[redacted])"


class GoogleOAuthTokenService:
    def __init__(
        self,
        *,
        client_id: str | None = None,
        client_secret: str | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        self._client_id = (client_id or os.getenv("GOOGLE_CLIENT_ID", "")).strip()
        self._client_secret = (
            client_secret or os.getenv("GOOGLE_CLIENT_SECRET", "")
        ).strip()
        self._client = client

    def refresh(self, encrypted_payload: str) -> GoogleAccessToken:
        if not self._client_id or not self._client_secret:
            raise GmailDraftRejectedBeforeEffect("mail.oauth_configuration_missing")
        try:
            secret = GmailOAuthSecret.parse(encrypted_payload)
        except MailOAuthSecretError as exc:
            raise GmailDraftRejectedBeforeEffect(exc.reason_code) from exc
        client = self._client or httpx.Client(timeout=10.0, follow_redirects=False)
        should_close = self._client is None
        try:
            response = client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": secret.refresh_token,
                },
                headers={"Accept": "application/json"},
            )
        except httpx.RequestError:
            raise GmailDraftRejectedBeforeEffect(
                "mail.oauth_token_exchange_failed"
            ) from None
        finally:
            if should_close:
                client.close()
        if response.status_code != 200:
            try:
                oauth_error = response.json().get("error")
            except (ValueError, AttributeError):
                oauth_error = None
            reason = "mail.oauth_token_exchange_failed"
            if response.status_code == 400 and oauth_error == "invalid_grant":
                reason = "mail.oauth_reauthorization_required"
            raise GmailDraftRejectedBeforeEffect(reason)
        try:
            payload = response.json()
            access_token = payload.get("access_token")
        except (TypeError, ValueError, AttributeError):
            raise GmailDraftRejectedBeforeEffect(
                "mail.oauth_token_exchange_failed"
            ) from None
        if not isinstance(access_token, str) or not access_token:
            raise GmailDraftRejectedBeforeEffect("mail.oauth_token_exchange_failed")
        rotated_secret_payload = None
        replacement_refresh_token = payload.get("refresh_token")
        if replacement_refresh_token is not None:
            if not isinstance(replacement_refresh_token, str):
                raise GmailDraftRejectedBeforeEffect("mail.oauth_token_exchange_failed")
            if (
                replacement_refresh_token
                and replacement_refresh_token != secret.refresh_token
            ):
                rotated_secret_payload = GmailOAuthSecret(
                    refresh_token=replacement_refresh_token,
                    scopes=secret.scopes,
                ).serialize()
        return GoogleAccessToken(
            access_token,
            rotated_secret_payload=rotated_secret_payload,
        )
