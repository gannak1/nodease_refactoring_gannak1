"""Ephemeral, allowlisted diagnostics for an explicitly enabled localhost benchmark."""

from __future__ import annotations

import os
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass


_MAX_RECORDS = 512
_OUTCOMES = frozenset({"disabled", "hit", "miss", "bypass", "error"})
_TERMINAL = frozenset(
    {
        "success",
        "provider_error",
        "validation_error",
        "timeout",
        "canceled",
    }
)


@dataclass(frozen=True)
class BenchmarkDiagnostic:
    user_id: uuid.UUID
    organization_id: uuid.UUID
    cache_outcome: str
    planning_latency_ms: int
    provider_call_count: int
    repair_call_count: int
    terminal_status: str
    validation_passed: bool

    def payload(self) -> dict[str, object]:
        return {
            "cache_outcome": self.cache_outcome,
            "planning_latency_ms": self.planning_latency_ms,
            "provider_call_count": self.provider_call_count,
            "repair_call_count": self.repair_call_count,
            "terminal_status": self.terminal_status,
            "validation_passed": self.validation_passed,
        }


class AgentBuilderBenchmarkDiagnostics:
    """Bounded process-local records; never stores input, IDs in payload, or secrets."""

    _records: OrderedDict[uuid.UUID, BenchmarkDiagnostic] = OrderedDict()
    _lock = threading.Lock()

    @classmethod
    def enabled(cls) -> bool:
        environment = os.getenv("NODE_ENV", "").strip().lower()
        return (
            environment not in {"production", "staging"}
            and os.getenv("AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED")
            == "true"
        )

    @classmethod
    def record(
        cls,
        *,
        request_id: uuid.UUID,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        outcome: str,
        planning_latency_ms: int,
        provider_call_count: int,
        repair_call_count: int,
        terminal_status: str,
        validation_passed: bool,
    ) -> None:
        if not cls.enabled() or outcome not in _OUTCOMES or terminal_status not in _TERMINAL:
            return
        if (
            isinstance(provider_call_count, bool)
            or isinstance(repair_call_count, bool)
            or not isinstance(provider_call_count, int)
            or not isinstance(repair_call_count, int)
            or provider_call_count < 0
            or provider_call_count > 2
            or repair_call_count < 0
            or repair_call_count > 1
            or repair_call_count > provider_call_count
            or (
                provider_call_count > 0
                and provider_call_count != repair_call_count + 1
            )
        ):
            return
        record = BenchmarkDiagnostic(
            user_id=user_id,
            organization_id=organization_id,
            cache_outcome=outcome,
            planning_latency_ms=max(0, min(int(planning_latency_ms), 600_000)),
            provider_call_count=provider_call_count,
            repair_call_count=repair_call_count,
            terminal_status=terminal_status,
            validation_passed=bool(validation_passed),
        )
        with cls._lock:
            cls._records[request_id] = record
            cls._records.move_to_end(request_id)
            while len(cls._records) > _MAX_RECORDS:
                cls._records.popitem(last=False)

    @classmethod
    def get_for_scope(
        cls, *, request_id: uuid.UUID, user_id: uuid.UUID, organization_id: uuid.UUID
    ) -> BenchmarkDiagnostic | None:
        with cls._lock:
            record = cls._records.get(request_id)
        if record is None or record.user_id != user_id or record.organization_id != organization_id:
            return None
        return record

    @classmethod
    def clear(cls) -> None:
        with cls._lock:
            cls._records.clear()


def is_loopback_host(host: str | None) -> bool:
    return host in {"127.0.0.1", "::1", "localhost", "testclient"}
