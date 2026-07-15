"""Workflow draft에 저장하는 모델 라우팅 입력군 정의."""

from __future__ import annotations

import uuid
from typing import Any


def model_routing_excluded_model_ids(node_data: dict[str, Any]) -> set[str]:
    """노드가 자동 라우팅과 유료 검증에서 제외한 모델 ID를 정규화한다."""
    policy = node_data.get("model_routing_policy")
    raw_values = policy.get("excluded_model_ids") if isinstance(policy, dict) else None
    if not isinstance(raw_values, list):
        return set()
    return {
        normalized
        for value in raw_values
        if (normalized := str(value or "").strip())
    }


def model_routing_cohort_drafts(node_data: dict[str, Any]) -> list[dict[str, Any]]:
    """손상된 graph 값은 제외하고 API와 runtime이 공유할 안전한 목록을 반환한다."""
    policy = node_data.get("model_routing_policy")
    raw_drafts = policy.get("cohort_drafts") if isinstance(policy, dict) else None
    if not isinstance(raw_drafts, list):
        return []

    drafts: list[dict[str, Any]] = []
    for raw in raw_drafts:
        if not isinstance(raw, dict):
            continue
        try:
            draft_id = str(uuid.UUID(str(raw.get("id"))))
        except (TypeError, ValueError):
            continue
        label = " ".join(str(raw.get("label") or "").split())[:255]
        key = str(raw.get("key") or "").strip().lower()[:128]
        representative_query = " ".join(
            str(raw.get("representative_query") or "").split()
        )[:2000]
        if not label or not key or not representative_query:
            continue
        drafts.append(
            {
                "id": draft_id,
                "key": key,
                "label": label,
                "representative_query": representative_query,
                "fixed": bool(raw.get("fixed")),
            }
        )
    return drafts


def add_model_routing_cohort_draft(
    node_data: dict[str, Any],
    *,
    label: str,
    key: str,
    representative_query: str,
    fixed: bool,
    draft_id: str | uuid.UUID | None = None,
) -> dict[str, Any]:
    """입력군 초안을 node data에 추가하고 정규화된 항목을 반환한다."""
    policy = node_data.get("model_routing_policy")
    policy = dict(policy) if isinstance(policy, dict) else {}
    drafts = model_routing_cohort_drafts(node_data)
    normalized_key = str(key or "").strip().lower()[:128]
    if any(item["key"] == normalized_key for item in drafts):
        raise ValueError("model_routing.cohort_key_exists")

    try:
        maximum = max(1, min(12, int(policy.get("max_cohorts", 6))))
    except (TypeError, ValueError):
        maximum = 6
    if len(drafts) >= maximum:
        raise ValueError("model_routing.cohort_limit_reached")

    item = {
        "id": str(uuid.UUID(str(draft_id))) if draft_id else str(uuid.uuid4()),
        "key": normalized_key,
        "label": " ".join(str(label or "").split())[:255],
        "representative_query": " ".join(
            str(representative_query or "").split()
        )[:2000],
        "fixed": bool(fixed),
    }
    if not item["key"] or not item["label"] or not item["representative_query"]:
        raise ValueError("model_routing.cohort_invalid")
    policy["cohort_drafts"] = [*drafts, item]
    node_data["model_routing_policy"] = policy
    return item


def update_model_routing_cohort_draft(
    node_data: dict[str, Any],
    *,
    draft_id: str | uuid.UUID,
    label: str,
    key: str,
    representative_query: str,
    fixed: bool,
) -> dict[str, Any] | None:
    """같은 draft UUID를 유지하면서 사용자가 바꾼 정의를 반영한다."""
    target_id = str(uuid.UUID(str(draft_id)))
    drafts = model_routing_cohort_drafts(node_data)
    target = next((item for item in drafts if item["id"] == target_id), None)
    if target is None:
        return None
    normalized_key = str(key or "").strip().lower()[:128]
    if any(
        item["id"] != target_id and item["key"] == normalized_key for item in drafts
    ):
        raise ValueError("model_routing.cohort_key_exists")
    updated = {
        "id": target_id,
        "key": normalized_key,
        "label": " ".join(str(label or "").split())[:255],
        "representative_query": " ".join(
            str(representative_query or "").split()
        )[:2000],
        "fixed": bool(fixed),
    }
    if not updated["key"] or not updated["label"] or not updated["representative_query"]:
        raise ValueError("model_routing.cohort_invalid")
    policy = node_data.get("model_routing_policy")
    policy = dict(policy) if isinstance(policy, dict) else {}
    policy["cohort_drafts"] = [
        updated if item["id"] == target_id else item for item in drafts
    ]
    node_data["model_routing_policy"] = policy
    return updated


def remove_model_routing_cohort_draft(
    node_data: dict[str, Any], *, draft_id: str | uuid.UUID
) -> bool:
    """초안 목록에서 UUID가 같은 항목만 제거한다."""
    target_id = str(uuid.UUID(str(draft_id)))
    drafts = model_routing_cohort_drafts(node_data)
    remaining = [item for item in drafts if item["id"] != target_id]
    if len(remaining) == len(drafts):
        return False
    policy = node_data.get("model_routing_policy")
    policy = dict(policy) if isinstance(policy, dict) else {}
    policy["cohort_drafts"] = remaining
    node_data["model_routing_policy"] = policy
    return True
