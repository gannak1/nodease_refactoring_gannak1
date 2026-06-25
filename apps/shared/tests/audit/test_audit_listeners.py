import pytest
from sqlalchemy import Integer, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from apps.shared.audit.context import clear_current_metadata, set_current_metadata
from apps.shared.audit import listeners


class Base(DeclarativeBase):
    pass


class AuditThing(Base):
    __tablename__ = "audit_things"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String)


@pytest.fixture
def session_factory(monkeypatch):
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)

    monkeypatch.setattr(listeners, "TRACKED_MODELS", {AuditThing: "thing"})
    monkeypatch.setattr(listeners, "SENSITIVE_FIELDS", {AuditThing: set()})
    listeners.register_audit_listeners()

    return sessionmaker(bind=engine)


def test_data_change_audit_emits_only_after_real_commit(
    monkeypatch, session_factory
):
    calls = []
    monkeypatch.setattr(listeners, "record_audit", lambda **event: calls.append(event))

    session = session_factory()
    thing = AuditThing(name="draft")
    session.add(thing)
    session.flush()

    assert calls == []

    session.commit()

    assert calls == [
        {
            "action": "thing.created",
            "category": "data_change",
            "actor_id": None,
            "actor_type": "system",
            "target_type": "thing",
            "target_id": 1,
            "before": None,
            "after": {"id": 1, "name": "draft"},
            "metadata": {},
        }
    ]


def test_data_change_audit_discards_real_rollback(monkeypatch, session_factory):
    calls = []
    monkeypatch.setattr(listeners, "record_audit", lambda **event: calls.append(event))

    session = session_factory()
    session.add(AuditThing(name="draft"))
    session.flush()
    session.rollback()

    assert calls == []


def test_data_change_audit_includes_request_metadata(monkeypatch, session_factory):
    calls = []
    monkeypatch.setattr(listeners, "record_audit", lambda **event: calls.append(event))

    token = set_current_metadata(
        {"ip": "127.0.0.1", "user_agent": "test-agent", "request_id": "req-test"}
    )
    try:
        session = session_factory()
        session.add(AuditThing(name="draft"))
        session.commit()
    finally:
        clear_current_metadata(token)

    assert calls == [
        {
            "action": "thing.created",
            "category": "data_change",
            "actor_id": None,
            "actor_type": "system",
            "target_type": "thing",
            "target_id": 1,
            "before": None,
            "after": {"id": 1, "name": "draft"},
            "metadata": {
                "ip": "127.0.0.1",
                "user_agent": "test-agent",
                "request_id": "req-test",
            },
        }
    ]


def test_data_change_audit_coalesces_multiple_flushes_before_commit(
    monkeypatch, session_factory
):
    calls = []
    monkeypatch.setattr(listeners, "record_audit", lambda **event: calls.append(event))

    session = session_factory()
    thing = AuditThing(name="draft")
    session.add(thing)
    session.flush()

    thing.name = "final"
    session.flush()
    session.commit()

    assert calls == [
        {
            "action": "thing.created",
            "category": "data_change",
            "actor_id": None,
            "actor_type": "system",
            "target_type": "thing",
            "target_id": 1,
            "before": None,
            "after": {"id": 1, "name": "final"},
            "metadata": {},
        }
    ]


def test_data_change_audit_skips_nested_transaction(monkeypatch, session_factory):
    calls = []
    monkeypatch.setattr(listeners, "record_audit", lambda **event: calls.append(event))

    session = session_factory()
    thing = AuditThing(name="outer")
    session.add(thing)
    session.flush()

    nested = session.begin_nested()
    thing.name = "inner"
    session.flush()
    nested.rollback()

    session.commit()

    assert calls == []
