"""배포 후 운영 실행과 모델 라우팅 policy refresh를 연결하는 lifecycle helper."""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


OPERATIONAL_TRIGGER_MODES = {"api", "webhook", "scheduler", "app"}


@dataclass(frozen=True)
class PolicyRunEventOutcome:
    should_enqueue_refresh: bool


class ModelRoutingPolicyLifecycleService:
    """DB 저장소가 event를 만들었는지에 따라 policy state만 전이한다."""

    @staticmethod
    def is_eligible_operational_run(run: Any) -> bool:
        deployment_id = getattr(run, "deployment_id", None)
        trigger_mode = getattr(run, "trigger_mode", None)
        normalized_trigger = str(getattr(trigger_mode, "value", trigger_mode) or "").lower()
        return bool(deployment_id) and normalized_trigger in OPERATIONAL_TRIGGER_MODES

    @staticmethod
    def apply_run_event(policy: Any, *, event_was_created: bool) -> PolicyRunEventOutcome:
        if not event_was_created or not bool(getattr(policy, "enabled", False)):
            return PolicyRunEventOutcome(should_enqueue_refresh=False)

        policy.eligible_runs_since_last_refresh = int(
            getattr(policy, "eligible_runs_since_last_refresh", 0) or 0
        ) + 1
        threshold = max(5, min(100, int(getattr(policy, "refresh_every_runs", 20) or 20)))
        already_requested = getattr(policy, "refresh_requested_at", None) is not None
        if policy.eligible_runs_since_last_refresh < threshold or already_requested:
            return PolicyRunEventOutcome(should_enqueue_refresh=False)

        policy.status = "refreshing"
        policy.refresh_requested_at = datetime.now(timezone.utc)
        return PolicyRunEventOutcome(should_enqueue_refresh=True)

    @staticmethod
    def apply_refresh_result(
        policy: Any,
        *,
        status: str,
        proposed_policy: dict[str, Any],
        policy_version: str | None,
    ) -> None:
        policy.last_refresh_result = status
        if status == "applied":
            policy.active_policy = proposed_policy
            policy.pending_policy = None
            policy.policy_version = policy_version
            policy.status = "active"
            return

        if status == "pending_review":
            policy.pending_policy = proposed_policy
            policy.status = "pending_review"
            return

        # kept_current와 failed는 기존 active policy를 그대로 실행한다.
        policy.status = "active" if getattr(policy, "active_policy", None) else "collecting"
