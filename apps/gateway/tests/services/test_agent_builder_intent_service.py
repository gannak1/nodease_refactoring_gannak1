import json
import uuid
from types import SimpleNamespace

import pytest

from apps.gateway.services.agent_builder_intent_service import (
    AgentBuilderIntentExtraction,
    AgentBuilderIntentExtractionError,
    AgentBuilderIntentRuntimeUnavailableError,
    AgentBuilderSemanticEdit,
    LLMAgentBuilderIntentExtractor,
    agent_builder_capability_guide,
)
from apps.gateway.services.agent_builder_service import AgentBuilderService
from apps.gateway.services.llm_service import LLMCredentialNotAvailableError
from apps.shared.schemas.agent_builder import AgentBuilderMessageRequest
from apps.shared.services.workflow_node_catalog import agent_builder_supported_capabilities


class FakeDb:
    pass


class FakeLLMClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke_sync(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return {"choices": [{"message": {"content": content}}]}


class SequenceFakeLLMClient:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def invoke_sync(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        payload = self.payloads.pop(0)
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}


class FakeIntentExtractor:
    def __init__(self, extraction):
        self.extraction = extraction
        self.calls = []

    def extract(self, *, safe_message, workflow_context):
        self.calls.append(
            {
                "safe_message": safe_message,
                "workflow_context": workflow_context,
            }
        )
        return self.extraction


class FailingIntentExtractor:
    def extract(self, *, safe_message, workflow_context):
        raise AgentBuilderIntentExtractionError("intent extraction failed")


def _service(extractor):
    return AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
        intent_extractor=extractor,
    )


def test_llm_intent_extractor_requests_json_and_preserves_step_order():
    client = FakeLLMClient(
        {
            "request_type": "new_workflow",
            "draft_mode": "new_workflow",
            "intent_summary": "웹훅으로 GitHub PR을 받아 검토한 후 댓글을 등록합니다.",
            "ordered_capabilities": [
                "webhook_trigger",
                "github_pr_read",
                "llm",
                "github_pr_comment",
                "answer",
            ],
            "knowledge_required": False,
            "knowledge_topics": [],
            "integration_actions": [
                {
                    "provider": "github",
                    "resource": "pull_request",
                    "operation": "read",
                },
                {
                    "provider": "github",
                    "resource": "pull_request",
                    "operation": "comment",
                },
            ],
            "edit": None,
            "unsupported_requests": [],
        }
    )
    credential_id = uuid.uuid4()
    model_id = uuid.uuid4()
    runtime_calls = []
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        credential_id=credential_id,
        model_id=model_id,
        runtime_loader=lambda **kwargs: runtime_calls.append(kwargs)
        or SimpleNamespace(client=client),
    )

    result = extractor.extract(
        safe_message=(
            "새 워크플로우로 웹훅에서 요청을 받고 GitHub PR을 조회한 뒤 "
            "LLM으로 리뷰해서 GitHub PR에 댓글을 등록해줘"
        ),
        workflow_context={"workflow_present": False, "nodes": []},
    )

    assert result.ordered_capabilities == [
        "webhook_trigger",
        "github_pr_read",
        "llm",
        "github_pr_comment",
        "answer",
    ]
    messages, kwargs = client.calls[0]
    assert "json" in str(messages).lower()
    assert kwargs["response_format"]["type"] == "json_object"
    assert kwargs["temperature"] == 0
    assert runtime_calls[0]["credential_id"] == credential_id
    assert runtime_calls[0]["model_id"] == model_id


def test_service_rejects_github_pr_create_instead_of_silently_using_http():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="modify_workflow",
            draft_mode="modify_workflow",
            intent_summary="LLM 뒤에 GitHub Pull Request를 생성합니다.",
            ordered_capabilities=["http_request"],
            integration_actions=[
                {
                    "provider": "github",
                    "resource": "pull_request",
                    "operation": "create",
                }
            ],
            edit=AgentBuilderSemanticEdit(
                placement="after",
                target_reference_type="natural_language_node",
                target_query="LLM",
                target_capabilities=["llm"],
            ),
        )
    )
    svc = _service(extractor)

    structured = svc._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(
            message="LLM 뒤에 깃허브로 PR을 올리는 로직을 추가해줘"
        ),
        workflow=SimpleNamespace(
            id=uuid.uuid4(),
            graph={
                "nodes": [
                    {"id": "llm", "type": "llmNode", "data": {"title": "LLM"}},
                    {
                        "id": "answer",
                        "type": "answerNode",
                        "data": {"title": "응답"},
                    },
                ],
                "edges": [
                    {"id": "edge-llm-answer", "source": "llm", "target": "answer"}
                ],
            },
        ),
    )

    assert structured.request_type == "unsupported"
    assert "http_request" not in structured.required_capabilities
    assert structured.unsupported_requests == [
        "GitHub Pull Request 생성은 현재 지원되지 않습니다."
    ]


def test_llm_intent_extractor_repairs_github_comment_mapped_to_http_once():
    base = {
        "request_type": "modify_workflow",
        "draft_mode": "modify_workflow",
        "intent_summary": "LLM 뒤에 GitHub PR 댓글 등록을 추가합니다.",
        "knowledge_required": False,
        "knowledge_topics": [],
        "integration_actions": [
            {
                "provider": "github",
                "resource": "pull_request",
                "operation": "comment",
            }
        ],
        "edit": {
            "placement": "after",
            "target_reference_type": "natural_language_node",
            "target_query": "LLM",
            "target_capabilities": ["llm"],
        },
        "unsupported_requests": [],
    }
    client = SequenceFakeLLMClient(
        [
            {**base, "ordered_capabilities": ["http_request"]},
            {**base, "ordered_capabilities": ["github_pr_comment"]},
        ]
    )
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
    )

    result = extractor.extract(
        safe_message="LLM 뒤에 GitHub PR에 리뷰 댓글을 올리는 노드를 추가해줘",
        workflow_context={
            "workflow_present": True,
            "selected_node_present": False,
            "selected_edge_present": False,
            "nodes": [{"type": "llmNode", "title": "LLM"}],
        },
    )

    assert result.ordered_capabilities == ["github_pr_comment"]
    assert len(client.calls) == 2
    assert "GITHUB_OPERATION_CAPABILITY_MISMATCH" in str(client.calls[1][0])


@pytest.mark.parametrize(
    "message",
    [
        "기존 LLM 노드 뒤에 GitHub PR 생성 노드를 삽입",
        "기존 LLM 노드 뒤에 깃허브 PR 생성 노드를 삽입",
    ],
)
def test_llm_intent_extractor_repairs_missing_github_pr_create_action_once(
    message,
):
    base = {
        "request_type": "modify_workflow",
        "draft_mode": "modify_workflow",
        "intent_summary": "기존 LLM 뒤에 GitHub PR 생성 단계를 삽입합니다.",
        "knowledge_required": False,
        "knowledge_topics": [],
        "knowledge_candidate_handles": [],
        "edit": {
            "placement": "after",
            "target_reference_type": "natural_language_node",
            "target_query": "LLM",
            "target_capabilities": ["llm"],
        },
        "unsupported_requests": [],
    }
    client = SequenceFakeLLMClient(
        [
            {
                **base,
                "ordered_capabilities": ["http_request"],
                "integration_actions": [],
            },
            {
                **base,
                "ordered_capabilities": [],
                "integration_actions": [
                    {
                        "provider": "github",
                        "resource": "pull_request",
                        "operation": "create",
                    }
                ],
            },
        ]
    )
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
    )

    result = extractor.extract(
        safe_message=message,
        workflow_context={
            "workflow_present": True,
            "selected_node_present": False,
            "selected_edge_present": False,
            "nodes": [{"type": "llmNode", "title": "LLM"}],
        },
    )

    assert result.integration_actions[0].operation == "create"
    assert len(client.calls) == 2
    assert "GITHUB_INTEGRATION_ACTION_REQUIRED" in str(client.calls[1][0])

    structured = _service(FakeIntentExtractor(result))._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message=message),
        workflow=SimpleNamespace(
            id=uuid.uuid4(),
            graph={
                "nodes": [
                    {"id": "llm", "type": "llmNode", "data": {"title": "LLM"}},
                    {
                        "id": "answer",
                        "type": "answerNode",
                        "data": {"title": "응답"},
                    },
                ],
                "edges": [
                    {"id": "edge-llm-answer", "source": "llm", "target": "answer"}
                ],
            },
        ),
    )
    assert structured.request_type == "unsupported"
    assert structured.required_capabilities == []
    assert structured.unsupported_requests == [
        "GitHub Pull Request 생성은 현재 지원되지 않습니다."
    ]


def test_llm_intent_extractor_repairs_missing_github_pr_read_action_once():
    base = {
        "request_type": "modify_workflow",
        "draft_mode": "modify_workflow",
        "intent_summary": "기존 LLM 뒤에 GitHub PR 조회 단계를 삽입합니다.",
        "knowledge_required": False,
        "knowledge_topics": [],
        "knowledge_candidate_handles": [],
        "edit": {
            "placement": "after",
            "target_reference_type": "natural_language_node",
            "target_query": "LLM",
            "target_capabilities": ["llm"],
        },
        "unsupported_requests": [],
    }
    client = SequenceFakeLLMClient(
        [
            {
                **base,
                "ordered_capabilities": ["http_request"],
                "integration_actions": [],
            },
            {
                **base,
                "ordered_capabilities": ["github_pr_read"],
                "integration_actions": [
                    {
                        "provider": "github",
                        "resource": "pull_request",
                        "operation": "read",
                    }
                ],
            },
        ]
    )
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
    )

    result = extractor.extract(
        safe_message="기존 LLM 노드 뒤에 GitHub PR 조회 노드를 삽입",
        workflow_context={
            "workflow_present": True,
            "selected_node_present": False,
            "selected_edge_present": False,
            "nodes": [{"type": "llmNode", "title": "LLM"}],
        },
    )

    assert result.ordered_capabilities == ["github_pr_read"]
    assert len(client.calls) == 2
    assert "GITHUB_INTEGRATION_ACTION_REQUIRED" in str(client.calls[1][0])


@pytest.mark.parametrize(
    "message",
    [
        "기존 LLM 노드 뒤에 REST API 호출 노드를 삽입",
        "기존 LLM 노드 뒤에 GitHub API proxy 호출 노드를 삽입",
    ],
)
def test_llm_intent_extractor_does_not_repair_generic_http_request(message):
    client = FakeLLMClient(
        {
            "request_type": "modify_workflow",
            "draft_mode": "modify_workflow",
            "intent_summary": "기존 LLM 뒤에 REST API 호출을 삽입합니다.",
            "ordered_capabilities": ["http_request"],
            "knowledge_required": False,
            "knowledge_topics": [],
            "knowledge_candidate_handles": [],
            "integration_actions": [],
            "edit": {
                "placement": "after",
                "target_reference_type": "natural_language_node",
                "target_query": "LLM",
                "target_capabilities": ["llm"],
            },
            "unsupported_requests": [],
        }
    )
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
    )

    result = extractor.extract(
        safe_message=message,
        workflow_context={
            "workflow_present": True,
            "selected_node_present": False,
            "selected_edge_present": False,
            "nodes": [{"type": "llmNode", "title": "LLM"}],
        },
    )

    assert result.ordered_capabilities == ["http_request"]
    assert len(client.calls) == 1


def test_intent_capability_guide_is_catalog_derived_and_excludes_loop():
    guide = agent_builder_capability_guide()

    assert set(guide) == agent_builder_supported_capabilities()
    assert "loop" not in guide
    assert "webhook_trigger" in guide
    assert "knowledge_backed_llm" in guide


def test_llm_intent_extractor_passes_only_bounded_safe_kb_context():
    raw_kb_id = str(uuid.uuid4())
    context_calls = []

    def load_context(**kwargs):
        context_calls.append(kwargs)
        return [
            {
                "candidate_handle": "rec-safe-1",
                "safe_label": "사내 문서",
                "safe_topics": ["사내 문서", "온보딩"],
                "safe_description": "사내 정책과 절차",
                "runtime_availability": "available",
                "relevance_score": 0.82,
            }
        ]

    client = FakeLLMClient(
        {
            "request_type": "new_workflow",
            "draft_mode": "new_workflow",
            "intent_summary": "사내 문서 챗봇 workflow 생성",
            "ordered_capabilities": [
                "webhook_trigger",
                "knowledge_backed_llm",
                "answer",
            ],
            "knowledge_required": True,
            "knowledge_topics": ["사내 문서"],
            "knowledge_candidate_handles": ["rec-safe-1"],
            "edit": None,
        }
    )
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
        knowledge_context_loader=load_context,
    )

    result = extractor.extract(
        safe_message="웹훅으로 받는 사내 문서 챗봇 워크플로우를 만들어줘",
        workflow_context={"workflow_present": False, "nodes": []},
    )

    assert context_calls[0]["max_candidates"] == 20
    prompt = str(client.calls[0][0])
    assert "rec-safe-1" in prompt
    assert "사내 문서" in prompt
    assert "온보딩" in prompt
    assert "사내 정책과 절차" in prompt
    assert raw_kb_id not in prompt
    assert "raw_source_path" not in prompt
    assert result.knowledge_candidate_handles == ["rec-safe-1"]


def test_llm_intent_extractor_repairs_unknown_kb_candidate_handle_once():
    invalid = {
        "request_type": "new_workflow",
        "draft_mode": "new_workflow",
        "intent_summary": "사내 문서 챗봇 workflow 생성",
        "ordered_capabilities": ["start_input", "knowledge_backed_llm", "answer"],
        "knowledge_required": True,
        "knowledge_topics": ["사내 문서"],
        "knowledge_candidate_handles": ["rec-not-issued"],
        "edit": None,
    }
    valid = {**invalid, "knowledge_candidate_handles": ["rec-safe-1"]}
    client = SequenceFakeLLMClient([invalid, valid])
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
        knowledge_context_loader=lambda **_kwargs: [
            {
                "candidate_handle": "rec-safe-1",
                "safe_label": "사내 문서",
                "safe_topics": ["사내 문서"],
                "runtime_availability": "available",
                "relevance_score": 0.8,
            }
        ],
    )

    result = extractor.extract(
        safe_message="사내 문서로 답변하는 workflow를 만들어줘",
        workflow_context={"workflow_present": False, "nodes": []},
    )

    assert result.knowledge_candidate_handles == ["rec-safe-1"]
    assert len(client.calls) == 2
    assert "UNKNOWN_KNOWLEDGE_CANDIDATE_HANDLE" in str(client.calls[1][0])


def test_llm_intent_extractor_repairs_semantically_invalid_result_once():
    client = SequenceFakeLLMClient(
        [
            {
                "request_type": "modify_workflow",
                "draft_mode": "modify_workflow",
                "intent_summary": "provider-only-invalid-summary-marker",
                "ordered_capabilities": [],
                "edit": None,
            },
            {
                "request_type": "new_workflow",
                "draft_mode": "new_workflow",
                "intent_summary": "사내 문서 챗봇 workflow 생성",
                "ordered_capabilities": [
                    "webhook_trigger",
                    "knowledge_backed_llm",
                    "answer",
                ],
                "knowledge_required": True,
                "knowledge_topics": ["사내 문서"],
                "edit": None,
            },
        ]
    )
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
    )

    result = extractor.extract(
        safe_message="웹훅으로 받는 사내 문서 챗봇 워크플로우를 만들어줘",
        workflow_context={"workflow_present": True, "nodes": []},
    )

    assert result.request_type == "new_workflow"
    assert len(client.calls) == 2
    repair_messages = client.calls[1][0]
    assert len(repair_messages) == 2
    assert "MODIFY_EDIT_REQUIRED" in str(repair_messages)
    assert "MODIFY_CAPABILITY_REQUIRED" in str(repair_messages)
    assert "웹훅으로 받는 사내 문서 챗봇 워크플로우를 만들어줘" in str(
        repair_messages
    )
    assert "explicit existing target" in str(repair_messages)
    assert "direct object is a workflow" in str(repair_messages)
    assert "provider-only-invalid-summary-marker" not in str(repair_messages)


def test_llm_intent_extractor_fails_after_one_invalid_repair():
    invalid = {
        "request_type": "modify_workflow",
        "draft_mode": "modify_workflow",
        "intent_summary": "모순된 수정 요청",
        "ordered_capabilities": [],
        "edit": None,
    }
    client = SequenceFakeLLMClient([invalid, invalid])
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
    )

    with pytest.raises(AgentBuilderIntentExtractionError):
        extractor.extract(
            safe_message="workflow를 만들어줘",
            workflow_context={"workflow_present": True, "nodes": []},
        )

    assert len(client.calls) == 2


def test_llm_intent_extractor_does_not_echo_invalid_provider_payload():
    raw_payload = "not-json secret-provider-payload"
    client = FakeLLMClient(raw_payload)
    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=lambda **_kwargs: SimpleNamespace(client=client),
    )

    with pytest.raises(AgentBuilderIntentExtractionError) as exc:
        extractor.extract(
            safe_message="입력 노드 뒤에 응답 노드를 추가해줘",
            workflow_context={"workflow_present": True, "nodes": []},
        )

    assert raw_payload not in str(exc.value)


def test_llm_intent_extractor_reports_permission_aware_runtime_failure():
    def fail_runtime(**_kwargs):
        raise LLMCredentialNotAvailableError(
            "credential_not_available",
            "credential-secret-must-not-leak",
        )

    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=fail_runtime,
    )

    with pytest.raises(AgentBuilderIntentRuntimeUnavailableError) as exc:
        extractor.extract(
            safe_message="입력 출력 노드를 생성해줘",
            workflow_context={"workflow_present": False, "nodes": []},
        )

    assert "credential-secret-must-not-leak" not in str(exc.value)


def test_llm_intent_extractor_does_not_misclassify_internal_loader_error():
    def fail_runtime(**_kwargs):
        raise ValueError("internal-db-detail-must-not-leak")

    extractor = LLMAgentBuilderIntentExtractor(
        db=FakeDb(),
        user_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        runtime_loader=fail_runtime,
    )

    with pytest.raises(AgentBuilderIntentExtractionError) as exc:
        extractor.extract(
            safe_message="입력 출력 노드를 생성해줘",
            workflow_context={"workflow_present": False, "nodes": []},
        )

    assert not isinstance(exc.value, AgentBuilderIntentRuntimeUnavailableError)
    assert "internal-db-detail-must-not-leak" not in str(exc.value)


def test_service_normalizes_llm_intent_with_catalog_allowlist_and_llm_order():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="new_workflow",
            draft_mode="new_workflow",
            intent_summary="웹훅 GitHub PR 리뷰 댓글 workflow",
            ordered_capabilities=[
                "webhook_trigger",
                "github_pr_read",
                "llm",
                "github_pr_comment",
                "answer",
            ],
            integration_actions=[
                {
                    "provider": "github",
                    "resource": "pull_request",
                    "operation": "read",
                },
                {
                    "provider": "github",
                    "resource": "pull_request",
                    "operation": "comment",
                },
            ],
        )
    )
    svc = _service(extractor)

    structured = svc._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(
            message=(
                "새 워크플로우로 웹훅에서 요청을 받고 GitHub PR을 조회한 뒤 "
                "LLM으로 리뷰해서 GitHub PR에 댓글을 등록해줘"
            )
        ),
        workflow=None,
    )

    assert [step.capability for step in structured.planned_steps] == [
        "webhook_trigger",
        "github_pr_read",
        "llm",
        "github_pr_comment",
        "answer",
    ]
    entry, body = svc._ordered_preview_capabilities(structured)  # noqa: SLF001
    assert entry == "webhook_trigger"
    assert body == ["github_pr_read", "llm", "github_pr_comment"]


def test_production_normalizer_keeps_explicit_workflow_creation_new_with_existing_context():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="new_workflow",
            draft_mode="new_workflow",
            intent_summary="웹훅으로 받는 사내 문서 챗봇 workflow",
            ordered_capabilities=[
                "webhook_trigger",
                "knowledge_backed_llm",
                "answer",
            ],
            knowledge_required=True,
            knowledge_topics=["사내 문서"],
            knowledge_candidate_handles=["rec-safe-1"],
            edit=None,
        )
    )
    svc = _service(extractor)
    workflow = SimpleNamespace(
        id=uuid.uuid4(),
        graph={
            "nodes": [
                {"id": "existing", "type": "startNode", "data": {"title": "기존 입력"}}
            ],
            "edges": [],
        },
    )

    structured = svc._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(
            message="웹훅으로 받는 사내 문서 챗봇 워크플로우를 만들어줘"
        ),
        workflow=workflow,
    )

    assert structured.request_type == "new_workflow"
    assert structured.draft_mode == "new_workflow"
    assert [step.capability for step in structured.planned_steps] == [
        "webhook_trigger",
        "knowledge_backed_llm",
        "answer",
    ]
    assert structured.edit_operations == []
    assert structured.knowledge_requirements[0].suggested_candidate_handles == [
        "rec-safe-1"
    ]


def test_service_uses_llm_edit_structure_for_create_wording_without_regex():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="modify_workflow",
            draft_mode="modify_workflow",
            intent_summary="GitHub PR 댓글 등록 뒤에 LLM 노드를 삽입합니다.",
            ordered_capabilities=["llm"],
            edit=AgentBuilderSemanticEdit(
                operation="insert",
                placement="after",
                target_reference_type="natural_language_node",
                target_query="GitHub PR 댓글 등록",
                target_capabilities=["github_pr_comment"],
            ),
        )
    )
    svc = _service(extractor)
    workflow = SimpleNamespace(
        id=uuid.uuid4(),
        graph={
            "nodes": [
                {
                    "id": "github-comment",
                    "type": "githubNode",
                    "data": {"title": "GitHub PR 댓글 등록", "action": "comment_pr"},
                }
            ],
            "edges": [],
        },
    )

    structured = svc._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(
            message="github pr 댓글 등록 뒤에 llm 노드 생성해줘"
        ),
        workflow=workflow,
    )

    assert structured.draft_mode == "modify_workflow"
    assert structured.required_capabilities == ["llm"]
    assert [step.capability for step in structured.planned_steps] == ["llm"]
    assert structured.edit_operations[0].placement == "after"
    assert structured.edit_operations[0].target.capabilities == [
        "github_pr_comment"
    ]
    assert structured.edit_operations[0].target.node_types == ["githubNode"]


def test_service_rejects_schema_valid_modify_without_semantic_edit():
    svc = _service(
        FakeIntentExtractor(
            AgentBuilderIntentExtraction(
                request_type="modify_workflow",
                draft_mode="modify_workflow",
                intent_summary="workflow 생성",
                ordered_capabilities=[],
                edit=None,
            )
        )
    )

    with pytest.raises(AgentBuilderIntentExtractionError):
        svc._structure_request(  # noqa: SLF001
            AgentBuilderMessageRequest(message="workflow를 만들어줘"),
            workflow=SimpleNamespace(graph={"nodes": [], "edges": []}),
        )


def test_service_preserves_replace_mode_request_type():
    svc = _service(
        FakeIntentExtractor(
            AgentBuilderIntentExtraction(
                request_type="modify_workflow",
                draft_mode="replace_workflow",
                intent_summary="workflow 전체 교체",
                ordered_capabilities=["llm"],
                edit=None,
            )
        )
    )

    structured = svc._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="현재 workflow를 새 흐름으로 교체해줘"),
        workflow=SimpleNamespace(graph={"nodes": [], "edges": []}),
    )

    assert structured.request_type == "modify_workflow"
    assert structured.draft_mode == "replace_workflow"
    assert [step.capability for step in structured.planned_steps] == [
        "start_input",
        "llm",
        "answer",
    ]


def test_service_rejects_selected_edge_edit_without_selected_edge_context():
    svc = _service(
        FakeIntentExtractor(
            AgentBuilderIntentExtraction(
                request_type="modify_workflow",
                draft_mode="modify_workflow",
                intent_summary="선택 연결에 LLM 삽입",
                ordered_capabilities=["llm"],
                edit=AgentBuilderSemanticEdit(
                    placement="between",
                    target_reference_type="selected_edge",
                ),
            )
        )
    )

    with pytest.raises(AgentBuilderIntentExtractionError):
        svc._structure_request(  # noqa: SLF001
            AgentBuilderMessageRequest(message="선택한 연결에 LLM을 추가해줘"),
            workflow=SimpleNamespace(graph={"nodes": [], "edges": []}),
        )


def test_service_rejects_llm_capability_outside_catalog_allowlist():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="new_workflow",
            draft_mode="new_workflow",
            intent_summary="임의 shell 실행 workflow",
            ordered_capabilities=["start_input", "shell_execute", "answer"],
        )
    )
    svc = _service(extractor)

    structured = svc._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(message="shell을 실행하는 workflow를 만들어줘"),
        workflow=None,
    )

    assert structured.request_type == "unsupported"
    assert "shell_execute" not in structured.required_capabilities
    assert structured.risk_flags == ["unsupported_capability"]


def test_service_redacts_secret_before_sending_message_to_intent_extractor():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="new_workflow",
            draft_mode="new_workflow",
            intent_summary="HTTP workflow",
            ordered_capabilities=["start_input", "http_request", "answer"],
        )
    )
    svc = _service(extractor)

    svc._structure_request(  # noqa: SLF001
        AgentBuilderMessageRequest(
            message="api_key=secret-value HTTP 요청 workflow를 만들어줘"
        ),
        workflow=None,
    )

    assert "secret-value" not in extractor.calls[0]["safe_message"]
    assert "[redacted]" in extractor.calls[0]["safe_message"]


def test_service_does_not_fall_back_to_regex_when_llm_extraction_fails():
    svc = _service(FailingIntentExtractor())

    with pytest.raises(AgentBuilderIntentExtractionError):
        svc._structure_request(  # noqa: SLF001
            AgentBuilderMessageRequest(message="llm 뒤에 응답 노드를 추가해줘"),
            workflow=SimpleNamespace(
                id=uuid.uuid4(),
                graph={"nodes": [], "edges": []},
            ),
        )


def test_service_requires_intent_extractor_instead_of_implicit_regex_fallback():
    svc = AgentBuilderService(
        FakeDb(),
        user=SimpleNamespace(id=uuid.uuid4()),
        organization_id=uuid.uuid4(),
    )

    with pytest.raises(AgentBuilderIntentRuntimeUnavailableError):
        svc._structure_request(  # noqa: SLF001
            AgentBuilderMessageRequest(message="입력 출력 노드를 생성해줘"),
            workflow=None,
        )


def test_target_resolver_prefers_github_action_role_over_shared_node_type():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="modify_workflow",
            draft_mode="modify_workflow",
            intent_summary="GitHub 댓글 노드 뒤에 LLM을 추가합니다.",
            ordered_capabilities=["llm"],
            edit=AgentBuilderSemanticEdit(
                placement="after",
                target_reference_type="natural_language_node",
                target_query="GitHub",
                target_capabilities=["github_pr_comment"],
            ),
        )
    )
    svc = _service(extractor)
    workflow = SimpleNamespace(
        id=uuid.uuid4(),
        graph={
            "nodes": [
                {
                    "id": "github-read",
                    "type": "githubNode",
                    "data": {"title": "GitHub PR 조회", "action": "get_pr"},
                },
                {
                    "id": "github-comment",
                    "type": "githubNode",
                    "data": {"title": "GitHub PR 댓글 등록", "action": "comment_pr"},
                },
                {"id": "answer", "type": "answerNode", "data": {"title": "응답"}},
            ],
            "edges": [
                {
                    "id": "edge-comment-answer",
                    "source": "github-comment",
                    "target": "answer",
                }
            ],
        },
    )
    request = AgentBuilderMessageRequest(
        message="github pr 댓글 등록 뒤에 llm 노드 생성해줘"
    )
    structured = svc._structure_request(request, workflow)  # noqa: SLF001

    resolution = svc._resolve_edit_target(  # noqa: SLF001
        structured,
        workflow=workflow,
        selected_node_id=None,
        selected_edge_id=None,
    )

    assert resolution["status"] == "resolved"
    assert resolution["node_id"] == "github-comment"


def test_llm_structured_answer_insertion_rewires_existing_graph():
    extractor = FakeIntentExtractor(
        AgentBuilderIntentExtraction(
            request_type="modify_workflow",
            draft_mode="modify_workflow",
            intent_summary="LLM 뒤에 응답 노드를 추가합니다.",
            ordered_capabilities=["answer"],
            edit=AgentBuilderSemanticEdit(
                placement="after",
                target_reference_type="natural_language_node",
                target_query="LLM",
                target_capabilities=["llm"],
            ),
        )
    )
    svc = _service(extractor)
    workflow = SimpleNamespace(
        id=uuid.uuid4(),
        graph={
            "nodes": [
                {"id": "llm", "type": "llmNode", "data": {"title": "LLM"}},
                {
                    "id": "github-comment",
                    "type": "githubNode",
                    "data": {"title": "GitHub PR 댓글 등록", "action": "comment_pr"},
                },
            ],
            "edges": [
                {
                    "id": "edge-llm-comment",
                    "source": "llm",
                    "target": "github-comment",
                }
            ],
        },
    )
    request = AgentBuilderMessageRequest(message="llm 뒤에 응답 노드 하나 추가")
    structured = svc._structure_request(request, workflow)  # noqa: SLF001
    resolution = svc._resolve_edit_target(  # noqa: SLF001
        structured,
        workflow=workflow,
        selected_node_id=None,
        selected_edge_id=None,
    )

    preview = svc._build_preview_graph(  # noqa: SLF001
        structured,
        workflow=workflow,
        kb_bindings=[],
        target_resolution=resolution,
    )

    generated = [
        node for node in preview["nodes"] if str(node["id"]).startswith("agent-")
    ]
    assert [node["type"] for node in generated] == ["answerNode"]
    answer_id = generated[0]["id"]
    edge_pairs = {(edge["source"], edge["target"]) for edge in preview["edges"]}
    assert ("llm", "github-comment") not in edge_pairs
    assert ("llm", answer_id) in edge_pairs
    assert (answer_id, "github-comment") in edge_pairs
