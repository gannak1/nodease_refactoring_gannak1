"""재배포 시 검증된 모델 라우팅 상태를 새 배포 snapshot으로 전달한다."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from apps.shared.db.models.model_routing_cohort import (
    LLMNodeModelRoutingCohort,
    LLMNodeModelRoutingCohortExample,
    LLMNodeModelRoutingModelEvidence,
)
from apps.shared.db.models.model_routing_policy import LLMNodeModelRoutingPolicy


class ModelRoutingPolicyInheritanceService:
    """같은 LLM node의 검증된 routing 상태를 새 활성 배포로 복제한다."""

    @classmethod
    def inherit_for_deployment(
        cls,
        db: Session,
        *,
        workflow_id: UUID,
        source_deployment_id: UUID | None,
        target_deployment_id: UUID,
        target_graph: dict[str, Any],
    ) -> int:
        """이전 활성 배포의 policy/cohort/evidence를 새 배포로 복제한다.

        실행 카운터, 진행 중 refresh, 운영 관찰값과 월간 검증 비용은 배포별 실행
        이력이므로 옮기지 않는다. 반면 active policy와 검증 완료 evidence는 같은
        node 설정을 다시 배포해도 그대로 사용할 수 있는 판단 근거다.
        """
        if source_deployment_id is None or source_deployment_id == target_deployment_id:
            return 0

        target_routing_nodes = cls._automatic_routing_node_ids(target_graph)
        if not target_routing_nodes:
            return 0

        source_policies = (
            db.query(LLMNodeModelRoutingPolicy)
            .filter(LLMNodeModelRoutingPolicy.workflow_id == workflow_id)
            .filter(LLMNodeModelRoutingPolicy.deployment_id == source_deployment_id)
            .all()
        )
        inherited_count = 0
        for source_policy in source_policies:
            if source_policy.node_id not in target_routing_nodes:
                continue
            existing_target = (
                db.query(LLMNodeModelRoutingPolicy)
                .filter(LLMNodeModelRoutingPolicy.workflow_id == workflow_id)
                .filter(LLMNodeModelRoutingPolicy.deployment_id == target_deployment_id)
                .filter(LLMNodeModelRoutingPolicy.node_id == source_policy.node_id)
                .first()
            )
            if existing_target is not None:
                continue

            target_policy = LLMNodeModelRoutingPolicy(
                organization_id=source_policy.organization_id,
                workflow_id=workflow_id,
                deployment_id=target_deployment_id,
                node_id=source_policy.node_id,
                enabled=source_policy.enabled,
                status="active" if source_policy.active_policy else "collecting",
                policy_version=source_policy.policy_version,
                active_policy=deepcopy(source_policy.active_policy or {}),
                pending_policy=None,
                refresh_every_runs=source_policy.refresh_every_runs,
                eligible_runs_since_last_refresh=0,
                refresh_requested_at=None,
                last_refreshed_at=source_policy.last_refreshed_at,
                last_refresh_result=source_policy.last_refresh_result,
                judge_user_id=source_policy.judge_user_id,
                execution_subject_user_id=source_policy.execution_subject_user_id,
                validation_budget_usd=source_policy.validation_budget_usd,
                max_cohorts=source_policy.max_cohorts,
            )
            db.add(target_policy)
            db.flush()
            cohort_id_map = cls._inherit_cohorts_and_evidence(
                db,
                source_policy_id=source_policy.id,
                target_policy_id=target_policy.id,
            )
            target_policy.active_policy = cls._remap_cohort_references(
                target_policy.active_policy,
                cohort_id_map,
            )
            inherited_count += 1
        return inherited_count

    @staticmethod
    def _automatic_routing_node_ids(graph: dict[str, Any]) -> set[str]:
        nodes = graph.get("nodes") if isinstance(graph, dict) else None
        if not isinstance(nodes, list):
            return set()
        return {
            str(node.get("id"))
            for node in nodes
            if isinstance(node, dict)
            and node.get("type") == "llmNode"
            and isinstance(node.get("data"), dict)
            and node["data"].get("auto_model_routing") is True
            and node.get("id")
        }

    @classmethod
    def _inherit_cohorts_and_evidence(
        cls,
        db: Session,
        *,
        source_policy_id: UUID,
        target_policy_id: UUID,
    ) -> dict[str, str]:
        source_cohorts = (
            db.query(LLMNodeModelRoutingCohort)
            .filter(LLMNodeModelRoutingCohort.policy_id == source_policy_id)
            .all()
        )
        source_cohort_ids = [cohort.id for cohort in source_cohorts]
        examples_by_cohort: dict[UUID, list[LLMNodeModelRoutingCohortExample]] = {}
        evidence_by_cohort: dict[UUID, list[LLMNodeModelRoutingModelEvidence]] = {}
        if source_cohort_ids:
            source_examples = (
                db.query(LLMNodeModelRoutingCohortExample)
                .filter(LLMNodeModelRoutingCohortExample.cohort_id.in_(source_cohort_ids))
                .all()
            )
            for example in source_examples:
                examples_by_cohort.setdefault(example.cohort_id, []).append(example)
            source_evidence = (
                db.query(LLMNodeModelRoutingModelEvidence)
                .filter(LLMNodeModelRoutingModelEvidence.cohort_id.in_(source_cohort_ids))
                .all()
            )
            for evidence in source_evidence:
                evidence_by_cohort.setdefault(evidence.cohort_id, []).append(evidence)

        cohort_id_map: dict[str, str] = {}
        for source_cohort in source_cohorts:
            target_cohort = LLMNodeModelRoutingCohort(
                policy_id=target_policy_id,
                cohort_key=source_cohort.cohort_key,
                label=source_cohort.label,
                label_en=source_cohort.label_en,
                source=source_cohort.source,
                status=source_cohort.status,
                required=source_cohort.required,
                safety_protected=source_cohort.safety_protected,
                encoder_model_id=source_cohort.encoder_model_id,
                centroid_embedding=deepcopy(source_cohort.centroid_embedding or []),
                observation_count=source_cohort.observation_count,
                review_window_count=source_cohort.review_window_count,
                low_share_streak=source_cohort.low_share_streak,
                last_traffic_share=source_cohort.last_traffic_share,
                node_config_fingerprint=source_cohort.node_config_fingerprint,
                first_seen_at=source_cohort.first_seen_at,
                last_seen_at=source_cohort.last_seen_at,
                dormant_since=source_cohort.dormant_since,
                retired_at=source_cohort.retired_at,
            )
            db.add(target_cohort)
            db.flush()
            cohort_id_map[str(source_cohort.id)] = str(target_cohort.id)
            for source_example in examples_by_cohort.get(source_cohort.id, []):
                db.add(
                    LLMNodeModelRoutingCohortExample(
                        cohort_id=target_cohort.id,
                        synthetic_text=source_example.synthetic_text,
                        embedding=deepcopy(source_example.embedding or []),
                        ordinal=source_example.ordinal,
                    )
                )
            for source_evidence in evidence_by_cohort.get(source_cohort.id, []):
                db.add(
                    LLMNodeModelRoutingModelEvidence(
                        cohort_id=target_cohort.id,
                        model_id=source_evidence.model_id,
                        node_config_fingerprint=source_evidence.node_config_fingerprint,
                        evidence_version=source_evidence.evidence_version,
                        status=source_evidence.status,
                        sample_count=source_evidence.sample_count,
                        quality_summary=deepcopy(source_evidence.quality_summary or {}),
                        efficiency_summary=deepcopy(source_evidence.efficiency_summary or {}),
                        source_candidate_ids=deepcopy(source_evidence.source_candidate_ids or []),
                        validated_at=source_evidence.validated_at,
                        expires_at=source_evidence.expires_at,
                    )
                )
        return cohort_id_map

    @staticmethod
    def _remap_cohort_references(
        active_policy: dict[str, Any],
        cohort_id_map: dict[str, str],
    ) -> dict[str, Any]:
        """새 cohort row를 가리키도록 runtime policy의 ID 참조를 갱신한다."""
        remapped = deepcopy(active_policy or {})
        rules = remapped.get("rules")
        if isinstance(rules, list):
            for rule in rules:
                if not isinstance(rule, dict):
                    continue
                when = rule.get("when")
                if not isinstance(when, dict):
                    continue
                source_id = str(when.get("semantic_cohort_id") or "")
                if source_id in cohort_id_map:
                    when["semantic_cohort_id"] = cohort_id_map[source_id]

        semantic_router = remapped.get("semantic_router")
        routes = semantic_router.get("routes") if isinstance(semantic_router, dict) else None
        if isinstance(routes, list):
            for route in routes:
                if not isinstance(route, dict):
                    continue
                source_id = str(route.get("cohort_id") or "")
                if source_id in cohort_id_map:
                    route["cohort_id"] = cohort_id_map[source_id]
        return remapped
