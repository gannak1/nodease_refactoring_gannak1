from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from collections.abc import Mapping

from cryptography.fernet import Fernet, InvalidToken

from apps.memory.application.public_lifecycle import (
    IssuedSecret,
    SecretCiphertext,
)


_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43,128}$")
_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$")
_DEFAULT_VERIFIER_KEY_VERSION = "memory-public-hmac-v1"
_DEFAULT_REPLAY_KEY_VERSION = "memory-public-replay-v1"


class HmacPublicSecretIssuer:
    """Issue opaque public capabilities and derive non-reversible verifiers."""

    def __init__(
        self,
        verifier_key: bytes,
        *,
        key_version: str = _DEFAULT_VERIFIER_KEY_VERSION,
    ) -> None:
        if len(verifier_key) < 32:
            raise ValueError("public capability verifier key must be at least 32 bytes")
        if not _VERSION_PATTERN.fullmatch(key_version):
            raise ValueError("public capability verifier key version is required")
        self._verifier_key = verifier_key
        self._key_version = key_version

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
    ) -> "HmacPublicSecretIssuer":
        raw_key = environ.get("MEMORY_PUBLIC_CAPABILITY_HMAC_KEY", "")
        if not raw_key:
            raise RuntimeError("MEMORY_PUBLIC_CAPABILITY_HMAC_KEY is required")
        key_version = environ.get(
            "MEMORY_PUBLIC_CAPABILITY_HMAC_KEY_VERSION",
            _DEFAULT_VERIFIER_KEY_VERSION,
        )
        try:
            return cls(raw_key.encode("utf-8"), key_version=key_version)
        except ValueError as exc:
            raise RuntimeError(str(exc)) from None

    def issue_access_grant(self) -> IssuedSecret:
        return self._issue(prefix="cag", purpose="access_grant")

    def access_grant_verifier(self, raw_value: str) -> tuple[str, str] | None:
        return self._verifier_for(raw_value, prefix="cag", purpose="access_grant")

    def issue_purge_receipt(self) -> IssuedSecret:
        return self._issue(prefix="cpr", purpose="purge_receipt")

    def purge_receipt_verifier(self, raw_value: str) -> tuple[str, str] | None:
        return self._verifier_for(raw_value, prefix="cpr", purpose="purge_receipt")

    def _issue(self, *, prefix: str, purpose: str) -> IssuedSecret:
        raw_value = f"{prefix}_v1_{secrets.token_urlsafe(32)}"
        return IssuedSecret(
            raw_value=raw_value,
            verifier_hash=self._digest(purpose, raw_value),
            verifier_key_version=self._key_version,
        )

    def _verifier_for(
        self,
        raw_value: str,
        *,
        prefix: str,
        purpose: str,
    ) -> tuple[str, str] | None:
        expected_prefix = f"{prefix}_v1_"
        if (
            not isinstance(raw_value, str)
            or not raw_value.startswith(expected_prefix)
            or not _TOKEN_PATTERN.fullmatch(raw_value[len(expected_prefix) :])
        ):
            return None
        return self._key_version, self._digest(purpose, raw_value)

    def _digest(self, purpose: str, raw_value: str) -> str:
        message = f"memory-public-capability-v1:{purpose}:{raw_value}".encode("utf-8")
        return hmac.new(self._verifier_key, message, hashlib.sha256).hexdigest()


class FernetSecretReplayCipher:
    """Encrypt short-lived replay values and bind them to an idempotency result."""

    def __init__(
        self,
        fernet_key: bytes,
        *,
        key_version: str = _DEFAULT_REPLAY_KEY_VERSION,
    ) -> None:
        if not _VERSION_PATTERN.fullmatch(key_version):
            raise ValueError("secret replay key version is required")
        try:
            self._fernet = Fernet(fernet_key)
        except (TypeError, ValueError) as exc:
            raise ValueError("secret replay key is invalid") from exc
        self._key_version = key_version

    @classmethod
    def from_environment(
        cls,
        environ: Mapping[str, str],
    ) -> "FernetSecretReplayCipher":
        raw_key = environ.get("MEMORY_PUBLIC_REPLAY_ENCRYPTION_KEY", "")
        if not raw_key:
            raise RuntimeError("MEMORY_PUBLIC_REPLAY_ENCRYPTION_KEY is required")
        key_version = environ.get(
            "MEMORY_PUBLIC_REPLAY_ENCRYPTION_KEY_VERSION",
            _DEFAULT_REPLAY_KEY_VERSION,
        )
        try:
            return cls(raw_key.encode("ascii"), key_version=key_version)
        except (UnicodeEncodeError, ValueError) as exc:
            raise RuntimeError("MEMORY_PUBLIC_REPLAY_ENCRYPTION_KEY is invalid") from exc

    def encrypt(
        self,
        raw_value: str,
        *,
        associated_data_digest: str,
    ) -> SecretCiphertext:
        if not isinstance(raw_value, str) or len(raw_value) > 1024:
            raise ValueError("secret replay value is invalid")
        payload = json.dumps(
            {"aad": associated_data_digest, "value": raw_value},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return SecretCiphertext(
            ciphertext=self._fernet.encrypt(payload),
            key_version=self._key_version,
        )

    def decrypt(
        self,
        ciphertext: bytes,
        *,
        key_version: str,
        associated_data_digest: str,
    ) -> str | None:
        if key_version != self._key_version:
            return None
        try:
            payload = json.loads(self._fernet.decrypt(ciphertext).decode("utf-8"))
        except (InvalidToken, UnicodeDecodeError, json.JSONDecodeError, TypeError):
            return None
        if not isinstance(payload, dict):
            return None
        stored_digest = payload.get("aad")
        raw_value = payload.get("value")
        if (
            not isinstance(stored_digest, str)
            or not isinstance(raw_value, str)
            or not hmac.compare_digest(stored_digest, associated_data_digest)
        ):
            return None
        return raw_value


__all__ = ["FernetSecretReplayCipher", "HmacPublicSecretIssuer"]
