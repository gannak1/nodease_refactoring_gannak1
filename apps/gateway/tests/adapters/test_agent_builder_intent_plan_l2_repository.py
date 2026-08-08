from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from cryptography.fernet import Fernet
from sqlalchemy.dialects import postgresql

from apps.gateway.adapters.cache.agent_builder_intent_plan_l2 import (
    IntentPlanL2EnvelopeCodec,
    PostgresIntentPlanRepository,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    EphemeralCacheScope,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanningContext,
    LogicalStepRef,
    PlannerRuntimeFingerprint,
)
from apps.gateway.core.config import AgentBuilderIntentPlanL2Config
from apps.shared.services.credential_encryption import CredentialEncryptionService


def _context() -> IntentPlanningContext:
    return IntentPlanningContext(
        full_safe_message="입력과 응답 workflow를 만들어줘",
        workflow_context=IntentLogicalTopology(
            workflow_present=False,
            nodes=(),
            edges=(),
        ),
        planner_runtime=PlannerRuntimeFingerprint(
            provider_ref="openai",
            model_relation_fingerprint="a" * 64,
            credential_relation_fingerprint="b" * 64,
        ),
        generation_mode="guided_generate",
        knowledge_context_fingerprint="c" * 64,
        contract_versions=IntentPlanContractVersions(
            normalizer_version="intent-normalizer-v2",
            cache_schema_version=1,
            planner_contract_version="agent-builder-intent-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v1",
            materializer_version="agent-builder-direct-edit-v1",
        ),
        scope=EphemeralCacheScope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            selected_target_type=None,
            selected_target_id=None,
        ),
    )


def _plan() -> CachedIntentPlanV1:
    context = _context()
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=("start_input", "answer"),
        logical_steps=(
            LogicalStepRef(capability="start_input", occurrence=1),
            LogicalStepRef(capability="answer", occurrence=1),
        ),
        contract_versions=context.contract_versions,
    )


def _encryption() -> CredentialEncryptionService:
    return CredentialEncryptionService(
        {"l2-v1": Fernet.generate_key().decode("utf-8")},
        "l2-v1",
        subject_label="Agent Builder L2 cache",
    )


def _envelope_codec(
    encryption: CredentialEncryptionService | None = None,
) -> IntentPlanL2EnvelopeCodec:
    return IntentPlanL2EnvelopeCodec(
        hmac_key=b"l2-test-hmac-key-material-at-least-32-bytes",
        hmac_key_version="l2-hmac-v1",
        encryption=encryption or _encryption(),
        max_payload_bytes=32 * 1024,
    )


def _read_config(
    context: IntentPlanningContext,
    encryption: CredentialEncryptionService,
) -> AgentBuilderIntentPlanL2Config:
    return AgentBuilderIntentPlanL2Config(
        mode="read",
        disabled_reason=None,
        organization_allowlist=frozenset({context.scope._organization_id}),
        encryption=encryption,
    )


def _write_config(
    context: IntentPlanningContext,
    encryption: CredentialEncryptionService,
) -> AgentBuilderIntentPlanL2Config:
    return AgentBuilderIntentPlanL2Config(
        mode="write_only",
        disabled_reason=None,
        organization_allowlist=frozenset({context.scope._organization_id}),
        encryption=encryption,
    )


class _UnexpectedSessionFactory:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self):
        self.calls += 1
        raise AssertionError("L2-disabled request must not open a DB session")


def test_l2_disabled_or_outside_allowlist_does_not_touch_the_database() -> None:
    context = _context()
    factory = _UnexpectedSessionFactory()
    repository = PostgresIntentPlanRepository(
        session_factory=factory,
        envelope_codec=_envelope_codec(),
        config=AgentBuilderIntentPlanL2Config(
            mode="disabled",
            disabled_reason="feature_disabled",
        ),
    )

    assert repository.load(context, b"canonical-material") is None
    assert repository.save(context, b"canonical-material", _plan()) is None
    assert factory.calls == 0


class _MissingL2SchemaError(Exception):
    pgcode = "42P01"


class _UnavailableL2DatabaseError(Exception):
    pgcode = "08006"


class _FailingSession:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.closed = False

    def execute(self, _statement):
        raise self._error

    def close(self) -> None:
        self.closed = True


class _FailingSessionFactory:
    def __init__(self, error: Exception) -> None:
        self._error = error
        self.calls = 0

    def __call__(self) -> _FailingSession:
        self.calls += 1
        return _FailingSession(self._error)


class _ScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value


class _InsertResult:
    def __init__(self, row) -> None:
        self._row = row

    def first(self):
        return self._row


class _RecordingSession:
    def __init__(
        self,
        *,
        existing=None,
        inserted=None,
        loser_existing=None,
        rowcount: int = 1,
    ) -> None:
        self._existing = existing
        self._inserted = inserted
        self._loser_existing = loser_existing
        self._rowcount = rowcount
        self.statements = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement):
        self.statements.append(statement)
        if len(self.statements) == 1:
            return _ScalarResult(self._existing)
        if self._existing is not None:
            return SimpleNamespace(rowcount=self._rowcount)
        if len(self.statements) == 2:
            return _InsertResult(self._inserted)
        return _ScalarResult(self._loser_existing)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_l2_unexpired_conflict_returns_locked_parent_receipt_and_preserves_expiry() -> None:
    context = _context()
    encryption = _encryption()
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    parent = SimpleNamespace(
        id=uuid4(),
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
    )
    session = _RecordingSession(existing=parent)
    repository = PostgresIntentPlanRepository(
        session_factory=lambda: session,
        envelope_codec=_envelope_codec(encryption),
        config=_write_config(context, encryption),
        now=lambda: now,
    )

    result = repository.save(context, b"canonical-material", _plan())

    assert result is not None
    assert result.status == "stored"
    assert result.receipt is not None
    assert result.receipt.parent_record_id == parent.id
    assert result.receipt.expires_at == parent.expires_at
    assert result.receipt.write_kind == "unexpired_conflict"
    assert session.committed is True
    assert session.closed is True
    select_sql = str(session.statements[0].compile(dialect=postgresql.dialect()))
    update_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert "FOR UPDATE" in select_sql
    assert "UPDATE agent_builder_intent_plan_cache_records" in update_sql
    assert "created_at" not in update_sql
    assert "expires_at" not in update_sql


def test_l2_expired_conflict_returns_replacement_receipt_and_new_expiry() -> None:
    context = _context()
    encryption = _encryption()
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    parent = SimpleNamespace(
        id=uuid4(),
        created_at=now - timedelta(days=31),
        expires_at=now - timedelta(days=1),
    )
    session = _RecordingSession(existing=parent)
    repository = PostgresIntentPlanRepository(
        session_factory=lambda: session,
        envelope_codec=_envelope_codec(encryption),
        config=_write_config(context, encryption),
        now=lambda: now,
    )

    result = repository.save(context, b"canonical-material", _plan())

    assert result is not None
    assert result.status == "stored"
    assert result.receipt is not None
    assert result.receipt.parent_record_id == parent.id
    assert result.receipt.expires_at == now + timedelta(days=30)
    assert result.receipt.write_kind == "expired_replacement"
    update_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert "created_at" in update_sql
    assert "expires_at" in update_sql


def test_l2_missing_row_uses_returning_receipt_without_post_commit_read() -> None:
    context = _context()
    encryption = _encryption()
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    parent_id = uuid4()
    expiry = now + timedelta(days=30)
    session = _RecordingSession(inserted=(parent_id, expiry))
    repository = PostgresIntentPlanRepository(
        session_factory=lambda: session,
        envelope_codec=_envelope_codec(encryption),
        config=_write_config(context, encryption),
        now=lambda: now,
    )

    result = repository.save(context, b"canonical-material", _plan())

    assert result is not None
    assert result.status == "stored"
    assert result.receipt is not None
    assert result.receipt.parent_record_id == parent_id
    assert result.receipt.expires_at == expiry
    assert result.receipt.write_kind == "inserted"
    assert len(session.statements) == 2
    insert_sql = str(session.statements[1].compile(dialect=postgresql.dialect()))
    assert "ON CONFLICT" in insert_sql
    assert "DO NOTHING" in insert_sql
    assert "RETURNING" in insert_sql


def test_l2_zero_row_upsert_does_not_report_a_durable_store() -> None:
    context = _context()
    encryption = _encryption()
    now = datetime(2026, 8, 8, tzinfo=timezone.utc)
    parent = SimpleNamespace(
        id=uuid4(),
        created_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=29),
    )
    session = _RecordingSession(existing=parent, rowcount=0)
    repository = PostgresIntentPlanRepository(
        session_factory=lambda: session,
        envelope_codec=_envelope_codec(encryption),
        config=_write_config(context, encryption),
        now=lambda: now,
    )

    result = repository.save(context, b"canonical-material", _plan())

    assert result is not None
    assert result.status == "unavailable"
    assert session.committed is False
    assert session.rolled_back is True
    assert session.closed is True


def test_l2_missing_schema_safely_disables_l2_without_retrying_db_io() -> None:
    context = _context()
    encryption = _encryption()
    factory = _FailingSessionFactory(_MissingL2SchemaError())
    repository = PostgresIntentPlanRepository(
        session_factory=factory,
        envelope_codec=_envelope_codec(encryption),
        config=_read_config(context, encryption),
    )

    assert repository.load(context, b"canonical-material") is None
    assert repository.save(context, b"canonical-material", _plan()) is None
    assert factory.calls == 1


def test_l2_database_failure_is_not_treated_as_schema_safe_disabled() -> None:
    context = _context()
    encryption = _encryption()
    factory = _FailingSessionFactory(_UnavailableL2DatabaseError())
    repository = PostgresIntentPlanRepository(
        session_factory=factory,
        envelope_codec=_envelope_codec(encryption),
        config=_read_config(context, encryption),
    )

    load_result = repository.load(context, b"canonical-material")
    save_result = repository.save(context, b"canonical-material", _plan())

    assert load_result is not None
    assert load_result.status == "unavailable"
    assert save_result is not None
    assert save_result.status == "unavailable"
    assert factory.calls == 2
