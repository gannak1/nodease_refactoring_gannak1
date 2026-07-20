import inspect
from typing import get_type_hints

import pytest
from pydantic import ValidationError

from apps.gateway.application.agent_builder.intent_cache import (
    CachedIntentPlanV1,
    DisabledIntentPlanCacheBoundary,
    IntentCacheKey,
    IntentNormalizationResult,
    IntentNormalizerPort,
    IntentPlanCacheBoundary,
    IntentPlanExecution,
    IntentPlanLoadResult,
    IntentPlanRehydratorPort,
    IntentPlanSaveResult,
    IntentPlanStorePort,
    IntentPlanningContext,
    IntentRehydrationResult,
)
from apps.shared.schemas.agent_builder import AgentBuilderStructuredRequest


class ExplodingContext:
    def __getattribute__(self, name):
        raise AssertionError(f"disabled boundary inspected context: {name}")


def _structured_request() -> AgentBuilderStructuredRequest:
    return AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="safe summary",
    )


def test_disabled_boundary_calls_planner_once_and_returns_same_request():
    boundary = DisabledIntentPlanCacheBoundary()
    structured = _structured_request()
    calls = 0

    def planner_call():
        nonlocal calls
        calls += 1
        return structured

    result = boundary.execute(planner_call, context=ExplodingContext())

    assert calls == 1
    assert isinstance(result, IntentPlanExecution)
    assert result.structured_request is structured
    assert result.decision.outcome == "bypass"
    assert result.decision.reason == "feature_disabled"
    with pytest.raises(ValidationError):
        result.decision.reason = "normalization_bypass"


def test_disabled_boundary_propagates_same_planner_exception_without_retry():
    boundary = DisabledIntentPlanCacheBoundary()
    failure = RuntimeError("safe planner failure")
    calls = 0

    def planner_call():
        nonlocal calls
        calls += 1
        raise failure

    with pytest.raises(RuntimeError) as captured:
        boundary.execute(planner_call)

    assert captured.value is failure
    assert calls == 1


def test_disabled_boundary_has_no_cache_dependency_constructor_parameters():
    signature = inspect.signature(DisabledIntentPlanCacheBoundary)

    assert list(signature.parameters) == []
    boundary = DisabledIntentPlanCacheBoundary()
    assert not hasattr(boundary, "normalizer")
    assert not hasattr(boundary, "store")
    assert not hasattr(boundary, "rehydrator")


def test_ports_are_runtime_checkable_narrow_protocols():
    class FakeNormalizer:
        def normalize(self, context):
            raise NotImplementedError

    class FakeStore:
        def load(self, key):
            raise NotImplementedError

        def save(self, key, plan):
            raise NotImplementedError

    class FakeRehydrator:
        def rehydrate(self, plan, context):
            raise NotImplementedError

    class FakeBoundary:
        def execute(self, planner_call, context=None):
            raise NotImplementedError

    assert isinstance(FakeNormalizer(), IntentNormalizerPort)
    assert isinstance(FakeStore(), IntentPlanStorePort)
    assert isinstance(FakeRehydrator(), IntentPlanRehydratorPort)
    assert isinstance(FakeBoundary(), IntentPlanCacheBoundary)

    assert get_type_hints(IntentNormalizerPort.normalize) == {
        "context": IntentPlanningContext,
        "return": IntentNormalizationResult,
    }
    assert get_type_hints(IntentPlanStorePort.load) == {
        "key": IntentCacheKey,
        "return": IntentPlanLoadResult,
    }
    assert get_type_hints(IntentPlanStorePort.save) == {
        "key": IntentCacheKey,
        "plan": CachedIntentPlanV1,
        "return": IntentPlanSaveResult,
    }
    assert get_type_hints(IntentPlanRehydratorPort.rehydrate) == {
        "plan": CachedIntentPlanV1,
        "context": IntentPlanningContext,
        "return": IntentRehydrationResult,
    }
