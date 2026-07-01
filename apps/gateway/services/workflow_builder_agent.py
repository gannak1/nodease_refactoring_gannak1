import json
import re
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any, Literal
from uuid import uuid4

import httpx

from apps.gateway.core.config import settings

WorkflowBuilderStatus = Literal["ready", "needs_input", "invalid", "error"]
WorkflowBuilderMode = Literal["openai", "heuristic"]

DEFAULT_VIEWPORT = {"x": 0, "y": 0, "zoom": 0.8}
NODE_X_GAP = 520
NODE_Y = 180
NODE_BRANCH_Y_GAP = 260
OPENAI_CHAT_COMPLETIONS_URL = "https://api.openai.com/v1/chat/completions"
DEMO_SLACK_CHANNEL_ID = "C0BB8QWV0CX"
DEFAULT_AGENT_LLM_MODEL = "gpt-5-mini"
DEFAULT_AGENT_LLM_FALLBACK_MODEL = "gpt-5-min"
DEMO_FAMILY_CARE_KB_ID = "30000000-0000-0000-0000-000000000101"
DEMO_FAMILY_CARE_KB_NAME = "가족돌봄휴가 안내"
SOURCE_NODE_TYPES = {"startNode", "webhookTrigger", "scheduleTrigger"}
TERMINAL_NODE_TYPES = {"answerNode"}
ACTION_NODE_TYPES = {
    "github": "githubNode",
    "mail": "mailNode",
    "http": "httpRequestNode",
    "guardrail": "guardrailNode",
    "llm": "llmNode",
    "template": "templateNode",
    "slack": "slackPostNode",
    "answer": "answerNode",
}


@dataclass
class BuilderPlan:
    trigger: str = "manual"
    actions: list[str] = field(default_factory=list)
    missing_fields: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    message: str | None = None


def _includes_any(value: str, terms: list[str]) -> bool:
    return any(term in value for term in terms)


def _unique(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _is_family_care_leave_demo(prompt: str) -> bool:
    normalized = prompt.lower()
    return _includes_any(
        normalized,
        [
            "가족돌봄",
            "가족 돌봄",
            "가족돌봄휴가",
            "family care leave",
        ],
    )


def is_family_care_leave_demo_request(prompt: str) -> bool:
    return _is_family_care_leave_demo(prompt)


def _default_demo_knowledge_base() -> dict[str, str]:
    return {"id": DEMO_FAMILY_CARE_KB_ID, "name": DEMO_FAMILY_CARE_KB_NAME}


def _demo_knowledge_bases(
    prompt: str,
    with_knowledge: bool,
    demo_knowledge_base: dict[str, str] | None = None,
) -> list[dict[str, str]]:
    if not with_knowledge or not _is_family_care_leave_demo(prompt):
        return []
    return [demo_knowledge_base or _default_demo_knowledge_base()]


def _llm_user_prompt(prompt: str, with_knowledge: bool) -> str:
    if not _is_family_care_leave_demo(prompt):
        return prompt
    if with_knowledge:
        return (
            "지식 베이스를 근거로 직원 A에게 가족돌봄휴가 안내문을 작성해줘. "
            "반드시 가족돌봄휴가를 연차와 이어서 사용할 수 있는지, 어디에서 "
            "신청해야 하는지, 증빙자료가 필요한지를 포함하고 Slack으로 공유하기 "
            f"좋은 짧은 형식으로 정리해줘.\n\n요청: {prompt}"
        )
    return prompt


def _graph_from_request(graph: dict[str, Any] | None) -> dict[str, Any]:
    graph = graph or {}
    return {
        "nodes": graph.get("nodes") or [],
        "edges": graph.get("edges") or [],
        "viewport": graph.get("viewport") or DEFAULT_VIEWPORT,
    }


def _is_starter_graph(graph: dict[str, Any]) -> bool:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    return not edges and (
        not nodes or (len(nodes) == 1 and nodes[0].get("type") == "startNode")
    )


def _should_replace_graph(prompt: str, graph: dict[str, Any]) -> bool:
    return _is_starter_graph(graph) or _includes_any(
        prompt,
        [
            "replace",
            "from scratch",
            "new workflow",
            "reset",
            "\uc0c8\ub85c",
            "\ucc98\uc74c\ubd80\ud130",
            "\uad50\uccb4",
            "\ucd08\uae30\ud654",
        ],
    )


def _append_position(nodes: list[dict[str, Any]]) -> dict[str, float]:
    if not nodes:
        return {"x": 240, "y": NODE_Y}

    max_x = max(float((node.get("position") or {}).get("x") or 0) for node in nodes)
    min_y = min(float((node.get("position") or {}).get("y") or NODE_Y) for node in nodes)
    return {"x": max_x + NODE_X_GAP, "y": min_y}


def _tail_node(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]):
    outgoing_node_ids = {edge.get("source") for edge in edges}
    candidates = [
        node
        for node in nodes
        if node.get("id") not in outgoing_node_ids
        and node.get("type") not in TERMINAL_NODE_TYPES
    ]
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda node: float((node.get("position") or {}).get("x") or 0),
        reverse=True,
    )[0]


def _node(
    node_id: str,
    node_type: str,
    title: str,
    position: dict[str, float],
    data: dict[str, Any],
) -> dict[str, Any]:
    clean_data = {key: value for key, value in data.items() if value is not None}
    return {
        "id": node_id,
        "type": node_type,
        "position": position,
        "data": {
            "title": title,
            **clean_data,
        },
    }


def _edge(
    source: str,
    target: str,
    index: int,
    source_handle: str = "source",
    target_handle: str = "target",
) -> dict[str, Any]:
    return {
        "id": f"agent-edge-{source}-{source_handle}-{target}-{target_handle}-{index}",
        "source": source,
        "target": target,
        "sourceHandle": source_handle,
        "targetHandle": target_handle,
        "type": "puzzle",
    }


def _start_node(base_id: str, position: dict[str, float]) -> dict[str, Any]:
    return _node(
        f"{base_id}-start",
        "startNode",
        "Start",
        position,
        {
            "triggerType": "manual",
            "variables": [
                {
                    "id": f"{base_id}-request",
                    "name": "request",
                    "label": "Request",
                    "type": "paragraph",
                    "required": True,
                }
            ],
        },
    )


def _webhook_node(base_id: str, position: dict[str, float], provider: str):
    return _node(
        f"{base_id}-webhook",
        "webhookTrigger",
        "Jira Webhook" if provider == "jira" else "Webhook",
        position,
        {
            "provider": provider,
            "variable_mappings": [
                {"variable_name": "summary", "json_path": "$.issue.fields.summary"},
                {
                    "variable_name": "description",
                    "json_path": "$.issue.fields.description",
                },
            ],
        },
    )


def _schedule_node(base_id: str, position: dict[str, float]) -> dict[str, Any]:
    return _node(
        f"{base_id}-schedule",
        "scheduleTrigger",
        "Schedule",
        position,
        {"cron_expression": "0 9 * * *", "timezone": "Asia/Seoul"},
    )


def _github_node(base_id: str, position: dict[str, float]) -> dict[str, Any]:
    return _node(
        f"{base_id}-github",
        "githubNode",
        "GitHub",
        position,
        {
            "action": "get_pr",
            "api_token": "",
            "repo_owner": "",
            "repo_name": "",
            "pr_number": "",
            "comment_body": "",
            "referenced_variables": [],
        },
    )


def _mail_node(base_id: str, position: dict[str, float]) -> dict[str, Any]:
    return _node(
        f"{base_id}-mail",
        "mailNode",
        "Mail Search",
        position,
        {
            "email": "",
            "password": "",
            "provider": "gmail",
            "imap_server": "imap.gmail.com",
            "imap_port": 993,
            "use_ssl": True,
            "folder": "INBOX",
            "max_results": 10,
            "unread_only": False,
            "mark_as_read": False,
            "referenced_variables": [],
        },
    )


def _http_node(base_id: str, position: dict[str, float]) -> dict[str, Any]:
    return _node(
        f"{base_id}-http",
        "httpRequestNode",
        "HTTP Request",
        position,
        {
            "method": "GET",
            "url": "",
            "headers": [],
            "body": "",
            "timeout": 5000,
            "authType": "none",
            "authConfig": {},
            "referenced_variables": [],
        },
    )


def _llm_node(
    base_id: str,
    position: dict[str, float],
    prompt: str,
    with_knowledge: bool,
    demo_knowledge_base: dict[str, str] | None = None,
) -> dict[str, Any]:
    return _node(
        f"{base_id}-llm",
        "llmNode",
        "KB Summarizer" if with_knowledge else "LLM",
        position,
        {
            "provider": "openai",
            "model_id": DEFAULT_AGENT_LLM_MODEL,
            "fallback_model_id": DEFAULT_AGENT_LLM_FALLBACK_MODEL,
            "system_prompt": (
                "You are a workflow assistant. Use provided context and produce "
                "concise business-ready output."
            ),
            "user_prompt": _llm_user_prompt(prompt, with_knowledge),
            "assistant_prompt": "",
            "referenced_variables": [],
            "context_variable": "knowledge_context" if with_knowledge else "",
            "knowledgeBases": _demo_knowledge_bases(
                prompt,
                with_knowledge,
                demo_knowledge_base,
            )
            if with_knowledge
            else None,
            "scoreThreshold": 0.5 if with_knowledge else None,
            "topK": 5 if with_knowledge else None,
            "parameters": {
                "temperature": 0.3,
                "top_p": 1,
                "max_tokens": 1200,
                "presence_penalty": 0,
                "frequency_penalty": 0,
                "stop": [],
            },
        },
    )


def _template_node(base_id: str, position: dict[str, float]) -> dict[str, Any]:
    return _node(
        f"{base_id}-template",
        "templateNode",
        "Message Template",
        position,
        {"template": "{{summary}}", "variables": []},
    )


def _slack_message_binding(
    input_selector: list[str] | None,
) -> tuple[str, list[dict[str, Any]]]:
    if not input_selector:
        return "", []
    return (
        "{{ llm_response }}",
        [{"name": "llm_response", "value_selector": input_selector}],
    )


def _demo_slack_bot_token() -> str:
    token = (
        settings.WORKFLOW_BUILDER_AGENT_SLACK_BOT_TOKEN
        or settings.WORKFLOW_BUILDER_DEMO_SLACK_BOT_TOKEN
        or ""
    )
    return token.strip()


def _demo_slack_auth_config() -> dict[str, str]:
    token = _demo_slack_bot_token()
    return {"token": token} if token else {}


def _has_demo_slack_bot_token() -> bool:
    return bool(_demo_slack_bot_token())


def _slack_node(
    base_id: str,
    position: dict[str, float],
    input_selector: list[str] | None = None,
) -> dict[str, Any]:
    message_template, referenced_variables = _slack_message_binding(input_selector)
    return _node(
        f"{base_id}-slack",
        "slackPostNode",
        "Slack",
        position,
        {
            "method": "POST",
            "url": "https://slack.com/api/chat.postMessage",
            "headers": [{"key": "Content-Type", "value": "application/json"}],
            "body": json.dumps(
                {"channel": DEMO_SLACK_CHANNEL_ID, "text": message_template},
                indent=2,
            ),
            "timeout": 5000,
            "authType": "bearer",
            "authConfig": _demo_slack_auth_config(),
            "referenced_variables": referenced_variables,
            "message": message_template,
            "channel": DEMO_SLACK_CHANNEL_ID,
            "blocks": "",
            "slackMode": "api",
        },
    )


def _wants_guardrail(prompt: str) -> bool:
    return _includes_any(
        prompt,
        [
            "guardrail",
            "guard rail",
            "sanitize",
            "redact",
            "mask",
            "pii",
            "personal data",
            "secret",
            "api key",
            "token",
            "password",
            "jailbreak",
            "nsfw",
            "regex",
            "url",
            "\uac00\ub4dc\ub808\uc77c",
            "\uc815\uc81c",
            "\uc81c\uac70",
            "\ub9c8\uc2a4\ud0b9",
            "\uac1c\uc778\uc815\ubcf4",
            "\ube44\ubc00",
            "\ud0a4",
            "\ud0c8\uc625",
            "\uc815\uaddc\uc2dd",
        ],
    )


def _guardrail_operation(prompt: str) -> str:
    if _includes_any(
        prompt,
        [
            "sanitize",
            "redact",
            "mask",
            "remove",
            "scrub",
            "\uc815\uc81c",
            "\uc81c\uac70",
            "\ub9c8\uc2a4\ud0b9",
            "\uc775\uba85",
        ],
    ):
        return "sanitize_text"
    return "check_text"


def _guardrail_options(prompt: str, operation: str) -> list[str]:
    options: list[str] = []
    if operation == "sanitize_text":
        if _includes_any(
            prompt,
            [
                "pii",
                "personal",
                "email",
                "phone",
                "\uac1c\uc778\uc815\ubcf4",
                "\uc774\uba54\uc77c",
                "\uc804\ud654",
            ],
        ):
            options.append("PII")
        if _includes_any(
            prompt,
            ["secret", "api key", "token", "password", "\ube44\ubc00", "\ud0a4"],
        ):
            options.append("Secret Keys")
        if _includes_any(prompt, ["url", "link", "\ub9c1\ud06c"]):
            options.append("URLs")
        if _includes_any(prompt, ["regex", "\uc815\uaddc\uc2dd"]):
            options.append("Custom Regex")
        return _unique(options or ["PII"])

    if _includes_any(
        prompt,
        ["keyword", "specific word", "word", "\ud0a4\uc6cc\ub4dc", "\ub2e8\uc5b4"],
    ):
        options.append("Keywords")
    if _includes_any(prompt, ["jailbreak", "\ud0c8\uc625"]):
        options.append("Jailbreak")
    if _includes_any(prompt, ["nsfw", "\uc131\uc778", "\uc720\ud574"]):
        options.append("NSFW")
    if _includes_any(
        prompt,
        ["pii", "personal", "email", "phone", "\uac1c\uc778\uc815\ubcf4"],
    ):
        options.append("Personal Data (PII)")
    if _includes_any(
        prompt,
        ["secret", "api key", "token", "password", "\ube44\ubc00", "\ud0a4"],
    ):
        options.append("Secret Keys")
    if _includes_any(prompt, ["topic", "alignment", "\uc8fc\uc81c"]):
        options.append("Topical Alignment")
    if _includes_any(prompt, ["url", "link", "\ub9c1\ud06c"]):
        options.append("URLs")
    if _includes_any(prompt, ["custom", "\ucee4\uc2a4\ud140"]):
        options.append("Custom")
    if _includes_any(prompt, ["regex", "\uc815\uaddc\uc2dd"]):
        options.append("Custom Regex")

    return _unique(options or ["Keywords"])


KEYWORD_STOP_WORDS = {
    "keyword",
    "keywords",
    "word",
    "words",
    "specific",
    "contains",
    "contain",
    "included",
    "include",
    "else",
    "normal",
    "pass",
    "fail",
    "guardrail",
    "guard",
    "rail",
    "\ud0a4\uc6cc\ub4dc",
    "\ub2e8\uc5b4",
    "\ud2b9\uc815",
    "\ud3ec\ud568",
    "\ub4e4\uc5b4\uc624\uba74",
    "\uc788\uc73c\uba74",
    "\uc544\ub2c8\uba74",
    "\uc815\uc0c1",
    "\ub77c\ub294",
    "\uc774\ub77c\ub294",
    "\uac00",
    "\uc774",
    "\uc740",
    "\ub294",
}


def _split_keywords(value: str) -> list[str]:
    keywords: list[str] = []
    for item in re.split(r"[,/\s]+", value):
        cleaned = item.strip(" \t\r\n\"'`.,;:()[]{}<>")
        if not cleaned:
            continue
        if cleaned.lower() in KEYWORD_STOP_WORDS:
            continue
        if len(cleaned) == 1 and not cleaned.isalnum():
            continue
        keywords.append(cleaned)
    return _unique(keywords)


def _guardrail_keywords(prompt: str) -> list[str]:
    keywords: list[str] = []
    for pattern in [
        r'"([^"]{1,80})"',
        r"'([^']{1,80})'",
        r"`([^`]{1,80})`",
        r"\u201c([^\u201d]{1,80})\u201d",
        r"\u2018([^\u2019]{1,80})\u2019",
    ]:
        for match in re.findall(pattern, prompt):
            keywords.extend(_split_keywords(str(match)))
    if keywords:
        return _unique(keywords)

    keyword_segment_pattern = re.compile(
        r"(?:keyword|keywords|word|words|\ud0a4\uc6cc\ub4dc|\ub2e8\uc5b4)"
        r"\s*(?:is|are|:|=|\uc740|\ub294|\uc774|\uac00)?\s*"
        r"([A-Za-z0-9_\-.\uac00-\ud7a3, ]{1,80})",
        re.IGNORECASE,
    )
    for match in keyword_segment_pattern.findall(prompt):
        keywords.extend(_split_keywords(str(match)))

    korean_suffix_pattern = re.compile(
        r"([A-Za-z0-9_\-.\uac00-\ud7a3]{2,40})\s*"
        r"(?:\ub77c\ub294|\uc774\ub77c\ub294)?\s*"
        r"(?:\ub2e8\uc5b4|\ud0a4\uc6cc\ub4dc)"
    )
    for match in korean_suffix_pattern.findall(prompt):
        keywords.extend(_split_keywords(str(match)))

    return _unique(keywords)


def _is_keyword_branch_request(prompt: str) -> bool:
    return _includes_any(
        prompt.lower(),
        [
            "keyword",
            "specific word",
            "contains",
            "contain",
            "\ud0a4\uc6cc\ub4dc",
            "\ub2e8\uc5b4",
            "\ud3ec\ud568",
            "\ub4e4\uc5b4\uc624\uba74",
        ],
    )


def _guardrail_branch_enabled(
    prompt: str, operation: str, keywords: list[str]
) -> bool:
    return operation == "check_text" and (
        bool(keywords)
        or _is_keyword_branch_request(prompt)
        or _includes_any(prompt.lower(), ["guardrail", "\uac00\ub4dc\ub808\uc77c"])
    )


def _primary_output_selector(node: dict[str, Any] | None) -> list[str]:
    if not node:
        return []
    node_id = str(node.get("id") or "")
    node_type = node.get("type")
    data = node.get("data") or {}

    if node_type == "webhookTrigger":
        mappings = data.get("variable_mappings") or []
        if mappings:
            key = str((mappings[0] or {}).get("variable_name") or "").strip()
            return [node_id, key] if key else []
    if node_type == "startNode":
        variables = data.get("variables") or []
        if variables:
            key = str((variables[0] or {}).get("name") or "").strip()
            return [node_id, key] if key else []
    if node_type == "variableExtractionNode":
        mappings = data.get("mappings") or []
        if mappings:
            key = str((mappings[0] or {}).get("name") or "").strip()
            return [node_id, key] if key else []
    if node_type == "answerNode":
        outputs = data.get("outputs") or []
        if outputs:
            key = str((outputs[0] or {}).get("variable") or "").strip()
            return [node_id, key] if key else []

    output_key_by_type = {
        "llmNode": "text",
        "templateNode": "text",
        "codeNode": "result",
        "httpRequestNode": "data",
        "githubNode": "pr_body",
        "mailNode": "emails",
        "fileExtractionNode": "text",
        "guardrailNode": (
            "sanitized_text"
            if data.get("operation") == "sanitize_text"
            else "checked_text"
        ),
        "scheduleTrigger": "triggered_at",
    }
    key = output_key_by_type.get(str(node_type))
    return [node_id, key] if node_id and key else []


def _guardrail_node(
    base_id: str,
    position: dict[str, float],
    prompt: str,
    input_selector: list[str] | None = None,
) -> dict[str, Any]:
    normalized = prompt.lower()
    operation = _guardrail_operation(normalized)
    keywords = _guardrail_keywords(prompt)
    guardrails = _guardrail_options(normalized, operation)
    if keywords and operation == "check_text" and "Keywords" not in guardrails:
        guardrails.insert(0, "Keywords")
    branching_enabled = _guardrail_branch_enabled(prompt, operation, keywords)
    selector = input_selector or []
    reference_name = selector[1] if len(selector) >= 2 else ""

    return _node(
        f"{base_id}-guardrail",
        "guardrailNode",
        "가드레일",
        position,
        {
            "operation": operation,
            "text_to_check": "",
            "input_selector": selector,
            "system_message": (
                "입력 텍스트가 선택한 가드레일 조건을 위반하는지 검사하고 "
                "구조화된 결과를 반환합니다."
            ),
            "guardrails": _unique(guardrails),
            "custom_keywords": ", ".join(keywords),
            "custom_prompt": "",
            "custom_regex": "",
            "branching_enabled": branching_enabled,
            "branch_condition": "keyword_match",
            "match_keywords": keywords,
            "pass_label": "통과",
            "fail_label": "실패",
            "pass_handle_id": "pass",
            "fail_handle_id": "fail",
            "referenced_variables": (
                [{"name": reference_name, "value_selector": selector}]
                if reference_name
                else []
            ),
        },
    )


def _answer_node(base_id: str, position: dict[str, float]) -> dict[str, Any]:
    return _node(
        f"{base_id}-answer",
        "answerNode",
        "Answer",
        position,
        {"outputs": []},
    )


def _is_branching_guardrail(node: dict[str, Any]) -> bool:
    data = node.get("data") or {}
    return (
        node.get("type") == "guardrailNode"
        and data.get("operation") != "sanitize_text"
        and data.get("branching_enabled") is True
    )


def _guardrail_pass_handle(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    return str(data.get("pass_handle_id") or "pass")


def _guardrail_fail_handle(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    return str(data.get("fail_handle_id") or "fail")


def _unique_node_id(nodes: list[dict[str, Any]], base_id: str) -> str:
    existing_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    if base_id not in existing_ids:
        return base_id
    suffix = 2
    while f"{base_id}-{suffix}" in existing_ids:
        suffix += 1
    return f"{base_id}-{suffix}"


def _guardrail_pass_answer_node(
    nodes: list[dict[str, Any]],
    guardrail_node: dict[str, Any],
) -> dict[str, Any]:
    guardrail_id = str(guardrail_node.get("id") or "guardrail")
    position = guardrail_node.get("position") or {}
    x = float(position.get("x") or 0) + NODE_X_GAP
    y = float(position.get("y") or NODE_Y) + NODE_BRANCH_Y_GAP
    return _node(
        _unique_node_id(nodes, f"{guardrail_id}-pass-answer"),
        "answerNode",
        "가드레일 통과",
        {"x": x, "y": y},
        {
            "outputs": [
                {
                    "variable": "guardrail_result",
                    "value_selector": [guardrail_id, "violations"],
                }
            ],
        },
    )


def _ensure_guardrail_branch_outputs(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    selected_nodes: list[dict[str, str]],
    missing_fields: list[str],
    new_node_ids: set[str],
) -> None:
    for guardrail_node in list(nodes):
        guardrail_id = str(guardrail_node.get("id") or "")
        if guardrail_id not in new_node_ids or not _is_branching_guardrail(
            guardrail_node
        ):
            continue

        data = guardrail_node.get("data") or {}
        if not data.get("match_keywords"):
            _add_missing_field(missing_fields, "가드레일 키워드 목록")

        fail_handle = _guardrail_fail_handle(guardrail_node)
        pass_handle = _guardrail_pass_handle(guardrail_node)

        for index, edge in enumerate(edges):
            if edge.get("source") != guardrail_id:
                continue
            if edge.get("sourceHandle") in {None, "", "source"}:
                edge["sourceHandle"] = fail_handle
                edge["id"] = (
                    f"agent-edge-{guardrail_id}-{fail_handle}-"
                    f"{edge.get('target')}-{edge.get('targetHandle') or 'target'}-{index}"
                )

        has_pass_edge = any(
            edge.get("source") == guardrail_id
            and edge.get("sourceHandle") == pass_handle
            for edge in edges
        )
        if has_pass_edge:
            continue

        pass_answer = _guardrail_pass_answer_node(nodes, guardrail_node)
        nodes.append(pass_answer)
        selected_nodes.append(
            {
                "id": pass_answer["id"],
                "type": pass_answer.get("type") or "unknown",
                "title": _node_title(pass_answer),
                "reason": "가드레일 통과 분기의 종료 노드입니다.",
            }
        )
        edges.append(
            _edge(
                guardrail_id,
                pass_answer["id"],
                len(edges),
                source_handle=pass_handle,
            )
        )


def _infer_plan(prompt: str) -> BuilderPlan:
    normalized = prompt.lower()
    wants_jira = _includes_any(
        normalized,
        ["jira", "\uc9c0\ub77c", "issue", "\uc774\uc288"],
    )
    wants_schedule = _includes_any(
        normalized,
        ["schedule", "cron", "daily", "weekly", "\ub9e4\uc77c", "\uc815\uae30"],
    )
    wants_slack = _includes_any(normalized, ["slack", "\uc2ac\ub799"])
    wants_github = _includes_any(
        normalized,
        ["github", "git hub", "pr", "pull request", "\ud480\ub9ac\ud018"],
    )
    wants_mail = _includes_any(
        normalized,
        ["mail", "email", "\uba54\uc77c", "\uc774\uba54\uc77c"],
    )
    wants_http = _includes_any(normalized, ["http", "api", "webhook"])
    wants_knowledge = _includes_any(
        normalized,
        [
            "knowledge",
            "kb",
            "wiki",
            "rag",
            "document",
            "\ubb38\uc11c",
            "\uc704\ud0a4",
            "\uc9c0\uc2dd",
            "\uac80\uc0c9",
        ],
    )
    wants_llm = _includes_any(
        normalized,
        [
            "llm",
            "ai",
            "summary",
            "summarize",
            "\uc694\uc57d",
            "\uc815\ub9ac",
            "\ubd84\uc11d",
        ],
    )
    wants_guardrail = _wants_guardrail(normalized)
    if _is_family_care_leave_demo(normalized):
        wants_knowledge = True
        wants_llm = True
        wants_slack = True

    actions: list[str] = []
    if wants_github:
        actions.append("github")
    if wants_mail:
        actions.append("mail")
    if wants_http and not wants_jira:
        actions.append("http")
    if wants_knowledge:
        actions.append("knowledge")
    if wants_guardrail:
        actions.append("guardrail")
    if wants_llm or wants_knowledge or wants_slack:
        actions.append("llm")
    if wants_slack:
        actions.append("slack")
    if not wants_slack:
        actions.append("answer")

    return BuilderPlan(
        trigger="schedule" if wants_schedule else "jira" if wants_jira else "manual",
        actions=_unique(actions or ["llm", "answer"]),
    )


def _sanitize_plan(prompt: str, raw_plan: dict[str, Any] | None) -> BuilderPlan:
    inferred = _infer_plan(prompt)
    if not raw_plan:
        return inferred

    allowed_triggers = {"manual", "jira", "schedule", "existing"}
    allowed_actions = {
        "github",
        "mail",
        "http",
        "knowledge",
        "guardrail",
        "llm",
        "template",
        "slack",
        "answer",
    }
    trigger = raw_plan.get("trigger")
    actions = [
        str(action)
        for action in raw_plan.get("actions", [])
        if str(action) in allowed_actions
    ]
    if _wants_guardrail(prompt.lower()) and "guardrail" not in actions:
        actions.insert(0, "guardrail")
    if _is_family_care_leave_demo(prompt):
        actions = [action for action in actions if action != "answer"]
        for required_action in ["knowledge", "llm", "slack"]:
            if required_action not in actions:
                actions.append(required_action)

    return BuilderPlan(
        trigger=str(trigger) if trigger in allowed_triggers else inferred.trigger,
        actions=_unique(actions or inferred.actions),
        missing_fields=[
            str(field) for field in raw_plan.get("missing_fields", []) if field
        ],
        questions=[str(question) for question in raw_plan.get("questions", []) if question],
        message=str(raw_plan["message"]) if raw_plan.get("message") else None,
    )


def _add_missing_field(fields: list[str], field_name: str) -> None:
    if field_name not in fields:
        fields.append(field_name)


def _node_title(node: dict[str, Any]) -> str:
    data = node.get("data") or {}
    return str(data.get("title") or node.get("type") or node.get("id"))


def _validate_graph(graph: dict[str, Any]) -> tuple[list[str], list[str]]:
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    node_map = {node.get("id"): node for node in nodes if node.get("id")}
    errors: list[str] = []
    warnings: list[str] = []
    seen_edges: set[tuple[Any, Any, Any, Any]] = set()
    adjacency = {node_id: [] for node_id in node_map}

    for edge in edges:
        source_id = edge.get("source")
        target_id = edge.get("target")
        source_node = node_map.get(source_id)
        target_node = node_map.get(target_id)

        if not source_node:
            errors.append("Edge starts from a missing source node.")
            continue
        if not target_node:
            errors.append("Edge points to a missing target node.")
            continue
        if target_node.get("type") in SOURCE_NODE_TYPES:
            errors.append("Start or trigger nodes cannot have incoming edges.")
        if source_node.get("type") in TERMINAL_NODE_TYPES:
            errors.append("Answer nodes cannot have outgoing edges.")

        key = (
            source_id,
            edge.get("sourceHandle") or "",
            target_id,
            edge.get("targetHandle") or "",
        )
        if key in seen_edges:
            warnings.append(
                f"Duplicate edge: {_node_title(source_node)} -> {_node_title(target_node)}"
            )
        else:
            seen_edges.add(key)
        adjacency.setdefault(source_id, []).append(target_id)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> str | None:
        if node_id in visiting:
            return node_id
        if node_id in visited:
            return None
        visiting.add(node_id)
        for next_node_id in adjacency.get(node_id, []):
            cycle_id = visit(next_node_id)
            if cycle_id:
                return cycle_id
        visiting.remove(node_id)
        visited.add(node_id)
        return None

    for node_id in node_map:
        cycle_node_id = visit(node_id)
        if cycle_node_id:
            errors.append(f"Workflow graph has a cycle near node {cycle_node_id}.")
            break

    return errors, warnings


def _find_node(nodes: list[dict[str, Any]], node_id: str | None):
    if not node_id:
        return None
    return next((node for node in nodes if node.get("id") == node_id), None)


def _incoming_edges(edges: list[dict[str, Any]], node_id: str) -> list[dict[str, Any]]:
    return [edge for edge in edges if edge.get("target") == node_id]


def _outgoing_edges(edges: list[dict[str, Any]], node_id: str) -> list[dict[str, Any]]:
    return [edge for edge in edges if edge.get("source") == node_id]


def _descendant_node_ids(start_node_id: str, edges: list[dict[str, Any]]) -> set[str]:
    descendants: set[str] = set()
    stack = [edge.get("target") for edge in edges if edge.get("source") == start_node_id]

    while stack:
        node_id = stack.pop()
        if not node_id or node_id in descendants:
            continue
        descendants.add(str(node_id))
        stack.extend(
            edge.get("target") for edge in edges if edge.get("source") == node_id
        )

    return descendants


def _position_between(
    source_nodes: list[dict[str, Any]],
    target_node: dict[str, Any],
    fallback_direction: Literal["before", "after"],
) -> dict[str, float]:
    target_position = target_node.get("position") or {}
    target_x = float(target_position.get("x") or 0)
    target_y = float(target_position.get("y") or NODE_Y)

    if source_nodes:
        source_x_values = [
            float((node.get("position") or {}).get("x") or target_x)
            for node in source_nodes
        ]
        source_y_values = [
            float((node.get("position") or {}).get("y") or target_y)
            for node in source_nodes
        ]
        source_x = sum(source_x_values) / len(source_x_values)
        source_y = sum(source_y_values) / len(source_y_values)
        return {"x": (source_x + target_x) / 2, "y": (source_y + target_y) / 2}

    offset = -NODE_X_GAP if fallback_direction == "before" else NODE_X_GAP
    return {"x": target_x + offset, "y": target_y}


def _insert_position(prompt: str, selected_node: dict[str, Any]) -> Literal["before", "after"]:
    normalized = prompt.lower()
    node_type = selected_node.get("type")

    if node_type in SOURCE_NODE_TYPES:
        return "after"
    if node_type in TERMINAL_NODE_TYPES:
        return "before"
    if _includes_any(
        normalized,
        ["before", "previous", "upstream", "\uc55e", "\uc774\uc804", "\uc804\uc5d0"],
    ):
        return "before"
    if _includes_any(
        normalized,
        ["after", "next", "downstream", "\ub4a4", "\ub2e4\uc74c", "\uc774\ud6c4"],
    ):
        return "after"
    if _wants_guardrail(normalized):
        return "before"
    return "after"


def _should_rewrite_from_selected(prompt: str) -> bool:
    normalized = prompt.lower()
    return _includes_any(
        normalized,
        [
            "from this node",
            "from selected node",
            "replace downstream",
            "rewrite downstream",
            "\uc774 \ub178\ub4dc\ubd80\ud130",
            "\uc120\ud0dd\ud55c \ub178\ub4dc\ubd80\ud130",
            "\ub2e4\uc74c\ubd80\ud130",
            "\ubd80\ud130 \ubc14\uafd4",
        ],
    )


def _action_exists_downstream(
    action: str,
    selected_node_id: str,
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> bool:
    node_type = ACTION_NODE_TYPES.get(action)
    if not node_type:
        return False
    descendants = _descendant_node_ids(selected_node_id, edges)
    return any(
        node.get("id") in descendants and node.get("type") == node_type for node in nodes
    )


def _edit_actions(
    prompt: str,
    plan: BuilderPlan,
    selected_node: dict[str, Any],
    graph: dict[str, Any],
    rewrite_downstream: bool,
) -> list[str]:
    normalized = prompt.lower()
    if _wants_guardrail(normalized) or "guardrail" in plan.actions:
        return ["guardrail"]

    selected_type = selected_node.get("type")
    actions: list[str] = []
    for action in plan.actions:
        if action == "knowledge":
            continue
        if ACTION_NODE_TYPES.get(action) == selected_type:
            continue
        if not rewrite_downstream and _action_exists_downstream(
            action,
            str(selected_node.get("id")),
            graph.get("nodes") or [],
            graph.get("edges") or [],
        ):
            continue
        actions.append(action)

    return _unique(actions)


def _build_action_nodes(
    actions: list[str],
    prompt: str,
    base_id: str,
    start_position: dict[str, float],
    input_selector: list[str],
    missing_fields: list[str],
    warnings: list[str],
    selected_nodes: list[dict[str, str]],
    demo_knowledge_base: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    action_nodes: list[dict[str, Any]] = []
    with_knowledge = "knowledge" in actions or _includes_any(
        prompt.lower(),
        [
            "knowledge",
            "kb",
            "wiki",
            "rag",
            "document",
            "\ubb38\uc11c",
            "\uc704\ud0a4",
            "\uc9c0\uc2dd",
            "\uac80\uc0c9",
        ],
    )
    offset = 0

    def next_position() -> dict[str, float]:
        nonlocal offset
        position = {"x": start_position["x"] + offset * NODE_X_GAP, "y": start_position["y"]}
        offset += 1
        return position

    def push_node(node: dict[str, Any], reason: str) -> None:
        action_nodes.append(node)
        selected_nodes.append(
            {
                "id": node["id"],
                "type": node.get("type") or "unknown",
                "title": _node_title(node),
                "reason": reason,
            }
        )

    for action in actions:
        if action == "knowledge":
            if not _demo_knowledge_bases(prompt, True, demo_knowledge_base):
                _add_missing_field(missing_fields, "Knowledge base selection")
            continue
        if action == "github":
            push_node(_github_node(base_id, next_position()), "GitHub data is required.")
            _add_missing_field(missing_fields, "GitHub repository and PR number")
            continue
        if action == "mail":
            push_node(_mail_node(base_id, next_position()), "Mail search was requested.")
            _add_missing_field(missing_fields, "Mail account connection")
            continue
        if action == "http":
            push_node(_http_node(base_id, next_position()), "External API call was requested.")
            _add_missing_field(missing_fields, "HTTP URL and authentication")
            continue
        if action == "guardrail":
            push_node(
                _guardrail_node(base_id, next_position(), prompt, input_selector),
                "이 지점에서 텍스트 검사 또는 정제가 필요합니다.",
            )
            warnings.append(
                "가드레일 노드는 현재 설정된 조건에 따라 텍스트를 검사하거나 분기합니다."
            )
            continue
        if action == "llm":
            push_node(
                _llm_node(
                    base_id,
                    next_position(),
                    prompt,
                    with_knowledge,
                    demo_knowledge_base,
                ),
                "LLM node can transform or summarize the selected path.",
            )
            continue
        if action == "template":
            push_node(_template_node(base_id, next_position()), "Template node can format output.")
            continue
        if action == "slack":
            previous_node = action_nodes[-1] if action_nodes else None
            selector = _primary_output_selector(previous_node) if previous_node else input_selector
            push_node(
                _slack_node(base_id, next_position(), selector),
                "Slack 채널로 앞 단계 응답을 전송합니다.",
            )
            if not _has_demo_slack_bot_token():
                _add_missing_field(missing_fields, "Slack bot token connection")
            continue
        if action == "answer":
            push_node(_answer_node(base_id, next_position()), "Answer node exposes final output.")

    return action_nodes


def _chain_new_nodes(
    edges: list[dict[str, Any]],
    action_nodes: list[dict[str, Any]],
) -> None:
    for index in range(0, max(len(action_nodes) - 1, 0)):
        edges.append(
            _edge(action_nodes[index]["id"], action_nodes[index + 1]["id"], len(edges))
        )


def _build_no_selection_response(graph: dict[str, Any]) -> dict[str, Any]:
    return {
        "status": "needs_input",
        "mode": "heuristic",
        "message": "Select a node to edit, or explicitly ask to create a new workflow.",
        "graph_preview": None,
        "selected_nodes": [],
        "missing_fields": [],
        "questions": [
            "Which existing node should the agent edit from?",
            "If you want a full replacement, say 'create a new workflow' or 'replace this workflow'.",
        ],
        "validation_errors": [],
        "validation_warnings": [],
        "warnings": [],
    }


def _build_selected_node_edit(
    prompt: str,
    graph: dict[str, Any],
    plan: BuilderPlan,
    selected_node_id: str,
    demo_knowledge_base: dict[str, str] | None = None,
) -> dict[str, Any]:
    nodes = deepcopy(graph.get("nodes") or [])
    edges = deepcopy(graph.get("edges") or [])
    original_node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    selected_node = _find_node(nodes, selected_node_id)
    if not selected_node:
        return {
            **_build_no_selection_response(graph),
            "message": "The selected node was not found in the current workflow.",
            "questions": ["Select an existing node and try again."],
        }

    selected_nodes = [
        {
            "id": selected_node["id"],
            "type": selected_node.get("type") or "unknown",
            "title": _node_title(selected_node),
            "reason": "Selected as the edit anchor.",
        }
    ]
    missing_fields = list(plan.missing_fields)
    questions = list(plan.questions)
    warnings: list[str] = []
    rewrite_downstream = _should_rewrite_from_selected(prompt)
    actions = _edit_actions(prompt, plan, selected_node, graph, rewrite_downstream)

    if "knowledge" in plan.actions and not _demo_knowledge_bases(
        prompt,
        True,
        demo_knowledge_base,
    ):
        _add_missing_field(missing_fields, "Knowledge base selection")

    if not actions:
        return {
            "status": "needs_input",
            "mode": "heuristic",
            "message": "No supported structural edit was detected for the selected node.",
            "graph_preview": None,
            "selected_nodes": selected_nodes,
            "missing_fields": _unique(missing_fields),
            "questions": _unique(
                questions
                + [
                    "Should the agent insert a node before/after the selected node, or replace the downstream path?"
                ]
            ),
            "validation_errors": [],
            "validation_warnings": [],
            "warnings": warnings,
        }

    base_id = f"agent-{uuid4().hex[:8]}"
    node_map = {node.get("id"): node for node in nodes}
    position_mode = _insert_position(prompt, selected_node)
    incoming = _incoming_edges(edges, selected_node_id)
    outgoing = _outgoing_edges(edges, selected_node_id)

    if rewrite_downstream:
        if selected_node.get("type") in TERMINAL_NODE_TYPES:
            questions.append("Answer nodes cannot be used as the start of a downstream rewrite.")
            return {
                **_build_no_selection_response(graph),
                "message": "Selected node cannot start a downstream rewrite.",
                "selected_nodes": selected_nodes,
                "questions": _unique(questions),
            }
        descendants = _descendant_node_ids(selected_node_id, edges)
        nodes = [node for node in nodes if node.get("id") not in descendants]
        edges = [
            edge
            for edge in edges
            if edge.get("source") not in descendants
            and edge.get("target") not in descendants
            and edge.get("source") != selected_node_id
        ]
        start_position = _position_between([], selected_node, "after")
        input_selector = _primary_output_selector(selected_node)
        action_nodes = _build_action_nodes(
            actions,
            prompt,
            base_id,
            start_position,
            input_selector,
            missing_fields,
            warnings,
            selected_nodes,
            demo_knowledge_base,
        )
        nodes.extend(action_nodes)
        if action_nodes:
            edges.append(_edge(selected_node_id, action_nodes[0]["id"], len(edges)))
            _chain_new_nodes(edges, action_nodes)
    elif position_mode == "before":
        source_nodes = [
            node_map.get(edge.get("source"))
            for edge in incoming
            if node_map.get(edge.get("source"))
        ]
        start_position = _position_between(source_nodes, selected_node, "before")
        input_selector = (
            _primary_output_selector(source_nodes[0]) if source_nodes else []
        )
        action_nodes = _build_action_nodes(
            actions,
            prompt,
            base_id,
            start_position,
            input_selector,
            missing_fields,
            warnings,
            selected_nodes,
            demo_knowledge_base,
        )
        nodes.extend(action_nodes)
        if action_nodes:
            edges = [edge for edge in edges if edge.get("target") != selected_node_id]
            for incoming_edge in incoming:
                edges.append(
                    {
                        **incoming_edge,
                        "id": f"agent-edge-{incoming_edge.get('source')}-{action_nodes[0]['id']}-{len(edges)}",
                        "target": action_nodes[0]["id"],
                        "targetHandle": "target",
                    }
                )
            _chain_new_nodes(edges, action_nodes)
            edges.append(_edge(action_nodes[-1]["id"], selected_node_id, len(edges)))
    else:
        target_nodes = [
            node_map.get(edge.get("target"))
            for edge in outgoing
            if node_map.get(edge.get("target"))
        ]
        start_position = _position_between(target_nodes, selected_node, "after")
        input_selector = _primary_output_selector(selected_node)
        action_nodes = _build_action_nodes(
            actions,
            prompt,
            base_id,
            start_position,
            input_selector,
            missing_fields,
            warnings,
            selected_nodes,
            demo_knowledge_base,
        )
        nodes.extend(action_nodes)
        if action_nodes:
            edges = [edge for edge in edges if edge.get("source") != selected_node_id]
            edges.append(_edge(selected_node_id, action_nodes[0]["id"], len(edges)))
            _chain_new_nodes(edges, action_nodes)
            for outgoing_edge in outgoing:
                edges.append(
                    {
                        **outgoing_edge,
                        "id": f"agent-edge-{action_nodes[-1]['id']}-{outgoing_edge.get('target')}-{len(edges)}",
                        "source": action_nodes[-1]["id"],
                        "sourceHandle": "source",
                    }
                )

    new_node_ids = {
        str(node.get("id"))
        for node in nodes
        if node.get("id") and str(node.get("id")) not in original_node_ids
    }
    _ensure_guardrail_branch_outputs(
        nodes,
        edges,
        selected_nodes,
        missing_fields,
        new_node_ids,
    )

    graph_preview = {"nodes": nodes, "edges": edges, "viewport": graph["viewport"]}
    validation_errors, validation_warnings = _validate_graph(graph_preview)
    status: WorkflowBuilderStatus
    if validation_errors:
        status = "invalid"
    elif missing_fields or questions:
        status = "needs_input"
    else:
        status = "ready"

    return {
        "status": status,
        "mode": "heuristic",
        "message": (
            "Rebuilt the downstream path from the selected node."
            if rewrite_downstream
            else "Created an edit preview around the selected node."
        ),
        "graph_preview": graph_preview,
        "selected_nodes": selected_nodes,
        "missing_fields": _unique(missing_fields),
        "questions": _unique(questions),
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "warnings": _unique(warnings),
    }


def build_workflow_draft(
    prompt: str,
    current_graph: dict[str, Any] | None = None,
    planner_result: dict[str, Any] | None = None,
    selected_node_id: str | None = None,
    demo_knowledge_base: dict[str, str] | None = None,
) -> dict[str, Any]:
    graph = _graph_from_request(current_graph)
    plan = _sanitize_plan(prompt, planner_result)
    replace_graph = _should_replace_graph(prompt.lower(), graph)

    if not replace_graph and selected_node_id:
        return _build_selected_node_edit(
            prompt,
            graph,
            plan,
            selected_node_id,
            demo_knowledge_base,
        )

    if not replace_graph and graph["nodes"]:
        return _build_no_selection_response(graph)

    base_id = f"agent-{uuid4().hex[:8]}"
    action_nodes: list[dict[str, Any]] = []
    selected_nodes: list[dict[str, str]] = []
    missing_fields = list(plan.missing_fields)
    questions = list(plan.questions)
    warnings: list[str] = []
    with_knowledge = "knowledge" in plan.actions
    trigger_type = plan.trigger if replace_graph else "existing"
    start_position = (
        {"x": 240, "y": NODE_Y} if replace_graph else _append_position(graph["nodes"])
    )

    def push_node(node: dict[str, Any], reason: str) -> None:
        action_nodes.append(node)
        selected_nodes.append(
            {
                "id": node["id"],
                "type": node.get("type") or "unknown",
                "title": _node_title(node),
                "reason": reason,
            }
        )

    if replace_graph:
        if trigger_type == "jira":
            push_node(
                _webhook_node(base_id, start_position, "jira"),
                "Jira issue events need a webhook trigger.",
            )
            _add_missing_field(missing_fields, "Jira webhook payload mapping")
        elif trigger_type == "schedule":
            push_node(
                _schedule_node(base_id, start_position),
                "Scheduled workflows need a cron trigger.",
            )
        else:
            push_node(
                _start_node(base_id, start_position),
                "Manual input is the default safe trigger.",
            )

    action_start_x = start_position["x"] + NODE_X_GAP if replace_graph else start_position["x"]
    offset = 0

    def next_position() -> dict[str, float]:
        nonlocal offset
        position = {"x": action_start_x + offset * NODE_X_GAP, "y": start_position["y"]}
        offset += 1
        return position

    for action in plan.actions:
        if action == "knowledge":
            if not _demo_knowledge_bases(prompt, True, demo_knowledge_base):
                _add_missing_field(missing_fields, "Knowledge base selection")
            continue
        if action == "github":
            push_node(_github_node(base_id, next_position()), "GitHub data is required.")
            _add_missing_field(missing_fields, "GitHub repository and PR number")
            continue
        if action == "mail":
            push_node(_mail_node(base_id, next_position()), "Mail search was requested.")
            _add_missing_field(missing_fields, "Mail account connection")
            continue
        if action == "http":
            push_node(
                _http_node(base_id, next_position()),
                "External API call was requested.",
            )
            _add_missing_field(missing_fields, "HTTP URL and authentication")
            continue
        if action == "guardrail":
            previous_node = action_nodes[-1] if action_nodes else None
            push_node(
                _guardrail_node(
                    base_id,
                    next_position(),
                    prompt,
                    _primary_output_selector(previous_node),
                ),
                "가드레일은 다음 단계 전에 텍스트를 검사하거나 정제합니다.",
            )
            warnings.append(
                "가드레일 노드는 현재 설정된 조건에 따라 텍스트를 검사하거나 분기합니다."
            )
            continue
        if action == "llm":
            push_node(
                _llm_node(
                    base_id,
                    next_position(),
                    prompt,
                    with_knowledge,
                    demo_knowledge_base,
                ),
                "LLM node can combine retrieved knowledge with the request."
                if with_knowledge
                else "LLM node can transform the request into a response.",
            )
            continue
        if action == "template":
            push_node(
                _template_node(base_id, next_position()),
                "Template node can format the final message.",
            )
            continue
        if action == "slack":
            previous_node = action_nodes[-1] if action_nodes else None
            selector = _primary_output_selector(previous_node) if previous_node else []
            push_node(
                _slack_node(base_id, next_position(), selector),
                "Slack 채널로 앞 단계 응답을 전송합니다.",
            )
            if not _has_demo_slack_bot_token():
                _add_missing_field(missing_fields, "Slack bot token connection")
            continue
        if action == "answer":
            push_node(_answer_node(base_id, next_position()), "Answer node exposes final output.")

    if not any(
        node.get("type") in {"answerNode", "slackPostNode"} for node in action_nodes
    ):
        push_node(
            _answer_node(base_id, next_position()),
            "Terminal answer keeps the draft executable.",
        )

    previous_nodes = [] if replace_graph else graph["nodes"]
    previous_edges = [] if replace_graph else graph["edges"]
    original_node_ids = {
        str(node.get("id")) for node in previous_nodes if node.get("id")
    }
    nodes = [*previous_nodes, *action_nodes]
    edges = [*previous_edges]
    first_new_node = action_nodes[0] if action_nodes else None
    tail_node = None if replace_graph else _tail_node(graph["nodes"], graph["edges"])

    if not replace_graph and tail_node and first_new_node:
        edges.append(_edge(tail_node["id"], first_new_node["id"], len(edges)))
    elif not replace_graph and not tail_node and first_new_node:
        questions.append("Where should the new workflow branch connect from?")

    start_index = 0 if replace_graph else len(previous_nodes)
    for index in range(start_index, max(len(nodes) - 1, 0)):
        source = nodes[index]
        target = nodes[index + 1]
        if target.get("type") in SOURCE_NODE_TYPES:
            continue
        if source.get("type") in TERMINAL_NODE_TYPES:
            continue
        edges.append(_edge(source["id"], target["id"], len(edges)))

    new_node_ids = {
        str(node.get("id"))
        for node in nodes
        if node.get("id") and str(node.get("id")) not in original_node_ids
    }
    _ensure_guardrail_branch_outputs(
        nodes,
        edges,
        selected_nodes,
        missing_fields,
        new_node_ids,
    )

    graph_preview = {"nodes": nodes, "edges": edges, "viewport": graph["viewport"]}
    validation_errors, validation_warnings = _validate_graph(graph_preview)
    status: WorkflowBuilderStatus
    if validation_errors:
        status = "invalid"
    elif missing_fields or questions:
        status = "needs_input"
    else:
        status = "ready"

    return {
        "status": status,
        "mode": "heuristic",
        "message": plan.message
        or (
            "Created a workflow draft from the request."
            if replace_graph
            else "Created a workflow edit draft from the request."
        ),
        "graph_preview": graph_preview,
        "selected_nodes": selected_nodes,
        "missing_fields": _unique(missing_fields),
        "questions": _unique(questions),
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings,
        "warnings": _unique(warnings),
    }


def _strip_json_fence(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\s*```$", "", value)
    return value.strip()


def _safe_node_summary(nodes: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "id": str(node.get("id") or ""),
            "type": str(node.get("type") or ""),
            "title": str((node.get("data") or {}).get("title") or node.get("type") or ""),
        }
        for node in nodes[:40]
    ]


async def create_openai_plan(
    prompt: str,
    current_nodes: list[dict[str, Any]],
    selected_node_id: str | None = None,
) -> dict[str, Any]:
    if not settings.OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    payload = {
        "model": settings.OPENAI_MODEL,
        "temperature": 0.1,
        "response_format": {"type": "json_object"},
        "messages": [
            {
                "role": "system",
                "content": (
                    "You convert workflow requests into compact JSON plans. "
                    "Allowed trigger values: manual, jira, schedule, existing. "
                    "Allowed actions: github, mail, http, knowledge, guardrail, llm, template, slack, answer. "
                    "Return only JSON with keys: trigger, actions, missing_fields, questions, message. "
                    "Do not include credentials, secrets, raw tokens, or webhook URLs."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "request": prompt,
                        "current_graph_nodes": _safe_node_summary(current_nodes),
                        "selected_node_id": selected_node_id,
                    }
                ),
            },
        ],
    }
    headers = {
        "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            OPENAI_CHAT_COMPLETIONS_URL, headers=headers, json=payload
        )
    response.raise_for_status()
    data = response.json()
    content = data.get("choices", [{}])[0].get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        raise RuntimeError("OpenAI planner returned an empty response.")
    parsed = json.loads(_strip_json_fence(content))
    return parsed if isinstance(parsed, dict) else {}


async def build_workflow_agent_response(
    prompt: str,
    current_graph: dict[str, Any] | None = None,
    selected_node_id: str | None = None,
    demo_knowledge_base: dict[str, str] | None = None,
) -> dict[str, Any]:
    graph = _graph_from_request(current_graph)
    if (
        not selected_node_id
        and not _should_replace_graph(prompt.lower(), graph)
        and graph["nodes"]
    ):
        return _build_no_selection_response(graph)

    if not settings.OPENAI_API_KEY:
        response = build_workflow_draft(
            prompt,
            graph,
            selected_node_id=selected_node_id,
            demo_knowledge_base=demo_knowledge_base,
        )
        response["warnings"].append(
            "OPENAI_API_KEY is not configured. Used the local heuristic planner."
        )
        return response

    try:
        plan = await create_openai_plan(prompt, graph["nodes"], selected_node_id)
        response = build_workflow_draft(
            prompt,
            graph,
            plan,
            selected_node_id=selected_node_id,
            demo_knowledge_base=demo_knowledge_base,
        )
        response["mode"] = "openai"
        return response
    except Exception as exc:
        response = build_workflow_draft(
            prompt,
            graph,
            selected_node_id=selected_node_id,
            demo_knowledge_base=demo_knowledge_base,
        )
        response["warnings"].append(
            f"{exc.__class__.__name__}: OpenAI planner failed. Used the local heuristic planner."
        )
        return response
