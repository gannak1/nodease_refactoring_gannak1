from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import requests

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


class GithubSecretMaterial:
    """Opaque adapter-only GitHub credential material."""

    __slots__ = ("__value",)

    def __init__(self, value: str) -> None:
        self.__value = value

    def reveal_for_adapter(self) -> str:
        return self.__value

    def __repr__(self) -> str:
        return "GithubSecretMaterial(<redacted>)"

    __str__ = __repr__

    def __reduce__(self):  # pragma: no cover - defensive protocol guard
        raise TypeError("GitHub secret material is not serializable")

    def __copy__(self):  # pragma: no cover - defensive protocol guard
        raise TypeError("GitHub secret material is not copyable")

    def __deepcopy__(self, memo):  # pragma: no cover - defensive protocol guard
        raise TypeError("GitHub secret material is not copyable")


@dataclass(frozen=True)
class GithubCommentRequest:
    secret: GithubSecretMaterial
    repo_owner: str
    repo_name: str
    pr_number: int
    comment_body: str
    authorization_guard: Callable[[], None] | None = None

    def __repr__(self) -> str:
        return "GithubCommentRequest(secret=<redacted>, comment_body=<redacted>)"


class GithubCommentEffectAdapter:
    _REQUEST_SEMANTICS = frozenset({"github.issue_comment.request.v1"})
    _RESPONSE_SEMANTICS = frozenset({"github.issue_comment.response.v1"})

    def __init__(
        self,
        *,
        contracts: ProviderContractRegistry | None = None,
        active_profile: ProviderContractProfile | None = None,
        historical_profiles: Iterable[ProviderContractProfile] = (),
    ) -> None:
        provider = "github"
        operation = "github.issue_comment.create"
        historical_profiles = tuple(historical_profiles)
        if contracts is not None and (
            active_profile is not None or historical_profiles
        ):
            raise ValueError("GitHub adapter contract sources cannot be mixed")
        if contracts is None and (active_profile is not None or historical_profiles):
            active_profile = active_profile or provider_contract_registry().active(
                provider,
                operation,
            )
            contracts = ProviderContractRegistry(
                (active_profile, *historical_profiles),
                active_versions={
                    (provider, operation): active_profile.contract_version
                },
            )
        contracts = contracts or provider_contract_registry()
        self._profile = contracts.active(provider, operation)
        profiles = contracts.profiles_for(provider, operation)
        if any(
            profile.provider != provider or profile.operation != operation
            for profile in profiles
        ):
            raise ValueError("GitHub adapter profile does not match its operation")
        self._profiles_by_version: dict[str, ProviderContractProfile] = {}
        for profile in profiles:
            if profile.request_semantics not in self._REQUEST_SEMANTICS:
                raise ValueError("unsupported GitHub request semantics")
            if profile.response_semantics not in self._RESPONSE_SEMANTICS:
                raise ValueError("unsupported GitHub response semantics")
            if profile.replay_projection_semantics is not None:
                raise ValueError("unsupported GitHub replay projection semantics")
            existing = self._profiles_by_version.get(profile.contract_version)
            if existing is not None and existing != profile:
                raise ValueError("GitHub contract version has conflicting definitions")
            self._profiles_by_version[profile.contract_version] = profile
        self.trace_metadata: dict[str, Any] = {}

    @property
    def profile(self) -> ProviderContractProfile:
        return self._profile

    def _require_known_profile(
        self,
        profile: ProviderContractProfile,
    ) -> ProviderContractProfile:
        known = self._profiles_by_version.get(profile.contract_version)
        if known != profile:
            raise ValueError("unsupported GitHub provider profile")
        return known

    def prepare_effect(
        self,
        payload: Any,
        *,
        profile: ProviderContractProfile | None = None,
    ) -> PreparedEffectRequest:
        profile = profile or self.profile
        profile = self._require_known_profile(profile)
        if profile.request_semantics != "github.issue_comment.request.v1":
            raise ValueError("unsupported GitHub request semantics")
        if not isinstance(payload, GithubCommentRequest) or not payload.comment_body:
            raise ValueError("invalid GitHub comment request")
        if not isinstance(payload.secret, GithubSecretMaterial):
            raise ValueError("invalid GitHub secret material")
        if payload.authorization_guard is not None and not callable(
            payload.authorization_guard
        ):
            raise ValueError("invalid GitHub authorization guard")
        secret = payload.secret.reveal_for_adapter()
        canonical = json.dumps(
            {
                "secret": secret,
                "repo_owner": payload.repo_owner,
                "repo_name": payload.repo_name,
                "pr_number": payload.pr_number,
                "comment_body": payload.comment_body,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        return PreparedEffectRequest(
            request=payload,
            effect_input_digest=hashlib.sha256(canonical).hexdigest(),
            profile=profile,
        )

    def finalize_provider_call(
        self,
        prepared: PreparedEffectRequest,
        idempotency_key: str | None,
    ) -> PreparedProviderCall:
        profile = prepared.profile or self.profile
        profile = self._require_known_profile(profile)
        if (
            profile.provider_replay is ProviderReplayCapability.SUPPORTED
            or idempotency_key is not None
        ):
            raise ValueError("GitHub comment contract does not support a system key")
        return PreparedProviderCall(
            request=prepared.request,
            idempotency_key=None,
            profile=profile,
        )

    def invoke_effect(self, call: PreparedProviderCall) -> ProviderInvocationResult:
        profile = self._require_known_profile(call.profile)
        if profile.response_semantics != "github.issue_comment.response.v1":
            raise ValueError("unsupported GitHub response semantics")
        request = call.request
        if not isinstance(request, GithubCommentRequest):
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="invalid_prepared_request",
                retry_before_effect=False,
            )
        url = (
            "https://api.github.com/repos/"
            f"{request.repo_owner}/{request.repo_name}/issues/{request.pr_number}/comments"
        )
        headers = {
            "Authorization": f"token {request.secret.reveal_for_adapter()}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "moduly",
        }
        started = time.perf_counter()
        if request.authorization_guard is not None:
            try:
                request.authorization_guard()
            except Exception:
                self._set_trace(request, None, started)
                raise EffectInvocationFailure(
                    outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                    error_code="credential_unavailable",
                    retry_before_effect=False,
                ) from None
        try:
            response = requests.post(
                url,
                headers=headers,
                json={"body": request.comment_body},
                timeout=30,
            )
        except (
            requests.exceptions.MissingSchema,
            requests.exceptions.InvalidSchema,
            requests.exceptions.InvalidURL,
            requests.exceptions.InvalidHeader,
        ):
            self._set_trace(request, None, started)
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="invalid_prepared_request",
                retry_before_effect=False,
            ) from None
        except requests.exceptions.ConnectTimeout:
            self._set_trace(request, None, started)
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="timeout",
                retry_before_effect=True,
            ) from None
        except requests.exceptions.RequestException:
            self._set_trace(request, None, started)
            raise EffectInvocationFailure(
                outcome=EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                error_code="response_lost",
            ) from None

        self._set_trace(request, response, started)
        if response.status_code in {401, 403, 404, 410, 422}:
            raise EffectInvocationFailure(
                outcome=EffectOutcome.FAILED_BEFORE_EFFECT,
                error_code="provider_rejected_request",
                provider_status_code=response.status_code,
                retry_before_effect=False,
            )
        if response.status_code != 201:
            raise EffectInvocationFailure(
                outcome=EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                error_code="unexpected_provider_status",
                provider_status_code=response.status_code,
            )
        try:
            comment = response.json()
            comment_id = comment["id"]
            comment_url = comment["html_url"]
            comment_body = comment["body"]
            if (
                isinstance(comment_id, bool)
                or not isinstance(comment_id, int)
                or not isinstance(comment_url, str)
                or not comment_url
                or not isinstance(comment_body, str)
            ):
                raise TypeError("invalid GitHub comment response")
            output = {
                "comment_id": comment_id,
                "comment_url": comment_url,
                "comment_body": comment_body,
            }
        except (ValueError, KeyError, TypeError):
            raise EffectInvocationFailure(
                outcome=EffectOutcome.EFFECT_OUTCOME_UNKNOWN,
                error_code="response_malformed",
                provider_status_code=response.status_code,
            ) from None
        return ProviderInvocationResult(
            output, provider_status_code=response.status_code
        )

    def _set_trace(
        self,
        request: GithubCommentRequest,
        response: Any,
        started: float,
    ) -> None:
        self.trace_metadata = {
            "http": {
                "method": "POST",
                "status_code": getattr(response, "status_code", None),
                "latency_ms": int((time.perf_counter() - started) * 1000),
                "request_size": len(request.comment_body.encode("utf-8")),
                "response_size": len(getattr(response, "content", b"") or b""),
            }
        }

    def replay_projection(
        self,
        output: Any,
        *,
        profile: ProviderContractProfile,
    ) -> Any:
        self._require_known_profile(profile)
        raise ValueError("GitHub contract does not support replay projection")
