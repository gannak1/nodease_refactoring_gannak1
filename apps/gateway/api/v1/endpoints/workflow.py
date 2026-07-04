import copy
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, List, Literal, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Date, Integer, cast, func
from sqlalchemy.orm import Session, noload, selectinload

# from sqlalchemy.orm import Session, noload, selectinload
from starlette.requests import Request

from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.auth.permissions import ensure_workflow_permission
from apps.gateway.services.organization_context import resolve_active_organization_id
from apps.gateway.utils.audit import audit
from apps.gateway.services.app_service import AppService
from apps.gateway.services.llm_service import LLMService
from apps.gateway.services.workflow_service import WorkflowService
from apps.shared.audit.actions import AuditAction
from apps.shared.celery_app import celery_app
from apps.shared.db.models.app import App
from apps.shared.db.models.llm import LLMUsageLog
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.permissions import workflow_auth_state_allows

# [NEW] 로깅 모델 및 스키마
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    WorkflowNodeRun,
    WorkflowRun,
)
from apps.shared.db.session import get_db
from apps.shared.schemas.log import (
    DashboardStatsResponse,
    WorkflowRunListResponse,
    WorkflowRunSchema,
)
from apps.shared.schemas.llm import LLMTraceListResponse
from apps.shared.schemas.permission import WorkflowPermissionResponse
from apps.shared.schemas.workflow import (
    WorkflowCreateRequest,
    WorkflowDraftRequest,
    WorkflowResponse,
)
from apps.shared.services.permissions import (
    get_effective_workflow_auth_state,
    get_workflow_permission_sources,
)

logger = logging.getLogger(__name__)
router = APIRouter()


class WorkflowCompareRequest(BaseModel):
    node_id: str
    compare_type: Literal["model", "prompt"]
    inputs: dict[str, Any] = Field(default_factory=dict)
    left: str
    right: str


class CostOptimizerPermissionResponse(BaseModel):
    can_compare: bool
    can_apply: bool
    required_auth_state: str


class CostOptimizerAvailabilityResponse(BaseModel):
    available: bool
    reason: str | None = None
    workflow_id: str
    node_id: str
    node_type: str
    permission: CostOptimizerPermissionResponse


class CostOptimizerLatestBaselineResponse(BaseModel):
    baseline: dict[str, Any]


class CostOptimizerBaselineListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[dict[str, Any]]


def _find_workflow_node(graph: dict[str, Any] | None, node_id: str) -> dict[str, Any] | None:
    if not isinstance(graph, dict):
        return None
    nodes = graph.get("nodes") or []
    for node in nodes:
        if isinstance(node, dict) and str(node.get("id")) == node_id:
            return node
    return None


def _ensure_cost_optimizer_llm_node(workflow: Workflow, node_id: str) -> dict[str, Any]:
    node = _find_workflow_node(workflow.graph, node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="resource.not_found")

    if str(node.get("type") or "") != "llmNode":
        raise HTTPException(status_code=400, detail="cost_optimizer.not_llm_node")

    return node


SENSITIVE_BASELINE_KEYS = {"api_key", "authorization", "encrypted_config", "secret"}


def _redact_baseline_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if str(key).lower() in SENSITIVE_BASELINE_KEYS
            else _redact_baseline_value(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact_baseline_value(item) for item in value]
    return value


def _preview_baseline_payload(value: Any) -> str:
    if value is None:
        return ""
    redacted = _redact_baseline_value(value)
    if isinstance(redacted, str):
        text = redacted
    else:
        text = json.dumps(redacted, ensure_ascii=False, default=str)
    return text[:300]


def _trace_payload_value(
    node_run: WorkflowNodeRun,
    payload_kind: str,
) -> tuple[bool, bool, Any]:
    trace_payloads = getattr(node_run, "trace_payloads", None) or []
    for payload in trace_payloads:
        if getattr(payload, "payload_kind", None) != payload_kind:
            continue
        if getattr(payload, "retention_purged_at", None) is not None:
            return True, False, None
        return True, True, getattr(payload, "redacted_payload", None)
    return False, False, None


def _usage_model_name(usage: LLMUsageLog) -> str:
    model = getattr(usage, "model", None)
    for attr in ("model_id_for_api_call", "name"):
        value = getattr(model, attr, None)
        if value:
            return str(value)
    return str(usage.model_id)


def _decimal_to_float(value: Any) -> float:
    if isinstance(value, Decimal):
        return float(value)
    return float(value or 0)


def _baseline_row_from_records(
    *,
    workflow: Workflow,
    run: WorkflowRun,
    node_run: WorkflowNodeRun,
    usage: LLMUsageLog,
) -> dict[str, Any]:
    has_trace_input, trace_input_available, trace_input = _trace_payload_value(
        node_run,
        "input",
    )
    has_trace_output, trace_output_available, trace_output = _trace_payload_value(
        node_run,
        "output",
    )
    input_payload = trace_input if has_trace_input else node_run.inputs
    output_payload = trace_output if has_trace_output else node_run.outputs
    input_available = (
        trace_input_available if has_trace_input else node_run.inputs is not None
    )
    output_available = (
        trace_output_available if has_trace_output else node_run.outputs is not None
    )
    usage_available = usage is not None
    compare_available = input_available and output_available and usage_available
    total_tokens = int((usage.prompt_tokens or 0) + (usage.completion_tokens or 0))
    cost = _decimal_to_float(usage.total_cost)
    latency_ms = int(usage.latency_ms or 0)
    model = _usage_model_name(usage)
    input_preview = _preview_baseline_payload(input_payload)
    output_preview = _preview_baseline_payload(output_payload)
    trace_available = bool(node_run.trace_metadata) or has_trace_input or has_trace_output
    process_data = getattr(node_run, "process_data", None) or {}
    node_options = (
        process_data.get("node_options") if isinstance(process_data, dict) else {}
    )
    node_options = node_options if isinstance(node_options, dict) else {}

    return {
        "baseline_id": str(node_run.id),
        "baseline_source": "workflow_node_run",
        "source_workflow_node_run_id": str(node_run.id),
        "workflow_run_id": str(run.id),
        "workflow_id": str(workflow.id),
        "node_id": node_run.node_id,
        "run_started_at": run.started_at.isoformat(),
        "workflow_run_status": run.status.value
        if hasattr(run.status, "value")
        else str(run.status),
        "node_status": node_run.status.value
        if hasattr(node_run.status, "value")
        else str(node_run.status),
        "model": model,
        "cost": cost,
        "total_tokens": total_tokens,
        "latency_ms": latency_ms,
        "input_available": input_available,
        "output_available": output_available,
        "usage_available": usage_available,
        "trace_available": trace_available,
        "compare_available": compare_available,
        "unavailable_reason": None
        if compare_available
        else "input_payload_unavailable",
        "input_preview": input_preview,
        "output_preview": output_preview,
        "has_trace": trace_available,
        "input": _redact_baseline_value(input_payload),
        "output": _redact_baseline_value(output_payload),
        "node_options": _redact_baseline_value(node_options),
        "usage": {
            "model": model,
            "prompt_tokens": int(usage.prompt_tokens or 0),
            "completion_tokens": int(usage.completion_tokens or 0),
            "total_tokens": total_tokens,
            "cost": cost,
            "latency_ms": latency_ms,
            "status": usage.status,
        },
        "trace": {
            "input_preview": input_preview,
            "output_preview": output_preview,
            "messages_preview": [],
            "rag_summary": None,
            "error_message": node_run.error_message,
        },
        "downstream_compatibility": {
            "state": "unknown",
            "label": "판정 전",
            "message": "downstream compatibility is not evaluated yet",
        },
    }


def _cost_optimizer_baseline_rows(
    db: Session,
    workflow: Workflow,
    node_id: str,
) -> list[dict[str, Any]]:
    rows = (
        db.query(WorkflowNodeRun, WorkflowRun, LLMUsageLog)
        .join(WorkflowRun, WorkflowRun.id == WorkflowNodeRun.workflow_run_id)
        .join(
            LLMUsageLog,
            (LLMUsageLog.workflow_run_id == WorkflowRun.id)
            & (LLMUsageLog.workflow_id == workflow.id)
            & (LLMUsageLog.node_id == WorkflowNodeRun.node_id),
        )
        .filter(
            WorkflowRun.workflow_id == workflow.id,
            WorkflowNodeRun.node_id == node_id,
            WorkflowNodeRun.node_type == "llmNode",
            WorkflowNodeRun.status == NodeRunStatus.SUCCESS,
            WorkflowNodeRun.outputs.is_not(None),
            LLMUsageLog.status == "success",
        )
        .all()
    )

    return [
        _baseline_row_from_records(
            workflow=workflow,
            run=run,
            node_run=node_run,
            usage=usage,
        )
        for node_run, run, usage in rows
    ]


def get_cost_optimizer_latest_baseline(
    db: Session,
    workflow: Workflow,
    node_id: str,
) -> dict[str, Any]:
    candidates = [
        row
        for row in _cost_optimizer_baseline_rows(db, workflow, node_id)
        if row["compare_available"]
    ]
    if not candidates:
        raise HTTPException(status_code=400, detail="cost_optimizer.no_baseline")
    return sorted(candidates, key=lambda row: row["run_started_at"], reverse=True)[0]


def list_cost_optimizer_baselines(
    db: Session,
    workflow: Workflow,
    node_id: str,
    *,
    q: str | None = None,
    model: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: str = "started_at_desc",
    compare_available: bool | None = None,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    rows = _cost_optimizer_baseline_rows(db, workflow, node_id)

    if q:
        query_text = q.lower()
        rows = [
            row
            for row in rows
            if query_text in (row.get("input_preview") or "").lower()
            or query_text in (row.get("output_preview") or "").lower()
        ]
    if model:
        rows = [row for row in rows if row.get("model") == model]
    if date_from:
        rows = [
            row
            for row in rows
            if datetime.fromisoformat(row["run_started_at"]) >= date_from
        ]
    if date_to:
        rows = [
            row
            for row in rows
            if datetime.fromisoformat(row["run_started_at"]) <= date_to
        ]
    if compare_available is not None:
        rows = [
            row
            for row in rows
            if row.get("compare_available") is compare_available
        ]

    sort_key = {
        "cost_desc": lambda row: row.get("cost") or 0,
        "cost_asc": lambda row: row.get("cost") or 0,
        "tokens_desc": lambda row: row.get("total_tokens") or 0,
        "latency_desc": lambda row: row.get("latency_ms") or 0,
        "started_at_desc": lambda row: row.get("run_started_at") or "",
    }.get(sort, lambda row: row.get("run_started_at") or "")
    rows = sorted(rows, key=sort_key, reverse=sort != "cost_asc")

    total = len(rows)
    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "items": rows[offset : offset + limit],
    }


def validate_execution_graph(graph: dict):
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_map = {
        node.get("id"): node
        for node in nodes
        if isinstance(node, dict) and node.get("id")
    }
    source_only_types = {"startNode", "webhookTrigger", "scheduleTrigger"}
    terminal_types = {"answerNode"}

    adjacency = {node_id: [] for node_id in node_map.keys()}

    for edge in edges:
        if not isinstance(edge, dict):
            raise HTTPException(status_code=400, detail="Invalid edge format")

        source_id = edge.get("source")
        target_id = edge.get("target")
        source_node = node_map.get(source_id)
        target_node = node_map.get(target_id)

        if source_node is None:
            raise HTTPException(
                status_code=400,
                detail=f"존재하지 않는 노드에서 시작하는 연결입니다. edge: {edge.get('id')}",
            )
        if target_node is None:
            raise HTTPException(
                status_code=400,
                detail=f"존재하지 않는 노드로 향하는 연결입니다. edge: {edge.get('id')}",
            )
        if target_node.get("type") in source_only_types:
            raise HTTPException(
                status_code=400,
                detail="입력/트리거 노드에는 다른 노드를 연결할 수 없습니다.",
            )
        if source_node.get("type") in terminal_types:
            raise HTTPException(
                status_code=400,
                detail="응답 노드에서는 다른 노드로 연결할 수 없습니다.",
            )

        adjacency[source_id].append(target_id)

    visited = set()

    for start_id in node_map.keys():
        if start_id in visited:
            continue
        # iterative DFS — avoids Python recursion limit on large graphs
        path: set[str] = set()
        stack = [(start_id, iter(adjacency.get(start_id, [])))]
        path.add(start_id)
        while stack:
            node_id, children = stack[-1]
            try:
                child = next(children)
                if child in path:
                    raise HTTPException(
                        status_code=400,
                        detail=f"워크플로우에 순환 연결이 있습니다. node: {child}",
                    )
                if child not in visited:
                    path.add(child)
                    stack.append((child, iter(adjacency.get(child, []))))
            except StopIteration:
                path.discard(node_id)
                visited.add(node_id)
                stack.pop()


def _patch_compare_graph(
    graph: dict[str, Any],
    node_id: str,
    compare_type: Literal["model", "prompt"],
    value: str,
) -> dict[str, Any]:
    patched = copy.deepcopy(graph)
    for node in patched.get("nodes", []):
        if str(node.get("id")) != node_id:
            continue
        data = node.setdefault("data", {})
        if compare_type == "model":
            data["model_id"] = value
        else:
            data["user_prompt"] = value
        validate_execution_graph(patched)
        return patched
    raise HTTPException(status_code=400, detail="Compare target node not found")


def _extract_node_result(outputs: Any, node_id: str) -> Any:
    if not isinstance(outputs, dict):
        return None
    if node_id in outputs:
        return outputs[node_id]
    nested_result = outputs.get("result")
    if isinstance(nested_result, dict):
        return nested_result.get(node_id)
    return None


def _format_compare_variant(
    *,
    label: str,
    value: str,
    node_id: str,
    status: str,
    outputs: Any = None,
    error: str | None = None,
    latency_ms: int | None = None,
) -> dict[str, Any]:
    node_output = _extract_node_result(outputs, node_id)
    usage = node_output.get("usage") if isinstance(node_output, dict) else {}
    usage = usage if isinstance(usage, dict) else {}
    return {
        "label": label,
        "value": value,
        "status": status,
        "error": error,
        "outputs": outputs,
        "node_output": node_output,
        "model": node_output.get("model") if isinstance(node_output, dict) else None,
        "total_tokens": usage.get("total_tokens")
        or usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0),
        "total_cost": node_output.get("cost", 0.0)
        if isinstance(node_output, dict)
        else 0.0,
        "latency_ms": usage.get("latency_ms") or latency_ms,
    }


@router.get(
    "/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/availability",
    response_model=CostOptimizerAvailabilityResponse,
)
def get_cost_optimizer_availability(
    workflow_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 LLM 노드가 Cost Optimizer A/B 테스트 진입 대상인지 확인합니다.
    """
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "write")
    node = _ensure_cost_optimizer_llm_node(workflow, node_id)
    node_type = str(node.get("type") or "")

    return {
        "available": True,
        "reason": None,
        "workflow_id": str(workflow.id),
        "node_id": node_id,
        "node_type": node_type,
        "permission": {
            "can_compare": True,
            "can_apply": True,
            "required_auth_state": "builder",
        },
    }


@router.get(
    "/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines/latest",
    response_model=CostOptimizerLatestBaselineResponse,
)
def get_cost_optimizer_latest_baseline_endpoint(
    workflow_id: str,
    node_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 LLM 노드의 가장 최근 비교 가능 baseline을 조회합니다.
    """
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "write")
    _ensure_cost_optimizer_llm_node(workflow, node_id)
    baseline = get_cost_optimizer_latest_baseline(db, workflow, node_id)
    return {"baseline": baseline}


@router.get(
    "/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines",
    response_model=CostOptimizerBaselineListResponse,
)
def list_cost_optimizer_baselines_endpoint(
    workflow_id: str,
    node_id: str,
    q: str | None = None,
    model: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    sort: str = "started_at_desc",
    compare_available: bool | None = None,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 LLM 노드의 baseline 후보 목록을 조회합니다.
    """
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "write")
    _ensure_cost_optimizer_llm_node(workflow, node_id)
    return list_cost_optimizer_baselines(
        db,
        workflow,
        node_id,
        q=q,
        model=model,
        date_from=date_from,
        date_to=date_to,
        sort=sort,
        compare_available=compare_available,
        limit=limit,
        offset=offset,
    )


# [NEW] 로그 조회 API
@router.get("/{workflow_id}/runs", response_model=WorkflowRunListResponse)
def get_workflow_runs(
    workflow_id: str,
    page: int = 1,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 워크플로우의 실행 이력 조회
    """
    skip = (page - 1) * limit

    ensure_workflow_permission(db, current_user, workflow_id, "read")

    total = db.query(WorkflowRun).filter(WorkflowRun.workflow_id == workflow_id).count()

    runs = (
        db.query(WorkflowRun)
        .options(noload(WorkflowRun.node_runs))
        .filter(WorkflowRun.workflow_id == workflow_id)
        .order_by(WorkflowRun.started_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )

    return {"total": total, "items": runs}


@router.get("/{workflow_id}/runs/{run_id}", response_model=WorkflowRunSchema)
def get_workflow_run_detail(
    workflow_id: str,
    run_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 워크플로우 실행 이력 상세 조회
    """
    ensure_workflow_permission(db, current_user, workflow_id, "read")

    run = (
        db.query(WorkflowRun)
        .options(selectinload(WorkflowRun.node_runs))
        .filter(WorkflowRun.id == run_id, WorkflowRun.workflow_id == workflow_id)
        .first()
    )

    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # [FIX] 중복 실행 로그 정리 (Celery Retry 등으로 인한 중복 제거)
    # node_id별로 가장 최신(started_at 기준) 로그만 필터링하여 반환
    if run.node_runs:
        latest_logs = {}
        for node_run in run.node_runs:
            node_id = node_run.node_id
            # 기존에 저장된 로그가 없거나, 현재 로그가 더 최신이면 업데이트
            if node_id not in latest_logs:
                latest_logs[node_id] = node_run
            else:
                existing = latest_logs[node_id]
                # started_at 비교 (None일 수 있으므로 안전하게 처리)
                current_start = node_run.started_at
                existing_start = existing.started_at

                if current_start and existing_start:
                    if current_start > existing_start:
                        latest_logs[node_id] = node_run
                elif current_start and not existing_start:
                    latest_logs[node_id] = node_run
                # 둘 다 없거나 기존만 있는 경우는 유지

        # 필터링된 로그 리스트로 교체 (started_at 순으로 정렬)
        run.node_runs = sorted(
            latest_logs.values(),
            key=lambda x: x.started_at
            if x.started_at
            else datetime.min.replace(tzinfo=timezone.utc),
        )

    return run


@router.get("/{workflow_id}/runs/{run_id}/llm-traces", response_model=LLMTraceListResponse)
def get_workflow_run_llm_traces(
    workflow_id: str,
    run_id: str,
    node_id: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 workflow run에 연결된 LLM usage trace를 조회합니다.
    """
    ensure_workflow_permission(db, current_user, workflow_id, "read")
    try:
        workflow_uuid = UUID(str(workflow_id))
        run_uuid = UUID(str(run_id))
    except ValueError:
        raise HTTPException(status_code=404, detail="Run not found")

    result = LLMService.list_workflow_run_llm_traces(
        db,
        workflow_uuid,
        run_uuid,
        node_id=node_id,
        limit=limit,
        offset=offset,
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return result


# [NEW] 모니터링 대시보드 통계 API


@router.get("/{workflow_id}/stats", response_model=DashboardStatsResponse)
def get_workflow_stats(
    workflow_id: str,
    days: int = 30,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    import traceback

    try:
        from apps.shared.db.models.workflow_run import WorkflowNodeRun, WorkflowRun
        from apps.shared.schemas.log import (
            DailyRunStat,
            DashboardStatsResponse,
            FailureStat,
            RecentFailure,
            RunCostStat,
            StatsSummary,
        )

        # 1. 권한 체크
        ensure_workflow_permission(db, current_user, workflow_id, "read")

        # 기간 필터 (기본 30일)
        cutoff_date = datetime.now() - timedelta(days=days)

        # base_query는 쿼리 통합으로 더 이상 사용하지 않음

        # === 1. Summary Stats (쿼리 통합 최적화) ===
        # [OPTIMIZATION] 4개의 개별 쿼리를 1개로 통합
        summary_stats = (
            db.query(
                func.count(WorkflowRun.id).label("total_runs"),
                func.sum(
                    func.cast(WorkflowRun.status == RunStatus.SUCCESS, Integer)
                ).label("success_count"),
                func.avg(WorkflowRun.duration).label("avg_duration"),
                func.sum(WorkflowRun.total_cost).label("total_cost"),
                func.sum(WorkflowRun.total_tokens).label("total_tokens"),
            )
            .filter(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.started_at >= cutoff_date,
            )
            .first()
        )

        total_runs = summary_stats.total_runs or 0
        success_count = summary_stats.success_count or 0
        avg_duration = float(summary_stats.avg_duration or 0.0)
        total_cost = float(summary_stats.total_cost or 0.0)
        total_tokens = int(summary_stats.total_tokens or 0)

        summary = StatsSummary(
            totalRuns=total_runs,
            successRate=round((success_count / total_runs * 100), 1)
            if total_runs > 0
            else 0.0,
            avgDuration=round(avg_duration, 2),
            totalCost=round(total_cost, 8),
            avgTokenPerRun=round(total_tokens / total_runs, 1)
            if total_runs > 0
            else 0.0,
            avgCostPerRun=round(total_cost / total_runs, 8) if total_runs > 0 else 0.0,
        )

        # === 2. Runs Over Time (Extended) ===
        runs_over_time = []
        daily_stats = (
            db.query(
                cast(WorkflowRun.started_at, Date).label("date"),
                func.count(WorkflowRun.id),
                func.sum(WorkflowRun.total_cost),
                func.sum(WorkflowRun.total_tokens),
            )
            .filter(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.started_at >= cutoff_date,
            )
            .group_by(cast(WorkflowRun.started_at, Date))
            .order_by(cast(WorkflowRun.started_at, Date))
            .all()
        )

        for row in daily_stats:
            runs_over_time.append(
                DailyRunStat(
                    date=str(row[0]),
                    count=row[1],
                    total_cost=float(row[2] or 0.0),
                    total_tokens=int(row[3] or 0),
                )
            )

        # === 3. Cost Analysis (Min/Max Runs) ===
        # Top 3 Min Cost (Success only, Cost > 0 to avoid boring zeros if wanted, but user asked for min cost. 0 is valid min.)
        # Let's just do Success runs.
        min_cost_runs = []
        min_runs_query = (
            db.query(WorkflowRun)
            .filter(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status == RunStatus.SUCCESS,
                WorkflowRun.started_at >= cutoff_date,
                # WorkflowRun.total_cost > 0 # Optional
            )
            .order_by(WorkflowRun.total_cost.asc())
            .limit(3)
            .all()
        )

        for run in min_runs_query:
            min_cost_runs.append(
                RunCostStat(
                    run_id=run.id,
                    started_at=run.started_at,
                    total_tokens=run.total_tokens or 0,
                    total_cost=run.total_cost or 0.0,
                )
            )

        # Top 3 Max Cost
        max_cost_runs = []
        max_runs_query = (
            db.query(WorkflowRun)
            .filter(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status == RunStatus.SUCCESS,
                WorkflowRun.started_at >= cutoff_date,
            )
            .order_by(WorkflowRun.total_cost.desc())
            .limit(3)
            .all()
        )

        for run in max_runs_query:
            max_cost_runs.append(
                RunCostStat(
                    run_id=run.id,
                    started_at=run.started_at,
                    total_tokens=run.total_tokens or 0,
                    total_cost=run.total_cost or 0.0,
                )
            )

        # === 4. Failure Analysis ===
        failure_analysis = []
        failed_nodes = (
            db.query(
                WorkflowNodeRun.node_id,
                WorkflowNodeRun.node_type,
                WorkflowNodeRun.error_message,
                func.count(WorkflowNodeRun.id),
            )
            .join(WorkflowRun)
            .filter(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowNodeRun.status == NodeRunStatus.FAILED,
                WorkflowRun.started_at >= cutoff_date,
            )
            .group_by(
                WorkflowNodeRun.node_id,
                WorkflowNodeRun.node_type,
                WorkflowNodeRun.error_message,
            )
            .order_by(func.count(WorkflowNodeRun.id).desc())
            .limit(5)
            .all()
        )

        for row in failed_nodes:
            failure_analysis.append(
                FailureStat(
                    node_id=row[0],
                    node_name=f"{row[1]} ({row[0]})",
                    count=row[3],
                    reason=str(row[2])[:50] + "..." if row[2] else "Unknown Error",
                    rate="-",
                )
            )

        # === 5. Recent Failures ===
        recent_failures = []
        failed_runs = (
            db.query(WorkflowRun)
            .options(
                selectinload(WorkflowRun.node_runs)
            )  # [FIX] N+1 문제 해결: node_runs 미리 로드
            .filter(
                WorkflowRun.workflow_id == workflow_id,
                WorkflowRun.status == RunStatus.FAILED,
            )
            .order_by(WorkflowRun.started_at.desc())
            .limit(5)
            .all()
        )

        for run in failed_runs:
            failed_node = next(
                (n for n in run.node_runs if n.status == NodeRunStatus.FAILED),
                None,
            )
            recent_failures.append(
                RecentFailure(
                    run_id=str(run.id),
                    failed_at=str(run.started_at),
                    node_id=failed_node.node_id if failed_node else "Unknown",
                    error_message=run.error_message
                    or (failed_node.error_message if failed_node else "Unknown error"),
                )
            )

        return DashboardStatsResponse(
            summary=summary,
            runsOverTime=runs_over_time,
            minCostRuns=min_cost_runs,
            maxCostRuns=max_cost_runs,
            failureAnalysis=failure_analysis,
            recentFailures=recent_failures,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[ERROR] Stats API Failed:\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("", response_model=WorkflowResponse)
@audit(AuditAction.WORKFLOW_CREATE)
def create_workflow(
    request: Request,
    payload: WorkflowCreateRequest,
    x_organization_id: str | None = Header(default=None, alias="X-Organization-Id"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    새 워크플로우 생성 (인증 필요)
    """
    organization_id = resolve_active_organization_id(
        db, request, x_organization_id, current_user.id
    )
    workflow = WorkflowService.create_workflow(
        db,
        payload,
        user_id=current_user.id,
        organization_id=organization_id,
    )

    return {
        "id": str(workflow.id),
        "app_id": workflow.app_id,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
    }


@router.get("/{workflow_id}", response_model=WorkflowResponse)
def get_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    워크플로우 메타데이터 조회 (app_id 포함)
    """
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "read")

    return {
        "id": str(workflow.id),
        "app_id": workflow.app_id,
        "created_at": workflow.created_at.isoformat(),
        "updated_at": workflow.updated_at.isoformat(),
    }


@router.get(
    "/{workflow_id}/permissions/me",
    response_model=WorkflowPermissionResponse,
    response_model_exclude_none=True,
)
def get_my_workflow_permission(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "read")
    auth_state = get_effective_workflow_auth_state(
        db,
        current_user.id,
        workflow.id,
        organization_id=workflow.organization_id,
    )
    sources = get_workflow_permission_sources(
        db,
        current_user.id,
        workflow.id,
        organization_id=workflow.organization_id,
    )
    return {
        "workflow_id": str(workflow.id),
        "organization_id": str(workflow.organization_id)
        if workflow.organization_id
        else None,
        "auth_state": auth_state,
        "can_read": workflow_auth_state_allows(auth_state, "read"),
        "can_write": workflow_auth_state_allows(auth_state, "write"),
        "can_execute": workflow_auth_state_allows(auth_state, "execute"),
        "can_deploy": workflow_auth_state_allows(auth_state, "deploy"),
        "can_manage": workflow_auth_state_allows(auth_state, "manage"),
        "sources": sources,
    }


@router.get("/app/{app_id}", response_model=List[WorkflowResponse])
def list_workflows_by_app(
    app_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    특정 App의 모든 워크플로우 조회
    """
    # App 권한 확인
    app = db.query(App).filter(App.id == app_id).first()
    if not app:
        raise HTTPException(status_code=404, detail="App not found")

    denial_status = AppService.access_denial_status(
        db, app, current_user.id, "read"
    )
    if denial_status is not None:
        detail = "Forbidden" if denial_status == 403 else "App not found"
        raise HTTPException(status_code=denial_status, detail=detail)

    # 워크플로우 목록 조회
    workflows = db.query(Workflow).filter(Workflow.app_id == app_id).all()

    return [
        {
            "id": str(w.id),
            "app_id": str(w.app_id),
            "created_at": w.created_at.isoformat(),
            "updated_at": w.updated_at.isoformat(),
        }
        for w in workflows
    ]


@router.post("/{workflow_id}/draft")
@audit(AuditAction.WORKFLOW_UPDATE, target_param="workflow_id")
def sync_draft_workflow(
    workflow_id: str,
    request: WorkflowDraftRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    프론트엔드로부터 워크플로우 초안 데이터를 받아 PostgreSQL에 저장합니다. (인증 필요)

    Args:
        workflow_id: 워크플로우 ID (URL 경로에서 가져옴)
        request: 워크플로우 데이터 (노드, 엣지, 뷰포트)
        db: 데이터베이스 세션 (의존성 주입)
        current_user: 현재 로그인한 사용자
    """
    ensure_workflow_permission(db, current_user, workflow_id, "write")

    return WorkflowService.save_draft(
        db, workflow_id, request, user_id=str(current_user.id)
    )


@router.get("/{workflow_id}/draft")
def get_draft_workflow(
    workflow_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    PostgreSQL에서 워크플로우 초안 데이터를 조회합니다. (인증 필요)
    """
    ensure_workflow_permission(db, current_user, workflow_id, "read")

    return WorkflowService.get_draft(db, workflow_id)


@router.post("/{workflow_id}/compare")
def compare_workflow_variants(
    workflow_id: str,
    request_body: WorkflowCompareRequest,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "execute")
    graph = WorkflowService.get_draft(db, workflow_id)
    if not graph:
        raise HTTPException(
            status_code=404, detail=f"Workflow '{workflow_id}' draft not found"
        )

    base_context = {
        "user_id": str(current_user.id),
        "workflow_id": workflow_id,
        "organization_id": (
            str(workflow.organization_id) if workflow.organization_id else None
        ),
        "app_id": str(workflow.app_id),
        "trigger_mode": "manual_compare",
        "request_id": request.headers.get("x-request-id"),
        "correlation_id": request.headers.get("x-correlation-id"),
        "compare": {
            "node_id": request_body.node_id,
            "compare_type": request_body.compare_type,
        },
    }

    def run_variant(label: str, value: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            patched_graph = _patch_compare_graph(
                graph, request_body.node_id, request_body.compare_type, value
            )
            task = celery_app.send_task(
                "workflow.execute",
                args=[patched_graph, request_body.inputs, base_context],
                kwargs={"is_deployed": False},
            )
            task_result = task.get(timeout=600)
            latency_ms = int((time.perf_counter() - started) * 1000)
            if task_result.get("status") == "success":
                return _format_compare_variant(
                    label=label,
                    value=value,
                    node_id=request_body.node_id,
                    status="success",
                    outputs=task_result.get("result", {}),
                    latency_ms=latency_ms,
                )
            return _format_compare_variant(
                label=label,
                value=value,
                node_id=request_body.node_id,
                status="failed",
                outputs=task_result.get("result", {}),
                error=task_result.get("error") or "Workflow execution failed",
                latency_ms=latency_ms,
            )
        except Exception as exc:
            latency_ms = int((time.perf_counter() - started) * 1000)
            return _format_compare_variant(
                label=label,
                value=value,
                node_id=request_body.node_id,
                status="failed",
                error=str(exc),
                latency_ms=latency_ms,
            )

    return {
        "workflow_id": workflow_id,
        "node_id": request_body.node_id,
        "compare_type": request_body.compare_type,
        "variants": [
            run_variant("A", request_body.left),
            run_variant("B", request_body.right),
        ],
    }


@router.post("/{workflow_id}/execute")
async def execute_workflow(
    workflow_id: str,
    request: Request,
    user_input: dict = {},
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    PostgreSQL에서 워크플로우 초안 데이터를 조회하고, Celery 태스크로 실행합니다. (인증 필요)
    """
    # 1. 권한 확인
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "execute")

    memory_mode_enabled = False
    if isinstance(user_input, dict):
        # 프론트 토글 상태가 실행 입력에 섞여 올 수 있으므로 분리해서 컨텍스트에만 전달
        memory_mode_enabled = bool(user_input.pop("memory_mode", False))

    # 2. 데이터 조회 및 Celery 태스크 호출
    try:
        graph = WorkflowService.get_draft(db, workflow_id)
        if not graph:
            raise HTTPException(
                status_code=404, detail=f"Workflow '{workflow_id}' draft not found"
            )

        # execution_context 구성
        execution_context = {
            "user_id": str(current_user.id),
            "workflow_id": workflow_id,
            "organization_id": (
                str(workflow.organization_id) if workflow.organization_id else None
            ),
            "app_id": str(workflow.app_id),
            "memory_mode": memory_mode_enabled,
            "request_id": request.headers.get("x-request-id"),
            "correlation_id": request.headers.get("x-correlation-id"),
        }

        # Celery 태스크 호출 (workflow.execute)
        task = celery_app.send_task(
            "workflow.execute",
            args=[graph, user_input, execution_context],
            kwargs={"is_deployed": False},
        )

        # 결과 대기 (타임아웃 10분)
        result = task.get(timeout=600)

        if result.get("status") == "success":
            return result.get("result", {})
        else:
            raise HTTPException(status_code=500, detail="Workflow execution failed")

    except celery_app.backend.TimeoutError:
        raise HTTPException(status_code=504, detail="Workflow execution timed out")
    except ValueError as e:
        # 노드 검증 실패 등의 입력 오류
        raise HTTPException(status_code=400, detail=str(e))
    except NotImplementedError as e:
        # 미지원 노드 등
        raise HTTPException(status_code=501, detail=str(e))
    except Exception as e:
        # 그 외 서버 에러
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{workflow_id}/stream")
async def stream_workflow(
    workflow_id: str,
    request: Request,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    워크플로우를 실행하고 실행 과정을 SSE(Server-Sent Events)로 스트리밍합니다.

    [완전 분리 버전] Gateway에서 run_id를 생성하고, Celery 태스크를 호출한 후
    Redis Pub/Sub 채널을 구독하여 이벤트를 SSE로 전달합니다.

    multipart/form-data 지원:
    - inputs: JSON 문자열 (일반 입력값)
    - file_변수명: 업로드된 파일들
    """
    import uuid

    memory_mode_enabled = False
    # 1. 권한 확인
    workflow = ensure_workflow_permission(db, current_user, workflow_id, "execute")

    # 2. Request에서 FormData 파싱
    content_type = request.headers.get("content-type", "")
    user_input = {}
    graph_snapshot = None

    if "multipart/form-data" in content_type:
        # FormData 파싱
        form = await request.form()

        # inputs 필드에서 JSON 파싱
        inputs_str = form.get("inputs", "{}")
        try:
            user_input = json.loads(inputs_str) if isinstance(inputs_str, str) else {}
        except json.JSONDecodeError:
            user_input = {}

        graph_snapshot_str = form.get("graph_snapshot")
        if isinstance(graph_snapshot_str, str) and graph_snapshot_str.strip():
            try:
                graph_snapshot = json.loads(graph_snapshot_str)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400, detail="Invalid graph_snapshot JSON"
                )

        # 토글 값 분리 (문자열 true/false 허용)
        memory_mode_enabled = str(
            form.get("memory_mode", user_input.pop("memory_mode", ""))
        ).lower() == "true"
    else:
        # JSON 방식 (기존)
        try:
            body = await request.json()
            if isinstance(body, dict) and (
                "inputs" in body or "graph_snapshot" in body
            ):
                raw_inputs = body.get("inputs", {})
                user_input = raw_inputs if isinstance(raw_inputs, dict) else {}
                graph_snapshot = body.get("graph_snapshot")
            else:
                user_input = body if isinstance(body, dict) else {}

            if isinstance(user_input, dict):
                memory_mode_enabled = bool(user_input.pop("memory_mode", False))
        except Exception:
            user_input = {}

    if graph_snapshot is not None and not isinstance(graph_snapshot, dict):
        raise HTTPException(status_code=400, detail="graph_snapshot must be an object")

    # 3. 실행 그래프 결정
    graph = graph_snapshot or WorkflowService.get_draft(db, workflow_id)
    if not graph:
        raise HTTPException(
            status_code=404, detail=f"Workflow '{workflow_id}' draft not found"
        )
    validate_execution_graph(graph)

    # 4. [NEW] Gateway에서 run_id 생성 (Celery 태스크에 전달)
    external_run_id = str(uuid.uuid4())

    # 5. 실행 컨텍스트 준비
    execution_context = {
        "user_id": str(current_user.id),
        "workflow_id": workflow_id,
        "organization_id": (
            str(workflow.organization_id) if workflow.organization_id else None
        ),
        "app_id": str(workflow.app_id),
        "memory_mode": memory_mode_enabled,
        "trigger_mode": "manual",  # 테스트 실행
        "request_id": request.headers.get("x-request-id"),
        "correlation_id": request.headers.get("x-correlation-id"),
    }

    # 6. Redis Pub/Sub 구독 및 SSE 스트리밍
    # Race Condition 방지: 구독 완료 후 Celery 태스크 시작
    def event_generator():
        """Redis Pub/Sub을 구독하여 SSE 이벤트로 변환"""
        from apps.shared.pubsub import get_redis_client

        client = get_redis_client()
        pubsub = client.pubsub()
        channel = f"workflow:{external_run_id}"

        try:
            # 1. 먼저 Redis 채널 구독
            pubsub.subscribe(channel)

            # 2. 구독 완료 후 Celery 태스크 시작 (중요!)
            celery_app.send_task(
                "workflow.stream",
                args=[graph, user_input, execution_context, external_run_id],
            )
            logger.info("[Gateway] Celery 태스크 시작됨")

            # 3. 이벤트 수신 및 SSE 전송
            for message in pubsub.listen():
                if message["type"] == "message":
                    event = json.loads(message["data"])
                    # SSE 포맷: "data: {json_content}\n\n"
                    yield f"data: {json.dumps(event)}\n\n"

                    # workflow_finish 또는 error 시 종료
                    if event.get("type") in ("workflow_finish", "error"):
                        logger.info(
                            f"[Gateway] 스트리밍 종료 - type: {event.get('type')}"
                        )
                        break
        except Exception as e:
            # 구독 중 에러 발생 시 에러 이벤트 전송
            error_event = {"type": "error", "data": {"message": str(e)}}
            yield f"data: {json.dumps(error_event)}\n\n"
        finally:
            pubsub.unsubscribe(channel)
            pubsub.close()

    # 7. StreamingResponse 반환
    return StreamingResponse(event_generator(), media_type="text/event-stream")
