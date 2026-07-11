from __future__ import annotations

from typing import Any, Mapping


RAG_PII_POLICY_REASON = "rag.pii_evidence_detected"
LEGACY_RAG_PII_POLICY_REASON = "pii_policy_blocked"

_CANONICAL_POLICY_REASONS = frozenset({RAG_PII_POLICY_REASON})
_LEGACY_POLICY_REASON_ALIASES = {
    LEGACY_RAG_PII_POLICY_REASON: RAG_PII_POLICY_REASON,
}


def normalize_security_alert_policy_reason(
    audit_metadata: Mapping[str, Any],
) -> str | None:
    policy_reason = audit_metadata.get("policy_reason")
    if isinstance(policy_reason, str) and policy_reason in _CANONICAL_POLICY_REASONS:
        return policy_reason

    policy_result = audit_metadata.get("policy_result")
    if not isinstance(policy_result, Mapping):
        return None
    legacy_reason = policy_result.get("reason_code")
    if not isinstance(legacy_reason, str):
        return None
    return _LEGACY_POLICY_REASON_ALIASES.get(legacy_reason)


def with_normalized_security_alert_policy_reason(
    audit_metadata: Mapping[str, Any],
) -> dict[str, Any]:
    normalized_metadata = dict(audit_metadata)
    policy_reason = normalize_security_alert_policy_reason(audit_metadata)
    if policy_reason is not None:
        normalized_metadata["policy_reason"] = policy_reason
    return normalized_metadata
