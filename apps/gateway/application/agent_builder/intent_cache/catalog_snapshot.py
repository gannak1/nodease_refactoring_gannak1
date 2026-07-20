from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class CatalogNodeSnapshot:
    node_type: str
    role: str
    capabilities: tuple[str, ...]
    parameter_input_types: tuple[tuple[str, str], ...]


AGENT_BUILDER_NODE_SNAPSHOT = (
    CatalogNodeSnapshot(
        "startNode",
        "entry",
        ("start_input",),
        (("variables", "json"),),
    ),
    CatalogNodeSnapshot(
        "webhookTrigger",
        "entry",
        ("webhook_trigger",),
        (("variable_mappings", "json"),),
    ),
    CatalogNodeSnapshot(
        "scheduleTrigger",
        "entry",
        ("schedule_trigger",),
        (("cron_expression", "text"), ("timezone", "text")),
    ),
    CatalogNodeSnapshot(
        "llmNode",
        "intermediate",
        ("llm", "knowledge_backed_llm"),
        (
            ("model_id", "resource_ref"),
            ("output_format_type", "select"),
            ("output_json_schema", "json"),
            ("system_prompt", "textarea"),
            ("user_prompt", "textarea"),
            ("assistant_prompt", "textarea"),
            ("referenced_variables", "variable_selector_list"),
            ("citationDisplayMode", "select"),
            ("auto_model_routing", "boolean"),
            ("fallback_model_id", "resource_ref"),
            ("model_routing_refresh_every_runs", "number"),
            ("model_routing_validation_budget_usd", "number"),
            ("model_routing_max_cohorts", "number"),
            ("knowledgeBases", "resource_ref"),
        ),
    ),
    CatalogNodeSnapshot(
        "workflowNode",
        "intermediate",
        ("workflow_call",),
        (("workflowId", "resource_ref"), ("appId", "resource_ref")),
    ),
    CatalogNodeSnapshot(
        "codeNode",
        "intermediate",
        ("code_execution",),
        (("code", "code"),),
    ),
    CatalogNodeSnapshot(
        "conditionNode",
        "branch",
        ("condition",),
        (("cases", "json"),),
    ),
    CatalogNodeSnapshot(
        "fileExtractionNode",
        "intermediate",
        ("file_extraction",),
        (("referenced_variables", "variable_selector"),),
    ),
    CatalogNodeSnapshot(
        "variableExtractionNode",
        "intermediate",
        ("variable_extraction",),
        (("source_selector", "variable_selector"), ("mappings", "json")),
    ),
    CatalogNodeSnapshot("answerNode", "terminal", ("answer",), (("outputs", "json"),)),
    CatalogNodeSnapshot(
        "httpRequestNode",
        "intermediate",
        ("http_request",),
        (("url", "text"),),
    ),
    CatalogNodeSnapshot(
        "slackPostNode",
        "intermediate",
        ("slack_send",),
        (
            ("slackMode", "select"),
            ("bot_token", "secret"),
            ("url", "secret"),
            ("channel", "text"),
            ("message", "textarea"),
            ("blocks", "json"),
            ("attachments", "json"),
            ("thread_ts", "text"),
            ("username", "text"),
            ("icon_emoji", "text"),
        ),
    ),
    CatalogNodeSnapshot(
        "templateNode",
        "intermediate",
        ("template_render",),
        (("template", "textarea"),),
    ),
    CatalogNodeSnapshot(
        "githubNode",
        "intermediate",
        ("github_pr_read", "github_pr_comment"),
        (
            ("action", "select"),
            ("api_token", "secret"),
            ("repo_owner", "text"),
            ("repo_name", "text"),
            ("pr_number", "number"),
            ("comment_body", "textarea"),
        ),
    ),
    CatalogNodeSnapshot(
        "mailNode",
        "intermediate",
        ("mail_search",),
        (
            ("credential_id", "credential_ref"),
            ("keyword", "text"),
            ("sender", "text"),
            ("subject", "text"),
            ("start_date", "text"),
            ("end_date", "text"),
            ("folder", "select"),
            ("max_results", "number"),
            ("unread_only", "boolean"),
            ("mark_as_read", "boolean"),
            ("processing_mode", "select"),
        ),
    ),
    CatalogNodeSnapshot(
        "gmailDraftNode",
        "intermediate",
        ("gmail_reply_draft_create",),
        (
            ("credential_id", "credential_ref"),
            ("processing_ref_selector", "variable_selector"),
            ("reply_body_selector", "variable_selector"),
        ),
    ),
    CatalogNodeSnapshot(
        "mailAcknowledgeNode",
        "terminal",
        ("mail_terminal_acknowledgement",),
        (
            ("processing_ref_selector", "variable_selector"),
            ("required_effect_ref_selectors", "variable_selector_list"),
        ),
    ),
)


CATALOG_NODE_ROLES = MappingProxyType(
    {node.node_type: node.role for node in AGENT_BUILDER_NODE_SNAPSHOT}
)
CATALOG_CAPABILITIES = frozenset(
    capability
    for node in AGENT_BUILDER_NODE_SNAPSHOT
    for capability in node.capabilities
)
CAPABILITY_PARAMETER_INPUT_TYPES = MappingProxyType(
    {
        capability: MappingProxyType(dict(node.parameter_input_types))
        for node in AGENT_BUILDER_NODE_SNAPSHOT
        for capability in node.capabilities
    }
)

CANONICAL_KNOWLEDGE_TOPIC_REFS = frozenset(
    {"topic.internal_documents.v1"}
)
CANONICAL_GUIDANCE_REASON_REFS = frozenset(
    {"guidance.reason.delivery_destination_required.v1"}
)
CANONICAL_INPUT_GUIDANCE_REFS = frozenset(
    {"guidance.input.select_slack_channel_id.v1"}
)

SUMMARY_PROJECTION_DESCRIPTOR = MappingProxyType(
    {
        "projection_id": "summary.current_safe_message.v1",
        "source": "IntentPlanningContext.full_safe_message",
        "whitespace_profile": "python-split-v1",
        "redaction_profile": "agent-builder-safe-summary-v1",
        "max_codepoints": 240,
        "failure": "summary_projection_failed",
        "provider_summary": "excluded",
        "persistence": "none",
    }
)

CAPABILITY_PURPOSES = MappingProxyType(
    {
        "start_input": "사용자 입력을 받습니다.",
        "webhook_trigger": "Webhook payload를 받습니다.",
        "schedule_trigger": "설정된 일정에 따라 workflow를 시작합니다.",
        "file_extraction": "입력 파일에서 텍스트를 추출합니다.",
        "variable_extraction": "입력 데이터에서 필요한 변수를 추출합니다.",
        "github_pr_read": "GitHub Pull Request와 변경 파일을 조회합니다.",
        "mail_search": "메일을 검색합니다.",
        "gmail_reply_draft_create": "원본 메일 thread에 Gmail 답장 초안을 생성합니다.",
        "mail_terminal_acknowledgement": "필수 작업 성공 후 원본 메일 처리를 완료합니다.",
        "http_request": "외부 HTTP API를 호출합니다.",
        "workflow_call": "다른 workflow를 호출합니다.",
        "code_execution": "sandbox에서 코드를 실행합니다.",
        "template_render": "입력값으로 템플릿을 렌더링합니다.",
        "condition": "조건에 따라 흐름을 분기합니다.",
        "llm": "입력을 분석하고 결과를 생성합니다.",
        "knowledge_backed_llm": "Knowledge Base 근거로 입력을 분석하고 결과를 생성합니다.",
        "github_pr_comment": "생성한 내용을 GitHub Pull Request 댓글로 등록합니다.",
        "slack_send": "이전 단계 결과를 Slack 메시지로 전송합니다.",
        "answer": "이전 단계 결과를 응답으로 반환합니다.",
    }
)

if frozenset(CAPABILITY_PURPOSES) != CATALOG_CAPABILITIES:
    raise RuntimeError("intent cache purpose snapshot is incomplete")
