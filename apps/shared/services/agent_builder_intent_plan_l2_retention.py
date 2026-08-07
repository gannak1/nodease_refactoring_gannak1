from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from apps.shared.db.models.agent_builder import AgentBuilderIntentPlanCacheRecord
from sqlalchemy import delete
from sqlalchemy.orm import Session

DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT = 1000
MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT = 1000
DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN = 5
MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_BATCHES_PER_RUN = 5


class AgentBuilderIntentPlanL2RetentionService:
    """Hard-delete a bounded batch of expired L2 records without audit replay."""

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
        candidate_id_rows = (
            db.query(AgentBuilderIntentPlanCacheRecord.id)
            .filter(AgentBuilderIntentPlanCacheRecord.expires_at <= cutoff)
            .order_by(AgentBuilderIntentPlanCacheRecord.expires_at.asc())
            .limit(normalized_limit)
            .all()
        )
        candidate_ids = [row_id for (row_id,) in candidate_id_rows]
        try:
            purged_count = 0
            if candidate_ids:
                result = db.execute(
                    delete(AgentBuilderIntentPlanCacheRecord).where(
                        AgentBuilderIntentPlanCacheRecord.id.in_(candidate_ids),
                        AgentBuilderIntentPlanCacheRecord.expires_at <= cutoff,
                    )
                )
                purged_count = max(0, int(getattr(result, "rowcount", 0) or 0))
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {
            "purged_count": purged_count,
            "limit": normalized_limit,
        }
