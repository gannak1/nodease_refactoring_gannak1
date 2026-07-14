from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from apps.gateway.application.connectors.errors import (
    ConnectorProbeCapacityExceeded,
    ConnectorProbeFailed,
    ConnectorTargetNotAllowed,
)
from apps.gateway.application.connectors.models import (
    ConnectorTestCommand,
    ConnectorTestPolicy,
)
from apps.shared.services.egress_guard import (
    EgressGuardError,
    ensure_network_target_allowed,
)

_URL_HOST_MARKERS = ("://", "/", "@", "?", "#")


class StrictPostgresConnectorProbe:
    def __init__(self, policy: ConnectorTestPolicy) -> None:
        self._policy = policy
        self._executor = ThreadPoolExecutor(
            max_workers=policy.global_concurrency_limit,
            thread_name_prefix="connector-test",
        )
        self._capacity = threading.BoundedSemaphore(policy.global_concurrency_limit)

    async def probe(self, command: ConnectorTestCommand) -> bool:
        if not self._capacity.acquire(blocking=False):
            raise ConnectorProbeCapacityExceeded()

        loop = asyncio.get_running_loop()
        future = loop.run_in_executor(self._executor, self._probe_sync, command)
        release_deferred = False
        try:
            return await asyncio.shield(future)
        except asyncio.CancelledError:
            future.add_done_callback(self._release_capacity)
            release_deferred = True
            raise
        finally:
            if not release_deferred:
                self._capacity.release()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=False)

    def _release_capacity(self, _: asyncio.Future[bool]) -> None:
        self._capacity.release()

    def _probe_sync(self, command: ConnectorTestCommand) -> bool:
        engine = None
        try:
            host_input = command.host.strip()
            if not host_input or any(marker in host_input for marker in _URL_HOST_MARKERS):
                raise ConnectorTargetNotAllowed()

            host, port, host_address = ensure_network_target_allowed(
                host_input,
                command.port,
                allowed_ports=frozenset({5432}),
            )
            url = URL.create(
                drivername="postgresql+psycopg2",
                username=command.username,
                password=command.password,
                host=host,
                port=port,
                database=command.database,
                query={
                    "hostaddr": host_address,
                    "sslmode": "verify-full",
                    "sslrootcert": "system",
                },
            )
            engine = create_engine(
                url,
                poolclass=NullPool,
                connect_args={
                    "connect_timeout": self._policy.connect_timeout_seconds,
                    "options": (
                        "-c statement_timeout="
                        f"{self._policy.statement_timeout_seconds * 1000}"
                    ),
                },
            )
            with engine.connect() as connection:
                connection.execute(text("SET TRANSACTION READ ONLY"))
                return connection.execute(text("SELECT 1")).scalar_one() == 1
        except ConnectorTargetNotAllowed:
            raise
        except EgressGuardError:
            raise ConnectorTargetNotAllowed() from None
        except Exception:
            raise ConnectorProbeFailed() from None
        finally:
            if engine is not None:
                engine.dispose()


__all__ = ["StrictPostgresConnectorProbe"]
