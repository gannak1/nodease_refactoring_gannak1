import copy
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from apps.gateway.auth.permissions import ensure_workflow_permission
from apps.gateway.services.app_service import AppService
from apps.gateway.services.audit_records import add_action_audit
from apps.gateway.services.knowledge_rag_recommendation_service import (
    KnowledgeRAGRecommendationService,
)
from apps.shared.audit.actions import AuditAction
from apps.shared.db.models.agent_builder import (
    AgentBuilderDraft,
    AgentBuilderRequest,
    AgentBuilderSession,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.schemas.agent_builder import (
    AgentBuilderApplyRequest,
    AgentBuilderApplyResponse,
    AgentBuilderDraftPreview,
    AgentBuilderKnowledgeRequirement,
    AgentBuilderMessageRequest,
    AgentBuilderMessageResponse,
    AgentBuilderPendingResolution,
    AgentBuilderPlannedStep,
    AgentBuilderSessionCreateRequest,
    AgentBuilderSessionResponse,
    AgentBuilderStructuredRequest,
    AgentBuilderValidationIssue,
    AgentBuilderValidationResult,
)
from apps.shared.schemas.knowledge import KnowledgeRAGRecommendationRequest
from apps.shared.services.permissions import (
    has_workflow_permission,
)
from apps.shared.services.permission_audit import record_resource_permission_denied


SESSION_TTL = timedelta(hours=24)
DRAFT_TTL = timedelta(minutes=30)
MVP_SUPPORTED_NODE_TYPES = {"startNode", "llmNode", "answerNode"}
SAFE_SIDE_EFFECT_NOTICE = (
    "초안 생성, 미리보기, 적용 및 저장 중에는 workflow 실행, Knowledge Base 검색, "
    "Slack 전송, credential 사용/변경, 외부 시스템 변경을 수행하지 않습니다."
)
_SECRET_LIKE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|"
    r"bearer\s+[A-Za-z0-9._\-]{8,}|eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+|"
    r"api[_-]?key|token|password|secret)",
    re.IGNORECASE,
)
_SECRET_KEY_VALUE_RE = re.compile(
    r"\b(?:api[_-]?key|token|password|secret|authorization|credential)"
    r"\s*[:=]\s*['\"]?[^'\"\s,;]+",
    re.IGNORECASE,
)
_AUTH_HEADER_VALUE_RE = re.compile(
    r"\bauthorization\s*[:=]\s*(?:bearer|basic|token)\s+[^'\"\s,;]+",
    re.IGNORECASE,
)
_SECRET_NATURAL_LANGUAGE_RE = re.compile(
    r"\b(?:api[_\s-]?key|token|password|secret|authorization|credential|"
    r"비밀번호|암호|토큰|시크릿|인증키)\b"
    r"\s*(?:is|are|as|값은|값이|는|은|:|=)?\s*['\"]?[^'\"\s,;]+",
    re.IGNORECASE,
)
_BEARER_VALUE_RE = re.compile(r"\bbearer\s+[A-Za-z0-9._~+/=\-]{8,}", re.IGNORECASE)
_URL_VALUE_RE = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
_PATH_VALUE_RE = re.compile(
    r"((?:[A-Za-z]:\\|\\\\)[^\s,;]+|/(?:[\w.\-]+/)+[\w.\-]+)",
    re.IGNORECASE,
)
UI_ONLY_NODE_DATA_KEYS = {
    "selected",
    "dragging",
    "status",
    "displayStatus",
    "isHovered",
}
SECRET_NODE_DATA_KEYS = {
    "api_key",
    "apiKey",
    "api_token",
    "token",
    "password",
    "secret",
    "authorization",
    "authConfig",
    "encrypted_config",
    "encryptedConfig",
    "headers",
}
SOURCE_REFERENCE_NODE_DATA_KEYS = {
    "url",
    "source_url",
    "sourceUrl",
    "path",
    "source_path",
    "sourcePath",
    "document_title",
    "documentTitle",
    "source_title",
    "sourceTitle",
    "raw_source_title",
    "webhook_url",
    "webhookUrl",
}
UNSAFE_DISPLAY_LABEL_RE = re.compile(
    r"(https?://|[A-Za-z]:\\|\\\\|/|\\|\.pdf\b|\.docx?\b|\.xlsx?\b|\.md\b|\.txt\b)",
    re.IGNORECASE,
)
SAFE_CANDIDATE_HANDLE_RE = re.compile(
    r"^rec-[0-9a-fA-F-]{8,}-[0-9a-fA-F-]{4,}-"
    r"[0-9a-fA-F-]{4,}-[0-9a-fA-F-]{4,}-[0-9a-fA-F-]{12}$"
)
PREVIEW_LAYOUT_X_GAP = 360
PREVIEW_LAYOUT_Y_GAP = 220
PREVIEW_LAYOUT_NODE_WIDTH = 280
PREVIEW_LAYOUT_NODE_HEIGHT = 140
EDGE_CONTEXT_RE = re.compile(
    r"(여기\s*사이|이\s*연결|연결\s*사이|엣지|edge|connection|between)",
    re.IGNORECASE,
)
NEW_WORKFLOW_INTENT_RE = re.compile(
    r"(새\s*workflow|새\s*워크플로우|새로\s*(?:만들|생성)|"
    r"처음부터|new\s+workflow|create\s+(?:a\s+)?new\s+workflow)",
    re.IGNORECASE,
)
APPROVED_DRAFT_MODEL_ENV = "AGENT_BUILDER_DRAFT_MODEL_ID"
SAFE_TRIGGER_TYPES = {"manual", "schedule", "api"}


def _safe_display_label(value: Any, *, fallback: str = "Knowledge Base") -> str:
    label = _safe_summary(str(value or ""), limit=80)
    if not label or UNSAFE_DISPLAY_LABEL_RE.search(label):
        return fallback
    return label


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _safe_summary(message: str, *, limit: int = 240) -> str:
    cleaned = " ".join((message or "").split())
    cleaned = _AUTH_HEADER_VALUE_RE.sub("[redacted]", cleaned)
    cleaned = _SECRET_KEY_VALUE_RE.sub("[redacted]", cleaned)
    cleaned = _SECRET_NATURAL_LANGUAGE_RE.sub("[redacted]", cleaned)
    cleaned = _BEARER_VALUE_RE.sub("[redacted]", cleaned)
    cleaned = _URL_VALUE_RE.sub("[redacted]", cleaned)
    cleaned = _PATH_VALUE_RE.sub("[redacted]", cleaned)
    cleaned = _SECRET_LIKE_RE.sub("[redacted]", cleaned)
    return cleaned[:limit]


def _message_mentions_edge_context(message: str) -> bool:
    return bool(EDGE_CONTEXT_RE.search(message or ""))


def _message_requests_new_workflow(message: str) -> bool:
    return bool(NEW_WORKFLOW_INTENT_RE.search(message or ""))


def _redact_kb_refs(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    safe_refs: list[dict[str, Any]] = []
    for index, item in enumerate(value):
        if not isinstance(item, dict):
            continue
        ref_id = str(item.get("id") or "")
        if (
            item.get("reference_type") == "safe_candidate_handle"
            and SAFE_CANDIDATE_HANDLE_RE.match(ref_id)
        ):
            safe_refs.append(
                {
                    "id": ref_id,
                    "name": _safe_display_label(item.get("name")),
                    "reference_type": "safe_candidate_handle",
                    "confidence": item.get("confidence"),
                    "score": item.get("score"),
                    "reason_category": item.get("reason_category"),
                    "threshold_result": item.get("threshold_result"),
                }
            )
            continue
        safe_refs.append(
            {
                "id": f"existing-kb-ref-{index + 1}",
                "name": "기존 Knowledge Base 참조",
                "reference_type": "existing_redacted_reference",
            }
        )
    return safe_refs


def _semantic_node_data(data: dict[str, Any] | None) -> dict[str, Any]:
    data = data or {}
    return {
        key: value
        for key, value in data.items()
        if key not in UI_ONLY_NODE_DATA_KEYS
    }


def _redact_node_data(data: Any) -> Any:
    if isinstance(data, dict):
        redacted: dict[str, Any] = {}
        for key, value in data.items():
            if key in UI_ONLY_NODE_DATA_KEYS:
                continue
            if key == "knowledgeBases":
                redacted[key] = _redact_kb_refs(value)
                continue
            if key in SECRET_NODE_DATA_KEYS:
                redacted[key] = "[redacted]"
                continue
            if key in SOURCE_REFERENCE_NODE_DATA_KEYS:
                redacted[key] = "[redacted]"
                continue
            redacted[key] = _redact_node_data(value)
        return redacted
    if isinstance(data, list):
        return [_redact_node_data(item) for item in data]
    if isinstance(data, str):
        return _SECRET_LIKE_RE.sub("[redacted]", data)
    return data


def _safe_preview_node_data(node: dict[str, Any]) -> dict[str, Any]:
    node_type = str(node.get("type") or "node")
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    title_by_type = {
        "startNode": "Start node",
        "llmNode": "LLM node",
        "answerNode": "Answer node",
    }
    safe_data: dict[str, Any] = {
        "title": title_by_type.get(node_type, "Workflow node"),
        "original_type": node_type,
    }
    if node_type == "startNode":
        trigger_type = data.get("triggerType") or data.get("trigger_type")
        if trigger_type in SAFE_TRIGGER_TYPES:
            safe_data["triggerType"] = trigger_type
        variables = data.get("variables") if isinstance(data.get("variables"), list) else []
        safe_data["variable_count"] = len(variables)
    elif node_type == "llmNode":
        safe_data.update(
            {
                "provider": "configured" if data.get("provider") else None,
                "model_configured": bool(data.get("model_id") or data.get("modelId")),
                "task_type": _safe_summary(
                    str(data.get("task_type") or data.get("taskType") or "llm"),
                    limit=40,
                ),
                "knowledgeBases": _redact_kb_refs(data.get("knowledgeBases") or []),
                "credential_reference_state": "not_exposed",
            }
        )
        if isinstance(data.get("scoreThreshold"), (int, float)):
            safe_data["scoreThreshold"] = data.get("scoreThreshold")
        if isinstance(data.get("topK"), int):
            safe_data["topK"] = data.get("topK")
    elif node_type == "answerNode":
        outputs = data.get("outputs") if isinstance(data.get("outputs"), list) else []
        safe_data["output_count"] = len(outputs)
    return {key: value for key, value in safe_data.items() if value is not None}


def _redact_graph_for_preview(graph: dict[str, Any] | None) -> dict[str, Any]:
    graph = copy.deepcopy(graph or _empty_graph())
    graph["nodes"] = [
        {
            "id": node.get("id"),
            "type": node.get("type")
            if node.get("type") in {"startNode", "llmNode", "answerNode", "note"}
            else "agentBuilderPreviewNode",
            "position": node.get("position") or {"x": 0, "y": 0},
            "selected": False,
            "data": _safe_preview_node_data(node),
        }
        for node in graph.get("nodes") or []
    ]
    graph["edges"] = [
        {
            "id": edge.get("id"),
            "source": edge.get("source"),
            "target": edge.get("target"),
            "sourceHandle": edge.get("sourceHandle"),
            "targetHandle": edge.get("targetHandle"),
            "selected": False,
        }
        for edge in graph.get("edges") or []
    ]
    graph.setdefault("viewport", {"x": 0, "y": 0, "zoom": 1})
    return graph


def canonical_workflow_graph(graph: dict[str, Any] | None) -> dict[str, Any]:
    graph = graph or {}
    nodes = []
    for node in graph.get("nodes") or []:
        if node.get("type") == "note":
            continue
        nodes.append(
            {
                "id": node.get("id"),
                "type": node.get("type"),
                "data": _semantic_node_data(node.get("data") or {}),
            }
        )
    node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    edges = []
    for edge in graph.get("edges") or []:
        if str(edge.get("source")) not in node_ids or str(edge.get("target")) not in node_ids:
            continue
        edges.append(
            {
                "source": edge.get("source"),
                "target": edge.get("target"),
                "sourceHandle": edge.get("sourceHandle"),
                "targetHandle": edge.get("targetHandle"),
            }
        )
    return {
        "nodes": sorted(nodes, key=lambda item: str(item.get("id") or "")),
        "edges": sorted(
            edges,
            key=lambda item: (
                str(item.get("source") or ""),
                str(item.get("target") or ""),
                str(item.get("sourceHandle") or ""),
                str(item.get("targetHandle") or ""),
            ),
        ),
    }


def calculate_graph_hash(graph: dict[str, Any] | None) -> str:
    payload = json.dumps(
        canonical_workflow_graph(graph),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _empty_graph() -> dict[str, Any]:
    return {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}


def _graph_node_ids(graph: dict[str, Any]) -> set[str]:
    return {str(node.get("id")) for node in graph.get("nodes") or [] if node.get("id")}


def _node_position(node: dict[str, Any]) -> dict[str, float]:
    position = node.get("position") if isinstance(node.get("position"), dict) else {}
    return {
        "x": float(position.get("x") or 0),
        "y": float(position.get("y") or 0),
    }


def _node_bounds(node: dict[str, Any]) -> tuple[float, float, float, float]:
    position = _node_position(node)
    width = float(node.get("width") or PREVIEW_LAYOUT_NODE_WIDTH)
    height = float(node.get("height") or PREVIEW_LAYOUT_NODE_HEIGHT)
    return (
        position["x"],
        position["y"],
        position["x"] + width,
        position["y"] + height,
    )


def _bounds_overlap(
    left: tuple[float, float, float, float],
    right: tuple[float, float, float, float],
) -> bool:
    return not (
        left[2] <= right[0]
        or left[0] >= right[2]
        or left[3] <= right[1]
        or left[1] >= right[3]
    )


def _layout_generated_preview_nodes(
    graph: dict[str, Any],
    generated_node_ids: list[str],
    *,
    anchor_node_id: str | None,
) -> dict[str, Any]:
    nodes = graph.get("nodes") or []
    generated_set = set(generated_node_ids)
    node_by_id = {str(node.get("id")): node for node in nodes if node.get("id")}
    generated_nodes = [node_by_id[node_id] for node_id in generated_node_ids if node_id in node_by_id]
    if not generated_nodes:
        return graph

    existing_nodes = [
        node
        for node in nodes
        if str(node.get("id")) not in generated_set and node.get("type") != "note"
    ]
    anchor_node = node_by_id.get(str(anchor_node_id)) if anchor_node_id else None

    if anchor_node and str(anchor_node.get("id")) not in generated_set:
        anchor_position = _node_position(anchor_node)
        base_x = anchor_position["x"] + PREVIEW_LAYOUT_X_GAP
        base_y = anchor_position["y"]
    elif existing_nodes:
        existing_positions = [_node_position(node) for node in existing_nodes]
        base_x = max(position["x"] for position in existing_positions) + PREVIEW_LAYOUT_X_GAP
        base_y = min(position["y"] for position in existing_positions)
    else:
        base_x = 0
        base_y = 0

    occupied_bounds = [_node_bounds(node) for node in existing_nodes]
    target_y = base_y
    for _ in range(50):
        candidate_bounds = [
            (
                base_x + index * PREVIEW_LAYOUT_X_GAP,
                target_y,
                base_x + index * PREVIEW_LAYOUT_X_GAP + PREVIEW_LAYOUT_NODE_WIDTH,
                target_y + PREVIEW_LAYOUT_NODE_HEIGHT,
            )
            for index, _node in enumerate(generated_nodes)
        ]
        if not any(
            _bounds_overlap(candidate, occupied)
            for candidate in candidate_bounds
            for occupied in occupied_bounds
        ):
            break
        target_y += PREVIEW_LAYOUT_Y_GAP

    for index, node in enumerate(generated_nodes):
        node["position"] = {
            "x": base_x + index * PREVIEW_LAYOUT_X_GAP,
            "y": target_y,
        }

    graph["nodes"] = nodes
    return graph


class AgentBuilderService:
    def __init__(
        self,
        db: Session,
        *,
        user: User,
        organization_id: uuid.UUID,
    ) -> None:
        self.db = db
        self.user = user
        self.organization_id = organization_id

    def create_or_restore_session(
        self,
        request: AgentBuilderSessionCreateRequest,
    ) -> AgentBuilderSessionResponse:
        workflow_id = request.workflow_id
        app_id = request.app_id
        workflow = None
        if workflow_id:
            workflow = self._workflow_in_active_org(workflow_id)
            ensure_workflow_permission(self.db, self.user, workflow.id, "write")
            app_id = workflow.app_id
        if app_id and workflow is None:
            app = self._app_in_active_org(app_id)
            denial_status = AppService.access_denial_status(
                self.db, app, self.user.id, "manage"
            )
            if denial_status is not None:
                detail = (
                    "APP_CREATE_PERMISSION_REQUIRED"
                    if denial_status == 403
                    else "App not found"
                )
                raise HTTPException(status_code=denial_status, detail=detail)

        session = (
            self.db.query(AgentBuilderSession)
            .filter(
                AgentBuilderSession.user_id == self.user.id,
                AgentBuilderSession.organization_id == self.organization_id,
                AgentBuilderSession.workflow_id == workflow_id,
                AgentBuilderSession.app_id == app_id,
                AgentBuilderSession.status == "active",
            )
            .order_by(AgentBuilderSession.updated_at.desc())
            .first()
        )
        created = False
        if session is None:
            session = AgentBuilderSession(
                organization_id=self.organization_id,
                user_id=self.user.id,
                workflow_id=workflow_id,
                app_id=app_id,
                status="active",
                expires_at=_now() + SESSION_TTL,
            )
            self.db.add(session)
            self.db.flush()
            created = True

        if created:
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_SESSION_CREATED,
                self.user.id,
                "agent_builder_session",
                session.id,
                organization_id=self.organization_id,
                metadata={
                    "session_id": str(session.id),
                    "workflow_id": str(workflow_id) if workflow_id else None,
                    "app_id": str(app_id) if app_id else None,
                },
            )
        session.updated_at = _now()
        self.db.commit()
        self.db.refresh(session)
        return self._session_response(session)

    def get_session(self, session_id: uuid.UUID) -> AgentBuilderSessionResponse:
        session = self._session_or_404(session_id)
        if not self._session_scope_allowed(session):
            return AgentBuilderSessionResponse(
                session_id=session.id,
                workflow_id=None,
                app_id=None,
                status="scope_unavailable",
                messages=[],
                pending_request=None,
                draft_preview=None,
            )
        return self._session_response(session)

    def submit_message(
        self,
        session_id: uuid.UUID,
        message_request: AgentBuilderMessageRequest,
    ) -> AgentBuilderMessageResponse:
        session = self._session_or_404(session_id)
        session = self._lock_session_for_request(session)
        self._reject_if_pending(session)
        workflow = None
        app = None
        workflow_id = message_request.workflow_id or session.workflow_id
        app_id = message_request.app_id or session.app_id
        if workflow_id:
            workflow = self._workflow_in_active_org(workflow_id)
            ensure_workflow_permission(self.db, self.user, workflow.id, "write")
            app_id = workflow.app_id
        if app_id:
            app = self._app_in_active_org(app_id)
        if workflow is None and app is not None:
            denial_status = AppService.access_denial_status(
                self.db, app, self.user.id, "manage"
            )
            if denial_status is not None:
                detail = (
                    "APP_CREATE_PERMISSION_REQUIRED"
                    if denial_status == 403
                    else "App not found"
                )
                if denial_status == 403:
                    record_resource_permission_denied(
                        user_id=self.user.id,
                        resource_type="app",
                        resource_id=app.id,
                        action="manage",
                        effective_auth_state="none",
                        organization_id=self.organization_id,
                        metadata={
                            "agent_builder_reason": "new_workflow_draft_scope_denied"
                        },
                    )
                raise HTTPException(status_code=denial_status, detail=detail)

        request_row = AgentBuilderRequest(
            session_id=session.id,
            organization_id=self.organization_id,
            user_id=self.user.id,
            status="processing",
            message_summary=_safe_summary(message_request.message),
            structured_request={},
            response_payload={},
            expires_at=_now() + SESSION_TTL,
        )
        self.db.add(request_row)
        self.db.flush()
        add_action_audit(
            self.db,
            AuditAction.AGENT_BUILDER_REQUEST_SUBMITTED,
            self.user.id,
            "agent_builder_request",
            request_row.id,
            organization_id=self.organization_id,
            metadata={"session_id": str(session.id), "request_id": str(request_row.id)},
        )
        self.db.commit()

        try:
            structured = self._build_structured_request(message_request, workflow)
            validation = self._validate_structured_request(structured, app_id=app_id)
            recommendations = self._resolve_knowledge_requirements(structured)
        except Exception:
            return self._fail_processing_request(request_row)
        if recommendations["status"] == "clarification_required":
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="clarification_required",
                structured_request=structured,
                clarification_questions=recommendations["questions"],
                validation_result=validation,
                warnings=recommendations["warnings"],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response
        if recommendations["status"] == "validation_failed":
            issue = AgentBuilderValidationIssue(
                code="KB_CANDIDATE_UNAVAILABLE",
                message="권한 확인된 Knowledge Base 후보를 찾을 수 없습니다.",
                path="knowledge_requirements",
            )
            validation = AgentBuilderValidationResult(valid=False, issues=[issue])
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="validation_failed",
                structured_request=structured,
                validation_result=validation,
                warnings=recommendations["warnings"],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response
        if not validation.valid and any(
            issue.code == "MISSING_INFORMATION" for issue in validation.issues
        ):
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="clarification_required",
                structured_request=structured,
                clarification_questions=list(structured.missing_information),
                validation_result=validation,
                warnings=[SAFE_SIDE_EFFECT_NOTICE],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response
        if not validation.valid:
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="validation_failed",
                structured_request=structured,
                validation_result=validation,
                warnings=[SAFE_SIDE_EFFECT_NOTICE],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response

        effective_selected_edge_id = self._selected_edge_id_for_message(
            workflow,
            message_request.selected_edge_id,
            message_request.message,
        )

        try:
            preview_graph = self._build_preview_graph(
                structured,
                workflow=workflow,
                kb_bindings=recommendations["bindings"],
                selected_node_id=message_request.selected_node_id,
                selected_edge_id=effective_selected_edge_id,
            )
        except HTTPException as exc:
            if exc.detail == "DRAFT_MODEL_ROUTE_REQUIRED":
                response = AgentBuilderMessageResponse(
                    request_id=request_row.id,
                    status="configuration_required",
                    structured_request=structured,
                    validation_result=AgentBuilderValidationResult(
                        valid=False,
                        issues=[
                            AgentBuilderValidationIssue(
                                code="DRAFT_MODEL_ROUTE_REQUIRED",
                                message="승인된 draft generation model route가 필요합니다.",
                                path="llm.model_id",
                            )
                        ],
                    ),
                    warnings=["모델 route가 구성되지 않아 초안을 확정하지 않았습니다."],
                )
                self._finish_request(request_row, response)
                self.db.commit()
                return response
            raise
        except Exception:
            return self._fail_processing_request(request_row)
        base_graph = workflow.graph if workflow else _empty_graph()
        base_node_ids = _graph_node_ids(base_graph)
        base_edge_ids = {
            str(edge.get("id"))
            for edge in (base_graph.get("edges") or [])
            if edge.get("id")
        }
        generated_node_ids = [
            str(node.get("id"))
            for node in (preview_graph.get("nodes") or [])
            if node.get("id") and str(node.get("id")) not in base_node_ids
        ]
        generated_edge_ids = [
            str(edge.get("id"))
            for edge in (preview_graph.get("edges") or [])
            if edge.get("id") and str(edge.get("id")) not in base_edge_ids
        ]
        draft_validation = self.validate_preview_graph(
            preview_graph,
            generated_node_ids=set(generated_node_ids) if workflow else None,
        )
        if not draft_validation.valid:
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="validation_failed",
                structured_request=structured,
                validation_result=draft_validation,
                warnings=[SAFE_SIDE_EFFECT_NOTICE],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response

        base_hash = calculate_graph_hash(base_graph)
        draft = AgentBuilderDraft(
            request_id=request_row.id,
            session_id=session.id,
            organization_id=self.organization_id,
            user_id=self.user.id,
            draft_mode=structured.draft_mode,
            workflow_id=workflow.id if workflow else None,
            app_id=app_id,
            preview_graph=preview_graph,
            node_detail_previews=self._node_detail_previews(preview_graph),
            validation_result=draft_validation.model_dump(mode="json"),
            draft_metadata={
                "base_graph_hash": base_hash,
                "base_workflow_updated_at": workflow.updated_at.isoformat()
                if workflow and workflow.updated_at
                else None,
                "safe_kb_bindings": self._safe_kb_bindings(recommendations["bindings"]),
                "structured_request": structured.model_dump(mode="json"),
                "generated_node_ids": generated_node_ids,
                "generated_edge_ids": generated_edge_ids,
                "target_resolution": {
                    "selected_node_id": message_request.selected_node_id,
                    "selected_edge_id": effective_selected_edge_id,
                },
                "app_id": str(app_id) if app_id else None,
                "workflow_id": str(workflow.id) if workflow else None,
                "workflow_scope": "existing_workflow" if workflow else "new_workflow",
            },
            base_graph_hash=base_hash,
            base_workflow_updated_at=workflow.updated_at if workflow else None,
            status="ready",
            expires_at=_now() + DRAFT_TTL,
        )
        try:
            self.db.add(draft)
            self.db.flush()
        except Exception:
            return self._fail_processing_request(request_row)
        preview = AgentBuilderDraftPreview(
            draft_id=draft.id,
            preview_graph=preview_graph,
            base_graph_hash=base_hash,
            base_workflow_updated_at=draft.base_workflow_updated_at,
            draft_mode=structured.draft_mode,
            node_detail_previews=draft.node_detail_previews,
            validation_result=draft_validation,
            safety_notices=[SAFE_SIDE_EFFECT_NOTICE],
        )
        response = AgentBuilderMessageResponse(
            request_id=request_row.id,
            status="draft_ready",
            structured_request=structured,
            draft_preview=preview,
            validation_result=draft_validation,
            preview_prompt="도안 보기",
            warnings=[SAFE_SIDE_EFFECT_NOTICE],
        )
        if self._finish_request(request_row, response) is not False:
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_DRAFT_CREATED,
                self.user.id,
                "agent_builder_draft",
                draft.id,
                organization_id=self.organization_id,
                metadata={
                    "session_id": str(session.id),
                    "request_id": str(request_row.id),
                    "draft_id": str(draft.id),
                    "draft_mode": draft.draft_mode,
                    "base_graph_hash": base_hash,
                    "validation_state": "valid",
                },
            )
            session.workflow_id = workflow.id if workflow else session.workflow_id
            session.app_id = app_id or session.app_id
            session.updated_at = _now()
        try:
            self.db.commit()
        except Exception:
            return self._fail_processing_request(request_row)
        return response

    def cancel_request(self, request_id: uuid.UUID) -> AgentBuilderMessageResponse:
        request_row = self._request_or_404(request_id)
        if request_row.status == "canceled":
            return AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="canceled",
                warnings=["요청이 이미 취소되었습니다."],
            )
        if request_row.status != "processing":
            raise HTTPException(
                status_code=409,
                detail="Agent Builder request is not pending",
            )
        canceled_at = _now()
        if isinstance(self.db, Session):
            updated = (
                self.db.query(AgentBuilderRequest)
                .filter(
                    AgentBuilderRequest.id == request_row.id,
                    AgentBuilderRequest.status == "processing",
                )
                .update(
                    {"status": "canceled", "canceled_at": canceled_at},
                    synchronize_session=False,
                )
            )
            if updated != 1:
                self.db.refresh(request_row)
                if request_row.status == "canceled":
                    return AgentBuilderMessageResponse(
                        request_id=request_row.id,
                        status="canceled",
                        warnings=["요청이 이미 취소되었습니다."],
                    )
                raise HTTPException(
                    status_code=409,
                    detail="Agent Builder request is not pending",
                )
        else:
            request_row.status = "canceled"
            request_row.canceled_at = canceled_at
        add_action_audit(
            self.db,
            AuditAction.AGENT_BUILDER_REQUEST_CANCELED,
            self.user.id,
            "agent_builder_request",
            request_row.id,
            organization_id=self.organization_id,
            metadata={"request_id": str(request_row.id), "session_id": str(request_row.session_id)},
        )
        response = AgentBuilderMessageResponse(
            request_id=request_row.id,
            status="canceled",
            warnings=["요청이 취소되었습니다."],
        )
        request_row.response_payload = response.model_dump(mode="json")
        self.db.commit()
        return response

    def record_preview_opened(self, draft_id: uuid.UUID) -> None:
        draft = self._draft_or_404(draft_id)
        metadata = {
            "draft_id": str(draft.id),
            "request_id": str(draft.request_id),
            "session_id": str(draft.session_id),
            "draft_mode": draft.draft_mode,
            "preview_graph_hash": calculate_graph_hash(draft.preview_graph),
        }
        block_reason = None
        if draft.status != "ready":
            block_reason = "DRAFT_NOT_APPLICABLE"
        elif draft.expires_at and draft.expires_at < _now():
            block_reason = "DRAFT_METADATA_EXPIRED"
        elif not (draft.validation_result or {}).get("valid", False):
            block_reason = "DRAFT_VALIDATION_FAILED"
        else:
            session = self._session_or_404(draft.session_id)
            if not self._session_scope_allowed(session):
                block_reason = "WORKFLOW_PERMISSION_REQUIRED"
        if block_reason:
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_PREVIEW_BLOCKED,
                self.user.id,
                "agent_builder_draft",
                draft.id,
                organization_id=self.organization_id,
                metadata={**metadata, "block_reason": block_reason},
                status="failure",
            )
            self.db.commit()
            raise HTTPException(status_code=409, detail=block_reason)
        add_action_audit(
            self.db,
            AuditAction.AGENT_BUILDER_PREVIEW_OPENED,
            self.user.id,
            "agent_builder_draft",
            draft.id,
            organization_id=self.organization_id,
            metadata=metadata,
        )
        self.db.commit()

    def apply_draft(
        self,
        draft_id: uuid.UUID,
        apply_request: AgentBuilderApplyRequest,
    ) -> AgentBuilderApplyResponse:
        apply_id = uuid.uuid4()
        try:
            draft = self._draft_or_404(draft_id)
        except HTTPException:
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_APPLY_SAVE_BLOCKED,
                self.user.id,
                "agent_builder_draft",
                draft_id,
                organization_id=self.organization_id,
                metadata={
                    "apply_id": str(apply_id),
                    "draft_id": str(draft_id),
                    "outcome": "blocked",
                    "block_reason": "DRAFT_METADATA_NOT_FOUND",
                },
                status="failure",
            )
            self.db.commit()
            return AgentBuilderApplyResponse(
                apply_id=apply_id,
                outcome="blocked",
                block_reason="DRAFT_METADATA_NOT_FOUND",
                audit_recorded=True,
                notices=["초안 정보를 확인할 수 없어 저장을 차단했습니다."],
            )
        try:
            draft = self._lock_draft_for_apply(draft)
        except HTTPException:
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_APPLY_SAVE_BLOCKED,
                self.user.id,
                "agent_builder_draft",
                draft_id,
                organization_id=self.organization_id,
                metadata={
                    "apply_id": str(apply_id),
                    "draft_id": str(draft_id),
                    "outcome": "blocked",
                    "block_reason": "DRAFT_METADATA_NOT_FOUND",
                },
                status="failure",
            )
            self.db.commit()
            return AgentBuilderApplyResponse(
                apply_id=apply_id,
                outcome="blocked",
                block_reason="DRAFT_METADATA_NOT_FOUND",
                audit_recorded=True,
                notices=["초안 정보를 확인할 수 없어 적용 및 저장을 차단했습니다."],
            )
        metadata_base = self._apply_metadata_base(draft, apply_id)
        add_action_audit(
            self.db,
            AuditAction.AGENT_BUILDER_APPLY_SAVE_REQUESTED,
            self.user.id,
            "agent_builder_draft",
            draft.id,
            organization_id=self.organization_id,
            metadata={**metadata_base, "requested_action": apply_request.action},
        )
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            return AgentBuilderApplyResponse(
                apply_id=apply_id,
                outcome="failed",
                failure_reason="AUDIT_RECORD_FAILED",
                audit_recorded=False,
                notices=[
                    "적용 및 저장 요청 audit 기록에 실패했습니다. Preview Mode를 유지하고 다시 시도해주세요."
                ],
            )
        if apply_request.action == "cancel":
            if draft.status != "ready":
                return self._block_apply(
                    draft,
                    apply_id,
                    "DRAFT_NOT_APPLICABLE",
                    metadata_base,
                    notice="이미 처리되었거나 취소된 초안은 다시 취소할 수 없습니다.",
                    mark_blocked=False,
                )
            draft.status = "canceled"
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_APPLY_SAVE_CANCELED,
                self.user.id,
                "agent_builder_draft",
                draft.id,
                organization_id=self.organization_id,
                metadata={**metadata_base, "outcome": "canceled"},
            )
            self.db.commit()
            return AgentBuilderApplyResponse(
                apply_id=apply_id,
                outcome="canceled",
                block_reason="USER_CANCELED",
                audit_recorded=True,
                notices=["도안 적용을 취소했습니다. 실제 workflow graph는 변경되지 않았습니다."],
            )

        if draft.status != "ready":
            return self._block_apply(
                draft,
                apply_id,
                "DRAFT_NOT_APPLICABLE",
                metadata_base,
                notice="이미 처리되었거나 취소된 초안은 다시 적용할 수 없습니다.",
                mark_blocked=False,
            )

        if draft.expires_at and draft.expires_at < _now():
            return self._block_apply(
                draft,
                apply_id,
                "DRAFT_METADATA_EXPIRED",
                metadata_base,
                notice="초안 정보가 만료되었습니다. 다시 생성해주세요.",
            )
        if not apply_request.client_preview_graph_hash:
            return self._block_apply(
                draft,
                apply_id,
                "DRAFT_STALE",
                metadata_base,
                stale_state="preview_hash_missing",
                notice="확인한 도안 hash가 없어 저장을 진행할 수 없습니다. 도안을 다시 확인해주세요.",
                mark_blocked=False,
            )
        if (
            calculate_graph_hash(draft.preview_graph)
            != apply_request.client_preview_graph_hash
        ):
            return self._block_apply(
                draft,
                apply_id,
                "DRAFT_STALE",
                metadata_base,
                stale_state="preview_hash_mismatch",
                notice="확인한 도안과 서버 초안이 일치하지 않습니다. 다시 확인해주세요.",
                mark_blocked=False,
            )

        workflow = None
        latest_graph_hash = None
        draft_metadata = draft.draft_metadata or {}
        metadata_workflow_id = draft_metadata.get("workflow_id")
        target_workflow_id = draft.workflow_id
        if target_workflow_id is None and metadata_workflow_id:
            target_workflow_id = (
                metadata_workflow_id
                if isinstance(metadata_workflow_id, uuid.UUID)
                else uuid.UUID(str(metadata_workflow_id))
            )
        if draft.draft_mode in {"modify_workflow", "replace_workflow"}:
            if not target_workflow_id:
                return self._block_apply(
                    draft,
                    apply_id,
                    "DRAFT_METADATA_NOT_FOUND",
                    metadata_base,
                    notice="원 workflow 정보를 확인할 수 없어 초안을 적용할 수 없습니다.",
                )
            try:
                workflow = self._lock_workflow_for_apply(target_workflow_id)
            except HTTPException:
                return self._block_apply(
                    draft,
                    apply_id,
                    "DRAFT_METADATA_NOT_FOUND",
                    metadata_base,
                    stale_state="target_workflow_missing",
                    notice="원 workflow를 확인할 수 없어 초안을 적용할 수 없습니다.",
                )
            if not has_workflow_permission(
                self.db,
                self.user.id,
                workflow.id,
                "write",
                organization_id=self.organization_id,
            ):
                return self._block_apply(
                    draft,
                    apply_id,
                    "WORKFLOW_PERMISSION_REQUIRED",
                    metadata_base,
                    permission_outcome="denied",
                    notice="기존 workflow를 수정할 권한이 없습니다.",
                )
            latest_graph_hash = calculate_graph_hash(workflow.graph)
            if not apply_request.client_latest_graph_hash:
                return self._block_apply(
                    draft,
                    apply_id,
                    "UNSAVED_EDITOR_CHANGES",
                    metadata_base,
                    latest_graph_hash=latest_graph_hash,
                    stale_state="client_graph_hash_missing",
                    notice="현재 editor graph hash가 없어 저장되지 않은 변경 여부를 확인할 수 없습니다.",
                    mark_blocked=False,
                )
            if (
                apply_request.client_latest_graph_hash
                and apply_request.client_latest_graph_hash != latest_graph_hash
            ):
                return self._block_apply(
                    draft,
                    apply_id,
                    "UNSAVED_EDITOR_CHANGES",
                    metadata_base,
                    latest_graph_hash=latest_graph_hash,
                    stale_state="client_graph_mismatch",
                    notice="저장되지 않은 editor 변경이 있어 초안을 적용할 수 없습니다.",
                    mark_blocked=False,
                )
            if latest_graph_hash != draft.base_graph_hash or (
                draft.base_workflow_updated_at
                and workflow.updated_at
                and workflow.updated_at != draft.base_workflow_updated_at
            ):
                return self._block_apply(
                    draft,
                    apply_id,
                    "DRAFT_STALE",
                    metadata_base,
                    latest_graph_hash=latest_graph_hash,
                    latest_workflow_updated_at=workflow.updated_at,
                    stale_state="stale",
                    notice="workflow가 초안 생성 이후 변경되었습니다. 도안을 다시 생성해주세요.",
                )
        else:
            if not draft.app_id:
                return self._block_apply(
                    draft,
                    apply_id,
                    "APP_CREATE_PERMISSION_REQUIRED",
                    metadata_base,
                    notice="새 workflow를 생성할 app scope가 없습니다.",
                )
            try:
                app = self._app_in_active_org(draft.app_id)
            except HTTPException:
                return self._block_apply(
                    draft,
                    apply_id,
                    "DRAFT_METADATA_NOT_FOUND",
                    metadata_base,
                    stale_state="target_app_missing",
                    notice="대상 App을 확인할 수 없어 초안을 적용할 수 없습니다.",
                )
            if (
                AppService.access_denial_status(self.db, app, self.user.id, "manage")
                is not None
            ):
                return self._block_apply(
                    draft,
                    apply_id,
                    "APP_CREATE_PERMISSION_REQUIRED",
                    metadata_base,
                    permission_outcome="denied",
                    notice="새 workflow를 생성할 권한이 없습니다.",
                )

        runtime_kb_bindings = self._runtime_kb_bindings_for_apply(draft)
        if isinstance(runtime_kb_bindings, str):
            return self._block_apply(
                draft,
                apply_id,
                runtime_kb_bindings,
                metadata_base,
                permission_outcome=(
                    "denied"
                    if runtime_kb_bindings == "KB_PERMISSION_REQUIRED"
                    else "allowed"
                ),
                validation_state="invalid",
                notice="Knowledge Base 권한 또는 후보 정보를 다시 확인할 수 없어 저장을 차단했습니다.",
            )

        save_graph = self._graph_for_apply(
            draft,
            workflow,
            runtime_kb_bindings=runtime_kb_bindings,
        )
        generated_node_ids = set((draft.draft_metadata or {}).get("generated_node_ids") or [])
        validation = self.validate_preview_graph(
            save_graph,
            generated_node_ids=generated_node_ids
            if workflow and draft.draft_mode == "modify_workflow"
            else None,
        )
        if not validation.valid:
            return self._block_apply(
                draft,
                apply_id,
                "DRAFT_VALIDATION_FAILED",
                metadata_base,
                validation_state="invalid",
                notice="도안 검증에 실패했습니다. 다시 생성해주세요.",
            )

        try:
            if workflow is None:
                workflow = Workflow(
                    organization_id=self.organization_id,
                    app_id=draft.app_id,
                    created_by=self.user.id,
                    updated_by=self.user.id,
                    graph=save_graph,
                    features={},
                    env_variables=[],
                    runtime_variables=[],
                )
                self.db.add(workflow)
                self.db.flush()
                AppService._grant_workflow_manager_permission(
                    self.db, workflow, self.user.id, self.organization_id
                )
                app = self._app_in_active_org(draft.app_id)
                if app.workflow_id is None:
                    app.workflow_id = workflow.id
            else:
                workflow.graph = save_graph
                workflow.updated_by = self.user.id
            draft.status = "applied"
            draft.workflow_id = workflow.id
            saved_hash = calculate_graph_hash(save_graph)
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_APPLY_SAVE_SUCCEEDED,
                self.user.id,
                "workflow",
                workflow.id,
                organization_id=self.organization_id,
                metadata={
                    **metadata_base,
                    "workflow_id": str(workflow.id),
                    "saved_workflow_id": str(workflow.id),
                    "latest_graph_hash": saved_hash,
                    "outcome": "saved",
                    "permission_recheck_outcome": "allowed",
                    "stale_state": "not_stale",
                    "validation_state": "valid",
                    "audit_durability": "same_transaction_audit_log",
                },
            )
            self.db.commit()
            try:
                self.db.refresh(workflow)
                saved_updated_at = workflow.updated_at
            except Exception:
                saved_updated_at = None
            return AgentBuilderApplyResponse(
                apply_id=apply_id,
                outcome="saved",
                saved_workflow_id=workflow.id,
                latest_graph_hash=saved_hash,
                latest_workflow_updated_at=saved_updated_at,
                stale_state="not_stale",
                permission_recheck_outcome="allowed",
                validation_state="valid",
                audit_recorded=True,
                notices=[
                    "도안을 workflow graph로 저장했습니다. 실행은 별도 사용자 동작으로만 시작됩니다."
                ],
            )
        except Exception:
            self.db.rollback()
            failed_audit_recorded = False
            try:
                add_action_audit(
                    self.db,
                    AuditAction.AGENT_BUILDER_APPLY_SAVE_FAILED,
                    self.user.id,
                    "agent_builder_draft",
                    draft.id,
                    organization_id=self.organization_id,
                    metadata={**metadata_base, "outcome": "failed"},
                )
                self.db.commit()
                failed_audit_recorded = True
            except Exception:
                self.db.rollback()
            return AgentBuilderApplyResponse(
                apply_id=apply_id,
                outcome="failed",
                failure_reason="SAVE_FAILED",
                permission_recheck_outcome="allowed",
                validation_state="valid",
                audit_recorded=failed_audit_recorded,
                notices=["저장 또는 audit 기록에 실패했습니다. Preview Mode를 유지하고 다시 시도해주세요."],
            )

    def _apply_metadata_base(
        self,
        draft: AgentBuilderDraft,
        apply_id: uuid.UUID,
    ) -> dict[str, Any]:
        return {
            "apply_id": str(apply_id),
            "draft_id": str(draft.id),
            "request_id": str(draft.request_id),
            "session_id": str(draft.session_id),
            "draft_mode": draft.draft_mode,
            "base_graph_hash": draft.base_graph_hash,
            "preview_graph_hash": calculate_graph_hash(draft.preview_graph),
        }

    def _lock_draft_for_apply(self, draft: AgentBuilderDraft) -> AgentBuilderDraft:
        if not isinstance(self.db, Session):
            return draft
        locked = (
            self.db.query(AgentBuilderDraft)
            .filter(
                AgentBuilderDraft.id == draft.id,
                AgentBuilderDraft.user_id == self.user.id,
                AgentBuilderDraft.organization_id == self.organization_id,
            )
            .with_for_update()
            .first()
        )
        if locked is None:
            raise HTTPException(status_code=404, detail="Agent Builder draft not found")
        return locked

    def validate_preview_graph(
        self,
        graph: dict[str, Any] | None,
        *,
        generated_node_ids: set[str] | None = None,
    ) -> AgentBuilderValidationResult:
        issues: list[AgentBuilderValidationIssue] = []
        graph = graph or {}
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        node_ids = _graph_node_ids(graph)
        for node in nodes:
            node_id = str(node.get("id") or "")
            if generated_node_ids is not None and node_id not in generated_node_ids:
                continue
            node_type = node.get("type")
            if node_type not in MVP_SUPPORTED_NODE_TYPES:
                issues.append(
                    AgentBuilderValidationIssue(
                        code="UNSUPPORTED_NODE_TYPE",
                        message=f"지원하지 않는 node type입니다: {node_type}",
                        path=f"nodes.{node.get('id')}",
                    )
                )
            if node_type == "llmNode":
                data = node.get("data") or {}
                if not data.get("model_id"):
                    issues.append(
                        AgentBuilderValidationIssue(
                            code="MISSING_LLM_MODEL",
                            message="LLM node model 설정이 필요합니다.",
                            path=f"nodes.{node.get('id')}.data.model_id",
                        )
                    )
        for edge in edges:
            if edge.get("source") not in node_ids or edge.get("target") not in node_ids:
                issues.append(
                    AgentBuilderValidationIssue(
                        code="INVALID_EDGE_REFERENCE",
                        message="edge가 존재하지 않는 node를 참조합니다.",
                        path=f"edges.{edge.get('id')}",
                    )
                )
        return AgentBuilderValidationResult(valid=not issues, issues=issues)

    def _block_apply(
        self,
        draft: AgentBuilderDraft,
        apply_id: uuid.UUID,
        reason: str,
        metadata_base: dict[str, Any],
        *,
        latest_graph_hash: str | None = None,
        latest_workflow_updated_at: datetime | None = None,
        permission_outcome: str = "allowed",
        validation_state: str = "valid",
        stale_state: str = "not_stale",
        notice: str,
        mark_blocked: bool = False,
    ) -> AgentBuilderApplyResponse:
        if mark_blocked:
            draft.status = "blocked"
        add_action_audit(
            self.db,
            AuditAction.AGENT_BUILDER_APPLY_SAVE_BLOCKED,
            self.user.id,
            "agent_builder_draft",
            draft.id,
            organization_id=self.organization_id,
            metadata={
                **metadata_base,
                "outcome": "blocked",
                "block_reason": reason,
                "latest_graph_hash": latest_graph_hash,
                "permission_recheck_outcome": permission_outcome,
                "validation_state": validation_state,
                "stale_state": stale_state,
            },
            status="failure",
        )
        self.db.commit()
        return AgentBuilderApplyResponse(
            apply_id=apply_id,
            outcome="blocked",
            latest_graph_hash=latest_graph_hash,
            latest_workflow_updated_at=latest_workflow_updated_at,
            block_reason=reason,
            stale_state=stale_state,
            permission_recheck_outcome=permission_outcome,
            validation_state=validation_state,
            audit_recorded=True,
            notices=[notice],
        )

    def _build_structured_request(
        self,
        request: AgentBuilderMessageRequest,
        workflow: Workflow | None,
    ) -> AgentBuilderStructuredRequest:
        text = request.message.lower()
        needs_kb = any(
            token in request.message
            for token in ["정책", "규정", "내규", "문서", "자료", "근거", "찾아", "검색", "Knowledge", "KB"]
        )
        wants_slack = "slack" in text or "슬랙" in request.message
        knowledge_requirements: list[AgentBuilderKnowledgeRequirement] = []
        pending_resolution: list[AgentBuilderPendingResolution] = []
        if needs_kb:
            knowledge_requirements.append(
                AgentBuilderKnowledgeRequirement(
                    requirement_id="kr_1",
                    query_topics=[_safe_summary(request.message, limit=80)],
                    expected_evidence_type="policy_or_reference",
                    required=True,
                    target_step_ref="step_llm",
                )
            )
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id="res_kb_1",
                    slot_type="knowledge_base",
                    slot_key="llm.knowledgeBases",
                    blocking=True,
                    target_step_ref="step_llm",
                )
            )
        missing_information = []
        if wants_slack:
            missing_information.append("Slack 채널을 선택해야 합니다.")
        explicit_new_workflow = _message_requests_new_workflow(request.message)
        draft_mode = (
            "new_workflow" if explicit_new_workflow or workflow is None else "modify_workflow"
        )
        return AgentBuilderStructuredRequest(
            request_type=draft_mode,
            draft_mode=draft_mode,
            intent_summary=_safe_summary(request.message),
            planned_steps=[
                AgentBuilderPlannedStep(
                    step_id="step_input",
                    capability="start_input",
                    purpose="사용자 입력을 받습니다.",
                ),
                AgentBuilderPlannedStep(
                    step_id="step_llm",
                    capability="knowledge_backed_llm" if needs_kb else "llm",
                    purpose="입력을 분석하고 답변을 생성합니다.",
                    depends_on=["step_input"],
                ),
                AgentBuilderPlannedStep(
                    step_id="step_answer",
                    capability="answer",
                    purpose="결과를 사용자에게 반환합니다.",
                    depends_on=["step_llm"],
                ),
            ],
            knowledge_requirements=knowledge_requirements,
            required_capabilities=["start_input", "llm", "answer"]
            + (["knowledge_base"] if needs_kb else []),
            pending_resolution=pending_resolution,
            missing_information=missing_information,
            risk_flags=["external_action_requested"] if wants_slack else [],
        )

    def _selected_edge_id_for_message(
        self,
        workflow: Workflow | None,
        selected_edge_id: str | None,
        message: str,
    ) -> str | None:
        if not workflow or not selected_edge_id:
            return None
        if not _message_mentions_edge_context(message):
            return None
        return (
            selected_edge_id
            if any(
                str(edge.get("id")) == selected_edge_id
                for edge in (workflow.graph or {}).get("edges") or []
            )
            else None
        )

    def _validate_structured_request(
        self,
        structured: AgentBuilderStructuredRequest,
        *,
        app_id: uuid.UUID | None,
    ) -> AgentBuilderValidationResult:
        issues: list[AgentBuilderValidationIssue] = []
        if structured.draft_mode == "new_workflow" and app_id is None:
            issues.append(
                AgentBuilderValidationIssue(
                    code="APP_SCOPE_REQUIRED",
                    message="새 workflow draft를 생성할 app scope가 필요합니다.",
                    path="app_id",
                )
            )
        if structured.missing_information:
            issues.append(
                AgentBuilderValidationIssue(
                    code="MISSING_INFORMATION",
                    message="사용자 확인이 필요한 정보가 있습니다.",
                    path="missing_information",
                )
            )
        return AgentBuilderValidationResult(valid=not issues, issues=issues)

    def _resolve_knowledge_requirements(
        self,
        structured: AgentBuilderStructuredRequest,
        *,
        include_materialized_refs: bool = False,
    ) -> dict[str, Any]:
        if not structured.knowledge_requirements:
            return {"status": "not_required", "bindings": [], "questions": [], "warnings": []}

        service = KnowledgeRAGRecommendationService(
            self.db,
            user_id=self.user.id,
            organization_id=self.organization_id,
        )
        bindings = []
        warnings = []
        pending_by_step = {
            item.target_step_ref: item.resolution_id
            for item in structured.pending_resolution
            if item.slot_type == "knowledge_base"
        }
        for requirement in structured.knowledge_requirements:
            response = service.recommend_for_builder(
                KnowledgeRAGRecommendationRequest(
                    workflow_intent=structured.intent_summary,
                    node_purpose="; ".join(requirement.query_topics) or requirement.expected_evidence_type,
                    knowledge_requirement=requirement.model_dump(mode="json"),
                    pending_resolution_ref=pending_by_step.get(requirement.target_step_ref),
                    safe_workflow_context_summary={
                        "planned_step_count": len(structured.planned_steps),
                        "required_capabilities": structured.required_capabilities,
                    },
                    intended_execution_subject_id=self.user.id,
                    mode="auto",
                    max_recommendations=3,
                ),
                include_materialized_refs=include_materialized_refs,
            )
            if response.status == "unavailable":
                return {
                    "status": "validation_failed"
                    if requirement.required
                    else "clarification_required",
                    "bindings": [],
                    "questions": ["사용할 Knowledge Base를 선택해주세요."],
                    "warnings": [
                        response.user_safe_warning
                        or "Knowledge Base 추천을 사용할 수 없습니다."
                    ],
                }
            recommendations = list(response.recommendations or [])
            if not recommendations:
                return {
                    "status": "validation_failed"
                    if requirement.required
                    else "clarification_required",
                    "bindings": [],
                    "questions": ["사용할 Knowledge Base를 선택해주세요."],
                    "warnings": ["권한 확인된 Knowledge Base 후보가 없습니다."],
                }
            top = recommendations[0]
            top_score = top.score if top.score is not None else 0.0
            second_score = (
                recommendations[1].score
                if len(recommendations) > 1
                and recommendations[1].score is not None
                else 0.0
            )
            high_confidence = (
                top.confidence == "high"
                and top.threshold_result == "high_confidence"
            ) and (
                len(recommendations) == 1
                or top_score - second_score >= 0.1
            )
            if not high_confidence:
                return {
                    "status": "clarification_required",
                    "bindings": [],
                    "questions": ["추천 후보가 여러 개입니다. 사용할 Knowledge Base를 선택해주세요."],
                    "warnings": ["Knowledge Base 후보가 비슷해 자동 선택하지 않았습니다."],
                }
            binding_base = {
                "safe_handle": top.candidate_handle or top.recommendation_id,
                "name": _safe_display_label(top.safe_label),
                "confidence": top.confidence,
                "score": top_score,
                "reason_category": top.reason_category or top.safe_reason_code,
                "threshold_result": top.threshold_result or "high_confidence",
            }
            if include_materialized_refs:
                for ref in top.materialized_knowledge_bases:
                    bindings.append(
                        {
                            **binding_base,
                            "knowledge_base_id": str(ref.id),
                            "name": _safe_display_label(ref.name),
                        }
                    )
            else:
                bindings.append(binding_base)
            warnings.extend(top.warnings)
        return {"status": "recommended", "bindings": bindings, "questions": [], "warnings": warnings}

    def _safe_kb_bindings(self, bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "safe_handle": item.get("safe_handle"),
                "name": _safe_display_label(item.get("name")),
                "confidence": item.get("confidence"),
                "score": item.get("score"),
                "reason_category": item.get("reason_category"),
                "threshold_result": item.get("threshold_result"),
            }
            for item in bindings
        ]

    def _runtime_kb_bindings(self, bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "safe_handle": item.get("safe_handle"),
                "knowledge_base_id": item.get("knowledge_base_id"),
            }
            for item in bindings
            if item.get("safe_handle") and item.get("knowledge_base_id")
        ]

    def _runtime_kb_bindings_for_apply(
        self, draft: AgentBuilderDraft
    ) -> list[dict[str, Any]] | str:
        required_handles = {
            ref.get("id")
            for node in (draft.preview_graph or {}).get("nodes") or []
            for ref in ((node.get("data") or {}).get("knowledgeBases") or [])
            if ref.get("reference_type") == "safe_candidate_handle"
        }
        if not required_handles:
            return []

        structured_payload = (draft.draft_metadata or {}).get("structured_request")
        try:
            structured = AgentBuilderStructuredRequest.model_validate(structured_payload)
        except Exception:
            return "KB_CANDIDATE_UNAVAILABLE"

        recommendations = self._resolve_knowledge_requirements(
            structured,
            include_materialized_refs=True,
        )
        if recommendations["status"] != "recommended":
            return (
                "KB_PERMISSION_REQUIRED"
                if recommendations["status"] == "validation_failed"
                else "KB_CANDIDATE_UNAVAILABLE"
            )

        runtime_bindings = self._runtime_kb_bindings(recommendations["bindings"])
        runtime_handles = {item.get("safe_handle") for item in runtime_bindings}
        if required_handles - runtime_handles:
            return "KB_CANDIDATE_UNAVAILABLE"
        return runtime_bindings

    def _materialize_kb_refs_for_save(
        self,
        graph: dict[str, Any],
        runtime_kb_bindings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        graph = copy.deepcopy(graph)
        handle_to_runtime_id = {
            item.get("safe_handle"): item.get("knowledge_base_id")
            for item in runtime_kb_bindings
        }
        for node in graph.get("nodes") or []:
            data = node.get("data") or {}
            materialized_refs = []
            for ref in data.get("knowledgeBases") or []:
                runtime_id = handle_to_runtime_id.get(ref.get("id"))
                if runtime_id:
                    materialized_refs.append(
                        {"id": runtime_id, "name": _safe_display_label(ref.get("name"))}
                    )
            if materialized_refs:
                data["knowledgeBases"] = materialized_refs
        return graph

    def _graph_for_apply(
        self,
        draft: AgentBuilderDraft,
        workflow: Workflow | None,
        *,
        runtime_kb_bindings: list[dict[str, Any]],
    ) -> dict[str, Any]:
        materialized_preview = self._materialize_kb_refs_for_save(
            draft.preview_graph,
            runtime_kb_bindings,
        )
        if workflow is None or draft.draft_mode == "replace_workflow":
            return materialized_preview

        save_graph = copy.deepcopy(workflow.graph or _empty_graph())
        generated_node_ids = set((draft.draft_metadata or {}).get("generated_node_ids") or [])
        generated_edge_ids = set((draft.draft_metadata or {}).get("generated_edge_ids") or [])
        target_resolution = (draft.draft_metadata or {}).get("target_resolution") or {}
        selected_edge_id = target_resolution.get("selected_edge_id")
        existing_node_ids = _graph_node_ids(save_graph)
        existing_edge_ids = {
            str(edge.get("id"))
            for edge in (save_graph.get("edges") or [])
            if edge.get("id")
        }
        save_graph["nodes"] = (save_graph.get("nodes") or []) + [
            node
            for node in materialized_preview.get("nodes") or []
            if str(node.get("id")) in generated_node_ids
            and str(node.get("id")) not in existing_node_ids
        ]
        if selected_edge_id:
            save_graph["edges"] = [
                edge
                for edge in save_graph.get("edges") or []
                if str(edge.get("id")) != str(selected_edge_id)
            ]
        save_graph["edges"] = (save_graph.get("edges") or []) + [
            edge
            for edge in materialized_preview.get("edges") or []
            if str(edge.get("id")) in generated_edge_ids
            and str(edge.get("id")) not in existing_edge_ids
        ]
        save_graph.setdefault("viewport", workflow.graph.get("viewport") if workflow.graph else None)
        return save_graph

    def _build_preview_graph(
        self,
        structured: AgentBuilderStructuredRequest,
        *,
        workflow: Workflow | None,
        kb_bindings: list[dict[str, Any]],
        selected_node_id: str | None = None,
        selected_edge_id: str | None = None,
    ) -> dict[str, Any]:
        graph = _redact_graph_for_preview(workflow.graph if workflow else _empty_graph())
        if structured.draft_mode == "new_workflow":
            graph = _empty_graph()
        existing_ids = _graph_node_ids(graph)
        suffix = uuid.uuid4().hex[:8]
        input_id = self._unique_node_id("agent-input", existing_ids, suffix)
        llm_id = self._unique_node_id("agent-llm", existing_ids | {input_id}, suffix)
        answer_id = self._unique_node_id(
            "agent-answer", existing_ids | {input_id, llm_id}, suffix
        )
        model_id = self._default_model_id()
        kb_refs = [
            {
                "id": item["safe_handle"],
                "name": _safe_display_label(item.get("name")),
                "reference_type": "safe_candidate_handle",
            }
            for item in kb_bindings
        ]
        generated_nodes = [
            {
                "id": input_id,
                "type": "startNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "title": "입력",
                    "triggerType": "manual",
                    "variables": [
                        {
                            "id": "question",
                            "name": "question",
                            "label": "질문",
                            "type": "paragraph",
                            "required": True,
                        }
                    ],
                },
            },
            {
                "id": llm_id,
                "type": "llmNode",
                "position": {"x": 360, "y": 0},
                "data": {
                    "title": "Knowledge Base-backed LLM" if kb_refs else "LLM",
                    "provider": "configured",
                    "model_id": model_id,
                    "task_type": "answer",
                    "system_prompt": "사용자 질문에 안전하게 답변합니다.",
                    "user_prompt": "{{question}}",
                    "referenced_variables": [
                        {"name": "question", "value_selector": [input_id, "question"]}
                    ],
                    "parameters": {},
                    "output_format": {"type": "text"},
                    "knowledgeBases": kb_refs,
                    "scoreThreshold": 0.5,
                    "topK": 3,
                },
            },
            {
                "id": answer_id,
                "type": "answerNode",
                "position": {"x": 720, "y": 0},
                "data": {
                    "title": "응답",
                    "outputs": [
                        {"variable": "answer", "value_selector": [llm_id, "text"]}
                    ],
                },
            },
        ]
        generated_edges = [
            {
                "id": f"edge-{input_id}-{llm_id}",
                "source": input_id,
                "target": llm_id,
            },
            {
                "id": f"edge-{llm_id}-{answer_id}",
                "source": llm_id,
                "target": answer_id,
            },
        ]
        layout_anchor_node_id = None
        if structured.draft_mode == "modify_workflow":
            selected_edge = next(
                (
                    edge
                    for edge in graph.get("edges") or []
                    if selected_edge_id and str(edge.get("id")) == selected_edge_id
                ),
                None,
            )
            selected_node_exists = any(
                selected_node_id and str(node.get("id")) == selected_node_id
                for node in graph.get("nodes") or []
            )
            if selected_edge:
                graph["edges"] = [
                    edge
                    for edge in graph.get("edges") or []
                    if str(edge.get("id")) != selected_edge_id
                ]
                layout_anchor_node_id = str(selected_edge.get("source") or "")
                generated_edges = [
                    {
                        "id": f"edge-{selected_edge['source']}-{input_id}",
                        "source": selected_edge["source"],
                        "sourceHandle": selected_edge.get("sourceHandle"),
                        "target": input_id,
                    },
                    *generated_edges,
                    {
                        "id": f"edge-{answer_id}-{selected_edge['target']}",
                        "source": answer_id,
                        "target": selected_edge["target"],
                        "targetHandle": selected_edge.get("targetHandle"),
                    },
                ]
            elif selected_node_exists and selected_node_id:
                layout_anchor_node_id = selected_node_id
                generated_edges = [
                    {
                        "id": f"edge-{selected_node_id}-{input_id}",
                        "source": selected_node_id,
                        "target": input_id,
                    },
                    *generated_edges,
                ]

        graph["nodes"] = (graph.get("nodes") or []) + generated_nodes
        graph["edges"] = (graph.get("edges") or []) + generated_edges
        graph = _layout_generated_preview_nodes(
            graph,
            [input_id, llm_id, answer_id],
            anchor_node_id=layout_anchor_node_id,
        )
        graph.setdefault("viewport", {"x": 0, "y": 0, "zoom": 1})
        return graph

    def _default_model_id(self) -> str:
        model_id = os.getenv(APPROVED_DRAFT_MODEL_ENV, "").strip()
        if model_id:
            return model_id
        raise HTTPException(status_code=409, detail="DRAFT_MODEL_ROUTE_REQUIRED")

    def _node_detail_previews(self, graph: dict[str, Any]) -> list[dict[str, Any]]:
        previews = []
        for node in graph.get("nodes") or []:
            data = node.get("data") or {}
            kb_refs = data.get("knowledgeBases") or []
            previews.append(
                {
                    "node_id": node.get("id"),
                    "node_type": node.get("type"),
                    "title": data.get("title"),
                    "knowledge_base_binding": [
                        {"name": kb.get("name"), "safe_handle": kb.get("id")} for kb in kb_refs
                    ],
                    "slack_channel_binding": self._safe_slack_binding(data),
                    "credential_reference_state": "not_exposed",
                    "input_output_mapping": self._safe_io_mapping(data),
                    "validation_state": "valid",
                    "editable": False,
                }
            )
        return previews

    def _safe_slack_binding(self, data: dict[str, Any]) -> dict[str, Any] | None:
        channel = data.get("channel") or data.get("channelName") or data.get("slackChannel")
        if not channel:
            return None
        return {"label": _safe_summary(str(channel), limit=80)}

    def _safe_io_mapping(self, data: dict[str, Any]) -> dict[str, Any]:
        inputs = data.get("inputs") or data.get("inputMapping") or {}
        outputs = data.get("outputs") or data.get("outputMapping") or {}
        return {
            "inputs": _safe_summary(
                json.dumps(inputs, ensure_ascii=False, sort_keys=True),
                limit=200,
            ),
            "outputs": _safe_summary(
                json.dumps(outputs, ensure_ascii=False, sort_keys=True),
                limit=200,
            ),
        }

    def _unique_node_id(self, prefix: str, existing_ids: set[str], suffix: str) -> str:
        candidate = f"{prefix}-{suffix}"
        counter = 1
        while candidate in existing_ids:
            counter += 1
            candidate = f"{prefix}-{suffix}-{counter}"
        return candidate

    def _session_response(self, session: AgentBuilderSession) -> AgentBuilderSessionResponse:
        now = _now()
        latest_request = (
            self.db.query(AgentBuilderRequest)
            .filter(
                AgentBuilderRequest.session_id == session.id,
                or_(
                    AgentBuilderRequest.expires_at.is_(None),
                    AgentBuilderRequest.expires_at > now,
                ),
            )
            .order_by(AgentBuilderRequest.created_at.desc())
            .first()
        )
        latest_draft = (
            self.db.query(AgentBuilderDraft)
            .filter(
                AgentBuilderDraft.session_id == session.id,
                or_(
                    AgentBuilderDraft.expires_at.is_(None),
                    AgentBuilderDraft.expires_at > now,
                ),
            )
            .order_by(AgentBuilderDraft.created_at.desc())
            .first()
        )
        return AgentBuilderSessionResponse(
            session_id=session.id,
            workflow_id=session.workflow_id,
            app_id=session.app_id,
            status=session.status,
            messages=[
                self._message_payload_with_latest_preview(latest_request, latest_draft)
            ]
            if latest_request
            else [],
            pending_request=self._request_summary(latest_request)
            if latest_request and latest_request.status == "processing"
            else None,
            draft_preview=self._draft_summary(latest_draft) if latest_draft else None,
        )

    def _session_scope_allowed(self, session: AgentBuilderSession) -> bool:
        if session.workflow_id:
            try:
                workflow = self._workflow_in_active_org(session.workflow_id)
            except HTTPException:
                return False
            return has_workflow_permission(
                self.db,
                self.user.id,
                workflow.id,
                "write",
                organization_id=self.organization_id,
            )
        if session.app_id:
            try:
                app = self._app_in_active_org(session.app_id)
            except HTTPException:
                return False
            return (
                AppService.access_denial_status(
                    self.db,
                    app,
                    self.user.id,
                    "manage",
                )
                is None
            )
        return True

    def _request_summary(self, request_row: AgentBuilderRequest) -> dict[str, Any]:
        return {
            "request_id": str(request_row.id),
            "status": request_row.status,
            "created_at": request_row.created_at.isoformat()
            if request_row.created_at
            else None,
        }

    def _draft_summary(self, draft: AgentBuilderDraft) -> dict[str, Any]:
        return {
            "draft_id": str(draft.id),
            "status": draft.status,
            "draft_mode": draft.draft_mode,
            "base_graph_hash": draft.base_graph_hash,
            "validation_result": draft.validation_result,
        }

    def _message_payload_with_latest_preview(
        self,
        request_row: AgentBuilderRequest,
        draft: AgentBuilderDraft | None,
    ) -> dict[str, Any]:
        payload = copy.deepcopy(request_row.response_payload or {})
        if (
            draft is not None
            and draft.request_id == request_row.id
            and draft.status == "ready"
            and (draft.validation_result or {}).get("valid", False)
            and not (draft.expires_at and draft.expires_at < _now())
        ):
            payload["draft_preview"] = AgentBuilderDraftPreview(
                draft_id=draft.id,
                preview_graph=draft.preview_graph,
                base_graph_hash=draft.base_graph_hash,
                base_workflow_updated_at=draft.base_workflow_updated_at,
                draft_mode=draft.draft_mode,
                node_detail_previews=draft.node_detail_previews,
                validation_result=AgentBuilderValidationResult.model_validate(
                    draft.validation_result
                ),
                safety_notices=[SAFE_SIDE_EFFECT_NOTICE],
            ).model_dump(mode="json")
        return payload

    def _finish_request(
        self,
        request_row: AgentBuilderRequest,
        response: AgentBuilderMessageResponse,
    ) -> bool | None:
        payload = self._stored_response_payload(response)
        structured_request = (
            response.structured_request.model_dump(mode="json")
            if response.structured_request
            else {}
        )
        completed_at = _now()
        if isinstance(self.db, Session):
            updated = (
                self.db.query(AgentBuilderRequest)
                .filter(
                    AgentBuilderRequest.id == request_row.id,
                    AgentBuilderRequest.status == "processing",
                )
                .update(
                    {
                        "status": response.status,
                        "response_payload": payload,
                        "structured_request": structured_request,
                        "completed_at": completed_at,
                    },
                    synchronize_session=False,
                )
            )
            if updated != 1:
                response.status = "canceled"
                response.draft_preview = None
                response.preview_prompt = None
                response.clarification_questions = []
                response.warnings = ["요청이 취소되었습니다."]
                try:
                    (
                        self.db.query(AgentBuilderDraft)
                        .filter(AgentBuilderDraft.request_id == request_row.id)
                        .update({"status": "canceled"}, synchronize_session=False)
                    )
                except Exception:
                    pass
                request_row.response_payload = response.model_dump(mode="json")
                request_row.completed_at = request_row.completed_at or completed_at
                return False
            request_row.status = response.status
            request_row.response_payload = payload
            request_row.structured_request = structured_request
            request_row.completed_at = completed_at
            return True
        try:
            self.db.refresh(request_row)
        except Exception:
            pass
        if request_row.status == "canceled":
            response.status = "canceled"
            response.draft_preview = None
            response.preview_prompt = None
            response.clarification_questions = []
            response.warnings = ["요청이 취소되었습니다."]
            try:
                (
                    self.db.query(AgentBuilderDraft)
                    .filter(AgentBuilderDraft.request_id == request_row.id)
                    .update({"status": "canceled"}, synchronize_session=False)
                )
            except Exception:
                pass
            request_row.response_payload = response.model_dump(mode="json")
            request_row.completed_at = request_row.completed_at or _now()
            return
        request_row.status = response.status
        request_row.response_payload = self._stored_response_payload(response)
        request_row.structured_request = (
            response.structured_request.model_dump(mode="json")
            if response.structured_request
            else {}
        )
        request_row.completed_at = _now()

    def _fail_processing_request(
        self,
        request_row: AgentBuilderRequest,
    ) -> AgentBuilderMessageResponse:
        self.db.rollback()
        response = AgentBuilderMessageResponse(
            request_id=request_row.id,
            status="failed",
            warnings=[
                "Agent Builder 요청 처리 중 실패했습니다. 다시 시도해주세요."
            ],
        )
        if self._finish_request(request_row, response) is not False:
            add_action_audit(
                self.db,
                AuditAction.AGENT_BUILDER_REQUEST_FAILED,
                self.user.id,
                "agent_builder_request",
                request_row.id,
                organization_id=self.organization_id,
                metadata={"request_id": str(request_row.id)},
                status="failure",
            )
        self.db.commit()
        return response

    def _stored_response_payload(
        self,
        response: AgentBuilderMessageResponse,
    ) -> dict[str, Any]:
        payload = response.model_dump(mode="json")
        payload.pop("draft_preview", None)
        return payload

    def _session_or_404(self, session_id: uuid.UUID) -> AgentBuilderSession:
        session = (
            self.db.query(AgentBuilderSession)
            .filter(
                AgentBuilderSession.id == session_id,
                AgentBuilderSession.user_id == self.user.id,
                AgentBuilderSession.organization_id == self.organization_id,
            )
            .first()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Agent Builder session not found")
        return session

    def _request_or_404(self, request_id: uuid.UUID) -> AgentBuilderRequest:
        request_row = (
            self.db.query(AgentBuilderRequest)
            .filter(
                AgentBuilderRequest.id == request_id,
                AgentBuilderRequest.user_id == self.user.id,
                AgentBuilderRequest.organization_id == self.organization_id,
            )
            .first()
        )
        if request_row is None:
            raise HTTPException(status_code=404, detail="Agent Builder request not found")
        return request_row

    def _draft_or_404(self, draft_id: uuid.UUID) -> AgentBuilderDraft:
        draft = (
            self.db.query(AgentBuilderDraft)
            .filter(
                AgentBuilderDraft.id == draft_id,
                AgentBuilderDraft.user_id == self.user.id,
                AgentBuilderDraft.organization_id == self.organization_id,
            )
            .first()
        )
        if draft is None:
            raise HTTPException(status_code=404, detail="Agent Builder draft not found")
        return draft

    def _workflow_in_active_org(self, workflow_id: uuid.UUID) -> Workflow:
        workflow = self.db.query(Workflow).filter(Workflow.id == workflow_id).first()
        if (
            workflow is None
            or workflow.organization_id is None
            or workflow.organization_id != self.organization_id
        ):
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow

    def _lock_session_for_request(
        self,
        session: AgentBuilderSession,
    ) -> AgentBuilderSession:
        if not isinstance(self.db, Session):
            return session
        locked = (
            self.db.query(AgentBuilderSession)
            .filter(
                AgentBuilderSession.id == session.id,
                AgentBuilderSession.user_id == self.user.id,
                AgentBuilderSession.organization_id == self.organization_id,
            )
            .with_for_update()
            .first()
        )
        if locked is None:
            raise HTTPException(status_code=404, detail="Agent Builder session not found")
        return locked

    def _lock_workflow_for_apply(self, workflow_id: uuid.UUID) -> Workflow:
        if not isinstance(self.db, Session):
            return self._workflow_in_active_org(workflow_id)
        workflow = (
            self.db.query(Workflow)
            .filter(Workflow.id == workflow_id)
            .with_for_update()
            .first()
        )
        if (
            workflow is None
            or workflow.organization_id is None
            or workflow.organization_id != self.organization_id
        ):
            raise HTTPException(status_code=404, detail="Workflow not found")
        return workflow

    def _app_in_active_org(self, app_id: uuid.UUID | None) -> App:
        app = self.db.query(App).filter(App.id == app_id).first()
        if app is None or app.organization_id != self.organization_id:
            raise HTTPException(status_code=404, detail="App not found")
        return app

    def _reject_if_pending(self, session: AgentBuilderSession) -> None:
        pending = (
            self.db.query(AgentBuilderRequest)
            .filter(
                AgentBuilderRequest.session_id == session.id,
                AgentBuilderRequest.status == "processing",
                or_(
                    AgentBuilderRequest.expires_at.is_(None),
                    AgentBuilderRequest.expires_at > _now(),
                ),
            )
            .first()
        )
        if pending is not None:
            raise HTTPException(status_code=409, detail="Agent Builder request pending")
