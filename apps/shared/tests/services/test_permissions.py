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
    is_llm_model_blocked_by_policy,
    model_id_matches_pattern,
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


class FakeSqlAlchemyRow:
    def __init__(self, auth_state):
        self._mapping = {"auth_state": auth_state}


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


def test_workflow_permission_sqlalchemy_rows_are_unpacked_before_ranking():
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
        all_values=[
            [FakeSqlAlchemyRow("viewer")],
            [FakeSqlAlchemyRow("builder")],
        ],
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


def test_llm_permission_sqlalchemy_rows_are_unpacked_before_ranking():
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
        all_values=[
            [FakeSqlAlchemyRow("viewer")],
            [FakeSqlAlchemyRow("operator")],
        ],
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


def test_model_id_matches_policy_pattern_only_treats_star_as_wildcard():
    # Verifies exact and star-only model deny pattern matching MBA-43
    assert model_id_matches_pattern("GPT-5", "gpt-5") is True
    assert model_id_matches_pattern("gpt-5-mini", "gpt-5*") is True
    assert model_id_matches_pattern(" gpt-5 ", " GPT-5 ") is True
    assert model_id_matches_pattern("gpt-5x", "gpt-5?") is False


def test_llm_model_policy_blocks_membership_or_team_patterns():
    # Verifies team and membership options can deny runtime model use MBA-43
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    db = FakeDb(
        all_values=[
            [
                (
                    {"model_policy": {"unallowed_model_patterns": ["claude-*"]}},
                    {},
                ),
                (
                    {},
                    {"model_policy": {"unallowed_model_patterns": ["gpt-5"]}},
                ),
            ]
        ]
    )

    assert (
        is_llm_model_blocked_by_policy(
            db, user_id, organization_id, "claude-3-5-sonnet"
        )
        is True
    )

    db = FakeDb(
        all_values=[
            [
                (
                    {},
                    {"model_policy": {"unallowed_model_patterns": ["gpt-5"]}},
                )
            ]
        ]
    )
    assert is_llm_model_blocked_by_policy(db, user_id, organization_id, "GPT-5") is True
