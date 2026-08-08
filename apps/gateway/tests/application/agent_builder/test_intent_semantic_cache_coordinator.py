from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    EphemeralCacheScope,
    IntentCacheKey,
    IntentLogicalTopology,
    IntentNormalizationResult,
    IntentPlanContractVersions,
    IntentPlanL2SaveResult,
    IntentPlanL2StoredReceipt,
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
    AgentBuilderIntentCacheCoordinator,
    RequestFenceAbortedError,
    SemanticTransactionBoundaryError,
)
from apps.gateway.application.agent_builder.intent_semantic_cache import (
    SemanticCachePolicy,
    SemanticEmbedding,
    SemanticExternalCallBinding,
    SemanticExternalCallAdmissionResult,
    SemanticIntentPlanCandidate,
    SemanticQueryProjectionBuilder,
    SemanticVerificationResult,
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


def _context(
    *,
    message: str = "입력과 응답 workflow를 만들어줘",
    workflow_present: bool = False,
    selected_target: bool = False,
) -> IntentPlanningContext:
    return IntentPlanningContext(
        full_safe_message=message,
        workflow_context=IntentLogicalTopology(
            workflow_present=workflow_present,
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
            selected_target_type="selected_node" if selected_target else None,
            selected_target_id="opaque-target" if selected_target else None,
        ),
    )


def _plan(*, eligible: bool = True) -> CachedIntentPlanV1:
    steps = (
        LogicalStepRef(capability="start_input", occurrence=1),
        LogicalStepRef(capability="answer", occurrence=1),
    )
    if eligible:
        request_type = "new_workflow"
        draft_mode = "new_workflow"
    else:
        request_type = "modify_workflow"
        draft_mode = "replace_workflow"
    return CachedIntentPlanV1(
        schema_version=1,
        request_type=request_type,
        draft_mode=draft_mode,
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


def _structured(summary: str = "planner result") -> AgentBuilderStructuredRequest:
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
    def normalize(self, _context):
        return IntentNormalizationResult(
            status="eligible",
            intent_signature=_HEX_A,
            reason=None,
            normalizer_version="intent-normalizer-v1",
            sensitive_input_detected=False,
        )


class _Store:
    def __init__(self, loaded: IntentPlanLoadResult) -> None:
        self.loaded = loaded
        self.load_calls = 0
        self.save_calls = 0
        self.acquire_calls = 0

    def build_key(self, _material: bytes) -> IntentCacheKey:
        return IntentCacheKey(
            namespace="agent-builder:intent-plan",
            key_version="test-v1",
            digest="d" * 64,
        )

    def load(self, _key):
        self.load_calls += 1
        return self.loaded

    def save(self, _key, _plan):
        self.save_calls += 1
        return IntentPlanSaveResult(status="stored", reason=None)

    def save_if_lease_owner(self, _key, _plan, _owner, _generation):
        self.save_calls += 1
        return IntentPlanSaveResult(status="stored", reason=None)

    @staticmethod
    def new_owner_token() -> str:
        return "owner-token"

    def acquire_lease(self, _key, _owner):
        self.acquire_calls += 1
        return SimpleNamespace(status="acquired", generation=1)

    @staticmethod
    def complete_without_value(_key, _owner, _generation):
        return SimpleNamespace(status="signaled_and_released")

    @staticmethod
    def release_lease(_key, _owner, _generation):
        return None


class _L2Store:
    def __init__(self, loaded: IntentPlanLoadResult | None) -> None:
        self.loaded = loaded
        self.load_calls = 0
        self.save_calls = 0
        self.save_result = IntentPlanL2SaveResult(
            status="stored",
            receipt=IntentPlanL2StoredReceipt(
                parent_record_id=uuid4(),
                expires_at=datetime(2026, 9, 7, tzinfo=timezone.utc),
                write_kind="inserted",
            ),
            reason=None,
        )

    def load(self, _context, _material):
        self.load_calls += 1
        return self.loaded

    def save(self, _context, _material, _plan):
        self.save_calls += 1
        return self.save_result


class _EmbeddingProvider:
    def __init__(self, *, error: bool = False, on_embed=None) -> None:
        self.error = error
        self.on_embed = on_embed
        self.calls = 0
        self.bindings = []

    def embed(self, _projection, *, binding):
        self.calls += 1
        self.bindings.append(binding)
        if self.on_embed is not None:
            self.on_embed()
        if self.error:
            raise RuntimeError("provider unavailable")
        return SemanticEmbedding(values=(0.25, 0.75))


class _Admission:
    def __init__(self, status: str = "admitted") -> None:
        self.status = status
        self.calls = 0
        self.purposes = []
        self.bindings = []

    def authorize(self, *, context, policy, purpose):
        self.calls += 1
        self.purposes.append(purpose)
        binding = None
        if self.status == "admitted":
            binding = SemanticExternalCallBinding(
                purpose=purpose,
            )
            self.bindings.append(binding)
        return SemanticExternalCallAdmissionResult(
            status=self.status,
            binding=binding,
        )


class _Index:
    def __init__(
        self,
        candidates=(),
        *,
        error: bool = False,
        append_error: bool = False,
    ) -> None:
        self.candidates = tuple(candidates)
        self.error = error
        self.append_error = append_error
        self.search_calls = 0
        self.append_calls = 0
        self.search_context = None

    def search(self, *, context, policy, projection, embedding):
        self.search_calls += 1
        self.search_context = (context, policy, projection, embedding)
        if self.error:
            raise RuntimeError("vector repository unavailable")
        return self.candidates

    def append(self, *, context, policy, embedding, receipt):
        self.append_calls += 1
        if self.append_error:
            raise RuntimeError("vector append unavailable")
        return True


class _Verifier:
    def __init__(
        self,
        status: str = "verified",
        *,
        provider_call_free: bool = True,
        on_verify=None,
    ) -> None:
        self.status = status
        self.provider_call_free = provider_call_free
        self.on_verify = on_verify
        self.calls = 0
        self.bindings = []

    def verify(self, *, projection, candidate, context, binding):
        self.calls += 1
        self.bindings.append(binding)
        if self.on_verify is not None:
            self.on_verify()
        return SemanticVerificationResult(status=self.status)


def _policy(*, serving: bool = False) -> SemanticCachePolicy:
    return SemanticCachePolicy(
        assist_enabled=True,
        planner_free_serving_enabled=serving,
        embedding_profile_version="agent-builder-semantic-profile-v1",
        embedding_model_version="test-model-v1",
        embedding_dimension=2,
        top_k=3,
        rehydration_contract_version="agent-builder-direct-edit-v1",
    )


def _coordinator(
    *,
    l1: IntentPlanLoadResult,
    l2: IntentPlanLoadResult | None,
    candidates=(),
    serving: bool = False,
    verifier_status: str = "verified",
    verifier_provider_call_free: bool = True,
    embedding_error: bool = False,
    index_error: bool = False,
    append_error: bool = False,
    admission_status: str = "admitted",
    rehydration_statuses: tuple[str, ...] = ("success", "success"),
    cache_io_guard=None,
    cancellation_fence=None,
    embedding_hook=None,
    verifier_hook=None,
    rehydration_hook=None,
):
    store = _Store(l1)
    l2_store = _L2Store(l2)
    embedding = _EmbeddingProvider(error=embedding_error, on_embed=embedding_hook)
    admission = _Admission(admission_status)
    index = _Index(candidates, error=index_error, append_error=append_error)
    verifier = _Verifier(
        verifier_status,
        provider_call_free=verifier_provider_call_free,
        on_verify=verifier_hook,
    )
    statuses = iter(rehydration_statuses)

    def rehydrator_factory(_context, _plan):
        status = next(statuses, "success")

        class Rehydrator:
            def rehydrate(self, _plan, _context):
                if rehydration_hook is not None:
                    rehydration_hook()
                if status == "success":
                    return IntentRehydrationResult(
                        status="success",
                        structured_request=_structured("rehydrated"),
                        reason=None,
                    )
                return IntentRehydrationResult(
                    status="failure",
                    structured_request=None,
                    reason="current_context_invalid",
                )

        return Rehydrator()

    coordinator = AgentBuilderIntentCacheCoordinator(
        normalizer=_Normalizer(),
        store=store,
        l2_store=l2_store,
        rehydrator_factory=rehydrator_factory,
        plan_projector=lambda _structured, _context: _plan(),
        cache_io_guard=cache_io_guard,
        cancellation_fence=cancellation_fence,
        semantic_policy=_policy(serving=serving),
        semantic_projection_builder=SemanticQueryProjectionBuilder(),
        semantic_external_call_admission=admission,
        semantic_embedding_provider=embedding,
        semantic_index=index,
        semantic_verifier=verifier,
    )
    return coordinator, store, l2_store, admission, embedding, index, verifier


def _miss() -> IntentPlanLoadResult:
    return IntentPlanLoadResult(status="miss", plan=None, reason="not_found")


def test_l1_hit_does_not_call_l2_or_semantic_dependencies() -> None:
    coordinator, _store, l2, admission, embedding, index, verifier = _coordinator(
        l1=IntentPlanLoadResult(status="hit", plan=_plan(), reason=None),
        l2=_miss(),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    result = coordinator.execute(planner, _context())

    assert result.decision.outcome == "hit"
    assert planner_calls == l2.load_calls == 0
    assert (
        admission.calls == embedding.calls == index.search_calls == verifier.calls == 0
    )


def test_l2_hit_does_not_call_semantic_dependencies() -> None:
    coordinator, _store, l2, admission, embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=IntentPlanLoadResult(status="hit", plan=_plan(), reason=None),
    )

    result = coordinator.execute(lambda: _structured(), _context())

    assert result.decision.outcome == "hit"
    assert l2.load_calls == 1
    assert (
        admission.calls == embedding.calls == index.search_calls == verifier.calls == 0
    )


def test_double_miss_assist_embeds_searches_verifies_then_still_runs_planner() -> None:
    candidate = SemanticIntentPlanCandidate(plan=_plan())
    coordinator, store, l2, admission, embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(candidate,),
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    result = coordinator.execute(planner, _context())

    assert result.decision.outcome == "miss"
    assert planner_calls == 1
    assert (
        admission.calls == embedding.calls == index.search_calls == verifier.calls == 1
    )
    assert admission.purposes == ["query_embedding"]
    assert embedding.bindings == admission.bindings
    assert verifier.bindings == [None]
    assert l2.save_calls == store.save_calls == index.append_calls == 1


def test_verified_planner_free_candidate_skips_planner_and_promotes_l1() -> None:
    candidate = SemanticIntentPlanCandidate(plan=_plan())
    coordinator, store, l2, admission, embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(candidate,),
        serving=True,
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    result = coordinator.execute(planner, _context())

    assert result.decision.outcome == "hit"
    assert planner_calls == 0
    assert (
        admission.calls == embedding.calls == index.search_calls == verifier.calls == 1
    )
    assert store.save_calls == 1
    assert l2.save_calls == index.append_calls == 0


def test_uncertain_verifier_and_failed_candidate_rehydration_fall_back() -> None:
    for verifier_status, statuses in (
        ("uncertain", ("success",)),
        ("verified", ("failure", "success")),
    ):
        coordinator, _store, _l2, _admission, _embedding, _index, _verifier = (
            _coordinator(
                l1=_miss(),
                l2=_miss(),
                candidates=(SemanticIntentPlanCandidate(plan=_plan()),),
                serving=True,
                verifier_status=verifier_status,
                rehydration_statuses=statuses,
            )
        )
        planner_calls = 0

        def planner():
            nonlocal planner_calls
            planner_calls += 1
            return _structured()

        result = coordinator.execute(planner, _context())

        assert result.decision.outcome == "miss"
        assert planner_calls == 1


def test_embedding_or_vector_failure_is_non_terminal_error_fallback() -> None:
    for kwargs in ({"embedding_error": True}, {"index_error": True}):
        coordinator, _store, _l2, _admission, _embedding, index, _verifier = (
            _coordinator(
                l1=_miss(),
                l2=_miss(),
                **kwargs,
            )
        )

        result = coordinator.execute(lambda: _structured(), _context())

        assert result.decision.outcome == "error"
        assert index.append_calls == 0


def test_ineligible_or_over_limit_request_performs_no_semantic_io() -> None:
    contexts = (
        _context(selected_target=True),
        _context(workflow_present=True),
        _context(message=("가" * 240) + "아님"),
    )
    for context in contexts:
        coordinator, _store, _l2, admission, embedding, index, verifier = _coordinator(
            l1=_miss(),
            l2=_miss(),
        )

        result = coordinator.execute(lambda: _structured(), context)

        assert result.decision.outcome == "miss"
        assert (
            admission.calls
            == embedding.calls
            == index.search_calls
            == verifier.calls
            == 0
        )
        assert index.append_calls == 0


def test_ineligible_candidate_is_discarded_before_verifier() -> None:
    coordinator, _store, _l2, _admission, _embedding, _index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(SemanticIntentPlanCandidate(plan=_plan(eligible=False)),),
        serving=True,
    )

    result = coordinator.execute(lambda: _structured(), _context())

    assert result.decision.outcome == "miss"
    assert verifier.calls == 0


def test_dirty_session_boundary_stops_semantic_follow_up_io() -> None:
    guard_results = iter((True, True, False))
    coordinator, _store, _l2, admission, embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        cache_io_guard=lambda: next(guard_results, False),
    )

    with pytest.raises(SemanticTransactionBoundaryError):
        coordinator.execute(lambda: _structured(), _context())

    assert (
        admission.calls == embedding.calls == index.search_calls == verifier.calls == 0
    )
    assert index.append_calls == 0


def test_guard_failure_after_embedding_is_sticky_and_prevents_all_follow_up() -> None:
    guard_results = iter((True, True, True, True, False))
    planner_calls = 0
    coordinator, store, l2, admission, embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        cache_io_guard=lambda: next(guard_results, False),
    )

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    with pytest.raises(SemanticTransactionBoundaryError):
        coordinator.execute(planner, _context())

    assert admission.calls == embedding.calls == 1
    assert index.search_calls == verifier.calls == index.append_calls == 0
    assert planner_calls == l2.save_calls == store.save_calls == 0


def test_semantic_rehydration_transaction_is_closed_before_planner() -> None:
    transaction = {"open": False}
    planner_saw_open_transaction = None

    def guard():
        transaction["open"] = False
        return True

    def rehydration_hook():
        transaction["open"] = True

    coordinator, *_dependencies = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(SemanticIntentPlanCandidate(plan=_plan()),),
        cache_io_guard=guard,
        rehydration_hook=rehydration_hook,
    )

    def planner():
        nonlocal planner_saw_open_transaction
        planner_saw_open_transaction = transaction["open"]
        return _structured()

    coordinator.execute(planner, _context())

    assert planner_saw_open_transaction is False


def test_uncloseable_semantic_rehydration_transaction_prevents_planner() -> None:
    transaction = {"open": False}
    planner_calls = 0

    def guard():
        return not transaction["open"]

    def rehydration_hook():
        transaction["open"] = True

    coordinator, store, l2, *_dependencies = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(SemanticIntentPlanCandidate(plan=_plan()),),
        cache_io_guard=guard,
        rehydration_hook=rehydration_hook,
    )

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    with pytest.raises(SemanticTransactionBoundaryError):
        coordinator.execute(planner, _context())

    assert planner_calls == store.save_calls == l2.save_calls == 0


@pytest.mark.parametrize(
    "l2_result",
    [
        None,
        IntentPlanLoadResult(
            status="unavailable",
            plan=None,
            reason="cache_unavailable",
        ),
        IntentPlanLoadResult(
            status="invalid",
            plan=None,
            reason="invalid_cached_plan",
        ),
    ],
)
def test_only_an_explicit_l2_miss_can_start_semantic_io(l2_result) -> None:
    coordinator, _store, _l2, admission, embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=l2_result,
    )

    coordinator.execute(lambda: _structured(), _context())

    assert (
        admission.calls
        == embedding.calls
        == index.search_calls
        == verifier.calls
        == index.append_calls
        == 0
    )


def test_l2_unavailable_result_prevents_semantic_append() -> None:
    coordinator, _store, l2, _admission, _embedding, index, _verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
    )
    l2.save_result = IntentPlanL2SaveResult(
        status="unavailable",
        receipt=None,
        reason="cache_unavailable",
    )

    result = coordinator.execute(lambda: _structured(), _context())

    assert result.decision.outcome == "error"
    assert index.append_calls == 0


def test_external_call_admission_denial_or_failure_prevents_semantic_io() -> None:
    for status, expected_outcome in (("denied", "miss"), ("unavailable", "error")):
        (
            coordinator,
            _store,
            _l2,
            admission,
            embedding,
            index,
            verifier,
        ) = _coordinator(
            l1=_miss(),
            l2=_miss(),
            admission_status=status,
        )

        result = coordinator.execute(lambda: _structured(), _context())

        assert result.decision.outcome == expected_outcome
        assert admission.calls == 1
        assert embedding.calls == index.search_calls == verifier.calls == 0


@pytest.mark.parametrize(
    "binding",
    [
        None,
        SemanticExternalCallBinding(
            purpose="semantic_verification",
        ),
    ],
)
def test_missing_or_wrong_purpose_embedding_binding_prevents_provider_call(
    binding,
) -> None:
    coordinator, _store, _l2, _admission, embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
    )

    class InvalidAdmission:
        @staticmethod
        def authorize(*, context, policy, purpose):
            return SimpleNamespace(status="admitted", binding=binding)

    coordinator._semantic_external_call_admission = InvalidAdmission()

    result = coordinator.execute(lambda: _structured(), _context())

    assert result.decision.outcome == "error"
    assert embedding.calls == index.search_calls == verifier.calls == 0


def test_verifier_error_result_is_an_error_fallback() -> None:
    coordinator, *_dependencies = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(SemanticIntentPlanCandidate(plan=_plan()),),
        verifier_status="error",
    )

    result = coordinator.execute(lambda: _structured(), _context())

    assert result.decision.outcome == "error"


def test_provider_backed_verifier_cannot_enable_planner_free_serving() -> None:
    coordinator, _store, _l2, admission, embedding, _index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(SemanticIntentPlanCandidate(plan=_plan()),),
        serving=True,
        verifier_provider_call_free=False,
    )
    planner_calls = 0

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    result = coordinator.execute(planner, _context())

    assert result.decision.outcome == "miss"
    assert planner_calls == 1
    assert admission.purposes == ["query_embedding", "semantic_verification"]
    assert embedding.bindings == [admission.bindings[0]]
    assert verifier.bindings == [admission.bindings[1]]


@pytest.mark.parametrize("serving", [False, True])
def test_cancellation_during_embedding_prevents_serving_planner_and_writes(
    serving: bool,
) -> None:
    request_status = {"value": "active"}
    planner_calls = 0

    def cancel_request():
        request_status["value"] = "canceled"

    coordinator, store, l2, _admission, _embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(SemanticIntentPlanCandidate(plan=_plan()),),
        serving=serving,
        cancellation_fence=lambda: request_status["value"],
        embedding_hook=cancel_request,
    )

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    with pytest.raises(RequestFenceAbortedError) as captured:
        coordinator.execute(planner, _context())

    assert captured.value.status == "canceled"
    assert planner_calls == store.save_calls == l2.save_calls == 0
    assert index.search_calls == index.append_calls == verifier.calls == 0


def test_cancellation_during_verifier_prevents_rehydration_serving_and_planner() -> (
    None
):
    request_status = {"value": "active"}
    planner_calls = 0

    def cancel_request():
        request_status["value"] = "canceled"

    coordinator, store, l2, _admission, _embedding, index, verifier = _coordinator(
        l1=_miss(),
        l2=_miss(),
        candidates=(SemanticIntentPlanCandidate(plan=_plan()),),
        serving=True,
        cancellation_fence=lambda: request_status["value"],
        verifier_hook=cancel_request,
    )

    def planner():
        nonlocal planner_calls
        planner_calls += 1
        return _structured()

    with pytest.raises(RequestFenceAbortedError):
        coordinator.execute(planner, _context())

    assert planner_calls == store.save_calls == l2.save_calls == 0
    assert index.search_calls == verifier.calls == 1
    assert index.append_calls == 0


def test_semantic_append_failure_keeps_result_and_l1_but_reports_error() -> None:
    coordinator, store, _l2, *_dependencies = _coordinator(
        l1=_miss(),
        l2=_miss(),
        append_error=True,
    )

    result = coordinator.execute(lambda: _structured(), _context())

    assert result.structured_request.intent_summary == "rehydrated"
    assert result.decision.outcome == "error"
    assert store.save_calls == 1
