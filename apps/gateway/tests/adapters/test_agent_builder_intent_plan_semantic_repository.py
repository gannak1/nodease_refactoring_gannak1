from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from sqlalchemy.dialects import postgresql

from apps.gateway.adapters.cache.agent_builder_intent_plan_l2 import (
    IntentPlanL2EnvelopeCodec,
)
from apps.gateway.adapters.cache.agent_builder_intent_plan_semantic import (
    PostgresSemanticIntentPlanIndexAdapter,
    SemanticIndexUnavailableError,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    EphemeralCacheScope,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanL2StoredReceipt,
    IntentPlanningContext,
    LogicalStepRef,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_semantic_cache import (
    SemanticCachePolicy,
    SemanticEmbedding,
    SemanticQueryProjectionBuilder,
)
from apps.shared.services.credential_encryption import CredentialEncryptionService


_NOW = datetime(2026, 8, 8, tzinfo=timezone.utc)


def _versions() -> IntentPlanContractVersions:
    return IntentPlanContractVersions(
        normalizer_version="intent-normalizer-v2",
        cache_schema_version=1,
        planner_contract_version="agent-builder-intent-v1",
        catalog_version=3,
        canonical_text_registry_version="intent-text-v1",
        materializer_version="agent-builder-direct-edit-v1",
    )


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
        contract_versions=_versions(),
        scope=EphemeralCacheScope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            selected_target_type=None,
            selected_target_id=None,
        ),
    )


def _plan() -> CachedIntentPlanV1:
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=("start_input", "answer"),
        logical_steps=(
            LogicalStepRef(capability="start_input", occurrence=1),
            LogicalStepRef(capability="answer", occurrence=1),
        ),
        contract_versions=_versions(),
    )


def _codec() -> IntentPlanL2EnvelopeCodec:
    encryption = CredentialEncryptionService(
        {"l2-v1": Fernet.generate_key().decode("utf-8")},
        "l2-v1",
        subject_label="Agent Builder L2 cache",
    )
    return IntentPlanL2EnvelopeCodec(
        hmac_key=b"l2-test-hmac-key-material-at-least-32-bytes",
        hmac_key_version="l2-hmac-v1",
        encryption=encryption,
        max_payload_bytes=32 * 1024,
    )


def _policy() -> SemanticCachePolicy:
    return SemanticCachePolicy(
        assist_enabled=True,
        planner_free_serving_enabled=False,
        embedding_profile_version="agent-builder-semantic-profile-v1",
        embedding_model_version="test-model-v1",
        embedding_dimension=2,
        top_k=3,
        rehydration_contract_version="agent-builder-direct-edit-v1",
    )


def _parent(codec: IntentPlanL2EnvelopeCodec, *, organization_id, expires_at):
    lookup_token = "f" * 64
    envelope = codec.encode(_plan(), lookup_token=lookup_token)
    return SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        lookup_key_version=codec.lookup_key_version,
        lookup_token=lookup_token,
        envelope_ciphertext=envelope.ciphertext,
        envelope_mac=envelope.mac,
        encryption_key_version=envelope.encryption_key_version,
        encryption_algorithm=envelope.encryption_algorithm,
        envelope_version=envelope.envelope_version,
        expires_at=expires_at,
    )


def _entry(context, parent, *, user_id=None, organization_id=None, **overrides):
    values = {
        "organization_id": organization_id or context.scope._organization_id,
        "user_id": user_id or context.scope._actor_id,
        "intent_plan_record_id": parent.id,
        "generation_mode": context.generation_mode,
        "semantic_query_projection_version": "semantic-query-projection-v1",
        "embedding_profile_version": _policy().embedding_profile_version,
        "embedding_model_version": _policy().embedding_model_version,
        "planner_contract_version": context.contract_versions.planner_contract_version,
        "catalog_version": context.contract_versions.catalog_version,
        "normalizer_version": context.contract_versions.normalizer_version,
        "rehydration_contract_version": _policy().rehydration_contract_version,
        "expires_at": parent.expires_at,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


class _RowsResult:
    def __init__(self, rows) -> None:
        self._rows = rows

    def all(self):
        return self._rows


class _SearchSession:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statement = None
        self.closed = False

    def execute(self, statement):
        self.statement = statement
        return _RowsResult(self.rows)

    def close(self) -> None:
        self.closed = True


def test_semantic_search_sql_filters_scope_versions_parent_expiry_before_top_k() -> (
    None
):
    context = _context()
    codec = _codec()
    parent = _parent(
        codec,
        organization_id=context.scope._organization_id,
        expires_at=_NOW + timedelta(days=1),
    )
    valid = _entry(context, parent)
    other_user = _entry(context, parent, user_id=uuid4())
    wrong_version = _entry(context, parent, normalizer_version="other-v1")
    session = _SearchSession(
        ((other_user, parent), (wrong_version, parent), (valid, parent))
    )
    adapter = PostgresSemanticIntentPlanIndexAdapter(
        session_factory=lambda: session,
        envelope_codec=codec,
        now=lambda: _NOW,
    )
    projection = SemanticQueryProjectionBuilder().build(context.full_safe_message)
    assert projection is not None

    candidates = adapter.search(
        context=context,
        policy=_policy(),
        projection=projection,
        embedding=SemanticEmbedding(values=(0.25, 0.75)),
    )

    assert len(candidates) == 1
    assert candidates[0].plan == _plan()
    assert session.closed is True
    statement_sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert (
        "agent_builder_intent_plan_semantic_cache_entries.organization_id"
        in statement_sql
    )
    assert "agent_builder_intent_plan_semantic_cache_entries.user_id" in statement_sql
    assert (
        "agent_builder_intent_plan_semantic_cache_entries.generation_mode"
        in statement_sql
    )
    assert (
        "agent_builder_intent_plan_semantic_cache_entries.expires_at >" in statement_sql
    )
    assert "agent_builder_intent_plan_cache_records.expires_at >" in statement_sql
    assert (
        "agent_builder_intent_plan_semantic_cache_entries.expires_at = agent_builder_intent_plan_cache_records.expires_at"
        in statement_sql
    )
    assert "ORDER BY" in statement_sql
    assert "LIMIT" in statement_sql


class _MutationSession:
    def __init__(self, *, rowcount: int = 1) -> None:
        self.rowcount = rowcount
        self.statement = None
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def execute(self, statement):
        self.statement = statement
        return SimpleNamespace(rowcount=self.rowcount)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize(
    ("write_kind", "expected_conflict"),
    [
        ("inserted", "DO NOTHING"),
        ("unexpired_conflict", "DO NOTHING"),
        ("expired_replacement", "DO UPDATE SET"),
    ],
)
def test_semantic_append_is_parent_fenced_and_write_kind_controls_conflict(
    write_kind: str,
    expected_conflict: str,
) -> None:
    context = _context()
    codec = _codec()
    session = _MutationSession()
    adapter = PostgresSemanticIntentPlanIndexAdapter(
        session_factory=lambda: session,
        envelope_codec=codec,
        now=lambda: _NOW,
    )
    receipt = IntentPlanL2StoredReceipt(
        parent_record_id=uuid4(),
        expires_at=_NOW + timedelta(days=30),
        write_kind=write_kind,
    )

    stored = adapter.append(
        context=context,
        policy=_policy(),
        embedding=SemanticEmbedding(values=(0.25, 0.75)),
        receipt=receipt,
    )

    assert stored is True
    assert session.committed is True
    statement_sql = str(session.statement.compile(dialect=postgresql.dialect()))
    assert (
        "INSERT INTO agent_builder_intent_plan_semantic_cache_entries" in statement_sql
    )
    assert "FROM agent_builder_intent_plan_cache_records" in statement_sql
    assert "agent_builder_intent_plan_cache_records.organization_id" in statement_sql
    assert "agent_builder_intent_plan_cache_records.id" in statement_sql
    assert "agent_builder_intent_plan_cache_records.expires_at" in statement_sql
    assert expected_conflict in statement_sql
    if write_kind == "expired_replacement":
        assert "expires_at < excluded.expires_at" in statement_sql


class _MissingSemanticSchemaError(Exception):
    pgcode = "42P01"


class _FailingSearchSession(_SearchSession):
    def execute(self, _statement):
        raise _MissingSemanticSchemaError()


def test_semantic_schema_readiness_is_reprobed_without_process_lifetime_disable() -> (
    None
):
    context = _context()
    codec = _codec()
    good_session = _SearchSession(())
    sessions = iter((_FailingSearchSession(()), good_session))
    adapter = PostgresSemanticIntentPlanIndexAdapter(
        session_factory=lambda: next(sessions),
        envelope_codec=codec,
        now=lambda: _NOW,
    )
    projection = SemanticQueryProjectionBuilder().build(context.full_safe_message)
    assert projection is not None
    kwargs = {
        "context": context,
        "policy": _policy(),
        "projection": projection,
        "embedding": SemanticEmbedding(values=(0.25, 0.75)),
    }

    with pytest.raises(SemanticIndexUnavailableError):
        adapter.search(**kwargs)
    assert adapter.search(**kwargs) == ()
    assert good_session.closed is True
