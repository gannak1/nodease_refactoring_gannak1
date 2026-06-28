from types import SimpleNamespace
from uuid import uuid4

from operator import eq
from sqlalchemy.sql.operators import is_

from apps.shared.db.models.team import (
    Team,
    TeamLLMPermission,
    TeamMembership,
    TeamWorkflowPermission,
    UserLLMPermission,
    UserWorkflowPermission,
)
from apps.shared.services.permission_enforcement import PermissionEnforcementService


def test_workflow_auth_state_denies_when_no_permission_rows():
    user_id = uuid4()
    organization_id = uuid4()
    workflow_id = uuid4()
    db = _Session()

    auth_state = PermissionEnforcementService.get_workflow_auth_state(
        db,
        organization_id,
        workflow_id,
        user_id,
    )

    assert auth_state == "none"
    assert not PermissionEnforcementService.has_workflow_manage_permission(
        db,
        organization_id,
        workflow_id,
        user_id,
    )


def test_workflow_auth_state_none_denies_manage():
    user_id = uuid4()
    organization_id = uuid4()
    workflow_id = uuid4()
    db = _Session(
        team_workflow_permissions=[
            _team_workflow_permission(
                organization_id=organization_id,
                workflow_id=workflow_id,
                team_id=uuid4(),
                auth_state="none",
                member_user_id=user_id,
            )
        ]
    )

    assert (
        PermissionEnforcementService.get_workflow_auth_state(
            db,
            organization_id,
            workflow_id,
            user_id,
        )
        == "none"
    )
    assert not PermissionEnforcementService.has_workflow_manage_permission(
        db,
        organization_id,
        workflow_id,
        user_id,
    )


def test_workflow_auth_state_invalid_value_fails_closed():
    user_id = uuid4()
    organization_id = uuid4()
    workflow_id = uuid4()
    db = _Session(
        team_workflow_permissions=[
            _team_workflow_permission(
                organization_id=organization_id,
                workflow_id=workflow_id,
                team_id=uuid4(),
                auth_state="admin",
                member_user_id=user_id,
            )
        ]
    )

    assert (
        PermissionEnforcementService.get_workflow_auth_state(
            db,
            organization_id,
            workflow_id,
            user_id,
        )
        == "none"
    )


def test_workflow_auth_state_uses_highest_team_or_user_direct_permission():
    user_id = uuid4()
    organization_id = uuid4()
    workflow_id = uuid4()
    db = _Session(
        team_workflow_permissions=[
            _team_workflow_permission(
                organization_id=organization_id,
                workflow_id=workflow_id,
                team_id=uuid4(),
                auth_state="viewer",
                member_user_id=user_id,
            )
        ],
        user_workflow_permissions=[
            _user_workflow_permission(
                organization_id=organization_id,
                workflow_id=workflow_id,
                user_id=user_id,
                auth_state="builder",
            )
        ],
    )

    assert (
        PermissionEnforcementService.get_workflow_auth_state(
            db,
            organization_id,
            workflow_id,
            user_id,
        )
        == "builder"
    )


def test_workflow_lower_user_direct_permission_does_not_reduce_team_permission():
    user_id = uuid4()
    organization_id = uuid4()
    workflow_id = uuid4()
    db = _Session(
        team_workflow_permissions=[
            _team_workflow_permission(
                organization_id=organization_id,
                workflow_id=workflow_id,
                team_id=uuid4(),
                auth_state="manager",
                member_user_id=user_id,
            )
        ],
        user_workflow_permissions=[
            _user_workflow_permission(
                organization_id=organization_id,
                workflow_id=workflow_id,
                user_id=user_id,
                auth_state="viewer",
            )
        ],
    )

    assert (
        PermissionEnforcementService.get_workflow_auth_state(
            db,
            organization_id,
            workflow_id,
            user_id,
        )
        == "manager"
    )
    assert PermissionEnforcementService.has_workflow_manage_permission(
        db,
        organization_id,
        workflow_id,
        user_id,
    )


def test_workflow_auth_state_excludes_inactive_team_permission():
    user_id = uuid4()
    organization_id = uuid4()
    workflow_id = uuid4()
    db = _Session(
        team_workflow_permissions=[
            _team_workflow_permission(
                organization_id=organization_id,
                workflow_id=workflow_id,
                team_id=uuid4(),
                auth_state="manager",
                member_user_id=user_id,
                team_is_active=False,
            )
        ]
    )

    assert (
        PermissionEnforcementService.get_workflow_auth_state(
            db,
            organization_id,
            workflow_id,
            user_id,
        )
        == "none"
    )


def test_llm_auth_state_uses_highest_team_or_user_direct_permission():
    user_id = uuid4()
    organization_id = uuid4()
    credential_id = uuid4()
    db = _Session(
        team_llm_permissions=[
            _team_llm_permission(
                organization_id=organization_id,
                credential_id=credential_id,
                team_id=uuid4(),
                auth_state="operator",
                member_user_id=user_id,
            )
        ],
        user_llm_permissions=[
            _user_llm_permission(
                organization_id=organization_id,
                credential_id=credential_id,
                user_id=user_id,
                auth_state="manager",
            )
        ],
    )

    assert (
        PermissionEnforcementService.get_llm_credential_auth_state(
            db,
            organization_id,
            credential_id,
            user_id,
        )
        == "manager"
    )
    assert PermissionEnforcementService.has_llm_credential_manage_permission(
        db,
        organization_id,
        credential_id,
        user_id,
    )


def test_llm_auth_state_invalid_and_inactive_team_fail_closed():
    user_id = uuid4()
    organization_id = uuid4()
    credential_id = uuid4()
    db = _Session(
        team_llm_permissions=[
            _team_llm_permission(
                organization_id=organization_id,
                credential_id=credential_id,
                team_id=uuid4(),
                auth_state="admin",
                member_user_id=user_id,
            ),
            _team_llm_permission(
                organization_id=organization_id,
                credential_id=credential_id,
                team_id=uuid4(),
                auth_state="manager",
                member_user_id=user_id,
                team_is_active=False,
            ),
        ]
    )

    assert (
        PermissionEnforcementService.get_llm_credential_auth_state(
            db,
            organization_id,
            credential_id,
            user_id,
        )
        == "none"
    )


class _Query:
    def __init__(self, items):
        self.items = items
        self.filter_expressions = []

    def join(self, *args):
        return self

    def filter(self, *expressions):
        self.filter_expressions.extend(expressions)
        return self

    def all(self):
        return [
            item
            for item in self.items
            if all(_matches_expression(item, expr) for expr in self.filter_expressions)
        ]


class _Session:
    def __init__(
        self,
        team_workflow_permissions=None,
        user_workflow_permissions=None,
        team_llm_permissions=None,
        user_llm_permissions=None,
    ):
        self.team_workflow_permissions = team_workflow_permissions or []
        self.user_workflow_permissions = user_workflow_permissions or []
        self.team_llm_permissions = team_llm_permissions or []
        self.user_llm_permissions = user_llm_permissions or []

    def query(self, model):
        if model is TeamWorkflowPermission:
            return _Query(self.team_workflow_permissions)
        if model is UserWorkflowPermission:
            return _Query(self.user_workflow_permissions)
        if model is TeamLLMPermission:
            return _Query(self.team_llm_permissions)
        if model is UserLLMPermission:
            return _Query(self.user_llm_permissions)
        raise AssertionError(f"Unexpected query model: {model}")


def _team_workflow_permission(
    organization_id,
    workflow_id,
    team_id,
    auth_state,
    member_user_id,
    team_is_active=True,
):
    return SimpleNamespace(
        auth_state=auth_state,
        workflow_id=workflow_id,
        grantee_organization_id=organization_id,
        team_id=team_id,
        member_user_id=member_user_id,
        membership_grantee_organization_id=organization_id,
        team_organization_id=organization_id,
        team_is_active=team_is_active,
    )


def _user_workflow_permission(organization_id, workflow_id, user_id, auth_state):
    return SimpleNamespace(
        auth_state=auth_state,
        workflow_id=workflow_id,
        grantee_organization_id=organization_id,
        user_id=user_id,
    )


def _team_llm_permission(
    organization_id,
    credential_id,
    team_id,
    auth_state,
    member_user_id,
    team_is_active=True,
):
    return SimpleNamespace(
        auth_state=auth_state,
        llm_credential_id=credential_id,
        grantee_organization_id=organization_id,
        team_id=team_id,
        member_user_id=member_user_id,
        membership_grantee_organization_id=organization_id,
        team_organization_id=organization_id,
        team_is_active=team_is_active,
    )


def _user_llm_permission(organization_id, credential_id, user_id, auth_state):
    return SimpleNamespace(
        auth_state=auth_state,
        llm_credential_id=credential_id,
        grantee_organization_id=organization_id,
        user_id=user_id,
    )


def _matches_expression(obj, expression):
    left_value = _column_value(obj, str(expression.left))

    if expression.operator is eq:
        if not hasattr(expression.right, "value"):
            return left_value == _column_value(obj, str(expression.right))
        return left_value == expression.right.value
    if expression.operator is is_:
        return left_value is (str(expression.right) == "true")
    raise AssertionError(f"Unexpected filter operator: {expression.operator}")


def _column_value(obj, column):
    missing = object()
    value_by_column = {
        "team_memberships.user_id": getattr(obj, "member_user_id", missing),
        "team_memberships.grantee_organization_id": getattr(
            obj,
            "membership_grantee_organization_id",
            missing,
        ),
        "teams.organization_id": getattr(obj, "team_organization_id", missing),
        "teams.is_active": getattr(obj, "team_is_active", missing),
        "team_workflow_permissions.workflow_id": getattr(
            obj,
            "workflow_id",
            missing,
        ),
        "team_workflow_permissions.grantee_organization_id": getattr(
            obj,
            "grantee_organization_id",
            missing,
        ),
        "user_workflow_permissions.user_id": getattr(obj, "user_id", missing),
        "user_workflow_permissions.workflow_id": getattr(
            obj,
            "workflow_id",
            missing,
        ),
        "user_workflow_permissions.grantee_organization_id": getattr(
            obj,
            "grantee_organization_id",
            missing,
        ),
        "team_llm_permissions.llm_credential_id": getattr(
            obj,
            "llm_credential_id",
            missing,
        ),
        "team_llm_permissions.grantee_organization_id": getattr(
            obj,
            "grantee_organization_id",
            missing,
        ),
        "user_llm_permissions.user_id": getattr(obj, "user_id", missing),
        "user_llm_permissions.llm_credential_id": getattr(
            obj,
            "llm_credential_id",
            missing,
        ),
        "user_llm_permissions.grantee_organization_id": getattr(
            obj,
            "grantee_organization_id",
            missing,
        ),
    }
    if column not in value_by_column:
        raise AssertionError(f"Unexpected filter column: {column}")
    if value_by_column[column] is missing:
        raise AssertionError(f"Missing fixture attribute for filter column: {column}")
    return value_by_column[column]
