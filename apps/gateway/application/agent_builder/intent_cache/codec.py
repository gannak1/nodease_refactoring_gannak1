from __future__ import annotations

import json
import re
from typing import final

from pydantic import ValidationError

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    _SAFE_REFERENCE_LOCATION_PARTS,
)


_ERROR_PATHS = {
    "invalid_payload_limit": frozenset({"payload_size"}),
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
_UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
_SECRET_VALUE_RE = re.compile(
    r"(?:"
    r"sk-[A-Za-z0-9_-]{8,}|"
    r"ghp_[A-Za-z0-9_]{8,}|"
    r"xox[baprs]-[A-Za-z0-9-]{8,}|"
    r"bearer\s+[A-Za-z0-9._-]{8,}|"
    r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+|"
    r"(?:api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]"
    r")",
    re.IGNORECASE,
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


def _validate_payload_limit(max_payload_bytes: int) -> int:
    if type(max_payload_bytes) is not int or max_payload_bytes <= 0:
        raise IntentPlanCodecError(
            "invalid_payload_limit",
            "payload_size",
        )
    return max_payload_bytes


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
        if any(
            str(part) in _SAFE_REFERENCE_LOCATION_PARTS
            for part in item.get("loc", ())
        ):
            return "reference"
    return "payload_shape"


class CanonicalIntentPlanCodec:
    def encode(
        self,
        plan: CachedIntentPlanV1,
        max_payload_bytes: int,
    ) -> bytes:
        max_payload_bytes = _validate_payload_limit(max_payload_bytes)
        if not isinstance(plan, CachedIntentPlanV1):
            raise IntentPlanCodecError("invalid_plan_schema", "payload_shape")
        raw = None
        dump_failed = False
        try:
            raw = plan.model_dump(mode="json", exclude_none=False)
        except (TypeError, ValueError, RecursionError):
            dump_failed = True
        if dump_failed:
            raise IntentPlanCodecError("invalid_plan_schema", "payload_shape")

        forbidden_content = False
        content_scan_failed = False
        try:
            forbidden_content = _has_forbidden_content(raw)
        except RecursionError:
            content_scan_failed = True
        if content_scan_failed:
            raise IntentPlanCodecError("invalid_plan_schema", "payload_shape")
        if forbidden_content:
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
        except (TypeError, ValueError, RecursionError):
            encoding_failed = True
            payload = b""
        if encoding_failed:
            raise IntentPlanCodecError("invalid_plan_schema", "payload_shape")
        if len(payload) > max_payload_bytes:
            raise IntentPlanCodecError("payload_too_large", "payload_size")

        validation_category = None
        try:
            CachedIntentPlanV1.model_validate_json(payload, strict=True)
        except ValidationError as error:
            validation_category = _validation_path_category(error)
        except RecursionError:
            validation_category = "payload_shape"
        if validation_category is not None:
            raise IntentPlanCodecError(
                "invalid_plan_schema",
                validation_category,
            )
        return payload

    def decode(
        self,
        payload: bytes,
        max_payload_bytes: int,
    ) -> CachedIntentPlanV1:
        max_payload_bytes = _validate_payload_limit(max_payload_bytes)
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
            RecursionError,
            TypeError,
            ValueError,
        ):
            raw_json_failed = True
        if raw_json_failed or not isinstance(raw, dict):
            raise IntentPlanCodecError("invalid_json", "root")

        forbidden_content = False
        content_scan_failed = False
        try:
            forbidden_content = _has_forbidden_content(raw)
        except RecursionError:
            content_scan_failed = True
        if content_scan_failed:
            raise IntentPlanCodecError("invalid_json", "root")
        if forbidden_content:
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
        except RecursionError:
            validation_category = "payload_shape"
        if validation_category is not None or plan is None:
            raise IntentPlanCodecError(
                "invalid_plan_schema",
                validation_category or "payload_shape",
            )

        canonical = self.encode(plan, max_payload_bytes)
        if canonical != payload:
            raise IntentPlanCodecError("non_canonical_payload", "root")
        return plan
