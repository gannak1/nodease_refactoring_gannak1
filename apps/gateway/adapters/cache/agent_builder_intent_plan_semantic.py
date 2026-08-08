from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Callable

from pgvector.sqlalchemy import Vector
from sqlalchemy import and_, literal, select
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.dialects.postgresql import insert as postgresql_insert

from apps.gateway.adapters.cache.agent_builder_intent_plan_l2 import (
    IntentPlanL2Envelope,
    IntentPlanL2EnvelopeCodec,
    IntentPlanL2EnvelopeError,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    IntentPlanL2StoredReceipt,
    IntentPlanningContext,
)
from apps.gateway.application.agent_builder.intent_semantic_cache import (
    SEMANTIC_QUERY_PROJECTION_VERSION,
    SemanticCachePolicy,
    SemanticEmbedding,
    SemanticIntentPlanCandidate,
    SemanticQueryProjectionV1,
)
from apps.shared.db.models.agent_builder import (
    AgentBuilderIntentPlanCacheRecord,
    AgentBuilderIntentPlanSemanticCacheEntry,
)


_SEMANTIC_UNIQUE_CONSTRAINT = "uq_agent_builder_semantic_cache_parent_profile_contract"


class SemanticIndexUnavailableError(RuntimeError):
    """Safe repository failure without row, vector, or provider details."""

    def __init__(self) -> None:
        super().__init__("agent_builder_semantic_index_unavailable")


class PostgresSemanticIntentPlanIndexAdapter:
    """Short-session pgvector index scoped to one organization and user."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], object],
        envelope_codec: IntentPlanL2EnvelopeCodec,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if not callable(session_factory):
            raise ValueError("invalid semantic session factory")
        if not isinstance(envelope_codec, IntentPlanL2EnvelopeCodec):
            raise ValueError("invalid semantic L2 envelope codec")
        self._session_factory = session_factory
        self._envelope_codec = envelope_codec
        self._now = now or (lambda: datetime.now(timezone.utc))

    def search(
        self,
        *,
        context: IntentPlanningContext,
        policy: SemanticCachePolicy,
        projection: SemanticQueryProjectionV1,
        embedding: SemanticEmbedding,
    ) -> tuple[SemanticIntentPlanCandidate, ...]:
        self._validate_inputs(context, policy, projection, embedding)
        now = self._aware_now()
        organization_id = context.scope._organization_id
        user_id = context.scope._actor_id
        entry = AgentBuilderIntentPlanSemanticCacheEntry
        parent = AgentBuilderIntentPlanCacheRecord
        statement = (
            select(entry, parent)
            .join(
                parent,
                and_(
                    entry.organization_id == parent.organization_id,
                    entry.intent_plan_record_id == parent.id,
                ),
            )
            .where(
                entry.organization_id == organization_id,
                entry.user_id == user_id,
                entry.generation_mode == context.generation_mode,
                entry.semantic_query_projection_version == projection.version,
                entry.embedding_profile_version == policy.embedding_profile_version,
                entry.embedding_model_version == policy.embedding_model_version,
                entry.planner_contract_version
                == context.contract_versions.planner_contract_version,
                entry.catalog_version == context.contract_versions.catalog_version,
                entry.normalizer_version
                == context.contract_versions.normalizer_version,
                entry.rehydration_contract_version
                == policy.rehydration_contract_version,
                entry.expires_at > now,
                parent.expires_at > now,
                entry.expires_at == parent.expires_at,
                parent.lookup_key_version == self._envelope_codec.lookup_key_version,
            )
            .order_by(
                entry.safe_query_embedding.cosine_distance(list(embedding.values))
            )
            .limit(policy.top_k)
        )
        session = None
        try:
            session = self._session_factory()
            rows = session.execute(statement).all()
            candidates = []
            for semantic_row, parent_row in rows:
                if not self._row_matches(
                    semantic_row,
                    parent_row,
                    context=context,
                    policy=policy,
                    projection=projection,
                    now=now,
                ):
                    continue
                try:
                    plan = self._envelope_codec.decode(
                        IntentPlanL2Envelope(
                            ciphertext=parent_row.envelope_ciphertext,
                            mac=parent_row.envelope_mac,
                            encryption_key_version=(parent_row.encryption_key_version),
                            encryption_algorithm=parent_row.encryption_algorithm,
                            envelope_version=parent_row.envelope_version,
                        ),
                        lookup_token=parent_row.lookup_token,
                    )
                except (AttributeError, IntentPlanL2EnvelopeError):
                    continue
                candidates.append(SemanticIntentPlanCandidate(plan=plan))
            return tuple(candidates[: policy.top_k])
        except Exception:
            raise SemanticIndexUnavailableError() from None
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def append(
        self,
        *,
        context: IntentPlanningContext,
        policy: SemanticCachePolicy,
        embedding: SemanticEmbedding,
        receipt: IntentPlanL2StoredReceipt,
    ) -> bool:
        if not isinstance(receipt, IntentPlanL2StoredReceipt):
            raise TypeError("invalid semantic parent receipt")
        self._validate_inputs(context, policy, None, embedding)
        now = self._aware_now()
        entry = AgentBuilderIntentPlanSemanticCacheEntry
        parent = AgentBuilderIntentPlanCacheRecord
        columns = (
            "id",
            "organization_id",
            "user_id",
            "intent_plan_record_id",
            "generation_mode",
            "semantic_query_projection_version",
            "embedding_profile_version",
            "embedding_model_version",
            "planner_contract_version",
            "catalog_version",
            "normalizer_version",
            "rehydration_contract_version",
            "safe_query_embedding",
            "created_at",
            "expires_at",
        )
        parent_fenced_values = select(
            literal(uuid.uuid4(), type_=PGUUID(as_uuid=True)),
            literal(context.scope._organization_id, type_=PGUUID(as_uuid=True)),
            literal(context.scope._actor_id, type_=PGUUID(as_uuid=True)),
            parent.id,
            literal(context.generation_mode),
            literal(SEMANTIC_QUERY_PROJECTION_VERSION),
            literal(policy.embedding_profile_version),
            literal(policy.embedding_model_version),
            literal(context.contract_versions.planner_contract_version),
            literal(context.contract_versions.catalog_version),
            literal(context.contract_versions.normalizer_version),
            literal(policy.rehydration_contract_version),
            literal(list(embedding.values), type_=Vector()),
            literal(now),
            parent.expires_at,
        ).where(
            parent.organization_id == context.scope._organization_id,
            parent.id == receipt.parent_record_id,
            parent.expires_at == receipt.expires_at,
            parent.expires_at > now,
        )
        statement = postgresql_insert(entry).from_select(
            columns,
            parent_fenced_values,
            include_defaults=False,
        )
        if receipt.write_kind in {"inserted", "unexpired_conflict"}:
            statement = statement.on_conflict_do_nothing(
                constraint=_SEMANTIC_UNIQUE_CONSTRAINT
            )
        else:
            excluded = statement.excluded
            statement = statement.on_conflict_do_update(
                constraint=_SEMANTIC_UNIQUE_CONSTRAINT,
                set_={
                    "safe_query_embedding": excluded.safe_query_embedding,
                    "created_at": excluded.created_at,
                    "expires_at": excluded.expires_at,
                },
                where=entry.expires_at < excluded.expires_at,
            )
        session = None
        try:
            session = self._session_factory()
            session.execute(statement)
            session.commit()
            return True
        except Exception:
            if session is not None:
                try:
                    session.rollback()
                except Exception:
                    pass
            raise SemanticIndexUnavailableError() from None
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception:
                    pass

    def _aware_now(self) -> datetime:
        now = self._now()
        if type(now) is not datetime or now.tzinfo is None or now.utcoffset() is None:
            raise SemanticIndexUnavailableError()
        return now

    @staticmethod
    def _validate_inputs(
        context: IntentPlanningContext,
        policy: SemanticCachePolicy,
        projection: SemanticQueryProjectionV1 | None,
        embedding: SemanticEmbedding,
    ) -> None:
        if not isinstance(context, IntentPlanningContext):
            raise TypeError("invalid semantic planning context")
        if not isinstance(policy, SemanticCachePolicy):
            raise TypeError("invalid semantic policy")
        if projection is not None and not isinstance(
            projection, SemanticQueryProjectionV1
        ):
            raise TypeError("invalid semantic projection")
        if not isinstance(embedding, SemanticEmbedding):
            raise TypeError("invalid semantic embedding")
        if len(embedding.values) != policy.embedding_dimension:
            raise ValueError("semantic embedding dimension mismatch")

    def _row_matches(
        self,
        semantic_row,
        parent_row,
        *,
        context: IntentPlanningContext,
        policy: SemanticCachePolicy,
        projection: SemanticQueryProjectionV1,
        now: datetime,
    ) -> bool:
        try:
            return bool(
                semantic_row.organization_id == context.scope._organization_id
                and parent_row.organization_id == context.scope._organization_id
                and semantic_row.user_id == context.scope._actor_id
                and semantic_row.intent_plan_record_id == parent_row.id
                and semantic_row.generation_mode == context.generation_mode
                and semantic_row.semantic_query_projection_version == projection.version
                and semantic_row.embedding_profile_version
                == policy.embedding_profile_version
                and semantic_row.embedding_model_version
                == policy.embedding_model_version
                and semantic_row.planner_contract_version
                == context.contract_versions.planner_contract_version
                and semantic_row.catalog_version
                == context.contract_versions.catalog_version
                and semantic_row.normalizer_version
                == context.contract_versions.normalizer_version
                and semantic_row.rehydration_contract_version
                == policy.rehydration_contract_version
                and semantic_row.expires_at == parent_row.expires_at
                and semantic_row.expires_at > now
                and parent_row.expires_at > now
                and parent_row.lookup_key_version
                == self._envelope_codec.lookup_key_version
            )
        except (AttributeError, TypeError):
            return False


__all__ = [
    "PostgresSemanticIntentPlanIndexAdapter",
    "SemanticIndexUnavailableError",
]
