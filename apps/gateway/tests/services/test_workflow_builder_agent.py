from apps.gateway.core.config import settings
from apps.gateway.services.workflow_builder_agent import (
    DEFAULT_AGENT_LLM_FALLBACK_MODEL,
    DEFAULT_AGENT_LLM_MODEL,
    DEMO_FAMILY_CARE_KB_ID,
    DEMO_FAMILY_CARE_KB_NAME,
    DEMO_SLACK_CHANNEL_ID,
    build_workflow_draft,
)


def _clear_agent_slack_token(monkeypatch):
    monkeypatch.setattr(settings, "WORKFLOW_BUILDER_AGENT_SLACK_BOT_TOKEN", None)
    monkeypatch.setattr(settings, "WORKFLOW_BUILDER_DEMO_SLACK_BOT_TOKEN", None)


def test_build_workflow_draft_creates_jira_slack_summary_graph(monkeypatch):
    _clear_agent_slack_token(monkeypatch)
    result = build_workflow_draft(
        "Jira issue summarize to Slack",
        {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 0.8}},
    )

    node_types = [node["type"] for node in result["graph_preview"]["nodes"]]

    assert result["status"] == "needs_input"
    assert node_types == ["webhookTrigger", "llmNode", "slackPostNode"]
    assert len(result["graph_preview"]["edges"]) == 2
    assert "Slack bot token connection" in result["missing_fields"]
    assert result["validation_errors"] == []

    llm = next(node for node in result["graph_preview"]["nodes"] if node["type"] == "llmNode")
    slack = next(
        node for node in result["graph_preview"]["nodes"] if node["type"] == "slackPostNode"
    )
    assert llm["data"]["model_id"] == DEFAULT_AGENT_LLM_MODEL
    assert llm["data"]["fallback_model_id"] == DEFAULT_AGENT_LLM_FALLBACK_MODEL
    assert slack["data"]["channel"] == DEMO_SLACK_CHANNEL_ID
    assert slack["data"]["message"] == "{{ llm_response }}"
    assert slack["data"]["referenced_variables"] == [
        {"name": "llm_response", "value_selector": [llm["id"], "text"]}
    ]


def test_build_workflow_draft_injects_agent_slack_token_when_configured(monkeypatch):
    _clear_agent_slack_token(monkeypatch)
    monkeypatch.setattr(
        settings,
        "WORKFLOW_BUILDER_AGENT_SLACK_BOT_TOKEN",
        "xoxb-agent-test-token",
    )

    result = build_workflow_draft(
        "Jira issue summarize to Slack",
        {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 0.8}},
    )

    slack = next(
        node for node in result["graph_preview"]["nodes"] if node["type"] == "slackPostNode"
    )
    assert "Slack bot token connection" not in result["missing_fields"]
    assert slack["data"]["authConfig"] == {"token": "xoxb-agent-test-token"}


def test_build_workflow_draft_maps_family_care_leave_demo_defaults(monkeypatch):
    _clear_agent_slack_token(monkeypatch)
    result = build_workflow_draft(
        (
            "가족돌봄휴가를 연차와 이어서 사용할 수 있는지, 어디에서 신청해야 하는지, "
            "증빙자료가 필요한지 지식베이스에서 찾아서 Slack으로 보내줘"
        ),
        {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 0.8}},
    )

    nodes = result["graph_preview"]["nodes"]
    llm = next(node for node in nodes if node["type"] == "llmNode")
    slack = next(node for node in nodes if node["type"] == "slackPostNode")

    assert result["status"] == "needs_input"
    assert "Knowledge base selection" not in result["missing_fields"]
    assert "LLM model credential/model selection" not in result["missing_fields"]
    assert "Slack bot token connection" in result["missing_fields"]
    assert llm["data"]["title"] == "KB Summarizer"
    assert llm["data"]["model_id"] == DEFAULT_AGENT_LLM_MODEL
    assert llm["data"]["fallback_model_id"] == DEFAULT_AGENT_LLM_FALLBACK_MODEL
    assert llm["data"]["knowledgeBases"] == [
        {"id": DEMO_FAMILY_CARE_KB_ID, "name": DEMO_FAMILY_CARE_KB_NAME}
    ]
    assert slack["data"]["channel"] == DEMO_SLACK_CHANNEL_ID
    assert slack["data"]["message"] == "{{ llm_response }}"
    assert slack["data"]["referenced_variables"] == [
        {"name": "llm_response", "value_selector": [llm["id"], "text"]}
    ]
    assert result["validation_errors"] == []


def test_build_workflow_draft_infers_family_care_demo_from_plain_scenario(monkeypatch):
    _clear_agent_slack_token(monkeypatch)
    result = build_workflow_draft(
        (
            "직원 A는 다음 달에 가족 병원 일정 때문에 며칠간 가족돌봄휴가를 "
            "사용해야 한다. 그런데 가족돌봄휴가를 연차와 이어서 사용할 수 "
            "있는지, 어디에서 신청해야 하는지, 증빙자료가 필요한지 정확히 모른다."
        ),
        {"nodes": [], "edges": [], "viewport": {"x": 0, "y": 0, "zoom": 0.8}},
    )

    node_types = [node["type"] for node in result["graph_preview"]["nodes"]]
    llm = next(node for node in result["graph_preview"]["nodes"] if node["type"] == "llmNode")
    slack = next(
        node for node in result["graph_preview"]["nodes"] if node["type"] == "slackPostNode"
    )

    assert result["status"] == "needs_input"
    assert node_types == ["startNode", "llmNode", "slackPostNode"]
    assert llm["data"]["title"] == "KB Summarizer"
    assert llm["data"]["knowledgeBases"] == [
        {"id": DEMO_FAMILY_CARE_KB_ID, "name": DEMO_FAMILY_CARE_KB_NAME}
    ]
    assert slack["data"]["channel"] == DEMO_SLACK_CHANNEL_ID
    assert slack["data"]["message"] == "{{ llm_response }}"
    assert result["missing_fields"] == ["Slack bot token connection"]
    assert result["validation_errors"] == []


def test_build_workflow_draft_requires_selection_for_existing_graph():
    existing_graph = {
        "nodes": [
            {
                "id": "start-1",
                "type": "startNode",
                "position": {"x": 0, "y": 0},
                "data": {"title": "Start"},
            },
            {
                "id": "template-1",
                "type": "templateNode",
                "position": {"x": 520, "y": 0},
                "data": {"title": "Template"},
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "start-1",
                "target": "template-1",
                "sourceHandle": "source",
                "targetHandle": "target",
            }
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
    }

    result = build_workflow_draft("summarize and answer", existing_graph)

    assert result["status"] == "needs_input"
    assert result["graph_preview"] is None
    assert "Which existing node should the agent edit from?" in result["questions"]
    assert result["validation_errors"] == []


def test_build_workflow_draft_inserts_guardrail_before_selected_node():
    existing_graph = {
        "nodes": [
            {
                "id": "start-1",
                "type": "startNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "title": "Start",
                    "variables": [{"id": "request", "name": "request"}],
                },
            },
            {
                "id": "slack-1",
                "type": "slackPostNode",
                "position": {"x": 520, "y": 0},
                "data": {"title": "Slack"},
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "start-1",
                "target": "slack-1",
                "sourceHandle": "source",
                "targetHandle": "target",
            }
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
    }

    result = build_workflow_draft(
        "Slack before sending, sanitize PII",
        existing_graph,
        selected_node_id="slack-1",
    )

    nodes = result["graph_preview"]["nodes"]
    guardrail = next(node for node in nodes if node["type"] == "guardrailNode")
    edges = result["graph_preview"]["edges"]

    assert result["validation_errors"] == []
    assert guardrail["data"]["operation"] == "sanitize_text"
    assert guardrail["data"]["guardrails"] == ["PII"]
    assert guardrail["data"]["input_selector"] == ["start-1", "request"]
    assert any(edge["source"] == "start-1" and edge["target"] == guardrail["id"] for edge in edges)
    assert any(edge["source"] == guardrail["id"] and edge["target"] == "slack-1" for edge in edges)


def test_build_workflow_draft_guardrail_matches_manual_node_defaults():
    existing_graph = {
        "nodes": [
            {
                "id": "start-1",
                "type": "startNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "title": "Start",
                    "variables": [{"id": "request", "name": "request"}],
                },
            },
            {
                "id": "slack-1",
                "type": "slackPostNode",
                "position": {"x": 520, "y": 0},
                "data": {"title": "Slack"},
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "start-1",
                "target": "slack-1",
                "sourceHandle": "source",
                "targetHandle": "target",
            }
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
    }

    result = build_workflow_draft(
        "Slack before sending, add guardrail",
        existing_graph,
        selected_node_id="slack-1",
    )

    nodes = result["graph_preview"]["nodes"]
    guardrail = next(node for node in nodes if node["type"] == "guardrailNode")

    assert guardrail["data"]["title"] == "가드레일"
    assert guardrail["data"]["operation"] == "check_text"
    assert guardrail["data"]["guardrails"] == ["Keywords"]
    assert guardrail["data"]["branching_enabled"] is True
    assert guardrail["data"]["branch_condition"] == "keyword_match"
    assert guardrail["data"]["pass_label"] == "통과"
    assert guardrail["data"]["fail_label"] == "실패"
    assert guardrail["data"]["pass_handle_id"] == "pass"
    assert guardrail["data"]["fail_handle_id"] == "fail"
    assert "가드레일 키워드 목록" in result["missing_fields"]
    assert result["validation_errors"] == []


def test_build_workflow_draft_inserts_keyword_guardrail_as_branch():
    existing_graph = {
        "nodes": [
            {
                "id": "start-1",
                "type": "startNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "title": "Start",
                    "variables": [{"id": "request", "name": "request"}],
                },
            },
            {
                "id": "slack-1",
                "type": "slackPostNode",
                "position": {"x": 520, "y": 0},
                "data": {"title": "Slack"},
            },
        ],
        "edges": [
            {
                "id": "edge-1",
                "source": "start-1",
                "target": "slack-1",
                "sourceHandle": "source",
                "targetHandle": "target",
            }
        ],
        "viewport": {"x": 0, "y": 0, "zoom": 0.8},
    }

    result = build_workflow_draft(
        'Slack before sending, if "blocked" word appears use guardrail pass',
        existing_graph,
        selected_node_id="slack-1",
    )

    nodes = result["graph_preview"]["nodes"]
    guardrail = next(node for node in nodes if node["type"] == "guardrailNode")
    pass_answer = next(node for node in nodes if node["data"]["title"] == "가드레일 통과")
    edges = result["graph_preview"]["edges"]

    assert result["validation_errors"] == []
    assert guardrail["data"]["operation"] == "check_text"
    assert guardrail["data"]["branching_enabled"] is True
    assert guardrail["data"]["match_keywords"] == ["blocked"]
    assert guardrail["data"]["guardrails"] == ["Keywords"]
    assert any(edge["source"] == "start-1" and edge["target"] == guardrail["id"] for edge in edges)
    assert any(
        edge["source"] == guardrail["id"]
        and edge["sourceHandle"] == "fail"
        and edge["target"] == "slack-1"
        for edge in edges
    )
    assert any(
        edge["source"] == guardrail["id"]
        and edge["sourceHandle"] == "pass"
        and edge["target"] == pass_answer["id"]
        for edge in edges
    )
