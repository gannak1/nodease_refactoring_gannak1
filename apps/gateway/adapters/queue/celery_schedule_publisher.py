from __future__ import annotations

from typing import Any

from apps.gateway.application.deployment.schedule_models import (
    SchedulePublishRequest,
)


class CeleryScheduleTaskPublisher:
    def __init__(self, celery_app: Any) -> None:
        self.celery_app = celery_app

    def publish(self, request: SchedulePublishRequest) -> None:
        self.celery_app.send_task(
            "workflow.execute_scheduled_deployment",
            args=[str(request.claim_id)],
            task_id=request.task_id,
            retry=False,
        )
