from __future__ import annotations

import json
import time
from contextvars import ContextVar
from dataclasses import dataclass
from collections.abc import Callable
from typing import Literal, Protocol

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CacheBoundaryDecision,
    CachedIntentPlanV1,
    IntentCacheKey,
    IntentPlanLoadResult,
    IntentPlanL2SaveResult,
    IntentPlanningContext,
)
from apps.gateway.application.agent_builder.intent_cache.ports import (
    IntentNormalizerPort,
    IntentPlanExecution,
    IntentPlanRehydratorPort,
    PlannerCall,
    SemanticCandidateVerifierPort,
    SemanticEmbeddingProviderPort,
    SemanticExternalCallAdmissionPort,
    SemanticIntentPlanIndexPort,
)
from apps.gateway.application.agent_builder.intent_semantic_cache import (
    SemanticCachePolicy,
    SemanticEmbedding,
    SemanticExternalCallBinding,
    SemanticIntentPlanCandidate,
    SemanticQueryProjectionBuilder,
    SemanticQueryProjectionV1,
)
from apps.shared.schemas.agent_builder import AgentBuilderStructuredRequest


class _IntentPlanKeyStore(Protocol):
    def build_key(self, canonical_key_material: bytes) -> IntentCacheKey: ...

    def load(self, key: IntentCacheKey) -> IntentPlanLoadResult: ...

    def save(self, key: IntentCacheKey, plan: CachedIntentPlanV1): ...

    def save_if_lease_owner(
        self,
        key: IntentCacheKey,
        plan: CachedIntentPlanV1,
        owner_token: str,
        lease_generation: int,
    ): ...

    def new_owner_token(self) -> str: ...

    def acquire_lease(self, key: IntentCacheKey, owner_token: str): ...

    def release_lease(
        self,
        key: IntentCacheKey,
        owner_token: str,
        lease_generation: int,
    ): ...

    def complete_without_value(
        self,
        key: IntentCacheKey,
        owner_token: str,
        lease_generation: int,
    ): ...

    def wait_for_value(
        self,
        key: IntentCacheKey,
        lease_generation: int,
        *,
        cancellation_fence: Callable[[], Literal["active", "canceled", "stale"]],
        request_deadline_monotonic: float | None = None,
    ): ...


class _IntentPlanL2Store(Protocol):
    def load(
        self,
        context: IntentPlanningContext,
        canonical_key_material: bytes,
    ) -> IntentPlanLoadResult | None: ...

    def save(
        self,
        context: IntentPlanningContext,
        canonical_key_material: bytes,
        plan: CachedIntentPlanV1,
    ): ...


PlanProjector = Callable[
    [AgentBuilderStructuredRequest, IntentPlanningContext], CachedIntentPlanV1 | None
]
RehydratorFactory = Callable[
    [IntentPlanningContext, CachedIntentPlanV1], IntentPlanRehydratorPort
]
CancellationFence = Callable[[], Literal["active", "canceled", "stale"]]
CacheIoGuard = Callable[[], bool]


@dataclass(frozen=True, slots=True)
class _SemanticAttempt:
    started: bool = False
    projection: SemanticQueryProjectionV1 | None = None
    embedding: SemanticEmbedding | None = None
    append_allowed: bool = False
    served_plan: CachedIntentPlanV1 | None = None
    served_request: AgentBuilderStructuredRequest | None = None
    outcome: Literal["miss", "error"] | None = None


@dataclass(frozen=True, slots=True)
class IntentCacheDiagnostic:
    outcome: Literal["hit", "miss", "bypass", "error"]
    reason: str | None
    single_flight_role: str
    latency_ms: int
    cache_schema_version: int | None
    normalizer_version: str | None
    planner_contract_version: str | None
    catalog_version: int | None
    canonical_text_registry_version: str | None
    materializer_version: str | None


DiagnosticObserver = Callable[[IntentCacheDiagnostic], None]
KnowledgeContextFingerprintFactory = Callable[..., str]
_DIAGNOSTIC_STARTED_AT: ContextVar[float | None] = ContextVar(
    "agent_builder_intent_cache_started_at",
    default=None,
)
_DIAGNOSTIC_CONTEXT: ContextVar[IntentPlanningContext | None] = ContextVar(
    "agent_builder_intent_cache_context",
    default=None,
)

class ColdMissRehydrationError(RuntimeError):
    """Provider work was charged but its cache-safe output was not materializable."""

    def __init__(self) -> None:
        super().__init__("agent_builder_intent_cache_rehydration_failed")


class RequestFenceAbortedError(RuntimeError):
    """A cache-enabled request was canceled or became stale before planner work."""

    def __init__(self, status: Literal["canceled", "stale"]) -> None:
        self.status = status
        super().__init__(f"agent_builder_intent_cache_request_{status}")


class SemanticTransactionBoundaryError(RuntimeError):
    """Semantic work could not release the request-owned service transaction."""

    def __init__(self) -> None:
        super().__init__("agent_builder_semantic_transaction_boundary_unavailable")


class FollowerWaitAbortedError(RequestFenceAbortedError):
    """The adapter observed the request cancellation/version fence while waiting."""

    def __init__(self, status: Literal["canceled", "stale"]) -> None:
        super().__init__(status)

def _active_fence() -> Literal["active"]:
    return "active"



def _cache_io_allowed() -> bool:
    return True

class AgentBuilderIntentCacheCoordinator:
    """Composes normalizer, cache, Planner and current-context rehydration.

    It intentionally has one follower wait call, never retries cache I/O, and never
    returns a raw provider result after a cache-safe cold miss has failed rehydration.
    """

    def __init__(
        self,
        *,
        normalizer: IntentNormalizerPort,
        store: _IntentPlanKeyStore,
        rehydrator_factory: RehydratorFactory,
        plan_projector: PlanProjector,
        cancellation_fence: CancellationFence | None = None,
        request_deadline_monotonic: float | None = None,
        cache_io_guard: CacheIoGuard | None = None,
        diagnostic_observer: DiagnosticObserver | None = None,
        knowledge_context_fingerprint_factory: KnowledgeContextFingerprintFactory | None = None,
        l2_store: _IntentPlanL2Store | None = None,
        semantic_policy: SemanticCachePolicy | None = None,
        semantic_projection_builder: SemanticQueryProjectionBuilder | None = None,
        semantic_external_call_admission: SemanticExternalCallAdmissionPort
        | None = None,
        semantic_embedding_provider: SemanticEmbeddingProviderPort | None = None,
        semantic_index: SemanticIntentPlanIndexPort | None = None,
        semantic_verifier: SemanticCandidateVerifierPort | None = None,
    ) -> None:
        self._normalizer = normalizer
        self._store = store
        self._rehydrator_factory = rehydrator_factory
        self._plan_projector = plan_projector
        self._cancellation_fence = cancellation_fence or _active_fence
        self._request_deadline_monotonic = request_deadline_monotonic
        self._cache_io_guard = cache_io_guard or _cache_io_allowed
        self._diagnostic_observer = diagnostic_observer
        self._knowledge_context_fingerprint_factory = (
            knowledge_context_fingerprint_factory
        )
        self._l2_store = l2_store
        self._semantic_policy = semantic_policy
        self._semantic_projection_builder = semantic_projection_builder
        self._semantic_external_call_admission = semantic_external_call_admission
        self._semantic_embedding_provider = semantic_embedding_provider
        self._semantic_index = semantic_index
        self._semantic_verifier = semantic_verifier

    def for_request(
        self,
        *,
        rehydrator_factory: RehydratorFactory | None = None,
        cancellation_fence: CancellationFence | None = None,
        request_deadline_monotonic: float | None = None,
        cache_io_guard: CacheIoGuard | None = None,
    ) -> "AgentBuilderIntentCacheCoordinator":
        """Bind only request-transient authority checks; no cache state is copied."""
        return AgentBuilderIntentCacheCoordinator(
            normalizer=self._normalizer,
            store=self._store,
            rehydrator_factory=rehydrator_factory or self._rehydrator_factory,
            plan_projector=self._plan_projector,
            cancellation_fence=cancellation_fence or self._cancellation_fence,
            request_deadline_monotonic=(
                request_deadline_monotonic
                if request_deadline_monotonic is not None
                else self._request_deadline_monotonic
            ),
            cache_io_guard=cache_io_guard or self._cache_io_guard,
            diagnostic_observer=self._diagnostic_observer,
            knowledge_context_fingerprint_factory=(
                self._knowledge_context_fingerprint_factory
            ),
            l2_store=self._l2_store,
            semantic_policy=self._semantic_policy,
            semantic_projection_builder=self._semantic_projection_builder,
            semantic_external_call_admission=(
                self._semantic_external_call_admission
            ),
            semantic_embedding_provider=self._semantic_embedding_provider,
            semantic_index=self._semantic_index,
            semantic_verifier=self._semantic_verifier,
        )

    def current_knowledge_context_fingerprint(self, **kwargs) -> str:
        factory = self._knowledge_context_fingerprint_factory
        if factory is None:
            raise RuntimeError("knowledge fingerprint factory is unavailable")
        return factory(**kwargs)

    def execute(
        self,
        planner_call: PlannerCall,
        context: IntentPlanningContext | None = None,
    ) -> IntentPlanExecution:
        started_token = _DIAGNOSTIC_STARTED_AT.set(time.monotonic())
        context_token = _DIAGNOSTIC_CONTEXT.set(context)
        try:
            return self._execute(planner_call, context)
        finally:
            _DIAGNOSTIC_CONTEXT.reset(context_token)
            _DIAGNOSTIC_STARTED_AT.reset(started_token)

    def _execute(
        self,
        planner_call: PlannerCall,
        context: IntentPlanningContext | None = None,
    ) -> IntentPlanExecution:
        if context is None:
            return self._planner_execution(
                planner_call,
                outcome="bypass",
                reason="normalization_bypass",
                single_flight_role="none",
            )

        self._ensure_request_active(single_flight_role="none")
        try:
            normalization = self._normalizer.normalize(context)
        except Exception:
            return self._planner_execution(
                planner_call,
                outcome="bypass",
                reason="normalization_bypass",
                single_flight_role="none",
            )
        if normalization.status != "eligible" or normalization.intent_signature is None:
            return self._planner_execution(
                planner_call,
                outcome="bypass",
                reason="normalization_bypass",
                single_flight_role="none",
            )

        canonical_key_material = self._canonical_key_material(
            context,
            normalization.intent_signature,
        )
        try:
            key = self._store.build_key(canonical_key_material)
        except Exception:
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="none",
            )

        if not self._cache_io_ready():
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="none",
            )

        try:
            loaded = self._store.load(key)
        except Exception:
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="none",
            )

        if loaded.status == "hit" and loaded.plan is not None:
            self._ensure_request_active(single_flight_role="none")
            rehydrated = self._rehydrate(loaded.plan, context)
            if rehydrated is not None:
                return self._execution(
                    rehydrated,
                    outcome="hit",
                    reason=None,
                    single_flight_role="none",
                    plan=loaded.plan,
                )
            return self._after_miss(
                planner_call,
                context,
                key,
                canonical_key_material,
                miss_reason="rehydration_failed",
                semantic_eligible=False,
            )
        if loaded.status == "unavailable":
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="none",
            )
        l2_loaded = self._load_l2(context, canonical_key_material)
        if (
            l2_loaded is not None
            and l2_loaded.status == "hit"
            and l2_loaded.plan is not None
        ):
            self._ensure_request_active(single_flight_role="none")
            rehydrated = self._rehydrate(l2_loaded.plan, context)
            if rehydrated is not None:
                self._promote_l2_hit(key, l2_loaded.plan)
                return self._execution(
                    rehydrated,
                    outcome="hit",
                    reason=None,
                    single_flight_role="none",
                    plan=l2_loaded.plan,
                )
            l2_miss_reason = "rehydration_failed"
        else:
            l2_miss_reason = (
                "invalid_cached_plan"
                if l2_loaded is not None and l2_loaded.status == "invalid"
                else "not_found"
            )
        return self._after_miss(
            planner_call,
            context,
            key,
            canonical_key_material,
            miss_reason=(
                "invalid_cached_plan"
                if loaded.status == "invalid"
                else l2_miss_reason
            ),
            semantic_eligible=(
                loaded.status == "miss"
                and l2_loaded is not None
                and l2_loaded.status == "miss"
            ),
        )

    @staticmethod
    def _canonical_key_material(
        context: IntentPlanningContext,
        intent_signature: str,
    ) -> bytes:
        """Return short-lived HMAC input only; it is never a cache value/diagnostic."""
        scope = context.scope
        projection = {
            "actor_id": str(scope._actor_id),
            "contract_versions": context.contract_versions.model_dump(mode="json"),
            "generation_mode": context.generation_mode,
            "intent_signature": intent_signature,
            "knowledge_context_fingerprint": context.knowledge_context_fingerprint,
            "organization_id": str(scope._organization_id),
            "planner_runtime": context.planner_runtime.model_dump(mode="json"),
            "selected_target": {
                "id": scope._selected_target_id,
                "type": scope._selected_target_type,
            },
        }
        return json.dumps(
            projection,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")

    def _load_l2(
        self,
        context: IntentPlanningContext,
        canonical_key_material: bytes,
    ) -> IntentPlanLoadResult | None:
        store = self._l2_store
        if store is None:
            return None
        try:
            return store.load(context, canonical_key_material)
        except Exception:
            return IntentPlanLoadResult(
                status="unavailable",
                plan=None,
                reason="cache_unavailable",
            )

    def _save_l2(
        self,
        context: IntentPlanningContext,
        canonical_key_material: bytes,
        plan: CachedIntentPlanV1,
    ):
        store = self._l2_store
        if store is None:
            return None
        # Rehydration can have opened the request-owned service Session.  Release
        # that read transaction before the repository obtains its own connection.
        if not self._cache_io_ready():
            return IntentPlanL2SaveResult(
                status="unavailable",
                receipt=None,
                reason="cache_unavailable",
            )
        try:
            return store.save(context, canonical_key_material, plan)
        except Exception:
            return IntentPlanL2SaveResult(
                status="unavailable",
                receipt=None,
                reason="cache_unavailable",
            )

    def _promote_l2_hit(
        self,
        key: IntentCacheKey,
        plan: CachedIntentPlanV1,
    ) -> None:
        if not self._cache_io_ready():
            return
        try:
            self._store.save(key, plan)
        except Exception:
            pass

    def _after_miss(
        self,
        planner_call: PlannerCall,
        context: IntentPlanningContext,
        key: IntentCacheKey,
        canonical_key_material: bytes,
        *,
        miss_reason: Literal[
            "not_found", "invalid_cached_plan", "rehydration_failed"
        ],
        semantic_eligible: bool,
    ) -> IntentPlanExecution:
        self._ensure_request_active(single_flight_role="none")
        try:
            owner_token = self._store.new_owner_token()
            if not self._cache_io_ready():
                raise RuntimeError("cache I/O transaction boundary unavailable")
            lease = self._store.acquire_lease(key, owner_token)
        except Exception:
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="none",
            )

        if lease.status == "unavailable" or lease.generation is None:
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="none",
            )
        if lease.status == "contended":
            return self._follower_execution(
                planner_call,
                context,
                key,
                lease.generation,
                miss_reason=miss_reason,
            )
        if lease.status != "acquired":
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="none",
            )
        return self._owner_execution(
            planner_call,
            context,
            key,
            canonical_key_material,
            owner_token,
            lease.generation,
            miss_reason=miss_reason,
            semantic_eligible=semantic_eligible,
        )

    def _follower_execution(
        self,
        planner_call: PlannerCall,
        context: IntentPlanningContext,
        key: IntentCacheKey,
        generation: int,
        *,
        miss_reason: Literal[
            "not_found", "invalid_cached_plan", "rehydration_failed"
        ],
    ) -> IntentPlanExecution:
        self._ensure_request_active(single_flight_role="follower")
        try:
            if not self._cache_io_ready():
                raise RuntimeError("cache I/O transaction boundary unavailable")
            waited = self._store.wait_for_value(
                key,
                generation,
                cancellation_fence=self._cancellation_fence,
                request_deadline_monotonic=self._request_deadline_monotonic,
            )
        except Exception:
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="follower",
            )
        if waited.status in {"canceled", "stale"}:
            self._emit_diagnostic(
                outcome="bypass",
                reason=f"request_{waited.status}",
                single_flight_role="follower",
            )
            raise FollowerWaitAbortedError(waited.status)
        if waited.status == "hit" and waited.plan is not None:
            self._ensure_request_active(single_flight_role="follower")
            rehydrated = self._rehydrate(waited.plan, context)
            if rehydrated is not None:
                return self._execution(
                    rehydrated,
                    outcome="hit",
                    reason=None,
                    single_flight_role="follower",
                    plan=waited.plan,
                )
            miss_reason = "rehydration_failed"
        if waited.status == "unavailable":
            return self._planner_execution(
                planner_call,
                outcome="error",
                reason="cache_unavailable",
                single_flight_role="follower",
            )
        # A follower never loops or overwrites the owner without a lease.
        return self._planner_execution(
            planner_call,
            outcome="miss",
            reason=miss_reason,
            diagnostic_reason=(
                "waiter_capacity_exceeded"
                if waited.status == "overflow"
                else None
            ),
            single_flight_role=(
                "overflow" if waited.status == "overflow" else "follower"
            ),
        )

    def _owner_execution(
        self,
        planner_call: PlannerCall,
        context: IntentPlanningContext,
        key: IntentCacheKey,
        canonical_key_material: bytes,
        owner_token: str,
        generation: int,
        *,
        miss_reason: Literal[
            "not_found", "invalid_cached_plan", "rehydration_failed"
        ],
        semantic_eligible: bool,
    ) -> IntentPlanExecution:
        completed_without_value = False
        try:
            self._ensure_request_active(single_flight_role="owner")
            semantic_attempt = (
                self._semantic_attempt(context)
                if semantic_eligible
                else _SemanticAttempt()
            )
            self._ensure_request_active(single_flight_role="owner")
            if semantic_attempt.started:
                self._require_semantic_transaction_boundary()
            if (
                semantic_attempt.served_plan is not None
                and semantic_attempt.served_request is not None
            ):
                saved = self._save_semantic_serving_to_l1(
                    key,
                    semantic_attempt.served_plan,
                    owner_token,
                    generation,
                )
                if not saved:
                    completed_without_value = self._complete_without_value(
                        key, owner_token, generation
                    )
                return self._execution(
                    semantic_attempt.served_request,
                    outcome="hit",
                    reason=None,
                    single_flight_role="owner",
                    plan=semantic_attempt.served_plan,
                )
            structured_request = planner_call()
            try:
                plan = self._plan_projector(structured_request, context)
            except Exception:
                plan = None
            if plan is None:
                completed_without_value = self._complete_without_value(
                    key, owner_token, generation
                )
                return self._execution(
                    structured_request,
                    outcome="miss",
                    reason=miss_reason,
                    single_flight_role="owner",
                )
            rehydrated = self._rehydrate(plan, context)
            if rehydrated is None:
                completed_without_value = self._complete_without_value(
                    key, owner_token, generation
                )
                self._emit_diagnostic(
                    outcome="error",
                    reason="cold_rehydration_failed",
                    single_flight_role="owner",
                )
                raise ColdMissRehydrationError()
            l2_saved = self._save_l2(context, canonical_key_material, plan)
            if (
                l2_saved is not None
                and getattr(l2_saved, "status", None) != "stored"
            ):
                completed_without_value = self._complete_without_value(
                    key, owner_token, generation
                )
                return self._execution(
                    rehydrated,
                    outcome="error",
                    reason="cache_unavailable",
                    single_flight_role="owner",
                )
            semantic_append_error = self._append_semantic_index(
                context=context,
                attempt=semantic_attempt,
                l2_saved=l2_saved,
            )
            if not self._cache_io_ready():
                saved = None
            else:
                try:
                    saved = self._store.save_if_lease_owner(
                        key,
                        plan,
                        owner_token,
                        generation,
                    )
                except Exception:
                    saved = None
            if getattr(saved, "status", None) != "stored":
                completed_without_value = self._complete_without_value(
                    key, owner_token, generation
                )
                return self._execution(
                    rehydrated,
                    outcome="error",
                    reason="cache_unavailable",
                    single_flight_role="owner",
                )
            final_outcome = (
                "error"
                if semantic_append_error
                else semantic_attempt.outcome or "miss"
            )
            return self._execution(
                rehydrated,
                outcome=final_outcome,
                reason=(
                    "cache_unavailable"
                    if final_outcome == "error"
                    else miss_reason
                ),
                single_flight_role="owner",
            )
        finally:
            if not completed_without_value:
                self._release_lease(key, owner_token, generation)

    def _semantic_attempt(self, context: IntentPlanningContext) -> _SemanticAttempt:
        policy = self._semantic_policy
        builder = self._semantic_projection_builder
        provider = self._semantic_embedding_provider
        index = self._semantic_index
        admission = self._semantic_external_call_admission
        if (
            policy is None
            or not policy.assist_enabled
            or builder is None
            or admission is None
            or provider is None
            or index is None
        ):
            return _SemanticAttempt()
        if (
            context.workflow_context.workflow_present
            or context.scope._selected_target_id is not None
        ):
            return _SemanticAttempt(outcome="miss")
        projection = builder.build(context.full_safe_message)
        if projection is None:
            return _SemanticAttempt(started=True, outcome="miss")
        self._require_semantic_transaction_boundary()
        try:
            admission_result = admission.authorize(
                context=context,
                policy=policy,
                purpose="query_embedding",
            )
        except Exception:
            return _SemanticAttempt(
                started=True,
                projection=projection,
                outcome="error",
            )
        self._ensure_request_active(single_flight_role="owner")
        admission_status = getattr(admission_result, "status", None)
        if admission_status != "admitted":
            return _SemanticAttempt(
                started=True,
                projection=projection,
                outcome="miss" if admission_status == "denied" else "error",
            )
        embedding_binding = getattr(admission_result, "binding", None)
        if (
            not isinstance(embedding_binding, SemanticExternalCallBinding)
            or embedding_binding.purpose != "query_embedding"
        ):
            return _SemanticAttempt(
                started=True,
                projection=projection,
                outcome="error",
            )
        self._require_semantic_transaction_boundary()
        try:
            embedding = provider.embed(projection, binding=embedding_binding)
        except Exception:
            return _SemanticAttempt(
                started=True,
                projection=projection,
                outcome="error",
            )
        self._ensure_request_active(single_flight_role="owner")
        if (
            not isinstance(embedding, SemanticEmbedding)
            or len(embedding.values) != policy.embedding_dimension
        ):
            return _SemanticAttempt(
                started=True,
                projection=projection,
                outcome="error",
            )
        self._require_semantic_transaction_boundary()
        try:
            candidates = tuple(
                index.search(
                    context=context,
                    policy=policy,
                    projection=projection,
                    embedding=embedding,
                )
            )[: policy.top_k]
        except Exception:
            return _SemanticAttempt(
                started=True,
                projection=projection,
                embedding=embedding,
                outcome="error",
            )
        self._ensure_request_active(single_flight_role="owner")
        for candidate in candidates:
            if not isinstance(candidate, SemanticIntentPlanCandidate):
                continue
            plan = candidate.plan
            if not (
                plan.request_type == "new_workflow"
                and plan.draft_mode == "new_workflow"
                and plan.edit_placement is None
            ):
                continue
            verifier = self._semantic_verifier
            if verifier is None:
                return _SemanticAttempt(
                    started=True,
                    projection=projection,
                    embedding=embedding,
                    append_allowed=True,
                    outcome="miss",
                )
            verifier_provider_call_free = (
                getattr(verifier, "provider_call_free", False) is True
            )
            verification_binding = None
            if not verifier_provider_call_free:
                self._require_semantic_transaction_boundary()
                try:
                    verification_admission = admission.authorize(
                        context=context,
                        policy=policy,
                        purpose="semantic_verification",
                    )
                except Exception:
                    return _SemanticAttempt(
                        started=True,
                        projection=projection,
                        embedding=embedding,
                        outcome="error",
                    )
                self._ensure_request_active(single_flight_role="owner")
                verification_admission_status = getattr(
                    verification_admission,
                    "status",
                    None,
                )
                if verification_admission_status != "admitted":
                    return _SemanticAttempt(
                        started=True,
                        projection=projection,
                        embedding=embedding,
                        append_allowed=(verification_admission_status == "denied"),
                        outcome=(
                            "miss"
                            if verification_admission_status == "denied"
                            else "error"
                        ),
                    )
                verification_binding = getattr(
                    verification_admission,
                    "binding",
                    None,
                )
                if (
                    not isinstance(
                        verification_binding,
                        SemanticExternalCallBinding,
                    )
                    or verification_binding.purpose != "semantic_verification"
                ):
                    return _SemanticAttempt(
                        started=True,
                        projection=projection,
                        embedding=embedding,
                        outcome="error",
                    )
            self._require_semantic_transaction_boundary()
            try:
                verification = verifier.verify(
                    projection=projection,
                    candidate=candidate,
                    context=context,
                    binding=verification_binding,
                )
            except Exception:
                return _SemanticAttempt(
                    started=True,
                    projection=projection,
                    embedding=embedding,
                    outcome="error",
                )
            self._ensure_request_active(single_flight_role="owner")
            verification_status = getattr(verification, "status", None)
            if verification_status not in {
                "verified",
                "rejected",
                "uncertain",
                "unavailable",
                "error",
            }:
                return _SemanticAttempt(
                    started=True,
                    projection=projection,
                    embedding=embedding,
                    outcome="error",
                )
            if verification_status != "verified":
                return _SemanticAttempt(
                    started=True,
                    projection=projection,
                    embedding=embedding,
                    append_allowed=(
                        verification_status not in {"unavailable", "error"}
                    ),
                    outcome=(
                        "error"
                        if verification_status in {"unavailable", "error"}
                        else "miss"
                    ),
                )
            rehydrated = self._rehydrate(plan, context)
            self._ensure_request_active(single_flight_role="owner")
            self._require_semantic_transaction_boundary()
            if rehydrated is None:
                return _SemanticAttempt(
                    started=True,
                    projection=projection,
                    embedding=embedding,
                    append_allowed=True,
                    outcome="miss",
                )
            if policy.planner_free_serving_enabled and verifier_provider_call_free:
                return _SemanticAttempt(
                    started=True,
                    projection=projection,
                    embedding=embedding,
                    served_plan=plan,
                    served_request=rehydrated,
                )
            return _SemanticAttempt(
                started=True,
                projection=projection,
                embedding=embedding,
                append_allowed=True,
                outcome="miss",
            )
        return _SemanticAttempt(
            started=True,
            projection=projection,
            embedding=embedding,
            append_allowed=True,
            outcome="miss",
        )

    def _save_semantic_serving_to_l1(
        self,
        key: IntentCacheKey,
        plan: CachedIntentPlanV1,
        owner_token: str,
        generation: int,
    ) -> bool:
        if not self._cache_io_ready():
            return False
        try:
            result = self._store.save_if_lease_owner(
                key,
                plan,
                owner_token,
                generation,
            )
        except Exception:
            return False
        return getattr(result, "status", None) == "stored"

    def _append_semantic_index(
        self,
        *,
        context: IntentPlanningContext,
        attempt: _SemanticAttempt,
        l2_saved,
    ) -> bool:
        policy = self._semantic_policy
        index = self._semantic_index
        if (
            policy is None
            or index is None
            or attempt.embedding is None
            or not attempt.append_allowed
            or attempt.outcome == "error"
            or not isinstance(l2_saved, IntentPlanL2SaveResult)
            or l2_saved.status != "stored"
            or l2_saved.receipt is None
            or not self._cache_io_ready()
        ):
            return False
        try:
            index.append(
                context=context,
                policy=policy,
                embedding=attempt.embedding,
                receipt=l2_saved.receipt,
            )
        except Exception:
            return True
        return False

    def _rehydrate(
        self,
        plan: CachedIntentPlanV1,
        context: IntentPlanningContext,
    ) -> AgentBuilderStructuredRequest | None:
        try:
            rehydrator = self._rehydrator_factory(context, plan)
            result = rehydrator.rehydrate(plan, context)
        except Exception:
            return None
        if result.status != "success":
            return None
        return result.structured_request

    def _complete_without_value(
        self,
        key: IntentCacheKey,
        owner_token: str,
        generation: int,
    ) -> bool:
        if not self._cache_io_ready():
            return False
        try:
            result = self._store.complete_without_value(key, owner_token, generation)
        except Exception:
            return False
        return getattr(result, "status", None) == "signaled_and_released"

    def _release_lease(
        self,
        key: IntentCacheKey,
        owner_token: str,
        generation: int,
    ) -> None:
        if not self._cache_io_ready():
            return
        try:
            self._store.release_lease(key, owner_token, generation)
        except Exception:
            pass

    def _ensure_request_active(self, *, single_flight_role: str) -> None:
        try:
            status = self._cancellation_fence()
        except Exception:
            status = "stale"
        if status == "active":
            return
        if status not in {"canceled", "stale"}:
            status = "stale"
        self._emit_diagnostic(
            outcome="bypass",
            reason=f"request_{status}",
            single_flight_role=single_flight_role,
        )
        raise RequestFenceAbortedError(status)


    def _cache_io_ready(self) -> bool:
        """Require a request-owned clean transaction boundary before Redis I/O."""
        try:
            return bool(self._cache_io_guard())
        except Exception:
            return False

    def _require_semantic_transaction_boundary(self) -> None:
        if not self._cache_io_ready():
            raise SemanticTransactionBoundaryError()

    def _planner_execution(
        self,
        planner_call: PlannerCall,
        *,
        outcome: Literal["hit", "miss", "bypass", "error"],
        reason: str | None,
        single_flight_role: str,
        plan: CachedIntentPlanV1 | None = None,
        diagnostic_reason: str | None = None,
    ) -> IntentPlanExecution:
        self._ensure_request_active(single_flight_role=single_flight_role)
        return self._execution(
            planner_call(),
            outcome=outcome,
            reason=reason,
            single_flight_role=single_flight_role,
            diagnostic_reason=diagnostic_reason,
        )

    def _emit_diagnostic(
        self,
        *,
        outcome: Literal["hit", "miss", "bypass", "error"],
        reason: str | None,
        single_flight_role: str,
    ) -> None:
        if self._diagnostic_observer is None:
            return
        context = _DIAGNOSTIC_CONTEXT.get()
        versions = context.contract_versions if context is not None else None
        started_at = _DIAGNOSTIC_STARTED_AT.get()
        latency_ms = (
            max(0, round((time.monotonic() - started_at) * 1000))
            if started_at is not None
            else 0
        )
        diagnostic = IntentCacheDiagnostic(
            outcome=outcome,
            reason=reason,
            single_flight_role=single_flight_role,
            latency_ms=latency_ms,
            cache_schema_version=(
                versions.cache_schema_version if versions is not None else None
            ),
            normalizer_version=(
                versions.normalizer_version if versions is not None else None
            ),
            planner_contract_version=(
                versions.planner_contract_version if versions is not None else None
            ),
            catalog_version=(versions.catalog_version if versions is not None else None),
            canonical_text_registry_version=(
                versions.canonical_text_registry_version if versions is not None else None
            ),
            materializer_version=(
                versions.materializer_version if versions is not None else None
            ),
        )
        try:
            self._diagnostic_observer(diagnostic)
        except Exception:
            pass

    def _execution(
        self,
        structured_request: AgentBuilderStructuredRequest,
        *,
        outcome: Literal["hit", "miss", "bypass", "error"],
        reason: str | None,
        single_flight_role: str,
        plan: CachedIntentPlanV1 | None = None,
        diagnostic_reason: str | None = None,
    ) -> IntentPlanExecution:
        decision = CacheBoundaryDecision(
            outcome=outcome,
            plan=plan,
            reason=reason,
        )
        self._emit_diagnostic(
            outcome=outcome,
            reason=(
                diagnostic_reason if diagnostic_reason is not None else reason
            ),
            single_flight_role=single_flight_role,
        )
        return IntentPlanExecution(
            structured_request=structured_request,
            decision=decision,
        )
