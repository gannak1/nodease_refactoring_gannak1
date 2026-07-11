"""Fail-closed application rollback preflight for durable schedule dispatch."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Verify that schedule dispatch can be rolled back without replay."
    )
    parser.add_argument("--inspect-timeout", type=float, default=5.0)
    args = parser.parse_args()
    if not 1.0 <= args.inspect_timeout <= 30.0:
        parser.error("--inspect-timeout must be between 1 and 30 seconds")
    return args


def _active_schedule_task_count(*, timeout: float) -> int:
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
                if name == _SCHEDULE_TASK:
                    count += 1
    return count


def main() -> int:
    args = _arguments()
    db = SessionLocal()
    try:
        blockers = ScheduleRollbackPreflightUseCase().evaluate(
            repository=SqlAlchemyScheduleDispatchRepository(db)
        )
        active_tasks = _active_schedule_task_count(timeout=args.inspect_timeout)
    except Exception as exc:
        print(f"schedule rollback preflight failed: error_type={type(exc).__name__}")
        return 1
    finally:
        db.close()

    if not blockers.ready or active_tasks:
        print(
            "schedule rollback blocked: "
            f"nonterminal_claims={blockers.nonterminal_claims} "
            "unreviewed_outcomes="
            f"{blockers.unreviewed_outcome_unknown_claims} "
            f"active_tasks={active_tasks}"
        )
        return 1

    print("schedule rollback preflight passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
