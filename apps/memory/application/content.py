"""Canonical associated-data identities for encrypted Memory projections."""

from __future__ import annotations

import uuid


def memory_content_aad(
    *,
    organization_id: uuid.UUID,
    session_id: uuid.UUID,
    turn_id: uuid.UUID,
    entry_id: uuid.UUID,
    projection: str,
) -> str:
    if projection not in {"display", "model"}:
        raise ValueError("memory content projection is invalid")
    return ":".join(
        (
            "memory-content-v1",
            str(organization_id),
            str(session_id),
            str(turn_id),
            str(entry_id),
            projection,
        )
    )


__all__ = ["memory_content_aad"]
