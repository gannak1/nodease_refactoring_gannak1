"""Workflow draft에 저장하는 모델 라우팅 입력군 정의."""

from __future__ import annotations

import uuid
from typing import Any


MAX_REPRESENTATIVE_EXAMPLES = 5
MIN_REPRESENTATIVE_EXAMPLES = 3
HIGH_RISK_MIN_REPRESENTATIVE_EXAMPLES = 5


def normalize_model_routing_model_id(value: Any) -> str:
    """모델 비교에만 쓰는 provider-agnostic ID를 만든다.

    Google catalog처럼 ``models/`` 접두사가 붙는 경우와 OpenAI처럼 접두사가
    없는 경우를 같은 모델로 다룬다. 실제 provider 호출에는 원래 catalog ID를
    유지해야 하므로, 이 값은 권한/제외/중복 비교에만 사용한다.
    """
    return str(value or "").strip().lower().removeprefix("models/")


def filter_model_routing_available_model_ids(
    model_ids: list[str] | set[str] | tuple[str, ...],
    *,
    node_data: dict[str, Any],
) -> list[str]:
    """원래 catalog 표기를 보존한 채 node 제외 모델만 제거한다."""
    excluded_model_ids = model_routing_excluded_model_ids(node_data)
    return [
        model_id
        for model_id in model_ids
        if normalize_model_routing_model_id(model_id) not in excluded_model_ids
    ]


def _representative_examples(
    representative_query: str,
    raw_examples: Any,
) -> list[str]:
    values = raw_examples if isinstance(raw_examples, list) else []
    normalized: list[str] = []
    for raw in [representative_query, *values]:
        text = " ".join(str(raw or "").split())[:2000]
        if text and text not in normalized:
            normalized.append(text)
        if len(normalized) >= MAX_REPRESENTATIVE_EXAMPLES:
            break
    return normalized


def required_model_routing_cohort_example_count(safety_protected: bool) -> int:
    """일반 입력군과 고위험 입력군의 최소 대표 예문 수를 반환한다."""
    return (
        HIGH_RISK_MIN_REPRESENTATIVE_EXAMPLES
        if safety_protected
        else MIN_REPRESENTATIVE_EXAMPLES
    )


def validate_model_routing_cohort_examples(
    representative_examples: list[str],
    *,
    safety_protected: bool,
) -> None:
    required = required_model_routing_cohort_example_count(safety_protected)
    if len(representative_examples) < required:
        raise ValueError("model_routing.cohort_examples_insufficient")


def model_routing_excluded_model_ids(node_data: dict[str, Any]) -> set[str]:
    """노드가 자동 라우팅과 유료 검증에서 제외한 모델 ID를 정규화한다."""
    policy = node_data.get("model_routing_policy")
    raw_values = policy.get("excluded_model_ids") if isinstance(policy, dict) else None
    if not isinstance(raw_values, list):
        return set()
    return {
        normalized
        for value in raw_values
        if (normalized := normalize_model_routing_model_id(value))
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
        representative_examples = _representative_examples(
            representative_query,
            raw.get("representative_examples"),
        )
        if not label or not key or not representative_query:
            continue
        drafts.append(
            {
                "id": draft_id,
                "key": key,
                "label": label,
                "representative_query": representative_query,
                "representative_examples": representative_examples,
                "fixed": bool(raw.get("fixed")),
                "safety_protected": bool(raw.get("safety_protected")),
            }
        )
    return drafts


def add_model_routing_cohort_draft(
    node_data: dict[str, Any],
    *,
    label: str,
    key: str,
    representative_query: str,
    representative_examples: list[str] | None = None,
    fixed: bool,
    safety_protected: bool = False,
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
        "safety_protected": bool(safety_protected),
    }
    item["representative_examples"] = _representative_examples(
        item["representative_query"],
        representative_examples,
    )
    validate_model_routing_cohort_examples(
        item["representative_examples"],
        safety_protected=item["safety_protected"],
    )
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
    representative_examples: list[str] | None = None,
    fixed: bool,
    safety_protected: bool = False,
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
        "safety_protected": bool(safety_protected),
    }
    updated["representative_examples"] = _representative_examples(
        updated["representative_query"],
        representative_examples,
    )
    validate_model_routing_cohort_examples(
        updated["representative_examples"],
        safety_protected=updated["safety_protected"],
    )
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
