from __future__ import annotations

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


class _RecordingSession:
    def __init__(self, *, rowcount: int = 1) -> None:
        self._rowcount = rowcount
        self.statement = None
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(rowcount=self._rowcount)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


def test_l2_same_key_write_replaces_invalid_or_expired_row_without_extending_retention() -> None:
    context = _context()
    encryption = _encryption()
    session = _RecordingSession()
    repository = PostgresIntentPlanRepository(
        session_factory=lambda: session,
        envelope_codec=_envelope_codec(encryption),
        config=_write_config(context, encryption),
    )

    result = repository.save(context, b"canonical-material", _plan())

    assert result is not None
    assert result.status == "stored"
    assert session.committed is True
    assert session.closed is True
    assert session.statement is not None
    statement_sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert "DO UPDATE SET" in statement_sql
    assert "DO NOTHING" not in statement_sql
    assert "envelope_ciphertext = excluded.envelope_ciphertext" in statement_sql
    assert "created_at = CASE WHEN" in statement_sql
    assert "expires_at = CASE WHEN" in statement_sql


def test_l2_zero_row_upsert_does_not_report_a_durable_store() -> None:
    context = _context()
    encryption = _encryption()
    session = _RecordingSession(rowcount=0)
    repository = PostgresIntentPlanRepository(
        session_factory=lambda: session,
        envelope_codec=_envelope_codec(encryption),
        config=_write_config(context, encryption),
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
