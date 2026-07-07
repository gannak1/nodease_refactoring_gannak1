"""Red-phase tests for budget alert item serialization/redaction (BGA-REQ-051, 052).

순수 함수 `serialize_alert_item(item, viewer_is_manager)`를 검증한다.
- 저장된 알림 항목(스냅샷 필드 포함)을 API 응답 dict로 직렬화한다.
- 관리자 뷰어면 금액 필드(monthly_budget_usd, current_month_cost) 포함, member면 제외.
- `type`은 `status`에서 파생("budget.at_risk"/"budget.exceeded").
- 내부/secret 필드는 응답에 노출되지 않는다(허용 키만).

대응 문서: docs/features/budget-alerts/test_cases.md
  - Unit Tests > 리댁션 `serialize_alert_item`
  - Acceptance Criteria AC-5
  - api_spec.md > GET /notifications/budget 응답 shape(관리자/member)
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from apps.shared.services.budget_alerts import serialize_alert_item

_COMMON_KEYS = {
    "id",
    "type",
    "workflow_id",
    "workflow_name",
    "organization_id",
    "status",
    "usage_ratio",
    "read",
    "created_at",
}
_MANAGER_KEYS = _COMMON_KEYS | {"monthly_budget_usd", "current_month_cost"}


def _item(status="at_risk", **overrides):
    base = dict(
        id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        workflow_name="Nightly Summarizer",
        organization_id=uuid.uuid4(),
        status=status,
        usage_ratio=0.923457,
        monthly_budget_usd=100.0,
        current_month_cost=92.345678,
        read=False,
        created_at=datetime(2026, 7, 7, tzinfo=timezone.utc),
        # 응답에 노출되면 안 되는 내부 필드 (누출 방지 검증용)
        encrypted_config="SECRET",
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def test_manager_includes_amount_fields():
    item = _item()
    result = serialize_alert_item(item, viewer_is_manager=True)
    assert result["monthly_budget_usd"] == 100.0
    assert result["current_month_cost"] == 92.345678
    assert set(result.keys()) == _MANAGER_KEYS


def test_member_excludes_amount_fields():
    item = _item()
    result = serialize_alert_item(item, viewer_is_manager=False)
    assert "monthly_budget_usd" not in result
    assert "current_month_cost" not in result
    assert result["usage_ratio"] == 0.923457
    assert result["status"] == "at_risk"
    assert set(result.keys()) == _COMMON_KEYS


@pytest.mark.parametrize(
    "status, expected_type",
    [("at_risk", "budget.at_risk"), ("exceeded", "budget.exceeded")],
)
def test_type_derived_from_status(status, expected_type):
    item = _item(status=status)
    result = serialize_alert_item(item, viewer_is_manager=True)
    assert result["type"] == expected_type
    assert result["status"] == status


def test_common_fields_present_for_both_views():
    item = _item()
    for is_manager in (True, False):
        result = serialize_alert_item(item, viewer_is_manager=is_manager)
        assert _COMMON_KEYS <= set(result.keys())
        assert result["id"] == item.id
        assert result["workflow_id"] == item.workflow_id
        assert result["workflow_name"] == "Nightly Summarizer"
        assert result["organization_id"] == item.organization_id
        assert result["read"] is False
        assert result["created_at"] == item.created_at


def test_no_internal_or_secret_fields_leak():
    item = _item()
    for is_manager in (True, False):
        result = serialize_alert_item(item, viewer_is_manager=is_manager)
        assert "encrypted_config" not in result
        assert set(result.keys()) <= _MANAGER_KEYS
