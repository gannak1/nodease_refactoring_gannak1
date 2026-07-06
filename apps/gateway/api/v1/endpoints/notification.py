import json

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.services.notification_service import (
    NOTIFICATION_EVENT_CHANGED,
    NotificationService,
    notification_channel,
)
from apps.shared.db.models.user import User
from apps.shared.db.session import get_db
from apps.shared.pubsub import get_redis_client
from apps.shared.schemas.notification import NotificationListResponse

router = APIRouter()


@router.get("", response_model=NotificationListResponse)
def list_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return NotificationListResponse(
        items=NotificationService.list_notifications(db, current_user.id)
    )


@router.get("/stream")
def stream_notifications(
    current_user: User = Depends(get_current_user),
):
    def event_generator():
        client = get_redis_client()
        pubsub = client.pubsub()
        channel = notification_channel(current_user.id)
        try:
            pubsub.subscribe(channel)
            for message in pubsub.listen():
                if message["type"] != "message":
                    continue
                event = json.loads(message["data"])
                event_type = event.get("type") or NOTIFICATION_EVENT_CHANGED
                yield f"event: {event_type}\ndata: {{}}\n\n"
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
