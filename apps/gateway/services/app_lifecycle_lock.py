from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.app import App


def lock_app_for_lifecycle(
    db: Session,
    app_id: Any,
    *,
    organization_id: Any | None = None,
) -> App | None:
    """Serialize commands that can change an App's primary or deployment pointers."""
    query = db.query(App).filter(App.id == app_id)
    if organization_id is not None:
        query = query.filter(App.organization_id == organization_id)
    return query.with_for_update().first()
