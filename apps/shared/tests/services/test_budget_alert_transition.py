"""Red-phase tests for budget alert transition decision logic (BGA-REQ-010, 013).

순수 함수 `decide_alert_transition(last_status, new_status)`를 검증한다.
- last_status: 당월 마지막 알린 상태(high-water mark). None | "at_risk" | "exceeded".
- new_status: 이번 재계산 상태. "normal" | "at_risk" | "exceeded".
- 반환: 발송할 임계("at_risk" | "exceeded") 또는 발송 없음(None).

대응 문서: docs/features/budget-alerts/test_cases.md
  - Unit Tests > 전이 판정 `decide_alert_transition`
  - Acceptance Criteria AC-2, AC-3
  - Boundary Cases > 임계 경계에서의 발송 / 전이 기록 당월 단조성
"""

import pytest

from apps.shared.services.budget_alerts import decide_alert_transition


@pytest.mark.parametrize(
    "last_status, new_status, expected",
    [
        # 상향 전이 → 해당 임계 발송 (BGA-REQ-010)
        (None, "at_risk", "at_risk"),
        (None, "exceeded", "exceeded"),  # 첫 run 곧바로 초과 → exceeded 1건만
        ("at_risk", "exceeded", "exceeded"),
        # 같은 임계 유지 → 미발송 (BGA-REQ-011)
        ("at_risk", "at_risk", None),
        ("exceeded", "exceeded", None),
        # 하향 전이 → 미발송 (BGA-REQ-013)
        ("exceeded", "at_risk", None),
        ("at_risk", "normal", None),
        ("exceeded", "normal", None),
        # 정상 유지 → 미발송
        (None, "normal", None),
    ],
)
def test_decide_alert_transition(last_status, new_status, expected):
    assert decide_alert_transition(last_status, new_status) == expected


def test_straight_jump_to_exceeded_sends_exceeded_only():
    # normal(None)에서 곧바로 100% 초과 → exceeded 1건만, at_risk 별도 발송 없음
    assert decide_alert_transition(None, "exceeded") == "exceeded"


def test_same_threshold_does_not_resend_within_month():
    # high-water mark: at_risk 알린 뒤 같은 달 재도달은 재발송 안 함 (BGA-REQ-013)
    assert decide_alert_transition("at_risk", "at_risk") is None


def test_downward_never_sends():
    for new_status in ("normal", "at_risk"):
        assert decide_alert_transition("exceeded", new_status) is None


def test_pure_function_has_no_side_effects():
    # 동일 입력 반복 호출은 동일 결과 (DB/시간 의존 없음)
    assert decide_alert_transition(None, "at_risk") == "at_risk"
    assert decide_alert_transition(None, "at_risk") == "at_risk"
