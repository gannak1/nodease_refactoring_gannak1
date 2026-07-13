import uuid
from types import SimpleNamespace

import pytest

from apps.gateway.adapters.db.knowledge_domain_permissions import (
    SqlAlchemyKnowledgeDomainPermissionRepository,
)
from apps.gateway.application.knowledge_administration.domain_permissions import (
    DomainPermissionCommand,
)
from apps.shared.db.models.team import (
    TeamKnowledgeDomainPermission,
    UserKnowledgeDomainPermission,
)


class _PermissionQuery:
    def __init__(self, row):
        self.row = row
        self.for_update = False

    def filter(self, *args, **kwargs):
        return self

    def with_for_update(self):
        self.for_update = True
        return self

    def first(self):
        return self.row


class _PermissionDb:
    def __init__(self, row):
        self.query_result = _PermissionQuery(row)
        self.queried_models = []
        self.deleted = []

    def query(self, model):
        self.queried_models.append(model)
        return self.query_result

    def delete(self, row):
        self.deleted.append(row)


@pytest.mark.parametrize(
    ("subject_type", "expected_model"),
    [
        ("team", TeamKnowledgeDomainPermission),
        ("user", UserKnowledgeDomainPermission),
    ],
)
def test_revoke_locks_and_deletes_existing_permission_row(
    subject_type,
    expected_model,
):
    permission = SimpleNamespace(id=uuid.uuid4())
    db = _PermissionDb(permission)
    command = DomainPermissionCommand(
        actor_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        subject_type=subject_type,
        subject_id=uuid.uuid4(),
        permission_action="catalog_manage",
    )

    permission_id = SqlAlchemyKnowledgeDomainPermissionRepository(db).revoke(command)

    assert permission_id == permission.id
    assert db.queried_models == [expected_model]
    assert db.query_result.for_update is True
    assert db.deleted == [permission]


def test_revoke_absent_permission_still_uses_row_lock_query_without_delete():
    db = _PermissionDb(None)
    command = DomainPermissionCommand(
        actor_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        subject_type="team",
        subject_id=uuid.uuid4(),
        permission_action="sync_manage",
    )

    permission_id = SqlAlchemyKnowledgeDomainPermissionRepository(db).revoke(command)

    assert permission_id is None
    assert db.query_result.for_update is True
    assert db.deleted == []
