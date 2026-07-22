"""Opt-in PostgreSQL evidence for the query-embedding capability migration."""

from __future__ import annotations

import os
import uuid

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.shared.alembic.versions import (
    ae2f3a4b5c6d_add_query_embedding_provider_capability as revision,
)
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError, OperationalError

RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_query_embedding"


def _create_legacy_schema(connection) -> None:
    statements = (
        """
            CREATE TABLE llm_deployment_credential_policies (
                id UUID PRIMARY KEY,
                organization_id UUID NOT NULL,
                deployment_id UUID NOT NULL,
                deployment_version INTEGER NOT NULL,
                node_id VARCHAR(255) NOT NULL,
                model_id UUID NOT NULL,
                is_active BOOLEAN NOT NULL,
                policy_revision INTEGER NOT NULL,
                CONSTRAINT ck_llm_deploy_credential_policy_revision
                    CHECK (deployment_version >= 1 AND policy_revision >= 1)
            )
        """,
        """
            CREATE UNIQUE INDEX uq_llm_deploy_credential_policy_active
                ON llm_deployment_credential_policies (
                    organization_id,
                    deployment_id,
                    deployment_version,
                    node_id
                ) WHERE is_active
        """,
        """
            CREATE INDEX ix_llm_deploy_credential_policy_lookup
                ON llm_deployment_credential_policies (
                    organization_id,
                    deployment_id,
                    deployment_version,
                    node_id,
                    is_active
                )
        """,
        """
            CREATE TABLE provider_execution_capabilities (
                id UUID PRIMARY KEY,
                purpose VARCHAR(32) NOT NULL,
                state VARCHAR(16) NOT NULL,
                output_token_cap INTEGER NOT NULL,
                execution_subject_kind VARCHAR(32) NOT NULL,
                billing_principal_kind VARCHAR(32) NOT NULL,
                audit_actor_kind VARCHAR(32) NOT NULL,
                permission_revision VARCHAR(64) NOT NULL,
                relation_revision VARCHAR(64) NOT NULL,
                egress_revision VARCHAR(64) NOT NULL,
                pricing_revision VARCHAR(64) NOT NULL,
                CONSTRAINT ck_provider_execution_capability_state CHECK (
                    purpose IN ('main_generation', 'memory_summary')
                    AND state IN ('active', 'revoked')
                    AND execution_subject_kind IN (
                        'user', 'anonymous_public', 'system'
                    )
                    AND billing_principal_kind = 'organization'
                    AND audit_actor_kind IN ('user', 'public', 'system')
                    AND length(permission_revision) = 64
                    AND length(relation_revision) = 64
                    AND length(egress_revision) = 64
                    AND length(pricing_revision) = 64
                )
            )
        """,
    )
    for statement in statements:
        connection.execute(text(statement))


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL migration integration",
)
def test_query_embedding_policy_upgrade_guarded_downgrade_and_reupgrade(
    monkeypatch,
) -> None:
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL connection settings are not safely configured",
            pytrace=False,
        ) from None

    database = f"{DB_PREFIX}_{uuid.uuid4().hex[:12]}"
    quoted_database = quote_disposable_database_name(database, prefix=DB_PREFIX)
    admin_engine = create_engine(
        config.database_url(config.maintenance_database),
        isolation_level="AUTOCOMMIT",
    )
    database_created = False
    test_engine = None

    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True
        test_engine = create_engine(config.database_url(database))

        organization_id = uuid.uuid4()
        deployment_id = uuid.uuid4()
        legacy_model_id = uuid.uuid4()
        query_model_a = uuid.uuid4()
        query_model_b = uuid.uuid4()
        with test_engine.begin() as connection:
            _create_legacy_schema(connection)
            connection.execute(
                text(
                    """
                    INSERT INTO llm_deployment_credential_policies (
                        id, organization_id, deployment_id, deployment_version,
                        node_id, model_id, is_active, policy_revision
                    ) VALUES (
                        :id, :organization_id, :deployment_id, 1,
                        'llm-1', :model_id, true, 1
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "organization_id": organization_id,
                    "deployment_id": deployment_id,
                    "model_id": legacy_model_id,
                },
            )
            operations = Operations(MigrationContext.configure(connection))
            monkeypatch.setattr(revision, "op", operations)

            revision.upgrade()

            purpose = connection.execute(
                text(
                    "SELECT purpose FROM llm_deployment_credential_policies "
                    "WHERE model_id = :model_id"
                ),
                {"model_id": legacy_model_id},
            ).scalar_one()
            assert purpose == "main_generation"

            for model_id in (query_model_a, query_model_b):
                connection.execute(
                    text(
                        """
                        INSERT INTO llm_deployment_credential_policies (
                            id, organization_id, deployment_id,
                            deployment_version, node_id, purpose, model_id,
                            is_active, policy_revision
                        ) VALUES (
                            :id, :organization_id, :deployment_id, 1,
                            'llm-1', 'query_embedding', :model_id, true, 1
                        )
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "organization_id": organization_id,
                        "deployment_id": deployment_id,
                        "model_id": model_id,
                    },
                )

            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO llm_deployment_credential_policies (
                            id, organization_id, deployment_id,
                            deployment_version, node_id, purpose, model_id,
                            is_active, policy_revision
                        ) VALUES (
                            :id, :organization_id, :deployment_id, 1,
                            'llm-1', 'query_embedding', :model_id, true, 2
                        )
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "organization_id": organization_id,
                        "deployment_id": deployment_id,
                        "model_id": query_model_a,
                    },
                )

            connection.execute(
                text(
                    """
                    INSERT INTO provider_execution_capabilities (
                        id, purpose, state, execution_subject_kind,
                        output_token_cap, billing_principal_kind, audit_actor_kind,
                        permission_revision, relation_revision,
                        egress_revision, pricing_revision
                    ) VALUES (
                        :id, 'query_embedding', 'active', 'user', 0,
                        'organization', 'user', :permission_revision,
                        :relation_revision, :egress_revision, :pricing_revision
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "permission_revision": "a" * 64,
                    "relation_revision": "b" * 64,
                    "egress_revision": "c" * 64,
                    "pricing_revision": "d" * 64,
                },
            )
            with pytest.raises(IntegrityError), connection.begin_nested():
                connection.execute(
                    text(
                        """
                        INSERT INTO provider_execution_capabilities (
                            id, purpose, state, execution_subject_kind,
                            output_token_cap, billing_principal_kind,
                            audit_actor_kind, permission_revision,
                            relation_revision, egress_revision, pricing_revision
                        ) VALUES (
                            :id, 'query_embedding', 'active', 'user', 1,
                            'organization', 'user', :permission_revision,
                            :relation_revision, :egress_revision,
                            :pricing_revision
                        )
                        """
                    ),
                    {
                        "id": uuid.uuid4(),
                        "permission_revision": "a" * 64,
                        "relation_revision": "b" * 64,
                        "egress_revision": "c" * 64,
                        "pricing_revision": "d" * 64,
                    },
                )

            with pytest.raises(RuntimeError, match="must be removed"):
                revision.downgrade()

            connection.execute(
                text(
                    "DELETE FROM provider_execution_capabilities "
                    "WHERE purpose = 'query_embedding'"
                )
            )
            connection.execute(
                text(
                    "DELETE FROM llm_deployment_credential_policies "
                    "WHERE purpose = 'query_embedding'"
                )
            )
            revision.downgrade()

            columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "llm_deployment_credential_policies"
                )
            }
            assert "purpose" not in columns
            assert connection.execute(
                text(
                    "SELECT count(*) FROM llm_deployment_credential_policies "
                    "WHERE model_id = :model_id"
                ),
                {"model_id": legacy_model_id},
            ).scalar_one() == 1

            revision.upgrade()
            assert connection.execute(
                text(
                    "SELECT purpose FROM llm_deployment_credential_policies "
                    "WHERE model_id = :model_id"
                ),
                {"model_id": legacy_model_id},
            ).scalar_one() == "main_generation"
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if test_engine is not None:
            test_engine.dispose()
        if database_created:
            try:
                with admin_engine.connect() as connection:
                    connection.execute(
                        text(
                            """
                            SELECT pg_terminate_backend(pid)
                            FROM pg_stat_activity
                            WHERE datname = :database
                              AND pid <> pg_backend_pid()
                            """
                        ),
                        {"database": database},
                    )
                    connection.execute(
                        text(f"DROP DATABASE IF EXISTS {quoted_database}")
                    )
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup could not connect; "
                    "connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()
