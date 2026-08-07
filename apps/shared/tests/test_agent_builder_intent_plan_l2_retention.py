from __future__ import annotations

import pytest
from apps.shared.services.agent_builder_intent_plan_l2_retention import (
    DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT,
    AgentBuilderIntentPlanL2RetentionService,
)


def test_l2_retention_default_limit_is_bounded() -> None:
    assert DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT == 1000
    assert (
        AgentBuilderIntentPlanL2RetentionService.validate_limit(
            DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT
        )
        == DEFAULT_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT
    )


@pytest.mark.parametrize(
    "limit",
    [0, -1, True, MAX_AGENT_BUILDER_INTENT_PLAN_L2_PURGE_LIMIT + 1],
)
def test_l2_retention_rejects_unbounded_or_non_integer_batch_limits(limit) -> None:
    with pytest.raises(ValueError):
        AgentBuilderIntentPlanL2RetentionService.validate_limit(limit)
