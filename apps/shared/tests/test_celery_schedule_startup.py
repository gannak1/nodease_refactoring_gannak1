from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace

import pytest
from apps.shared.domain.schedule_dispatch import ScheduleDispatchDomainError

celery_module = importlib.import_module("apps.shared.celery_app")


class _Engine:
    def __init__(self) -> None:
        self.disposed = False

    def dispose(self) -> None:
        self.disposed = True


def _install_noop_dotenv(monkeypatch) -> None:
    monkeypatch.setitem(
        sys.modules,
        "dotenv",
        SimpleNamespace(load_dotenv=lambda **kwargs: None),
    )


def test_worker_startup_rejects_invalid_schedule_settings_before_engine_dispose(
    monkeypatch,
):
    from apps.shared.db import session as session_module

    fake_engine = _Engine()
    _install_noop_dotenv(monkeypatch)
    monkeypatch.setattr(session_module, "engine", fake_engine)
    monkeypatch.setenv("SCHEDULE_DISPATCH_MODE", "unsupported")

    with pytest.raises(ScheduleDispatchDomainError):
        celery_module.init_worker_process()

    assert fake_engine.disposed is False


def test_worker_startup_validates_schedule_settings_then_resets_engine_pool(
    monkeypatch,
):
    from apps.shared.db import session as session_module

    fake_engine = _Engine()
    _install_noop_dotenv(monkeypatch)
    monkeypatch.setattr(session_module, "engine", fake_engine)
    monkeypatch.setenv("SCHEDULE_DISPATCH_MODE", "disabled")

    celery_module.init_worker_process()

    assert fake_engine.disposed is True
