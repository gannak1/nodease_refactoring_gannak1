from __future__ import annotations


class MemoryDomainError(RuntimeError):
    """Base typed error containing only a safe public reason code."""

    code = "memory.invariant_violation"

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class SessionNotFoundError(MemoryDomainError):
    code = "memory.session_hidden"


class SessionNotActiveError(MemoryDomainError):
    code = "memory.session_hidden"


class SessionClosedError(SessionNotActiveError):
    code = "memory.session_closed"


class StaleRevisionError(MemoryDomainError):
    code = "memory.stale_revision"


class StaleLifecycleRevisionError(StaleRevisionError):
    code = "memory.stale_lifecycle_revision"


class StaleTurnVersionError(StaleRevisionError):
    code = "memory.stale_turn_version"


class ActiveTurnConflictError(MemoryDomainError):
    code = "memory.active_turn_conflict"


class DuplicateRequestConflictError(MemoryDomainError):
    code = "memory.duplicate_request_conflict"


class InvalidTurnTransitionError(MemoryDomainError):
    code = "memory.stale_turn_version"


class DispatchStateConflictError(StaleRevisionError):
    code = "memory.dispatch_state_conflict"


class MemoryAdapterUnavailableError(MemoryDomainError):
    code = "memory.adapter_unavailable"


class EntryNotFoundError(MemoryDomainError):
    code = "memory.entry_not_found"
