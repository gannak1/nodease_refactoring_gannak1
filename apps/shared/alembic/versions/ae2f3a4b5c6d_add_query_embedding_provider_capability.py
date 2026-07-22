"""Add query-embedding provider capability and policy slots.

Revision ID: ae2f3a4b5c6d
Revises: ad1e2f3a4b5c
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ae2f3a4b5c6d"
down_revision: str | Sequence[str] | None = "ad1e2f3a4b5c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

QUERY_EMBEDDING_DOWNGRADE_GUARD = (
    "query_embedding policies or capabilities must be removed before downgrade"
)

_POLICY_CHECK = (
    "deployment_version >= 1 AND policy_revision >= 1 "
    "AND purpose IN ('main_generation', 'query_embedding')"
)
_CAPABILITY_CHECK = (
    "purpose IN ('main_generation', 'memory_summary', 'query_embedding') "
    "AND state IN ('active', 'revoked') "
    "AND execution_subject_kind IN ('user', 'anonymous_public', 'system') "
    "AND billing_principal_kind = 'organization' "
    "AND audit_actor_kind IN ('user', 'public', 'system') "
    "AND length(permission_revision) = 64 "
    "AND length(relation_revision) = 64 "
    "AND length(egress_revision) = 64 "
    "AND length(pricing_revision) = 64"
)
_LEGACY_CAPABILITY_CHECK = _CAPABILITY_CHECK.replace(
    ", 'query_embedding'",
    "",
)


def upgrade() -> None:
    op.add_column(
        "llm_deployment_credential_policies",
        sa.Column(
            "purpose",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'main_generation'"),
        ),
    )
    op.drop_constraint(
        "ck_llm_deploy_credential_policy_revision",
        "llm_deployment_credential_policies",
        type_="check",
    )
    op.create_check_constraint(
        "ck_llm_deploy_credential_policy_revision",
        "llm_deployment_credential_policies",
        _POLICY_CHECK,
    )

    op.drop_index(
        "uq_llm_deploy_credential_policy_active",
        table_name="llm_deployment_credential_policies",
    )
    op.create_index(
        "uq_llm_deploy_credential_policy_active",
        "llm_deployment_credential_policies",
        ["organization_id", "deployment_id", "deployment_version", "node_id"],
        unique=True,
        postgresql_where=sa.text(
            "is_active AND purpose = 'main_generation'"
        ),
    )
    op.create_index(
        "uq_llm_deploy_credential_policy_active_query_embedding",
        "llm_deployment_credential_policies",
        [
            "organization_id",
            "deployment_id",
            "deployment_version",
            "node_id",
            "model_id",
        ],
        unique=True,
        postgresql_where=sa.text(
            "is_active AND purpose = 'query_embedding'"
        ),
    )
    op.drop_index(
        "ix_llm_deploy_credential_policy_lookup",
        table_name="llm_deployment_credential_policies",
    )
    op.create_index(
        "ix_llm_deploy_credential_policy_lookup",
        "llm_deployment_credential_policies",
        [
            "organization_id",
            "deployment_id",
            "deployment_version",
            "node_id",
            "purpose",
            "model_id",
            "is_active",
        ],
    )

    op.drop_constraint(
        "ck_provider_execution_capability_state",
        "provider_execution_capabilities",
        type_="check",
    )
    op.create_check_constraint(
        "ck_provider_execution_capability_state",
        "provider_execution_capabilities",
        _CAPABILITY_CHECK,
    )
    op.create_check_constraint(
        "ck_provider_execution_capability_query_embedding_output",
        "provider_execution_capabilities",
        "purpose <> 'query_embedding' OR output_token_cap = 0",
    )


def downgrade() -> None:
    bind = op.get_bind()
    has_query_embedding_rows = bind.execute(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM llm_deployment_credential_policies "
            "WHERE purpose = 'query_embedding' "
            "UNION ALL "
            "SELECT 1 FROM provider_execution_capabilities "
            "WHERE purpose = 'query_embedding'"
            ")"
        )
    ).scalar()
    if has_query_embedding_rows:
        raise RuntimeError(QUERY_EMBEDDING_DOWNGRADE_GUARD)

    op.drop_constraint(
        "ck_provider_execution_capability_query_embedding_output",
        "provider_execution_capabilities",
        type_="check",
    )
    op.drop_constraint(
        "ck_provider_execution_capability_state",
        "provider_execution_capabilities",
        type_="check",
    )
    op.create_check_constraint(
        "ck_provider_execution_capability_state",
        "provider_execution_capabilities",
        _LEGACY_CAPABILITY_CHECK,
    )

    op.drop_index(
        "ix_llm_deploy_credential_policy_lookup",
        table_name="llm_deployment_credential_policies",
    )
    op.create_index(
        "ix_llm_deploy_credential_policy_lookup",
        "llm_deployment_credential_policies",
        [
            "organization_id",
            "deployment_id",
            "deployment_version",
            "node_id",
            "is_active",
        ],
    )
    op.drop_index(
        "uq_llm_deploy_credential_policy_active_query_embedding",
        table_name="llm_deployment_credential_policies",
    )
    op.drop_index(
        "uq_llm_deploy_credential_policy_active",
        table_name="llm_deployment_credential_policies",
    )
    op.create_index(
        "uq_llm_deploy_credential_policy_active",
        "llm_deployment_credential_policies",
        ["organization_id", "deployment_id", "deployment_version", "node_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )
    op.drop_constraint(
        "ck_llm_deploy_credential_policy_revision",
        "llm_deployment_credential_policies",
        type_="check",
    )
    op.create_check_constraint(
        "ck_llm_deploy_credential_policy_revision",
        "llm_deployment_credential_policies",
        "deployment_version >= 1 AND policy_revision >= 1",
    )
    op.drop_column("llm_deployment_credential_policies", "purpose")
