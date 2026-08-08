from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.shared.db.models.agent_builder import (
    AgentBuilderIntentPlanCacheRecord,
    AgentBuilderIntentPlanSemanticCacheEntry,
)
from sqlalchemy import delete
from sqlalchemy.orm import Session

DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT = 1000
MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT = 1000
DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN = 5
MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN = 5
_SEMANTIC_SCHEMA_READINESS_SQLSTATES = frozenset({"42P01", "42703"})


class AgentBuilderIntentPlanL2RetentionService:
    """Delete bounded expired semantic children, then their L2 parent rows."""

    @staticmethod
    def validate_limit(limit: int) -> int:
        if isinstance(limit, bool):
            raise ValueError("L2 retention purge limit must be an integer")
        try:
            normalized_limit = int(limit)
        except (TypeError, ValueError) as exc:
            raise ValueError("L2 retention purge limit must be an integer") from exc
        if not (
            1 <= normalized_limit <= MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT
        ):
            raise ValueError("L2 retention purge limit is outside the allowed range")
        return normalized_limit

    @staticmethod
    def validate_batch_count(batch_count: int) -> int:
        if isinstance(batch_count, bool):
            raise ValueError("L2 retention purge batch count must be an integer")
        try:
            normalized_count = int(batch_count)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "L2 retention purge batch count must be an integer"
            ) from exc
        if not (
            1
            <= normalized_count
            <= MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN
        ):
            raise ValueError(
                "L2 retention purge batch count is outside the allowed range"
            )
        return normalized_count

    @classmethod
    def purge(
        cls,
        db: Session,
        *,
        now: datetime | None = None,
        limit: int = DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    ) -> dict[str, Any]:
        normalized_limit = cls.validate_limit(limit)
        cutoff = now or datetime.now(timezone.utc)
        if cutoff.tzinfo is None:
            raise ValueError("L2 retention cutoff must be timezone-aware")
        try:
            semantic_purged_count = 0
            try:
                with db.begin_nested():
                    semantic_candidate_rows = (
                        db.query(AgentBuilderIntentPlanSemanticCacheEntry.id)
                        .filter(
                            AgentBuilderIntentPlanSemanticCacheEntry.expires_at
                            <= cutoff
                        )
                        .order_by(
                            AgentBuilderIntentPlanSemanticCacheEntry.expires_at.asc()
                        )
                        .limit(normalized_limit)
                        .all()
                    )
                    semantic_candidate_ids = [
                        row_id for (row_id,) in semantic_candidate_rows
                    ]
                    if semantic_candidate_ids:
                        result = db.execute(
                            delete(AgentBuilderIntentPlanSemanticCacheEntry).where(
                                AgentBuilderIntentPlanSemanticCacheEntry.id.in_(
                                    semantic_candidate_ids
                                ),
                                AgentBuilderIntentPlanSemanticCacheEntry.expires_at
                                <= cutoff,
                            )
                        )
                        semantic_purged_count = max(
                            0, int(getattr(result, "rowcount", 0) or 0)
                        )
            except Exception as exc:
                if not cls._is_semantic_schema_readiness_failure(exc):
                    raise

            parent_candidate_rows = (
                db.query(AgentBuilderIntentPlanCacheRecord.id)
                .filter(AgentBuilderIntentPlanCacheRecord.expires_at <= cutoff)
                .order_by(AgentBuilderIntentPlanCacheRecord.expires_at.asc())
                .limit(normalized_limit)
                .all()
            )
            parent_candidate_ids = [row_id for (row_id,) in parent_candidate_rows]
            parent_purged_count = 0
            if parent_candidate_ids:
                result = db.execute(
                    delete(AgentBuilderIntentPlanCacheRecord).where(
                        AgentBuilderIntentPlanCacheRecord.id.in_(
                            parent_candidate_ids
                        ),
                        AgentBuilderIntentPlanCacheRecord.expires_at <= cutoff,
                    )
                )
                parent_purged_count = max(
                    0, int(getattr(result, "rowcount", 0) or 0)
                )
            db.commit()
        except Exception:
            db.rollback()
            raise
        purged_count = semantic_purged_count + parent_purged_count
        return {
            "semantic_purged_count": semantic_purged_count,
            "parent_purged_count": parent_purged_count,
            "purged_count": purged_count,
            "limit": normalized_limit,
            "batch_full": (
                semantic_purged_count >= normalized_limit
                or parent_purged_count >= normalized_limit
            ),
        }

    @staticmethod
    def _is_semantic_schema_readiness_failure(error: Exception) -> bool:
        for candidate in (error, getattr(error, "orig", None)):
            if candidate is None:
                continue
            sqlstate = getattr(candidate, "sqlstate", None) or getattr(
                candidate, "pgcode", None
            )
            if sqlstate in _SEMANTIC_SCHEMA_READINESS_SQLSTATES:
                return True
        return False
