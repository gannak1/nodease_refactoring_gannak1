from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

import httpx
from apps.shared.services.egress_guard import EgressGuardError
from apps.shared.services.guarded_http_transport import (
    EgressResponseRejectedError,
    GuardedAsyncHttpTransport,
    GuardedHttpTransport,
)
from apps.shared.services.outbound_operation_policy import (
    require_outbound_operation_profile,
)


class OperationHttpFailurePhase(str, Enum):
    BEFORE_SEND = "before_send"
    OUTCOME_UNKNOWN = "outcome_unknown"


class OperationHttpFailure(RuntimeError):
    def __init__(self, reason_code: str, phase: OperationHttpFailurePhase) -> None:
        self.reason_code = reason_code
        self.phase = phase
        super().__init__(reason_code)


@dataclass(frozen=True)
class OperationHttpTimeouts:
    connect_seconds: float
    write_seconds: float
    read_seconds: float
    pool_seconds: float

    def __post_init__(self) -> None:
        for value in (
            self.connect_seconds,
            self.write_seconds,
            self.read_seconds,
            self.pool_seconds,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or value <= 0
            ):
                raise ValueError("operation HTTP timeout is invalid")


@dataclass(frozen=True)
class OperationHttpResponse:
    status_code: int
    headers: Mapping[str, str]
    content: bytes
    header_items: tuple[tuple[str, str], ...] = ()

    def json(self) -> Any:
        return json.loads(self.content)

    @property
    def text(self) -> str:
        return self.content.decode("utf-8")

    def header_values(self, name: str) -> tuple[str, ...]:
        lower_name = name.lower()
        if self.header_items:
            return tuple(
                value for key, value in self.header_items if key.lower() == lower_name
            )
        value = self.headers.get(lower_name)
        return () if value is None else (value,)


def _response(response: httpx.Response) -> OperationHttpResponse:
    return OperationHttpResponse(
        status_code=response.status_code,
        headers=MappingProxyType(
            {str(key).lower(): str(value) for key, value in response.headers.items()}
        ),
        content=bytes(response.content),
        header_items=tuple(
            (str(key).lower(), str(value))
            for key, value in response.headers.multi_items()
        ),
    )


def _safe_failure(exc: Exception) -> OperationHttpFailure:
    if isinstance(exc, EgressResponseRejectedError):
        return OperationHttpFailure(
            exc.reason_code,
            OperationHttpFailurePhase.OUTCOME_UNKNOWN,
        )
    if isinstance(exc, EgressGuardError):
        return OperationHttpFailure(
            exc.reason_code,
            OperationHttpFailurePhase.BEFORE_SEND,
        )
    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)):
        return OperationHttpFailure(
            "egress.connection_failed",
            OperationHttpFailurePhase.BEFORE_SEND,
        )
    return OperationHttpFailure(
        "egress.request_outcome_unknown",
        OperationHttpFailurePhase.OUTCOME_UNKNOWN,
    )


def _bounded_timeout(
    *,
    operation_limit_seconds: float,
    timeouts: OperationHttpTimeouts | None,
) -> float | httpx.Timeout:
    if timeouts is None:
        return operation_limit_seconds
    if any(
        value > operation_limit_seconds
        for value in (
            timeouts.connect_seconds,
            timeouts.write_seconds,
            timeouts.read_seconds,
            timeouts.pool_seconds,
        )
    ):
        raise OperationHttpFailure(
            "egress.timeout_policy_invalid",
            OperationHttpFailurePhase.BEFORE_SEND,
        )
    return httpx.Timeout(
        connect=timeouts.connect_seconds,
        write=timeouts.write_seconds,
        read=timeouts.read_seconds,
        pool=timeouts.pool_seconds,
    )


class OperationHttpRequester:
    def __init__(
        self,
        *,
        client_factory: Callable[..., httpx.Client] = httpx.Client,
    ) -> None:
        self._client_factory = client_factory

    def request(
        self,
        *,
        operation_id: str,
        approved_endpoint: str,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        form_data: Mapping[str, Any] | None = None,
        query_params: Mapping[str, Any] | None = None,
        timeouts: OperationHttpTimeouts | None = None,
    ) -> OperationHttpResponse:
        try:
            profile = require_outbound_operation_profile(operation_id)
            operation = profile.bind(approved_endpoint)
            operation.validate_url_policy(url)
            transport = GuardedHttpTransport(operation=operation)
            with self._client_factory(
                transport=transport,
                timeout=_bounded_timeout(
                    operation_limit_seconds=profile.policy.timeout_seconds,
                    timeouts=timeouts,
                ),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    data=form_data,
                    params=query_params,
                )
                return _response(response)
        except OperationHttpFailure:
            raise
        except Exception as exc:
            raise _safe_failure(exc) from None


class AsyncOperationHttpRequester:
    def __init__(
        self,
        *,
        client_factory: Callable[..., httpx.AsyncClient] = httpx.AsyncClient,
    ) -> None:
        self._client_factory = client_factory

    async def request(
        self,
        *,
        operation_id: str,
        approved_endpoint: str,
        method: str,
        url: str,
        headers: Mapping[str, str] | None = None,
        json_body: Any | None = None,
        form_data: Mapping[str, Any] | None = None,
        query_params: Mapping[str, Any] | None = None,
        timeouts: OperationHttpTimeouts | None = None,
    ) -> OperationHttpResponse:
        try:
            profile = require_outbound_operation_profile(operation_id)
            operation = profile.bind(approved_endpoint)
            operation.validate_url_policy(url)
            transport = GuardedAsyncHttpTransport(operation=operation)
            async with self._client_factory(
                transport=transport,
                timeout=_bounded_timeout(
                    operation_limit_seconds=profile.policy.timeout_seconds,
                    timeouts=timeouts,
                ),
                follow_redirects=False,
                trust_env=False,
            ) as client:
                response = await client.request(
                    method,
                    url,
                    headers=headers,
                    json=json_body,
                    data=form_data,
                    params=query_params,
                )
                return _response(response)
        except OperationHttpFailure:
            raise
        except Exception as exc:
            raise _safe_failure(exc) from None


__all__ = [
    "AsyncOperationHttpRequester",
    "OperationHttpFailure",
    "OperationHttpFailurePhase",
    "OperationHttpRequester",
    "OperationHttpResponse",
    "OperationHttpTimeouts",
]
