"""Judge-first + 점진적 local router 정책의 단일 생성 경계."""

from __future__ import annotations

from typing import Any, Iterable


JUDGE_FIRST_STRATEGY_ID = "judge_bootstrap_incremental_v1"
DEFAULT_LOCAL_CONFIDENCE_THRESHOLD = 0.78


def build_judge_first_active_policy(
    *,
    policy_version: str,
    default_model_id: str,
    fallback_model_id: str | None,
    candidate_model_ids: Iterable[str],
    learning: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """실행 가능한 후보만 포함한 Judge-first active policy를 만든다."""

    candidates = _unique_model_ids(candidate_model_ids)
    default_model = str(default_model_id or "").strip()
    if not default_model:
        raise ValueError("model_routing.default_model_required")
    if default_model not in candidates:
        candidates.insert(0, default_model)

    fallback_model = str(fallback_model_id or "").strip() or None
    if fallback_model and fallback_model not in candidates:
        candidates.append(fallback_model)
    if fallback_model == default_model:
        fallback_model = None

    return {
        "strategy_id": JUDGE_FIRST_STRATEGY_ID,
        "policy_version": str(policy_version or "judge-first-v1"),
        "default_model_id": default_model,
        "fallback_model_id": fallback_model,
        "candidate_model_ids": candidates,
        "learning": dict(learning) if isinstance(learning, dict) else _empty_learning(),
    }


def normalize_judge_first_active_policy(
    active_policy: dict[str, Any] | None,
    *,
    policy_version: str,
    default_model_id: str,
    fallback_model_id: str | None,
    candidate_model_ids: Iterable[str],
) -> dict[str, Any]:
    """구형 전략 필드는 버리고 유효한 Judge-first 학습 상태만 보존한다."""

    source = active_policy if isinstance(active_policy, dict) else {}
    learning = (
        source.get("learning")
        if source.get("strategy_id") == JUDGE_FIRST_STRATEGY_ID
        and isinstance(source.get("learning"), dict)
        else None
    )
    return build_judge_first_active_policy(
        policy_version=policy_version,
        default_model_id=default_model_id,
        fallback_model_id=fallback_model_id,
        candidate_model_ids=candidate_model_ids,
        learning=learning,
    )


def is_judge_first_active_policy(active_policy: Any) -> bool:
    return (
        isinstance(active_policy, dict)
        and active_policy.get("strategy_id") == JUDGE_FIRST_STRATEGY_ID
    )


def _empty_learning() -> dict[str, Any]:
    return {
        "mode": "judge_first",
        "judged_request_count": 0,
        "selected_model_ids": [],
        "local_confidence_threshold": DEFAULT_LOCAL_CONFIDENCE_THRESHOLD,
    }


def _unique_model_ids(model_ids: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for model_id in model_ids:
        value = str(model_id or "").strip()
        if value and value not in seen:
            seen.add(value)
            result.append(value)
    return result
