from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.agent_builder import AgentBuilderIntentPlanCacheRecord


DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT = 1000
MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT = 5000


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
        rows = (
            db.query(AgentBuilderIntentPlanCacheRecord)
            .filter(AgentBuilderIntentPlanCacheRecord.expires_at <= cutoff)
            .order_by(AgentBuilderIntentPlanCacheRecord.expires_at.asc())
            .limit(normalized_limit)
            .all()
        )
        try:
            for row in rows:
                db.delete(row)
            db.commit()
        except Exception:
            db.rollback()
            raise
        return {
            "purged_count": len(rows),
            "limit": normalized_limit,
        }
