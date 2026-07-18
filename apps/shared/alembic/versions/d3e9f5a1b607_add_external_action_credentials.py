"""Add external action credential resources.

Revision ID: d3e9f5a1b607
Revises: f4a5b6c7d8e9
"""

import json
from collections.abc import Mapping, Sequence
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


revision: str = "d3e9f5a1b607"
down_revision: str | Sequence[str] | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_GITHUB_NODE_ALLOWED_DATA_FIELDS = frozenset(
    {
        "title",
        "description",
        "parameters",
        "action",
        "credential_id",
        "configuration_state",
        "repo_owner",
        "repo_name",
        "pr_number",
        "comment_body",
        "referenced_variables",
    }
)


def _redact_legacy_external_action_credentials(value: Any) -> Any:
    """Remove deprecated direct Slack/GitHub credential fields from JSON graphs.

    The migration deliberately never attempts to preserve or re-encrypt a value
    from a workflow graph.  Those graphs are broadly replicated durable data;
    they become unresolved and require an authorized user to bind a dedicated
    credential resource again.
    """

    if isinstance(value, list):
        return [_redact_legacy_external_action_credentials(item) for item in value]
    if not isinstance(value, Mapping):
        return value

    result = {
        str(key): _redact_legacy_external_action_credentials(item)
        for key, item in value.items()
    }
    node_type = result.get("type")
    data = result.get("data")
    if not isinstance(data, dict):
        return result
    if node_type == "slackPostNode":
        for field_name in (
            "url",
            "authConfig",
            "token",
            "headers",
            "body",
            "authType",
            "method",
            "timeout",
        ):
            data.pop(field_name, None)
        if data.get("parameters") not in (None, {}):
            data["parameters"] = {}
        if not data.get("credential_id"):
            data["configuration_state"] = "unresolved"
    elif node_type == "githubNode":
        for field_name in set(data).difference(_GITHUB_NODE_ALLOWED_DATA_FIELDS):
            data.pop(field_name, None)
        if data.get("parameters") not in (None, {}):
            data["parameters"] = {}
        if not data.get("credential_id"):
            data["configuration_state"] = "unresolved"
    return result


def _scrub_json_column(table_name: str, column_name: str, *, touch_updated_at: bool) -> None:
    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            f"SELECT id, {column_name} FROM {table_name} "
            f"WHERE {column_name} IS NOT NULL"
        )
    ).mappings()
    for row in rows:
        source = row[column_name]
        sanitized = _redact_legacy_external_action_credentials(source)
        if sanitized == source:
            continue
        update_suffix = ", updated_at = NOW()" if touch_updated_at else ""
        connection.execute(
            sa.text(
                f"UPDATE {table_name} SET {column_name} = CAST(:payload AS jsonb)"
                f"{update_suffix} WHERE id = :id"
            ),
            {"id": row["id"], "payload": json.dumps(sanitized)},
        )


def _scrub_legacy_graph_credentials() -> None:
    _scrub_json_column("workflows", "graph", touch_updated_at=True)
    _scrub_json_column("workflow_deployments", "graph_snapshot", touch_updated_at=False)
    _scrub_json_column("agent_builder_drafts", "preview_graph", touch_updated_at=True)
    _scrub_json_column(
        "agent_builder_drafts",
        "node_detail_previews",
        touch_updated_at=True,
    )
    _scrub_json_column(
        "agent_builder_requests",
        "response_payload",
        touch_updated_at=False,
    )


def upgrade() -> None:
    op.create_table(
        "external_action_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("credential_name", sa.String(length=255), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("encrypted_secret", sa.Text(), nullable=False),
        sa.Column("encryption_key_version", sa.String(length=64), nullable=False),
        sa.Column("encryption_algorithm", sa.String(length=32), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "status", sa.String(length=32), nullable=False, server_default="active"
        ),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "provider IN ('github', 'slack_api', 'slack_webhook')",
            name="ck_external_action_credentials_provider",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_external_action_credentials_status",
        ),
        sa.CheckConstraint(
            "revision > 0",
            name="ck_external_action_credentials_revision_positive",
        ),
        sa.ForeignKeyConstraint(["organization_id"], ["organization.id"]),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "id",
            "organization_id",
            name="uq_external_action_credentials_id_organization_id",
        ),
    )
    op.create_index(
        "ix_external_action_credentials_organization_id",
        "external_action_credentials",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_external_action_credentials_provider",
        "external_action_credentials",
        ["provider"],
        unique=False,
    )
    op.create_index(
        "ix_external_action_credentials_status",
        "external_action_credentials",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_external_action_credentials_created_by",
        "external_action_credentials",
        ["created_by"],
        unique=False,
    )

    op.create_table(
        "user_external_action_credential_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grantee_organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_state", sa.String(length=50), nullable=False, server_default="none"),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("flags", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "external_action_credential_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "auth_state IN ('none', 'viewer', 'operator', 'builder', 'manager')",
            name="ck_user_external_action_credential_permissions_auth_state",
        ),
        sa.CheckConstraint(
            "flags >= 0",
            name="ck_user_external_action_credential_permissions_flags_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["grantee_organization_id"], ["organization.id"]
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["external_action_credential_id", "grantee_organization_id"],
            [
                "external_action_credentials.id",
                "external_action_credentials.organization_id",
            ],
            name="fk_user_external_action_credential_permissions_credential_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grantee_organization_id",
            "user_id",
            "external_action_credential_id",
            name="uq_user_external_action_credential_permissions_org_user_credential",
        ),
    )
    for column in (
        "grantee_organization_id",
        "user_id",
        "assigned_by",
        "external_action_credential_id",
    ):
        op.create_index(
            f"ix_user_external_action_credential_permissions_{column}",
            "user_external_action_credential_permissions",
            [column],
            unique=False,
        )

    op.create_table(
        "team_external_action_credential_permissions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("grantee_organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("team_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("auth_state", sa.String(length=50), nullable=False, server_default="none"),
        sa.Column("assigned_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "options",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("flags", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "external_action_credential_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.CheckConstraint(
            "auth_state IN ('none', 'viewer', 'operator', 'builder', 'manager')",
            name="ck_team_external_action_credential_permissions_auth_state",
        ),
        sa.CheckConstraint(
            "flags >= 0",
            name="ck_team_external_action_credential_permissions_flags_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["grantee_organization_id"], ["organization.id"]
        ),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"]),
        sa.ForeignKeyConstraint(["assigned_by"], ["users.id"]),
        sa.ForeignKeyConstraint(
            ["team_id", "grantee_organization_id"],
            ["teams.id", "teams.organization_id"],
            name="fk_team_external_action_credential_permissions_team_org",
        ),
        sa.ForeignKeyConstraint(
            ["external_action_credential_id", "grantee_organization_id"],
            [
                "external_action_credentials.id",
                "external_action_credentials.organization_id",
            ],
            name="fk_team_external_action_credential_permissions_credential_org",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grantee_organization_id",
            "external_action_credential_id",
            "team_id",
            name="uq_team_external_action_credential_permissions_org_credential_team",
        ),
    )
    for column in (
        "grantee_organization_id",
        "team_id",
        "assigned_by",
        "external_action_credential_id",
    ):
        op.create_index(
            f"ix_team_external_action_credential_permissions_{column}",
            "team_external_action_credential_permissions",
            [column],
            unique=False,
        )

    _scrub_legacy_graph_credentials()


def downgrade() -> None:
    connection = op.get_bind()
    row_exists = connection.execute(
        sa.text("SELECT 1 FROM external_action_credentials LIMIT 1")
    ).first()
    if row_exists is not None:
        raise RuntimeError(
            "Cannot remove external action credentials while credential rows exist."
        )

    op.drop_table("team_external_action_credential_permissions")
    op.drop_table("user_external_action_credential_permissions")
    op.drop_table("external_action_credentials")
