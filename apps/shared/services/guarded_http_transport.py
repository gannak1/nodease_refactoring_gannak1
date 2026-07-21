from __future__ import annotations

import ipaddress
from collections.abc import Iterable
from contextlib import suppress

import httpcore
import httpx
from apps.shared.services.egress_guard import (
    EgressGuardError,
    OutboundEgressGuard,
)
from apps.shared.services.outbound_operation_policy import BoundOutboundOperation


def _same_address(left: str, right: str) -> bool:
    return ipaddress.ip_address(str(left)) == ipaddress.ip_address(str(right))


class GuardedNetworkBackend(httpcore.NetworkBackend):
    """Resolve, validate and connect to the same public address."""

    def __init__(
        self,
        guard: OutboundEgressGuard,
        *,
        backend: httpcore.NetworkBackend | None = None,
    ) -> None:
        self._guard = guard
        self._backend = backend or httpcore.SyncBackend()

    def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        _host, safe_port, target_ips = self._guard.validate_host_port_addresses(
            host,
            port,
        )
        last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for target_ip in target_ips:
            try:
                stream = self._backend.connect_tcp(
                    host=target_ip,
                    port=safe_port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
                continue
            try:
                server_address = stream.get_extra_info("server_addr")
                peer_ip = server_address[0] if server_address else None
                self._guard.validate_response_peer_ip(peer_ip)
                if not peer_ip or not _same_address(peer_ip, target_ip):
                    raise EgressGuardError("egress.peer_mismatch")
            except Exception:
                with suppress(Exception):
                    stream.close()
                raise
            return stream
        if last_error is not None:
            raise last_error
        raise EgressGuardError("egress.dns_resolution_failed")

    def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.NetworkStream:
        raise EgressGuardError("egress.unix_socket_not_allowed")

    def sleep(self, seconds: float) -> None:
        self._backend.sleep(seconds)


class GuardedAsyncNetworkBackend(httpcore.AsyncNetworkBackend):
    """Async counterpart of GuardedNetworkBackend."""

    def __init__(
        self,
        guard: OutboundEgressGuard,
        *,
        backend: httpcore.AsyncNetworkBackend | None = None,
    ) -> None:
        self._guard = guard
        self._backend = backend or httpcore.AnyIOBackend()

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        _host, safe_port, target_ips = self._guard.validate_host_port_addresses(
            host,
            port,
        )
        last_error: httpcore.ConnectError | httpcore.ConnectTimeout | None = None
        for target_ip in target_ips:
            try:
                stream = await self._backend.connect_tcp(
                    host=target_ip,
                    port=safe_port,
                    timeout=timeout,
                    local_address=local_address,
                    socket_options=socket_options,
                )
            except (httpcore.ConnectError, httpcore.ConnectTimeout) as exc:
                last_error = exc
                continue
            try:
                server_address = stream.get_extra_info("server_addr")
                peer_ip = server_address[0] if server_address else None
                self._guard.validate_response_peer_ip(peer_ip)
                if not peer_ip or not _same_address(peer_ip, target_ip):
                    raise EgressGuardError("egress.peer_mismatch")
            except Exception:
                with suppress(Exception):
                    await stream.aclose()
                raise
            return stream
        if last_error is not None:
            raise last_error
        raise EgressGuardError("egress.dns_resolution_failed")

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> httpcore.AsyncNetworkStream:
        raise EgressGuardError("egress.unix_socket_not_allowed")

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _CappedSyncStream(httpx.SyncByteStream):
    def __init__(self, stream: httpx.SyncByteStream, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes

    def __iter__(self):
        total = 0
        for chunk in self._stream:
            total += len(chunk)
            if total > self._max_bytes:
                raise EgressGuardError("egress.response_too_large")
            yield chunk

    def close(self) -> None:
        self._stream.close()


class _CappedAsyncStream(httpx.AsyncByteStream):
    def __init__(self, stream: httpx.AsyncByteStream, max_bytes: int) -> None:
        self._stream = stream
        self._max_bytes = max_bytes

    async def __aiter__(self):
        total = 0
        async for chunk in self._stream:
            total += len(chunk)
            if total > self._max_bytes:
                raise EgressGuardError("egress.response_too_large")
            yield chunk

    async def aclose(self) -> None:
        await self._stream.aclose()


class _GuardedTransportMixin:
    def _initialize_guard(
        self,
        *,
        operation: BoundOutboundOperation | None,
        guard: OutboundEgressGuard | None,
    ) -> None:
        if (operation is None) == (guard is None):
            raise ValueError("Exactly one outbound operation or guard is required")
        self._operation = operation
        self._guard = operation.guard if operation is not None else guard

    def _validate_request(self, request: httpx.Request) -> None:
        url = str(request.url)
        if self._operation is not None:
            self._operation.validate_url(url)
        else:
            self._guard.validate_url(url)
        self._guard.validate_method(request.method)

        expected_host = request.url.netloc.decode("ascii").lower()
        supplied_host = (request.headers.get("host") or "").strip().lower()
        if not supplied_host or supplied_host != expected_host:
            raise EgressGuardError("egress.host_header_mismatch")
        self._guard.validate_request_header_items(request.headers.multi_items())

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                request_size = int(content_length)
            except ValueError as exc:
                raise EgressGuardError("egress.invalid_content_length") from exc
            if request_size < 0:
                raise EgressGuardError("egress.invalid_content_length")
            if request_size > self._guard.policy.max_request_bytes:
                raise EgressGuardError("egress.request_too_large")
        elif request.method.upper() not in {"GET", "HEAD"}:
            try:
                request_size = len(request.content)
            except httpx.RequestNotRead as exc:
                raise EgressGuardError("egress.request_size_unverified") from exc
            if request_size > self._guard.policy.max_request_bytes:
                raise EgressGuardError("egress.request_too_large")

        if self._guard.policy.force_identity_encoding:
            request.headers["Accept-Encoding"] = "identity"


class GuardedHttpTransport(_GuardedTransportMixin, httpx.HTTPTransport):
    def __init__(
        self,
        guard: OutboundEgressGuard | None = None,
        *,
        operation: BoundOutboundOperation | None = None,
    ) -> None:
        self._initialize_guard(operation=operation, guard=guard)
        limits = httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=5.0,
        )
        super().__init__(
            verify=True,
            trust_env=False,
            http1=True,
            http2=False,
            limits=limits,
            retries=0,
        )
        self._pool.close()
        self._pool = httpcore.ConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=0,
            network_backend=GuardedNetworkBackend(self._guard),
        )

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        self._validate_request(request)
        response = super().handle_request(request)
        try:
            self._guard.validate_response_headers(
                response.headers,
                enforce_content_type=not response.is_redirect,
            )
        except Exception:
            response.close()
            raise
        response.stream = _CappedSyncStream(
            response.stream,
            self._guard.policy.max_response_bytes,
        )
        return response


class GuardedAsyncHttpTransport(_GuardedTransportMixin, httpx.AsyncHTTPTransport):
    def __init__(
        self,
        guard: OutboundEgressGuard | None = None,
        *,
        operation: BoundOutboundOperation | None = None,
    ) -> None:
        self._initialize_guard(operation=operation, guard=guard)
        limits = httpx.Limits(
            max_connections=10,
            max_keepalive_connections=5,
            keepalive_expiry=5.0,
        )
        super().__init__(
            verify=True,
            trust_env=False,
            http1=True,
            http2=False,
            limits=limits,
            retries=0,
        )
        self._pool = httpcore.AsyncConnectionPool(
            ssl_context=httpx.create_ssl_context(verify=True, trust_env=False),
            max_connections=limits.max_connections,
            max_keepalive_connections=limits.max_keepalive_connections,
            keepalive_expiry=limits.keepalive_expiry,
            http1=True,
            http2=False,
            retries=0,
            network_backend=GuardedAsyncNetworkBackend(self._guard),
        )

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self._validate_request(request)
        response = await super().handle_async_request(request)
        try:
            self._guard.validate_response_headers(
                response.headers,
                enforce_content_type=not response.is_redirect,
            )
        except Exception:
            await response.aclose()
            raise
        response.stream = _CappedAsyncStream(
            response.stream,
            self._guard.policy.max_response_bytes,
        )
        return response


__all__ = [
    "GuardedAsyncHttpTransport",
    "GuardedAsyncNetworkBackend",
    "GuardedHttpTransport",
    "GuardedNetworkBackend",
]
