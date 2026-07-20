from __future__ import annotations

import json
import re
from typing import final

from pydantic import ValidationError

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
)


_ERROR_PATHS = {
    "payload_too_large": frozenset({"payload_size"}),
    "invalid_utf8": frozenset({"root"}),
    "invalid_json": frozenset({"root"}),
    "unsupported_schema_version": frozenset({"contract_version"}),
    "forbidden_cache_content": frozenset({"cache_content"}),
    "invalid_plan_schema": frozenset({"reference", "payload_shape"}),
    "non_canonical_payload": frozenset({"root"}),
}

_FORBIDDEN_FIELDS = frozenset(
    {
        "graph",
        "nodes",
        "edges",
        "position",
        "viewport",
        "workflow_id",
        "node_id",
        "edge_id",
        "request_id",
        "session_id",
        "operation_id",
        "credential",
        "credential_id",
        "credential_config",
        "secret",
        "token",
        "api_key",
        "password",
        "redis_url",
        "parameter_value",
        "actual_parameter_value",
        "explicit_parameter_value",
        "knowledge_base_id",
        "kb_id",
        "collection_id",
        "knowledge_base_name",
        "candidate_handle",
        "opaque_handle",
        "raw_provider_response",
        "raw_payload",
        "audit_payload",
        "intent_summary",
        "purpose",
        "reason",
        "input_guidance",
    }
)
_REFERENCE_FIELDS = frozenset(
    {
        "capability",
        "ordered_capabilities",
        "logical_steps",
        "edit_placement",
        "step_refs",
        "integration_actions",
        "parameter_key",
        "reason_template_ref",
        "input_guidance_template_ref",
        "requirement_ref",
        "target_step_ref",
        "topic_refs",
        "contract_versions",
        "normalizer_version",
        "planner_contract_version",
        "canonical_text_registry_version",
        "materializer_version",
    }
)
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-"
    r"[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$"
)
_SECRET_VALUE_RE = re.compile(
    r"(?i)(?:api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]"
)
_URL_RE = re.compile(r"(?i)^(?:redis|rediss|https?|postgres(?:ql)?):/{1,2}")


@final
class IntentPlanCodecError(ValueError):
    __slots__ = ("_code", "_path_category")

    def __init_subclass__(cls, **_kwargs):
        raise TypeError("IntentPlanCodecError is final")

    def __init__(self, code: str, path_category: str) -> None:
        if code not in _ERROR_PATHS or path_category not in _ERROR_PATHS[code]:
            raise ValueError("invalid codec error contract")
        self._code = code
        self._path_category = path_category
        super().__init__(f"{code}:{path_category}")

    @property
    def code(self) -> str:
        return self._code

    @property
    def path_category(self) -> str:
        return self._path_category

    def __str__(self) -> str:
        return f"{self.code}:{self.path_category}"

    def __repr__(self) -> str:
        return str(self)


class _DuplicateKeyError(ValueError):
    pass


class _NonFiniteNumberError(ValueError):
    pass


def _object_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError()
        result[key] = value
    return result


def _reject_nonfinite(_value):
    raise _NonFiniteNumberError()


def _is_forbidden_string(value: str, *, field_name: str | None) -> bool:
    if field_name == "parameter_key":
        return False
    return bool(
        value == "[redacted]"
        or _UUID_RE.fullmatch(value)
        or _SECRET_VALUE_RE.search(value)
        or _URL_RE.match(value)
    )


def _has_forbidden_content(value, *, field_name: str | None = None) -> bool:
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str) or key.casefold() in _FORBIDDEN_FIELDS:
                return True
            if _has_forbidden_content(child, field_name=key.casefold()):
                return True
        return False
    if isinstance(value, (list, tuple)):
        return any(
            _has_forbidden_content(child, field_name=field_name) for child in value
        )
    return isinstance(value, str) and _is_forbidden_string(
        value,
        field_name=field_name,
    )


def _validation_path_category(error: ValidationError) -> str:
    for item in error.errors(
        include_url=False,
        include_context=False,
        include_input=False,
    ):
        if any(str(part) in _REFERENCE_FIELDS for part in item.get("loc", ())):
            return "reference"
    return "payload_shape"


class CanonicalIntentPlanCodec:
    def encode(
        self,
        plan: CachedIntentPlanV1,
        max_payload_bytes: int,
    ) -> bytes:
        if not isinstance(plan, CachedIntentPlanV1):
            raise IntentPlanCodecError("invalid_plan_schema", "payload_shape")
        raw = plan.model_dump(mode="json", exclude_none=False)
        if _has_forbidden_content(raw):
            raise IntentPlanCodecError(
                "forbidden_cache_content",
                "cache_content",
            )

        encoding_failed = False
        try:
            payload = json.dumps(
                raw,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        except (TypeError, ValueError):
            encoding_failed = True
            payload = b""
        if encoding_failed:
            raise IntentPlanCodecError("invalid_plan_schema", "payload_shape")
        if len(payload) > max_payload_bytes:
            raise IntentPlanCodecError("payload_too_large", "payload_size")
        return payload

    def decode(
        self,
        payload: bytes,
        max_payload_bytes: int,
    ) -> CachedIntentPlanV1:
        if not isinstance(payload, bytes):
            raise IntentPlanCodecError("invalid_utf8", "root")
        if len(payload) > max_payload_bytes:
            raise IntentPlanCodecError("payload_too_large", "payload_size")

        text = None
        try:
            text = payload.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            pass
        if text is None:
            raise IntentPlanCodecError("invalid_utf8", "root")

        raw = None
        raw_json_failed = False
        try:
            raw = json.loads(
                text,
                object_pairs_hook=_object_without_duplicates,
                parse_constant=_reject_nonfinite,
            )
        except (
            json.JSONDecodeError,
            _DuplicateKeyError,
            _NonFiniteNumberError,
            TypeError,
            ValueError,
        ):
            raw_json_failed = True
        if raw_json_failed or not isinstance(raw, dict):
            raise IntentPlanCodecError("invalid_json", "root")
        if _has_forbidden_content(raw):
            raise IntentPlanCodecError(
                "forbidden_cache_content",
                "cache_content",
            )
        if raw.get("schema_version") != 1:
            raise IntentPlanCodecError(
                "unsupported_schema_version",
                "contract_version",
            )

        plan = None
        validation_category = None
        try:
            plan = CachedIntentPlanV1.model_validate_json(payload, strict=True)
        except ValidationError as error:
            validation_category = _validation_path_category(error)
        if validation_category is not None or plan is None:
            raise IntentPlanCodecError(
                "invalid_plan_schema",
                validation_category or "payload_shape",
            )

        canonical = self.encode(plan, max_payload_bytes)
        if canonical != payload:
            raise IntentPlanCodecError("non_canonical_payload", "root")
        return plan
