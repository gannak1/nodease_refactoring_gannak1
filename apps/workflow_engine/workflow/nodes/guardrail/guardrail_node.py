"""Guardrail Node 구현"""

import re
from typing import Any, Dict, Iterable, List

from apps.workflow_engine.workflow.core.utils import get_nested_value
from apps.workflow_engine.workflow.nodes.base.node import Node

from .entities import GuardrailNodeData


class GuardrailNode(Node[GuardrailNodeData]):
    """
    입력 텍스트를 검사하거나 민감 문자열을 정제하는 노드입니다.

    현재 런타임은 키워드/정규식 기반의 결정적 검사만 수행합니다. LLM 호출 기반
    정책 판단은 후속 노드 확장에서 다룹니다.
    """

    node_type = "guardrailNode"

    def _run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        text = self._resolve_input_text(inputs)

        if self.data.operation == "sanitize_text":
            sanitized_text, matched = self._sanitize_text(text)
            return {
                "result": True,
                "blocked": False,
                "sanitized_text": sanitized_text,
                "text": sanitized_text,
                "matched": matched,
            }

        matched = self._find_matches(text)
        blocked = bool(matched)
        selected_handle = (
            self.data.fail_handle_id if blocked else self.data.pass_handle_id
        )
        output = {
            "result": not blocked,
            "blocked": blocked,
            "allowed": not blocked,
            "text": text,
            "matched": matched,
            "matched_keywords": matched,
            "selected_handle": selected_handle,
            "reason": "policy_violation" if blocked else "allowed",
        }

        if not self.data.branching_enabled:
            output.pop("selected_handle", None)

        return output

    def _resolve_input_text(self, inputs: Dict[str, Any]) -> str:
        selector = self.data.input_selector or []
        value: Any = None

        if selector:
            source_data = inputs.get(selector[0])
            value = get_nested_value(source_data, selector[1:]) if len(selector) > 1 else source_data

        if value is None and self.data.text_to_check:
            value = self.data.text_to_check

        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return str(value)

    def _find_matches(self, text: str) -> List[str]:
        normalized_text = text.lower()
        matches: List[str] = []

        if self.data.branch_condition == "regex_match":
            regex_matches = self._regex_matches(text)
            matches.extend(regex_matches)
        else:
            for keyword in self._keywords():
                normalized_keyword = keyword.lower()
                if normalized_keyword and normalized_keyword in normalized_text:
                    matches.append(keyword)

        for pattern_name, pattern in self._built_in_patterns().items():
            if re.search(pattern, text, flags=re.IGNORECASE):
                matches.append(pattern_name)

        return self._deduplicate(matches)

    def _keywords(self) -> Iterable[str]:
        keywords = list(self.data.match_keywords or [])
        if self.data.custom_keywords:
            keywords.extend(
                item.strip()
                for item in re.split(r"[,;\n]", self.data.custom_keywords)
                if item.strip()
            )

        guardrails = set(self.data.guardrails or [])
        if "Jailbreak" in guardrails:
            keywords.extend(
                [
                    "ignore previous instructions",
                    "이전 지시를 무시",
                    "권한 우회",
                    "승인 우회",
                    "관리자 승인 없이",
                ]
            )
        if "Topical Alignment" in guardrails:
            keywords.extend(["운영 DB", "내부 API 키", "시크릿", "토큰"])

        return keywords

    def _regex_matches(self, text: str) -> List[str]:
        if not self.data.custom_regex:
            return []

        try:
            return (
                ["custom_regex"]
                if re.search(self.data.custom_regex, text, flags=re.IGNORECASE)
                else []
            )
        except re.error:
            return []

    def _built_in_patterns(self) -> Dict[str, str]:
        guardrails = set(self.data.guardrails or [])
        patterns: Dict[str, str] = {}

        if "Personal Data (PII)" in guardrails or "PII" in guardrails:
            patterns["pii"] = (
                r"(\b\d{6}[- ]?\d{7}\b)|"
                r"(\b01[016789][- ]?\d{3,4}[- ]?\d{4}\b)|"
                r"([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})|"
                r"(병가 기록|인사평가|개인정보)"
            )

        if "Secret Keys" in guardrails:
            patterns["secret_keys"] = (
                r"(?i)(api[_-]?key|secret|token|password|xoxb-|sk-[A-Za-z0-9])"
            )

        if "URLs" in guardrails:
            patterns["url"] = r"https?://[^\s]+"

        if "NSFW" in guardrails:
            patterns["nsfw"] = r"(성인|음란|폭력|혐오)"

        return patterns

    def _sanitize_text(self, text: str) -> tuple[str, List[str]]:
        matched: List[str] = []
        sanitized = text

        for name, pattern in self._built_in_patterns().items():
            sanitized_next = re.sub(pattern, "[REDACTED]", sanitized, flags=re.IGNORECASE)
            if sanitized_next != sanitized:
                matched.append(name)
                sanitized = sanitized_next

        for keyword in self._keywords():
            if keyword and keyword.lower() in sanitized.lower():
                matched.append(keyword)
                sanitized = re.sub(
                    re.escape(keyword),
                    "[REDACTED]",
                    sanitized,
                    flags=re.IGNORECASE,
                )

        return sanitized, self._deduplicate(matched)

    @staticmethod
    def _deduplicate(items: Iterable[str]) -> List[str]:
        seen = set()
        result: List[str] = []
        for item in items:
            if item in seen:
                continue
            seen.add(item)
            result.append(item)
        return result
