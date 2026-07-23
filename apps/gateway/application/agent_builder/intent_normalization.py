from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections.abc import Iterable
from functools import lru_cache
from pathlib import Path
from typing import Literal, final

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    IntentNormalizationResult,
    IntentPlanningContext,
)

NORMALIZER_VERSION = "intent-normalizer-v2"

_CATALOG_PATH = (
    Path(__file__).resolve().parents[3]
    / "shared/config/workflow_node_catalog.json"
)

_SIGNATURE_DOMAIN = b"agent-builder:intent-normalization\x00"
_MAX_FULL_SAFE_MESSAGE_CODEPOINTS = 4000
_WORD_RE = re.compile(r"\w+", re.UNICODE)
_SINGLE_LEXICAL_TOKEN_RE = re.compile(r"^[^\W_]+$", re.UNICODE)
_LINEBREAK_OR_TAB_RE = re.compile(r"[\t\r\n]+")
_SPACE_RUN_RE = re.compile(r" {2,}")
_REDACTION_MARKER_RE = re.compile(
    r"(?:"
    r"\[\s*redacted\s*\]|"
    r"<\s*redacted\s*>|"
    r"\*{2,}\s*redacted\s*\*{2,}"
    r")",
    re.IGNORECASE,
)
_SECRET_VALUE_RE = re.compile(
    r"(?:"
    r"sk-[A-Za-z0-9_-]{8,}|"
    r"gh[oprsu]_[A-Za-z0-9_]{8,}|"
    r"xox[baprs]-[A-Za-z0-9-]{8,}|"
    r"bearer\s+[A-Za-z0-9._~+/=-]{8,}|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"(?:api[_\s-]?key|token|password|secret|authorization|credential|"
    r"비밀번호|암호|토큰|시크릿|인증키)\s*[:=]\s*\S+|"
    r"(?:api[_\s-]?key|token|password|secret|authorization|credential|비밀번호|암호|토큰|시크릿|인증키)\s+\S+"
    r")",
    re.IGNORECASE,
)
_TRUNCATION_MARKER_RE = re.compile(
    r"(?:\[\s*truncated\s*\]|<\s*truncated\s*>|…\s*\[\s*truncated\s*\])",
    re.IGNORECASE,
)
_URL_VALUE_RE = re.compile(
    r"(?:https?|redis|rediss|postgres(?:ql)?)://\S+",
    re.IGNORECASE,
)
_GENERIC_ASSIGNMENT_RE = re.compile(
    r"(?<!\w)[A-Za-z_][A-Za-z0-9_.-]{0,63}\s*[:=]\s*\S+"
)
_MODIFY_ACTION_TOKENS = frozenset(
    {
        "change",
        "delete",
        "modify",
        "remove",
        "update",
        "변경",
        "변경해",
        "삭제",
        "삭제해",
        "수정",
        "수정해",
        "제거",
        "제거해",
    }
)

_QUOTE_PAIRS = {
    '"': '"',
    "'": "'",
    "“": "”",
    "‘": "’",
    "「": "」",
    "『": "』",
}

# These exact tokens only admit a request into the v1 grammar. They are never
# rewritten, removed, reordered, or treated as aliases for one another.
_ELIGIBILITY_LITERAL_TOKENS_V1 = frozenset(
    {
        "add",
        "after",
        "before",
        "between",
        "create",
        "current",
        "edge",
        "existing",
        "node",
        "not",
        "selected",
        "step",
        "기존",
        "노드",
        "노드를",
        "뒤에",
        "마",
        "사이에",
        "선택한",
        "앞에",
        "이름",
        "인",
        "추가",
        "추가하지",
    }
) | _MODIFY_ACTION_TOKENS
_NUMBER_OR_COUNTER_TOKEN_RE = re.compile(r"^\d+(?:개|번)?$", re.UNICODE)

_SegmentKind = Literal["literal", "catalog_capability", "catalog_node"]
_Segment = tuple[_SegmentKind, str]


def _expression_cleanup(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = _LINEBREAK_OR_TAB_RE.sub(" ", normalized)
    normalized = _SPACE_RUN_RE.sub(" ", normalized)
    return normalized.strip(" ")


@lru_cache(maxsize=1)
def _load_catalog_normalization_metadata() -> dict[str, object]:
    catalog = json.loads(_CATALOG_PATH.read_text(encoding="utf-8"))
    if catalog.get("version") != 3:
        raise RuntimeError("unsupported workflow node catalog version")
    if not isinstance(catalog.get("capability_contracts"), dict):
        raise RuntimeError("workflow node catalog capability contracts are missing")
    if not isinstance(catalog.get("nodes"), list):
        raise RuntimeError("workflow node catalog nodes are missing")
    return catalog


def _catalog_exact_token_map() -> dict[str, _Segment]:
    catalog = _load_catalog_normalization_metadata()
    token_map: dict[str, _Segment] = {}

    nodes = catalog["nodes"]
    assert isinstance(nodes, list)
    supported_nodes: list[dict[str, object]] = []
    supported_capabilities: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict) or not isinstance(node.get("node_type"), str):
            raise RuntimeError("workflow node catalog node is invalid")
        if not (
            node.get("implemented") is True
            and node.get("agent_builder_supported") is True
        ):
            continue
        capabilities = node.get("capabilities")
        if not isinstance(capabilities, list) or any(
            not isinstance(capability, str) for capability in capabilities
        ):
            raise RuntimeError("workflow node catalog capabilities are invalid")
        supported_nodes.append(node)
        supported_capabilities.update(capabilities)

    contracts = catalog["capability_contracts"]
    assert isinstance(contracts, dict)
    for capability, contract in contracts.items():
        if capability not in supported_capabilities:
            continue
        if not isinstance(contract, dict) or not isinstance(
            contract.get("planner_aliases"), list
        ):
            raise RuntimeError("workflow node catalog aliases are invalid")
        for raw_alias in contract["planner_aliases"]:
            if not isinstance(raw_alias, str) or not raw_alias:
                raise RuntimeError("workflow node catalog alias is invalid")
            alias = _expression_cleanup(raw_alias)
            if _SINGLE_LEXICAL_TOKEN_RE.fullmatch(alias) is None:
                continue
            key = alias.casefold()
            segment: _Segment = ("catalog_capability", str(capability))
            existing = token_map.get(key)
            if existing is not None and existing != segment:
                raise RuntimeError("catalog exact alias maps to multiple capabilities")
            token_map[key] = segment

    for node in supported_nodes:
        node_type = str(node["node_type"])
        node_capabilities = node.get("capabilities")
        assert isinstance(node_capabilities, list)
        candidates = [node_type]
        if node_type.endswith("Node"):
            candidates.append(node_type[: -len("Node")])
        for raw_token in candidates:
            token = _expression_cleanup(raw_token)
            if _SINGLE_LEXICAL_TOKEN_RE.fullmatch(token) is None:
                continue
            key = token.casefold()
            existing = token_map.get(key)
            if existing is not None:
                if (
                    existing[0] == "catalog_capability"
                    and existing[1] in node_capabilities
                ):
                    continue
                if existing == ("catalog_node", node_type):
                    continue
                raise RuntimeError(
                    "catalog exact node token maps to conflicting capability"
                )
            token_map.setdefault(key, ("catalog_node", node_type))

    return token_map


_CATALOG_EXACT_TOKENS = _catalog_exact_token_map()


def _catalog_parameter_alternatives() -> tuple[str, str]:
    catalog = _load_catalog_normalization_metadata()
    nodes = catalog["nodes"]
    assert isinstance(nodes, list)
    parameter_keys: set[str] = set()
    parameter_labels: set[str] = set()
    for node in nodes:
        if not isinstance(node, dict):
            continue
        for parameter in node.get("parameters") or ():
            if not isinstance(parameter, dict):
                continue
            key = parameter.get("key")
            if isinstance(key, str) and key:
                parameter_keys.add(key)
            label = parameter.get("label")
            if isinstance(label, str):
                normalized_label = _expression_cleanup(label)
                if normalized_label:
                    parameter_labels.add(normalized_label)
    return (
        "|".join(
            re.escape(key) for key in sorted(parameter_keys, key=len, reverse=True)
        ),
        "|".join(
            re.escape(label) for label in sorted(parameter_labels, key=len, reverse=True)
        ),
    )


(
    _CATALOG_PARAMETER_KEY_ALTERNATIVES,
    _CATALOG_PARAMETER_LABEL_ALTERNATIVES,
) = _catalog_parameter_alternatives()


def _catalog_parameter_assignment_re() -> re.Pattern[str]:
    return re.compile(
        rf"(?<!\w)(?:{_CATALOG_PARAMETER_KEY_ALTERNATIVES})(?!\w)\s*(?:"
        rf"[:=]|(?:is|are|to|은|는|을|를|로|으로)\s+\S)",
        re.IGNORECASE,
    )


_CATALOG_PARAMETER_ASSIGNMENT_RE = _catalog_parameter_assignment_re()


def _catalog_parameter_shorthand_re(alternatives: str) -> re.Pattern[str]:
    if not alternatives:
        return re.compile(r"(?!x)x")
    return re.compile(
        rf"(?<!\w)(?:{alternatives})(?!\w)\s+\S+",
        re.IGNORECASE,
    )


_CATALOG_PARAMETER_SHORTHAND_RE = _catalog_parameter_shorthand_re(
    _CATALOG_PARAMETER_KEY_ALTERNATIVES,
)
_CATALOG_PARAMETER_LABEL_SHORTHAND_RE = _catalog_parameter_shorthand_re(
    _CATALOG_PARAMETER_LABEL_ALTERNATIVES,
)


def _quoted_ranges(value: str) -> tuple[tuple[int, int], ...] | None:
    ranges: list[tuple[int, int]] = []
    index = 0
    while index < len(value):
        closer = _QUOTE_PAIRS.get(value[index])
        if closer is None:
            index += 1
            continue
        end = index + 1
        closed = False
        while end < len(value):
            if value[end] == "\\":
                end += 2
                continue
            if value[end] == closer:
                end += 1
                closed = True
                break
            end += 1
        if not closed:
            return None
        ranges.append((index, end))
        index = end
    return tuple(ranges)


def _unquoted_words(value: str) -> tuple[str, ...] | None:
    quoted_ranges = _quoted_ranges(value)
    if quoted_ranges is None:
        return None

    words: list[str] = []
    cursor = 0
    for start, end in quoted_ranges:
        words.extend(
            match.group(0).casefold()
            for match in _WORD_RE.finditer(value[cursor:start])
        )
        cursor = end
    words.extend(
        match.group(0).casefold()
        for match in _WORD_RE.finditer(value[cursor:])
    )
    return tuple(words)


def _append_segment(segments: list[_Segment], segment: _Segment) -> None:
    kind, value = segment
    if not value:
        return
    if kind == "literal" and segments and segments[-1][0] == "literal":
        previous_kind, previous_value = segments[-1]
        segments[-1] = (previous_kind, previous_value + value)
        return
    segments.append(segment)


def _is_allowed_literal_token(raw_token: str) -> bool:
    return bool(
        raw_token.casefold() in _ELIGIBILITY_LITERAL_TOKENS_V1
        or _NUMBER_OR_COUNTER_TOKEN_RE.fullmatch(raw_token)
    )


def _canonicalize_unquoted(value: str) -> list[_Segment] | None:
    segments: list[_Segment] = []
    cursor = 0
    for match in _WORD_RE.finditer(value):
        _append_segment(segments, ("literal", value[cursor : match.start()]))
        raw_token = match.group(0)
        canonical = _CATALOG_EXACT_TOKENS.get(raw_token.casefold())
        if canonical is None:
            canonical = ("literal", raw_token)
        _append_segment(segments, canonical)
        cursor = match.end()
    _append_segment(segments, ("literal", value[cursor:]))
    return segments


def _canonical_segments(value: str) -> tuple[_Segment, ...] | None:
    quoted_ranges = _quoted_ranges(value)
    if quoted_ranges is None:
        return None

    segments: list[_Segment] = []
    cursor = 0
    for start, end in quoted_ranges:
        unquoted_segments = _canonicalize_unquoted(value[cursor:start])
        if unquoted_segments is None:
            return None
        for segment in unquoted_segments:
            _append_segment(segments, segment)
        _append_segment(segments, ("literal", value[start:end]))
        cursor = end

    unquoted_segments = _canonicalize_unquoted(value[cursor:])
    if unquoted_segments is None:
        return None
    for segment in unquoted_segments:
        _append_segment(segments, segment)

    return tuple(segments)


def _signature(segments: Iterable[_Segment]) -> str:
    projection = json.dumps(
        {
            "normalizer_version": NORMALIZER_VERSION,
            "segments": list(segments),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(_SIGNATURE_DOMAIN + projection).hexdigest()


def _bypass(
    reason: Literal[
        "sensitive_input",
        "explicit_value_suspected",
        "unknown_token_sequence",
        "ambiguous_target",
        "unsupported_request_shape",
        "normalizer_disabled",
        "input_projection_truncated",
    ],
) -> IntentNormalizationResult:
    return IntentNormalizationResult(
        status="bypass",
        intent_signature=None,
        reason=reason,
        normalizer_version=NORMALIZER_VERSION,
        sensitive_input_detected=reason == "sensitive_input",
    )


def _has_quoted_parameter_value(value: str) -> bool:
    quoted_ranges = _quoted_ranges(value)
    if quoted_ranges is None:
        return False
    return any(
        _CATALOG_PARAMETER_SHORTHAND_RE.search(value[start + 1 : end - 1])
        or _CATALOG_PARAMETER_LABEL_SHORTHAND_RE.search(value[start + 1 : end - 1])
        for start, end in quoted_ranges
    )


def _has_explicit_parameter_value(value: str) -> bool:
    return bool(
        _URL_VALUE_RE.search(value)
        or _CATALOG_PARAMETER_ASSIGNMENT_RE.search(value)
        or _GENERIC_ASSIGNMENT_RE.search(value)
        or _has_quoted_parameter_value(value)
    )


@final
class DeterministicIntentNormalizer:
    __slots__ = ()

    def normalize(
        self,
        context: IntentPlanningContext,
    ) -> IntentNormalizationResult:
        if not isinstance(context, IntentPlanningContext):
            return _bypass("normalizer_disabled")
        if context.contract_versions.normalizer_version != NORMALIZER_VERSION:
            return _bypass("unsupported_request_shape")

        raw_message = context.full_safe_message
        normalized = _expression_cleanup(raw_message)
        if (
            _REDACTION_MARKER_RE.search(raw_message)
            or _REDACTION_MARKER_RE.search(normalized)
            or _SECRET_VALUE_RE.search(raw_message)
            or _SECRET_VALUE_RE.search(normalized)
        ):
            return _bypass("sensitive_input")
        if (
            len(raw_message) >= _MAX_FULL_SAFE_MESSAGE_CODEPOINTS
            or _TRUNCATION_MARKER_RE.search(raw_message)
            or _TRUNCATION_MARKER_RE.search(normalized)
        ):
            return _bypass("input_projection_truncated")

        if not normalized:
            return _bypass("unsupported_request_shape")
        if _WORD_RE.search(normalized) is None:
            return _bypass("unsupported_request_shape")
        if _has_explicit_parameter_value(normalized):
            return _bypass("explicit_value_suspected")
        unquoted_words = _unquoted_words(normalized)
        if unquoted_words is None:
            return _bypass("unknown_token_sequence")
        selected_target_type = object.__getattribute__(
            context.scope,
            "_selected_target_type",
        )
        if selected_target_type is None and any(
            word in _MODIFY_ACTION_TOKENS for word in unquoted_words
        ):
            return _bypass("ambiguous_target")

        segments = _canonical_segments(normalized)
        if segments is None:
            return _bypass("unknown_token_sequence")
        return IntentNormalizationResult(
            status="eligible",
            intent_signature=_signature(segments),
            reason=None,
            normalizer_version=NORMALIZER_VERSION,
            sensitive_input_detected=False,
        )

    def __repr__(self) -> str:
        return f"<DeterministicIntentNormalizer {NORMALIZER_VERSION}>"
