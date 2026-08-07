from __future__ import annotations

from collections.abc import Callable
from uuid import uuid4

import pytest

from apps.gateway.adapters.cache.agent_builder_intent_plan import (
    IntentPlanCompletionResult,
    IntentPlanLeaseAcquireResult,
    IntentPlanWaitResult,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    EphemeralCacheScope,
    IntentCacheKey,
    IntentLogicalTopology,
    IntentNormalizationResult,
    IntentPlanContractVersions,
    IntentPlanLoadResult,
    IntentPlanSaveResult,
    IntentPlanningContext,
    LogicalStepRef,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_cache.ports import (
    IntentRehydrationResult,
)
from apps.gateway.application.agent_builder.intent_cache_coordinator import (
    ColdMissRehydrationError,
    FollowerWaitAbortedError,
    RequestFenceAbortedError,
    AgentBuilderIntentCacheCoordinator,
)
from apps.shared.schemas.agent_builder import (
    AgentBuilderPlannedStep,
    AgentBuilderStructuredRequest,
)


_HEX_A = "a" * 64
_HEX_B = "b" * 64
_HEX_C = "c" * 64


def _versions() -> IntentPlanContractVersions:
    return IntentPlanContractVersions(
        normalizer_version="intent-normalizer-v1",
        cache_schema_version=1,
        planner_contract_version="agent-builder-intent-v1",
        catalog_version=3,
        canonical_text_registry_version="intent-text-v1",
        materializer_version="agent-builder-direct-edit-v1",
    )


def _context() -> IntentPlanningContext:
    return IntentPlanningContext(
        full_safe_message="입력과 응답 workflow를 만들어줘",
        workflow_context=IntentLogicalTopology(
            workflow_present=False,
            nodes=(),
            edges=(),
        ),
        planner_runtime=PlannerRuntimeFingerprint(
            provider_ref="openai",
            model_relation_fingerprint=_HEX_A,
            credential_relation_fingerprint=_HEX_B,
        ),
        generation_mode="guided_generate",
        knowledge_context_fingerprint=_HEX_C,
        contract_versions=_versions(),
        scope=EphemeralCacheScope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            selected_target_type=None,
            selected_target_id=None,
        ),
    )


def _plan() -> CachedIntentPlanV1:
    steps = (
        LogicalStepRef(capability="start_input", occurrence=1),
        LogicalStepRef(capability="answer", occurrence=1),
    )
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=("start_input", "answer"),
        logical_steps=steps,
        edit_placement=None,
        integration_actions=(),
        parameter_guidance_refs=(),
        knowledge_requirements=(),
        knowledge_placements=(),
        risk_flags=(),
        contract_versions=_versions(),
    )


def _structured(summary: str = "canonical summary") -> AgentBuilderStructuredRequest:
    return AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary=summary,
        planned_steps=[
            AgentBuilderPlannedStep(
                step_id="step_start",
                capability="start_input",
                purpose="입력을 받습니다.",
            ),
            AgentBuilderPlannedStep(
                step_id="step_answer",
                capability="answer",
                purpose="결과를 응답합니다.",
                depends_on=["step_start"],
            ),
        ],
        required_capabilities=["start_input", "answer"],
    )


class _Normalizer:
    def __init__(self, *, status: str = "eligible") -> None:
        self.status = status
        self.calls = 0

    def normalize(self, _context: IntentPlanningContext) -> IntentNormalizationResult:
        self.calls += 1
        if self.status == "eligible":
            return IntentNormalizationResult(
                status="eligible",
                intent_signature=_HEX_A,
                reason=None,
                normalizer_version="intent-normalizer-v1",
                sensitive_input_detected=False,
            )
        return IntentNormalizationResult(
            status="bypass",
            intent_signature=None,
            reason="unknown_token_sequence",
            normalizer_version="intent-normalizer-v1",
            sensitive_input_detected=False,
        )


class _Store:
    def __init__(
        self,
        *,
        loaded: IntentPlanLoadResult,
        acquired: str = "acquired",
        waited: IntentPlanWaitResult | None = None,
        saved: IntentPlanSaveResult | None = None,
        completion_status: str = "signaled_and_released",
    ) -> None:
        self.loaded = loaded
        self.acquired = acquired
        self.waited = waited or IntentPlanWaitResult(status="timeout")
        self.saved = saved or IntentPlanSaveResult(status="stored", reason=None)
        self.completion_status = completion_status
        self.load_calls = 0
        self.save_calls = 0
        self.direct_save_calls = 0
        self.acquire_calls = 0
        self.wait_calls = 0
        self.wait_kwargs = None
        self.save_lease = None
        self.completed_calls = 0
        self.released_calls = 0
        self.key_material: bytes | None = None

    def build_key(self, material: bytes) -> IntentCacheKey:
        self.key_material = material
        return IntentCacheKey(
            namespace="agent-builder:intent-plan",
            key_version="test-v1",
            digest="d" * 64,
        )

    def load(self, _key: IntentCacheKey) -> IntentPlanLoadResult:
        self.load_calls += 1
        return self.loaded

    def save_if_lease_owner(
        self,
        _key: IntentCacheKey,
        _plan: CachedIntentPlanV1,
        owner: str,
        generation: int,
    ) -> IntentPlanSaveResult:
        self.save_calls += 1
        self.save_lease = (owner, generation)
        return self.saved

    def save(
        self,
        _key: IntentCacheKey,
        _plan: CachedIntentPlanV1,
    ) -> IntentPlanSaveResult:
        self.direct_save_calls += 1
        return self.saved

    @staticmethod
    def new_owner_token() -> str:
        return "owner-token"

    def acquire_lease(self, _key: IntentCacheKey, _owner: str):
        self.acquire_calls += 1
        return IntentPlanLeaseAcquireResult(
            status=self.acquired,
            generation=(
                1 if self.acquired in {"acquired", "contended"} else None
            ),
        )

    def wait_for_value(self, _key: IntentCacheKey, _generation: int, **_kwargs):
        self.wait_calls += 1
        self.wait_kwargs = _kwargs
        return self.waited

    def complete_without_value(self, _key, _owner, _generation):
        self.completed_calls += 1
        return IntentPlanCompletionResult(status=self.completion_status)

    def release_lease(self, _key, _owner, _generation):
        self.released_calls += 1


class _Rehydrator:
    def __init__(self, result: IntentRehydrationResult) -> None:
        self.result = result
        self.calls = 0

    def rehydrate(self, _plan, _context) -> IntentRehydrationResult:
        self.calls += 1
        return self.result


_L2_SAVE_UNSET = object()


class _L2Store:
    def __init__(
        self,
        *,
        loaded: IntentPlanLoadResult | None = None,
        saved: IntentPlanSaveResult | None | object = _L2_SAVE_UNSET,
    ) -> None:
        self.loaded = loaded
        self.saved = (
            IntentPlanSaveResult(status="stored", reason=None)
            if saved is _L2_SAVE_UNSET
            else saved
        )
        self.load_calls = 0
        self.save_calls = 0
        self.materials: list[bytes] = []

    def load(
        self,
        _context: IntentPlanningContext,
        canonical_key_material: bytes,
    ) -> IntentPlanLoadResult | None:
        self.load_calls += 1
        self.materials.append(canonical_key_material)
        return self.loaded

    def save(
        self,
        _context: IntentPlanningContext,
        canonical_key_material: bytes,
        _plan: CachedIntentPlanV1,
    ) -> IntentPlanSaveResult | None:
        self.save_calls += 1
        self.materials.append(canonical_key_material)
        return self.saved


def _coordinator(
    *,
    normalizer: _Normalizer,
    store: _Store,
    rehydrator_result: IntentRehydrationResult,
    projector: Callable[[AgentBuilderStructuredRequest, IntentPlanningContext], CachedIntentPlanV1 | None] | None = None,
    diagnostic_observer=None,
    cancellation_fence=None,
    cache_io_guard=None,
    l2_store=None,
):
    rehydrators: list[_Rehydrator] = []

    def build_rehydrator(_context, _plan):
        rehydrator = _Rehydrator(rehydrator_result)
        rehydrators.append(rehydrator)
        return rehydrator

    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_factory=build_rehydrator,
        plan_projector=projector or (lambda _structured, _context: _plan()),
        diagnostic_observer=diagnostic_observer,
        cancellation_fence=cancellation_fence,
        cache_io_guard=cache_io_guard,
        l2_store=l2_store,
    )
    return coordinator, rehydrators


def _success(structured: AgentBuilderStructuredRequest | None = None):
    return IntentRehydrationResult(
        status="success",
        structured_request=structured or _structured(),
        reason=None,
    )


def _failure():
    return IntentRehydrationResult(
        status="failure",
        structured_request=None,
        reason="current_context_invalid",
    )


def test_context_absence_bypasses_every_cache_dependency_and_calls_planner_once():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("planner result")

    execution = coordinator.execute(planner, context=None)

    assert execution.structured_request.intent_summary == "planner result"
    assert execution.decision.outcome == "bypass"
    assert execution.decision.reason == "normalization_bypass"
    assert calls == 1
    assert normalizer.calls == store.load_calls == store.save_calls == 0
    assert rehydrators == []


@pytest.mark.parametrize("status", ["canceled", "stale"])
def test_request_fence_aborts_before_normalization_or_cache_lookup(status):
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="hit", plan=_plan(), reason=None)
    )
    observed = []
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
        diagnostic_observer=observed.append,
        cancellation_fence=lambda: status,
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured("must not plan")

    with pytest.raises(RequestFenceAbortedError) as captured:
        coordinator.execute(planner, _context())

    assert captured.value.status == status
    assert planner_calls == normalizer.calls == store.load_calls == 0
    assert rehydrators == []
    assert [(item.outcome, item.reason) for item in observed] == [
        ("bypass", f"request_{status}")
    ]


def test_request_fence_aborts_direct_hit_before_rehydration_or_planner():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="hit", plan=_plan(), reason=None)
    )
    statuses = iter(("active", "canceled"))
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
        cancellation_fence=lambda: next(statuses),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured("must not plan")

    with pytest.raises(RequestFenceAbortedError) as captured:
        coordinator.execute(planner, _context())

    assert captured.value.status == "canceled"
    assert normalizer.calls == store.load_calls == 1
    assert planner_calls == 0
    assert rehydrators == []

def test_normalizer_bypass_never_reads_or_writes_cache_and_calls_planner_once():
    normalizer = _Normalizer(status="bypass")
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
    )

    execution = coordinator.execute(lambda: _structured("planner result"), _context())

    assert execution.structured_request.intent_summary == "planner result"
    assert execution.decision.outcome == "bypass"
    assert execution.decision.reason == "normalization_bypass"
    assert normalizer.calls == 1
    assert store.load_calls == store.save_calls == 0
    assert rehydrators == []


def test_normalizer_bypass_rechecks_fence_before_existing_planner():
    normalizer = _Normalizer(status="bypass")
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    statuses = iter(("active", "canceled"))
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
        cancellation_fence=lambda: next(statuses),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured("must not plan")

    with pytest.raises(RequestFenceAbortedError) as captured:
        coordinator.execute(planner, _context())

    assert captured.value.status == "canceled"
    assert normalizer.calls == 1
    assert store.load_calls == store.save_calls == 0
    assert planner_calls == 0


def test_cache_unavailable_rechecks_fence_before_fail_open_planner():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(
            status="unavailable", plan=None, reason="cache_unavailable"
        )
    )
    statuses = iter(("active", "canceled"))
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
        cancellation_fence=lambda: next(statuses),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured("must not plan")

    with pytest.raises(RequestFenceAbortedError) as captured:
        coordinator.execute(planner, _context())

    assert captured.value.status == "canceled"
    assert normalizer.calls == store.load_calls == 1
    assert store.acquire_calls == store.save_calls == 0
    assert planner_calls == 0


@pytest.mark.parametrize(
    (
        "fallback_case",
        "expected_load_calls",
        "expected_acquire_calls",
        "expected_wait_calls",
        "active_fence_checks",
    ),
    [
        ("load_exception", 1, 0, 0, 1),
        ("lease_exception", 1, 1, 0, 2),
        ("lease_unavailable", 1, 1, 0, 2),
        ("follower_wait_exception", 1, 1, 1, 3),
        ("follower_timeout", 1, 1, 1, 3),
        ("follower_overflow", 1, 1, 1, 3),
    ],
)
def test_cache_induced_fallback_rechecks_fence_before_existing_planner(
    fallback_case,
    expected_load_calls,
    expected_acquire_calls,
    expected_wait_calls,
    active_fence_checks,
):
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        acquired="contended" if fallback_case.startswith("follower") else "acquired",
        waited=IntentPlanWaitResult(
            status=(
                "overflow"
                if fallback_case == "follower_overflow"
                else "timeout"
            ),
            reason=(
                "waiter_capacity_exceeded"
                if fallback_case == "follower_overflow"
                else None
            ),
        ),
    )
    if fallback_case == "load_exception":
        def load_raises(_key):
            store.load_calls += 1
            raise RuntimeError("cache unavailable")

        store.load = load_raises
    elif fallback_case == "lease_exception":
        def acquire_raises(_key, _owner):
            store.acquire_calls += 1
            raise RuntimeError("lease unavailable")

        store.acquire_lease = acquire_raises
    elif fallback_case == "lease_unavailable":
        store.acquired = "unavailable"
    elif fallback_case == "follower_wait_exception":
        def wait_raises(_key, _generation, **_kwargs):
            store.wait_calls += 1
            raise RuntimeError("wait unavailable")

        store.wait_for_value = wait_raises

    statuses = iter(("active",) * active_fence_checks + ("canceled",))
    normalizer = _Normalizer()
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
        cancellation_fence=lambda: next(statuses),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured("must not plan")

    with pytest.raises(RequestFenceAbortedError) as captured:
        coordinator.execute(planner, _context())

    assert captured.value.status == "canceled"
    assert normalizer.calls == 1
    assert store.load_calls == expected_load_calls
    assert store.acquire_calls == expected_acquire_calls
    assert store.wait_calls == expected_wait_calls
    assert planner_calls == 0


@pytest.mark.parametrize(
    (
        "fallback_case",
        "active_fence_checks",
        "expected_load_calls",
        "expected_acquire_calls",
        "expected_wait_calls",
        "expected_rehydrator_calls",
    ),
    [
        ("normalizer_exception", 1, 0, 0, 0, 0),
        ("invalid_cached_plan", 2, 1, 1, 0, 0),
        ("warm_rehydration_failure", 3, 1, 1, 0, 1),
        ("follower_rehydration_failure", 4, 1, 1, 1, 1),
    ],
)
def test_remaining_cache_induced_fallbacks_recheck_fence_before_planner(
    fallback_case,
    active_fence_checks,
    expected_load_calls,
    expected_acquire_calls,
    expected_wait_calls,
    expected_rehydrator_calls,
):
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    rehydrator_result = _success()
    if fallback_case == "normalizer_exception":
        def normalize_raises(_context):
            normalizer.calls += 1
            raise RuntimeError("normalizer unavailable")

        normalizer.normalize = normalize_raises
    elif fallback_case == "invalid_cached_plan":
        store.loaded = IntentPlanLoadResult(
            status="invalid", plan=None, reason="invalid_cached_plan"
        )
    elif fallback_case == "warm_rehydration_failure":
        store.loaded = IntentPlanLoadResult(status="hit", plan=_plan(), reason=None)
        rehydrator_result = _failure()
    elif fallback_case == "follower_rehydration_failure":
        store.loaded = IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
        store.acquired = "contended"
        store.waited = IntentPlanWaitResult(status="hit", plan=_plan(), reason=None)
        rehydrator_result = _failure()

    statuses = iter(("active",) * active_fence_checks + ("canceled",))
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=rehydrator_result,
        cancellation_fence=lambda: next(statuses),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured("must not plan")

    with pytest.raises(RequestFenceAbortedError) as captured:
        coordinator.execute(planner, _context())

    assert captured.value.status == "canceled"
    assert normalizer.calls == 1
    assert store.load_calls == expected_load_calls
    assert store.acquire_calls == expected_acquire_calls
    assert store.wait_calls == expected_wait_calls
    assert sum(item.calls for item in rehydrators) == expected_rehydrator_calls
    assert store.save_calls == planner_calls == 0

def test_warm_hit_rehydrates_without_planner_or_usage_path():
    plan = _plan()
    normalizer = _Normalizer()
    store = _Store(loaded=IntentPlanLoadResult(status="hit", plan=plan, reason=None))
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(_structured("rehydrated")),
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("planner")

    execution = coordinator.execute(planner, _context())

    assert execution.structured_request.intent_summary == "rehydrated"
    assert execution.decision.outcome == "hit"
    assert execution.decision.reason is None
    assert calls == 0
    assert normalizer.calls == store.load_calls == 1
    assert store.acquire_calls == store.save_calls == 0
    assert sum(rehydrator.calls for rehydrator in rehydrators) == 1


def test_l1_miss_l2_hit_rehydrates_then_promotes_to_l1_without_planner():
    plan = _plan()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    l2_store = _L2Store(
        loaded=IntentPlanLoadResult(status="hit", plan=plan, reason=None)
    )
    coordinator, rehydrators = _coordinator(
        normalizer=_Normalizer(),
        store=store,
        l2_store=l2_store,
        rehydrator_result=_success(_structured("rehydrated from L2")),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured("must not plan")

    execution = coordinator.execute(planner, _context())

    assert execution.structured_request.intent_summary == "rehydrated from L2"
    assert execution.decision.outcome == "hit"
    assert planner_calls == 0
    assert store.load_calls == 1
    assert store.acquire_calls == store.save_calls == 0
    assert store.direct_save_calls == 1
    assert l2_store.load_calls == 1
    assert l2_store.save_calls == 0
    assert len(l2_store.materials) == 1
    assert sum(item.calls for item in rehydrators) == 1


def test_l2_write_failure_keeps_planner_result_but_prevents_l1_store():
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    l2_store = _L2Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        saved=IntentPlanSaveResult(status="unavailable", reason="cache_unavailable"),
    )
    coordinator, _ = _coordinator(
        normalizer=_Normalizer(),
        store=store,
        l2_store=l2_store,
        rehydrator_result=_success(_structured("planner result")),
    )

    execution = coordinator.execute(lambda: _structured("planner result"), _context())

    assert execution.structured_request.intent_summary == "planner result"
    assert execution.decision.outcome == "error"
    assert execution.decision.reason == "cache_unavailable"
    assert l2_store.load_calls == l2_store.save_calls == 1
    assert store.save_calls == 0


def test_l2_safe_disabled_after_schema_failure_preserves_l1_storage():
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    l2_store = _L2Store(loaded=None, saved=None)
    coordinator, _ = _coordinator(
        normalizer=_Normalizer(),
        store=store,
        l2_store=l2_store,
        rehydrator_result=_success(_structured("planner result")),
    )

    execution = coordinator.execute(lambda: _structured("planner result"), _context())

    assert execution.decision.outcome == "miss"
    assert l2_store.load_calls == l2_store.save_calls == 1
    assert store.save_calls == 1


def test_warm_rehydration_failure_discards_hit_then_calls_planner_once():
    plan = _plan()
    normalizer = _Normalizer()
    store = _Store(loaded=IntentPlanLoadResult(status="hit", plan=plan, reason=None))
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_failure(),
        projector=lambda _structured, _context: None,
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("planner after rejected hit")

    execution = coordinator.execute(planner, _context())

    assert execution.structured_request.intent_summary == "planner after rejected hit"
    assert execution.decision.outcome == "miss"
    assert execution.decision.reason == "rehydration_failed"
    assert calls == 1
    assert store.acquire_calls == 1
    assert store.save_calls == 0


def test_owner_miss_calls_planner_once_rehydrates_then_stores():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(_structured("canonical miss")),
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("provider summary")

    execution = coordinator.execute(planner, _context())

    assert execution.structured_request.intent_summary == "canonical miss"
    assert execution.decision.outcome == "miss"
    assert execution.decision.reason == "not_found"
    assert calls == 1
    assert store.load_calls == store.acquire_calls == store.save_calls == 1
    assert store.save_lease == ("owner-token", 1)
    assert store.released_calls == 1
    assert store.completed_calls == 0
    assert sum(rehydrator.calls for rehydrator in rehydrators) == 1
    assert store.key_material is not None
    assert b"provider summary" not in store.key_material


def test_owner_cache_put_failure_signals_followers_without_waiting_for_lease_expiry():
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        saved=IntentPlanSaveResult(status="unavailable", reason="cache_unavailable"),
    )
    coordinator, _ = _coordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_result=_success(_structured("canonical miss")),
    )

    execution = coordinator.execute(
        lambda: _structured("provider summary"),
        _context(),
    )

    assert execution.structured_request.intent_summary == "canonical miss"
    assert execution.decision.outcome == "error"
    assert execution.decision.reason == "cache_unavailable"
    assert store.save_calls == 1
    assert store.completed_calls == 1
    assert store.released_calls == 0

def test_owner_cache_put_failure_releases_lease_when_completion_signal_is_unavailable():
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        saved=IntentPlanSaveResult(status="unavailable", reason="cache_unavailable"),
        completion_status="unavailable",
    )
    coordinator, _ = _coordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_result=_success(_structured("canonical miss")),
    )

    execution = coordinator.execute(
        lambda: _structured("provider summary"),
        _context(),
    )

    assert execution.decision.reason == "cache_unavailable"
    assert store.completed_calls == 1
    assert store.released_calls == 1

def test_cold_miss_rehydration_failure_never_uses_raw_planner_result_or_saves():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    observed = []
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_failure(),
        diagnostic_observer=observed.append,
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("raw provider result")

    with pytest.raises(ColdMissRehydrationError):
        coordinator.execute(planner, _context())

    assert calls == 1
    assert store.save_calls == 0
    assert store.completed_calls == 1
    assert store.released_calls == 0
    assert [(item.outcome, item.reason) for item in observed] == [
        ("error", "cold_rehydration_failed")
    ]


def test_unavailable_cache_fails_open_without_single_flight_or_rehydration():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(
            status="unavailable", plan=None, reason="cache_unavailable"
        )
    )
    coordinator, rehydrators = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("planner after cache failure")

    execution = coordinator.execute(planner, _context())

    assert execution.structured_request.intent_summary == "planner after cache failure"
    assert execution.decision.outcome == "error"
    assert execution.decision.reason == "cache_unavailable"
    assert calls == 1
    assert store.acquire_calls == store.save_calls == 0
    assert rehydrators == []


def test_follower_waits_once_then_rehydrates_value_without_planner():
    plan = _plan()
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        acquired="contended",
        waited=IntentPlanWaitResult(status="hit", plan=plan),
    )
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(_structured("follower hit")),
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("planner")

    execution = coordinator.execute(planner, _context())

    assert execution.structured_request.intent_summary == "follower hit"
    assert execution.decision.outcome == "hit"
    assert calls == 0
    assert store.wait_calls == 1
    assert store.save_calls == 0


def test_follower_timeout_calls_planner_once_without_retry_or_save():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        acquired="contended",
        waited=IntentPlanWaitResult(status="timeout"),
    )
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
    )
    calls = 0

    def planner():
        nonlocal calls
        calls += 1
        return _structured("planner after one wait")

    execution = coordinator.execute(planner, _context())

    assert execution.structured_request.intent_summary == "planner after one wait"
    assert execution.decision.outcome == "miss"
    assert calls == 1
    assert store.wait_calls == 1
    assert store.acquire_calls == 1
    assert store.save_calls == 0


def test_follower_overflow_records_allowlisted_capacity_reason():
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        acquired="contended",
        waited=IntentPlanWaitResult(
            status="overflow",
            reason="waiter_capacity_exceeded",
        ),
    )
    observed = []
    coordinator, _ = _coordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_result=_success(),
        diagnostic_observer=observed.append,
    )

    execution = coordinator.execute(lambda: _structured("overflow fallback"), _context())

    assert execution.decision.outcome == "miss"
    assert execution.decision.reason == "not_found"
    assert [(item.outcome, item.reason, item.single_flight_role) for item in observed] == [
        ("miss", "waiter_capacity_exceeded", "overflow")
    ]

def test_request_bound_follower_wait_passes_cancellation_fence_and_deadline():
    normalizer = _Normalizer()
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found"),
        acquired="contended",
        waited=IntentPlanWaitResult(status="canceled"),
    )
    observed = []
    coordinator, _ = _coordinator(
        normalizer=normalizer,
        store=store,
        rehydrator_result=_success(),
        diagnostic_observer=observed.append,
    )
    bound = coordinator.for_request(
        rehydrator_factory=lambda _context, _plan: _Rehydrator(_success()),
        cancellation_fence=lambda: "active",
        request_deadline_monotonic=123.0,
    )

    with pytest.raises(FollowerWaitAbortedError) as captured:
        bound.execute(lambda: _structured("must not plan"), _context())

    assert captured.value.status == "canceled"
    assert store.wait_calls == 1
    assert store.wait_kwargs["cancellation_fence"]() == "active"
    assert store.wait_kwargs["request_deadline_monotonic"] == 123.0
    assert [(item.outcome, item.reason) for item in observed] == [
        ("bypass", "request_canceled")
    ]


def test_cache_diagnostic_observer_receives_only_safe_contract_fields():
    plan = _plan()
    store = _Store(
        loaded=IntentPlanLoadResult(status="hit", plan=plan, reason=None),
    )
    observed = []
    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_factory=lambda _context, _plan: _Rehydrator(
            _success(_structured("rehydrated"))
        ),
        plan_projector=lambda _structured, _context: plan,
        diagnostic_observer=observed.append,
    )

    execution = coordinator.execute(lambda: _structured("provider raw"), _context())

    assert execution.decision.outcome == "hit"
    assert len(observed) == 1
    diagnostic = observed[0]
    assert diagnostic.outcome == "hit"

    assert diagnostic.reason is None
    assert diagnostic.single_flight_role == "none"
    assert diagnostic.latency_ms >= 0
    assert diagnostic.cache_schema_version == 1
    assert diagnostic.normalizer_version == "intent-normalizer-v1"
    assert "provider raw" not in repr(diagnostic)

def test_initial_transaction_guard_failure_does_not_retry_failing_planner():
    """An unavailable cache boundary must not cause the existing Planner to run twice."""
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )
    coordinator, _ = _coordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_result=_success(),
        cache_io_guard=lambda: False,
    )
    planner_calls = 0

    def planner_call():
        nonlocal planner_calls
        planner_calls += 1
        raise RuntimeError("planner failure")

    with pytest.raises(RuntimeError, match="planner failure"):
        coordinator.execute(planner_call, context=_context())
    assert planner_calls == 1
    assert store.load_calls == 0

def test_warm_rehydration_closes_session_before_fallback_lease_io():
    """A rehydration DB read must end before the warm-hit fallback acquires Redis."""
    transaction = {"open": False}
    guard_observations = []

    class TransactionAssertingStore(_Store):
        def load(self, key):
            assert not transaction["open"]
            return super().load(key)

        def acquire_lease(self, key, owner):
            assert not transaction["open"]
            return super().acquire_lease(key, owner)

    store = TransactionAssertingStore(
        loaded=IntentPlanLoadResult(status="hit", plan=_plan(), reason=None),
        acquired="unavailable",
    )

    def rehydrator_factory(_context, _plan):
        transaction["open"] = True
        return _Rehydrator(_failure())

    def cache_io_guard():
        guard_observations.append(transaction["open"])
        transaction["open"] = False
        return True

    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_factory=rehydrator_factory,
        plan_projector=lambda _structured, _context: _plan(),
        cache_io_guard=cache_io_guard,
    )
    planner_calls = 0

    def planner_call():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    execution = coordinator.execute(planner_call, context=_context())

    assert execution.decision.reason == "cache_unavailable"
    assert planner_calls == 1
    assert store.acquire_calls == 1
    assert guard_observations == [False, True]


def test_owner_rehydration_closes_session_before_save_and_release_io():
    """The owner must not save or release a Redis lease under a rehydration read."""
    transaction = {"open": False}
    guard_observations = []

    class TransactionAssertingStore(_Store):
        def load(self, key):
            assert not transaction["open"]
            return super().load(key)

        def acquire_lease(self, key, owner):
            assert not transaction["open"]
            return super().acquire_lease(key, owner)

        def save_if_lease_owner(self, key, plan, owner, generation):
            assert not transaction["open"]
            return super().save_if_lease_owner(key, plan, owner, generation)

        def release_lease(self, key, owner, generation):
            assert not transaction["open"]
            return super().release_lease(key, owner, generation)

    store = TransactionAssertingStore(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )

    def rehydrator_factory(_context, _plan):
        transaction["open"] = True
        return _Rehydrator(_success())

    def cache_io_guard():
        guard_observations.append(transaction["open"])
        transaction["open"] = False
        return True

    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_factory=rehydrator_factory,
        plan_projector=lambda _structured, _context: _plan(),
        cache_io_guard=cache_io_guard,
    )

    execution = coordinator.execute(_structured, context=_context())

    assert execution.decision.outcome == "miss"
    assert store.save_calls == 1
    assert store.released_calls == 1
    assert guard_observations == [False, False, True, False]


def test_owner_with_unclosable_rehydration_transaction_skips_terminal_redis_io():
    """A dirty current-context read must not signal or release Redis under it."""
    transaction = {"open": False}
    guard_observations = []
    store = _Store(
        loaded=IntentPlanLoadResult(status="miss", plan=None, reason="not_found")
    )

    def rehydrator_factory(_context, _plan):
        transaction["open"] = True
        return _Rehydrator(_success(_structured("canonical miss")))

    def cache_io_guard():
        guard_observations.append(transaction["open"])
        return not transaction["open"]

    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_factory=rehydrator_factory,
        plan_projector=lambda _structured, _context: _plan(),
        cache_io_guard=cache_io_guard,
    )
    planner_calls = 0

    def planner_call():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    execution = coordinator.execute(planner_call, context=_context())

    assert execution.structured_request.intent_summary == "canonical miss"
    assert execution.decision.outcome == "error"
    assert execution.decision.reason == "cache_unavailable"
    assert planner_calls == 1
    assert store.save_calls == store.completed_calls == store.released_calls == 0
    assert guard_observations == [False, False, True, True, True]

def test_unclosable_rehydration_transaction_skips_fallback_redis_io():
    """If a clean Session boundary is impossible, preserve the Planner fail-open path."""
    transaction = {"open": False}
    store = _Store(
        loaded=IntentPlanLoadResult(status="hit", plan=_plan(), reason=None)
    )

    def rehydrator_factory(_context, _plan):
        transaction["open"] = True
        return _Rehydrator(_failure())

    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_factory=rehydrator_factory,
        plan_projector=lambda _structured, _context: _plan(),
        cache_io_guard=lambda: not transaction["open"],
    )
    planner_calls = 0

    def planner_call():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    execution = coordinator.execute(planner_call, context=_context())

    assert execution.decision.reason == "cache_unavailable"
    assert planner_calls == 1
    assert store.acquire_calls == 0


def test_rehydrator_request_binding_preserves_cache_io_guard():
    """Attaching request-current rehydration must retain the service cache-I/O guard."""
    guard_calls = []
    store = _Store(
        loaded=IntentPlanLoadResult(status="hit", plan=_plan(), reason=None)
    )
    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=_Normalizer(),
        store=store,
        rehydrator_factory=lambda _context, _plan: _Rehydrator(_failure()),
        plan_projector=lambda _structured, _context: _plan(),
        cache_io_guard=lambda: guard_calls.append("checked") or True,
    )

    request_bound = coordinator.for_request(
        rehydrator_factory=lambda _context, _plan: _Rehydrator(_success())
    )
    execution = request_bound.execute(
        lambda: _structured("Planner must not be called"),
        context=_context(),
    )

    assert execution.decision.outcome == "hit"
    assert store.load_calls == 1
    assert store.save_calls == 0
