from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from string import Formatter
from types import MappingProxyType

from apps.gateway.application.agent_builder.intent_cache.catalog_snapshot import (
    CANONICAL_GUIDANCE_REASON_REFS,
    CANONICAL_INPUT_GUIDANCE_REFS,
    CANONICAL_KNOWLEDGE_TOPIC_REFS,
    CAPABILITY_PARAMETER_INPUT_TYPES,
    CAPABILITY_PURPOSES,
    SUMMARY_PROJECTION_DESCRIPTOR,
)
from apps.shared.domain.app_auth_secret import APP_AUTH_SECRET_PREFIX


class RegistryContractError(RuntimeError):
    """The static text registry does not implement its closed contract."""


class CanonicalReferenceError(ValueError):
    """A closed canonical reference cannot be rendered."""


class GuidanceInputTypeError(ValueError):
    """A guidance template is not applicable to the current Catalog member."""


@dataclass(frozen=True, slots=True)
class TopicEntry:
    ref: str
    canonical_text: str
    aliases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GuidanceTemplateEntry:
    ref: str
    canonical_template: str
    aliases: tuple[str, ...]
    allowed_input_types: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SummaryProjectionEntry:
    projection_id: str
    source: str
    max_codepoints: int
    whitespace_profile: str
    redaction_profile: str


@dataclass(frozen=True, slots=True)
class IntentTextManifest:
    registry_version: str
    summary_projection: SummaryProjectionEntry
    topics: tuple[TopicEntry, ...]
    reason_templates: tuple[GuidanceTemplateEntry, ...]
    input_guidance_templates: tuple[GuidanceTemplateEntry, ...]


_GENERIC_GUIDANCE_REASON_REF = "guidance.reason.configuration_required.v1"
_GENERIC_INPUT_GUIDANCE_REF = "guidance.input.provide_parameter_value.v1"
_CURRENT_SAFE_MESSAGE_TOPIC_REF = "topic.current_safe_message.v1"
_SPECIFIC_SLACK_GUIDANCE_REFS = (
    "guidance.reason.delivery_destination_required.v1",
    "guidance.input.select_slack_channel_id.v1",
)
_GENERIC_GUIDANCE_REFS = (
    _GENERIC_GUIDANCE_REASON_REF,
    _GENERIC_INPUT_GUIDANCE_REF,
)
_GENERIC_GUIDANCE_INPUT_TYPES = tuple(
    sorted(
        {
            input_type
            for parameters in CAPABILITY_PARAMETER_INPUT_TYPES.values()
            for input_type in parameters.values()
        }
    )
)

INTENT_TEXT_V1_MANIFEST = IntentTextManifest(
    registry_version="intent-text-v1",
    summary_projection=SummaryProjectionEntry(
        projection_id="summary.current_safe_message.v1",
        source=SUMMARY_PROJECTION_DESCRIPTOR["source"],
        max_codepoints=240,
        whitespace_profile="python-split-v1",
        redaction_profile="agent-builder-safe-summary-v1",
    ),
    topics=(
        TopicEntry(
            ref=_CURRENT_SAFE_MESSAGE_TOPIC_REF,
            canonical_text="Current safe request",
            aliases=(),
        ),
        TopicEntry(
            ref="topic.internal_documents.v1",
            canonical_text="사내 문서",
            aliases=("내부 문서", "internal documents"),
        ),
    ),
    reason_templates=(
        GuidanceTemplateEntry(
            ref=_GENERIC_GUIDANCE_REASON_REF,
            canonical_template="Additional configuration is required.",
            aliases=(),
            allowed_input_types=_GENERIC_GUIDANCE_INPUT_TYPES,
        ),
        GuidanceTemplateEntry(
            ref="guidance.reason.delivery_destination_required.v1",
            canonical_template="메시지 전달 위치가 필요합니다.",
            aliases=(
                "메시지 목적지가 필요합니다.",
                "전송 대상을 선택해야 합니다.",
                "delivery destination required",
            ),
            allowed_input_types=("text",),
        ),
    ),
    input_guidance_templates=(
        GuidanceTemplateEntry(
            ref=_GENERIC_INPUT_GUIDANCE_REF,
            canonical_template="Provide a value for {parameter_key}.",
            aliases=(),
            allowed_input_types=_GENERIC_GUIDANCE_INPUT_TYPES,
        ),
        GuidanceTemplateEntry(
            ref="guidance.input.select_slack_channel_id.v1",
            canonical_template="Slack channel ID를 선택하세요.",
            aliases=(
                "Slack 채널 ID를 선택하세요.",
                "select Slack channel ID",
            ),
            allowed_input_types=("text",),
        ),
    ),
)

_GUIDANCE_CATALOG_CONTEXT = MappingProxyType(
    {("slack_send", "channel"): ("Slack channel", "text")}
)

_ALLOWED_TEMPLATE_FIELDS = frozenset({"parameter_key", "safe_label", "input_type"})

_SECRET_LIKE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|ghp_[A-Za-z0-9_]{8,}|xox[baprs]-[A-Za-z0-9-]{8,}|"
    r"bearer\s+[A-Za-z0-9._\-]{8,}|"
    r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+|"
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


_TRACE_PII_RULES = (
    re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
    re.compile(r"(?<!\w)\+?(?:\d{1,3}[-.\s]?)?(?:\d{2,4}[-.\s]?){2,4}\d{2,4}\b"),
    re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
    re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
)
_TRACE_SECRET_VALUE_RULES = (
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:api[_-]?key|token|secret)\s*[:=]\s*['\"]?[^'\"\s,}]+"),
    re.compile(r"\b(?:github_pat_|gh[oprsu]_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    re.compile(r"\bAIza[0-9A-Za-z_-]{35}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{8,}\b"),
    re.compile(
        rf"(?<![A-Za-z0-9_-]){re.escape(APP_AUTH_SECRET_PREFIX)}"
        r"[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])"
    ),
    re.compile(r"(?<![A-Za-z0-9_-])cag_v1_[A-Za-z0-9_-]{43,128}(?![A-Za-z0-9_-])"),
    re.compile(r"(?<![A-Za-z0-9_-])cpr_v1_[A-Za-z0-9_-]{43,128}(?![A-Za-z0-9_-])"),
    re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
        re.S,
    ),
)


def _normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).casefold()


def _template_fields(template: str) -> frozenset[str]:
    fields: set[str] = set()
    try:
        parsed = Formatter().parse(template)
        for _literal, field_name, _format_spec, _conversion in parsed:
            if field_name is not None:
                fields.add(field_name)
    except ValueError as exc:
        raise RegistryContractError("invalid canonical template") from exc
    return frozenset(fields)


def _validate_entries(entries, expected_refs: frozenset[str], *, template: bool):
    expected_type = GuidanceTemplateEntry if template else TopicEntry
    if type(entries) is not tuple or any(
        type(entry) is not expected_type for entry in entries
    ):
        raise RegistryContractError("registry entry type mismatch")
    for entry in entries:
        canonical = entry.canonical_template if template else entry.canonical_text
        if (
            type(entry.ref) is not str
            or type(canonical) is not str
            or type(entry.aliases) is not tuple
            or any(type(alias) is not str for alias in entry.aliases)
        ):
            raise RegistryContractError("registry text type mismatch")
        if template and (
            type(entry.allowed_input_types) is not tuple
            or any(
                type(input_type) is not str for input_type in entry.allowed_input_types
            )
        ):
            raise RegistryContractError("guidance input type mismatch")
    refs = [entry.ref for entry in entries]
    if len(refs) != len(set(refs)) or frozenset(refs) != expected_refs:
        raise RegistryContractError("closed registry membership mismatch")
    text_owner: dict[str, str] = {}
    for entry in entries:
        canonical = entry.canonical_template if template else entry.canonical_text
        if not canonical or not canonical.strip():
            raise RegistryContractError("empty canonical text")
        values = (canonical, *entry.aliases)
        normalized = tuple(_normalized_text(value) for value in values)
        if any(not value for value in normalized) or len(normalized) != len(
            set(normalized)
        ):
            raise RegistryContractError("duplicate canonical text or alias")
        for value in normalized:
            previous = text_owner.setdefault(value, entry.ref)
            if previous != entry.ref:
                raise RegistryContractError("alias maps to multiple references")
        if template:
            if not entry.allowed_input_types:
                raise RegistryContractError("guidance input type set is empty")
            if len(entry.allowed_input_types) != len(set(entry.allowed_input_types)):
                raise RegistryContractError("duplicate guidance input type")
            if not _template_fields(canonical).issubset(_ALLOWED_TEMPLATE_FIELDS):
                raise RegistryContractError("unsupported template placeholder")


def _validate_global_text_ownership(manifest: IntentTextManifest) -> None:
    owners: dict[str, str] = {}
    groups = (
        (manifest.topics, False),
        (manifest.reason_templates, True),
        (manifest.input_guidance_templates, True),
    )
    for entries, template in groups:
        for entry in entries:
            canonical = entry.canonical_template if template else entry.canonical_text
            for text in (entry.ref, canonical, *entry.aliases):
                normalized = _normalized_text(text)
                if normalized in owners:
                    raise RegistryContractError(
                        "ref, canonical text or alias is duplicated"
                    )
                owners[normalized] = entry.ref


class RequestIntentSummaryProjector:
    def __init__(
        self,
        descriptor: SummaryProjectionEntry | None = None,
    ) -> None:
        self._descriptor = descriptor or INTENT_TEXT_V1_MANIFEST.summary_projection
        expected = SUMMARY_PROJECTION_DESCRIPTOR
        if (
            self._descriptor.projection_id != expected["projection_id"]
            or self._descriptor.source != expected["source"]
            or self._descriptor.max_codepoints != expected["max_codepoints"]
            or self._descriptor.whitespace_profile != expected["whitespace_profile"]
            or self._descriptor.redaction_profile != expected["redaction_profile"]
        ):
            raise RegistryContractError("summary projection contract mismatch")

    def _clean_redacted(self, full_safe_message: str) -> str | None:
        if type(full_safe_message) is not str:
            return None
        cleaned = " ".join(full_safe_message.split())
        try:
            for pattern in _TRACE_SECRET_VALUE_RULES:
                cleaned = pattern.sub("[redacted]", cleaned)
            for pattern in _TRACE_PII_RULES:
                cleaned = pattern.sub("[redacted]", cleaned)
        except Exception:
            return None
        cleaned = cleaned.replace("[REDACTED]", "[redacted]")
        cleaned = _AUTH_HEADER_VALUE_RE.sub("[redacted]", cleaned)
        cleaned = _SECRET_KEY_VALUE_RE.sub("[redacted]", cleaned)
        cleaned = _SECRET_NATURAL_LANGUAGE_RE.sub("[redacted]", cleaned)
        cleaned = _BEARER_VALUE_RE.sub("[redacted]", cleaned)
        cleaned = _URL_VALUE_RE.sub("[redacted]", cleaned)
        cleaned = _PATH_VALUE_RE.sub("[redacted]", cleaned)
        cleaned = _SECRET_LIKE_RE.sub("[redacted]", cleaned)
        if not cleaned or "[redacted]" in cleaned.casefold():
            return None
        return cleaned

    def project(self, full_safe_message: str) -> str | None:
        cleaned = self._clean_redacted(full_safe_message)
        if cleaned is None:
            return None
        return cleaned[: self._descriptor.max_codepoints]

    def project_semantic(self, full_safe_message: str) -> str | None:
        """Return an untruncated safe projection or fail closed above the limit."""
        cleaned = self._clean_redacted(full_safe_message)
        if cleaned is None or len(cleaned) > self._descriptor.max_codepoints:
            return None
        return cleaned


class CanonicalIntentTextRegistry:
    def __init__(
        self,
        manifest: IntentTextManifest = INTENT_TEXT_V1_MANIFEST,
    ) -> None:
        if type(manifest) is not IntentTextManifest:
            raise RegistryContractError("registry manifest type mismatch")
        if manifest.registry_version != "intent-text-v1":
            raise RegistryContractError("registry version mismatch")
        expected_summary = INTENT_TEXT_V1_MANIFEST.summary_projection
        if manifest.summary_projection != expected_summary:
            raise RegistryContractError("summary projection contract mismatch")
        _validate_entries(
            manifest.topics,
            CANONICAL_KNOWLEDGE_TOPIC_REFS,
            template=False,
        )
        _validate_entries(
            manifest.reason_templates,
            CANONICAL_GUIDANCE_REASON_REFS,
            template=True,
        )
        _validate_entries(
            manifest.input_guidance_templates,
            CANONICAL_INPUT_GUIDANCE_REFS,
            template=True,
        )
        _validate_global_text_ownership(manifest)
        if manifest != INTENT_TEXT_V1_MANIFEST:
            raise RegistryContractError("same-version registry manifest drift")
        self._manifest = manifest
        self._topics = {entry.ref: entry for entry in manifest.topics}
        self._reasons = {entry.ref: entry for entry in manifest.reason_templates}
        self._input_guidance = {
            entry.ref: entry for entry in manifest.input_guidance_templates
        }
        self._topic_projection = self._projection_table(
            manifest.topics,
            template=False,
        )
        self._reason_projection = self._projection_table(
            manifest.reason_templates,
            template=True,
        )
        self._input_projection = self._projection_table(
            manifest.input_guidance_templates,
            template=True,
        )
        self._summary_projector = RequestIntentSummaryProjector(
            manifest.summary_projection
        )

    @staticmethod
    def _projection_table(entries, *, template: bool):
        result = {}
        for entry in entries:
            canonical = entry.canonical_template if template else entry.canonical_text
            for value in (canonical, *entry.aliases):
                result[_normalized_text(value)] = entry.ref
        return MappingProxyType(result)

    @property
    def registry_version(self) -> str:
        return self._manifest.registry_version

    @property
    def capability_purposes(self):
        return CAPABILITY_PURPOSES

    def project_topic(self, provider_text: str) -> str | None:
        if type(provider_text) is not str:
            return None
        return self._topic_projection.get(_normalized_text(provider_text))

    def project_current_safe_message_topic(self, full_safe_message: str) -> str | None:
        if self.project_summary(full_safe_message) is None:
            return None
        return _CURRENT_SAFE_MESSAGE_TOPIC_REF

    def project_reason(self, provider_text: str) -> str | None:
        if type(provider_text) is not str:
            return None
        return self._reason_projection.get(_normalized_text(provider_text))

    def project_input_guidance(self, provider_text: str) -> str | None:
        if type(provider_text) is not str:
            return None
        return self._input_projection.get(_normalized_text(provider_text))

    def project_summary(self, full_safe_message: str) -> str | None:
        return self._summary_projector.project(full_safe_message)

    def purpose_for(self, capability: str) -> str:
        try:
            return CAPABILITY_PURPOSES[capability]
        except KeyError as exc:
            raise CanonicalReferenceError("unknown capability purpose") from exc

    def render_topic(self, ref: str, *, full_safe_message: str | None = None) -> str:
        if ref == _CURRENT_SAFE_MESSAGE_TOPIC_REF:
            rendered = self.project_summary(full_safe_message or "")
            if rendered is None:
                raise CanonicalReferenceError("current safe message topic is unavailable")
            return rendered
        try:
            return self._topics[ref].canonical_text
        except KeyError as exc:
            raise CanonicalReferenceError("unknown Knowledge topic reference") from exc

    def guidance_catalog_context(
        self,
        capability: str,
        parameter_key: str,
    ) -> tuple[str, str]:
        context = _GUIDANCE_CATALOG_CONTEXT.get((capability, parameter_key))
        if context is not None:
            return context
        input_type = CAPABILITY_PARAMETER_INPUT_TYPES.get(capability, {}).get(
            parameter_key
        )
        if input_type is None:
            raise GuidanceInputTypeError(
                "guidance is not applicable to Catalog member"
            )
        return ("required configuration", input_type)

    def canonicalize_guidance(
        self,
        *,
        capability: str,
        parameter_key: str,
        provider_reason: str,
        provider_input_guidance: str,
    ) -> tuple[str, str]:
        """Drop provider wording in favour of a deterministic catalog template."""
        reason_ref = self.project_reason(provider_reason)
        input_ref = self.project_input_guidance(provider_input_guidance)
        if not self._is_specific_slack_pair(
            reason_ref,
            input_ref,
            capability,
            parameter_key,
        ):
            reason_ref, input_ref = _GENERIC_GUIDANCE_REFS
        safe_label, input_type = self.guidance_catalog_context(
            capability,
            parameter_key,
        )
        return self.render_guidance(
            reason_ref=reason_ref,
            input_guidance_ref=input_ref,
            capability=capability,
            parameter_key=parameter_key,
            safe_label=safe_label,
            input_type=input_type,
        )

    def project_guidance(
        self,
        *,
        capability: str,
        parameter_key: str,
        reason: str,
        input_guidance: str,
    ) -> tuple[str, str] | None:
        """Accept only a rendered catalog pair for storage in a cached plan."""
        reason_ref = self.project_reason(reason)
        input_ref = self.project_input_guidance(input_guidance)
        if self._is_specific_slack_pair(
            reason_ref,
            input_ref,
            capability,
            parameter_key,
        ):
            return _SPECIFIC_SLACK_GUIDANCE_REFS
        try:
            safe_label, input_type = self.guidance_catalog_context(
                capability,
                parameter_key,
            )
            expected_reason, expected_input = self.render_guidance(
                reason_ref=_GENERIC_GUIDANCE_REASON_REF,
                input_guidance_ref=_GENERIC_INPUT_GUIDANCE_REF,
                capability=capability,
                parameter_key=parameter_key,
                safe_label=safe_label,
                input_type=input_type,
            )
        except (CanonicalReferenceError, GuidanceInputTypeError):
            return None
        if (
            _normalized_text(reason) == _normalized_text(expected_reason)
            and _normalized_text(input_guidance) == _normalized_text(expected_input)
        ):
            return _GENERIC_GUIDANCE_REFS
        return None

    @staticmethod
    def _is_specific_slack_pair(
        reason_ref: str | None,
        input_ref: str | None,
        capability: str,
        parameter_key: str,
    ) -> bool:
        return (
            (reason_ref, input_ref) == _SPECIFIC_SLACK_GUIDANCE_REFS
            and capability == "slack_send"
            and parameter_key == "channel"
        )

    def render_guidance(
        self,
        *,
        reason_ref: str,
        input_guidance_ref: str,
        capability: str,
        parameter_key: str,
        safe_label: str,
        input_type: str,
    ) -> tuple[str, str]:
        try:
            reason = self._reasons[reason_ref]
            input_guidance = self._input_guidance[input_guidance_ref]
        except KeyError as exc:
            raise CanonicalReferenceError("unknown guidance reference") from exc
        expected = CAPABILITY_PARAMETER_INPUT_TYPES.get(capability, {}).get(
            parameter_key
        )
        catalog_context = self.guidance_catalog_context(capability, parameter_key)
        is_specific_slack_pair = self._is_specific_slack_pair(
            reason_ref,
            input_guidance_ref,
            capability,
            parameter_key,
        )
        is_generic_pair = (reason_ref, input_guidance_ref) == _GENERIC_GUIDANCE_REFS
        if (
            expected != input_type
            or catalog_context != (safe_label, input_type)
            or not (is_specific_slack_pair or is_generic_pair)
            or input_type not in reason.allowed_input_types
            or input_type not in input_guidance.allowed_input_types
        ):
            raise GuidanceInputTypeError("guidance input type is incompatible")
        arguments = {
            "parameter_key": parameter_key,
            "safe_label": safe_label,
            "input_type": input_type,
        }
        return (
            reason.canonical_template.format(**arguments),
            input_guidance.canonical_template.format(**arguments),
        )
