import importlib.util
import sys
import types
from pathlib import Path

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKeyConstraint,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB


def _load_team_module():
    root = Path(__file__).resolve().parents[2]
    packages = {
        "apps": root / "apps",
        "apps.shared": root / "apps" / "shared",
        "apps.shared.db": root / "apps" / "shared" / "db",
        "apps.shared.db.models": root / "apps" / "shared" / "db" / "models",
    }
    for name, path in packages.items():
        module = sys.modules.get(name) or types.ModuleType(name)
        module.__path__ = [str(path)]
        sys.modules[name] = module
        if "." in name:
            parent_name, child_name = name.rsplit(".", 1)
            setattr(sys.modules[parent_name], child_name, module)

    base_spec = importlib.util.spec_from_file_location(
        "apps.shared.db.base",
        root / "apps" / "shared" / "db" / "base.py",
    )
    base_module = importlib.util.module_from_spec(base_spec)
    sys.modules["apps.shared.db.base"] = base_module
    base_spec.loader.exec_module(base_module)
    sys.modules["apps.shared.db"].base = base_module

    team_spec = importlib.util.spec_from_file_location(
        "apps.shared.db.models.team",
        root / "apps" / "shared" / "db" / "models" / "team.py",
    )
    team_module = importlib.util.module_from_spec(team_spec)
    sys.modules["apps.shared.db.models.team"] = team_module
    team_spec.loader.exec_module(team_module)
    sys.modules["apps.shared.db.models"].team = team_module
    return team_module


def test_team_tables_use_final_names():
    team = _load_team_module()

    assert team.Team.__tablename__ == "teams"
    assert team.TeamMembership.__tablename__ == "team_memberships"
    assert team.TeamWorkflowPermission.__tablename__ == "team_workflow_permissions"
    assert team.UserWorkflowPermission.__tablename__ == "user_workflow_permissions"
    assert team.UserLLMPermission.__tablename__ == "user_llm_permissions"


def test_team_has_unique_team_id_organization_id_constraint():
    team = _load_team_module()

    assert any(
        isinstance(constraint, UniqueConstraint)
        and constraint.name == "uq_teams_id_organization_id"
        and [column.name for column in constraint.columns] == [
            "id",
            "organization_id",
        ]
        for constraint in team.Team.__table__.constraints
    )


def test_team_assignment_tables_have_composite_team_org_fk():
    team = _load_team_module()
    expected_constraints = {
        team.TeamMembership: "fk_team_memberships_team_org",
        team.TeamWorkflowPermission: "fk_team_workflow_permissions_team_org",
        team.TeamKnowledgePermission: "fk_team_knowledge_permissions_team_org",
        team.TeamLLMPermission: "fk_team_llm_permissions_team_org",
        team.TeamAuditPermission: "fk_team_audit_permissions_team_org",
    }

    for model, constraint_name in expected_constraints.items():
        foreign_keys = [
            constraint
            for constraint in model.__table__.constraints
            if isinstance(constraint, ForeignKeyConstraint)
        ]
        target = next(
            (
                constraint
                for constraint in foreign_keys
                if constraint.name == constraint_name
            ),
            None,
        )

        assert target is not None
        assert [column.name for column in target.columns] == [
            "team_id",
            "grantee_organization_id",
        ]
        assert [element.target_fullname for element in target.elements] == [
            "teams.id",
            "teams.organization_id",
        ]


def test_team_options_and_flags_columns():
    team = _load_team_module()
    expected_check_names = {
        team.Team: "ck_teams_flags_nonnegative",
        team.TeamMembership: "ck_team_memberships_flags_nonnegative",
        team.TeamWorkflowPermission: "ck_team_workflow_permissions_flags_nonnegative",
        team.TeamKnowledgePermission: "ck_team_knowledge_permissions_flags_nonnegative",
        team.TeamLLMPermission: "ck_team_llm_permissions_flags_nonnegative",
        team.TeamAuditPermission: "ck_team_audit_permissions_flags_nonnegative",
        team.UserWorkflowPermission: "ck_user_workflow_permissions_flags_nonnegative",
        team.UserLLMPermission: "ck_user_llm_permissions_flags_nonnegative",
    }

    for model, check_name in expected_check_names.items():
        assert "option" not in model.__table__.columns

        options_column = model.__table__.columns["options"]
        assert isinstance(options_column.type, JSONB)
        assert options_column.nullable is False

        flags_column = model.__table__.columns["flags"]
        assert isinstance(flags_column.type, BigInteger)
        assert flags_column.nullable is False

        assert any(
            isinstance(constraint, CheckConstraint)
            and constraint.name == check_name
            for constraint in model.__table__.constraints
        )


def test_auth_state_is_only_on_resource_permission_tables():
    team = _load_team_module()

    assert "auth_state" not in team.Team.__table__.columns
    assert "auth_state" not in team.TeamMembership.__table__.columns

    for model in (
        team.TeamWorkflowPermission,
        team.TeamKnowledgePermission,
        team.TeamLLMPermission,
        team.TeamAuditPermission,
        team.UserWorkflowPermission,
        team.UserLLMPermission,
    ):
        assert "auth_state" in model.__table__.columns


def test_user_direct_permission_tables_are_additive_user_resource_grants():
    team = _load_team_module()
    expected_unique_constraints = {
        team.UserWorkflowPermission: (
            "uq_user_workflow_permissions_org_user_workflow",
            ["grantee_organization_id", "user_id", "workflow_id"],
        ),
        team.UserLLMPermission: (
            "uq_user_llm_permissions_org_user_credential",
            ["grantee_organization_id", "user_id", "llm_credential_id"],
        ),
    }

    for model, (constraint_name, columns) in expected_unique_constraints.items():
        assert "team_id" not in model.__table__.columns
        assert any(
            isinstance(constraint, UniqueConstraint)
            and constraint.name == constraint_name
            and [column.name for column in constraint.columns] == columns
            for constraint in model.__table__.constraints
        )
