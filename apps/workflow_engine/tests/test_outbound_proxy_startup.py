from __future__ import annotations

from pathlib import Path

import pytest

from apps.shared.services.outbound_proxy_policy import (
    OutboundProxyConfigurationError,
)
from apps.workflow_engine import outbound_proxy_startup


WORKFLOW_TASKS = Path(__file__).resolve().parents[1] / "tasks.py"


def test_workflow_worker_rejects_invalid_proxy_before_consuming_tasks(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        outbound_proxy_startup,
        "require_outbound_proxy_security_ready",
        lambda: (_ for _ in ()).throw(
            OutboundProxyConfigurationError("egress.proxy_policy_revision_invalid")
        ),
    )

    with pytest.raises(OutboundProxyConfigurationError) as captured:
        outbound_proxy_startup.validate_outbound_proxy_worker_readiness()

    assert captured.value.reason_code == "egress.proxy_policy_revision_invalid"


def test_workflow_worker_child_rechecks_proxy_policy(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        outbound_proxy_startup,
        "require_outbound_proxy_security_ready",
        lambda: calls.append("checked"),
    )

    outbound_proxy_startup.validate_outbound_proxy_worker_process()

    assert calls == ["checked"]


def test_workflow_task_module_registers_outbound_proxy_startup_hooks() -> None:
    source = WORKFLOW_TASKS.read_text(encoding="utf-8")

    assert "from apps.workflow_engine import outbound_proxy_startup" in source
