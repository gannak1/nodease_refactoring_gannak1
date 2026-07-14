import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from apps.shared.db import demo_seed
from apps.shared.domain.knowledge_runtime_candidates import (
    AuthenticatedAudience,
    KnowledgeRuntimeCandidateRequest,
)
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from apps.workflow_engine.adapters.knowledge_runtime_candidates import (
    PostgresKnowledgeRuntimeCandidateSnapshotAdapter,
)
from apps.workflow_engine.application.runtime_retrieval.knowledge_candidates import (
    KnowledgeRuntimeCandidateResolver,
)
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_disposable"


def _run_seed_command(
    args: list[str],
    *,
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    env = config.subprocess_environment(
        database=database,
        root_dir=ROOT_DIR,
        extra={
            "NODEASE_DEMO_REGENERATE_KNOWLEDGE_FIXTURE": "0",
            "NODEASE_DEMO_ENABLE_RUNTIME_OPENAI_CREDENTIAL": "0",
        },
    )
    result = subprocess.run(
        [sys.executable, *args],
        cwd=ROOT_DIR,
        env=env,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        returncode = result.returncode
        del result
        pytest.fail(
            f"command failed with exit code {returncode}; "
            "stdout/stderr omitted to avoid leaking local configuration"
        )


def _enable_vector_extension(
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    engine = create_engine(
        config.database_url(database),
        isolation_level="AUTOCOMMIT",
    )
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    finally:
        engine.dispose()


def _snapshot_counts(
    database: str,
    config: DisposablePostgresConfig,
) -> dict[str, int]:
    engine = create_engine(config.database_url(database))
    try:
        with engine.connect() as conn:
            return {
                "knowledge_bases": conn.execute(
                    text("SELECT COUNT(*) FROM knowledge_bases")
                ).scalar_one(),
                "documents": conn.execute(
                    text("SELECT COUNT(*) FROM documents")
                ).scalar_one(),
                "document_chunks": conn.execute(
                    text("SELECT COUNT(*) FROM document_chunks")
                ).scalar_one(),
                "document_chunk_document_orphans": conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM document_chunks c
                        LEFT JOIN documents d ON d.id = c.document_id
                        WHERE d.id IS NULL
                        """
                    )
                ).scalar_one(),
                "document_chunk_kb_orphans": conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM document_chunks c
                        LEFT JOIN knowledge_bases kb ON kb.id = c.knowledge_base_id
                        WHERE kb.id IS NULL
                        """
                    )
                ).scalar_one(),
                "document_kb_orphans": conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM documents d
                        LEFT JOIN knowledge_bases kb ON kb.id = d.knowledge_base_id
                        WHERE kb.id IS NULL
                        """
                    )
                ).scalar_one(),
                "knowledge_ingestion_outbox": conn.execute(
                    text("SELECT COUNT(*) FROM knowledge_ingestion_outbox")
                ).scalar_one(),
            }
    finally:
        engine.dispose()


def _insert_demo_user_knowledge_permission(
    database: str,
    config: DisposablePostgresConfig,
) -> None:
    engine = create_engine(config.database_url(database))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO user_knowledge_permissions (
                        id,
                        grantee_organization_id,
                        user_id,
                        knowledge_base_id,
                        auth_state,
                        assigned_by,
                        assigned_at,
                        options,
                        flags
                    ) VALUES (
                        :id,
                        :organization_id,
                        :user_id,
                        :knowledge_base_id,
                        'manager',
                        :user_id,
                        NOW(),
                        '{}'::jsonb,
                        0
                    )
                    """
                ),
                {
                    "id": uuid.uuid4(),
                    "organization_id": demo_seed.ORG_ID,
                    "user_id": demo_seed.USER_IDS["admin"],
                    "knowledge_base_id": demo_seed.KB_IDS["onboarding_platform"],
                },
            )
    finally:
        engine.dispose()


def _insert_non_demo_knowledge_base(
    database: str,
    config: DisposablePostgresConfig,
) -> uuid.UUID:
    knowledge_base_id = uuid.uuid4()
    engine = create_engine(config.database_url(database))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO knowledge_bases (
                        id,
                        organization_id,
                        name,
                        description,
                        safe_metadata,
                        embedding_model,
                        top_k,
                        similarity_threshold,
                        sync_state,
                        lifecycle_state,
                        user_id,
                        created_at,
                        updated_at
                    ) VALUES (
                        :id,
                        :organization_id,
                        :name,
                        'demo reset 범위 검증용 사용자 생성 KB',
                        '{}'::jsonb,
                        'text-embedding-3-small',
                        5,
                        0.7,
                        'manual',
                        'active',
                        :user_id,
                        NOW(),
                        NOW()
                    )
                    """
                ),
                {
                    "id": knowledge_base_id,
                    "organization_id": demo_seed.ORG_ID,
                    "name": f"user-created-reset-test-{knowledge_base_id}",
                    "user_id": demo_seed.USER_IDS["admin"],
                },
            )
    finally:
        engine.dispose()
    return knowledge_base_id


def _insert_knowledge_ingestion_outbox(
    database: str,
    config: DisposablePostgresConfig,
    *,
    knowledge_base_id: uuid.UUID,
    key_prefix: str,
) -> uuid.UUID:
    outbox_id = uuid.uuid4()
    engine = create_engine(config.database_url(database))
    try:
        with engine.begin() as conn:
            conn.execute(
                text(
                    """
                    INSERT INTO knowledge_ingestion_outbox (
                        id,
                        organization_id,
                        knowledge_base_id,
                        event_type,
                        idempotency_key,
                        status,
                        attempt_count,
                        max_attempts,
                        retryable,
                        target_ref,
                        safe_metadata,
                        created_at,
                        updated_at
                    ) VALUES (
                        :id,
                        :organization_id,
                        :knowledge_base_id,
                        'finalize_version',
                        :idempotency_key,
                        'pending',
                        0,
                        5,
                        true,
                        '{}'::jsonb,
                        '{}'::jsonb,
                        NOW(),
                        NOW()
                    )
                    """
                ),
                {
                    "id": outbox_id,
                    "organization_id": demo_seed.ORG_ID,
                    "knowledge_base_id": knowledge_base_id,
                    "idempotency_key": f"{key_prefix}:{uuid.uuid4()}",
                },
            )
    finally:
        engine.dispose()
    return outbox_id


def _existing_knowledge_ingestion_outbox_ids(
    database: str,
    config: DisposablePostgresConfig,
    *,
    first_id: uuid.UUID,
    second_id: uuid.UUID,
) -> set[uuid.UUID]:
    engine = create_engine(config.database_url(database))
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id FROM knowledge_ingestion_outbox "
                    "WHERE id IN (:first_id, :second_id)"
                ),
                {"first_id": first_id, "second_id": second_id},
            ).all()
            return {row[0] for row in rows}
    finally:
        engine.dispose()


def _snapshot_department_onboarding_rbac(
    database: str,
    config: DisposablePostgresConfig,
) -> dict[str, object]:
    engine = create_engine(config.database_url(database))
    try:
        session_factory = sessionmaker(
            bind=engine,
            autoflush=False,
            expire_on_commit=False,
        )
        resolver = KnowledgeRuntimeCandidateResolver(
            snapshot_port=PostgresKnowledgeRuntimeCandidateSnapshotAdapter(
                session_factory=session_factory
            )
        )
        selected_kb_ids = (
            demo_seed.KB_IDS["internal_onboarding"],
            demo_seed.KB_IDS["internal_developer_onboarding_rules"],
            demo_seed.KB_IDS["internal_planning_onboarding_guide"],
        )
        team_onboarding_kb_ids = tuple(
            demo_seed.KB_IDS[spec.key] for spec in demo_seed.ONBOARDING_PDF_SPECS
        )

        def resolve_for(user_key: str) -> set[uuid.UUID]:
            resolution = resolver.resolve(
                KnowledgeRuntimeCandidateRequest(
                    audience=AuthenticatedAudience(
                        organization_id=demo_seed.ORG_ID,
                        user_id=demo_seed.USER_IDS[user_key],
                    ),
                    direct_kb_ids=selected_kb_ids,
                )
            )
            return {candidate.knowledge_base_id for candidate in resolution.candidates}

        with engine.connect() as conn:
            deployment_type = conn.execute(
                text(
                    "SELECT CAST(type AS TEXT) FROM workflow_deployments "
                    "WHERE id = :deployment_id"
                ),
                {
                    "deployment_id": demo_seed.DEPLOYMENT_IDS[
                        "department_onboarding_chatbot"
                    ]
                },
            ).scalar_one()
            workflow_permission_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM team_workflow_permissions "
                    "WHERE workflow_id = :workflow_id "
                    "AND team_id IN (:development_team_id, :planning_team_id) "
                    "AND auth_state = 'operator'"
                ),
                {
                    "workflow_id": demo_seed.WORKFLOW_IDS[
                        "department_onboarding_chatbot"
                    ],
                    "development_team_id": demo_seed.TEAM_IDS["department_development"],
                    "planning_team_id": demo_seed.TEAM_IDS["department_planning"],
                },
            ).scalar_one()
            runtime_llm_permission_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM team_llm_permissions "
                    "WHERE team_id IN (:development_team_id, :planning_team_id)"
                ),
                {
                    "development_team_id": demo_seed.TEAM_IDS["department_development"],
                    "planning_team_id": demo_seed.TEAM_IDS["department_planning"],
                },
            ).scalar_one()
            planning_document = conn.execute(
                text(
                    "SELECT d.status, COUNT(c.id), "
                    "MIN(vector_dims(c.embedding)) "
                    "FROM documents d "
                    "JOIN document_chunks c ON c.document_id = d.id "
                    "WHERE d.id = :document_id "
                    "GROUP BY d.status"
                ),
                {
                    "document_id": demo_seed.DOCUMENT_IDS[
                        "internal_planning_onboarding_guide"
                    ]
                },
            ).one()
            team_onboarding_workflow_permission_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM team_workflow_permissions "
                    "WHERE workflow_id = :workflow_id "
                    "AND team_id IN (:platform_team_id, :sales_team_id, :people_team_id)"
                ),
                {
                    "workflow_id": demo_seed.WORKFLOW_IDS[
                        "team_onboarding_access_control"
                    ],
                    "platform_team_id": demo_seed.TEAM_IDS["onboarding_platform"],
                    "sales_team_id": demo_seed.TEAM_IDS["onboarding_sales"],
                    "people_team_id": demo_seed.TEAM_IDS["onboarding_people"],
                },
            ).scalar_one()
            bundled_onboarding_document_count = conn.execute(
                text(
                    "SELECT COUNT(*) FROM documents "
                    "WHERE knowledge_base_id = ANY(:knowledge_base_ids)"
                ),
                {"knowledge_base_ids": list(team_onboarding_kb_ids)},
            ).scalar_one()

            def onboarding_permissions_for(team_key: str) -> set[uuid.UUID]:
                rows = conn.execute(
                    text(
                        "SELECT knowledge_base_id FROM team_knowledge_permissions "
                        "WHERE team_id = :team_id "
                        "AND knowledge_base_id = ANY(:knowledge_base_ids)"
                    ),
                    {
                        "team_id": demo_seed.TEAM_IDS[team_key],
                        "knowledge_base_ids": list(team_onboarding_kb_ids),
                    },
                ).all()
                return {row[0] for row in rows}

            platform_onboarding_permissions = onboarding_permissions_for(
                "onboarding_platform"
            )
            sales_onboarding_permissions = onboarding_permissions_for(
                "onboarding_sales"
            )
            people_onboarding_permissions = onboarding_permissions_for(
                "onboarding_people"
            )

        return {
            "developer_candidates": resolve_for("developer"),
            "planning_candidates": resolve_for("planning"),
            "deployment_type": deployment_type,
            "workflow_permission_count": workflow_permission_count,
            "runtime_llm_permission_count": runtime_llm_permission_count,
            "planning_document_status": planning_document[0],
            "planning_chunk_count": planning_document[1],
            "planning_embedding_dimension": planning_document[2],
            "platform_onboarding_permissions": platform_onboarding_permissions,
            "sales_onboarding_permissions": sales_onboarding_permissions,
            "people_onboarding_permissions": people_onboarding_permissions,
            "team_onboarding_workflow_permission_count": (
                team_onboarding_workflow_permission_count
            ),
            "bundled_onboarding_document_count": bundled_onboarding_document_count,
        }
    finally:
        engine.dispose()


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL seed smoke",
)
def test_demo_seed_is_idempotent_in_disposable_postgres_database():
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

    try:
        with admin_engine.connect() as conn:
            conn.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True

        _enable_vector_extension(database, config)
        _run_seed_command(
            ["-m", "alembic", "-c", "apps/shared/alembic.ini", "upgrade", "heads"],
            database=database,
            config=config,
        )
        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo", "--reset"],
            database=database,
            config=config,
        )
        reset_counts = _snapshot_counts(database, config)

        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo"],
            database=database,
            config=config,
        )
        seeded_counts = _snapshot_counts(database, config)
        _insert_demo_user_knowledge_permission(database, config)
        non_demo_kb_id = _insert_non_demo_knowledge_base(database, config)
        demo_outbox_id = _insert_knowledge_ingestion_outbox(
            database,
            config,
            knowledge_base_id=demo_seed.KB_IDS["onboarding_platform"],
            key_prefix="demo-reset-test",
        )
        non_demo_outbox_id = _insert_knowledge_ingestion_outbox(
            database,
            config,
            knowledge_base_id=non_demo_kb_id,
            key_prefix="user-created-reset-test",
        )

        _run_seed_command(
            ["scripts/seed_demo.py", "--profile", "demo", "--reset"],
            database=database,
            config=config,
        )
        second_reset_counts = _snapshot_counts(database, config)
        remaining_outbox_ids = _existing_knowledge_ingestion_outbox_ids(
            database,
            config,
            first_id=demo_outbox_id,
            second_id=non_demo_outbox_id,
        )
        rbac_state = _snapshot_department_onboarding_rbac(database, config)

        assert reset_counts["knowledge_bases"] > 0
        assert reset_counts["documents"] > 0
        assert reset_counts["document_chunks"] > 0
        assert reset_counts == seeded_counts
        assert second_reset_counts == {
            **seeded_counts,
            "knowledge_bases": seeded_counts["knowledge_bases"] + 1,
            "knowledge_ingestion_outbox": 1,
        }
        assert reset_counts["document_chunk_document_orphans"] == 0
        assert reset_counts["document_chunk_kb_orphans"] == 0
        assert reset_counts["document_kb_orphans"] == 0
        assert remaining_outbox_ids == {non_demo_outbox_id}
        assert rbac_state["developer_candidates"] == {
            demo_seed.KB_IDS["internal_onboarding"],
            demo_seed.KB_IDS["internal_developer_onboarding_rules"],
        }
        assert rbac_state["planning_candidates"] == {
            demo_seed.KB_IDS["internal_onboarding"],
            demo_seed.KB_IDS["internal_planning_onboarding_guide"],
        }
        assert (
            rbac_state["deployment_type"]
            == demo_seed.DeploymentType.INTERNAL_CHATBOT.name
        )
        assert rbac_state["workflow_permission_count"] == 2
        assert rbac_state["runtime_llm_permission_count"] == 0
        assert rbac_state["planning_document_status"] == "completed"
        assert rbac_state["planning_chunk_count"] > 0
        assert (
            rbac_state["planning_embedding_dimension"]
            == demo_seed.DEMO_EMBEDDING_DIMENSION
        )
        assert rbac_state["platform_onboarding_permissions"] == {
            demo_seed.KB_IDS["onboarding_company_common"],
            demo_seed.KB_IDS["onboarding_platform"],
        }
        assert rbac_state["sales_onboarding_permissions"] == {
            demo_seed.KB_IDS["onboarding_company_common"],
            demo_seed.KB_IDS["onboarding_sales"],
        }
        assert rbac_state["people_onboarding_permissions"] == {
            demo_seed.KB_IDS[spec.key] for spec in demo_seed.ONBOARDING_PDF_SPECS
        }
        assert rbac_state["team_onboarding_workflow_permission_count"] == 3
        assert rbac_state["bundled_onboarding_document_count"] == 4
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if database_created:
            try:
                with admin_engine.connect() as conn:
                    conn.execute(
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
                    conn.execute(text(f"DROP DATABASE IF EXISTS {quoted_database}"))
            except OperationalError:
                raise pytest.fail.Exception(
                    "disposable PostgreSQL cleanup could not connect; "
                    "connection details omitted",
                    pytrace=False,
                ) from None
        admin_engine.dispose()
