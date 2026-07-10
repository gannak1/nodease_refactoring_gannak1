import logging
import uuid
from types import SimpleNamespace

import pytest

from apps.gateway.services.knowledge_lifecycle_service import (
    KnowledgeLifecycleNotFound,
    KnowledgeLifecycleService,
)
from apps.shared.db.models.knowledge import KnowledgeBase
from apps.shared.db.models.team import TeamKnowledgePermission, UserKnowledgePermission


class _LifecycleQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *_args, **_kwargs):
        self.db.filters.append((self.model, _args))
        return self

    def first(self):
        if self.model is KnowledgeBase:
            return self.db.kb
        return None

    def delete(self, **_kwargs):
        self.db.operations.append(("permission_delete", self.model))
        return 1


class _LifecycleDb:
    def __init__(self, kb):
        self.kb = kb
        self.operations = []
        self.filters = []
        self.committed = False

    def query(self, model):
        return _LifecycleQuery(self, model)

    def delete(self, row):
        self.operations.append(("kb_delete", row))

    def commit(self):
        self.committed = True


class _Storage:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.deleted_paths = []

    def delete(self, file_path):
        self.deleted_paths.append(file_path)
        if self.fail:
            raise OSError("storage failure")


def _kb(*, documents=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        documents=documents or [],
    )


def test_delete_owned_knowledge_base_deletes_files_permissions_and_kb():
    doc_with_file = SimpleNamespace(id=uuid.uuid4(), file_path="kb/doc.txt")
    doc_without_file = SimpleNamespace(id=uuid.uuid4(), file_path=None)
    kb = _kb(documents=[doc_with_file, doc_without_file])
    db = _LifecycleDb(kb)
    storage = _Storage()

    KnowledgeLifecycleService(
        db,
        storage_service_factory=lambda: storage,
    ).delete_owned_knowledge_base(kb.id, kb.user_id)

    assert storage.deleted_paths == ["kb/doc.txt"]
    assert db.operations == [
        ("permission_delete", UserKnowledgePermission),
        ("permission_delete", TeamKnowledgePermission),
        ("kb_delete", kb),
    ]
    permission_filters = {
        model: filters
        for model, filters in db.filters
        if model in {UserKnowledgePermission, TeamKnowledgePermission}
    }
    assert len(permission_filters[UserKnowledgePermission]) == 1
    assert len(permission_filters[TeamKnowledgePermission]) == 1
    assert db.committed is True


def test_delete_owned_knowledge_base_storage_failure_is_best_effort(caplog):
    sensitive_path = "private/customer-contract.pdf"
    doc = SimpleNamespace(id=uuid.uuid4(), file_path=sensitive_path)
    kb = _kb(documents=[doc])
    db = _LifecycleDb(kb)
    storage = _Storage(fail=True)

    with caplog.at_level(
        logging.WARNING,
        logger="apps.gateway.services.knowledge_lifecycle_service",
    ):
        KnowledgeLifecycleService(
            db,
            storage_service_factory=lambda: storage,
        ).delete_owned_knowledge_base(kb.id, kb.user_id)

    assert db.operations[-1] == ("kb_delete", kb)
    assert db.committed is True
    assert str(doc.id) in caplog.text
    assert "OSError" in caplog.text
    assert sensitive_path not in caplog.text


def test_delete_owned_knowledge_base_storage_factory_failure_is_best_effort(caplog):
    kb = _kb(documents=[SimpleNamespace(id=uuid.uuid4(), file_path="hidden/path")])
    db = _LifecycleDb(kb)

    def raise_storage_error():
        raise RuntimeError("sensitive storage configuration")

    with caplog.at_level(
        logging.WARNING,
        logger="apps.gateway.services.knowledge_lifecycle_service",
    ):
        KnowledgeLifecycleService(
            db,
            storage_service_factory=raise_storage_error,
        ).delete_owned_knowledge_base(kb.id, kb.user_id)

    assert db.operations[-1] == ("kb_delete", kb)
    assert db.committed is True
    assert "RuntimeError" in caplog.text
    assert "sensitive storage configuration" not in caplog.text
    assert "hidden/path" not in caplog.text


def test_delete_owned_knowledge_base_missing_owned_kb_does_not_mutate():
    db = _LifecycleDb(kb=None)
    storage_called = False

    def storage_factory():
        nonlocal storage_called
        storage_called = True
        return _Storage()

    with pytest.raises(KnowledgeLifecycleNotFound):
        KnowledgeLifecycleService(
            db,
            storage_service_factory=storage_factory,
        ).delete_owned_knowledge_base(uuid.uuid4(), uuid.uuid4())

    assert storage_called is False
    assert db.operations == []
    assert db.committed is False
