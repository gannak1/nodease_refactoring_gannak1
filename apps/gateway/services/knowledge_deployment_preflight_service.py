"""Knowledge/RAG deployment preflight checks.

This service validates whether KB references in a workflow snapshot are safe for
the runtime audience that a deployment surface will actually use. It deliberately
returns only redaction-safe reason codes and bucketed counts.
"""

import uuid
from dataclasses import dataclass
from typing import Iterable

from fastapi import HTTPException
from sqlalchemy.orm import Session

from apps.shared.db.models.app import App
from apps.shared.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
)
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment
from apps.shared.schemas.deployment import (
    DeploymentPreflightAudience,
    DeploymentPreflightNodeResult,
    DeploymentPreflightRequiredAction,
    DeploymentPreflightResponse,
    DeploymentPreflightStatus,
    DeploymentPreflightSummary,
)

PUBLIC_REQUIRED_ACTIONS = {
    "private_kb_requires_execution_subject": DeploymentPreflightRequiredAction(
        action="remove_private_kb_or_use_authenticated_run",
        label="Private KB를 제거하거나 인증 실행 경로를 사용하세요",
    ),
    "source_public_exposure_required": DeploymentPreflightRequiredAction(
        action="approve_source_public_exposure_or_remove_kb",
        label="Source 공개 승인 정책을 추가하거나 해당 KB를 제거하세요",
    ),
    "knowledge_base_unavailable": DeploymentPreflightRequiredAction(
        action="remove_unavailable_kb_reference",
        label="사용할 수 없는 KB 참조를 제거하세요",
    ),
    "workflow_node_target_unavailable": DeploymentPreflightRequiredAction(
        action="fix_workflow_node_target_or_remove_reference",
        label="서브 모듈 대상 배포를 복구하거나 노드를 제거하세요",
    ),
    "workflow_node_cycle_detected": DeploymentPreflightRequiredAction(
        action="remove_recursive_workflow_node_reference",
        label="순환되는 서브 모듈 참조를 제거하세요",
    ),
}

WARNING_REQUIRED_ACTIONS = {
    "workflow_node_execution_subject_inherited": DeploymentPreflightRequiredAction(
        action="verify_parent_execution_subject",
        label="상위 워크플로우 실행 주체가 KB 권한을 제공하는지 확인하세요",
    ),
}


@dataclass(frozen=True)
class _PreflightIssue:
    node_id: str | None
    node_type: str
    severity: DeploymentPreflightStatus
    reason_code: str
    knowledge_base_count: int = 0


class KnowledgeDeploymentPreflightService:
    """Evaluates Knowledge/RAG availability for deployment publishing."""

    ANONYMOUS_PUBLIC_TYPES = {
        DeploymentType.API,
        DeploymentType.WEBAPP,
        DeploymentType.WIDGET,
        DeploymentType.CHATBOT,
        DeploymentType.MCP,
        DeploymentType.SCHEDULE,
        DeploymentType.WEBHOOK,
    }
    MAX_WORKFLOW_NODE_DEPTH = 3

    def __init__(
        self,
        db: Session,
        *,
        organization_id: uuid.UUID | None,
        candidate_graphs_by_app_id: dict[uuid.UUID, dict] | None = None,
    ) -> None:
        self.db = db
        self.organization_id = organization_id
        self.candidate_graphs_by_app_id = candidate_graphs_by_app_id or {}

    def preview(
        self,
        *,
        deployment_type: DeploymentType,
        graph_snapshot: dict,
        audience_hint: DeploymentPreflightAudience | None = None,
    ) -> DeploymentPreflightResponse:
        audience = self._effective_audience(deployment_type, audience_hint)
        issues = self._evaluate_graph(
            graph_snapshot,
            audience=audience,
            depth=0,
            visited_app_ids=set(self.candidate_graphs_by_app_id.keys()),
        )
        return self._response(audience, issues)

    def enforce_active_publish(
        self,
        *,
        deployment_type: DeploymentType,
        graph_snapshot: dict,
    ) -> DeploymentPreflightResponse:
        response = self.preview(
            deployment_type=deployment_type,
            graph_snapshot=graph_snapshot,
            audience_hint=None,
        )
        if response.status == "blocked":
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "deployment.preflight.blocked",
                        "message": "Deployment preflight blocked activation",
                        "reason_code": response.safe_summary.blocked_reason,
                        "required_actions": [
                            action.action for action in response.required_actions
                        ],
                        "preflight": response.model_dump(mode="json"),
                    }
                },
            )
        return response

    @classmethod
    def server_derived_audience(
        cls,
        deployment_type: DeploymentType,
    ) -> DeploymentPreflightAudience:
        if deployment_type == DeploymentType.WORKFLOW_NODE:
            return "workflow_node_inherited"
        if deployment_type in cls.ANONYMOUS_PUBLIC_TYPES:
            return "anonymous_public"
        return "anonymous_public"

    def _effective_audience(
        self,
        deployment_type: DeploymentType,
        audience_hint: DeploymentPreflightAudience | None,
    ) -> DeploymentPreflightAudience:
        derived = self.server_derived_audience(deployment_type)
        if audience_hint == "anonymous_public":
            return "anonymous_public"
        return derived

    def _evaluate_graph(
        self,
        graph_snapshot: dict,
        *,
        audience: DeploymentPreflightAudience,
        depth: int,
        visited_app_ids: set[uuid.UUID],
    ) -> list[_PreflightIssue]:
        if not isinstance(graph_snapshot, dict):
            return []
        nodes = graph_snapshot.get("nodes")
        if not isinstance(nodes, list):
            return []

        issues: list[_PreflightIssue] = []
        for node in nodes:
            if not isinstance(node, dict):
                continue
            node_id = self._safe_node_id(node)
            node_type = self._safe_node_type(node)
            data = node.get("data")
            if not isinstance(data, dict):
                data = {}

            kb_ids, invalid_count = self._extract_knowledge_base_ids(data)
            if invalid_count:
                issues.append(
                    _PreflightIssue(
                        node_id=node_id,
                        node_type=node_type,
                        severity="blocked"
                        if audience == "anonymous_public"
                        else "warning",
                        reason_code="knowledge_base_unavailable",
                        knowledge_base_count=invalid_count,
                    )
                )
            if kb_ids:
                issues.extend(
                    self._evaluate_kb_references(
                        kb_ids,
                        node_id=node_id,
                        node_type=node_type,
                        audience=audience,
                    )
                )

            if node_type == "workflowNode":
                issues.extend(
                    self._evaluate_workflow_node_target(
                        data,
                        node_id=node_id,
                        node_type=node_type,
                        audience=audience,
                        depth=depth,
                        visited_app_ids=visited_app_ids,
                    )
                )

        return issues

    def _evaluate_kb_references(
        self,
        kb_ids: list[uuid.UUID],
        *,
        node_id: str | None,
        node_type: str,
        audience: DeploymentPreflightAudience,
    ) -> list[_PreflightIssue]:
        if audience == "workflow_node_inherited":
            return [
                _PreflightIssue(
                    node_id=node_id,
                    node_type=node_type,
                    severity="warning",
                    reason_code="workflow_node_execution_subject_inherited",
                    knowledge_base_count=len(kb_ids),
                )
            ]
        if audience == "authenticated_user":
            return []

        kbs_by_id = self._active_kbs_by_id(kb_ids)
        public_eligible_ids = self._public_runtime_eligible_kb_ids(kb_ids)
        issue_counts: dict[str, int] = {}

        for kb_id in kb_ids:
            kb = kbs_by_id.get(kb_id)
            if kb is None:
                issue_counts["knowledge_base_unavailable"] = (
                    issue_counts.get("knowledge_base_unavailable", 0) + 1
                )
                continue
            if kb_id not in public_eligible_ids:
                issue_counts["private_kb_requires_execution_subject"] = (
                    issue_counts.get("private_kb_requires_execution_subject", 0) + 1
                )
                continue
            if getattr(kb, "source_identity_id", None) is not None:
                issue_counts["source_public_exposure_required"] = (
                    issue_counts.get("source_public_exposure_required", 0) + 1
                )

        return [
            _PreflightIssue(
                node_id=node_id,
                node_type=node_type,
                severity="blocked",
                reason_code=reason_code,
                knowledge_base_count=count,
            )
            for reason_code, count in sorted(issue_counts.items())
        ]

    def _evaluate_workflow_node_target(
        self,
        data: dict,
        *,
        node_id: str | None,
        node_type: str,
        audience: DeploymentPreflightAudience,
        depth: int,
        visited_app_ids: set[uuid.UUID],
    ) -> list[_PreflightIssue]:
        if depth >= self.MAX_WORKFLOW_NODE_DEPTH:
            return [
                _PreflightIssue(
                    node_id=node_id,
                    node_type=node_type,
                    severity="blocked"
                    if audience == "anonymous_public"
                    else "warning",
                    reason_code="workflow_node_target_unavailable",
                )
            ]

        target_app_id = self._uuid_or_none(data.get("appId"))
        if target_app_id is None:
            return [
                _PreflightIssue(
                    node_id=node_id,
                    node_type=node_type,
                    severity="blocked"
                    if audience == "anonymous_public"
                    else "warning",
                    reason_code="workflow_node_target_unavailable",
                )
            ]
        if target_app_id in visited_app_ids:
            return [
                _PreflightIssue(
                    node_id=node_id,
                    node_type=node_type,
                    severity="blocked"
                    if audience == "anonymous_public"
                    else "warning",
                    reason_code="workflow_node_cycle_detected",
                )
            ]

        target_app = self._target_app(target_app_id)
        if not target_app or not getattr(target_app, "active_deployment_id", None):
            return [
                _PreflightIssue(
                    node_id=node_id,
                    node_type=node_type,
                    severity="blocked"
                    if audience == "anonymous_public"
                    else "warning",
                    reason_code="workflow_node_target_unavailable",
                )
            ]

        candidate_graph = self.candidate_graphs_by_app_id.get(target_app_id)
        if candidate_graph is not None:
            return self._evaluate_graph(
                candidate_graph,
                audience=audience,
                depth=depth + 1,
                visited_app_ids={*visited_app_ids, target_app_id},
            )

        deployment_id = self._uuid_or_none(target_app.active_deployment_id)
        if deployment_id is None:
            return [
                _PreflightIssue(
                    node_id=node_id,
                    node_type=node_type,
                    severity="blocked"
                    if audience == "anonymous_public"
                    else "warning",
                    reason_code="workflow_node_target_unavailable",
                )
            ]
        target_deployment = (
            self.db.query(WorkflowDeployment)
            .filter(
                WorkflowDeployment.id == deployment_id,
                WorkflowDeployment.app_id == target_app.id,
                WorkflowDeployment.is_active.is_(True),
            )
            .first()
        )
        if target_deployment is None:
            return [
                _PreflightIssue(
                    node_id=node_id,
                    node_type=node_type,
                    severity="blocked"
                    if audience == "anonymous_public"
                    else "warning",
                    reason_code="workflow_node_target_unavailable",
                )
            ]

        return self._evaluate_graph(
            target_deployment.graph_snapshot,
            audience=audience,
            depth=depth + 1,
            visited_app_ids={*visited_app_ids, target_app_id},
        )

    def _target_app(self, target_app_id: uuid.UUID) -> App | None:
        query = self.db.query(App).filter(App.id == target_app_id)
        if self.organization_id is not None:
            query = query.filter(App.organization_id == self.organization_id)
        return query.first()

    def _active_kbs_by_id(
        self,
        kb_ids: Iterable[uuid.UUID],
    ) -> dict[uuid.UUID, KnowledgeBase]:
        ids = self._dedupe_ids(kb_ids)
        if not ids or self.organization_id is None:
            return {}
        rows = (
            self.db.query(KnowledgeBase)
            .filter(
                KnowledgeBase.id.in_(ids),
                KnowledgeBase.organization_id == self.organization_id,
                KnowledgeBase.lifecycle_state == "active",
            )
            .all()
        )
        return {row.id: row for row in rows}

    def _public_runtime_eligible_kb_ids(
        self,
        kb_ids: Iterable[uuid.UUID],
    ) -> set[uuid.UUID]:
        ids = self._dedupe_ids(kb_ids)
        if not ids or self.organization_id is None:
            return set()

        items = (
            self.db.query(KnowledgeCollectionItem)
            .filter(
                KnowledgeCollectionItem.organization_id == self.organization_id,
                KnowledgeCollectionItem.knowledge_base_id.in_(ids),
            )
            .all()
        )
        collection_ids = self._dedupe_ids(item.collection_id for item in items)
        if not collection_ids:
            return set()

        collections = (
            self.db.query(KnowledgeCollection)
            .filter(
                KnowledgeCollection.id.in_(collection_ids),
                KnowledgeCollection.organization_id == self.organization_id,
                KnowledgeCollection.lifecycle_state == "active",
            )
            .all()
        )
        public_collection_ids = {
            collection.id
            for collection in collections
            if (getattr(collection, "safe_metadata", None) or {}).get("visibility")
            == "public"
        }
        return {
            item.knowledge_base_id
            for item in items
            if item.collection_id in public_collection_ids
        }

    def _response(
        self,
        audience: DeploymentPreflightAudience,
        issues: list[_PreflightIssue],
    ) -> DeploymentPreflightResponse:
        node_results = self._node_results(issues)
        status: DeploymentPreflightStatus = "passed"
        if any(issue.severity == "blocked" for issue in issues):
            status = "blocked"
        elif any(issue.severity == "warning" for issue in issues):
            status = "warning"

        first_reason = next((issue.reason_code for issue in issues), None)
        affected_kb_count = sum(issue.knowledge_base_count for issue in issues)
        required_actions = self._required_actions(issues)
        warnings = [
            issue.reason_code
            for issue in issues
            if issue.severity == "warning"
        ]
        return DeploymentPreflightResponse(
            status=status,
            audience=audience,
            safe_summary=DeploymentPreflightSummary(
                blocked_reason=first_reason,
                affected_node_count=len(node_results),
                affected_kb_count_bucket=self._bucket_count(affected_kb_count),
            ),
            required_actions=required_actions,
            warnings=list(dict.fromkeys(warnings)),
            nodes=node_results,
        )

    def _node_results(
        self,
        issues: list[_PreflightIssue],
    ) -> list[DeploymentPreflightNodeResult]:
        grouped: dict[tuple[str | None, str], list[_PreflightIssue]] = {}
        for issue in issues:
            grouped.setdefault((issue.node_id, issue.node_type), []).append(issue)

        results: list[DeploymentPreflightNodeResult] = []
        for (node_id, node_type), node_issues in grouped.items():
            status: DeploymentPreflightStatus = (
                "blocked"
                if any(issue.severity == "blocked" for issue in node_issues)
                else "warning"
            )
            results.append(
                DeploymentPreflightNodeResult(
                    node_id=node_id,
                    node_type=node_type,
                    status=status,
                    reason_codes=list(
                        dict.fromkeys(issue.reason_code for issue in node_issues)
                    ),
                    knowledge_base_count_bucket=self._bucket_count(
                        sum(issue.knowledge_base_count for issue in node_issues)
                    ),
                )
            )
        return results

    def _required_actions(
        self,
        issues: list[_PreflightIssue],
    ) -> list[DeploymentPreflightRequiredAction]:
        actions: dict[str, DeploymentPreflightRequiredAction] = {}
        for issue in issues:
            mapping = (
                PUBLIC_REQUIRED_ACTIONS
                if issue.severity == "blocked"
                else WARNING_REQUIRED_ACTIONS
            )
            action = mapping.get(issue.reason_code)
            if action is not None:
                actions[action.action] = action
        return list(actions.values())

    @staticmethod
    def _extract_knowledge_base_ids(data: dict) -> tuple[list[uuid.UUID], int]:
        raw_values = data.get("knowledgeBases")
        if not isinstance(raw_values, list):
            return [], 0

        ids: list[uuid.UUID] = []
        invalid_count = 0
        for value in raw_values:
            raw_id = value.get("id") if isinstance(value, dict) else value
            parsed = KnowledgeDeploymentPreflightService._uuid_or_none(raw_id)
            if parsed is None:
                invalid_count += 1
                continue
            if parsed not in ids:
                ids.append(parsed)
        return ids, invalid_count

    @staticmethod
    def _safe_node_id(node: dict) -> str | None:
        node_id = node.get("id")
        if node_id is None:
            return None
        return str(node_id)[:128]

    @staticmethod
    def _safe_node_type(node: dict) -> str:
        node_type = node.get("type")
        if not isinstance(node_type, str) or not node_type:
            return "unknown"
        return node_type[:64]

    @staticmethod
    def _uuid_or_none(value) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _dedupe_ids(values: Iterable[uuid.UUID]) -> list[uuid.UUID]:
        result: list[uuid.UUID] = []
        seen: set[uuid.UUID] = set()
        for value in values:
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result

    @staticmethod
    def _bucket_count(value: int) -> str:
        if value <= 0:
            return "0"
        if value == 1:
            return "1"
        if value <= 10:
            return "2-10"
        if value <= 100:
            return "11-100"
        if value <= 1000:
            return "101-1000"
        return "1000+"
