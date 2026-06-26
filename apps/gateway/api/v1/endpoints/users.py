from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.shared.db.models.audit_log import ActorType, AuditLog
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.schemas.audit import AuditLogListResponse

router = APIRouter()


@router.get("/me/audit-logs", response_model=AuditLogListResponse)
def list_my_audit_logs(
    page: int = Query(default=1, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    query = db.query(AuditLog).filter(
        AuditLog.actor_id == current_user.id,
        AuditLog.actor_type == ActorType.USER,
    )
    items = (
        query.order_by(desc(AuditLog.occurred_at), desc(AuditLog.id))
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "total": query.count(),
        "items": [
            {
                "id": item.id,
                "occurred_at": item.occurred_at,
                "actor_id": item.actor_id,
                "actor_type": item.actor_type,
                "category": item.category,
                "action": item.action,
                "target_type": item.target_type,
                "target_id": item.target_id,
                "status": item.status,
                "request_id": (item.audit_metadata or {}).get("request_id"),
            }
            for item in items
        ],
    }
