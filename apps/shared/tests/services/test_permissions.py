import uuid
from types import SimpleNamespace

from apps.shared.permissions import (
    auth_state_at_least,
    llm_credential_auth_state_allows,
    normalize_auth_state,
    normalize_resource_auth_state,
    workflow_auth_state_allows,
)
from apps.shared.services.permissions import (
    get_effective_llm_credential_auth_state,
    get_effective_workflow_auth_state,
    has_llm_credential_permission,
    has_workflow_permission,
)


class FakeQuery:
    def __init__(self, db):
        self.db = db

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self.db.first_values.pop(0)

    def all(self):
        return self.db.all_values.pop(0)


class FakeDb:
    def __init__(self, first_values=None, all_values=None):
        self.first_values = list(first_values or [])
        self.all_values = list(all_values or [])

    def query(self, *args, **kwargs):
        return FakeQuery(self)


def test_legacy_auth_states_normalize_to_mvp_auth_states():
    assert normalize_auth_state("read") == "viewer"
    assert normalize_auth_state("execute") == "operator"
    assert normalize_auth_state("write") == "builder"
    assert normalize_auth_state("admin") == "manager"
    assert auth_state_at_least("admin", "manager") is True


def test_workflow_permission_action_matrix():
    assert workflow_auth_state_allows("viewer", "read") is True
    assert workflow_auth_state_allows("viewer", "execute") is False
    assert workflow_auth_state_allows("operator", "execute") is True
    assert workflow_auth_state_allows("operator", "write") is False
    assert workflow_auth_state_allows("builder", "write") is True
    assert workflow_auth_state_allows("builder", "deploy") is False
    assert workflow_auth_state_allows("manager", "manage") is True


def test_audit_only_states_fail_closed_for_resource_permissions():
    assert normalize_resource_auth_state("auditor") == "none"
    assert normalize_resource_auth_state("raw_auditor") == "none"
    assert workflow_auth_state_allows("auditor", "read") is False
    assert workflow_auth_state_allows("raw_auditor", "execute") is False
    assert llm_credential_auth_state_allows("raw_auditor", "use") is False


def test_organization_owner_gets_manager_for_workflow():
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(
                id=organization_id,
                created_by=user_id,
                managed_by=None,
                is_active=True,
            ),
        ]
    )

    assert (
        get_effective_workflow_auth_state(db, user_id, workflow_id, organization_id)
        == "manager"
    )


def test_workflow_permissions_fail_closed_without_rows():
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[], []],
    )

    assert (
        get_effective_workflow_auth_state(db, user_id, workflow_id, organization_id)
        == "none"
    )


def test_direct_workflow_permission_is_additive_over_team_permission():
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[("viewer",)], [("builder",)]],
    )

    assert (
        get_effective_workflow_auth_state(db, user_id, workflow_id, organization_id)
        == "builder"
    )


def test_weaker_direct_workflow_permission_does_not_lower_team_permission():
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[("manager",)], [("viewer",)]],
    )

    assert (
        get_effective_workflow_auth_state(db, user_id, workflow_id, organization_id)
        == "manager"
    )


def test_audit_only_workflow_permission_does_not_override_valid_resource_permission():
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[("viewer",), ("raw_auditor",)], []],
    )

    assert (
        get_effective_workflow_auth_state(db, user_id, workflow_id, organization_id)
        == "viewer"
    )


def test_llm_credential_use_requires_operator_or_builder():
    assert llm_credential_auth_state_allows("viewer", "use") is False
    assert llm_credential_auth_state_allows("operator", "use") is True
    assert llm_credential_auth_state_allows("builder", "use") is True


def test_llm_credential_write_requires_manager():
    assert llm_credential_auth_state_allows("builder", "write") is False
    assert llm_credential_auth_state_allows("manager", "write") is True


def test_llm_credential_effective_permission_allows_direct_operator_use():
    user_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(
                id=credential_id,
                user_id=owner_id,
                organization_id=organization_id,
            ),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[], [("operator",)]],
    )

    assert (
        get_effective_llm_credential_auth_state(
            db, user_id, credential_id, organization_id
        )
        == "operator"
    )


def test_llm_credential_viewer_cannot_use():
    user_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(
                id=credential_id,
                user_id=owner_id,
                organization_id=organization_id,
            ),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[], [("viewer",)]],
    )

    assert has_llm_credential_permission(
        db, user_id, credential_id, "use", organization_id
    ) is False


def test_audit_only_llm_permission_does_not_grant_use():
    user_id = uuid.uuid4()
    owner_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(
                id=credential_id,
                user_id=owner_id,
                organization_id=organization_id,
            ),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[("raw_auditor",)], []],
    )

    assert has_llm_credential_permission(
        db, user_id, credential_id, "use", organization_id
    ) is False


def test_has_workflow_permission_uses_effective_auth_state():
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    db = FakeDb(
        first_values=[
            SimpleNamespace(id=workflow_id, organization_id=organization_id),
            SimpleNamespace(
                id=organization_id,
                created_by=uuid.uuid4(),
                managed_by=None,
                is_active=True,
            ),
        ],
        all_values=[[("operator",)], []],
    )

    assert has_workflow_permission(
        db, user_id, workflow_id, "execute", organization_id
    ) is True
