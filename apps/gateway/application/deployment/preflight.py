from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass, replace

from .errors import DeploymentPreflightBlocked
from .models import (
    DeploymentPreflightResult,
    PreflightAudience,
    PreflightNodeResult,
    PreflightRequiredAction,
    PreflightStatus,
    PreflightSummary,
)
from .ports import DeploymentPreflightRepository

PUBLIC_REQUIRED_ACTIONS = {
    "private_kb_requires_execution_subject": PreflightRequiredAction(
        action="remove_private_kb_or_use_authenticated_run",
        label="Private KB를 제거하거나 인증 실행 경로를 사용하세요",
    ),
    "source_public_exposure_required": PreflightRequiredAction(
        action="approve_source_public_exposure_or_remove_kb",
        label="Source 공개 승인 정책을 추가하거나 해당 KB를 제거하세요",
    ),
    "knowledge_base_unavailable": PreflightRequiredAction(
        action="remove_unavailable_kb_reference",
        label="사용할 수 없는 KB 참조를 제거하세요",
    ),
    "workflow_node_target_unavailable": PreflightRequiredAction(
        action="fix_workflow_node_target_or_remove_reference",
        label="서브 모듈 대상 배포를 복구하거나 노드를 제거하세요",
    ),
    "workflow_node_cycle_detected": PreflightRequiredAction(
        action="remove_recursive_workflow_node_reference",
        label="순환되는 서브 모듈 참조를 제거하세요",
    ),
}

WARNING_REQUIRED_ACTIONS = {
    "workflow_node_execution_subject_inherited": PreflightRequiredAction(
        action="verify_parent_execution_subject",
        label="상위 워크플로우 실행 주체가 KB 권한을 제공하는지 확인하세요",
    ),
}

NON_DOWNGRADABLE_REASON_CODES = {
    "workflow_node_target_unavailable",
    "workflow_node_cycle_detected",
}

ANONYMOUS_PUBLIC_TYPES = {
    "api",
    "webapp",
    "widget",
    "chatbot",
    "mcp",
    "schedule",
    "webhook",
}


@dataclass(frozen=True)
class _PreflightIssue:
    node_id: str | None
    node_type: str
    severity: PreflightStatus
    reason_code: str
    knowledge_base_count: int = 0


class DeploymentPreflightUseCase:
    MAX_WORKFLOW_NODE_DEPTH = 3

    def __init__(
        self,
        repository: DeploymentPreflightRepository,
        *,
        organization_id: uuid.UUID | None,
        candidate_graphs_by_app_id: Mapping[uuid.UUID, dict] | None = None,
        candidate_deployment_types_by_app_id: Mapping[uuid.UUID, str] | None = None,
    ) -> None:
        self.repository = repository
        self.organization_id = organization_id
        self.candidate_graphs_by_app_id = dict(candidate_graphs_by_app_id or {})
        self.candidate_deployment_types_by_app_id = dict(
            candidate_deployment_types_by_app_id or {}
        )

    def preview(
        self,
        *,
        deployment_type: str,
        graph_snapshot: dict,
        audience_hint: PreflightAudience | None = None,
        is_active: bool = True,
    ) -> DeploymentPreflightResult:
        audience = self._effective_audience(deployment_type, audience_hint)
        issues = self._evaluate_graph(
            graph_snapshot,
            audience=audience,
            depth=0,
            visited_app_ids=set(self.candidate_graphs_by_app_id),
        )
        if not is_active:
            issues = self._downgrade_blocked_issues(issues)
        return self._result(audience, issues)

    def enforce_active_publish(
        self,
        *,
        deployment_type: str,
        graph_snapshot: dict,
    ) -> DeploymentPreflightResult:
        result = self.preview(
            deployment_type=deployment_type,
            graph_snapshot=graph_snapshot,
        )
        if result.status == "blocked":
            raise DeploymentPreflightBlocked(result)
        return result

    @staticmethod
    def server_derived_audience(deployment_type: str) -> PreflightAudience:
        if deployment_type == "workflow_node":
            return "workflow_node_inherited"
        if deployment_type in ANONYMOUS_PUBLIC_TYPES:
            return "anonymous_public"
        return "anonymous_public"

    def _effective_audience(
        self,
        deployment_type: str,
        audience_hint: PreflightAudience | None,
    ) -> PreflightAudience:
        derived = self.server_derived_audience(deployment_type)
        if audience_hint == "anonymous_public":
            return "anonymous_public"
        return derived

    def _evaluate_graph(
        self,
        graph_snapshot: dict,
        *,
        audience: PreflightAudience,
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
                        severity=(
                            "blocked" if audience == "anonymous_public" else "warning"
                        ),
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
        audience: PreflightAudience,
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

        kbs_by_id = self.repository.get_active_knowledge_bases(
            kb_ids,
            self.organization_id,
        )
        public_eligible_ids = (
            self.repository.get_public_runtime_eligible_knowledge_base_ids(
                kb_ids,
                self.organization_id,
            )
        )
        issue_counts: dict[str, int] = {}
        for kb_id in kb_ids:
            kb = kbs_by_id.get(kb_id)
            if kb is None:
                reason_code = "knowledge_base_unavailable"
            elif kb_id not in public_eligible_ids:
                reason_code = "private_kb_requires_execution_subject"
            elif kb.source_managed:
                reason_code = "source_public_exposure_required"
            else:
                continue
            issue_counts[reason_code] = issue_counts.get(reason_code, 0) + 1

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
        audience: PreflightAudience,
        depth: int,
        visited_app_ids: set[uuid.UUID],
    ) -> list[_PreflightIssue]:
        if depth >= self.MAX_WORKFLOW_NODE_DEPTH:
            return [self._workflow_node_unavailable(node_id, node_type)]

        target_app_id = self._uuid_or_none(data.get("appId"))
        if target_app_id is None:
            return [self._workflow_node_unavailable(node_id, node_type)]

        target = self.repository.get_workflow_node_target(
            target_app_id,
            self.organization_id,
        )
        if target is None:
            return [self._workflow_node_unavailable(node_id, node_type)]

        candidate_graph = self.candidate_graphs_by_app_id.get(target_app_id)
        if candidate_graph is not None:
            if (
                self.candidate_deployment_types_by_app_id.get(target_app_id)
                != "workflow_node"
            ):
                return [self._workflow_node_unavailable(node_id, node_type)]
            if target_app_id in visited_app_ids:
                return [self._workflow_node_cycle(node_id, node_type)]
            return self._evaluate_graph(
                candidate_graph,
                audience=audience,
                depth=depth + 1,
                visited_app_ids={*visited_app_ids, target_app_id},
            )

        if target_app_id in visited_app_ids:
            return [self._workflow_node_cycle(node_id, node_type)]
        if target.active_graph_snapshot is None:
            return [self._workflow_node_unavailable(node_id, node_type)]
        return self._evaluate_graph(
            target.active_graph_snapshot,
            audience=audience,
            depth=depth + 1,
            visited_app_ids={*visited_app_ids, target_app_id},
        )

    @staticmethod
    def _workflow_node_unavailable(
        node_id: str | None,
        node_type: str,
    ) -> _PreflightIssue:
        return _PreflightIssue(
            node_id=node_id,
            node_type=node_type,
            severity="blocked",
            reason_code="workflow_node_target_unavailable",
        )

    @staticmethod
    def _workflow_node_cycle(
        node_id: str | None,
        node_type: str,
    ) -> _PreflightIssue:
        return _PreflightIssue(
            node_id=node_id,
            node_type=node_type,
            severity="blocked",
            reason_code="workflow_node_cycle_detected",
        )

    def _result(
        self,
        audience: PreflightAudience,
        issues: list[_PreflightIssue],
    ) -> DeploymentPreflightResult:
        node_results = self._node_results(issues)
        status: PreflightStatus = "passed"
        if any(issue.severity == "blocked" for issue in issues):
            status = "blocked"
        elif any(issue.severity == "warning" for issue in issues):
            status = "warning"

        first_reason = next((issue.reason_code for issue in issues), None)
        affected_kb_count = sum(issue.knowledge_base_count for issue in issues)
        warnings = tuple(
            dict.fromkeys(
                issue.reason_code
                for issue in issues
                if issue.severity == "warning"
            )
        )
        return DeploymentPreflightResult(
            status=status,
            audience=audience,
            safe_summary=PreflightSummary(
                blocked_reason=first_reason,
                affected_node_count=len(node_results),
                affected_kb_count_bucket=self._bucket_count(affected_kb_count),
            ),
            required_actions=self._required_actions(issues),
            warnings=warnings,
            nodes=node_results,
        )

    def _node_results(
        self,
        issues: list[_PreflightIssue],
    ) -> tuple[PreflightNodeResult, ...]:
        grouped: dict[tuple[str | None, str], list[_PreflightIssue]] = {}
        for issue in issues:
            grouped.setdefault((issue.node_id, issue.node_type), []).append(issue)

        results: list[PreflightNodeResult] = []
        for (node_id, node_type), node_issues in grouped.items():
            status: PreflightStatus = (
                "blocked"
                if any(issue.severity == "blocked" for issue in node_issues)
                else "warning"
            )
            results.append(
                PreflightNodeResult(
                    node_id=node_id,
                    node_type=node_type,
                    status=status,
                    reason_codes=tuple(
                        dict.fromkeys(issue.reason_code for issue in node_issues)
                    ),
                    knowledge_base_count_bucket=self._bucket_count(
                        sum(issue.knowledge_base_count for issue in node_issues)
                    ),
                )
            )
        return tuple(results)

    @staticmethod
    def _required_actions(
        issues: list[_PreflightIssue],
    ) -> tuple[PreflightRequiredAction, ...]:
        actions: dict[str, PreflightRequiredAction] = {}
        for issue in issues:
            action = (
                WARNING_REQUIRED_ACTIONS.get(issue.reason_code)
                if issue.severity == "warning"
                else None
            ) or PUBLIC_REQUIRED_ACTIONS.get(issue.reason_code)
            if action is not None:
                actions[action.action] = action
        return tuple(actions.values())

    @staticmethod
    def _downgrade_blocked_issues(
        issues: list[_PreflightIssue],
    ) -> list[_PreflightIssue]:
        return [
            replace(issue, severity="warning")
            if issue.severity == "blocked"
            and issue.reason_code not in NON_DOWNGRADABLE_REASON_CODES
            else issue
            for issue in issues
        ]

    @staticmethod
    def _extract_knowledge_base_ids(data: dict) -> tuple[list[uuid.UUID], int]:
        raw_values = data.get("knowledgeBases")
        if not isinstance(raw_values, list):
            return [], 0

        ids: list[uuid.UUID] = []
        invalid_count = 0
        for value in raw_values:
            raw_id = value.get("id") if isinstance(value, dict) else value
            parsed = DeploymentPreflightUseCase._uuid_or_none(raw_id)
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
    def _uuid_or_none(value: object) -> uuid.UUID | None:
        try:
            return uuid.UUID(str(value))
        except (TypeError, ValueError):
            return None

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
