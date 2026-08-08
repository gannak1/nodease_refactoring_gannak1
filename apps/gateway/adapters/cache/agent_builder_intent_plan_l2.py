from __future__ import annotations

import hashlib
import hmac
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from apps.gateway.application.agent_builder.intent_cache import (
    CachedIntentPlanV1,
    CanonicalIntentPlanCodec,
    IntentPlanL2SaveResult,
    IntentPlanL2StoredReceipt,
    IntentPlanLoadResult,
    IntentPlanningContext,
)
from apps.gateway.core.config import AgentBuilderIntentPlanL2Config
from apps.shared.db.models.agent_builder import AgentBuilderIntentPlanCacheRecord
from apps.shared.services.credential_encryption import (
    CredentialEncryptionError,
    CredentialEncryptionService,
    EncryptedSecretEnvelope,
)


_LOOKUP_TOKEN_PATTERN = re.compile(r"^[a-f0-9]{64}$")
_VERSION_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
_L2_ENVELOPE_VERSION = 1
_LOOKUP_DOMAIN = b"agent-builder-intent-plan-l2:lookup:"
_ENVELOPE_DOMAIN = b"agent-builder-intent-plan-l2:envelope:"
_RETENTION = timedelta(days=30)
_SCHEMA_READINESS_SQLSTATES = frozenset({"42P01", "42703"})


class IntentPlanL2EnvelopeError(ValueError):
    """Safe L2 envelope failure that never carries cache payload details."""


@dataclass(frozen=True, slots=True)
class IntentPlanL2Envelope:
    ciphertext: str
    mac: str
    encryption_key_version: str
    encryption_algorithm: str
    envelope_version: int = _L2_ENVELOPE_VERSION


class IntentPlanL2EnvelopeCodec:
    """Repository-specific encrypted envelope for an already cache-safe plan."""

    def __init__(
        self,
        *,
        hmac_key: bytes,
        hmac_key_version: str,
        encryption: CredentialEncryptionService,
        max_payload_bytes: int,
    ) -> None:
        if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
            raise ValueError("invalid L2 HMAC configuration")
        if _VERSION_PATTERN.fullmatch(hmac_key_version) is None:
            raise ValueError("invalid L2 HMAC key version")
        if not isinstance(encryption, CredentialEncryptionService):
            raise ValueError("invalid L2 encryption service")
        if (
            type(max_payload_bytes) is not int
            or not 4 * 1024 <= max_payload_bytes <= 64 * 1024
        ):
            raise ValueError("invalid L2 payload limit")
        self._hmac_key = hmac_key
        self._hmac_key_version = hmac_key_version
        self._encryption = encryption
        self._max_payload_bytes = max_payload_bytes
        self._plan_codec = CanonicalIntentPlanCodec()

    @property
    def lookup_key_version(self) -> str:
        return self._hmac_key_version

    def lookup_token(self, canonical_key_material: bytes) -> str:
        if not isinstance(canonical_key_material, bytes) or not canonical_key_material:
            raise IntentPlanL2EnvelopeError("invalid L2 lookup material")
        payload = self._frame(
            _LOOKUP_DOMAIN + self._hmac_key_version.encode("ascii") + b"\0",
            canonical_key_material,
        )
        return hmac.new(self._hmac_key, payload, hashlib.sha256).hexdigest()

    def encode(
        self,
        plan: CachedIntentPlanV1,
        *,
        lookup_token: str,
    ) -> IntentPlanL2Envelope:
        self._validate_lookup_token(lookup_token)
        try:
            payload = self._plan_codec.encode(plan, self._max_payload_bytes)
            encrypted = self._encryption.encrypt(payload.decode("utf-8"))
        except (CredentialEncryptionError, UnicodeDecodeError, ValueError) as exc:
            raise IntentPlanL2EnvelopeError("L2 envelope encoding failed") from exc
        envelope = IntentPlanL2Envelope(
            ciphertext=encrypted.ciphertext,
            mac="",
            encryption_key_version=encrypted.key_version,
            encryption_algorithm=encrypted.algorithm,
        )
        return IntentPlanL2Envelope(
            ciphertext=envelope.ciphertext,
            mac=self._mac(lookup_token=lookup_token, envelope=envelope),
            encryption_key_version=envelope.encryption_key_version,
            encryption_algorithm=envelope.encryption_algorithm,
            envelope_version=envelope.envelope_version,
        )

    def decode(
        self,
        envelope: IntentPlanL2Envelope,
        *,
        lookup_token: str,
    ) -> CachedIntentPlanV1:
        self._validate_lookup_token(lookup_token)
        self._validate_envelope(envelope)
        expected_mac = self._mac(lookup_token=lookup_token, envelope=envelope)
        if not hmac.compare_digest(expected_mac, envelope.mac):
            raise IntentPlanL2EnvelopeError("L2 envelope integrity failed")
        try:
            plaintext = self._encryption.decrypt(
                EncryptedSecretEnvelope(
                    ciphertext=envelope.ciphertext,
                    key_version=envelope.encryption_key_version,
                    algorithm=envelope.encryption_algorithm,
                )
            )
            return self._plan_codec.decode(
                plaintext.encode("utf-8"),
                self._max_payload_bytes,
            )
        except (CredentialEncryptionError, UnicodeDecodeError, ValueError) as exc:
            raise IntentPlanL2EnvelopeError("L2 envelope decoding failed") from exc

    def _mac(self, *, lookup_token: str, envelope: IntentPlanL2Envelope) -> str:
        payload = self._frame(
            _ENVELOPE_DOMAIN + self._hmac_key_version.encode("ascii") + b"\0",
            lookup_token.encode("ascii"),
            str(envelope.envelope_version).encode("ascii"),
            envelope.encryption_key_version.encode("ascii"),
            envelope.encryption_algorithm.encode("ascii"),
            envelope.ciphertext.encode("ascii"),
        )
        return hmac.new(self._hmac_key, payload, hashlib.sha256).hexdigest()

    @staticmethod
    def _frame(domain: bytes, *parts: bytes) -> bytes:
        return b"".join(
            len(part).to_bytes(4, "big") + part
            for part in (domain, *parts)
        )

    @staticmethod
    def _validate_lookup_token(lookup_token: str) -> None:
        if not isinstance(lookup_token, str) or _LOOKUP_TOKEN_PATTERN.fullmatch(
            lookup_token
        ) is None:
            raise IntentPlanL2EnvelopeError("invalid L2 lookup token")

    @staticmethod
    def _validate_envelope(envelope: IntentPlanL2Envelope) -> None:
        if not isinstance(envelope, IntentPlanL2Envelope):
            raise IntentPlanL2EnvelopeError("invalid L2 envelope")
        if envelope.envelope_version != _L2_ENVELOPE_VERSION:
            raise IntentPlanL2EnvelopeError("invalid L2 envelope")
        if (
            not envelope.ciphertext
            or _LOOKUP_TOKEN_PATTERN.fullmatch(envelope.mac) is None
            or _VERSION_PATTERN.fullmatch(envelope.encryption_key_version) is None
            or envelope.encryption_algorithm != "fernet-v1"
        ):
            raise IntentPlanL2EnvelopeError("invalid L2 envelope")
        try:
            envelope.ciphertext.encode("ascii")
        except UnicodeEncodeError as exc:
            raise IntentPlanL2EnvelopeError("invalid L2 envelope") from exc


class PostgresIntentPlanRepository:
    """Optional L2 repository that owns a short, independent DB transaction."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], object],
        envelope_codec: IntentPlanL2EnvelopeCodec,
        config: AgentBuilderIntentPlanL2Config,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("invalid L2 session factory")
        if not isinstance(envelope_codec, IntentPlanL2EnvelopeCodec):
            raise ValueError("invalid L2 envelope codec")
        if not isinstance(config, AgentBuilderIntentPlanL2Config):
            raise ValueError("invalid L2 configuration")
        self._session_factory = session_factory
        self._envelope_codec = envelope_codec
        self._config = config
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._schema_available = True

    def load(
        self,
        context: IntentPlanningContext,
        canonical_key_material: bytes,
    ) -> IntentPlanLoadResult | None:
        organization_id = context.scope._organization_id
        if not self._schema_available or not self._config.should_read(organization_id):
            return None
        session = None
        try:
            lookup_token = self._envelope_codec.lookup_token(canonical_key_material)
            session = self._session_factory()
            record = session.execute(
                select(AgentBuilderIntentPlanCacheRecord).where(
                    AgentBuilderIntentPlanCacheRecord.organization_id
                    == organization_id,
                    AgentBuilderIntentPlanCacheRecord.lookup_key_version
                    == self._envelope_codec.lookup_key_version,
                    AgentBuilderIntentPlanCacheRecord.lookup_token == lookup_token,
                )
            ).scalar_one_or_none()
            now = self._now()
            if now.tzinfo is None:
                raise ValueError("L2 clock must be timezone-aware")
            if record is None or record.expires_at <= now:
                return IntentPlanLoadResult(
                    status="miss",
                    plan=None,
                    reason="not_found",
                )
            plan = self._envelope_codec.decode(
                IntentPlanL2Envelope(
                    ciphertext=record.envelope_ciphertext,
                    mac=record.envelope_mac,
                    encryption_key_version=record.encryption_key_version,
                    encryption_algorithm=record.encryption_algorithm,
                    envelope_version=record.envelope_version,
                ),
                lookup_token=lookup_token,
            )
            return IntentPlanLoadResult(status="hit", plan=plan, reason=None)
        except IntentPlanL2EnvelopeError:
            return IntentPlanLoadResult(
                status="invalid",
                plan=None,
                reason="invalid_cached_plan",
            )
        except Exception as exc:
            if self._disable_for_schema_readiness_failure(exc):
                return None
            return IntentPlanLoadResult(
                status="unavailable",
                plan=None,
                reason="cache_unavailable",
            )
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def save(
        self,
        context: IntentPlanningContext,
        canonical_key_material: bytes,
        plan: CachedIntentPlanV1,
    ) -> IntentPlanL2SaveResult | None:
        organization_id = context.scope._organization_id
        if not self._schema_available or not self._config.should_write(organization_id):
            return None
        session = None
        try:
            lookup_token = self._envelope_codec.lookup_token(canonical_key_material)
            envelope = self._envelope_codec.encode(plan, lookup_token=lookup_token)
            now = self._now()
            if now.tzinfo is None:
                raise ValueError("L2 clock must be timezone-aware")
            session = self._session_factory()
            values = {
                "organization_id": organization_id,
                "lookup_key_version": self._envelope_codec.lookup_key_version,
                "lookup_token": lookup_token,
                "envelope_ciphertext": envelope.ciphertext,
                "envelope_mac": envelope.mac,
                "encryption_key_version": envelope.encryption_key_version,
                "encryption_algorithm": envelope.encryption_algorithm,
                "envelope_version": envelope.envelope_version,
                "created_at": now,
                "expires_at": now + _RETENTION,
            }
            locked_statement = select(AgentBuilderIntentPlanCacheRecord).where(
                AgentBuilderIntentPlanCacheRecord.organization_id == organization_id,
                AgentBuilderIntentPlanCacheRecord.lookup_key_version
                == self._envelope_codec.lookup_key_version,
                AgentBuilderIntentPlanCacheRecord.lookup_token == lookup_token,
            ).with_for_update()
            record = session.execute(locked_statement).scalar_one_or_none()
            if record is None:
                parent_record_id = uuid.uuid4()
                inserted = session.execute(
                    postgresql_insert(AgentBuilderIntentPlanCacheRecord)
                    .values(id=parent_record_id, **values)
                    .on_conflict_do_nothing(
                        index_elements=(
                            "organization_id",
                            "lookup_key_version",
                            "lookup_token",
                        )
                    )
                    .returning(
                        AgentBuilderIntentPlanCacheRecord.id,
                        AgentBuilderIntentPlanCacheRecord.expires_at,
                    )
                ).first()
                if inserted is not None:
                    parent_record_id, receipt_expiry = inserted
                    write_kind = "inserted"
                else:
                    record = session.execute(locked_statement).scalar_one_or_none()
                    if record is None:
                        session.rollback()
                        return IntentPlanL2SaveResult(
                            status="unavailable",
                            receipt=None,
                            reason="cache_unavailable",
                        )
            if record is not None:
                expired = record.expires_at <= now
                mutation_values = {
                    "envelope_ciphertext": envelope.ciphertext,
                    "envelope_mac": envelope.mac,
                    "encryption_key_version": envelope.encryption_key_version,
                    "encryption_algorithm": envelope.encryption_algorithm,
                    "envelope_version": envelope.envelope_version,
                }
                if expired:
                    mutation_values.update(
                        created_at=values["created_at"],
                        expires_at=values["expires_at"],
                    )
                mutation_result = session.execute(
                    update(AgentBuilderIntentPlanCacheRecord)
                    .where(AgentBuilderIntentPlanCacheRecord.id == record.id)
                    .values(**mutation_values)
                )
                if getattr(mutation_result, "rowcount", None) != 1:
                    session.rollback()
                    return IntentPlanL2SaveResult(
                        status="unavailable",
                        receipt=None,
                        reason="cache_unavailable",
                    )
                parent_record_id = record.id
                receipt_expiry = values["expires_at"] if expired else record.expires_at
                write_kind = (
                    "expired_replacement" if expired else "unexpired_conflict"
                )
            receipt = IntentPlanL2StoredReceipt(
                parent_record_id=parent_record_id,
                expires_at=receipt_expiry,
                write_kind=write_kind,
            )
            session.commit()
            return IntentPlanL2SaveResult(
                status="stored",
                receipt=receipt,
                reason=None,
            )
        except Exception as exc:
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    pass
            if self._disable_for_schema_readiness_failure(exc):
                return None
            return IntentPlanL2SaveResult(
                status="unavailable",
                receipt=None,
                reason="cache_unavailable",
            )
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _disable_for_schema_readiness_failure(self, error: Exception) -> bool:
        """Disable only L2 after PostgreSQL reports its additive schema is absent."""
        candidates = (error, getattr(error, "orig", None))
        for candidate in candidates:
            if candidate is None:
                continue
            sqlstate = getattr(candidate, "sqlstate", None) or getattr(
                candidate, "pgcode", None
            )
            if sqlstate in _SCHEMA_READINESS_SQLSTATES:
                self._schema_available = False
                return True
        return False
