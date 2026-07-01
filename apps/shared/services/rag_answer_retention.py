import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.shared.audit.actions import AuditAction
from apps.shared.audit.logger import record_audit
from apps.shared.db.models.knowledge import RAGAnswerRun


class RAGAnswerRetentionService:
    """만료된 standalone RAG Agent answer run을 정리한다."""

    @staticmethod
    def purge(
        db: Session,
        *,
        now: datetime | None = None,
        organization_id: uuid.UUID | None = None,
        limit: int = 1000,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        cutoff = now or datetime.now(timezone.utc)
        query = db.query(RAGAnswerRun).filter(
            RAGAnswerRun.retention_expires_at <= cutoff
        )
        if organization_id is not None:
            query = query.filter(RAGAnswerRun.organization_id == organization_id)
        rows = (
            query.order_by(RAGAnswerRun.retention_expires_at.asc())
            .limit(limit)
            .all()
        )
        would_purge_count = len(rows)

        purged_count = 0
        failed_count = 0
        if not dry_run:
            try:
                for row in rows:
                    db.delete(row)
                    purged_count += 1
                db.commit()
            except Exception:
                db.rollback()
                failed_count = len(rows)
                purged_count = 0
                RAGAnswerRetentionService._record_purge_audit(
                    organization_id=organization_id,
                    cutoff=cutoff,
                    purged_count=purged_count,
                    failed_count=failed_count,
                    retryable=True,
                    status="failure",
                )
                raise

        status = "success" if failed_count == 0 else "failure"
        if not dry_run:
            RAGAnswerRetentionService._record_purge_audit(
                organization_id=organization_id,
                cutoff=cutoff,
                purged_count=purged_count,
                failed_count=failed_count,
                retryable=failed_count > 0,
                status=status,
            )
        return {
            "cutoff": cutoff.isoformat(),
            "would_purge_count": would_purge_count,
            "purged_count": purged_count,
            "failed_count": failed_count,
            "retryable": failed_count > 0,
            "dry_run": dry_run,
        }

    @staticmethod
    def _record_purge_audit(
        *,
        organization_id: uuid.UUID | None,
        cutoff: datetime,
        purged_count: int,
        failed_count: int,
        retryable: bool,
        status: str,
    ) -> None:
        metadata: dict[str, Any] = {
            "cutoff": cutoff.isoformat(),
            "purged_count": purged_count,
            "failed_count": failed_count,
            "retryable": retryable,
            "status": status,
        }
        if organization_id is not None:
            metadata["organization_id"] = str(organization_id)
        record_audit(
            action=AuditAction.RAG_ANSWER_PURGE,
            category="system",
            actor_type="system",
            target_type="rag_answer_runs",
            target_id=None,
            status=status,
            metadata=metadata,
        )
