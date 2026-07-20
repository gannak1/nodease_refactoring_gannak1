from __future__ import annotations

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CacheBoundaryDecision,
    IntentPlanningContext,
)
from apps.gateway.application.agent_builder.intent_cache.ports import (
    IntentPlanExecution,
    PlannerCall,
)


class DisabledIntentPlanCacheBoundary:
    __slots__ = ()

    def execute(
        self,
        planner_call: PlannerCall,
        context: IntentPlanningContext | None = None,
    ) -> IntentPlanExecution:
        del context
        structured_request = planner_call()
        return IntentPlanExecution(
            structured_request=structured_request,
            decision=CacheBoundaryDecision(
                outcome="bypass",
                plan=None,
                reason="feature_disabled",
            ),
        )
