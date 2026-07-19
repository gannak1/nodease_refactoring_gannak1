"""Slack provider adapter for the durable external-effect boundary."""

from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

import httpx

from apps.shared.domain.slack_delivery import is_valid_commercial_slack_webhook_url
from apps.shared.services.egress_guard import EgressGuardError, OutboundEgressGuard
from apps.workflow_engine.domain.external_effect import (
    EffectInvocationFailure,
    EffectOutcome,
    PreparedEffectRequest,
    PreparedProviderCall,
    ProviderContractProfile,
    ProviderContractRegistry,
    ProviderInvocationResult,
    ProviderReplayCapability,
    provider_contract_registry,
)


_API_URL = "https://slack.com/api/chat.postMessage"
_MESSAGE_REF_RE = re.compile(r"^[0-9]{1,20}\.[0-9]{1,20}$")
_API_PERMANENT_ERRORS = frozenset(
    {
        "account_inactive",
        "channel_not_found",
        "ekm_access_denied",
        "invalid_arguments",
        "invalid_arg_name",
        "invalid_array_arg",
        "invalid_attachments",
        "invalid_auth",
        "invalid_blocks",
        "invalid_charset",
        "invalid_form_data",
        "invalid_post_type",
        "is_archived",
        "message_limit_exceeded",
        "method_deprecated",
        "missing_post_type",
        "missing_scope",
        "msg_too_long",
        "no_text",
        "not_authed",
        "not_in_channel",
        "posting_to_general_channel_denied",
        "restricted_action",
        "restricted_action_read_only_channel",
        "team_access_not_granted",
        "token_revoked",
    }
)
_API_AMBIGUOUS_ERRORS = frozenset(
    {"fatal_error", "internal_error", "request_timeout", "service_unavailable"}
)


class SlackDeliveryMode(str, Enum):
    API = "api"
    WEBHOOK = "webhook"


class SlackSecretMaterial:
    """Opaque adapter-only secret holder. This type must never be serialized."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        self.__value = value

    def reveal_for_adapter(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return "SlackSecretMaterial(<redacted>)"

    __str__ = __repr__

    def __reduce__(self):  # pragma: no cover - defensive protocol guard
        raise TypeError("Slack secret material is not serializable")

    def __copy__(self):  # pragma: no cover - defensive protocol guard
        raise TypeError("Slack secret material is not copyable")

    def __deepcopy__(self, memo):  # pragma: no cover - defensive protocol guard
        raise TypeError("Slack secret material is not copyable")


@dataclass(frozen=True)
class SlackDeliveryPolicy:
    connect_timeout_seconds: float = 3.0
    write_timeout_seconds: float = 5.0
    read_timeout_seconds: float = 10.0
    pool_timeout_seconds: float = 2.0
    max_request_bytes: int = 256 * 1024
    max_response_bytes: int = 64 * 1024
    max_retry_after_seconds: int = 60

    def __post_init__(self) -> None:
        for value in (
            self.connect_timeout_seconds,
            self.write_timeout_seconds,
            self.read_timeout_seconds,
            self.pool_timeout_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("invalid Slack delivery policy")
        for value in (
            self.max_request_bytes,
            self.max_response_bytes,
            self.max_retry_after_seconds,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError("invalid Slack delivery policy")


@dataclass(frozen=True)
class SlackEffectRequest:
    mode: SlackDeliveryMode
    payload: Mapping[str, Any]
    secret: SlackSecretMaterial
    authorization_guard: Callable[[], None] | None = None

    def __repr__(self) -> str:
        return f"SlackEffectRequest(mode={self.mode.value!r}, payload=<redacted>)"


@dataclass(frozen=True)
class PreparedSlackRequest:
    mode: SlackDeliveryMode
    payload: dict[str, Any]
    canonical_payload: bytes
    secret: SlackSecretMaterial
    authorization_guard: Callable[[], None] | None = None

    def __repr__(self) -> str:
        return f"PreparedSlackRequest(mode={self.mode.value!r}, payload=<redacted>)"


@dataclass(frozen=True)
class _Classification:
    outcome: EffectOutcome
    provider_reason: str
    error_code: str | None = None
    output: dict[str, Any] | None = None
    provider_retryable: bool = False
    retry_after_seconds: int | None = None


def _framed(name: str, value: str | bytes) -> bytes:
    name_bytes = name.encode("utf-8")
    value_bytes = value if isinstance(value, bytes) else value.encode("utf-8")
    return (
        len(name_bytes).to_bytes(4, "big")
        + name_bytes
        + len(value_bytes).to_bytes(4, "big")
        + value_bytes
    )


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate response key")
        result[key] = value
    return result


def parse_retry_after(values: Iterable[str] | None, *, cap: int) -> int | None:
    values = tuple(values or ())
    if len(values) != 1 or not re.fullmatch(r"[0-9]+", values[0]):
        return None
    seconds = int(values[0])
    return seconds if 0 <= seconds <= cap else None


class SlackEffectAdapter:
    _REQUEST_SEMANTICS = {
        SlackDeliveryMode.API: "slack.chat.post_message.request.v1",
        SlackDeliveryMode.WEBHOOK: "slack.incoming_webhook.post.request.v1",
    }
    _RESPONSE_SEMANTICS = {
        SlackDeliveryMode.API: "slack.chat.post_message.response.v1",
        SlackDeliveryMode.WEBHOOK: "slack.incoming_webhook.post.response.v1",
    }
    _OPERATIONS = {
        SlackDeliveryMode.API: "slack.chat.post_message",
        SlackDeliveryMode.WEBHOOK: "slack.incoming_webhook.post",
    }
    _REPLAY_SEMANTICS = "slack.delivery.replay_projection.v1"

    def __init__(
        self,
        mode: SlackDeliveryMode,
        *,
        egress_guard: OutboundEgressGuard,
        policy: SlackDeliveryPolicy | None = None,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
        contracts: ProviderContractRegistry | None = None,
        active_profile: ProviderContractProfile | None = None,
        historical_profiles: Iterable[ProviderContractProfile] = (),
    ) -> None:
        self.mode = SlackDeliveryMode(mode)
        self.policy = policy or SlackDeliveryPolicy()
        self.egress_guard = egress_guard
        self.client_factory = client_factory
        operation = self._OPERATIONS[self.mode]
        historical_profiles = tuple(historical_profiles)
        if contracts is not None and (
            active_profile is not None or historical_profiles
        ):
            raise ValueError("Slack adapter contract sources cannot be mixed")
        if contracts is None and (active_profile is not None or historical_profiles):
            active_profile = active_profile or provider_contract_registry().active(
                "slack", operation
            )
            contracts = ProviderContractRegistry(
                (active_profile, *historical_profiles),
                active_versions={
                    ("slack", operation): active_profile.contract_version,
                },
            )
        contracts = contracts or provider_contract_registry()
        self._profile = contracts.active("slack", operation)
        self._profiles_by_version: dict[str, ProviderContractProfile] = {}
        for profile in contracts.profiles_for("slack", operation):
            if profile.request_semantics != self._REQUEST_SEMANTICS[self.mode]:
                raise ValueError("unsupported Slack request semantics")
            if profile.response_semantics != self._RESPONSE_SEMANTICS[self.mode]:
                raise ValueError("unsupported Slack response semantics")
            if profile.replay_projection_semantics != self._REPLAY_SEMANTICS:
                raise ValueError("unsupported Slack replay projection semantics")
            self._profiles_by_version[profile.contract_version] = profile
        self.trace_metadata: dict[str, Any] = {}

    @property
    def profile(self) -> ProviderContractProfile:
        return self._profile

    def _require_known_profile(
        self, profile: ProviderContractProfile
    ) -> ProviderContractProfile:
        known = self._profiles_by_version.get(profile.contract_version)
        if known != profile:
            raise ValueError("unsupported Slack provider profile")
        return known

    def prepare_effect(
        self,
        payload: Any,
        *,
        profile: ProviderContractProfile | None = None,
    ) -> PreparedEffectRequest:
        profile = self._require_known_profile(profile or self.profile)
        if not isinstance(payload, SlackEffectRequest) or payload.mode is not self.mode:
            raise ValueError("invalid Slack effect request")
        if not isinstance(payload.secret, SlackSecretMaterial):
            raise ValueError("invalid Slack secret material")
        if payload.authorization_guard is not None and not callable(
            payload.authorization_guard
        ):
            raise ValueError("invalid Slack authorization guard")
        if not isinstance(payload.payload, Mapping):
            raise ValueError("invalid Slack payload")
        canonical_payload = json.dumps(
            dict(payload.payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        if len(canonical_payload) > self.policy.max_request_bytes:
            raise ValueError("Slack payload is too large")
        secret = payload.secret.reveal_for_adapter()
        self._validate_secret(secret)
        digest_input = b"".join(
            (
                _framed("domain", "nodease.slack-effect-request.v1"),
                _framed("mode", self.mode.value),
                _framed("payload", canonical_payload),
                _framed("secret", secret),
            )
        )
        request = PreparedSlackRequest(
            mode=self.mode,
            payload=json.loads(canonical_payload.decode("utf-8")),
            canonical_payload=canonical_payload,
            secret=payload.secret,
            authorization_guard=payload.authorization_guard,
        )
        self._set_trace(
            delivery_status="prepared",
            request_size=len(canonical_payload),
        )
        return PreparedEffectRequest(
            request=request,
            effect_input_digest=hashlib.sha256(digest_input).hexdigest(),
            profile=profile,
        )

    def finalize_provider_call(
        self,
        prepared: PreparedEffectRequest,
        idempotency_key: str | None,
    ) -> PreparedProviderCall:
        profile = self._require_known_profile(prepared.profile or self.profile)
        if profile.provider_replay is ProviderReplayCapability.SUPPORTED:
            raise ValueError("Slack profile cannot accept a system idempotency key")
        if idempotency_key is not None or not isinstance(
            prepared.request, PreparedSlackRequest
        ):
            raise ValueError("invalid Slack provider call")
        return PreparedProviderCall(
            request=prepared.request,
            idempotency_key=None,
            profile=profile,
        )

    def invoke_effect(self, call: PreparedProviderCall) -> ProviderInvocationResult:
        profile = self._require_known_profile(call.profile)
        if profile.response_semantics != self._RESPONSE_SEMANTICS[self.mode]:
            raise ValueError("unsupported Slack response semantics")
        request = call.request
        if (
            not isinstance(request, PreparedSlackRequest)
            or request.mode is not self.mode
        ):
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="invalid_prepared_request",
                retry_before_effect=False,
            )

        started = time.perf_counter()
        response: httpx.Response | None = None
        request_started = False
        if request.authorization_guard is not None:
            try:
                request.authorization_guard()
            except Exception:
                self._set_trace(
                    delivery_status="failed_before_effect",
                    provider_reason="credential_unavailable",
                    latency_ms=self._latency_ms(started),
                    request_size=len(request.canonical_payload),
                )
                raise EffectInvocationFailure(
                    outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                    error_code="credential_unavailable",
                    retry_before_effect=False,
                ) from None

        try:
            url = self._resolve_url_with_timeout(request)
            self.egress_guard.validate_method("POST")
            self.egress_guard.validate_request_body(
                json_body=request.payload,
                data=None,
            )
            headers = self._headers_for(request)
        except (EgressGuardError, TypeError, ValueError):
            self._set_trace(
                delivery_status="failed_before_effect",
                provider_reason="egress_denied",
                latency_ms=self._latency_ms(started),
                request_size=len(request.canonical_payload),
            )
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="invalid_prepared_request",
                retry_before_effect=False,
            ) from None

        try:
            timeout = httpx.Timeout(
                connect=self.policy.connect_timeout_seconds,
                write=self.policy.write_timeout_seconds,
                read=self.policy.read_timeout_seconds,
                pool=self.policy.pool_timeout_seconds,
            )
            with self.client_factory(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                verify=True,
            ) as client:
                request_started = True
                with client.stream(
                    "POST", url, headers=headers, json=request.payload
                ) as response:
                    if 300 <= response.status_code < 400:
                        self._raise_transport_failure(
                            request,
                            response,
                            started,
                            reason="redirect_rejected",
                            error_code="unexpected_provider_status",
                        )
                    self.egress_guard.validate_response_peer_ip(
                        self._response_peer_ip(response)
                    )
                    body = self._read_bounded_body(response)
                    retry_after = parse_retry_after(
                        response.headers.get_list("retry-after"),
                        cap=self.policy.max_retry_after_seconds,
                    )
                    classification = self._classify_response(
                        status_code=response.status_code,
                        content_type=response.headers.get("content-type"),
                        body=body,
                        retry_after_seconds=retry_after,
                    )
        except EffectInvocationFailure:
            raise
        except (httpx.ConnectTimeout, httpx.ConnectError, httpx.PoolTimeout):
            self._set_trace(
                delivery_status="failed_before_effect",
                provider_reason="transport_unavailable",
                latency_ms=self._latency_ms(started),
                request_size=len(request.canonical_payload),
            )
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="connection_failed",
                retry_before_effect=False,
            ) from None
        except (
            httpx.WriteTimeout,
            httpx.ReadTimeout,
            httpx.WriteError,
            httpx.ReadError,
            httpx.RemoteProtocolError,
        ):
            self._raise_transport_failure(
                request,
                response,
                started,
                reason="response_lost",
                error_code="response_lost",
            )
        except EgressGuardError:
            self._raise_transport_failure(
                request,
                response,
                started,
                reason="response_unverified" if request_started else "egress_denied",
                error_code=(
                    "response_lost" if request_started else "invalid_prepared_request"
                ),
                before_effect=not request_started,
            )
        except (httpx.InvalidURL, httpx.UnsupportedProtocol, httpx.LocalProtocolError):
            self._set_trace(
                delivery_status="failed_before_effect",
                provider_reason="egress_denied",
                latency_ms=self._latency_ms(started),
                request_size=len(request.canonical_payload),
            )
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="invalid_prepared_request",
                retry_before_effect=False,
            ) from None
        except Exception:
            self._raise_transport_failure(
                request,
                response,
                started,
                reason="response_lost" if request_started else "transport_unavailable",
                error_code="provider_call_failed",
                before_effect=not request_started,
            )

        response_size = len(body)
        self._set_trace(
            delivery_status=(
                "delivered"
                if classification.outcome is EffectOutcome.SUCCEEDED
                else (
                    "failed_before_effect"
                    if classification.outcome is EffectOutcome.FAILED_BEFORE_EFFECT
                    else "outcome_unknown"
                )
            ),
            provider_reason=classification.provider_reason,
            provider_retryable=classification.provider_retryable,
            retry_after_seconds=classification.retry_after_seconds,
            status_code=response.status_code,
            latency_ms=self._latency_ms(started),
            request_size=len(request.canonical_payload),
            response_size=response_size,
            has_message_ref=bool(
                classification.output and classification.output.get("message_ref")
            ),
        )
        if classification.outcome is not EffectOutcome.SUCCEEDED:
            raise EffectInvocationFailure(
                outcome=classification.outcome,
                error_code=classification.error_code or "provider_call_failed",
                provider_status_code=response.status_code,
                retry_before_effect=False,
            )
        return ProviderInvocationResult(
            classification.output,
            provider_status_code=response.status_code,
        )

    def replay_projection(
        self,
        output: Any,
        *,
        profile: ProviderContractProfile,
    ) -> Any:
        profile = self._require_known_profile(profile)
        if profile.replay_projection_semantics != self._REPLAY_SEMANTICS:
            raise ValueError("unsupported Slack replay projection semantics")
        if not isinstance(output, Mapping):
            raise ValueError("invalid Slack replay result")
        required = {
            "status": 200,
            "delivery_status": "delivered",
            "delivery_mode": self.mode.value,
        }
        if any(output.get(key) != value for key, value in required.items()):
            raise ValueError("invalid Slack replay result")
        allowed = set(required)
        result = dict(required)
        message_ref = output.get("message_ref")
        if self.mode is SlackDeliveryMode.API:
            if not isinstance(message_ref, str) or not _MESSAGE_REF_RE.fullmatch(
                message_ref
            ):
                raise ValueError("invalid Slack replay result")
            allowed.add("message_ref")
            result["message_ref"] = message_ref
        elif message_ref is not None:
            raise ValueError("invalid Slack replay result")
        if set(output) != allowed:
            raise ValueError("invalid Slack replay result")
        return result

    def _validate_secret(self, value: str) -> None:
        limit = 4096 if self.mode is SlackDeliveryMode.API else 2048
        if (
            not isinstance(value, str)
            or not value
            or value != value.strip()
            or len(value.encode("utf-8")) > limit
            or any(char in value for char in "\r\n\x00")
        ):
            raise ValueError("invalid Slack secret")
        if self.mode is SlackDeliveryMode.WEBHOOK and not (
            is_valid_commercial_slack_webhook_url(value)
        ):
            raise ValueError("invalid Slack webhook URL")

    def _resolve_url_with_timeout(self, request: PreparedSlackRequest) -> str:
        try:
            from gevent import Timeout  # noqa: PLC0415
        except ImportError as exc:  # pragma: no cover - Worker readiness dependency
            raise EgressGuardError("egress.dns_timeout") from exc

        timer = Timeout(self.policy.connect_timeout_seconds)
        timer.start()
        try:
            candidate = (
                _API_URL
                if request.mode is SlackDeliveryMode.API
                else request.secret.reveal_for_adapter()
            )
            if request.mode is SlackDeliveryMode.WEBHOOK and not (
                is_valid_commercial_slack_webhook_url(candidate)
            ):
                raise EgressGuardError("egress.invalid_url")
            validated = self.egress_guard.validate_url(candidate)
            if validated != candidate:
                raise EgressGuardError("egress.invalid_url")
            return candidate
        except Timeout:
            raise EgressGuardError("egress.dns_timeout") from None
        finally:
            timer.cancel()

    def _headers_for(self, request: PreparedSlackRequest) -> dict[str, str]:
        headers = {
            "Accept": (
                "application/json"
                if request.mode is SlackDeliveryMode.API
                else "text/plain"
            ),
            "Accept-Encoding": "identity",
            "Content-Type": "application/json; charset=utf-8",
        }
        if request.mode is SlackDeliveryMode.API:
            headers["Authorization"] = f"Bearer {request.secret.reveal_for_adapter()}"
        return headers

    def _read_bounded_body(self, response: httpx.Response) -> bytes:
        encoding = response.headers.get("content-encoding", "").strip().lower()
        if encoding and encoding != "identity":
            raise EgressGuardError("egress.compressed_response_not_allowed")
        content_length = response.headers.get("content-length")
        if content_length is not None:
            try:
                declared_length = int(content_length)
            except ValueError as exc:
                raise EgressGuardError("egress.response_too_large") from exc
            if declared_length < 0 or declared_length > self.policy.max_response_bytes:
                raise EgressGuardError("egress.response_too_large")
        chunks: list[bytes] = []
        size = 0
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > self.policy.max_response_bytes:
                raise EgressGuardError("egress.response_too_large")
            chunks.append(chunk)
        return b"".join(chunks)

    def _classify_response(
        self,
        *,
        status_code: int,
        content_type: str | None,
        body: bytes,
        retry_after_seconds: int | None,
    ) -> _Classification:
        if status_code == 429:
            return _Classification(
                EffectOutcome.FAILED_BEFORE_EFFECT,
                "rate_limited",
                error_code="provider_rejected_request",
                provider_retryable=True,
                retry_after_seconds=retry_after_seconds,
            )
        if self.mode is SlackDeliveryMode.WEBHOOK:
            return self._classify_webhook(status_code=status_code, body=body)
        return self._classify_api(
            status_code=status_code,
            content_type=content_type,
            body=body,
        )

    def _classify_api(
        self,
        *,
        status_code: int,
        content_type: str | None,
        body: bytes,
    ) -> _Classification:
        if status_code != 200:
            if status_code in {400, 401, 403, 404}:
                return _Classification(
                    EffectOutcome.FAILED_BEFORE_EFFECT,
                    "request_rejected",
                    error_code="provider_rejected_request",
                )
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "provider_unavailable",
                error_code="unexpected_provider_status",
            )
        normalized_type = (content_type or "").split(";", 1)[0].strip().lower()
        if normalized_type != "application/json":
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "response_unverified",
                error_code="response_malformed",
            )
        try:
            parsed = json.loads(
                body.decode("utf-8", errors="strict"),
                object_pairs_hook=_reject_duplicate_keys,
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
        except (UnicodeDecodeError, ValueError, json.JSONDecodeError):
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "response_unverified",
                error_code="response_malformed",
            )
        if not isinstance(parsed, dict) or not isinstance(parsed.get("ok"), bool):
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "response_unverified",
                error_code="response_malformed",
            )
        if parsed["ok"] is False:
            provider_error = parsed.get("error")
            if provider_error == "ratelimited":
                return _Classification(
                    EffectOutcome.FAILED_BEFORE_EFFECT,
                    "rate_limited",
                    error_code="provider_rejected_request",
                    provider_retryable=True,
                )
            if provider_error in _API_PERMANENT_ERRORS:
                return _Classification(
                    EffectOutcome.FAILED_BEFORE_EFFECT,
                    "request_rejected",
                    error_code="provider_rejected_request",
                )
            if provider_error in _API_AMBIGUOUS_ERRORS:
                return _Classification(
                    EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                    "provider_unavailable",
                    error_code="provider_call_failed",
                )
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "response_unverified",
                error_code="response_malformed",
            )
        if parsed.get("error") is not None:
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "response_unverified",
                error_code="response_malformed",
            )
        message_ref = parsed.get("ts")
        if not isinstance(message_ref, str) or not _MESSAGE_REF_RE.fullmatch(
            message_ref
        ):
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "response_unverified",
                error_code="response_malformed",
            )
        return _Classification(
            EffectOutcome.SUCCEEDED,
            "accepted",
            output={
                "status": 200,
                "delivery_status": "delivered",
                "delivery_mode": self.mode.value,
                "message_ref": message_ref,
            },
        )

    def _classify_webhook(self, *, status_code: int, body: bytes) -> _Classification:
        if status_code == 200:
            try:
                text = body.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                text = ""
            if text == "ok":
                return _Classification(
                    EffectOutcome.SUCCEEDED,
                    "accepted",
                    output={
                        "status": 200,
                        "delivery_status": "delivered",
                        "delivery_mode": self.mode.value,
                    },
                )
            return _Classification(
                EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                "response_unverified",
                error_code="response_malformed",
            )
        if status_code in {400, 403, 404}:
            return _Classification(
                EffectOutcome.FAILED_BEFORE_EFFECT,
                "request_rejected",
                error_code="provider_rejected_request",
            )
        return _Classification(
            EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
            "provider_unavailable",
            error_code="unexpected_provider_status",
        )

    def _raise_transport_failure(
        self,
        request: PreparedSlackRequest,
        response: httpx.Response | None,
        started: float,
        *,
        reason: str,
        error_code: str,
        before_effect: bool = False,
    ) -> None:
        self._set_trace(
            delivery_status=(
                "failed_before_effect" if before_effect else "outcome_unknown"
            ),
            provider_reason=reason,
            status_code=getattr(response, "status_code", None),
            latency_ms=self._latency_ms(started),
            request_size=len(request.canonical_payload),
            response_size=self._safe_response_size(response),
        )
        raise EffectInvocationFailure(
            outcome=(
                EffectOutcome.FAILED_BEFORE_EFFECT
                if before_effect
                else EffectOutcome.EFFECT_OUTCOME_UNKNOWN
            ),
            error_code=error_code,
            provider_status_code=getattr(response, "status_code", None),
            retry_before_effect=False,
        )

    def _set_trace(self, **values: Any) -> None:
        slack = {"delivery_mode": self.mode.value}
        slack.update({key: value for key, value in values.items() if value is not None})
        self.trace_metadata = {"slack": slack}

    @staticmethod
    def _safe_response_size(response: httpx.Response | None) -> int | None:
        if response is None:
            return None
        try:
            return len(response.content)
        except httpx.ResponseNotRead:
            return None

    @staticmethod
    def _latency_ms(started: float) -> int:
        return max(0, int((time.perf_counter() - started) * 1000))

    @staticmethod
    def _response_peer_ip(response: httpx.Response) -> str | None:
        stream = response.extensions.get("network_stream")
        if stream is None or not hasattr(stream, "get_extra_info"):
            return None
        server_addr = stream.get_extra_info("server_addr")
        if isinstance(server_addr, tuple) and server_addr:
            return str(server_addr[0])
        return None
