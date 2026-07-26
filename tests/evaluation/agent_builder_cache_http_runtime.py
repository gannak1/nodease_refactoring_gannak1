"""Loopback-only HTTP runtime for the MBA-350 live cache benchmark.

Raw scenario messages, authorization, protected identifiers, server responses,
and session identifiers stay inside this module.  Only allowlisted diagnostic
fields and HMAC fingerprints reach the collector.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Callable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from tests.evaluation.agent_builder_cache_live_collector import (
    LiveAttemptObservation,
    LiveAttemptRequest,
)
from tests.evaluation.run_agent_builder_cache_latency_benchmark import (
    LiveBenchmarkRuntime,
    RuntimeAdmission,
)


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})
_OUTCOMES = frozenset({"disabled", "hit", "miss", "bypass", "error"})
_TERMINAL_STATUSES = frozenset(
    {"success", "provider_error", "validation_error", "timeout", "canceled"}
)
_PARITY_RESPONSE_FIELDS = (
    "status",
    "structured_plan",
    "knowledge_resolution",
    "graph_mutation",
    "parameter_group",
    "clarification_questions",
    "clarification_options",
    "validation_result",
    "warnings",
)
_PARITY_IDENTITY_FIELDS = frozenset(
    {
        "candidate_id",
        "collection_handle",
        "draft_id",
        "edge_id",
        "id",
        "kb_handle",
        "node_id",
        "operation_id",
        "request_id",
        "requirement_id",
        "resolution_id",
        "session_id",
        "source",
        "source_node_id",
        "target",
        "target_node_id",
        "affected_node_ids",
        "group_id",
        "knowledge_resolution_id",
        "parameter_task_id",
        "selected_collection_handles",
        "selected_kb_handles",
        "suggestion_id",
        "task_id",
    }
)


def _canonical_identity(value: object, identities: dict[str, str]) -> object:
    if isinstance(value, str):
        return identities.setdefault(value, f"identity-{len(identities) + 1}")
    if isinstance(value, list):
        return [_canonical_identity(item, identities) for item in value]
    return value


def _parity_projection(
    value: object,
    *,
    identities: dict[str, str],
    field_name: str | None = None,
) -> object:
    if field_name in _PARITY_IDENTITY_FIELDS:
        return _canonical_identity(value, identities)
    if isinstance(value, Mapping):
        return {
            str(key): _parity_projection(
                item,
                identities=identities,
                field_name=str(key),
            )
            for key, item in sorted(value.items(), key=lambda item: str(item[0]))
        }
    if isinstance(value, list):
        return [
            _parity_projection(item, identities=identities)
            for item in value
        ]
    return value


_RequestJson = Callable[..., Any]


def _loopback_url(value: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError("Benchmark server URL is required")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in _LOOPBACK_HOSTS
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Benchmark server URL must be loopback-only")
    return value.rstrip("/")


@dataclass(frozen=True)
class HttpBenchmarkConfiguration:
    """Private connection inputs supplied through ignored local configuration."""

    cache_off_base_url: str
    cache_on_base_url: str
    authorization: str
    organization_id: str
    workflow_id: str
    credential_id: str
    model_id: str
    fingerprint_key: bytes
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        object.__setattr__(self, "cache_off_base_url", _loopback_url(self.cache_off_base_url))
        object.__setattr__(self, "cache_on_base_url", _loopback_url(self.cache_on_base_url))
        if self.cache_off_base_url == self.cache_on_base_url:
            raise ValueError("Cache-off and cache-on endpoints must differ")
        for value in (
            self.authorization,
            self.organization_id,
            self.workflow_id,
            self.credential_id,
            self.model_id,
        ):
            if not isinstance(value, str) or not value:
                raise ValueError("Benchmark private configuration is incomplete")
        if not isinstance(self.fingerprint_key, bytes) or len(self.fingerprint_key) < 16:
            raise ValueError("Benchmark fingerprint key is invalid")
        if not isinstance(self.timeout_seconds, (int, float)) or not 1 <= self.timeout_seconds <= 300:
            raise ValueError("Benchmark timeout is invalid")
        if not self.auth_token or any(
            character in self.auth_token for character in (";", "\r", "\n")
        ):
            raise ValueError("Benchmark auth token is invalid")

    @property
    def auth_token(self) -> str:
        value = self.authorization.strip()
        if value.casefold().startswith("bearer "):
            value = value[7:].strip()
        return value


def _default_request_json(
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    payload: Mapping[str, object] | None,
    timeout_seconds: float,
) -> Any:
    data = None
    request_headers = dict(headers)
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310 - loopback is validated
            body = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise RuntimeError("Benchmark HTTP request failed") from exc
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("Benchmark HTTP response is invalid") from exc


class HttpLiveBenchmarkRuntime(LiveBenchmarkRuntime):
    """Runs only the normal Agent Builder API and its loopback diagnostic."""

    def __init__(
        self,
        configuration: HttpBenchmarkConfiguration,
        scenarios: Mapping[str, object],
        *,
        request_json: _RequestJson = _default_request_json,
    ) -> None:
        self._configuration = configuration
        self._scenarios = self._validate_scenarios(scenarios)
        self._request_json = request_json
        self._sessions: dict[tuple[bool, str], str] = {}
        self._prime_fingerprints: dict[str, str] = {}
        self._admitted_workflow_context: Mapping[str, str] | None = None
        self._pair_workflow_contexts: dict[str, Mapping[str, str]] = {}

    @staticmethod
    def _validate_scenarios(scenarios: Mapping[str, object]) -> Mapping[str, object]:
        if not isinstance(scenarios, Mapping) or scenarios.get("schema_version") != "mba-350-live-scenarios-v1":
            raise ValueError("Live benchmark scenarios are invalid")
        for phase in ("development", "final"):
            if not isinstance(scenarios.get(phase), Mapping):
                raise ValueError("Live benchmark scenarios are incomplete")
        return scenarios

    def _base_url(self, cache_enabled: bool) -> str:
        return self._configuration.cache_on_base_url if cache_enabled else self._configuration.cache_off_base_url

    def _headers(self, *, fresh_session: bool = False) -> Mapping[str, str]:
        headers = {
            "Cookie": f"auth_token={self._configuration.auth_token}",
            "X-Organization-Id": self._configuration.organization_id,
            "Accept": "application/json",
        }
        if fresh_session:
            headers["X-Agent-Builder-Benchmark-Fresh-Session"] = "true"
        return headers

    def _call(
        self,
        cache_enabled: bool,
        method: str,
        path: str,
        payload: Mapping[str, object] | None = None,
        *,
        fresh_session: bool = False,
    ) -> Any:
        return self._request_json(
            method,
            self._base_url(cache_enabled) + path,
            headers=self._headers(fresh_session=fresh_session),
            payload=payload,
            timeout_seconds=float(self._configuration.timeout_seconds),
        )

    def _workflow_context_url(self, cache_enabled: bool) -> str:
        base_url = self._base_url(cache_enabled)
        if base_url.endswith("/agent-builder"):
            base_url = base_url[: -len("/agent-builder")]
        return f"{base_url}/workflows/{self._configuration.workflow_id}"

    def _workflow_context(self, cache_enabled: bool) -> Mapping[str, str]:
        response = self._request_json(
            "GET",
            self._workflow_context_url(cache_enabled),
            headers=self._headers(),
            payload=None,
            timeout_seconds=float(self._configuration.timeout_seconds),
        )
        if not isinstance(response, Mapping):
            raise RuntimeError("Benchmark workflow context is unavailable")
        workflow_id = response.get("id")
        app_id = response.get("app_id")
        updated_at = response.get("updated_at")
        if (
            str(workflow_id) != self._configuration.workflow_id
            or not isinstance(app_id, str)
            or not app_id
            or not isinstance(updated_at, str)
            or not updated_at
        ):
            raise RuntimeError("Benchmark workflow context is unavailable")
        return {
            "workflow_id": self._configuration.workflow_id,
            "app_id": app_id,
            "updated_at": updated_at,
        }

    def _matching_workflow_context(self) -> Mapping[str, str]:
        cache_off_context = self._workflow_context(False)
        cache_on_context = self._workflow_context(True)
        if cache_off_context != cache_on_context:
            raise RuntimeError("Benchmark workflow contexts do not match")
        return cache_off_context

    def _verify_pair_workflow_context(self, pair_id: str) -> None:
        if self._admitted_workflow_context is None:
            return
        current_context = self._matching_workflow_context()
        if current_context != self._admitted_workflow_context:
            raise RuntimeError("Benchmark workflow context changed")
        prior_context = self._pair_workflow_contexts.setdefault(
            pair_id,
            current_context,
        )
        if prior_context != current_context:
            raise RuntimeError("Benchmark workflow context changed")

    def _has_selected_gpt55_relation(self, model_options: object) -> bool:
        if not isinstance(model_options, list):
            return False
        for provider in model_options:
            if not isinstance(provider, Mapping):
                continue
            for option in provider.get("options", []):
                if not isinstance(option, Mapping):
                    continue
                model = option.get("model")
                credential = option.get("credential")
                if not isinstance(model, Mapping) or not isinstance(credential, Mapping):
                    continue
                if (
                    str(model.get("id", "")) == self._configuration.model_id
                    and str(credential.get("id", "")) == self._configuration.credential_id
                    and model.get("model_id_for_api_call") == "gpt-5.5"
                ):
                    return True
        return False

    def _create_session(self, cache_enabled: bool, scope: str) -> str:
        response = self._call(
            cache_enabled,
            "POST",
            "/sessions",
            {"workflow_id": self._configuration.workflow_id},
            fresh_session=True,
        )
        if not isinstance(response, Mapping):
            raise RuntimeError("Benchmark session response is invalid")
        session_id = response.get("session_id")
        if (
            not isinstance(session_id, str)
            or str(response.get("workflow_id", "")) != self._configuration.workflow_id
        ):
            raise RuntimeError("Benchmark session context is unavailable")
        self._sessions[(cache_enabled, scope)] = session_id
        return session_id

    def _session_id(self, cache_enabled: bool, scope: str) -> str:
        key = (cache_enabled, scope)
        return self._sessions.get(key) or self._create_session(cache_enabled, scope)

    def _fingerprint_material(self) -> bytes:
        material = json.dumps(
            {
                "cache_off": self._configuration.cache_off_base_url,
                "cache_on": self._configuration.cache_on_base_url,
                "authorization": self._configuration.authorization,
                "organization_id": self._configuration.organization_id,
                "workflow_id": self._configuration.workflow_id,
                "credential_id": self._configuration.credential_id,
                "model_id": self._configuration.model_id,
                "off_session": self._sessions.get((False, "preflight"), ""),
                "on_session": self._sessions.get((True, "preflight"), ""),
                "workflow_context": self._admitted_workflow_context or {},
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hmac.new(
            self._configuration.fingerprint_key,
            b"mba-350-runtime-preflight-v1\x00" + material,
            hashlib.sha256,
        ).digest()

    def admission(self) -> RuntimeAdmission:
        """Check scope, exact model relation, and server-loaded workflow on both arms."""

        try:
            cache_off_options = self._call(False, "GET", "/model-options")
            cache_on_options = self._call(True, "GET", "/model-options")
            relation_ready = (
                self._has_selected_gpt55_relation(cache_off_options)
                and self._has_selected_gpt55_relation(cache_on_options)
            )
            if not relation_ready:
                raise RuntimeError("Benchmark model relation is unavailable")
            self._admitted_workflow_context = self._matching_workflow_context()
            self._create_session(False, "preflight")
            self._create_session(True, "preflight")
        except Exception:
            self._admitted_workflow_context = None
            return RuntimeAdmission(
                permission_checked=False,
                gpt55_available=False,
                graph_context_ready=False,
                cache_contract_ready=False,
                fingerprint_material=hmac.new(
                    self._configuration.fingerprint_key,
                    b"mba-350-runtime-preflight-failed-v1",
                    hashlib.sha256,
                ).digest(),
            )
        return RuntimeAdmission(
            permission_checked=True,
            gpt55_available=True,
            graph_context_ready=True,
            cache_contract_ready=True,
            fingerprint_material=self._fingerprint_material(),
        )

    @staticmethod
    def _phase_and_index(run_id: str) -> tuple[str, int, bool]:
        if not isinstance(run_id, str):
            raise RuntimeError("Benchmark run identity is invalid")
        if run_id.startswith(("dev-", "development-")):
            phase = "development"
        elif run_id.startswith(("fin-", "final-")):
            phase = "final"
        else:
            raise RuntimeError("Benchmark run identity is invalid")
        is_warmup = "-warmup-" in run_id
        try:
            attempt = int(run_id.rsplit("-", 1)[1])
        except (IndexError, ValueError) as exc:
            raise RuntimeError("Benchmark run identity is invalid") from exc
        if attempt < 1:
            raise RuntimeError("Benchmark run identity is invalid")
        index = attempt - 1
        if is_warmup:
            index += 10 if phase == "development" else 30
        return phase, index, is_warmup

    def _scenario(self, request: LiveAttemptRequest) -> tuple[str, object]:
        group = request.paired_comparison_group or request.comparison_group
        if group not in {"cold_miss", "exact_warm_hit", "normalization_warm_hit", "semantic_bypass", "negative_control"}:
            raise RuntimeError("Benchmark comparison group is invalid")
        phase, index, _ = self._phase_and_index(request.run_id)
        phase_scenarios = self._scenarios[phase]
        assert isinstance(phase_scenarios, Mapping)
        entries = phase_scenarios.get(group)
        if not isinstance(entries, list) or index >= len(entries):
            raise RuntimeError("Benchmark private scenario is unavailable")
        return group, entries[index]

    @staticmethod
    def _scenario_message(entry: object) -> str:
        if not isinstance(entry, str) or not entry:
            raise RuntimeError("Benchmark private scenario is invalid")
        return entry

    def _submit(
        self,
        cache_enabled: bool,
        message: str,
        generation_mode: str,
        session_scope: str,
    ) -> tuple[Mapping[str, object], Mapping[str, object], float]:
        session_id = self._session_id(cache_enabled, session_scope)
        started = time.monotonic()
        response = self._call(
            cache_enabled,
            "POST",
            f"/sessions/{session_id}/messages",
            {
                "message": message,
                "generation_mode": generation_mode,
                "workflow_id": self._configuration.workflow_id,
                "intent_model_selection": {
                    "credential_id": self._configuration.credential_id,
                    "model_id": self._configuration.model_id,
                },
            },
        )
        elapsed_ms = (time.monotonic() - started) * 1000.0
        if not isinstance(response, Mapping) or not isinstance(response.get("request_id"), str):
            raise RuntimeError("Benchmark message response is invalid")
        diagnostic = self._call(
            cache_enabled,
            "GET",
            f"/benchmark/diagnostics/{response['request_id']}",
        )
        if not isinstance(diagnostic, Mapping):
            raise RuntimeError("Benchmark diagnostic response is invalid")
        return response, diagnostic, elapsed_ms

    @staticmethod
    def _validated_diagnostic(diagnostic: Mapping[str, object]) -> tuple[str, float, int, int, str, bool]:
        outcome = diagnostic.get("cache_outcome")
        planning_latency = diagnostic.get("planning_latency_ms")
        provider_calls = diagnostic.get("provider_call_count")
        repair_calls = diagnostic.get("repair_call_count")
        terminal_status = diagnostic.get("terminal_status")
        validation_passed = diagnostic.get("validation_passed")
        if (
            outcome not in _OUTCOMES
            or not isinstance(planning_latency, (int, float))
            or isinstance(planning_latency, bool)
            or float(planning_latency) < 0
            or not isinstance(provider_calls, int)
            or isinstance(provider_calls, bool)
            or not 0 <= provider_calls <= 2
            or not isinstance(repair_calls, int)
            or isinstance(repair_calls, bool)
            or repair_calls not in {0, 1}
            or terminal_status not in _TERMINAL_STATUSES
            or not isinstance(validation_passed, bool)
        ):
            raise RuntimeError("Benchmark diagnostic response is invalid")
        if outcome == "hit" and (provider_calls, repair_calls) != (0, 0):
            raise RuntimeError("Benchmark diagnostic response is invalid")
        if provider_calls == 0 and repair_calls != 0:
            raise RuntimeError("Benchmark diagnostic response is invalid")
        if provider_calls > 0 and provider_calls != 1 + repair_calls:
            raise RuntimeError("Benchmark diagnostic response is invalid")
        return outcome, float(planning_latency), provider_calls, repair_calls, terminal_status, validation_passed

    def _result_fingerprint(
        self,
        response: Mapping[str, object],
        _diagnostic: Mapping[str, object],
    ) -> str:
        identities: dict[str, str] = {}
        private_projection = json.dumps(
            {
                "response": {
                    field: _parity_projection(
                        response[field],
                        identities=identities,
                        field_name=field,
                    )
                    for field in _PARITY_RESPONSE_FIELDS
                    if field in response
                }
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
        return hmac.new(
            self._configuration.fingerprint_key,
            b"mba-350-result-v2\x00" + private_projection,
            hashlib.sha256,
        ).hexdigest()

    @staticmethod
    def _failure(request: LiveAttemptRequest) -> LiveAttemptObservation:
        outcome = {
            "cache_disabled_baseline": "disabled",
            "cold_miss": "miss",
            "exact_warm_hit": "miss",
            "normalization_warm_hit": "miss",
            "semantic_bypass": "bypass",
            "negative_control": "error",
        }.get(request.comparison_group, "error")
        return LiveAttemptObservation(
            cache_outcome=outcome,
            planning_latency_ms=None,
            end_to_end_latency_ms=None,
            provider_call_count=0,
            repair_call_count=0,
            terminal_status="provider_error",
            validation_passed=False,
            result_fingerprint="",
        )

    def execute(self, request: LiveAttemptRequest) -> LiveAttemptObservation:
        """Prepare each candidate privately, then surface one safe observed row."""

        try:
            group, entry = self._scenario(request)
            self._verify_pair_workflow_context(request.pair_id)
            measured_scope = (
                f"candidate:{request.pair_id}"
                if request.cache_enabled
                else f"baseline:{request.pair_id}"
            )
            if request.comparison_group == "normalization_warm_hit" and request.cache_enabled:
                if not isinstance(entry, Mapping):
                    raise RuntimeError("Benchmark private scenario is invalid")
                prime_response, prime_diagnostic, _ = self._submit(True, self._scenario_message(entry.get("prime")), request.generation_mode, f"prime:{request.pair_id}")
                self._prime_fingerprints[request.pair_id] = self._result_fingerprint(prime_response, prime_diagnostic)
                message = self._scenario_message(entry.get("measure"))
            else:
                message = self._scenario_message(entry)
                if request.cache_enabled and request.comparison_group == "exact_warm_hit":
                    prime_response, prime_diagnostic, _ = self._submit(True, message, request.generation_mode, f"prime:{request.pair_id}")
                    self._prime_fingerprints[request.pair_id] = self._result_fingerprint(prime_response, prime_diagnostic)
            response, diagnostic, end_to_end_latency_ms = self._submit(
                request.cache_enabled,
                message,
                request.generation_mode,
                measured_scope,
            )
            (
                outcome,
                planning_latency_ms,
                provider_call_count,
                repair_call_count,
                terminal_status,
                validation_passed,
            ) = self._validated_diagnostic(diagnostic)
            result_fingerprint = self._result_fingerprint(response, diagnostic)
            if request.cache_enabled and request.comparison_group in {"exact_warm_hit", "normalization_warm_hit"} and outcome == "hit" and self._prime_fingerprints.get(request.pair_id) != result_fingerprint:
                raise RuntimeError("Benchmark cached materialization parity failed")
            return LiveAttemptObservation(
                cache_outcome=outcome,
                planning_latency_ms=planning_latency_ms,
                end_to_end_latency_ms=end_to_end_latency_ms,
                provider_call_count=provider_call_count,
                repair_call_count=repair_call_count,
                terminal_status=terminal_status,
                validation_passed=validation_passed,
                result_fingerprint=result_fingerprint,
            )
        except Exception:
            return self._failure(request)
