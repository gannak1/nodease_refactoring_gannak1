"""Fail-closed application rollback preflight for durable schedule dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import redis

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from apps.gateway.adapters.db.schedule_dispatch_repository import (  # noqa: E402
    SqlAlchemyScheduleDispatchRepository,
)
from apps.gateway.application.deployment.schedule_rollback_preflight import (  # noqa: E402
    ScheduleRollbackPreflightUseCase,
)
from apps.shared.celery_app import celery_app  # noqa: E402
from apps.shared.db.session import SessionLocal  # noqa: E402

_SCHEDULE_TASK = "workflow.execute_scheduled_deployment"
_LEGACY_DEPLOYMENT_TASK = "workflow.execute_by_deployment"
_WORKFLOW_QUEUE = b"workflow"
_REDIS_PRIORITY_SEPARATOR = b"\x06\x16"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that schedule dispatch can be rolled back without replay."
    )
    parser.add_argument("--inspect-timeout", type=float, default=5.0)
    parser.add_argument(
        "--purpose",
        choices=("activation", "rollback"),
        default="rollback",
    )
    args = parser.parse_args()
    if not 1.0 <= args.inspect_timeout <= 30.0:
        parser.error("--inspect-timeout must be between 1 and 30 seconds")
    return args


def _active_schedule_task_count(*, timeout: float, include_legacy: bool = False) -> int:
    inspector = celery_app.control.inspect(timeout=timeout)
    responses = [
        inspector.active(),
        inspector.reserved(),
        inspector.scheduled(),
    ]
    if any(response is None for response in responses):
        raise RuntimeError("worker task inspection is unavailable")

    count = 0
    for response in responses:
        for tasks in response.values():
            for task in tasks or []:
                request = task.get("request") if isinstance(task, dict) else None
                name = (
                    request.get("name")
                    if isinstance(request, dict)
                    else task.get("name") if isinstance(task, dict) else None
                )
                task_names = {_SCHEDULE_TASK}
                if include_legacy:
                    task_names.add(_LEGACY_DEPLOYMENT_TASK)
                if name in task_names:
                    count += 1
    return count


def _workflow_queue_depth(*, timeout: float) -> int:
    client = redis.Redis.from_url(
        str(celery_app.conf.broker_url),
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
    )
    try:
        depth = 0
        for key in client.scan_iter(match=b"workflow*"):
            if not (
                key == _WORKFLOW_QUEUE
                or key.startswith(_WORKFLOW_QUEUE + _REDIS_PRIORITY_SEPARATOR)
            ):
                continue
            if client.type(key) == b"list":
                depth += int(client.llen(key))
        return depth
    finally:
        client.close()


def main() -> int:
    args = _arguments()
    blockers = None
    db = None
    try:
        if args.purpose == "rollback":
            db = SessionLocal()
            blockers = ScheduleRollbackPreflightUseCase().evaluate(
                repository=SqlAlchemyScheduleDispatchRepository(db)
            )
        active_tasks = _active_schedule_task_count(
            timeout=args.inspect_timeout,
            include_legacy=args.purpose == "activation",
        )
        queued_tasks = _workflow_queue_depth(timeout=args.inspect_timeout)
    except Exception as exc:
        print(f"schedule rollback preflight failed: error_type={type(exc).__name__}")
        return 1
    finally:
        if db is not None:
            db.close()

    if (blockers is not None and not blockers.ready) or active_tasks or queued_tasks:
        print(
            "schedule dispatch transition blocked: "
            "nonterminal_claims="
            f"{blockers.nonterminal_claims if blockers is not None else 0} "
            "unreviewed_outcomes="
            f"{blockers.unreviewed_outcome_unknown_claims if blockers is not None else 0} "
            f"active_tasks={active_tasks} queued_tasks={queued_tasks}"
        )
        return 1

    print("schedule dispatch transition preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
