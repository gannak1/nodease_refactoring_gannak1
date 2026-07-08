import copy
import uuid
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from apps.gateway.services import agent_builder_service as service_module
from apps.gateway.services.agent_builder_service import (
    AgentBuilderService,
    calculate_graph_hash,
)
from apps.shared.schemas.agent_builder import (
    AgentBuilderApplyRequest,
    AgentBuilderApplyResponse,
    AgentBuilderMessageResponse,
    AgentBuilderMessageRequest,
)
from apps.shared.schemas.knowledge import (
    KnowledgeRAGRecommendation,
    KnowledgeRAGRecommendationProvenance,
    KnowledgeRAGRecommendationResponse,
    KnowledgeRAGRecommendationSummary,
    KnowledgeRAGRecommendedOptions,
)


class FakeDb:
    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.flushed = False
        self.refreshed = []
        self.query_result = None

    def add(self, row):
        self.added.append(row)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def flush(self):
        self.flushed = True

    def refresh(self, row):
        self.refreshed.append(row)

    def query(self, _model):
        return self.query_result


class FakeQuery:
    def __init__(self, result=None):
        self.result = result

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.result


def _ready_modify_draft(preview_graph, *, workflow_id=None):
    workflow_id = workflow_id or uuid.uuid4()
    return SimpleNamespace(
        id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="modify_workflow",
        base_graph_hash=calculate_graph_hash(preview_graph),
        base_workflow_updated_at=None,
        preview_graph=preview_graph,
        status="ready",
        workflow_id=workflow_id,
        app_id=None,
        draft_metadata={"workflow_id": str(workflow_id)},
        expires_at=None,
    )


def test_agent_builder_graph_hash_ignores_viewport_and_ui_only_state():
    graph_a = {
        "nodes": [
            {
                "id": "start",
                "type": "startNode",
                "position": {"x": 1, "y": 1},
                "data": {"title": "입력", "selected": True},
            }
        ],
        "edges": [],
        "viewport": {"x": 0, "y": 0, "zoom": 1},
    }
    graph_b = {
        "nodes": [
            {
                "id": "start",
                "type": "startNode",
                "position": {"x": 999, "y": 999},
                "data": {"title": "입력", "selected": True},
            }
        ],
        "edges": [],
        "viewport": {"x": 50, "y": 50, "zoom": 2},
    }

    assert calculate_graph_hash(graph_a) == calculate_graph_hash(graph_b)


def test_agent_builder_graph_hash_ignores_ui_only_data_values():
    graph_a = {
        "nodes": [
            {
                "id": "start",
                "type": "startNode",
                "data": {"title": "Input", "selected": True, "status": "active"},
            }
        ],
        "edges": [],
    }
    graph_b = {
        "nodes": [
            {
                "id": "start",
                "type": "startNode",
                "data": {"title": "Input", "selected": False, "status": "idle"},
            }
        ],
        "edges": [],
    }

    assert calculate_graph_hash(graph_a) == calculate_graph_hash(graph_b)


def test_agent_builder_graph_hash_ignores_edge_id():
    graph_a = {
        "nodes": [{"id": "start", "type": "startNode", "data": {}}],
        "edges": [
            {
                "id": "edge-1",
                "source": "start",
                "target": "answer",
                "sourceHandle": "source",
                "targetHandle": "target",
            }
        ],
    }
    graph_b = {
        "nodes": [{"id": "start", "type": "startNode", "data": {}}],
        "edges": [
            {
                "id": "edge-2",
                "source": "start",
                "target": "answer",
                "sourceHandle": "source",
                "targetHandle": "target",
            }
        ],
    }

    assert calculate_graph_hash(graph_a) == calculate_graph_hash(graph_b)


def test_agent_builder_graph_hash_ignores_note_nodes_and_edges():
    graph_a = {
        "nodes": [
            {"id": "start", "type": "startNode", "data": {"title": "Input"}},
        ],
        "edges": [],
    }
    graph_b = {
        "nodes": [
            {"id": "start", "type": "startNode", "data": {"title": "Input"}},
            {"id": "note-1", "type": "note", "data": {"text": "memo"}},
        ],
        "edges": [
            {"id": "note-edge", "source": "note-1", "target": "start"},
        ],
    }

    assert calculate_graph_hash(graph_a) == calculate_graph_hash(graph_b)


def test_agent_builder_graph_hash_changes_for_semantic_data():
    graph_a = {
        "nodes": [{"id": "start", "type": "startNode", "data": {"title": "A"}}],
        "edges": [],
    }
    graph_b = {
        "nodes": [{"id": "start", "type": "startNode", "data": {"title": "B"}}],
        "edges": [],
    }

    assert calculate_graph_hash(graph_a) != calculate_graph_hash(graph_b)


@pytest.mark.parametrize(
    "raw_graph_key",
    [
        "client_graph_snapshot",
        "graph",
        "nodes",
        "edges",
        "preview_graph",
        "previewGraph",
        "workflow_graph",
        "workflowGraph",
        "raw_graph",
        "rawGraph",
        "clientGraphSnapshot",
    ],
)
def test_agent_builder_message_request_rejects_raw_graph_payload(raw_graph_key):
    with pytest.raises(ValidationError):
        AgentBuilderMessageRequest(
            message="create a workflow",
            **{raw_graph_key: {"nodes": [{"data": {"token": "secret"}}]}},
        )


def test_agent_builder_preview_redacts_raw_kb_and_source_identifiers():
    raw_kb_id = str(uuid.uuid4())
    preview = service_module._redact_graph_for_preview(
        {
            "nodes": [
                {
                    "id": "llm",
                    "type": "llmNode",
                    "data": {
                        "knowledgeBases": [{"id": raw_kb_id, "name": "Private KB"}],
                        "url": "https://secret.example.com/source",
                    },
                }
            ],
            "edges": [],
        }
    )

    node_data = preview["nodes"][0]["data"]
    assert raw_kb_id not in str(node_data)
    assert "secret.example.com" not in str(node_data)
    assert node_data["knowledgeBases"][0]["reference_type"] == "existing_redacted_reference"
    assert "url" not in node_data


def test_agent_builder_saved_response_requires_audit_recorded():
    with pytest.raises(ValueError):
        AgentBuilderApplyResponse(
            apply_id=uuid.uuid4(),
            outcome="saved",
            audit_recorded=False,
        )


def test_finish_request_does_not_overwrite_canceled_request():
    request_id = uuid.uuid4()
    request_row = SimpleNamespace(
        id=request_id,
        status="canceled",
        response_payload={},
        completed_at=None,
    )
    response = AgentBuilderMessageResponse(
        request_id=request_id,
        status="draft_ready",
        preview_prompt="도안 생성 미리보기",
        warnings=["ready"],
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    svc._finish_request(request_row, response)  # noqa: SLF001

    assert response.status == "canceled"
    assert response.draft_preview is None
    assert response.preview_prompt is None
    assert request_row.response_payload["status"] == "canceled"
    assert request_row.completed_at is not None


def test_safe_summary_redacts_secret_values_urls_and_paths():
    summary = service_module._safe_summary(  # noqa: SLF001
        "password=hunter2 api_key: sk-test-secret Bearer abcdefghijk "
        "Authorization: Bearer super-secret-bearer Authorization: Basic super-secret-basic "
        "https://secret.example.com/doc C:\\secret\\policy.pdf /srv/private/file.txt "
        "password is hunter2 토큰 값은 korean-secret-token"
    )

    assert "hunter2" not in summary
    assert "sk-test-secret" not in summary
    assert "abcdefghijk" not in summary
    assert "super-secret-bearer" not in summary
    assert "super-secret-basic" not in summary
    assert "korean-secret-token" not in summary
    assert "secret.example.com" not in summary
    assert "C:\\secret" not in summary
    assert "/srv/private" not in summary


def test_agent_builder_record_preview_opened_audits_success(monkeypatch):
    db = FakeDb()
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="new_workflow",
        preview_graph={"nodes": [], "edges": []},
        status="ready",
        expires_at=None,
        validation_result={"valid": True},
    )
    audit_calls = []
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(
        svc,
        "_session_or_404",
        lambda _session_id: SimpleNamespace(workflow_id=None, app_id=uuid.uuid4()),
    )
    monkeypatch.setattr(svc, "_session_scope_allowed", lambda _session: True)
    monkeypatch.setattr(
        service_module,
        "add_action_audit",
        lambda *args, **kwargs: audit_calls.append((args, kwargs)),
    )

    svc.record_preview_opened(draft.id)

    assert audit_calls[0][0][1] == service_module.AuditAction.AGENT_BUILDER_PREVIEW_OPENED
    assert db.commits == 1


def test_agent_builder_record_preview_opened_blocks_invalid_draft(monkeypatch):
    db = FakeDb()
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="new_workflow",
        preview_graph={"nodes": [], "edges": []},
        status="ready",
        expires_at=None,
        validation_result={"valid": False},
    )
    audit_calls = []
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(
        service_module,
        "add_action_audit",
        lambda *args, **kwargs: audit_calls.append((args, kwargs)),
    )

    with pytest.raises(service_module.HTTPException) as exc:
        svc.record_preview_opened(draft.id)

    assert exc.value.detail == "DRAFT_VALIDATION_FAILED"
    assert audit_calls[0][0][1] == service_module.AuditAction.AGENT_BUILDER_PREVIEW_BLOCKED
    assert audit_calls[0][1]["metadata"]["block_reason"] == "DRAFT_VALIDATION_FAILED"
    assert db.commits == 1


def test_create_session_uses_workflow_app_id_over_client_app_id(monkeypatch):
    db = FakeDb()
    db.query_result = FakeQuery(None)
    workflow_id = uuid.uuid4()
    workflow_app_id = uuid.uuid4()
    client_app_id = uuid.uuid4()
    workflow = SimpleNamespace(
        id=workflow_id,
        app_id=workflow_app_id,
        organization_id=uuid.uuid4(),
    )
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=workflow.organization_id,
    )
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "ensure_workflow_permission", lambda *args, **kwargs: None)
    monkeypatch.setattr(svc, "_session_response", lambda _session: SimpleNamespace())

    svc.create_or_restore_session(
        service_module.AgentBuilderSessionCreateRequest(
            workflow_id=workflow_id,
            app_id=client_app_id,
        )
    )

    session = db.added[0]
    assert session.workflow_id == workflow_id
    assert session.app_id == workflow_app_id


def test_structured_request_respects_explicit_new_workflow_intent_with_workflow_scope():
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    workflow = SimpleNamespace(id=uuid.uuid4(), graph={"nodes": [], "edges": []})

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="새 워크플로우로 휴가 정책 답변 로직을 만들어줘"),
        workflow=workflow,
    )

    assert structured.request_type == "new_workflow"
    assert structured.draft_mode == "new_workflow"


def test_structured_request_defaults_to_new_workflow_without_targeted_insert():
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    workflow = SimpleNamespace(id=uuid.uuid4(), graph={"nodes": [], "edges": []})

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="입력값을 분석해서 답변하는 로직을 만들어줘"),
        workflow=workflow,
    )

    assert structured.request_type == "new_workflow"
    assert structured.draft_mode == "new_workflow"


def test_structured_request_modifies_existing_workflow_only_for_targeted_insert():
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    workflow = SimpleNamespace(id=uuid.uuid4(), graph={"nodes": [], "edges": []})

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(
            message="이 연결 사이에 입력값을 분석하는 노드를 넣어줘",
            selected_edge_id="edge-1",
        ),
        workflow=workflow,
    )

    assert structured.request_type == "modify_workflow"
    assert structured.draft_mode == "modify_workflow"


def test_structured_request_rejects_non_workflow_message_with_hints():
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="h"),
        workflow=None,
    )
    validation = svc._validate_structured_request(  # noqa: SLF001
        structured,
        app_id=uuid.uuid4(),
    )

    assert structured.request_type == "unsupported"
    assert structured.planned_steps == []
    assert structured.unsupported_requests
    assert validation.valid is False
    assert validation.issues[0].code == "UNSUPPORTED_REQUEST"


def test_structured_request_rejects_guardrail_node_in_mvp():
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="입력값을 검사하는 Guardrail 노드를 추가해줘"),
        workflow=None,
    )
    validation = svc._validate_structured_request(  # noqa: SLF001
        structured,
        app_id=uuid.uuid4(),
    )

    assert structured.request_type == "unsupported"
    assert structured.planned_steps == []
    assert "unsupported_capability" in structured.risk_flags
    assert validation.valid is False
    assert validation.issues[0].code == "UNSUPPORTED_REQUEST"


def test_input_output_request_builds_without_llm_model_route(monkeypatch):
    monkeypatch.delenv(service_module.APPROVED_DRAFT_MODEL_ENV, raising=False)
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="입력 - 출력 노드를 만들어줘"),
        workflow=None,
    )
    preview_graph = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=None,
        kb_bindings=[],
    )

    assert structured.request_type == "new_workflow"
    assert "llm" not in structured.required_capabilities
    assert [node["type"] for node in preview_graph["nodes"]] == [
        "startNode",
        "answerNode",
    ]
    assert preview_graph["edges"][0]["source"].startswith("agent-input")
    assert preview_graph["edges"][0]["target"].startswith("agent-answer")


def test_webhook_request_builds_webhook_trigger_preview(monkeypatch):
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_default_model_id", lambda: "model-1")

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(
            message="웹훅으로 받는 사내 문서 챗봇 워크플로우를 만들어줘"
        ),
        workflow=None,
    )
    preview_graph = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=None,
        kb_bindings=[],
    )

    nodes_by_type = {node["type"]: node for node in preview_graph["nodes"]}
    assert structured.planned_steps[0].capability == "webhook_trigger"
    assert "webhook_trigger" in structured.required_capabilities
    assert "webhookTrigger" in nodes_by_type
    webhook_node = nodes_by_type["webhookTrigger"]
    assert webhook_node["data"]["variable_mappings"] == [
        {"variable_name": "payload", "json_path": "$"}
    ]
    llm_node = nodes_by_type["llmNode"]
    assert llm_node["data"]["user_prompt"] == "{{payload}}"
    assert llm_node["data"]["referenced_variables"] == [
        {"name": "payload", "value_selector": [webhook_node["id"], "payload"]}
    ]
    assert svc.validate_preview_graph(preview_graph).valid is True


def test_structured_request_keeps_unresolved_slack_channel_as_nonblocking_warning():
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="Analyze the input and send it to Slack"),
        workflow=None,
    )

    assert structured.missing_information == []
    assert "slack_send" in structured.required_capabilities
    assert "slack_channel_unresolved" in structured.risk_flags
    slack_resolution = next(
        item
        for item in structured.pending_resolution
        if item.slot_key == "slack.channel"
    )
    assert slack_resolution.slot_type == "other"
    assert slack_resolution.blocking is False
    assert slack_resolution.target_step_ref == "step_slack"


def test_session_message_payload_rehydrates_ready_draft_preview():
    graph = {"nodes": [], "edges": []}
    request_id = uuid.uuid4()
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=request_id,
        status="ready",
        preview_graph=graph,
        base_graph_hash=calculate_graph_hash(graph),
        base_workflow_updated_at=None,
        draft_mode="new_workflow",
        node_detail_previews=[],
        validation_result={"valid": True, "issues": []},
        expires_at=None,
    )
    request_row = SimpleNamespace(
        id=request_id,
        response_payload={"request_id": str(request_id), "status": "draft_ready"},
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    payload = svc._message_payload_with_latest_preview(request_row, draft)  # noqa: SLF001

    assert payload["draft_preview"]["draft_id"] == str(draft.id)
    assert payload["draft_preview"]["preview_graph"] == graph


def test_agent_builder_validator_rejects_unsupported_node_type():
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    result = svc.validate_preview_graph(
        {
            "nodes": [{"id": "custom", "type": "customNode", "data": {}}],
            "edges": [],
        }
    )

    assert result.valid is False
    assert result.issues[0].code == "UNSUPPORTED_NODE_TYPE"


def test_agent_builder_kb_recommendation_uses_safe_summary_and_high_confidence(monkeypatch):
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    captured = {}

    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            captured["user_id"] = user_id
            captured["organization_id"] = organization_id

        def recommend_for_builder(self, request, **_kwargs):
            captured["workflow_intent"] = request.workflow_intent
            captured["node_purpose"] = request.node_purpose
            return KnowledgeRAGRecommendationResponse(
                recommendations=[
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-1",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-1",
                        candidate_handle="safe-rec-1",
                        safe_label="휴가 정책",
                        confidence="high",
                        score=0.82,
                        threshold_result="high_confidence",
                        safe_reason_code="topic_keyword_match",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=[{"id": kb_id, "name": "휴가 정책"}],
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="topic_keyword_match",
                        ),
                        runtime_availability="available",
                    )
                ],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="1",
                    recommendation_count_bucket="1",
                ),
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=user_id),
        organization_id=organization_id,
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="휴가 정책 문서를 찾아 답변 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(structured)  # noqa: SLF001

    assert result["status"] == "recommended"
    assert result["bindings"][0]["safe_handle"] == "safe-rec-1"
    assert "knowledge_base_id" not in result["bindings"][0]
    assert captured["user_id"] == user_id
    assert captured["organization_id"] == organization_id
    assert "sk-" not in captured["workflow_intent"]


def test_agent_builder_kb_recommendation_close_score_requires_clarification(monkeypatch):
    kb_id_a = uuid.uuid4()
    kb_id_b = uuid.uuid4()

    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            return KnowledgeRAGRecommendationResponse(
                recommendations=[
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-1",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-1",
                        candidate_handle="safe-rec-1",
                        safe_label="휴가 정책",
                        confidence="high",
                        score=0.7,
                        threshold_result="high_confidence",
                        safe_reason_code="topic_keyword_match",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=[{"id": kb_id_a, "name": "휴가 정책"}],
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="topic_keyword_match",
                        ),
                        runtime_availability="available",
                    ),
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-2",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-2",
                        candidate_handle="safe-rec-2",
                        safe_label="인사 정책",
                        confidence="high",
                        score=0.66,
                        threshold_result="high_confidence",
                        safe_reason_code="metadata_match",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=[{"id": kb_id_b, "name": "인사 정책"}],
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="metadata_match",
                        ),
                        runtime_availability="available",
                    ),
                ],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="2",
                    recommendation_count_bucket="2",
                ),
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="휴가 정책 문서를 찾아 답변 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(structured)  # noqa: SLF001

    assert result["status"] == "clarification_required"
    assert result["questions"]
    assert result["options"] == [
        {
            "type": "knowledge_base",
            "candidate_id": "safe-rec-1",
            "label": "휴가 정책",
            "confidence": "high",
            "score": 0.7,
            "reason_category": "topic_keyword_match",
            "threshold_result": "high_confidence",
            "runtime_availability": "available",
            "requirement_id": "kr_1",
            "resolution_id": "res_kb_1",
        },
        {
            "type": "knowledge_base",
            "candidate_id": "safe-rec-2",
            "label": "인사 정책",
            "confidence": "high",
            "score": 0.66,
            "reason_category": "metadata_match",
            "threshold_result": "high_confidence",
            "runtime_availability": "available",
            "requirement_id": "kr_1",
            "resolution_id": "res_kb_1",
        },
        {
            "type": "no_knowledge_base",
            "candidate_id": service_module.NO_KB_CANDIDATE_ID,
            "label": service_module.NO_KB_CANDIDATE_LABEL,
            "safe_label": service_module.NO_KB_CANDIDATE_LABEL,
            "confidence": "user_choice",
            "score": None,
            "reason_category": "user_selected_no_kb",
            "threshold_result": "user_selected",
            "runtime_availability": "not_applicable",
            "requirement_id": "kr_1",
            "resolution_id": "res_kb_1",
        },
    ]


def test_agent_builder_single_close_score_kb_candidate_is_bound(monkeypatch):
    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            return KnowledgeRAGRecommendationResponse(
                recommendations=[
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-1",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-1",
                        candidate_handle="safe-rec-1",
                        safe_label="사내 문서",
                        confidence="medium",
                        score=0.5,
                        threshold_result="close_score",
                        safe_reason_code="intent_matches_safe_metadata",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=[],
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="intent_matches_safe_metadata",
                        ),
                        runtime_availability="available",
                    )
                ],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="1",
                    recommendation_count_bucket="1",
                ),
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="사내 문서를 찾아 답변 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(structured)  # noqa: SLF001

    assert result["status"] == "recommended"
    assert result["bindings"] == [
        {
            "safe_handle": "safe-rec-1",
            "name": "사내 문서",
            "confidence": "medium",
            "score": 0.5,
            "reason_category": "intent_matches_safe_metadata",
            "threshold_result": "close_score",
        }
    ]


def test_agent_builder_selected_kb_candidate_uses_selected_safe_handle(monkeypatch):
    kb_id_a = uuid.uuid4()
    kb_id_b = uuid.uuid4()

    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **kwargs):
            include_materialized_refs = kwargs.get("include_materialized_refs", False)
            materialized_a = [{"id": kb_id_a, "name": "휴가 정책"}] if include_materialized_refs else []
            materialized_b = [{"id": kb_id_b, "name": "인사 정책"}] if include_materialized_refs else []
            return KnowledgeRAGRecommendationResponse(
                recommendations=[
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-1",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-1",
                        candidate_handle="safe-rec-1",
                        safe_label="휴가 정책",
                        confidence="high",
                        score=0.7,
                        threshold_result="high_confidence",
                        safe_reason_code="topic_keyword_match",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=materialized_a,
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="topic_keyword_match",
                        ),
                        runtime_availability="available",
                    ),
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-2",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-2",
                        candidate_handle="safe-rec-2",
                        safe_label="인사 정책",
                        confidence="high",
                        score=0.66,
                        threshold_result="high_confidence",
                        safe_reason_code="metadata_match",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=materialized_b,
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="metadata_match",
                        ),
                        runtime_availability="available",
                    ),
                ],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="2",
                    recommendation_count_bucket="2",
                ),
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="휴가 정책 문서를 찾아 답변 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(  # noqa: SLF001
        structured,
        selected_candidate_handles={"safe-rec-2"},
        include_materialized_refs=True,
    )

    assert result["status"] == "recommended"
    assert result["bindings"] == [
        {
            "safe_handle": "safe-rec-2",
            "name": "인사 정책",
            "confidence": "high",
            "score": 0.66,
            "reason_category": "metadata_match",
            "threshold_result": "high_confidence",
            "knowledge_base_id": str(kb_id_b),
        }
    ]


def test_agent_builder_selected_low_score_kb_candidate_does_not_repeat_clarification(
    monkeypatch,
):
    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            return KnowledgeRAGRecommendationResponse(
                recommendations=[
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-1",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-1",
                        candidate_handle="safe-rec-1",
                        safe_label="Knowledge Base",
                        confidence="low",
                        score=0.33,
                        threshold_result="below_threshold",
                        safe_reason_code="intent_matches_safe_metadata",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=[],
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="intent_matches_safe_metadata",
                        ),
                        runtime_availability="available",
                    )
                ],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="1",
                    recommendation_count_bucket="1",
                ),
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="Knowledge Base로 답변 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(  # noqa: SLF001
        structured,
        selected_candidate_handles={"safe-rec-1"},
    )

    assert result["status"] == "recommended"
    assert result["bindings"] == [
        {
            "safe_handle": "safe-rec-1",
            "name": "Knowledge Base",
            "confidence": "low",
            "score": 0.33,
            "reason_category": "intent_matches_safe_metadata",
            "threshold_result": "below_threshold",
        }
    ]
    assert "사용자가 선택한 Knowledge Base 후보" in result["warnings"][0]


def test_agent_builder_selected_no_kb_option_skips_kb_binding(monkeypatch):
    service_called = False

    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            nonlocal service_called
            service_called = True
            return KnowledgeRAGRecommendationResponse(
                recommendations=[
                    KnowledgeRAGRecommendation(
                        recommendation_id="safe-rec-1",
                        recommendation_mode="auto_collection",
                        candidate_id="safe-rec-1",
                        candidate_handle="safe-rec-1",
                        safe_label="Knowledge Base",
                        confidence="low",
                        score=0.33,
                        threshold_result="below_threshold",
                        safe_reason_code="intent_matches_safe_metadata",
                        recommended_options=KnowledgeRAGRecommendedOptions(),
                        materialized_knowledge_bases=[],
                        provenance=KnowledgeRAGRecommendationProvenance(
                            safe_reason_code="intent_matches_safe_metadata",
                        ),
                        runtime_availability="available",
                    )
                ],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="1",
                    recommendation_count_bucket="1",
                ),
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="Use a Knowledge policy document in this workflow",
        knowledge_requirements=[
            service_module.AgentBuilderKnowledgeRequirement(
                requirement_id="kr_1",
                query_topics=["policy"],
                target_step_ref="step_llm",
            )
        ],
        pending_resolution=[
            service_module.AgentBuilderPendingResolution(
                resolution_id="res_kb_1",
                slot_type="knowledge_base",
                slot_key="llm.knowledgeBases",
                target_step_ref="step_llm",
            )
        ],
    )

    result = svc._resolve_knowledge_requirements(  # noqa: SLF001
        structured,
        selected_candidate_handles={service_module.NO_KB_CANDIDATE_ID},
    )

    assert result["status"] == "recommended"
    assert result["bindings"] == []
    assert "Knowledge Base 없이" in result["warnings"][0]
    assert service_called is False


def test_agent_builder_kb_recommendation_adapter_unavailable_with_options_requires_clarification(monkeypatch):
    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            return KnowledgeRAGRecommendationResponse(
                status="clarification_required",
                recommendations=[],
                clarification_options=[
                    {
                        "candidate_id": "safe-rec-1",
                        "safe_label": "휴가 정책",
                        "reason_category": "adapter_unavailable",
                    }
                ],
                fallback_reason="adapter_unavailable",
                user_safe_warning="Knowledge Base 추천을 사용할 수 없어 사용자 확인이 필요합니다.",
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="휴가 정책 문서를 찾아 답변 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(structured)  # noqa: SLF001

    assert result["status"] == "clarification_required"
    assert result["options"][0]["candidate_id"] == "safe-rec-1"
    assert result["options"][0]["requirement_id"] == "kr_1"
    assert result["options"][0]["resolution_id"] == "res_kb_1"


def test_agent_builder_selected_kb_candidate_from_unavailable_fallback_is_used(monkeypatch):
    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            return KnowledgeRAGRecommendationResponse(
                status="unavailable",
                recommendations=[],
                clarification_options=[
                    {
                        "candidate_id": "safe-rec-1",
                        "safe_label": "HR Policy",
                        "confidence": "low",
                        "score": 0.0,
                        "reason_category": "adapter_unavailable",
                        "threshold_result": "adapter_unavailable",
                    }
                ],
                fallback_reason="adapter_unavailable",
                user_safe_warning="Knowledge Base recommendation is unavailable.",
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="Use a Knowledge policy document in this workflow",
        knowledge_requirements=[
            service_module.AgentBuilderKnowledgeRequirement(
                requirement_id="kr_1",
                query_topics=["policy"],
                target_step_ref="step_llm",
            )
        ],
        pending_resolution=[
            service_module.AgentBuilderPendingResolution(
                resolution_id="res_kb_1",
                slot_type="knowledge_base",
                slot_key="llm.knowledgeBases",
                target_step_ref="step_llm",
            )
        ],
    )

    result = svc._resolve_knowledge_requirements(  # noqa: SLF001
        structured,
        selected_candidate_handles={"safe-rec-1"},
    )

    assert result["status"] == "recommended"
    assert result["bindings"] == [
        {
            "safe_handle": "safe-rec-1",
            "name": "HR Policy",
            "confidence": "low",
            "score": 0.0,
            "reason_category": "adapter_unavailable",
            "threshold_result": "adapter_unavailable",
        }
    ]


def test_agent_builder_kb_recommendation_unavailable_blocks_required_kb(monkeypatch):
    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            return KnowledgeRAGRecommendationResponse(
                status="unavailable",
                recommendations=[],
                fallback_reason="adapter_unavailable",
                user_safe_warning="Knowledge Base 추천을 사용할 수 없습니다.",
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="휴가 정책 문서를 찾아 답변 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(structured)  # noqa: SLF001

    assert result["status"] == "validation_failed"
    assert "Knowledge Base" in result["warnings"][0]


def test_agent_builder_kb_recommendation_no_candidate_warns_and_continues(monkeypatch):
    monkeypatch.setenv(service_module.APPROVED_DRAFT_MODEL_ENV, "approved-draft-route")

    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def recommend_for_builder(self, request, **_kwargs):
            return KnowledgeRAGRecommendationResponse(
                recommendations=[],
                summary=KnowledgeRAGRecommendationSummary(
                    candidate_count_bucket="0",
                    recommendation_count_bucket="0",
                ),
            )

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )
    svc = AgentBuilderService(
        object(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    structured = svc._build_structured_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="휴가 정책 문서를 찾아 Slack으로 보내는 workflow를 만들어줘"),
        workflow=None,
    )

    result = svc._resolve_knowledge_requirements(structured)  # noqa: SLF001
    preview_graph = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=None,
        kb_bindings=result["bindings"],
    )

    nodes_by_type = {node["type"]: node for node in preview_graph["nodes"]}
    assert result["status"] == "recommended"
    assert result["bindings"] == []
    assert "Knowledge Base 없이" in result["warnings"][0]
    assert nodes_by_type["llmNode"]["data"]["knowledgeBases"] == []
    assert nodes_by_type["slackPostNode"]["data"]["channel_resolution_state"] == "unresolved"


def test_agent_builder_session_messages_restore_redacted_user_turn_and_assistant_turn():
    request_id = uuid.uuid4()
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    request_row = SimpleNamespace(
        id=request_id,
        message_summary="휴가 정책을 찾아서 요약해줘",
        response_payload={
            "request_id": str(request_id),
            "status": "clarification_required",
            "clarification_questions": ["사용할 Knowledge Base를 선택해주세요."],
            "clarification_options": [],
            "warnings": [],
        },
    )

    messages = svc._session_messages(request_row, None)  # noqa: SLF001

    assert messages[0] == {
        "kind": "user",
        "request_id": str(request_id),
        "content": "휴가 정책을 찾아서 요약해줘",
        "redacted": True,
    }
    assert messages[1]["kind"] == "assistant"
    assert messages[1]["response"]["status"] == "clarification_required"


def test_agent_builder_selected_kb_candidate_validates_prior_clarification_context():
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="휴가 정책",
        knowledge_requirements=[
            service_module.AgentBuilderKnowledgeRequirement(
                requirement_id="kr_1",
                query_topics=["휴가 정책"],
                target_step_ref="step_llm",
            )
        ],
        pending_resolution=[
            service_module.AgentBuilderPendingResolution(
                resolution_id="res_kb_1",
                slot_type="knowledge_base",
                slot_key="llm.knowledgeBases",
                target_step_ref="step_llm",
            )
        ],
    )
    previous_request = SimpleNamespace(
        response_payload={
            "clarification_options": [
                {
                    "candidate_id": "safe-rec-1",
                    "resolution_id": "res_kb_1",
                    "requirement_id": "kr_1",
                }
            ],
            "structured_request": structured.model_dump(mode="json"),
        },
        structured_request=structured.model_dump(mode="json"),
    )
    db = FakeDb()
    db.query_result = FakeQuery(previous_request)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    session = SimpleNamespace(id=uuid.uuid4())

    context = svc._selected_knowledge_candidate_context(  # noqa: SLF001
        session,
        AgentBuilderMessageRequest(
            message="선택한 Knowledge Base로 도안을 생성해줘",
            selected_knowledge_candidate={
                "candidate_id": "safe-rec-1",
                "resolution_id": "res_kb_1",
                "requirement_id": "kr_1",
            },
        ),
    )

    assert context["candidate_handles"] == {"safe-rec-1"}
    assert context["structured_request"].knowledge_requirements[0].requirement_id == "kr_1"


def test_agent_builder_selected_kb_candidate_rejects_mismatched_context():
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="휴가 정책",
        knowledge_requirements=[],
        pending_resolution=[],
    )
    previous_request = SimpleNamespace(
        response_payload={
            "clarification_options": [
                {
                    "candidate_id": "safe-rec-1",
                    "resolution_id": "res_kb_1",
                    "requirement_id": "kr_1",
                }
            ],
            "structured_request": structured.model_dump(mode="json"),
        },
        structured_request=structured.model_dump(mode="json"),
    )
    db = FakeDb()
    db.query_result = FakeQuery(previous_request)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    context = svc._selected_knowledge_candidate_context(  # noqa: SLF001
        SimpleNamespace(id=uuid.uuid4()),
        AgentBuilderMessageRequest(
            message="선택한 Knowledge Base로 도안을 생성해줘",
            selected_knowledge_candidate={
                "candidate_id": "safe-rec-1",
                "resolution_id": "other-resolution",
                "requirement_id": "kr_1",
            },
        ),
    )

    assert context == {"error": "candidate_not_in_prior_options"}


def test_agent_builder_apply_blocks_missing_client_preview_hash(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.added = []
            self.committed = False

        def add(self, row):
            self.added.append(row)

        def commit(self):
            self.committed = True

    db = FakeDb()
    draft_id = uuid.uuid4()
    draft = SimpleNamespace(
        id=draft_id,
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="modify_workflow",
        base_graph_hash="base",
        preview_graph={"nodes": [], "edges": []},
        status="ready",
        workflow_id=uuid.uuid4(),
        expires_at=None,
    )
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    lock_calls = []
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(
        svc,
        "_lock_draft_for_apply",
        lambda locked_draft: lock_calls.append(locked_draft.id) or locked_draft,
    )

    response = svc.apply_draft(
        draft_id,
        AgentBuilderApplyRequest(action="apply_and_save"),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "DRAFT_STALE"
    assert response.stale_state == "preview_hash_missing"
    assert response.audit_recorded is True
    assert db.committed is True
    assert draft.status == "ready"
    assert lock_calls == [draft_id, draft_id]


def test_agent_builder_apply_blocks_preview_hash_mismatch(monkeypatch):
    db = FakeDb()
    graph = {"nodes": [], "edges": []}
    draft = _ready_modify_draft(graph)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash="wrong-preview-hash",
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "DRAFT_STALE"
    assert response.stale_state == "preview_hash_mismatch"
    assert draft.status == "ready"


def test_agent_builder_apply_blocks_canceled_draft_without_overwriting_status(monkeypatch):
    class FakeDb:
        def __init__(self):
            self.commits = 0

        def add(self, row):
            pass

        def commit(self):
            self.commits += 1

    preview_graph = {"nodes": [], "edges": []}
    draft_id = uuid.uuid4()
    draft = SimpleNamespace(
        id=draft_id,
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="modify_workflow",
        base_graph_hash="base",
        preview_graph=preview_graph,
        status="canceled",
        workflow_id=uuid.uuid4(),
        app_id=None,
        draft_metadata={"workflow_id": str(uuid.uuid4())},
        expires_at=None,
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)

    response = svc.apply_draft(
        draft_id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(preview_graph),
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "DRAFT_NOT_APPLICABLE"
    assert draft.status == "canceled"


def test_agent_builder_cancel_does_not_overwrite_applied_draft(monkeypatch):
    preview_graph = {"nodes": [], "edges": []}
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="modify_workflow",
        base_graph_hash=calculate_graph_hash(preview_graph),
        preview_graph=preview_graph,
        status="applied",
        workflow_id=uuid.uuid4(),
        app_id=None,
        draft_metadata={"workflow_id": str(uuid.uuid4())},
        expires_at=None,
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(action="cancel"),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "DRAFT_NOT_APPLICABLE"
    assert draft.status == "applied"


def test_agent_builder_cancel_records_audit_without_terminally_canceling_ready_draft(monkeypatch):
    preview_graph = {"nodes": [], "edges": []}
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="modify_workflow",
        base_graph_hash=calculate_graph_hash(preview_graph),
        preview_graph=preview_graph,
        status="ready",
        workflow_id=uuid.uuid4(),
        app_id=None,
        draft_metadata={"workflow_id": str(uuid.uuid4())},
        expires_at=None,
    )
    db = FakeDb()
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(action="cancel"),
    )

    assert response.outcome == "canceled"
    assert response.audit_recorded is True
    assert draft.status == "ready"
    assert db.commits == 2


def test_agent_builder_apply_requires_workflow_write_permission(monkeypatch):
    db = FakeDb()
    workflow_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=graph,
        updated_at=None,
        app_id=uuid.uuid4(),
    )
    draft = _ready_modify_draft(graph, workflow_id=workflow_id)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: False)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "WORKFLOW_PERMISSION_REQUIRED"
    assert response.permission_recheck_outcome == "denied"
    assert response.audit_recorded is True
    assert draft.status == "ready"


def test_agent_builder_apply_blocks_missing_latest_graph_hash(monkeypatch):
    db = FakeDb()
    workflow_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=graph,
        updated_at=None,
        app_id=uuid.uuid4(),
    )
    draft = _ready_modify_draft(graph, workflow_id=workflow_id)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: True)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "UNSAVED_EDITOR_CHANGES"
    assert response.stale_state == "client_graph_hash_missing"


def test_agent_builder_apply_blocks_latest_graph_hash_mismatch(monkeypatch):
    db = FakeDb()
    workflow_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=graph,
        updated_at=None,
        app_id=uuid.uuid4(),
    )
    draft = _ready_modify_draft(graph, workflow_id=workflow_id)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: True)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
            client_latest_graph_hash="wrong-latest-hash",
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "UNSAVED_EDITOR_CHANGES"
    assert response.stale_state == "client_graph_mismatch"


def test_agent_builder_apply_blocks_stale_base_graph_hash(monkeypatch):
    db = FakeDb()
    workflow_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    changed_graph = {"nodes": [{"id": "n1", "type": "startNode", "data": {}}], "edges": []}
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=changed_graph,
        updated_at=None,
        app_id=uuid.uuid4(),
    )
    draft = _ready_modify_draft(graph, workflow_id=workflow_id)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: True)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
            client_latest_graph_hash=calculate_graph_hash(changed_graph),
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "DRAFT_STALE"
    assert response.stale_state == "stale"


def test_agent_builder_apply_blocks_stale_workflow_updated_at(monkeypatch):
    db = FakeDb()
    workflow_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    base_updated_at = service_module.datetime(2026, 1, 1, tzinfo=service_module.timezone.utc)
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=graph,
        updated_at=service_module.datetime(2026, 1, 2, tzinfo=service_module.timezone.utc),
        app_id=uuid.uuid4(),
    )
    draft = _ready_modify_draft(graph, workflow_id=workflow_id)
    draft.base_workflow_updated_at = base_updated_at
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: True)

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
            client_latest_graph_hash=calculate_graph_hash(graph),
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "DRAFT_STALE"
    assert response.stale_state == "stale"


def test_agent_builder_apply_commit_success_refresh_failure_still_returns_saved(monkeypatch):
    class RefreshFailingDb(FakeDb):
        def refresh(self, row):
            raise RuntimeError("refresh failed")

    db = RefreshFailingDb()
    workflow_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=graph,
        updated_at=None,
        app_id=uuid.uuid4(),
        updated_by=None,
    )
    draft = _ready_modify_draft(graph, workflow_id=workflow_id)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(svc, "_runtime_kb_bindings_for_apply", lambda _draft: [])

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
            client_latest_graph_hash=calculate_graph_hash(graph),
        ),
    )

    assert response.outcome == "saved"
    assert response.saved_workflow_id == workflow_id
    assert response.audit_recorded is True
    assert response.layout_optimization_applied is True
    assert db.rollbacks == 0


def test_agent_builder_apply_requires_app_create_scope(monkeypatch):
    db = FakeDb()
    app_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="new_workflow",
        base_graph_hash=calculate_graph_hash(graph),
        base_workflow_updated_at=None,
        preview_graph=graph,
        status="ready",
        workflow_id=None,
        app_id=app_id,
        draft_metadata={},
        expires_at=None,
    )
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_app_in_active_org", lambda _app_id: SimpleNamespace(id=app_id))
    monkeypatch.setattr(
        service_module.AppService,
        "access_denial_status",
        lambda *args, **kwargs: 403,
    )

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "APP_CREATE_PERMISSION_REQUIRED"
    assert response.permission_recheck_outcome == "denied"
    assert response.audit_recorded is True
    assert draft.status == "ready"


def test_agent_builder_preview_splices_generated_chain_into_selected_edge(monkeypatch):
    workflow = SimpleNamespace(
        graph={
            "nodes": [
                {"id": "start", "type": "startNode", "data": {}},
                {"id": "answer", "type": "answerNode", "data": {}},
            ],
            "edges": [{"id": "edge-start-answer", "source": "start", "target": "answer"}],
        }
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_default_model_id", lambda: "model-1")
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="modify_workflow",
        draft_mode="modify_workflow",
        intent_summary="insert",
    )

    preview = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=workflow,
        kb_bindings=[],
        selected_edge_id="edge-start-answer",
    )

    edge_ids = {edge.get("id") for edge in preview["edges"]}
    assert "edge-start-answer" not in edge_ids
    assert any(edge.get("source") == "start" for edge in preview["edges"])
    assert any(edge.get("target") == "answer" for edge in preview["edges"])


def test_agent_builder_preview_auto_layouts_new_workflow_chain(monkeypatch):
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_default_model_id", lambda: "model-1")
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="create",
        required_capabilities=["start_input", "llm", "answer"],
    )

    preview = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=None,
        kb_bindings=[],
    )

    nodes_by_type = {node["type"]: node for node in preview["nodes"]}
    start_position = nodes_by_type["startNode"]["position"]
    llm_position = nodes_by_type["llmNode"]["position"]
    answer_position = nodes_by_type["answerNode"]["position"]

    assert start_position["x"] < llm_position["x"] < answer_position["x"]
    assert start_position["y"] == llm_position["y"] == answer_position["y"]


def test_agent_builder_preview_generates_valid_slack_node_when_requested(monkeypatch):
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_default_model_id", lambda: "model-1")
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="send to Slack",
        required_capabilities=["start_input", "llm", "slack_send", "answer"],
    )

    preview = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=None,
        kb_bindings=[],
    )

    nodes_by_type = {node["type"]: node for node in preview["nodes"]}
    assert "slackPostNode" in nodes_by_type
    slack_node = nodes_by_type["slackPostNode"]
    assert slack_node["data"]["channel"] == ""
    assert slack_node["data"]["authConfig"] == {}
    assert any(
        edge.get("source") == nodes_by_type["llmNode"]["id"]
        and edge.get("target") == slack_node["id"]
        for edge in preview["edges"]
    )
    assert svc.validate_preview_graph(preview).valid is True


def test_agent_builder_preview_auto_layout_avoids_existing_node_overlap(monkeypatch):
    workflow = SimpleNamespace(
        graph={
            "nodes": [
                {
                    "id": "selected",
                    "type": "startNode",
                    "position": {"x": 0, "y": 0},
                    "data": {},
                },
                {
                    "id": "occupied",
                    "type": "answerNode",
                    "position": {"x": 360, "y": 0},
                    "data": {},
                },
            ],
            "edges": [],
        }
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_default_model_id", lambda: "model-1")
    structured = service_module.AgentBuilderStructuredRequest(
        request_type="modify_workflow",
        draft_mode="modify_workflow",
        intent_summary="append",
        required_capabilities=["start_input", "llm", "answer"],
    )

    preview = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=workflow,
        kb_bindings=[],
        selected_node_id="selected",
    )

    generated_nodes = [
        node for node in preview["nodes"] if str(node["id"]).startswith("agent-")
    ]
    generated_positions = [node["position"] for node in generated_nodes]

    assert {position["y"] for position in generated_positions} == {220}
    assert sorted(position["x"] for position in generated_positions) == [
        360,
        720,
        1080,
    ]


def test_agent_builder_selected_edge_requires_edge_context_in_message():
    workflow = SimpleNamespace(
        graph={
            "nodes": [],
            "edges": [{"id": "edge-start-answer", "source": "start", "target": "answer"}],
        }
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    assert (
        svc._selected_edge_id_for_message(  # noqa: SLF001
            workflow,
            "edge-start-answer",
            "이 노드 뒤에 LLM을 추가해줘",
        )
        is None
    )
    assert (
        svc._selected_edge_id_for_message(  # noqa: SLF001
            workflow,
            "edge-start-answer",
            "이 연결 사이에 LLM을 추가해줘",
        )
        == "edge-start-answer"
    )


def test_agent_builder_save_graph_removes_selected_edge_when_spliced():
    base_graph = {
        "nodes": [
            {"id": "start", "type": "startNode", "data": {}},
            {"id": "answer", "type": "answerNode", "data": {}},
        ],
        "edges": [{"id": "edge-start-answer", "source": "start", "target": "answer"}],
    }
    preview_graph = {
        "nodes": [
            *base_graph["nodes"],
            {"id": "agent-input", "type": "startNode", "data": {}},
            {"id": "agent-llm", "type": "llmNode", "data": {"model_id": "model-1"}},
            {"id": "agent-answer", "type": "answerNode", "data": {}},
        ],
        "edges": [
            {"id": "edge-start-agent-input", "source": "start", "target": "agent-input"},
            {"id": "edge-agent-input-agent-llm", "source": "agent-input", "target": "agent-llm"},
            {"id": "edge-agent-llm-agent-answer", "source": "agent-llm", "target": "agent-answer"},
            {"id": "edge-agent-answer-answer", "source": "agent-answer", "target": "answer"},
        ],
    }
    draft = SimpleNamespace(
        preview_graph=preview_graph,
        draft_mode="modify_workflow",
        draft_metadata={
            "generated_node_ids": ["agent-input", "agent-llm", "agent-answer"],
            "generated_edge_ids": [
                "edge-start-agent-input",
                "edge-agent-input-agent-llm",
                "edge-agent-llm-agent-answer",
                "edge-agent-answer-answer",
            ],
            "target_resolution": {"selected_edge_id": "edge-start-answer"},
        },
    )
    workflow = SimpleNamespace(graph=base_graph)
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    save_graph = svc._graph_for_apply(  # noqa: SLF001
        draft,
        workflow,
        runtime_kb_bindings=[],
    )

    edge_ids = {edge["id"] for edge in save_graph["edges"]}
    assert "edge-start-answer" not in edge_ids
    assert "edge-start-agent-input" in edge_ids
    assert "edge-agent-answer-answer" in edge_ids


def test_agent_builder_graph_for_apply_optimizes_layout_before_save():
    preview_graph = {
        "nodes": [
            {"id": "agent-input", "type": "startNode", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "agent-llm", "type": "llmNode", "position": {"x": 0, "y": 0}, "data": {}},
            {"id": "agent-answer", "type": "answerNode", "position": {"x": 0, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "edge-agent-input-agent-llm", "source": "agent-input", "target": "agent-llm"},
            {"id": "edge-agent-llm-agent-answer", "source": "agent-llm", "target": "agent-answer"},
        ],
    }
    draft = SimpleNamespace(
        preview_graph=preview_graph,
        draft_mode="new_workflow",
        draft_metadata={
            "generated_node_ids": ["agent-input", "agent-llm", "agent-answer"]
        },
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    save_graph = svc._graph_for_apply(  # noqa: SLF001
        draft,
        None,
        runtime_kb_bindings=[],
    )

    positions = {node["id"]: node["position"] for node in save_graph["nodes"]}
    assert positions["agent-input"]["x"] < positions["agent-llm"]["x"]
    assert positions["agent-llm"]["x"] < positions["agent-answer"]["x"]
    assert {
        positions["agent-input"]["y"],
        positions["agent-llm"]["y"],
        positions["agent-answer"]["y"],
    } == {0}


def test_agent_builder_apply_persists_optimized_layout(monkeypatch):
    db = FakeDb()
    workflow_id = uuid.uuid4()
    base_graph = {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 1}}
    preview_graph = {
        "nodes": [
            {"id": "agent-input", "type": "startNode", "position": {"x": 0, "y": 0}, "data": {}},
            {
                "id": "agent-llm",
                "type": "llmNode",
                "position": {"x": 0, "y": 0},
                "data": {"model_id": "model-1"},
            },
            {"id": "agent-answer", "type": "answerNode", "position": {"x": 0, "y": 0}, "data": {}},
        ],
        "edges": [
            {"id": "edge-agent-input-agent-llm", "source": "agent-input", "target": "agent-llm"},
            {"id": "edge-agent-llm-agent-answer", "source": "agent-llm", "target": "agent-answer"},
        ],
    }
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=copy.deepcopy(base_graph),
        updated_at=None,
        app_id=uuid.uuid4(),
        updated_by=None,
    )
    draft = SimpleNamespace(
        id=uuid.uuid4(),
        request_id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        draft_mode="modify_workflow",
        base_graph_hash=calculate_graph_hash(base_graph),
        base_workflow_updated_at=None,
        preview_graph=preview_graph,
        status="ready",
        workflow_id=workflow_id,
        app_id=None,
        draft_metadata={
            "workflow_id": str(workflow_id),
            "generated_node_ids": ["agent-input", "agent-llm", "agent-answer"],
            "generated_edge_ids": [
                "edge-agent-input-agent-llm",
                "edge-agent-llm-agent-answer",
            ],
        },
        expires_at=None,
    )
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(svc, "_runtime_kb_bindings_for_apply", lambda _draft: [])

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(preview_graph),
            client_latest_graph_hash=calculate_graph_hash(base_graph),
        ),
    )

    assert response.outcome == "saved"
    assert response.layout_optimization_applied is True
    positions = {node["id"]: node["position"] for node in workflow.graph["nodes"]}
    assert positions["agent-input"]["x"] < positions["agent-llm"]["x"]
    assert positions["agent-llm"]["x"] < positions["agent-answer"]["x"]
    assert {position["y"] for position in positions.values()} == {0}


def test_agent_builder_model_route_requires_explicit_approved_env(monkeypatch):
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.delenv(service_module.APPROVED_DRAFT_MODEL_ENV, raising=False)

    with pytest.raises(service_module.HTTPException) as exc:
        svc._default_model_id()  # noqa: SLF001

    assert exc.value.detail == "DRAFT_MODEL_ROUTE_REQUIRED"


def test_agent_builder_model_route_uses_explicit_approved_env(monkeypatch):
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setenv(service_module.APPROVED_DRAFT_MODEL_ENV, "approved-draft-route")

    assert svc._default_model_id() == "approved-draft-route"  # noqa: SLF001


def test_agent_builder_apply_save_failure_returns_safe_failure(monkeypatch):
    class SaveFailingDb(FakeDb):
        def commit(self):
            self.commits += 1
            if self.commits == 2:
                raise RuntimeError("commit failed")

    db = SaveFailingDb()
    workflow_id = uuid.uuid4()
    graph = {"nodes": [], "edges": []}
    workflow = SimpleNamespace(
        id=workflow_id,
        graph=graph,
        updated_at=None,
        app_id=uuid.uuid4(),
        updated_by=None,
    )
    draft = _ready_modify_draft(graph, workflow_id=workflow_id)
    svc = AgentBuilderService(
        db,
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_draft_or_404", lambda _draft_id: draft)
    monkeypatch.setattr(svc, "_workflow_in_active_org", lambda _workflow_id: workflow)
    monkeypatch.setattr(service_module, "has_workflow_permission", lambda *args, **kwargs: True)
    monkeypatch.setattr(svc, "_runtime_kb_bindings_for_apply", lambda _draft: [])

    response = svc.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(graph),
            client_latest_graph_hash=calculate_graph_hash(graph),
        ),
    )

    assert response.outcome == "failed"
    assert response.failure_reason == "SAVE_FAILED"
    assert response.audit_recorded is True
    assert db.rollbacks == 1
    assert db.commits == 3


def test_agent_builder_apply_materializes_kb_at_apply_time(monkeypatch):
    draft = SimpleNamespace(
        preview_graph={
            "nodes": [
                {
                    "data": {
                        "knowledgeBases": [
                            {
                                "id": "safe-rec-1",
                                "reference_type": "safe_candidate_handle",
                            }
                        ]
                    }
                }
            ]
        },
        draft_metadata={
            "structured_request": service_module.AgentBuilderStructuredRequest(
                request_type="modify_workflow",
                draft_mode="modify_workflow",
                intent_summary="휴가 정책",
                knowledge_requirements=[
                    service_module.AgentBuilderKnowledgeRequirement(
                        requirement_id="kr_1",
                        query_topics=["휴가 정책"],
                        target_step_ref="step_llm",
                    )
                ],
                pending_resolution=[
                    service_module.AgentBuilderPendingResolution(
                        resolution_id="res_kb_1",
                        slot_type="knowledge_base",
                        slot_key="llm.knowledgeBases",
                        target_step_ref="step_llm",
                    )
                ],
            ).model_dump(mode="json")
        },
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    class FakeRecommendationService:
        def __init__(self, db, *, user_id, organization_id):
            pass

        def materialize_candidate_handles_for_builder(self, request, candidate_handles):
            assert candidate_handles == {"safe-rec-1"}
            return [
                {
                    "safe_handle": "safe-rec-1",
                    "knowledge_base_id": str(uuid.uuid4()),
                    "name": "휴가 규정",
                }
            ]

    monkeypatch.setattr(
        service_module,
        "KnowledgeRAGRecommendationService",
        FakeRecommendationService,
    )

    bindings = svc._runtime_kb_bindings_for_apply(draft)  # noqa: SLF001

    assert isinstance(bindings, list)
    assert bindings[0]["safe_handle"] == "safe-rec-1"
    assert "knowledge_base_id" in bindings[0]


def test_agent_builder_session_restore_hides_cached_payload_when_scope_denied(monkeypatch):
    session = SimpleNamespace(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        app_id=None,
        status="active",
    )
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )
    monkeypatch.setattr(svc, "_session_or_404", lambda _session_id: session)
    monkeypatch.setattr(svc, "_session_scope_allowed", lambda _session: False)

    response = svc.get_session(session.id)

    assert response.messages == []
    assert response.pending_request is None
    assert response.draft_preview is None
