"""Celery task가 사용할 persisted model-routing policy refresh orchestration."""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_policy import (
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyRunEvent,
    LLMNodeModelRoutingPolicyUpdate,
)
from apps.shared.db.models.workflow_deployment import WorkflowDeployment
from apps.shared.services.model_routing_cohort_drafts import (
    filter_model_routing_available_model_ids,
)
from apps.shared.services.model_routing_policy_optimizer import (
    ModelRoutingOptimizationRequest,
    ModelRoutingPolicyOptimizer,
)
from apps.shared.services.node_config_fingerprint import (
    llm_node_config_fingerprint,
)
from apps.workflow_engine.services.llm_service import LLMService
from apps.workflow_engine.services.model_router import ModelRouter, ModelRouterContext
from apps.workflow_engine.services.model_routing_evidence import ReplayEvidenceAdapter
from apps.workflow_engine.services.model_routing_eligibility import (
    ModelRoutingEligibilityService,
)
from apps.workflow_engine.services.model_routing_policy_lifecycle import (
    ModelRoutingPolicyLifecycleService,
)
from apps.workflow_engine.services.model_routing_policy_refresh import (
    POLICY_JUDGE_PROMPT_VERSION,
    ModelRoutingPolicyRefreshRequest,
    ModelRoutingPolicyRefreshService,
)
from apps.workflow_engine.services.model_routing_semantic_catalog import (
    SemanticRouteCatalogBuilder,
)


logger = logging.getLogger(__name__)


class PersistedModelRoutingPolicyRefreshService:
    """저장된 policy를 읽고 judge refresh 결과를 policy/update row에 반영한다."""

    @classmethod
    def refresh(cls, db: Session, *, policy_id: str | uuid.UUID, trigger: str):
        policy = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.id == uuid.UUID(str(policy_id)))
            .first()
        )
        if policy is None:
            return None

        requested_at = policy.refresh_requested_at or datetime.now(timezone.utc)
        update = LLMNodeModelRoutingPolicyUpdate(
            policy_id=policy.id,
            trigger=trigger,
            status="failed",
            input_summary={},
            output_summary={},
        )
        db.add(update)

        try:
            deployment = (
                db.query(WorkflowDeployment)
                .filter(WorkflowDeployment.id == policy.deployment_id)
                .first()
            )
            node_data = cls._node_data(deployment.graph_snapshot if deployment else {}, policy.node_id)
            # 적응형 경로의 실제 품질 판단은 후보별 Replay와 quality judge가 맡는다.
            # 여기서 기존 policy judge를 추가로 호출하면 policy row를 잡은 DB transaction이
            # 네트워크 응답까지 열려 있어 뒤따르는 운영 observation 기록을 막을 수 있다.
            # 따라서 갱신 task는 짧게 "검증 계획 대기" 상태만 저장하고, 다음 task가
            # 실제 Replay/Judge evidence를 모아 rule을 활성화한다.
            if bool((node_data or {}).get("auto_model_routing")):
                return cls._prepare_adaptive_refresh(
                    db,
                    policy=policy,
                    update=update,
                    node_data=node_data or {},
                    requested_at=requested_at,
                )
            semantic_snapshot = cls._resolve_semantic_router_snapshot(
                db,
                policy=policy,
                node_data=node_data or {},
            )
            active_policy = (
                dict(policy.active_policy)
                if isinstance(policy.active_policy, dict)
                else {}
            )
            if (
                semantic_snapshot is not None
                and active_policy.get("semantic_router") != semantic_snapshot
            ):
                active_policy["semantic_router"] = semantic_snapshot
                policy.active_policy = active_policy
                policy.policy_version = ModelRoutingPolicyRefreshService._next_policy_version(
                    str(policy.policy_version or "v0")
                )
            current_policy = cls._as_router_policy(policy)
            candidates = (
                ModelRouter.collect_candidates(db, organization_id=policy.organization_id)
                if policy.organization_id is not None
                else []
            )
            available_model_ids: set[str] = set()
            if policy.judge_user_id is not None and policy.organization_id is not None:
                available_model_ids = set(
                    LLMService.get_runtime_available_model_ids_for_user(
                        db,
                        user_id=policy.judge_user_id,
                        organization_id=policy.organization_id,
                    )
                )
                available_model_ids = set(
                    filter_model_routing_available_model_ids(
                        available_model_ids,
                        node_data=node_data or {},
                    )
                )
                candidates = [
                    candidate
                    for candidate in candidates
                    if candidate.model_id in available_model_ids
                ]

            eligibility = None
            optimization_result = None
            evidence_batch = None
            node_fingerprint = llm_node_config_fingerprint(node_data or {})
            if (
                semantic_snapshot is not None
                and len(candidates) >= 2
                and policy.judge_user_id is not None
                and policy.organization_id is not None
            ):
                evidence_batch = ReplayEvidenceAdapter.collect(
                    db,
                    workflow_id=policy.workflow_id,
                    node_id=policy.node_id,
                    organization_id=policy.organization_id,
                    current_node_fingerprint=node_fingerprint,
                )
                eligibility = ModelRoutingEligibilityService.evaluate(
                    candidate_model_ids=[
                        candidate.model_id for candidate in candidates
                    ],
                    available_model_ids=available_model_ids,
                    semantic_catalog=semantic_snapshot,
                    evidence_batch=evidence_batch,
                    current_model_id=cls._current_default_model(
                        policy,
                        node_data=node_data or {},
                    ),
                )
                if eligibility.status == "eligible":
                    evidence_version = cls._evidence_version(
                        evidence_batch.samples,
                        node_fingerprint=node_fingerprint,
                    )
                    optimization_result = ModelRoutingPolicyOptimizer.optimize(
                        ModelRoutingOptimizationRequest(
                            default_model_id=cls._current_default_model(
                                policy,
                                node_data=node_data or {},
                            ),
                            evidence_samples=evidence_batch.samples,
                            objective=cls._routing_objective(node_data or {}),
                            expected_request_count=max(
                                100,
                                int(policy.refresh_every_runs or 20) * 5,
                            ),
                            embedding_cost_per_request=(
                                cls._embedding_cost_per_request(node_data or {})
                            ),
                            evidence_version=evidence_version,
                        )
                    )
            profile = ModelRouter.collect_profile(
                db,
                ModelRouterContext(
                    workflow_id=str(policy.workflow_id),
                    node_id=policy.node_id,
                    current_model_id=(node_data or {}).get("model_id"),
                    deployment_id=str(policy.deployment_id),
                ),
            )
            recent_runs = cls._safe_recent_runs(profile)
            segment_profiles = cls._safe_segment_profiles(profile)
            excluded_count = cls._excluded_run_count(db, policy, requested_at)
            update.eligible_run_count = profile.operational_usable_runs
            update.excluded_run_count = excluded_count
            update.excluded_reason_summary = {
                "missing_usage_or_output": excluded_count,
            }
            update.input_summary = {
                "node_summary": cls._safe_node_summary(node_data or {}),
                "model_profile": profile.as_snapshot(),
                "segment_profile_count": len(segment_profiles),
                "candidate_count": len(candidates),
                "routing_eligibility": (
                    {
                        "status": eligibility.status,
                        "reason_code": eligibility.reason_code,
                        "evidence_model_count": len(
                            eligibility.evidence_model_ids
                        ),
                    }
                    if eligibility is not None
                    else None
                ),
                "replay_evidence_count": (
                    len(evidence_batch.samples)
                    if evidence_batch is not None
                    else 0
                ),
            }

            if policy.judge_user_id is None or not candidates:
                result_status = "failed"
                proposed_active_policy = policy.active_policy or {}
                policy_version = policy.policy_version
                update.error_code = "judge_context_unavailable"
                update.output_summary = {"reason": "judge user 또는 실행 가능 모델이 없습니다."}
                judge_model_id = None
                judge_usage = {}
            else:
                judge_model_id = cls._select_judge_model(
                    candidates,
                    current_model_id=(node_data or {}).get("model_id"),
                )
                result = ModelRoutingPolicyRefreshService.refresh_policy(
                    db,
                    ModelRoutingPolicyRefreshRequest(
                        workflow_id=str(policy.workflow_id),
                        node_id=policy.node_id,
                        user_id=policy.judge_user_id,
                        organization_id=policy.organization_id,
                        current_policy=current_policy,
                        candidate_models=candidates,
                        recent_runs=recent_runs,
                        segment_profiles=segment_profiles,
                        node_summary=cls._safe_node_summary(node_data or {}),
                        trigger=trigger,
                        judge_model_id=judge_model_id,
                    ),
                )
                result_status = result.status
                proposed_active_policy = result.policy.get("active_policy") or policy.active_policy or {}
                policy_version = result.policy.get("policy_version")
                judge_model_id = result.judge_model_id
                judge_usage = result.judge_usage
                update.output_summary = {
                    "reason": result.reason,
                    "judge_usage": judge_usage,
                    "result": result.metadata,
                }
                update.judge_provider = result.judge_provider
                judge_usage_log = cls._record_judge_usage(
                    db,
                    policy=policy,
                    result=result,
                )
                if judge_usage_log is not None:
                    update.judge_usage_log_id = judge_usage_log.id
                    update.output_summary = {
                        **(update.output_summary or {}),
                        "judge_cost": float(judge_usage_log.total_cost or 0),
                    }

            if eligibility is not None:
                optimizer_summary = cls._optimizer_summary(
                    eligibility=eligibility,
                    optimization_result=optimization_result,
                )
                # JSONB는 MutableDict가 아니므로 이전 flush 뒤 in-place 수정하면
                # SQLAlchemy가 변경을 놓친다. 새 dict를 대입해 감사 이력에 남긴다.
                update.output_summary = {
                    **(update.output_summary or {}),
                    "optimizer": optimizer_summary,
                }
                if (
                    optimization_result is not None
                    and optimization_result.status == "applied"
                ):
                    proposed_active_policy = cls._optimized_active_policy(
                        policy,
                        optimization_result=optimization_result,
                        semantic_snapshot=semantic_snapshot,
                    )
                    result_status = "applied"
                    policy_version = ModelRoutingPolicyRefreshService._next_policy_version(
                        str(policy.policy_version or "v0")
                    )
                else:
                    proposed_active_policy = policy.active_policy or {}
                    result_status = (
                        "pending_review"
                        if eligibility.status == "needs_evidence"
                        else "kept_current"
                    )
                    policy_version = policy.policy_version

            # 자동 발견 cohort 경로에서는 judge가 만든 초안을 곧바로 runtime에
            # 적용하지 않는다. 실제 Replay 5회와 schema/downstream/품질 gate를
            # 통과한 후보만 validation task가 active policy rule로 승격한다.
            if bool((node_data or {}).get("auto_model_routing")) and result_status != "failed":
                result_status = "pending_review"
                policy_version = policy.policy_version

            ModelRoutingPolicyLifecycleService.apply_refresh_result(
                policy,
                status=result_status,
                proposed_policy=proposed_active_policy,
                policy_version=policy_version,
            )
            policy.last_refreshed_at = requested_at
            policy.refresh_requested_at = None
            policy.eligible_runs_since_last_refresh = cls._remaining_event_count(
                db, policy, requested_at
            )
            update.status = result_status
            update.judge_model = judge_model_id
            update.prompt_version = POLICY_JUDGE_PROMPT_VERSION if judge_model_id else None
            update.new_policy_version = policy_version if result_status == "applied" else None
            db.flush()
            return update
        except Exception as exc:
            logger.exception(
                "[Model-Routing] policy refresh failed: policy_id=%s trigger=%s error_type=%s",
                policy.id,
                trigger,
                type(exc).__name__,
            )
            ModelRoutingPolicyLifecycleService.apply_refresh_result(
                policy,
                status="failed",
                proposed_policy=policy.active_policy or {},
                policy_version=policy.policy_version,
            )
            policy.refresh_requested_at = None
            update.status = "failed"
            update.error_code = type(exc).__name__
            update.output_summary = {"reason": "judge policy refresh failed"}
            db.flush()
            return update

    @classmethod
    def _prepare_adaptive_refresh(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        update: LLMNodeModelRoutingPolicyUpdate,
        node_data: dict[str, Any],
        requested_at: datetime,
    ) -> LLMNodeModelRoutingPolicyUpdate:
        """외부 호출 없이 adaptive Replay 검증 batch를 준비한다.

        이 단계는 policy row의 상태와 운영 표본 수만 짧게 확정한다. 후보 모델의
        실제 출력 품질은 validation task에서 5회 Replay와 LLM judge로 확인한다.
        """
        # 자동 발견 route가 아직 없더라도 deployment에 이미 정의된 안전 semantic
        # catalog는 활성 policy에 보존한다. 이 catalog는 model_routing_context의
        # curated utterance를 activation 시 한 번만 embedding해 만들며, runtime은
        # 이후 저장된 vector만 평가한다.
        semantic_snapshot = cls._resolve_semantic_router_snapshot(
            db,
            policy=policy,
            node_data=node_data,
        )
        if semantic_snapshot is not None:
            active = (
                dict(policy.active_policy)
                if isinstance(policy.active_policy, dict)
                else {}
            )
            active["semantic_router"] = semantic_snapshot
            active["rules"] = cls._static_safety_rules(
                active.get("rules"),
                semantic_router=semantic_snapshot,
                default_model_id=cls._current_default_model(policy, node_data=node_data),
                fallback_model_id=str(node_data.get("fallback_model_id") or "").strip() or None,
            )
            policy.active_policy = active

        profile = ModelRouter.collect_profile(
            db,
            ModelRouterContext(
                workflow_id=str(policy.workflow_id),
                node_id=policy.node_id,
                current_model_id=node_data.get("model_id"),
                deployment_id=str(policy.deployment_id),
            ),
        )
        excluded_count = cls._excluded_run_count(db, policy, requested_at)
        # Replay/Judge batch가 끝나기 전에는 다음 run이 같은 policy refresh를
        # 중복 예약하면 안 된다. refresh_requested_at lease와 refreshing 상태는
        # validation service의 finalization에서만 해제한다.
        policy.status = "refreshing"
        policy.last_refreshed_at = requested_at
        policy.last_refresh_result = "pending_review"
        update.status = "pending_review"
        update.eligible_run_count = profile.operational_usable_runs
        update.excluded_run_count = excluded_count
        update.excluded_reason_summary = {
            "missing_usage_or_output": excluded_count,
        }
        update.input_summary = {
            "node_summary": cls._safe_node_summary(node_data),
            "model_profile": profile.as_snapshot(),
            "adaptive_validation": {
                "replays_per_candidate": 5,
                "judge_called": False,
            },
        }
        update.output_summary = {
            "reason": "후보별 실제 Replay와 quality judge 검증을 예약합니다.",
            "adaptive_validation": {
                "status": "planning",
                "judge_called": False,
            },
        }
        update.error_code = None
        update.judge_model = None
        update.judge_provider = None
        update.prompt_version = None
        update.new_policy_version = None
        db.flush()
        return update

    @staticmethod
    def _static_safety_rules(
        current_rules: Any,
        *,
        semantic_router: dict[str, Any],
        default_model_id: str,
        fallback_model_id: str | None,
    ) -> list[dict[str, Any]]:
        """저장된 catalog의 safety route를 baseline 고정 rule로 투영한다.

        도메인 키워드를 코드에 두지 않는다. catalog에서 ``safety_override``로
        선언된 route만 읽어, 해당 입력군은 검증 전 저비용 후보로 내려가지 않게 한다.
        """
        existing = [rule for rule in current_rules or [] if isinstance(rule, dict)]
        retained = [
            rule
            for rule in existing
            if str(rule.get("reason_code") or "") != "safety_override_baseline"
        ]
        routes = semantic_router.get("routes") if isinstance(semantic_router, dict) else []
        safety_rules: list[dict[str, Any]] = []
        for route in routes if isinstance(routes, list) else []:
            if not isinstance(route, dict) or not route.get("safety_override"):
                continue
            cohort_id = str(route.get("cohort_id") or "").strip()
            if not cohort_id or not default_model_id:
                continue
            safety_rules.append(
                {
                    "id": f"safety-baseline-{cohort_id}",
                    "when": {"semantic_cohort_id": cohort_id},
                    "selected_model_id": default_model_id,
                    "fallback_model_id": fallback_model_id,
                    "priority": 10,
                    "reason_code": "safety_override_baseline",
                }
            )
        return [*safety_rules, *retained]

    @staticmethod
    def _has_active_adaptive_rule(active_policy: Any) -> bool:
        """정적 안전 rule과 검증 완료된 할인 route를 구분한다."""
        if not isinstance(active_policy, dict):
            return False
        return any(
            isinstance(rule, dict)
            and str(rule.get("reason_code") or "") == "validated_adaptive_cohort"
            and isinstance(rule.get("when"), dict)
            and bool(rule["when"].get("semantic_cohort_id"))
            for rule in active_policy.get("rules") or []
        )

    @staticmethod
    def _current_default_model(policy, *, node_data: dict[str, Any]) -> str:
        active_policy = (
            policy.active_policy if isinstance(policy.active_policy, dict) else {}
        )
        return str(
            active_policy.get("default_model_id")
            or node_data.get("model_id")
            or ""
        ).strip()

    @staticmethod
    def _routing_objective(node_data: dict[str, Any]) -> str:
        context = node_data.get("model_routing_context")
        context = context if isinstance(context, dict) else {}
        objective = str(context.get("objective") or "cost").lower()
        return "latency" if objective == "latency" else "cost"

    @staticmethod
    def _embedding_cost_per_request(node_data: dict[str, Any]) -> float:
        context = node_data.get("model_routing_context")
        context = context if isinstance(context, dict) else {}
        semantic = context.get("semantic_router")
        semantic = semantic if isinstance(semantic, dict) else {}
        try:
            return max(
                0.0,
                float(semantic.get("estimated_embedding_cost_per_request") or 0),
            )
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _evidence_version(samples, *, node_fingerprint: str) -> str:
        identifiers = sorted(
            str(getattr(sample, "candidate_id", "") or "")
            for sample in samples
        )
        catalog_versions = sorted(
            {
                str(getattr(sample, "route_catalog_version", "") or "")
                for sample in samples
            }
        )
        payload = "|".join(
            [node_fingerprint, *catalog_versions, *identifiers]
        )
        return f"evidence-{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:16]}"

    @classmethod
    def _optimized_active_policy(
        cls,
        policy,
        *,
        optimization_result,
        semantic_snapshot: dict[str, Any] | None,
    ) -> dict[str, Any]:
        active = (
            dict(policy.active_policy)
            if isinstance(policy.active_policy, dict)
            else {}
        )
        existing_rules = [
            rule
            for rule in active.get("rules") or []
            if isinstance(rule, dict)
            and not (
                isinstance(rule.get("when"), dict)
                and rule["when"].get("semantic_cohort_id")
            )
        ]
        active["rules"] = [*existing_rules, *optimization_result.rules]
        active["strategy"] = "workflow_aware_adaptive"
        active["evidence_version"] = (
            optimization_result.rules[0].get("evidence_version")
            if optimization_result.rules
            else None
        )
        active["gate_profile_version"] = (
            optimization_result.rules[0].get("gate_profile_version")
            if optimization_result.rules
            else None
        )
        if semantic_snapshot is not None:
            active["semantic_router"] = semantic_snapshot
        return active

    @staticmethod
    def _optimizer_summary(*, eligibility, optimization_result) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "status": (
                optimization_result.status
                if optimization_result is not None
                else eligibility.status
            ),
            "eligibility_reason_code": eligibility.reason_code,
            "eligible_model_count": len(eligibility.eligible_model_ids),
            "evidence_model_count": len(eligibility.evidence_model_ids),
        }
        if optimization_result is None:
            return summary
        summary.update(
            {
                "rule_count": len(optimization_result.rules),
                "expected_net_savings": optimization_result.expected_net_savings,
                "cohort_decisions": [
                    {
                        "cohort_id": decision.cohort_id,
                        "selected_model_id": decision.selected_model_id,
                        "baseline_model_id": decision.baseline_model_id,
                        "reason_code": decision.reason_code,
                        "sample_count": decision.candidate_sample_count,
                        "expected_net_savings": decision.expected_net_savings,
                        "candidate_quality_lower_bound": (
                            decision.candidate_quality_lower_bound
                        ),
                        "baseline_quality_lower_bound": (
                            decision.baseline_quality_lower_bound
                        ),
                    }
                    for decision in optimization_result.cohort_decisions
                ],
            }
        )
        return summary

    @staticmethod
    def _record_judge_usage(db: Session, *, policy, result):
        """judge 호출 비용을 usage log로 남기되 운영 node profile에는 섞지 않는다."""
        credential_id = getattr(result, "judge_credential_id", None)
        model_id = getattr(result, "judge_model_id", None)
        usage = result.judge_usage if isinstance(result.judge_usage, dict) else {}
        if not credential_id or not model_id or not usage:
            return None

        prompt_tokens = int(usage.get("prompt_tokens") or 0)
        completion_tokens = int(usage.get("completion_tokens") or 0)
        cost = LLMService.calculate_cost(
            db,
            model_id,
            prompt_tokens,
            completion_tokens,
        )
        return LLMService.log_usage(
            db,
            user_id=policy.judge_user_id,
            model_id=model_id,
            usage=usage,
            cost=cost,
            organization_id=policy.organization_id,
            workflow_id=policy.workflow_id,
            node_id=f"{policy.node_id}:model-routing-judge",
            credential_id=credential_id,
        )

    @staticmethod
    def _as_router_policy(policy: LLMNodeModelRoutingPolicy) -> dict[str, Any]:
        return {
            "policy_id": str(policy.id),
            "policy_version": policy.policy_version,
            "active_policy": policy.active_policy or {},
            "refresh": {"refresh_every_runs": policy.refresh_every_runs},
        }

    @staticmethod
    def _node_data(graph: dict[str, Any], node_id: str) -> dict[str, Any] | None:
        for node in graph.get("nodes") or []:
            if isinstance(node, dict) and str(node.get("id")) == node_id:
                data = node.get("data")
                return data if isinstance(data, dict) else None
        return None

    @staticmethod
    def _safe_node_summary(node_data: dict[str, Any]) -> dict[str, Any]:
        output_format = node_data.get("output_format")
        if not isinstance(output_format, dict):
            output_format = {}
        routing_context = node_data.get("model_routing_context")
        routing_context = (
            routing_context if isinstance(routing_context, dict) else {}
        )
        safe_routing_context = {
            key: routing_context[key]
            for key in (
                "customer_facing",
                "node_task",
                "category",
                "risk_level",
            )
            if key in routing_context
        }
        semantic_source = routing_context.get("semantic_router")
        semantic_source = (
            semantic_source if isinstance(semantic_source, dict) else {}
        )
        routes = semantic_source.get("routes")
        routes = routes if isinstance(routes, list) else []
        safe_semantic_summary = None
        if semantic_source:
            safe_semantic_summary = {
                "route_catalog_version": semantic_source.get(
                    "route_catalog_version"
                ),
                "encoder_model_id": semantic_source.get("encoder_model_id"),
                "route_count": len(routes),
                "cohort_ids": [
                    str(route.get("cohort_id"))
                    for route in routes
                    if isinstance(route, dict) and route.get("cohort_id")
                ],
                "safety_override_route_count": sum(
                    1
                    for route in routes
                    if isinstance(route, dict) and route.get("safety_override") is True
                ),
                "lexical_signal_count": sum(
                    len(route.get("lexical_signals") or [])
                    for route in routes
                    if isinstance(route, dict)
                    and isinstance(route.get("lexical_signals"), list)
                ),
            }
        return {
            "output_format": output_format.get("type") or "text",
            "schema_required": bool(output_format.get("schema")),
            "knowledge_enabled": bool(
                node_data.get("knowledgeBases")
                or node_data.get("knowledgeCollections")
            ),
            "has_fallback_model": bool(node_data.get("fallback_model_id")),
            "model_routing_context": safe_routing_context,
            "semantic_router": safe_semantic_summary,
        }

    @staticmethod
    def _semantic_router_snapshot(
        db: Session,
        *,
        node_data: dict[str, Any],
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
    ) -> dict[str, Any] | None:
        routing_context = node_data.get("model_routing_context")
        routing_context = (
            routing_context if isinstance(routing_context, dict) else {}
        )
        source = routing_context.get("semantic_router")
        if not isinstance(source, dict) or not source:
            return None
        encoder_model_id = str(source.get("encoder_model_id") or "").strip()
        if not encoder_model_id:
            raise ValueError("semantic router encoder_model_id is required")
        selection = LLMService.get_runtime_client_for_user(
            db,
            user_id=user_id,
            model_id=encoder_model_id,
            organization_id=organization_id,
        )
        return SemanticRouteCatalogBuilder.build(
            source,
            embed=selection.client.embed_sync,
        )

    @classmethod
    def _resolve_semantic_router_snapshot(
        cls,
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        adaptive_snapshot = cls._adaptive_semantic_router_snapshot(
            db,
            policy=policy,
            node_data=node_data,
        )
        if adaptive_snapshot is not None:
            return adaptive_snapshot

        routing_context = node_data.get("model_routing_context")
        routing_context = (
            routing_context if isinstance(routing_context, dict) else {}
        )
        source = routing_context.get("semantic_router")
        if not isinstance(source, dict) or not source:
            return None
        # Adaptive 입력군은 encoder와 입력 경로만 먼저 설정할 수 있다. 정적
        # catalog의 필수 routes가 없으면 catalog builder가 아니라 관찰 수집
        # 설정으로만 취급한다.
        routes = source.get("routes")
        if not isinstance(routes, list) or not routes:
            return None

        active_policy = (
            policy.active_policy if isinstance(policy.active_policy, dict) else {}
        )
        active_snapshot = active_policy.get("semantic_router")
        if isinstance(active_snapshot, dict):
            same_version = active_snapshot.get("route_catalog_version") == source.get(
                "route_catalog_version"
            )
            same_encoder = active_snapshot.get("encoder_model_id") == source.get(
                "encoder_model_id"
            )
            if same_version and same_encoder:
                return active_snapshot

        if policy.judge_user_id is None or policy.organization_id is None:
            raise ValueError("semantic router activation principal is unavailable")
        return cls._semantic_router_snapshot(
            db,
            node_data=node_data,
            user_id=policy.judge_user_id,
            organization_id=policy.organization_id,
        )

    @staticmethod
    def _adaptive_semantic_router_snapshot(
        db: Session,
        *,
        policy: LLMNodeModelRoutingPolicy,
        node_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        """검증된 자동 입력군 catalog를 lifecycle 변경 없이 읽는다.

        입력군 발견과 휴면 판정은 validation ``plan_batch``가 한 번만 수행한다.
        snapshot 조회에서도 전진시키면 한 refresh 안에서 같은 관찰값이 두 번
        반영되어 저빈도 입력군이 예상보다 빨리 dormant 상태가 된다.
        """
        try:
            from apps.workflow_engine.services.model_routing_adaptive_store import (
                AdaptiveModelRoutingCohortStore,
            )

            return AdaptiveModelRoutingCohortStore.build_runtime_catalog(
                db,
                policy_id=policy.id,
                policy=policy,
                node_data=node_data,
            )
        except Exception as exc:
            # 입력군 부가 기능이 일시적으로 실패해도 기존 수동 semantic catalog와
            # 현재 active policy 실행은 유지한다. 오류는 refresh update에 남긴다.
            logger.warning(
                "[Model-Routing] adaptive cohort snapshot skipped: error_type=%s",
                type(exc).__name__,
            )
            return None

    @staticmethod
    def _safe_recent_runs(profile) -> list[dict[str, Any]]:
        return [
            {"model_id": model_id, **summary}
            for model_id, summary in profile.as_snapshot()["model_performance"].items()
        ]

    @staticmethod
    def _safe_segment_profiles(profile) -> list[dict[str, Any]]:
        snapshot = profile.as_snapshot()
        segments = snapshot.get("segment_performance")
        return segments if isinstance(segments, list) else []

    @staticmethod
    def _select_judge_model(candidates, *, current_model_id: Any) -> str:
        """현재 운영 모델을 우선하고, 없으면 안정적인 순서로 judge 모델을 고른다."""
        current_model_id = str(current_model_id or "").strip()
        for candidate in candidates:
            if candidate.model_id == current_model_id:
                return candidate.model_id
        ordered = sorted(
            candidates,
            key=lambda candidate: (candidate.price_score, candidate.model_id),
        )
        return ordered[len(ordered) // 2].model_id

    @staticmethod
    def _remaining_event_count(
        db: Session,
        policy: LLMNodeModelRoutingPolicy,
        cutoff: datetime,
    ) -> int:
        return (
            db.query(LLMNodeModelRoutingPolicyRunEvent)
            .filter(LLMNodeModelRoutingPolicyRunEvent.policy_id == policy.id)
            .filter(LLMNodeModelRoutingPolicyRunEvent.created_at > cutoff)
            .count()
        )

    @staticmethod
    def _excluded_run_count(
        db: Session,
        policy: LLMNodeModelRoutingPolicy,
        cutoff: datetime,
    ) -> int:
        total = (
            db.query(LLMNodeModelRoutingPolicyRunEvent)
            .filter(LLMNodeModelRoutingPolicyRunEvent.policy_id == policy.id)
            .filter(LLMNodeModelRoutingPolicyRunEvent.created_at <= cutoff)
            .count()
        )
        profile = ModelRouter.collect_profile(
            db,
            ModelRouterContext(
                workflow_id=str(policy.workflow_id),
                node_id=policy.node_id,
                current_model_id=None,
                deployment_id=str(policy.deployment_id),
            ),
        )
        return max(0, total - profile.operational_usable_runs)
