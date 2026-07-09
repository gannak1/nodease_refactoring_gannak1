import sys
import types
import uuid
from types import SimpleNamespace

from apps.gateway.api.v1.endpoints import knowledge as knowledge_endpoint
from apps.shared.db.models.knowledge import KnowledgeBase
from apps.shared.db.models.team import TeamKnowledgePermission, UserKnowledgePermission


class _DeleteQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is KnowledgeBase:
            return self.db.kb
        return None

    def delete(self, **kwargs):
        self.db.operations.append(("permission_delete", self.model))
        return 1


class _DeleteDb:
    def __init__(self, kb):
        self.kb = kb
        self.operations = []
        self.committed = False

    def query(self, model):
        return _DeleteQuery(self, model)

    def delete(self, row):
        self.operations.append(("kb_delete", row))

    def commit(self):
        self.committed = True


def test_delete_knowledge_base_cleans_direct_permissions_before_kb_delete(
    monkeypatch,
):
    kb_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    kb = SimpleNamespace(
        id=kb_id,
        organization_id=organization_id,
        user_id=user_id,
        documents=[],
    )
    db = _DeleteDb(kb)
    current_user = SimpleNamespace(id=user_id)

    storage_module = types.ModuleType("services.storage")
    storage_module.get_storage_service = lambda: SimpleNamespace(
        delete=lambda _path: None
    )
    monkeypatch.setitem(sys.modules, "services", types.ModuleType("services"))
    monkeypatch.setitem(sys.modules, "services.storage", storage_module)

    response = knowledge_endpoint.delete_knowledge_base.__wrapped__(
        kb_id=kb_id,
        db=db,
        current_user=current_user,
    )

    assert response.status_code == 204
    assert db.operations == [
        ("permission_delete", UserKnowledgePermission),
        ("permission_delete", TeamKnowledgePermission),
        ("kb_delete", kb),
    ]
    assert db.committed is True
