from __future__ import annotations

from uuid import uuid4

from cryptography.fernet import Fernet

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
