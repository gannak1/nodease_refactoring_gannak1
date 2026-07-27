from __future__ import annotations

import hashlib
import math
import hmac
import json

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    IntentPlanningContext,
)
from apps.gateway.application.agent_builder.intent_rehydration import (
    CurrentKnowledgeResolution,
)
from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    CanonicalIntentTextRegistry,
)
from apps.gateway.services.knowledge_rag_recommendation_service import (
    KnowledgeRAGRecommendationService,
)
from apps.shared.schemas.knowledge import (
    KnowledgeRAGRecommendationRequest,
)

def _canonical_payload(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _hmac_token(
    key: bytes,
    *,
    domain: str,
    value: object,
) -> str:
    return hmac.new(
        key,
        domain.encode("ascii") + b"\0" + _canonical_payload(value),
        hashlib.sha256,
    ).hexdigest()


def _as_json_value(value: object) -> object:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    return value


_CACHE_SEMANTIC_METADATA_KEYS = frozenset(
    {
        "active_document_version_status",
        "collection_safe_topics",
        "is_system_managed",
        "kb_safe_topics",
        "lifecycle_state",
        "linked_kb_count_bucket",
        "route_scope_type",
        "runtime_reason_code",
        "safe_topics",
        "source_managed",
        "source_tier",
        "sync_state",
    }
)


_UNSAFE_CACHE_METADATA = object()


def _cache_semantic_value(value: object) -> object:
    """Keep only primitive cache semantics; nested structures need an explicit schema."""
    normalized = _as_json_value(value)
    if normalized is None or type(normalized) in {str, bool, int}:
        return normalized
    if type(normalized) is float:
        return normalized if math.isfinite(normalized) else _UNSAFE_CACHE_METADATA
    if type(normalized) in {list, tuple}:
        projected = []
        for item in normalized:
            safe_item = _cache_semantic_value(item)
            if safe_item is _UNSAFE_CACHE_METADATA or isinstance(safe_item, list):
                return _UNSAFE_CACHE_METADATA
            projected.append(safe_item)
        return projected
    return _UNSAFE_CACHE_METADATA


def _cache_semantic_metadata(value: object) -> dict[str, object]:
    """Return the closed, non-identifying metadata projection used by cache keys.

    Resolver payloads may include safe-to-display labels, descriptions, and
    protected-resource identifiers beside fields that affect planning. Only this
    reviewed allowlist is part of the cache contract. Allowed keys carry only
    primitive values or primitive lists; nested data needs an explicit projection
    and contract test before it can influence a cache key.
    """
    normalized = _as_json_value(value)
    if not isinstance(normalized, dict):
        return {}

    projection: dict[str, object] = {}
    for key in sorted(_CACHE_SEMANTIC_METADATA_KEYS.intersection(normalized)):
        semantic_value = _cache_semantic_value(normalized[key])
        if semantic_value is not _UNSAFE_CACHE_METADATA:
            projection[key] = semantic_value
    return projection

def _current_policy_revision(permission: object) -> str:
    safe_metadata = getattr(permission, "safe_metadata", None)
    if not isinstance(safe_metadata, dict):
        raise ValueError("current Knowledge policy revision unavailable")
    revision = safe_metadata.get("policy_revision")
    if isinstance(revision, str) and revision.strip():
        return revision.strip()

    freshness_epoch = getattr(permission, "freshness_epoch", None)
    if isinstance(freshness_epoch, bool) or not isinstance(freshness_epoch, int):
        raise ValueError("current Knowledge policy revision unavailable")
    return "derived-policy-state-v1:" + hashlib.sha256(
        _canonical_payload(
            {
                "effective_auth_state": getattr(permission, "effective_auth_state", None),
                "freshness_epoch": freshness_epoch,
                "reason_code": getattr(permission, "reason_code", None),
                "source_acl_state": getattr(permission, "source_acl_state", None),
            }
        )
    ).hexdigest()


def current_knowledge_context_fingerprint(
    *,
    db,
    user_id,
    organization_id,
    full_safe_message: str,
    hmac_key: bytes,
) -> str:
    """Return an order-independent HMAC of all current authorized Knowledge state.

    Resolver identities and relationship data stay request-transient. Only their
    domain-separated HMAC projection reaches the planning context or cache key.
    """
    if not isinstance(hmac_key, bytes) or len(hmac_key) < 32:
        raise ValueError("invalid cache fingerprint key")
    service = KnowledgeRAGRecommendationService(
        db,
        user_id=user_id,
        organization_id=organization_id,
    )
    response = service.recommend_for_builder(
        KnowledgeRAGRecommendationRequest(
            workflow_intent=full_safe_message,
            node_purpose=full_safe_message,
            intended_execution_subject_id=user_id,
            mode="auto",
            max_recommendations=20,
        ),
        include_materialized_refs=False,
        allow_unready_candidates=True,
        include_cache_fingerprint_projection=True,
    )
    if response.status == "unavailable":
        raise ValueError("current Knowledge resolver unavailable")

    candidates = getattr(response, "_cache_fingerprint_candidates", None)
    collections = getattr(response, "_cache_fingerprint_collections", None)
    if not isinstance(candidates, list) or not isinstance(collections, list):
        raise ValueError("current Knowledge cache projection unavailable")

    candidate_collection_tokens: dict[str, set[str]] = {}
    collection_records: dict[str, dict[str, object]] = {}
    for collection in collections:
        resource_id = getattr(collection, "collection_id", None)
        if resource_id is None:
            raise ValueError("current Knowledge collection binding invalid")
        collection_token = _hmac_token(
            hmac_key,
            domain="agent-builder-cache:knowledge-collection:v1",
            value={
                "organization_id": str(organization_id),
                "resource_id": str(resource_id),
            },
        )
        collection_records[collection_token] = {
            "collection": collection_token,
            "safe_metadata": _cache_semantic_metadata(
                getattr(collection, "safe_metadata", {})
            ),
        }
        for candidate in getattr(collection, "candidates", ()):
            candidate_id = getattr(candidate, "candidate_id", None)
            if candidate_id is None:
                raise ValueError("current Knowledge hierarchy candidate binding invalid")
            candidate_collection_tokens.setdefault(str(candidate_id), set()).add(
                collection_token
            )

    candidate_records: dict[str, dict[str, object]] = {}
    for candidate in candidates:
        resource_id = getattr(candidate, "candidate_id", None)
        permission = getattr(candidate, "permission", None)
        if resource_id is None or permission is None:
            raise ValueError("current Knowledge candidate binding invalid")
        candidate_token = _hmac_token(
            hmac_key,
            domain="agent-builder-cache:knowledge-kb:v1",
            value={
                "organization_id": str(organization_id),
                "resource_id": str(resource_id),
            },
        )
        candidate_records[candidate_token] = {
            "candidate": candidate_token,
            "candidate_type": str(getattr(candidate, "candidate_type", "unknown")),
            "permission": {
                "effective_auth_state": getattr(permission, "effective_auth_state", None),
                "freshness_epoch": getattr(permission, "freshness_epoch", None),
                "policy_revision": _current_policy_revision(permission),
                "reason_code": getattr(permission, "reason_code", None),
                "safe_metadata": _cache_semantic_metadata(
                    getattr(permission, "safe_metadata", {})
                ),
                "source_acl_state": getattr(permission, "source_acl_state", None),
            },
            "runtime_availability": str(
                getattr(candidate, "runtime_availability", "unknown")
            ),
            "safe_metadata": _cache_semantic_metadata(
                getattr(candidate, "safe_metadata", {})
            ),
            "collection_tokens": sorted(
                candidate_collection_tokens.get(str(resource_id), set())
            ),
        }

    projection = {
        "candidate_records": [
            candidate_records[token] for token in sorted(candidate_records)
        ],
        "collection_records": [
            collection_records[token] for token in sorted(collection_records)
        ],
        "reason_code": getattr(response, "reason_code", None),
        "status": response.status,
        "summary": _as_json_value(getattr(response, "summary", {})),
    }
    return _hmac_token(
        hmac_key,
        domain="agent-builder-cache:knowledge-context:v1",
        value=projection,
    )

def current_knowledge_resolutions(
    *,
    db,
    user_id,
    organization_id,
    context: IntentPlanningContext,
    plan: CachedIntentPlanV1,
) -> tuple[CurrentKnowledgeResolution, ...]:
    """Reissue request-current candidate handles after permission/lifecycle filtering."""
    registry = CanonicalIntentTextRegistry()
    summary = registry.project_summary(context.full_safe_message)
    if summary is None:
        raise ValueError("safe summary projection failed")
    service = KnowledgeRAGRecommendationService(
        db,
        user_id=user_id,
        organization_id=organization_id,
    )
    resolutions = []
    for ordinal, requirement in enumerate(plan.knowledge_requirements, start=1):
        topics = [
            registry.render_topic(ref, full_safe_message=context.full_safe_message)
            for ref in requirement.topic_refs
        ]
        response = service.recommend_for_builder(
            KnowledgeRAGRecommendationRequest(
                workflow_intent=summary,
                node_purpose="; ".join(topics) or requirement.evidence_kind,
                knowledge_requirement={"requirement_id": requirement.requirement_ref},
                safe_query_topics=topics,
                pending_resolution_ref=f"cache_knowledge_{ordinal}",
                safe_workflow_context_summary={
                    "planned_step_count": len(plan.logical_steps),
                    "required_capabilities": list(plan.ordered_capabilities),
                },
                intended_execution_subject_id=user_id,
                mode="auto",
                max_recommendations=20,
            ),
            include_materialized_refs=False,
            allow_unready_candidates=True,
        )
        if response.status == "unavailable":
            raise ValueError("current Knowledge resolver unavailable")
        handles = tuple(
            item.candidate_handle
            for item in response.recommendations
            if isinstance(item.candidate_handle, str)
            and item.candidate_handle
            and item.runtime_availability == "available"
        )
        if len(handles) != len(set(handles)):
            raise ValueError("current Knowledge handles are not unique")
        status = "ready" if len(handles) == 1 else "ambiguous" if len(handles) > 1 else "empty"
        resolutions.append(
            CurrentKnowledgeResolution(
                requirement_ref=requirement.requirement_ref,
                resolution_id=f"cache_knowledge_{ordinal}",
                status=status,
                candidate_handles=handles,
                # recommend_for_builder recreates the hierarchy, current permission,
                # lifecycle and runtime-readiness decision for this request. An empty
                # result is represented as an empty current resolution, not a reused
                # historic authorization decision.
                hierarchy_authorized=True,
                permission_allowed=True,
                lifecycle_active=True,
                operationally_ready=True,
            )
        )
    return tuple(resolutions)
