import copy
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import or_
from sqlalchemy.orm import Session

from apps.gateway.auth.permissions import ensure_workflow_permission
from apps.gateway.services.app_service import AppService
from apps.gateway.services.agent_builder_intent_service import (
    AgentBuilderIntentExtraction,
    AgentBuilderIntentExtractionError,
    AgentBuilderIntentExtractor,
    AgentBuilderIntentRuntimeUnavailableError,
)
from apps.gateway.services.audit_records import add_action_audit
from apps.gateway.services.knowledge_rag_recommendation_service import (
    KnowledgeRAGRecommendationService,
)
from apps.gateway.services.llm_service import LLMService
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
    AgentBuilderEditOperation,
    AgentBuilderEditTargetReference,
    AgentBuilderKnowledgeRequirement,
    AgentBuilderMessageRequest,
    AgentBuilderMessageResponse,
    AgentBuilderMissingParameter,
    AgentBuilderNodeConfigurationIssue,
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
from apps.shared.services.workflow_layout import calculate_workflow_auto_layout
from apps.shared.services.workflow_node_catalog import (
    agent_builder_supported_capabilities,
    agent_builder_supported_node_types,
    node_definition,
    node_type_for_capability,
)
from apps.shared.services.permission_audit import record_resource_permission_denied


SESSION_TTL = timedelta(hours=24)
DRAFT_TTL = timedelta(minutes=30)
AGENT_BUILDER_SUPPORTED_NODE_TYPES = agent_builder_supported_node_types()
AGENT_BUILDER_SUPPORTED_CAPABILITIES = agent_builder_supported_capabilities()
NO_KB_CANDIDATE_ID = "__agent_builder_no_kb__"
NO_KB_CANDIDATE_LABEL = "Knowledge Base 없이 생성"
NO_KB_CANDIDATE_WARNING = (
    "사용자가 Knowledge Base 없이 도안 생성을 선택했습니다. LLM node는 Knowledge Base binding 없이 생성됩니다."
)
AGENT_BUILDER_KB_RECOMMENDATION_LIMIT = 20
SAFE_SIDE_EFFECT_NOTICE = (
    "초안 생성, 미리보기, 적용 및 저장 중에는 workflow 실행, Knowledge Base 검색, "
    "Slack/GitHub/HTTP/Mail 외부 호출, workflow node credential 사용/변경, "
    "외부 시스템 변경을 수행하지 않습니다."
)
SLACK_CHANNEL_UNRESOLVED_WARNING = (
    "Slack 채널이 아직 선택되지 않아 Slack node는 채널 미정 상태로 생성됩니다. "
    "저장 후 실행 전에 Slack 채널과 credential 참조를 확인해야 합니다."
)
GITHUB_CONFIGURATION_UNRESOLVED_WARNING = (
    "GitHub credential과 repository와 PR 대상이 설정되지 않아 GitHub node는 미설정 상태로 생성됩니다. "
    "저장 후 실행 전에 GitHub credential, repository, PR 번호를 확인해야 합니다."
)
EXTERNAL_NODE_CONFIGURATION_WARNING = (
    "외부 연동 node의 credential과 target 설정은 자동으로 채우지 않았습니다. "
    "저장 후 실제 실행 전에 미설정 항목을 확인해야 합니다."
)
CAPABILITY_GENERATION_ORDER = (
    "file_extraction",
    "variable_extraction",
    "github_pr_read",
    "mail_search",
    "http_request",
    "workflow_call",
    "code_execution",
    "template_render",
    "condition",
    "loop",
    "llm",
    "knowledge_backed_llm",
    "github_pr_comment",
    "slack_send",
    "answer",
)
CAPABILITY_STEP_IDS = {
    "file_extraction": "step_file_extraction",
    "variable_extraction": "step_variable_extraction",
    "github_pr_read": "step_github_read",
    "mail_search": "step_mail",
    "http_request": "step_http",
    "workflow_call": "step_workflow",
    "code_execution": "step_code",
    "template_render": "step_template",
    "condition": "step_condition",
    "loop": "step_loop",
    "llm": "step_llm",
    "knowledge_backed_llm": "step_llm",
    "github_pr_comment": "step_github_comment",
    "slack_send": "step_slack",
    "answer": "step_answer",
}
CAPABILITY_NODE_PREFIXES = {
    "file_extraction": "agent-file-extraction",
    "variable_extraction": "agent-variable-extraction",
    "github_pr_read": "agent-github-read",
    "mail_search": "agent-mail",
    "http_request": "agent-http",
    "workflow_call": "agent-workflow",
    "code_execution": "agent-code",
    "template_render": "agent-template",
    "condition": "agent-condition",
    "loop": "agent-loop",
    "llm": "agent-llm",
    "knowledge_backed_llm": "agent-llm",
    "github_pr_comment": "agent-github-comment",
    "slack_send": "agent-slack",
    "answer": "agent-answer",
}
CAPABILITY_OUTPUT_KEYS = {
    "start_input": "question",
    "webhook_trigger": "payload",
    "schedule_trigger": "triggered_at",
    "file_extraction": "text",
    "variable_extraction": "result",
    "github_pr_read": "files",
    "mail_search": "emails",
    "http_request": "data",
    "workflow_call": "result",
    "code_execution": "result",
    "template_render": "text",
    "condition": "result",
    "loop": "results",
    "llm": "text",
    "knowledge_backed_llm": "text",
    "github_pr_comment": "comment_url",
    "slack_send": "data",
    "answer": "answer",
}
CAPABILITY_PURPOSES = {
    "start_input": "사용자 입력을 받습니다.",
    "webhook_trigger": "Webhook payload를 받습니다.",
    "schedule_trigger": "설정된 일정에 따라 workflow를 시작합니다.",
    "file_extraction": "입력 파일에서 텍스트를 추출합니다.",
    "variable_extraction": "입력 데이터에서 필요한 변수를 추출합니다.",
    "github_pr_read": "GitHub Pull Request와 변경 파일을 조회합니다.",
    "mail_search": "메일을 검색합니다.",
    "http_request": "외부 HTTP API를 호출합니다.",
    "workflow_call": "다른 workflow를 호출합니다.",
    "code_execution": "sandbox에서 코드를 실행합니다.",
    "template_render": "입력값으로 템플릿을 렌더링합니다.",
    "condition": "조건에 따라 흐름을 분기합니다.",
    "loop": "목록의 각 항목을 반복 처리합니다.",
    "llm": "입력을 분석하고 결과를 생성합니다.",
    "knowledge_backed_llm": "Knowledge Base 근거로 입력을 분석하고 결과를 생성합니다.",
    "github_pr_comment": "생성한 내용을 GitHub Pull Request 댓글로 등록합니다.",
    "slack_send": "이전 단계 결과를 Slack 메시지로 전송합니다.",
    "answer": "이전 단계 결과를 응답으로 반환합니다.",
}
CAPABILITY_NODE_ACTIONS = {
    "github_pr_read": "get_pr",
    "github_pr_comment": "comment_pr",
}
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
TARGETED_MODIFY_INTENT_RE = re.compile(
    r"(여기|이\s*노드|선택한\s*노드|현재\s*workflow|현재\s*워크플로우|기존\s*workflow|"
    r"기존\s*워크플로우|뒤에|앞에|사이에|이\s*연결|연결\s*사이|insert|"
    r"between|after|before|modify\s+this|update\s+current)",
    re.IGNORECASE,
)
NEW_WORKFLOW_INTENT_RE = re.compile(
    r"(새\s*workflow|새\s*워크플로우|새로\s*(?:만들|생성)|"
    r"처음부터|new\s+workflow|create\s+(?:a\s+)?new\s+workflow)",
    re.IGNORECASE,
)
WORKFLOW_REQUEST_INTENT_RE = re.compile(
    r"(workflow|워크플로우|플로우|로직|자동화|노드|node|입력|출력|input|output|"
    r"llm|slack|슬랙|knowledge|kb|rag|전송|보내|요약|분석|답변|찾아|검색)",
    re.IGNORECASE,
)
WORKFLOW_BUILD_ACTION_RE = re.compile(
    r"(만들|생성|작성|구성|설계|추가|연결|붙여|자동|보내|전송|요약|분석|답변|"
    r"찾아|검색|리뷰(?:해|하)|등록(?:해|하)|create|build|make|generate|add|connect|"
    r"send|summari[sz]e|analy[sz]e)",
    re.IGNORECASE,
)
SIMPLE_INPUT_OUTPUT_RE = re.compile(
    r"((입력|input)\s*(?:-|→|->|에서|을|를)?\s*(출력|output))|"
    r"((출력|output)\s*(?:-|←|<-)?\s*(입력|input))",
    re.IGNORECASE,
)
WEBHOOK_TRIGGER_RE = re.compile(r"(webhook|web\s*hook|웹\s*훅)", re.IGNORECASE)
KOREAN_NODE_INSERT_RE = re.compile(
    r"(?P<target>.+?)\s*(?P<placement>뒤에|다음에|후에|앞에|이전에|전에)"
    r"\s*(?P<new_steps>.+?)\s*(?:추가|삽입|넣|붙)",
    re.IGNORECASE,
)
KOREAN_EDGE_INSERT_RE = re.compile(
    r"(?:사이에|연결에)\s*(?P<new_steps>.+?)\s*(?:추가|삽입|넣|붙)",
    re.IGNORECASE,
)
ENGLISH_NODE_INSERT_RE = re.compile(
    r"(?:add|insert)\s+(?P<new_steps>.+?)\s+"
    r"(?P<placement>after|before)\s+(?P<target>.+?)(?:[.!?]|$)",
    re.IGNORECASE,
)
SAFE_TRIGGER_TYPES = {"manual", "schedule", "api", "webhook"}


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


def _message_requests_targeted_modify(message: str) -> bool:
    return bool(TARGETED_MODIFY_INTENT_RE.search(message or ""))


def _message_looks_like_workflow_request(message: str) -> bool:
    text = message or ""
    return bool(
        WORKFLOW_REQUEST_INTENT_RE.search(text)
        and WORKFLOW_BUILD_ACTION_RE.search(text)
    )


def _message_requests_simple_input_output(message: str) -> bool:
    return bool(SIMPLE_INPUT_OUTPUT_RE.search(message or ""))


def _message_requests_webhook_trigger(message: str) -> bool:
    return bool(WEBHOOK_TRIGGER_RE.search(message or ""))


def _extract_workflow_edit_spec(
    message: str,
    *,
    selected_edge_id: str | None,
) -> dict[str, str] | None:
    text = " ".join((message or "").split())
    match = KOREAN_NODE_INSERT_RE.search(text)
    if match:
        placement_token = match.group("placement")
        placement = "after" if placement_token in {"뒤에", "다음에", "후에"} else "before"
        target_text = match.group("target").strip()
        normalized_target = target_text.casefold()
        reference_type = (
            "selected_node"
            if any(
                token in normalized_target
                for token in ("선택한", "이 노드", "여기", "현재 노드")
            )
            else "natural_language_node"
        )
        return {
            "placement": placement,
            "target_text": target_text,
            "new_steps_text": match.group("new_steps").strip(),
            "reference_type": reference_type,
        }

    match = ENGLISH_NODE_INSERT_RE.search(text)
    if match:
        target_text = match.group("target").strip()
        reference_type = (
            "selected_node"
            if re.search(r"\b(?:this|selected|current)\s+node\b", target_text, re.I)
            else "natural_language_node"
        )
        return {
            "placement": match.group("placement").casefold(),
            "target_text": target_text,
            "new_steps_text": match.group("new_steps").strip(),
            "reference_type": reference_type,
        }

    if selected_edge_id and _message_mentions_edge_context(text):
        edge_match = KOREAN_EDGE_INSERT_RE.search(text)
        return {
            "placement": "between",
            "target_text": "selected edge",
            "new_steps_text": (
                edge_match.group("new_steps").strip() if edge_match else text
            ),
            "reference_type": "selected_edge",
        }
    return None


def _message_requests_llm_processing(message: str) -> bool:
    text = (message or "").casefold()
    return any(
        token in text
        for token in (
            "llm",
            " ai ",
            "챗봇",
            "답변",
            "분석",
            "요약",
            "리뷰",
            "review",
            "analyze",
            "analyse",
            "summarize",
        )
    )


def _message_requested_catalog_capabilities(message: str) -> list[str]:
    text = (message or "").casefold()
    requested: list[str] = []

    def add(capability: str) -> None:
        if (
            capability in AGENT_BUILDER_SUPPORTED_CAPABILITIES
            and capability not in requested
        ):
            requested.append(capability)

    if _message_requests_webhook_trigger(message):
        add("webhook_trigger")
    if any(token in text for token in ("schedule", "cron", "스케줄", "예약 실행")):
        add("schedule_trigger")
    if any(
        token in text
        for token in ("서브 워크플로우", "하위 워크플로우", "sub workflow", "subworkflow")
    ):
        add("workflow_call")
    if any(token in text for token in ("python", "파이썬", "코드 실행", "스크립트 실행")):
        add("code_execution")
    if any(token in text for token in ("조건 분기", "조건문", "if/else", "condition")):
        add("condition")
    if any(token in text for token in ("파일 추출", "문서 추출", "file extraction")):
        add("file_extraction")
    if any(token in text for token in ("변수 추출", "json 추출", "variable extraction")):
        add("variable_extraction")
    if any(token in text for token in ("반복", "루프", "loop")):
        add("loop")
    if any(token in text for token in ("http 요청", "http request", "rest api", "api 호출")):
        add("http_request")
    if any(token in text for token in ("slack", "슬랙")):
        add("slack_send")
    if any(token in text for token in ("template", "템플릿")):
        add("template_render")

    mentions_github = any(
        token in text for token in ("github", "깃허브", "pull request")
    ) or bool(re.search(r"\bpr\b", text, re.IGNORECASE))
    if mentions_github:
        add("github_pr_read")
        if any(
            token in text
            for token in (
                "댓글",
                "코멘트",
                "comment",
                "올리",
                "올려",
                "등록",
                "게시",
                "post",
            )
        ):
            add("github_pr_comment")

    if any(token in text for token in ("메일", "이메일", "email", "imap")):
        add("mail_search")
    if re.search(r"(?:응답|출력|answer)\s*(?:노드|node)", text, re.IGNORECASE):
        add("answer")
    if _message_requests_llm_processing(message):
        add("llm")
    return requested


def _target_node_types_for_text(
    target_text: str,
    target_capabilities: list[str],
) -> list[str]:
    node_types: list[str] = []
    for capability in target_capabilities:
        node_type = node_type_for_capability(capability)
        if node_type and node_type not in node_types:
            node_types.append(node_type)

    normalized_target = str(target_text or "").casefold()
    for node_type in sorted(AGENT_BUILDER_SUPPORTED_NODE_TYPES):
        if node_type in node_types:
            continue
        separated = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", node_type).casefold()
        semantic_tokens = [
            token
            for token in re.findall(r"[a-z0-9]+", separated)
            if token not in {"node", "trigger", "post"} and len(token) >= 3
        ]
        if semantic_tokens and any(token in normalized_target for token in semantic_tokens):
            node_types.append(node_type)
    return node_types


def _knowledge_query_topics(message: str) -> list[str]:
    safe_message = _safe_summary(message, limit=400)
    text = safe_message.lower()
    topics: list[str] = []

    def add(*values: str) -> None:
        for value in values:
            normalized = _safe_summary(value, limit=80)
            if normalized and normalized not in topics:
                topics.append(normalized)

    if any(token in text for token in ("사내 문서", "사내문서", "내부 문서", "내부문서")):
        add("사내 문서", "내부 문서", "문서 질의")
    if any(token in text for token in ("hr", "인사", "휴가", "복지", "온보딩")):
        add("인사", "복지", "온보딩")
    if any(token in text for token in ("재무", "정산", "회계", "finance")):
        add("재무", "정산")
    if any(token in text for token in ("계약", "contract")):
        add("계약")
    if any(token in text for token in ("정책", "규정", "내규", "policy")):
        add("정책", "규정")
    if any(token in text for token in ("문서", "자료", "근거", "document")):
        add("문서 질의")

    if not topics:
        add(safe_message[:80])
    return topics[:10]


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
        intent_extractor: AgentBuilderIntentExtractor | None = None,
    ) -> None:
        self.db = db
        self.user = user
        self.organization_id = organization_id
        self.intent_extractor = intent_extractor

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
            selected_kb_context = self._selected_knowledge_candidate_context(
                session,
                message_request,
                current_request_id=request_row.id,
            )
            if selected_kb_context and selected_kb_context.get("error"):
                issue = AgentBuilderValidationIssue(
                    code="KB_SELECTION_INVALID",
                    message="선택한 Knowledge Base 후보를 다시 확인할 수 없습니다.",
                    path="selected_knowledge_candidate",
                )
                response = AgentBuilderMessageResponse(
                    request_id=request_row.id,
                    status="validation_failed",
                    validation_result=AgentBuilderValidationResult(
                        valid=False,
                        issues=[issue],
                    ),
                    warnings=[SAFE_SIDE_EFFECT_NOTICE],
                )
                self._finish_request(request_row, response)
                self.db.commit()
                return response
            structured = (
                selected_kb_context["structured_request"]
                if selected_kb_context
                else self._structure_request(message_request, workflow)
            )
            effective_selected_edge_id = self._selected_edge_id_for_message(
                workflow,
                message_request.selected_edge_id,
                message_request.message,
            )
            target_resolution = self._resolve_edit_target(
                structured,
                workflow=workflow,
                selected_node_id=message_request.selected_node_id,
                selected_edge_id=effective_selected_edge_id,
            )
            if target_resolution["status"] == "clarification_required":
                response = AgentBuilderMessageResponse(
                    request_id=request_row.id,
                    status="clarification_required",
                    structured_request=structured,
                    clarification_questions=target_resolution.get("questions", []),
                    clarification_options=target_resolution.get("options", []),
                    validation_result=AgentBuilderValidationResult(
                        valid=False,
                        issues=[
                            AgentBuilderValidationIssue(
                                code="WORKFLOW_TARGET_UNRESOLVED",
                                message="기존 workflow 수정 대상을 확인해야 합니다.",
                                path="edit_operations.0.target",
                            )
                        ],
                    ),
                    warnings=[SAFE_SIDE_EFFECT_NOTICE],
                )
                self._finish_request(request_row, response)
                self.db.commit()
                return response
            validation = self._validate_structured_request(structured, app_id=app_id)
            recommendations = self._resolve_knowledge_requirements(
                structured,
                selected_candidate_handles=(
                    selected_kb_context["candidate_handles"]
                    if selected_kb_context
                    else None
                ),
            )
        except AgentBuilderIntentRuntimeUnavailableError:
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="configuration_required",
                validation_result=AgentBuilderValidationResult(
                    valid=False,
                    issues=[
                        AgentBuilderValidationIssue(
                            code="INTENT_MODEL_ROUTE_REQUIRED",
                            message="Agent Builder 요청 구조화에 사용할 LLM credential과 model route가 필요합니다.",
                            path="message",
                        )
                    ],
                ),
                warnings=[SAFE_SIDE_EFFECT_NOTICE],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response
        except AgentBuilderIntentExtractionError:
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="failed",
                validation_result=AgentBuilderValidationResult(
                    valid=False,
                    issues=[
                        AgentBuilderValidationIssue(
                            code="INTENT_EXTRACTION_FAILED",
                            message="Agent Builder가 요청을 안전한 workflow 구조로 변환하지 못했습니다.",
                            path="message",
                        )
                    ],
                ),
                warnings=[SAFE_SIDE_EFFECT_NOTICE],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response
        except Exception:
            return self._fail_processing_request(request_row)
        structured_warnings = self._structured_request_warnings(structured)
        draft_safety_notices = self._draft_safety_notices(structured)
        if structured.request_type == "unsupported":
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="unsupported",
                structured_request=structured,
                clarification_questions=[
                    "워크플로우로 만들 작업을 설명해주세요. 예: '입력값을 LLM으로 요약해 응답하는 workflow를 만들어줘'",
                    "기존 workflow에 추가하려면 '선택한 노드 뒤에' 또는 '이 연결 사이에'처럼 위치를 함께 알려주세요.",
                    "간단한 구조만 원하면 '입력 - 출력 노드를 만들어줘'처럼 노드 흐름을 적어주세요.",
                ],
                validation_result=validation,
                warnings=[SAFE_SIDE_EFFECT_NOTICE, *structured_warnings],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response
        if recommendations["status"] == "clarification_required":
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="clarification_required",
                structured_request=structured,
                clarification_questions=recommendations["questions"],
                clarification_options=recommendations.get("options", []),
                validation_result=validation,
                warnings=[*structured_warnings, *recommendations["warnings"]],
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
                warnings=[*structured_warnings, *recommendations["warnings"]],
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
                warnings=[SAFE_SIDE_EFFECT_NOTICE, *structured_warnings],
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
                warnings=[SAFE_SIDE_EFFECT_NOTICE, *structured_warnings],
            )
            self._finish_request(request_row, response)
            self.db.commit()
            return response

        try:
            preview_graph = self._build_preview_graph(
                structured,
                workflow=workflow,
                kb_bindings=recommendations["bindings"],
                selected_node_id=message_request.selected_node_id,
                selected_edge_id=effective_selected_edge_id,
                target_resolution=target_resolution,
            )
        except HTTPException as exc:
            raise
        except Exception:
            return self._fail_processing_request(request_row)
        uses_existing_workflow_base = workflow is not None and structured.draft_mode in {
            "modify_workflow",
            "replace_workflow",
        }
        base_graph = workflow.graph if uses_existing_workflow_base else _empty_graph()
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
            generated_node_ids=(
                set(generated_node_ids)
                if workflow is not None and structured.draft_mode == "modify_workflow"
                else None
            ),
        )
        if not draft_validation.valid:
            response = AgentBuilderMessageResponse(
                request_id=request_row.id,
                status="validation_failed",
                structured_request=structured,
                validation_result=draft_validation,
                warnings=[SAFE_SIDE_EFFECT_NOTICE, *structured_warnings],
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
            workflow_id=workflow.id if uses_existing_workflow_base else None,
            app_id=app_id,
            preview_graph=preview_graph,
            node_detail_previews=self._node_detail_previews(preview_graph),
            validation_result=draft_validation.model_dump(mode="json"),
            draft_metadata={
                "base_graph_hash": base_hash,
                "base_workflow_updated_at": workflow.updated_at.isoformat()
                if uses_existing_workflow_base and workflow.updated_at
                else None,
                "safe_kb_bindings": self._safe_kb_bindings(recommendations["bindings"]),
                "selected_kb_handles": list(
                    selected_kb_context["candidate_handles"]
                )
                if selected_kb_context
                else [],
                "structured_request": structured.model_dump(mode="json"),
                "safety_notices": draft_safety_notices,
                "generated_node_ids": generated_node_ids,
                "generated_edge_ids": generated_edge_ids,
                "target_resolution": {
                    **target_resolution,
                    "selected_node_id": message_request.selected_node_id,
                    "selected_edge_id": effective_selected_edge_id,
                },
                "app_id": str(app_id) if app_id else None,
                "workflow_id": str(workflow.id) if uses_existing_workflow_base else None,
                "workflow_scope": (
                    "existing_workflow"
                    if uses_existing_workflow_base
                    else "new_workflow"
                ),
            },
            base_graph_hash=base_hash,
            base_workflow_updated_at=(
                workflow.updated_at if uses_existing_workflow_base else None
            ),
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
            safety_notices=draft_safety_notices,
            configuration_issues=self._node_configuration_issues(preview_graph),
        )
        response = AgentBuilderMessageResponse(
            request_id=request_row.id,
            status="draft_ready",
            structured_request=structured,
            draft_preview=preview,
            validation_result=draft_validation,
            preview_prompt="도안 생성 미리보기",
            warnings=draft_safety_notices,
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
        try:
            draft = self._lock_draft_for_apply(draft)
            metadata_base = self._apply_metadata_base(draft, apply_id)
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
                notices=["초안 정보를 다시 확인할 수 없어 적용 및 저장을 차단했습니다."],
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
                notices=[
                    "도안 생성 미리보기를 닫았습니다. 실제 workflow graph는 변경되지 않았습니다."
                ],
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
            if draft.draft_mode == "new_workflow":
                self._rebind_session_after_new_workflow_apply(draft, workflow)
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
                    "layout_optimization_applied": True,
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
                layout_optimization_applied=True,
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

    def _rebind_session_after_new_workflow_apply(
        self,
        draft: AgentBuilderDraft,
        workflow: Workflow,
    ) -> None:
        if not isinstance(self.db, Session):
            return
        session = (
            self.db.query(AgentBuilderSession)
            .filter(
                AgentBuilderSession.id == draft.session_id,
                AgentBuilderSession.user_id == self.user.id,
                AgentBuilderSession.organization_id == self.organization_id,
            )
            .with_for_update()
            .first()
        )
        if session is None:
            raise RuntimeError("Agent Builder session not found during apply")
        session.workflow_id = workflow.id
        session.app_id = workflow.app_id
        session.updated_at = _now()

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
            if node_type not in AGENT_BUILDER_SUPPORTED_NODE_TYPES:
                issues.append(
                    AgentBuilderValidationIssue(
                        code="UNSUPPORTED_NODE_TYPE",
                        message=f"지원하지 않는 node type입니다: {node_type}",
                        path=f"nodes.{node.get('id')}",
                    )
                )
            if node_type == "llmNode":
                data = node.get("data") or {}
                if (
                    not data.get("model_id")
                    and data.get("configuration_state") != "unresolved"
                ):
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
        if generated_node_ids:
            generated_ids = set(generated_node_ids)
            existing_ids = node_ids - generated_ids
            generated_adjacency = {node_id: set() for node_id in generated_ids}
            attached_to_existing: set[str] = set()
            for edge in edges:
                source = str(edge.get("source") or "")
                target = str(edge.get("target") or "")
                if source in generated_ids and target in generated_ids:
                    generated_adjacency[source].add(target)
                    generated_adjacency[target].add(source)
                elif source in generated_ids and target in existing_ids:
                    attached_to_existing.add(source)
                elif target in generated_ids and source in existing_ids:
                    attached_to_existing.add(target)

            unchecked = set(generated_ids)
            while unchecked:
                root = next(iter(unchecked))
                component: set[str] = set()
                stack = [root]
                while stack:
                    current = stack.pop()
                    if current in component:
                        continue
                    component.add(current)
                    stack.extend(generated_adjacency.get(current, set()) - component)
                unchecked -= component
                if component.isdisjoint(attached_to_existing):
                    issues.append(
                        AgentBuilderValidationIssue(
                            code="DETACHED_GENERATED_COMPONENT",
                            message="새로 생성된 node가 기존 workflow graph에 연결되지 않았습니다.",
                            path=f"nodes.{root}",
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

    def _safe_intent_workflow_context(
        self,
        workflow: Workflow | None,
        request: AgentBuilderMessageRequest,
    ) -> dict[str, Any]:
        safe_nodes: list[dict[str, str]] = []
        if workflow is not None:
            for node in ((workflow.graph or {}).get("nodes") or [])[:50]:
                if not isinstance(node, dict):
                    continue
                data = node.get("data") if isinstance(node.get("data"), dict) else {}
                node_type = str(node.get("type") or "")
                safe_node_type = (
                    node_type
                    if node_type in AGENT_BUILDER_SUPPORTED_NODE_TYPES
                    else "unsupportedNode"
                )
                safe_node = {
                    "node_type": safe_node_type,
                    "title": _safe_display_label(
                        data.get("title") or safe_node_type or "Workflow node",
                        fallback="Workflow node",
                    ),
                }
                action = str(data.get("action") or "")
                if action in {"get_pr", "comment_pr"}:
                    safe_node["role"] = action
                safe_nodes.append(safe_node)
        return {
            "workflow_present": workflow is not None,
            "selected_node_present": bool(request.selected_node_id),
            "selected_edge_present": bool(request.selected_edge_id),
            "nodes": safe_nodes,
        }

    def _structure_request(
        self,
        request: AgentBuilderMessageRequest,
        workflow: Workflow | None,
    ) -> AgentBuilderStructuredRequest:
        if self.intent_extractor is None:
            raise AgentBuilderIntentRuntimeUnavailableError(
                "Agent Builder intent extractor is not configured"
            )
        extraction = self.intent_extractor.extract(
            safe_message=_safe_summary(request.message, limit=2000),
            workflow_context=self._safe_intent_workflow_context(workflow, request),
        )
        return self._normalize_intent_extraction(
            extraction,
            request=request,
            workflow=workflow,
        )

    def _normalize_intent_extraction(
        self,
        extraction: AgentBuilderIntentExtraction,
        *,
        request: AgentBuilderMessageRequest,
        workflow: Workflow | None,
    ) -> AgentBuilderStructuredRequest:
        intent_summary = _safe_summary(extraction.intent_summary, limit=240)
        if not intent_summary:
            intent_summary = _safe_summary(request.message)

        requested = [
            str(capability).strip()
            for capability in extraction.ordered_capabilities
            if str(capability).strip()
        ]
        target_requested = (
            [
                str(capability).strip()
                for capability in extraction.edit.target_capabilities
                if str(capability).strip()
            ]
            if extraction.edit
            else []
        )
        unsupported_capabilities = [
            capability
            for capability in [*requested, *target_requested]
            if capability not in AGENT_BUILDER_SUPPORTED_CAPABILITIES
        ]
        mode_matches_request = (
            extraction.request_type == "unsupported"
            or (
                extraction.request_type == "new_workflow"
                and extraction.draft_mode == "new_workflow"
            )
            or (
                extraction.request_type == "modify_workflow"
                and extraction.draft_mode in {"modify_workflow", "replace_workflow"}
            )
        )
        if (
            extraction.request_type == "unsupported"
            or unsupported_capabilities
            or not mode_matches_request
        ):
            reasons = [
                _safe_summary(reason, limit=160)
                for reason in extraction.unsupported_requests
                if _safe_summary(reason, limit=160)
            ]
            if unsupported_capabilities:
                reasons.append("지원 capability allowlist 밖의 요청이 포함되어 있습니다.")
            if not mode_matches_request:
                reasons.append("요청 유형과 workflow 변경 모드가 일치하지 않습니다.")
            if not reasons:
                reasons.append("지원하는 workflow 생성 또는 수정 요청으로 구조화할 수 없습니다.")
            return AgentBuilderStructuredRequest(
                request_type="unsupported",
                draft_mode="new_workflow",
                intent_summary=intent_summary,
                planned_steps=[],
                knowledge_requirements=[],
                required_capabilities=[],
                pending_resolution=[],
                unsupported_requests=reasons,
                risk_flags=["unsupported_capability"],
            )

        draft_mode = extraction.draft_mode
        entry_capabilities = {
            "start_input",
            "webhook_trigger",
            "schedule_trigger",
        }
        knowledge_required = extraction.knowledge_required or (
            "knowledge_backed_llm" in requested
        )
        normalized_capabilities: list[str] = []
        knowledge_capability_added = False
        for capability in requested:
            normalized = capability
            if knowledge_required and capability == "llm" and not knowledge_capability_added:
                normalized = "knowledge_backed_llm"
                knowledge_capability_added = True
            elif capability == "knowledge_backed_llm":
                knowledge_capability_added = True
            normalized_capabilities.append(normalized)

        if knowledge_required and not knowledge_capability_added:
            answer_index = next(
                (
                    index
                    for index, capability in enumerate(normalized_capabilities)
                    if capability == "answer"
                ),
                len(normalized_capabilities),
            )
            normalized_capabilities.insert(answer_index, "knowledge_backed_llm")

        missing_information: list[str] = []
        if draft_mode == "new_workflow":
            entries = [
                capability
                for capability in normalized_capabilities
                if capability in entry_capabilities
            ]
            if len(entries) > 1:
                return AgentBuilderStructuredRequest(
                    request_type="unsupported",
                    draft_mode="new_workflow",
                    intent_summary=intent_summary,
                    unsupported_requests=[
                        "한 workflow에 여러 entry trigger가 요청되었습니다."
                    ],
                    risk_flags=["unsupported_capability"],
                )
            entry = entries[0] if entries else "start_input"
            normalized_capabilities = [
                capability
                for capability in normalized_capabilities
                if capability not in entry_capabilities and capability != "answer"
            ]
            normalized_capabilities = [entry, *normalized_capabilities, "answer"]
        elif draft_mode == "modify_workflow":
            normalized_capabilities = [
                capability
                for capability in normalized_capabilities
                if capability not in entry_capabilities
            ]
            if workflow is None:
                missing_information.append("수정할 기존 workflow가 필요합니다.")
            if extraction.edit is None:
                missing_information.append(
                    "수정할 기존 node 또는 edge와 삽입 위치를 지정해주세요."
                )
            if not normalized_capabilities:
                missing_information.append("새로 추가할 node capability를 지정해주세요.")

        planned_steps: list[AgentBuilderPlannedStep] = []
        required_capabilities: list[str] = []
        step_counts: dict[str, int] = {}
        dependency_step_id: str | None = None
        knowledge_step_id: str | None = None
        for index, capability in enumerate(normalized_capabilities):
            if capability in entry_capabilities:
                base_step_id = "step_input"
            else:
                base_step_id = CAPABILITY_STEP_IDS[capability]
            step_counts[base_step_id] = step_counts.get(base_step_id, 0) + 1
            count = step_counts[base_step_id]
            step_id = base_step_id if count == 1 else f"{base_step_id}_{count}"
            planned_steps.append(
                AgentBuilderPlannedStep(
                    step_id=step_id,
                    capability=capability,
                    purpose=CAPABILITY_PURPOSES[capability],
                    depends_on=[dependency_step_id] if dependency_step_id else [],
                )
            )
            dependency_step_id = step_id
            if capability == "knowledge_backed_llm":
                knowledge_step_id = knowledge_step_id or step_id
                for required in ("llm", "knowledge_base"):
                    if required not in required_capabilities:
                        required_capabilities.append(required)
            elif capability not in required_capabilities:
                required_capabilities.append(capability)

        pending_resolution: list[AgentBuilderPendingResolution] = []
        knowledge_requirements: list[AgentBuilderKnowledgeRequirement] = []
        if knowledge_required and knowledge_step_id:
            topics = []
            for topic in extraction.knowledge_topics:
                safe_topic = _safe_summary(str(topic), limit=80)
                if safe_topic and safe_topic not in topics:
                    topics.append(safe_topic)
            if not topics:
                topics = _knowledge_query_topics(intent_summary)
            knowledge_requirements.append(
                AgentBuilderKnowledgeRequirement(
                    requirement_id="kr_1",
                    query_topics=topics,
                    expected_evidence_type="policy_or_reference",
                    required=True,
                    target_step_ref=knowledge_step_id,
                )
            )
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id="res_kb_1",
                    slot_type="knowledge_base",
                    slot_key="llm.knowledgeBases",
                    blocking=True,
                    target_step_ref=knowledge_step_id,
                )
            )

        capability_set = set(normalized_capabilities)
        risk_flags: list[str] = []
        if "slack_send" in capability_set:
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id="res_slack_channel_1",
                    slot_type="other",
                    slot_key="slack.channel",
                    blocking=False,
                    target_step_ref=CAPABILITY_STEP_IDS["slack_send"],
                )
            )
            risk_flags.extend(
                ["external_action_requested", "slack_channel_unresolved"]
            )
        if {"github_pr_read", "github_pr_comment"} & capability_set:
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id="res_github_configuration_1",
                    slot_type="other",
                    slot_key="github.credential_and_target",
                    blocking=False,
                    target_step_ref=(
                        CAPABILITY_STEP_IDS["github_pr_read"]
                        if "github_pr_read" in capability_set
                        else CAPABILITY_STEP_IDS["github_pr_comment"]
                    ),
                )
            )
            if "external_action_requested" not in risk_flags:
                risk_flags.append("external_action_requested")
            risk_flags.append("github_configuration_unresolved")
        if {
            "workflow_call",
            "http_request",
            "slack_send",
            "github_pr_read",
            "github_pr_comment",
            "mail_search",
        } & capability_set:
            risk_flags.append("external_configuration_unresolved")

        edit_operations: list[AgentBuilderEditOperation] = []
        if draft_mode == "modify_workflow" and extraction.edit and planned_steps:
            target = extraction.edit
            target_capabilities = list(dict.fromkeys(target_requested))
            target_node_types = list(
                dict.fromkeys(
                    node_type
                    for capability in target_capabilities
                    if (node_type := node_type_for_capability(capability)) is not None
                )
            )
            target_query = _safe_summary(target.target_query or "", limit=255) or None
            if (
                target.target_reference_type == "natural_language_node"
                and not target_query
                and not target_capabilities
            ):
                missing_information.append(
                    "수정할 기존 node의 이름 또는 역할을 지정해주세요."
                )
            else:
                edit_operations.append(
                    AgentBuilderEditOperation(
                        operation_id="edit_1",
                        operation="insert",
                        placement=target.placement,
                        step_refs=[step.step_id for step in planned_steps],
                        target=AgentBuilderEditTargetReference(
                            reference_type=target.target_reference_type,
                            query=target_query,
                            capabilities=target_capabilities,
                            node_types=target_node_types,
                        ),
                    )
                )
                pending_resolution.append(
                    AgentBuilderPendingResolution(
                        resolution_id="res_target_1",
                        slot_type="target",
                        slot_key="edit_operations.0.target",
                        blocking=True,
                        target_step_ref=planned_steps[0].step_id,
                    )
                )

        return AgentBuilderStructuredRequest(
            request_type=draft_mode,
            draft_mode=draft_mode,
            intent_summary=intent_summary,
            planned_steps=planned_steps,
            knowledge_requirements=knowledge_requirements,
            required_capabilities=required_capabilities,
            pending_resolution=pending_resolution,
            edit_operations=edit_operations,
            missing_information=list(dict.fromkeys(missing_information)),
            risk_flags=list(dict.fromkeys(risk_flags)),
        )

    def _build_structured_request(
        self,
        request: AgentBuilderMessageRequest,
        workflow: Workflow | None,
    ) -> AgentBuilderStructuredRequest:
        """Legacy deterministic compatibility helper; not a production parser."""
        if not _message_looks_like_workflow_request(request.message):
            return AgentBuilderStructuredRequest(
                request_type="unsupported",
                draft_mode="new_workflow",
                intent_summary=_safe_summary(request.message),
                planned_steps=[],
                knowledge_requirements=[],
                required_capabilities=[],
                pending_resolution=[],
                missing_information=[],
                unsupported_requests=[
                    "워크플로우 생성 또는 수정 의도가 충분히 명확하지 않습니다."
                ],
                risk_flags=[],
            )

        text = request.message.lower()
        if "guardrail" in text or "가드레일" in request.message or "안전장치" in request.message:
            return AgentBuilderStructuredRequest(
                request_type="unsupported",
                draft_mode="new_workflow",
                intent_summary=_safe_summary(request.message),
                planned_steps=[],
                knowledge_requirements=[],
                required_capabilities=[],
                pending_resolution=[],
                missing_information=[],
                unsupported_requests=[
                    "Guardrail node 자동 생성은 MVP 범위가 아닙니다."
                ],
                risk_flags=["unsupported_capability"],
            )
        explicit_new_workflow = _message_requests_new_workflow(request.message)
        edit_spec = (
            _extract_workflow_edit_spec(
                request.message,
                selected_edge_id=request.selected_edge_id,
            )
            if workflow is not None and not explicit_new_workflow
            else None
        )
        targeted_modify = (
            workflow is not None
            and not explicit_new_workflow
            and (
                edit_spec is not None
                or _message_requests_targeted_modify(request.message)
                or (
                    request.selected_edge_id is not None
                    and _message_mentions_edge_context(request.message)
                )
            )
        )
        draft_mode = "modify_workflow" if targeted_modify else "new_workflow"
        capability_text = (
            edit_spec["new_steps_text"] if targeted_modify and edit_spec else request.message
        )
        needs_kb = any(
            token in capability_text
            for token in ["정책", "규정", "내규", "문서", "자료", "근거", "찾아", "검색", "Knowledge", "KB"]
        )
        requested_capabilities = _message_requested_catalog_capabilities(capability_text)
        wants_slack = "slack_send" in requested_capabilities
        wants_webhook = "webhook_trigger" in requested_capabilities
        wants_schedule = "schedule_trigger" in requested_capabilities
        simple_input_output = (
            not targeted_modify
            and _message_requests_simple_input_output(request.message)
        )
        knowledge_requirements: list[AgentBuilderKnowledgeRequirement] = []
        pending_resolution: list[AgentBuilderPendingResolution] = []
        if needs_kb:
            query_topics = _knowledge_query_topics(request.message)
            knowledge_requirements.append(
                AgentBuilderKnowledgeRequirement(
                    requirement_id="kr_1",
                    query_topics=query_topics,
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
        missing_information: list[str] = []
        entry_capability = (
            "webhook_trigger"
            if wants_webhook
            else "schedule_trigger"
            if wants_schedule
            else "start_input"
        )
        entry_purpose = {
            "webhook_trigger": "웹훅 payload를 받습니다.",
            "schedule_trigger": "설정된 일정에 따라 workflow를 시작합니다.",
            "start_input": "사용자 입력을 받습니다.",
        }[entry_capability]
        planned_steps = (
            []
            if targeted_modify
            else [
                AgentBuilderPlannedStep(
                    step_id="step_input",
                    capability=entry_capability,
                    purpose=entry_purpose,
                )
            ]
        )
        required_capabilities = [] if targeted_modify else [entry_capability]
        risk_flags: list[str] = []

        uses_llm = not simple_input_output and (
            needs_kb
            or _message_requests_llm_processing(capability_text)
            or (
                not targeted_modify
                and (
                    wants_slack
                    or "github_pr_comment" in requested_capabilities
                )
            )
            or (not requested_capabilities and not targeted_modify)
        )
        selected_capabilities = set() if simple_input_output else set(requested_capabilities)
        selected_capabilities.discard("start_input")
        selected_capabilities.discard("webhook_trigger")
        selected_capabilities.discard("schedule_trigger")
        selected_capabilities.discard("llm")
        if not targeted_modify:
            selected_capabilities.discard("answer")
        if uses_llm:
            selected_capabilities.add(
                "knowledge_backed_llm" if needs_kb else "llm"
            )

        ordered_capabilities = [
            capability
            for capability in CAPABILITY_GENERATION_ORDER
            if capability in selected_capabilities
        ]
        dependency_step_id: str | None = None if targeted_modify else "step_input"
        purpose_by_capability = {
            "file_extraction": "입력 파일에서 텍스트를 추출하도록 설정합니다.",
            "variable_extraction": "입력 데이터에서 필요한 변수를 추출하도록 설정합니다.",
            "github_pr_read": "GitHub Pull Request와 변경 파일을 조회하도록 설정합니다.",
            "mail_search": "메일을 검색하도록 설정합니다.",
            "http_request": "외부 HTTP API를 호출하도록 설정합니다.",
            "workflow_call": "다른 workflow를 호출하도록 설정합니다.",
            "code_execution": "sandbox에서 코드를 실행하도록 설정합니다.",
            "template_render": "입력값으로 템플릿을 렌더링하도록 설정합니다.",
            "condition": "조건에 따라 흐름을 분기하도록 설정합니다.",
            "loop": "목록의 각 항목을 반복 처리하도록 설정합니다.",
            "llm": "입력을 분석하고 답변을 생성합니다.",
            "knowledge_backed_llm": "Knowledge Base 근거로 입력을 분석하고 답변을 생성합니다.",
            "github_pr_comment": "생성된 리뷰를 GitHub Pull Request에 댓글로 등록하도록 설정합니다.",
            "slack_send": "이전 단계 결과를 Slack 메시지로 전송하도록 설정합니다.",
            "answer": "이전 단계 결과를 응답으로 반환하도록 설정합니다.",
        }
        for capability in ordered_capabilities:
            step_id = CAPABILITY_STEP_IDS[capability]
            planned_steps.append(
                AgentBuilderPlannedStep(
                    step_id=step_id,
                    capability=capability,
                    purpose=purpose_by_capability[capability],
                    depends_on=[dependency_step_id] if dependency_step_id else [],
                )
            )
            dependency_step_id = step_id
            if capability == "knowledge_backed_llm":
                required_capabilities.extend(["llm", "knowledge_base"])
            else:
                required_capabilities.append(capability)

        if "slack_send" in selected_capabilities:
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id="res_slack_channel_1",
                    slot_type="other",
                    slot_key="slack.channel",
                    blocking=False,
                    target_step_ref="step_slack",
                )
            )
            risk_flags.extend(
                ["external_action_requested", "slack_channel_unresolved"]
            )
        if {
            "github_pr_read",
            "github_pr_comment",
        } & selected_capabilities:
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id="res_github_configuration_1",
                    slot_type="other",
                    slot_key="github.credential_and_target",
                    blocking=False,
                    target_step_ref="step_github_read"
                    if "github_pr_read" in selected_capabilities
                    else "step_github_comment",
                )
            )
            risk_flags.extend(
                ["external_action_requested", "github_configuration_unresolved"]
            )
        if {
            "workflow_call",
            "http_request",
            "slack_send",
            "github_pr_read",
            "github_pr_comment",
            "mail_search",
        } & selected_capabilities:
            if "external_configuration_unresolved" not in risk_flags:
                risk_flags.append("external_configuration_unresolved")
        edit_operations: list[AgentBuilderEditOperation] = []
        if targeted_modify:
            if edit_spec is None:
                missing_information.append("수정할 기존 node 또는 edge와 삽입 위치를 지정해주세요.")
            elif not planned_steps:
                missing_information.append("새로 추가할 node capability를 지정해주세요.")
            else:
                target_capabilities = _message_requested_catalog_capabilities(
                    edit_spec["target_text"]
                )
                target_node_types = _target_node_types_for_text(
                    edit_spec["target_text"],
                    target_capabilities,
                )
                edit_operations.append(
                    AgentBuilderEditOperation(
                        operation_id="edit_1",
                        operation="insert",
                        placement=edit_spec["placement"],
                        step_refs=[step.step_id for step in planned_steps],
                        target=AgentBuilderEditTargetReference(
                            reference_type=edit_spec["reference_type"],
                            query=_safe_summary(edit_spec["target_text"], limit=255),
                            capabilities=target_capabilities,
                            node_types=target_node_types,
                        ),
                    )
                )
                pending_resolution.append(
                    AgentBuilderPendingResolution(
                        resolution_id="res_target_1",
                        slot_type="target",
                        slot_key="edit_operations.0.target",
                        blocking=True,
                        target_step_ref=planned_steps[0].step_id,
                    )
                )
        else:
            planned_steps.append(
                AgentBuilderPlannedStep(
                    step_id="step_answer",
                    capability="answer",
                    purpose="결과를 사용자에게 반환합니다.",
                    depends_on=[dependency_step_id] if dependency_step_id else [],
                )
            )
            required_capabilities.append("answer")
        return AgentBuilderStructuredRequest(
            request_type=draft_mode,
            draft_mode=draft_mode,
            intent_summary=_safe_summary(request.message),
            planned_steps=planned_steps,
            knowledge_requirements=knowledge_requirements,
            required_capabilities=required_capabilities,
            pending_resolution=pending_resolution,
            edit_operations=edit_operations,
            missing_information=missing_information,
            risk_flags=risk_flags,
        )

    def _resolve_edit_target(
        self,
        structured: AgentBuilderStructuredRequest,
        *,
        workflow: Workflow | None,
        selected_node_id: str | None,
        selected_edge_id: str | None,
    ) -> dict[str, Any]:
        if structured.draft_mode != "modify_workflow":
            return {"status": "not_required", "replaced_edge_ids": []}
        if structured.missing_information:
            return {"status": "not_required", "replaced_edge_ids": []}
        if workflow is None or not structured.edit_operations:
            return {
                "status": "clarification_required",
                "questions": ["수정할 기존 node 또는 edge와 삽입 위치를 지정해주세요."],
                "options": [],
            }

        operation = structured.edit_operations[0]
        target = operation.target
        graph = workflow.graph or _empty_graph()
        nodes = graph.get("nodes") or []
        edges = graph.get("edges") or []
        node_by_id = {
            str(node.get("id")): node for node in nodes if node.get("id")
        }
        edge_by_id = {
            str(edge.get("id")): edge for edge in edges if edge.get("id")
        }

        if target.reference_type == "selected_edge":
            edge = edge_by_id.get(str(selected_edge_id or ""))
            if edge is None:
                return {
                    "status": "clarification_required",
                    "questions": ["삽입할 기존 연결을 선택해주세요."],
                    "options": [],
                }
            return {
                "status": "resolved",
                "operation_id": operation.operation_id,
                "placement": "between",
                "edge_id": str(edge["id"]),
                "node_id": None,
                "source_node_id": str(edge["source"]),
                "destination_node_id": str(edge["target"]),
                "replaced_edge_ids": [str(edge["id"])],
            }

        if target.reference_type == "selected_node":
            selected_node = node_by_id.get(str(selected_node_id or ""))
            candidates = [selected_node] if selected_node else []
        else:
            target_node_types = set(target.node_types)
            target_actions = {
                action
                for capability in target.capabilities
                if (action := CAPABILITY_NODE_ACTIONS.get(capability)) is not None
            }
            normalized_query = re.sub(
                r"[^0-9a-z가-힣]+",
                "",
                str(target.query or "").casefold(),
            )
            type_candidates = []
            title_candidates = []
            role_candidates = []
            for node in nodes:
                node_type = str(node.get("type") or "")
                data = node.get("data") if isinstance(node.get("data"), dict) else {}
                normalized_title = re.sub(
                    r"[^0-9a-z가-힣]+",
                    "",
                    str(data.get("title") or "").casefold(),
                )
                title_matches = bool(
                    normalized_query
                    and normalized_title
                    and (
                        normalized_query in normalized_title
                        or normalized_title in normalized_query
                    )
                )
                if node_type in target_node_types:
                    type_candidates.append(node)
                if title_matches:
                    title_candidates.append(node)
                if target_actions and str(data.get("action") or "") in target_actions:
                    role_candidates.append(node)

            if role_candidates and title_candidates:
                role_ids = {str(node.get("id")) for node in role_candidates}
                candidates = [
                    node
                    for node in title_candidates
                    if str(node.get("id")) in role_ids
                ]
            elif role_candidates:
                candidates = role_candidates
            elif title_candidates:
                candidates = title_candidates
            else:
                candidates = type_candidates

        candidate_ids = {str(node.get("id")) for node in candidates}
        if selected_node_id and str(selected_node_id) in candidate_ids:
            candidates = [node_by_id[str(selected_node_id)]]
        if len(candidates) != 1:
            options = [
                {
                    "type": "workflow_node",
                    "node_id": str(node.get("id")),
                    "node_type": str(node.get("type") or "node"),
                    "label": _safe_display_label(
                        (node.get("data") or {}).get("title"),
                        fallback=str(node.get("type") or "Workflow node"),
                    ),
                }
                for node in candidates
            ]
            return {
                "status": "clarification_required",
                "questions": [
                    "수정 대상 node를 하나로 특정할 수 없습니다. 사용할 node를 선택해주세요."
                    if candidates
                    else "요청한 수정 대상 node를 현재 workflow에서 찾을 수 없습니다."
                ],
                "options": options,
            }

        node_id = str(candidates[0]["id"])
        if operation.placement == "after":
            adjacent_edges = [
                edge for edge in edges if str(edge.get("source")) == node_id
            ]
            source_node_id = node_id
            destination_node_id = (
                str(adjacent_edges[0].get("target")) if len(adjacent_edges) == 1 else None
            )
        else:
            adjacent_edges = [
                edge for edge in edges if str(edge.get("target")) == node_id
            ]
            source_node_id = (
                str(adjacent_edges[0].get("source")) if len(adjacent_edges) == 1 else None
            )
            destination_node_id = node_id

        if len(adjacent_edges) > 1:
            return {
                "status": "clarification_required",
                "questions": [
                    "대상 node에 연결이 여러 개입니다. '이 연결 사이에'처럼 삽입할 분기를 지칭해 다시 요청해주세요."
                ],
                "options": [],
            }
        if operation.placement == "before" and not adjacent_edges:
            return {
                "status": "clarification_required",
                "questions": ["대상 node 앞에 연결된 node가 없어 삽입 위치를 정할 수 없습니다."],
                "options": [],
            }

        replaced_edge_ids = (
            [str(adjacent_edges[0]["id"])] if adjacent_edges else []
        )
        return {
            "status": "resolved",
            "operation_id": operation.operation_id,
            "placement": operation.placement,
            "node_id": node_id,
            "edge_id": replaced_edge_ids[0] if replaced_edge_ids else None,
            "source_node_id": source_node_id,
            "destination_node_id": destination_node_id,
            "replaced_edge_ids": replaced_edge_ids,
        }

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
        if structured.request_type == "unsupported":
            issues.append(
                AgentBuilderValidationIssue(
                    code="UNSUPPORTED_REQUEST",
                    message="워크플로우 생성 또는 수정 요청으로 이해할 수 없습니다.",
                    path="message",
                )
            )
            return AgentBuilderValidationResult(valid=False, issues=issues)
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

    def _structured_request_warnings(
        self, structured: AgentBuilderStructuredRequest
    ) -> list[str]:
        warnings: list[str] = []
        if "slack_channel_unresolved" in structured.risk_flags:
            warnings.append(SLACK_CHANNEL_UNRESOLVED_WARNING)
        if "github_configuration_unresolved" in structured.risk_flags:
            warnings.append(GITHUB_CONFIGURATION_UNRESOLVED_WARNING)
        if "external_configuration_unresolved" in structured.risk_flags:
            warnings.append(EXTERNAL_NODE_CONFIGURATION_WARNING)
        return warnings

    def _draft_safety_notices(
        self,
        structured: AgentBuilderStructuredRequest,
    ) -> list[str]:
        _ = structured
        return [SAFE_SIDE_EFFECT_NOTICE]

    def _safety_notices_for_draft(self, draft: AgentBuilderDraft) -> list[str]:
        _ = draft
        return [SAFE_SIDE_EFFECT_NOTICE]

    def _resolve_knowledge_requirements(
        self,
        structured: AgentBuilderStructuredRequest,
        *,
        include_materialized_refs: bool = False,
        selected_candidate_handles: set[str] | None = None,
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
            if (
                selected_candidate_handles
                and NO_KB_CANDIDATE_ID in selected_candidate_handles
            ):
                warnings.append(NO_KB_CANDIDATE_WARNING)
                continue
            response = service.recommend_for_builder(
                KnowledgeRAGRecommendationRequest(
                    workflow_intent=structured.intent_summary,
                    node_purpose="; ".join(requirement.query_topics) or requirement.expected_evidence_type,
                    knowledge_requirement=requirement.model_dump(mode="json"),
                    safe_query_topics=requirement.query_topics,
                    pending_resolution_ref=pending_by_step.get(requirement.target_step_ref),
                    safe_workflow_context_summary={
                        "planned_step_count": len(structured.planned_steps),
                        "required_capabilities": structured.required_capabilities,
                    },
                    intended_execution_subject_id=self.user.id,
                    mode="auto",
                    max_recommendations=AGENT_BUILDER_KB_RECOMMENDATION_LIMIT,
                ),
                include_materialized_refs=include_materialized_refs,
            )
            resolution_id = pending_by_step.get(requirement.target_step_ref)
            if response.status == "unavailable":
                if selected_candidate_handles and not include_materialized_refs:
                    selected_option = next(
                        (
                            option
                            for option in response.clarification_options
                            if str(option.get("candidate_id"))
                            in selected_candidate_handles
                        ),
                        None,
                    )
                    if selected_option:
                        bindings.append(
                            {
                                "safe_handle": selected_option.get("candidate_id"),
                                "name": _safe_display_label(
                                    selected_option.get("safe_label")
                                    or selected_option.get("label")
                                ),
                                "confidence": selected_option.get("confidence")
                                or "medium",
                                "score": selected_option.get("score"),
                                "reason_category": selected_option.get(
                                    "reason_category"
                                )
                                or "user_selected",
                                "threshold_result": selected_option.get(
                                    "threshold_result"
                                )
                                or "user_selected",
                            }
                        )
                        warnings.append(
                            response.user_safe_warning
                            or "사용자가 선택한 Knowledge Base 후보로 초안을 생성합니다."
                        )
                        continue
                return {
                    "status": "validation_failed"
                    if requirement.required
                    else "clarification_required",
                    "bindings": [],
                    "questions": ["사용할 Knowledge Base를 선택해주세요."],
                    "options": self._kb_options_with_requirement_context(
                        response.clarification_options,
                        requirement=requirement,
                        resolution_id=resolution_id,
                    ),
                    "warnings": [
                        response.user_safe_warning
                        or "Knowledge Base 추천을 사용할 수 없습니다."
                    ],
                }
            if response.status == "clarification_required" and not selected_candidate_handles:
                return {
                    "status": "clarification_required",
                    "bindings": [],
                    "questions": ["사용할 Knowledge Base를 선택해주세요."],
                    "options": self._kb_options_with_requirement_context(
                        response.clarification_options,
                        requirement=requirement,
                        resolution_id=resolution_id,
                    ),
                    "warnings": [
                        response.user_safe_warning
                        or "Knowledge Base 후보를 사용자 확인으로 선택해야 합니다."
                    ],
                }
            recommendations = list(response.recommendations or [])
            if selected_candidate_handles:
                selected_recommendations = [
                    item
                    for item in recommendations
                    if (item.candidate_handle or item.recommendation_id)
                    in selected_candidate_handles
                ]
                if selected_recommendations:
                    recommendations = selected_recommendations
                    for selected in recommendations:
                        binding_base = {
                            "safe_handle": (
                                selected.candidate_handle
                                or selected.recommendation_id
                            ),
                            "name": _safe_display_label(selected.safe_label),
                            "confidence": selected.confidence or "medium",
                            "score": selected.score,
                            "reason_category": (
                                selected.reason_category
                                or selected.safe_reason_code
                                or "user_selected"
                            ),
                            "threshold_result": (
                                selected.threshold_result or "user_selected"
                            ),
                        }
                        if include_materialized_refs:
                            for ref in selected.materialized_knowledge_bases:
                                bindings.append(
                                    {
                                        **binding_base,
                                        "knowledge_base_id": str(ref.id),
                                        "name": _safe_display_label(ref.name),
                                    }
                                )
                        else:
                            bindings.append(binding_base)
                        warnings.extend(selected.warnings)
                    if bindings:
                        warnings.append(
                            "사용자가 선택한 Knowledge Base 후보로 초안을 생성합니다."
                        )
                        continue
                else:
                    if not include_materialized_refs:
                        selected_option = next(
                            (
                                option
                                for option in response.clarification_options
                                if str(option.get("candidate_id"))
                                in selected_candidate_handles
                            ),
                            None,
                        )
                        if selected_option:
                            bindings.append(
                                {
                                    "safe_handle": selected_option.get("candidate_id"),
                                    "name": _safe_display_label(
                                        selected_option.get("safe_label")
                                        or selected_option.get("label")
                                    ),
                                    "confidence": selected_option.get("confidence")
                                    or "medium",
                                    "score": selected_option.get("score"),
                                    "reason_category": selected_option.get(
                                        "reason_category"
                                    )
                                    or "user_selected",
                                    "threshold_result": selected_option.get(
                                        "threshold_result"
                                    )
                                    or "user_selected",
                                }
                            )
                            warnings.append(
                                "사용자가 선택한 Knowledge Base 후보로 초안을 생성합니다."
                            )
                            continue
                    return {
                        "status": "validation_failed",
                        "bindings": [],
                        "questions": [],
                        "options": [],
                        "warnings": [
                            "선택한 Knowledge Base 후보를 다시 확인할 수 없습니다."
                        ],
                    }
            if not recommendations:
                return {
                    "status": "recommended",
                    "bindings": [],
                    "questions": [],
                    "options": [],
                    "warnings": [
                        "권한 확인된 Knowledge Base 후보가 없어 Knowledge Base 없이 LLM node 초안을 생성합니다."
                    ],
                }
            return {
                "status": "clarification_required",
                "bindings": [],
                "questions": ["추천 후보를 확인하고 사용할 Knowledge Base를 선택해주세요."],
                "options": self._kb_options_with_requirement_context(
                    response.clarification_options
                    or self._kb_clarification_options(
                        recommendations,
                        requirement=requirement,
                        resolution_id=resolution_id,
                    ),
                    requirement=requirement,
                    resolution_id=resolution_id,
                ),
                "warnings": ["Knowledge Base 후보를 확인하고 선택해주세요."],
            }
        return {"status": "recommended", "bindings": bindings, "questions": [], "options": [], "warnings": warnings}

    def _kb_clarification_options(
        self,
        recommendations: list[Any],
        *,
        requirement: AgentBuilderKnowledgeRequirement,
        resolution_id: str | None,
    ) -> list[dict[str, Any]]:
        options: list[dict[str, Any]] = []
        for item in recommendations:
            options.append(
                {
                    "type": "knowledge_base",
                    "candidate_id": item.candidate_handle or item.recommendation_id,
                    "label": _safe_display_label(item.safe_label),
                    "confidence": item.confidence,
                    "score": item.score,
                    "reason_category": item.reason_category or item.safe_reason_code,
                    "threshold_result": item.threshold_result,
                    "runtime_availability": item.runtime_availability,
                }
            )
        return self._kb_options_with_requirement_context(
            options,
            requirement=requirement,
            resolution_id=resolution_id,
        )

    def _kb_options_with_requirement_context(
        self,
        options: list[dict[str, Any]],
        *,
        requirement: AgentBuilderKnowledgeRequirement,
        resolution_id: str | None,
    ) -> list[dict[str, Any]]:
        contextualized = [
            {
                **option,
                "requirement_id": option.get("requirement_id")
                or requirement.requirement_id,
                "resolution_id": option.get("resolution_id") or resolution_id,
            }
            for option in options
        ]
        return contextualized

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

        service = KnowledgeRAGRecommendationService(
            self.db,
            user_id=self.user.id,
            organization_id=self.organization_id,
        )
        pending_by_step = {
            item.target_step_ref: item.resolution_id
            for item in structured.pending_resolution
            if item.slot_type == "knowledge_base"
        }
        runtime_bindings: list[dict[str, Any]] = []
        for requirement in structured.knowledge_requirements:
            runtime_bindings.extend(
                service.materialize_candidate_handles_for_builder(
                    KnowledgeRAGRecommendationRequest(
                        workflow_intent=structured.intent_summary,
                        node_purpose="; ".join(requirement.query_topics)
                        or requirement.expected_evidence_type,
                        knowledge_requirement=requirement.model_dump(mode="json"),
                        safe_query_topics=requirement.query_topics,
                        pending_resolution_ref=pending_by_step.get(
                            requirement.target_step_ref
                        ),
                        safe_workflow_context_summary={
                            "planned_step_count": len(structured.planned_steps),
                            "required_capabilities": structured.required_capabilities,
                        },
                        intended_execution_subject_id=self.user.id,
                        mode="auto",
                        max_recommendations=AGENT_BUILDER_KB_RECOMMENDATION_LIMIT,
                    ),
                    required_handles,
                )
            )

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
        generated_node_ids = list(
            (draft.draft_metadata or {}).get("generated_node_ids") or []
        )
        if workflow is None or draft.draft_mode == "replace_workflow":
            return self._layout_graph_for_apply_save(
                materialized_preview,
                generated_node_ids=generated_node_ids,
            )

        save_graph = copy.deepcopy(workflow.graph or _empty_graph())
        generated_node_id_set = set(generated_node_ids)
        generated_edge_ids = set((draft.draft_metadata or {}).get("generated_edge_ids") or [])
        target_resolution = (draft.draft_metadata or {}).get("target_resolution") or {}
        selected_edge_id = target_resolution.get("selected_edge_id")
        replaced_edge_ids = set(target_resolution.get("replaced_edge_ids") or [])
        if selected_edge_id:
            replaced_edge_ids.add(str(selected_edge_id))
        existing_node_ids = _graph_node_ids(save_graph)
        existing_edge_ids = {
            str(edge.get("id"))
            for edge in (save_graph.get("edges") or [])
            if edge.get("id")
        }
        save_graph["nodes"] = (save_graph.get("nodes") or []) + [
            node
            for node in materialized_preview.get("nodes") or []
            if str(node.get("id")) in generated_node_id_set
            and str(node.get("id")) not in existing_node_ids
        ]
        if replaced_edge_ids:
            save_graph["edges"] = [
                edge
                for edge in save_graph.get("edges") or []
                if str(edge.get("id")) not in replaced_edge_ids
            ]
        save_graph["edges"] = (save_graph.get("edges") or []) + [
            edge
            for edge in materialized_preview.get("edges") or []
            if str(edge.get("id")) in generated_edge_ids
            and str(edge.get("id")) not in existing_edge_ids
        ]
        save_graph.setdefault(
            "viewport",
            workflow.graph.get("viewport") if workflow.graph else None,
        )
        return self._layout_graph_for_apply_save(
            save_graph,
            generated_node_ids=generated_node_ids,
        )

    def _layout_graph_for_apply_save(
        self,
        graph: dict[str, Any],
        *,
        generated_node_ids: list[str],
    ) -> dict[str, Any]:
        _ = generated_node_ids
        return calculate_workflow_auto_layout(graph)

    def _ordered_preview_capabilities(
        self,
        structured: AgentBuilderStructuredRequest,
    ) -> tuple[str, list[str]]:
        planned_capabilities = [
            step.capability for step in structured.planned_steps
        ]
        required = set(structured.required_capabilities)
        entry_capability = next(
            (
                capability
                for capability in planned_capabilities
                if capability
                in {"start_input", "webhook_trigger", "schedule_trigger"}
            ),
            (
                "webhook_trigger"
                if "webhook_trigger" in required
                else "schedule_trigger"
                if "schedule_trigger" in required
                else "start_input"
            ),
        )
        body_capabilities = [
            capability
            for capability in planned_capabilities
            if capability
            not in {"start_input", "webhook_trigger", "schedule_trigger"}
        ]
        if not body_capabilities:
            body_capabilities = [
                capability
                for capability in CAPABILITY_GENERATION_ORDER
                if capability in required
            ]
        if structured.draft_mode != "modify_workflow":
            body_capabilities = [
                capability for capability in body_capabilities if capability != "answer"
            ]
        if "knowledge_backed_llm" in body_capabilities:
            body_capabilities = [
                capability
                for capability in body_capabilities
                if capability != "llm"
            ]
        return entry_capability, body_capabilities

    def _build_entry_preview_node(
        self,
        capability: str,
        node_id: str,
    ) -> dict[str, Any]:
        if capability == "webhook_trigger":
            data = {
                "title": "웹훅 입력",
                "provider": "custom",
                "variable_mappings": [
                    {"variable_name": "payload", "json_path": "$"}
                ],
            }
        elif capability == "schedule_trigger":
            data = {
                "title": "스케줄 트리거",
                "cron_expression": "0 9 * * *",
                "timezone": "UTC",
            }
        else:
            data = {
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
            }
        node_type = node_type_for_capability(capability)
        if node_type is None:
            raise ValueError(f"Unsupported entry capability: {capability}")
        return {
            "id": node_id,
            "type": node_type,
            "position": {"x": 0, "y": 0},
            "data": data,
        }

    def _github_target_configuration(
        self,
        *,
        entry_id: str,
        entry_capability: str,
    ) -> tuple[dict[str, str], list[dict[str, Any]]]:
        if entry_capability != "webhook_trigger":
            return {"repo_owner": "", "repo_name": "", "pr_number": ""}, []
        return (
            {
                "repo_owner": "{{repo_owner}}",
                "repo_name": "{{repo_name}}",
                "pr_number": "{{pr_number}}",
            },
            [
                {
                    "name": "repo_owner",
                    "value_selector": [
                        entry_id,
                        "payload",
                        "repository",
                        "owner",
                        "login",
                    ],
                },
                {
                    "name": "repo_name",
                    "value_selector": [entry_id, "payload", "repository", "name"],
                },
                {
                    "name": "pr_number",
                    "value_selector": [entry_id, "payload", "number"],
                },
            ],
        )

    def _build_capability_preview_node(
        self,
        capability: str,
        node_id: str,
        *,
        source_id: str,
        source_output_key: str,
        entry_id: str,
        entry_capability: str,
        model_id: str | None,
        kb_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        source_selector = [source_id, source_output_key]
        configuration_state = "unresolved"
        if capability in {"llm", "knowledge_backed_llm"}:
            data: dict[str, Any] = {
                "title": "Knowledge Base-backed LLM" if kb_refs else "LLM",
                "provider": "configured",
                "model_id": model_id,
                "configuration_state": (
                    "resolved" if model_id else configuration_state
                ),
                "task_type": "answer",
                "system_prompt": "입력을 안전하게 분석하고 결과를 생성합니다.",
                "user_prompt": f"{{{{{source_output_key}}}}}",
                "referenced_variables": [
                    {"name": source_output_key, "value_selector": source_selector}
                ],
                "parameters": {},
                "output_format": {"type": "text"},
                "knowledgeBases": kb_refs,
                "scoreThreshold": 0.5,
                "topK": 3,
            }
        elif capability == "workflow_call":
            data = {
                "title": "서브 워크플로우",
                "workflowId": "",
                "appId": "",
                "inputs": [
                    {"name": "input", "value_selector": source_selector}
                ],
                "outputs": [],
                "configuration_state": configuration_state,
            }
        elif capability == "code_execution":
            data = {
                "title": "코드 실행",
                "code": "def main(inputs):\n    return {'result': inputs}",
                "inputs": [
                    {"name": "input", "source": f"{source_id}.{source_output_key}"}
                ],
                "timeout": 10,
            }
        elif capability == "condition":
            data = {
                "title": "IF/ELSE",
                "cases": [],
                "conditions": [],
                "configuration_state": configuration_state,
            }
        elif capability == "file_extraction":
            data = {
                "title": "문서 추출",
                "referenced_variables": [
                    {"name": "file", "value_selector": source_selector}
                ],
            }
        elif capability == "variable_extraction":
            data = {
                "title": "변수 추출",
                "source_selector": source_selector,
                "mappings": [],
                "configuration_state": configuration_state,
            }
        elif capability == "loop":
            data = {
                "title": "반복",
                "loop_key": "",
                "inputs": [
                    {"name": "items", "value_selector": source_selector}
                ],
                "outputs": [],
                "max_iterations": 100,
                "parallel_mode": False,
                "error_strategy": "end",
                "flatten_output": True,
                "subGraph": {"nodes": [], "edges": []},
                "configuration_state": configuration_state,
            }
        elif capability == "http_request":
            data = {
                "title": "HTTP 요청",
                "method": "GET",
                "url": "",
                "headers": [],
                "body": "",
                "timeout": 5000,
                "authType": "none",
                "authConfig": {},
                "referenced_variables": [
                    {"name": "input", "value_selector": source_selector}
                ],
                "configuration_state": configuration_state,
            }
        elif capability == "slack_send":
            data = {
                "title": "Slack 전송",
                "method": "POST",
                "url": "https://slack.com/api/chat.postMessage",
                "headers": [{"key": "Content-Type", "value": "application/json"}],
                "body": json.dumps({"text": "{{result}}"}, ensure_ascii=False),
                "timeout": 5000,
                "authType": "bearer",
                "authConfig": {},
                "referenced_variables": [
                    {"name": "result", "value_selector": source_selector}
                ],
                "message": "{{result}}",
                "channel": "",
                "blocks": "",
                "slackMode": "api",
                "channel_resolution_state": configuration_state,
                "configuration_state": configuration_state,
            }
        elif capability == "template_render":
            data = {
                "title": "템플릿",
                "template": "{{input}}",
                "variables": [
                    {"name": "input", "value_selector": source_selector}
                ],
            }
        elif capability in {"github_pr_read", "github_pr_comment"}:
            target_config, referenced_variables = self._github_target_configuration(
                entry_id=entry_id,
                entry_capability=entry_capability,
            )
            data = {
                "title": "GitHub PR 조회"
                if capability == "github_pr_read"
                else "GitHub PR 댓글 등록",
                "action": "get_pr"
                if capability == "github_pr_read"
                else "comment_pr",
                "api_token": "",
                **target_config,
                "comment_body": None,
                "referenced_variables": referenced_variables,
                "configuration_state": configuration_state,
            }
            if capability == "github_pr_comment":
                data["comment_body"] = "{{review}}"
                data["referenced_variables"] = [
                    *referenced_variables,
                    {"name": "review", "value_selector": source_selector},
                ]
        elif capability == "mail_search":
            data = {
                "title": "메일 검색",
                "email": "",
                "password": "",
                "provider": "gmail",
                "imap_server": "imap.gmail.com",
                "imap_port": 993,
                "use_ssl": True,
                "keyword": None,
                "sender": None,
                "subject": None,
                "start_date": None,
                "end_date": None,
                "folder": "INBOX",
                "max_results": 10,
                "unread_only": False,
                "mark_as_read": False,
                "referenced_variables": [],
                "configuration_state": configuration_state,
            }
        elif capability == "answer":
            data = {
                "title": "응답",
                "outputs": [
                    {
                        "variable": "answer",
                        "value_selector": source_selector,
                    }
                ],
            }
        else:
            raise ValueError(f"Unsupported draft capability: {capability}")

        node_type = node_type_for_capability(capability)
        if node_type is None or node_type not in AGENT_BUILDER_SUPPORTED_NODE_TYPES:
            raise ValueError(f"Capability is not in the Agent Builder allowlist: {capability}")
        return {
            "id": node_id,
            "type": node_type,
            "position": {"x": 0, "y": 0},
            "data": data,
        }

    def _existing_node_capability(self, node: dict[str, Any]) -> str:
        node_type = str(node.get("type") or "")
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if node_type == "githubNode":
            return (
                "github_pr_comment"
                if data.get("action") == "comment_pr"
                else "github_pr_read"
            )
        definition = node_definition(node_type) or {}
        capabilities = definition.get("capabilities") or []
        return str(capabilities[0]) if capabilities else "unknown"

    def _build_modify_preview_graph(
        self,
        structured: AgentBuilderStructuredRequest,
        *,
        workflow: Workflow,
        kb_bindings: list[dict[str, Any]],
        target_resolution: dict[str, Any],
    ) -> dict[str, Any]:
        if target_resolution.get("status") != "resolved":
            raise ValueError("Workflow edit target is not resolved")

        raw_graph = workflow.graph or _empty_graph()
        graph = _redact_graph_for_preview(raw_graph)
        raw_node_by_id = {
            str(node.get("id")): node
            for node in raw_graph.get("nodes") or []
            if node.get("id")
        }
        raw_edge_by_id = {
            str(edge.get("id")): edge
            for edge in raw_graph.get("edges") or []
            if edge.get("id")
        }
        source_id = str(target_resolution.get("source_node_id") or "")
        destination_id = target_resolution.get("destination_node_id")
        source_node = raw_node_by_id.get(source_id)
        if source_node is None:
            raise ValueError("Workflow edit source node is not available")

        _entry_capability, body_capabilities = self._ordered_preview_capabilities(
            structured
        )
        if not body_capabilities:
            raise ValueError("Workflow edit has no new capability")

        existing_ids = _graph_node_ids(graph)
        reserved_ids = set(existing_ids)
        suffix = uuid.uuid4().hex[:8]
        uses_llm = any(
            capability in {"llm", "knowledge_backed_llm"}
            for capability in body_capabilities
        )
        model_id = self._recommended_draft_model_id() if uses_llm else None
        kb_refs = (
            [
                {
                    "id": item["safe_handle"],
                    "name": _safe_display_label(item.get("name")),
                    "reference_type": "safe_candidate_handle",
                }
                for item in kb_bindings
            ]
            if uses_llm
            else []
        )

        source_capability = self._existing_node_capability(source_node)
        source_output_key = CAPABILITY_OUTPUT_KEYS.get(source_capability, "result")
        generated_nodes: list[dict[str, Any]] = []
        generated_node_ids: list[str] = []
        current_source_id = source_id
        current_output_key = source_output_key
        for capability in body_capabilities:
            node_id = self._unique_node_id(
                CAPABILITY_NODE_PREFIXES[capability],
                reserved_ids,
                suffix,
            )
            generated_nodes.append(
                self._build_capability_preview_node(
                    capability,
                    node_id,
                    source_id=current_source_id,
                    source_output_key=current_output_key,
                    entry_id=source_id,
                    entry_capability=source_capability,
                    model_id=model_id,
                    kb_refs=kb_refs,
                )
            )
            generated_node_ids.append(node_id)
            reserved_ids.add(node_id)
            current_source_id = node_id
            current_output_key = CAPABILITY_OUTPUT_KEYS[capability]

        replaced_edge_ids = set(target_resolution.get("replaced_edge_ids") or [])
        replaced_edge = next(
            (
                raw_edge_by_id[edge_id]
                for edge_id in replaced_edge_ids
                if edge_id in raw_edge_by_id
            ),
            None,
        )
        graph["edges"] = [
            edge
            for edge in graph.get("edges") or []
            if str(edge.get("id")) not in replaced_edge_ids
        ]
        generated_edges: list[dict[str, Any]] = [
            {
                "id": f"edge-{source_id}-{generated_node_ids[0]}",
                "source": source_id,
                "sourceHandle": replaced_edge.get("sourceHandle")
                if replaced_edge
                else None,
                "target": generated_node_ids[0],
            }
        ]
        generated_edges.extend(
            {
                "id": f"edge-{left}-{right}",
                "source": left,
                "target": right,
            }
            for left, right in zip(generated_node_ids, generated_node_ids[1:])
        )
        if destination_id:
            generated_edges.append(
                {
                    "id": f"edge-{generated_node_ids[-1]}-{destination_id}",
                    "source": generated_node_ids[-1],
                    "target": str(destination_id),
                    "targetHandle": replaced_edge.get("targetHandle")
                    if replaced_edge
                    else None,
                }
            )

        graph["nodes"] = (graph.get("nodes") or []) + generated_nodes
        graph["edges"] = (graph.get("edges") or []) + generated_edges
        graph = _layout_generated_preview_nodes(
            graph,
            generated_node_ids,
            anchor_node_id=source_id,
        )
        graph.setdefault("viewport", {"x": 0, "y": 0, "zoom": 1})
        return graph

    def _build_preview_graph(
        self,
        structured: AgentBuilderStructuredRequest,
        *,
        workflow: Workflow | None,
        kb_bindings: list[dict[str, Any]],
        selected_node_id: str | None = None,
        selected_edge_id: str | None = None,
        target_resolution: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if structured.draft_mode == "modify_workflow":
            if workflow is None:
                raise ValueError("Workflow edit requires an existing workflow")
            if target_resolution is None:
                target_resolution = self._resolve_edit_target(
                    structured,
                    workflow=workflow,
                    selected_node_id=selected_node_id,
                    selected_edge_id=selected_edge_id,
                )
            return self._build_modify_preview_graph(
                structured,
                workflow=workflow,
                kb_bindings=kb_bindings,
                target_resolution=target_resolution,
            )

        graph = _redact_graph_for_preview(workflow.graph if workflow else _empty_graph())
        graph = _empty_graph()
        existing_ids = _graph_node_ids(graph)
        suffix = uuid.uuid4().hex[:8]
        entry_capability, body_capabilities = self._ordered_preview_capabilities(
            structured
        )
        input_id = self._unique_node_id("agent-input", existing_ids, suffix)
        input_output_key = CAPABILITY_OUTPUT_KEYS[entry_capability]
        generated_nodes = [
            self._build_entry_preview_node(entry_capability, input_id)
        ]
        generated_node_ids_for_layout = [input_id]
        reserved_ids = existing_ids | {input_id}

        uses_llm = any(
            capability in {"llm", "knowledge_backed_llm"}
            for capability in body_capabilities
        )
        model_id = self._recommended_draft_model_id() if uses_llm else None
        kb_refs = (
            [
                {
                    "id": item["safe_handle"],
                    "name": _safe_display_label(item.get("name")),
                    "reference_type": "safe_candidate_handle",
                }
                for item in kb_bindings
            ]
            if uses_llm
            else []
        )
        source_id = input_id
        source_output_key = input_output_key
        for capability in body_capabilities:
            prefix = CAPABILITY_NODE_PREFIXES[capability]
            node_id = self._unique_node_id(prefix, reserved_ids, suffix)
            generated_nodes.append(
                self._build_capability_preview_node(
                    capability,
                    node_id,
                    source_id=source_id,
                    source_output_key=source_output_key,
                    entry_id=input_id,
                    entry_capability=entry_capability,
                    model_id=model_id,
                    kb_refs=kb_refs,
                )
            )
            reserved_ids.add(node_id)
            generated_node_ids_for_layout.append(node_id)
            source_id = node_id
            source_output_key = CAPABILITY_OUTPUT_KEYS[capability]

        answer_id = self._unique_node_id("agent-answer", reserved_ids, suffix)
        generated_nodes.append(
            {
                "id": answer_id,
                "type": "answerNode",
                "position": {"x": 0, "y": 0},
                "data": {
                    "title": "응답",
                    "outputs": [
                        {
                            "variable": "answer",
                            "value_selector": [source_id, source_output_key],
                        }
                    ],
                },
            }
        )
        generated_node_ids_for_layout.append(answer_id)
        generated_edges = [
            {
                "id": f"edge-{source['id']}-{target['id']}",
                "source": source["id"],
                "target": target["id"],
            }
            for source, target in zip(generated_nodes, generated_nodes[1:])
        ]
        graph["nodes"] = (graph.get("nodes") or []) + generated_nodes
        graph["edges"] = (graph.get("edges") or []) + generated_edges
        graph = _layout_generated_preview_nodes(
            graph,
            generated_node_ids_for_layout,
            anchor_node_id=None,
        )
        graph.setdefault("viewport", {"x": 0, "y": 0, "zoom": 1})
        return graph

    def _recommended_draft_model_id(self) -> str | None:
        if not isinstance(self.db, Session):
            return None
        recommendation = LLMService.get_agent_builder_draft_model_recommendation(
            self.db,
            self.user.id,
            self.organization_id,
        )
        if recommendation is None:
            return None
        return recommendation.model.model_id_for_api_call

    def _node_configuration_issues(
        self,
        graph: dict[str, Any],
    ) -> list[AgentBuilderNodeConfigurationIssue]:
        issues: list[AgentBuilderNodeConfigurationIssue] = []
        for node in graph.get("nodes") or []:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            if data.get("configuration_state") != "unresolved":
                continue

            node_type = str(node.get("type") or "")
            definition = node_definition(node_type)
            if not definition or not definition.get("agent_builder_supported"):
                continue
            required_parameters = definition.get("required_configuration") or []
            parameter_labels = definition.get("configuration_labels") or {}
            capabilities = definition.get("capabilities") or []
            if node_type == "githubNode":
                capability = (
                    "github_pr_comment"
                    if data.get("action") == "comment_pr"
                    else "github_pr_read"
                )
            else:
                capability = str(capabilities[0]) if capabilities else node_type

            node_id = str(node.get("id") or "")
            if not node_id:
                continue
            issues.append(
                AgentBuilderNodeConfigurationIssue(
                    node_id=node_id,
                    node_type=node_type,
                    node_label=_safe_display_label(
                        data.get("title") or definition.get("node_type")
                    ),
                    capability=capability,
                    missing_parameters=[
                        AgentBuilderMissingParameter(
                            key=str(parameter),
                            label=str(
                                parameter_labels.get(parameter) or parameter
                            )[:120],
                        )
                        for parameter in required_parameters
                    ],
                )
            )
        return issues

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
            messages=self._session_messages(latest_request, latest_draft),
            pending_request=self._request_summary(latest_request)
            if latest_request and latest_request.status == "processing"
            else None,
            draft_preview=self._draft_summary(latest_draft) if latest_draft else None,
        )

    def _session_messages(
        self,
        latest_request: AgentBuilderRequest | None,
        latest_draft: AgentBuilderDraft | None,
    ) -> list[dict[str, Any]]:
        if latest_request is None:
            return []
        messages: list[dict[str, Any]] = []
        if latest_request.message_summary:
            messages.append(
                {
                    "kind": "user",
                    "request_id": str(latest_request.id),
                    "content": latest_request.message_summary,
                    "redacted": True,
                }
            )
        messages.append(
            {
                "kind": "assistant",
                "request_id": str(latest_request.id),
                "response": self._message_payload_with_latest_preview(
                    latest_request,
                    latest_draft,
                ),
            }
        )
        return messages

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
        if (
            draft.status == "ready"
            and (draft.validation_result or {}).get("valid", False)
            and not (draft.expires_at and draft.expires_at < _now())
        ):
            return AgentBuilderDraftPreview(
                draft_id=draft.id,
                preview_graph=draft.preview_graph,
                base_graph_hash=draft.base_graph_hash,
                base_workflow_updated_at=draft.base_workflow_updated_at,
                draft_mode=draft.draft_mode,
                node_detail_previews=draft.node_detail_previews,
                validation_result=AgentBuilderValidationResult.model_validate(
                    draft.validation_result
                ),
                safety_notices=self._safety_notices_for_draft(draft),
                configuration_issues=self._node_configuration_issues(
                    draft.preview_graph
                ),
            ).model_dump(mode="json")
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
                safety_notices=self._safety_notices_for_draft(draft),
                configuration_issues=self._node_configuration_issues(
                    draft.preview_graph
                ),
            ).model_dump(mode="json")
        return payload

    def _selected_knowledge_candidate_context(
        self,
        session: AgentBuilderSession,
        message_request: AgentBuilderMessageRequest,
        *,
        current_request_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        if message_request.selected_knowledge_candidates is not None:
            selections = list(message_request.selected_knowledge_candidates)
        elif message_request.selected_knowledge_candidate is not None:
            selections = [message_request.selected_knowledge_candidate]
        else:
            return None
        now = _now()
        request_filters = [
            AgentBuilderRequest.session_id == session.id,
            AgentBuilderRequest.user_id == self.user.id,
            AgentBuilderRequest.organization_id == self.organization_id,
            or_(
                AgentBuilderRequest.expires_at.is_(None),
                AgentBuilderRequest.expires_at > now,
            ),
        ]
        if current_request_id is not None:
            request_filters.append(AgentBuilderRequest.id != current_request_id)
        previous_request = (
            self.db.query(AgentBuilderRequest)
            .filter(*request_filters)
            .order_by(AgentBuilderRequest.created_at.desc())
            .first()
        )
        if previous_request is None:
            return {"error": "missing_prior_clarification"}
        if getattr(previous_request, "status", None) != "clarification_required":
            return {"error": "prior_clarification_not_pending"}

        response_payload = previous_request.response_payload or {}
        options = response_payload.get("clarification_options") or []
        structured_payload = previous_request.structured_request or response_payload.get(
            "structured_request"
        )
        try:
            structured = AgentBuilderStructuredRequest.model_validate(
                structured_payload
            )
        except Exception:
            return {"error": "structured_request_unavailable"}
        if not selections:
            return {
                "structured_request": structured,
                "candidate_handles": {NO_KB_CANDIDATE_ID},
            }
        candidate_handles: set[str] = set()
        for selection in selections:
            matched = None
            candidate_id = selection.candidate_id
            for option in options:
                if str(option.get("candidate_id")) != candidate_id:
                    continue
                if selection.resolution_id and str(option.get("resolution_id")) != str(
                    selection.resolution_id
                ):
                    continue
                if selection.requirement_id and str(option.get("requirement_id")) != str(
                    selection.requirement_id
                ):
                    continue
                matched = option
                break
            if matched is None:
                return {"error": "candidate_not_in_prior_options"}
            candidate_handles.add(candidate_id)
        return {
            "structured_request": structured,
            "candidate_handles": candidate_handles,
        }

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
