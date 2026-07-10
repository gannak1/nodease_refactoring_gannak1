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
        if self.db.delete_error_model is self.model:
            raise RuntimeError("permission cleanup failed")
        self.db.operations.append(("permission_delete", self.model))
        return 1


class _LifecycleDb:
    def __init__(self, kb, *, commit_error=None, delete_error_model=None):
        self.kb = kb
        self.commit_error = commit_error
        self.delete_error_model = delete_error_model
        self.operations = []
        self.filters = []
        self.committed = False
        self.rolled_back = False

    def query(self, model):
        return _LifecycleQuery(self, model)

    def delete(self, row):
        self.operations.append(("kb_delete", row))

    def commit(self):
        if self.commit_error is not None:
            raise self.commit_error
        self.committed = True

    def rollback(self):
        self.rolled_back = True


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


def test_delete_owned_knowledge_base_continues_after_one_storage_delete_failure(
    caplog,
):
    first_path = "private/failing.pdf"
    second_path = "private/succeeds.pdf"
    first_doc = SimpleNamespace(id=uuid.uuid4(), file_path=first_path)
    second_doc = SimpleNamespace(id=uuid.uuid4(), file_path=second_path)
    kb = _kb(documents=[first_doc, second_doc])
    db = _LifecycleDb(kb)

    class _PartiallyFailingStorage:
        def __init__(self):
            self.deleted_paths = []

        def delete(self, file_path):
            self.deleted_paths.append(file_path)
            if file_path == first_path:
                raise OSError("provider detail must not be logged")

    storage = _PartiallyFailingStorage()

    with caplog.at_level(
        logging.WARNING,
        logger="apps.gateway.services.knowledge_lifecycle_service",
    ):
        KnowledgeLifecycleService(
            db,
            storage_service_factory=lambda: storage,
        ).delete_owned_knowledge_base(kb.id, kb.user_id)

    assert storage.deleted_paths == [first_path, second_path]
    assert db.committed is True
    assert str(first_doc.id) in caplog.text
    assert "OSError" in caplog.text
    assert first_path not in caplog.text
    assert second_path not in caplog.text
    assert "provider detail must not be logged" not in caplog.text


def test_delete_owned_knowledge_base_rolls_back_and_propagates_commit_failure():
    doc = SimpleNamespace(id=uuid.uuid4(), file_path="private/document.pdf")
    kb = _kb(documents=[doc])
    commit_error = RuntimeError("commit failed")
    db = _LifecycleDb(kb, commit_error=commit_error)
    storage = _Storage()

    with pytest.raises(RuntimeError, match="commit failed") as exc_info:
        KnowledgeLifecycleService(
            db,
            storage_service_factory=lambda: storage,
        ).delete_owned_knowledge_base(kb.id, kb.user_id)

    assert exc_info.value is commit_error
    assert db.committed is False
    assert db.rolled_back is True
    assert storage.deleted_paths == [doc.file_path]


def test_delete_owned_knowledge_base_rolls_back_permission_cleanup_failure():
    kb = _kb()
    db = _LifecycleDb(kb, delete_error_model=TeamKnowledgePermission)

    with pytest.raises(RuntimeError, match="permission cleanup failed"):
        KnowledgeLifecycleService(
            db,
            storage_service_factory=lambda: _Storage(),
        ).delete_owned_knowledge_base(kb.id, kb.user_id)

    assert db.operations == [
        ("permission_delete", UserKnowledgePermission),
    ]
    assert db.committed is False
    assert db.rolled_back is True


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
    assert db.rolled_back is False
