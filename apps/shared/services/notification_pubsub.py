import json
import logging
from typing import Any

from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    OrganizationMembership,
)
from apps.shared.db.models.user import User
from apps.shared.pubsub import get_redis_client

logger = logging.getLogger(__name__)

NOTIFICATION_EVENT_CHANGED = "notifications.changed"


def notification_channel(user_id: Any) -> str:
    return f"notifications:user:{user_id}"


def publish_notifications_changed(user_id: Any) -> None:
    try:
        get_redis_client().publish(
            notification_channel(user_id),
            json.dumps({"type": NOTIFICATION_EVENT_CHANGED}),
        )
    except Exception as error:
        logger.warning(
            "Failed to publish notification change: error_type=%s",
            type(error).__name__,
        )


def publish_notifications_changed_to_organization_managers(
    db: Any,
    organization_id: Any,
) -> None:
    try:
        rows = (
            db.query(OrganizationMembership.user_id)
            .join(User, User.id == OrganizationMembership.user_id)
            .filter(
                OrganizationMembership.organization_id == organization_id,
                OrganizationMembership.membership_state
                == ORGANIZATION_MEMBERSHIP_ACTIVE,
                OrganizationMembership.organization_auth_state
                == ORGANIZATION_AUTH_MANAGER,
                User.deactivated_at.is_(None),
            )
            .all()
        )
    except Exception as error:
        logger.warning(
            "Failed to resolve security alert notification recipients: error_type=%s",
            type(error).__name__,
        )
        return

    for row in rows:
        user_id = row[0] if isinstance(row, tuple) else row.user_id
        publish_notifications_changed(user_id)
