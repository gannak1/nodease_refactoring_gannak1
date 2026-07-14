import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from apps.gateway.services.agent_builder_service import (
    EXPECTED_APP_PRIMARY_WORKFLOW_ID,
    AgentBuilderService,
    calculate_graph_hash,
)
from apps.shared.db.models.agent_builder import (
    AgentBuilderDraft,
    AgentBuilderRequest,
    AgentBuilderSession,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import OrganizationMembership
from apps.shared.db.models.team import (
    Team,
    TeamWorkflowPermission,
    UserWorkflowPermission,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import (
    DeploymentType,
    WorkflowDeployment,
)
from apps.shared.schemas.agent_builder import AgentBuilderApplyRequest
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from apps.workflow_engine.tasks import (
    PermanentDeploymentExecutionError,
    _canonical_workflow_execution_context,
)


ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mba254_primary"


def _run_alembic(database: str, config: DisposablePostgresConfig) -> None:
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/shared/alembic.ini",
            "upgrade",
            "heads",
        ],
        cwd=ROOT_DIR,
        env=config.subprocess_environment(database=database, root_dir=ROOT_DIR),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
    )
    if completed.returncode != 0:
        raise pytest.fail.Exception(
            "disposable PostgreSQL migration failed; output omitted",
            pytrace=False,
        )


@pytest.fixture(scope="module")
def db_session():
    if os.getenv(RUN_ENV) != "1":
        pytest.skip(f"set {RUN_ENV}=1 to run disposable PostgreSQL integration")
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
    engine = None
    db = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True
        extension_engine = create_engine(config.database_url(database))
        try:
            with extension_engine.begin() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        finally:
            extension_engine.dispose()
        _run_alembic(database, config)
        engine = create_engine(config.database_url(database), pool_pre_ping=True)
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        yield db
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
        if db is not None:
            db.close()
        if engine is not None:
            engine.dispose()
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


def _user(prefix: str) -> User:
    suffix = uuid.uuid4().hex
    return User(
        email=f"{prefix}-{suffix}@example.invalid",
        name=f"Agent Builder Primary {prefix}",
        social_provider="local",
    )


def _ready_new_workflow_draft(
    db: Session,
    *,
    actor: User,
    organization: Organization,
    app: App,
    expected_primary_workflow_id: uuid.UUID,
) -> AgentBuilderDraft:
    graph = {
        "nodes": [
            {"id": "start", "type": "startNode", "data": {}},
            {"id": "answer", "type": "answerNode", "data": {}},
        ],
        "edges": [{"id": "start-answer", "source": "start", "target": "answer"}],
    }
    session = AgentBuilderSession(
        organization_id=organization.id,
        user_id=actor.id,
        workflow_id=expected_primary_workflow_id,
        app_id=app.id,
        status="active",
    )
    db.add(session)
    db.flush()
    request = AgentBuilderRequest(
        session_id=session.id,
        organization_id=organization.id,
        user_id=actor.id,
        status="done",
        message_summary="safe test summary",
        structured_request={},
        response_payload={},
    )
    db.add(request)
    db.flush()
    draft = AgentBuilderDraft(
        request_id=request.id,
        session_id=session.id,
        organization_id=organization.id,
        user_id=actor.id,
        draft_mode="new_workflow",
        workflow_id=None,
        app_id=app.id,
        preview_graph=graph,
        node_detail_previews=[],
        validation_result={"valid": True, "issues": []},
        draft_metadata={
            EXPECTED_APP_PRIMARY_WORKFLOW_ID: str(expected_primary_workflow_id),
            "generated_node_ids": ["start", "answer"],
        },
        base_graph_hash=calculate_graph_hash(graph),
        status="ready",
    )
    db.add(draft)
    db.flush()
    return draft


def _app_context(db: Session):
    actor = _user("actor")
    collaborator = _user("collaborator")
    db.add_all([actor, collaborator])
    db.flush()
    organization = Organization(
        name=f"Agent Builder Primary {uuid.uuid4().hex}",
        created_by=actor.id,
        managed_by=actor.id,
    )
    db.add(organization)
    db.flush()
    db.add_all(
        [
            OrganizationMembership(
                organization_id=organization.id,
                user_id=actor.id,
                membership_state="active",
                organization_auth_state="manager",
                invited_by=actor.id,
            ),
            OrganizationMembership(
                organization_id=organization.id,
                user_id=collaborator.id,
                membership_state="active",
                organization_auth_state="member",
                invited_by=actor.id,
            ),
        ]
    )
    app = App(
        organization_id=organization.id,
        name="Agent Builder Primary Test",
        url_slug=f"agent-builder-primary-{uuid.uuid4().hex}",
        auth_secret="test-placeholder",
        created_by=actor.id,
    )
    db.add(app)
    db.flush()
    workflow = Workflow(
        organization_id=organization.id,
        app_id=app.id,
        created_by=actor.id,
        graph={"nodes": [], "edges": []},
    )
    db.add(workflow)
    db.flush()
    app.workflow_id = workflow.id
    db.add_all(
        [
            UserWorkflowPermission(
                grantee_organization_id=organization.id,
                workflow_id=workflow.id,
                user_id=actor.id,
                auth_state="builder",
                assigned_by=actor.id,
                options={"source": "actor"},
                flags=1,
            ),
            UserWorkflowPermission(
                grantee_organization_id=organization.id,
                workflow_id=workflow.id,
                user_id=collaborator.id,
                auth_state="viewer",
                assigned_by=actor.id,
                options={"source": "collaborator"},
                flags=2,
            ),
        ]
    )
    team = Team(
        organization_id=organization.id,
        name=f"Primary Team {uuid.uuid4().hex}",
        created_by=actor.id,
    )
    db.add(team)
    db.flush()
    db.add(
        TeamWorkflowPermission(
            grantee_organization_id=organization.id,
            workflow_id=workflow.id,
            team_id=team.id,
            auth_state="operator",
            assigned_by=actor.id,
            options={"source": "team"},
            flags=4,
        )
    )
    db.flush()
    return actor, collaborator, organization, app, workflow, team


def test_new_workflow_apply_atomically_promotes_primary_and_inherits_permissions(
    db_session,
):
    actor, collaborator, organization, app, old_workflow, team = _app_context(
        db_session
    )
    draft = _ready_new_workflow_draft(
        db_session,
        actor=actor,
        organization=organization,
        app=app,
        expected_primary_workflow_id=old_workflow.id,
    )
    service = AgentBuilderService(
        db_session,
        user=actor,
        organization_id=organization.id,
    )

    response = service.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(draft.preview_graph),
        ),
    )

    assert response.outcome == "saved"
    db_session.refresh(app)
    assert app.workflow_id == response.saved_workflow_id
    inherited_users = (
        db_session.query(UserWorkflowPermission)
        .filter(UserWorkflowPermission.workflow_id == response.saved_workflow_id)
        .all()
    )
    assert {row.user_id: row.auth_state for row in inherited_users} == {
        actor.id: "manager",
        collaborator.id: "viewer",
    }
    inherited_team = (
        db_session.query(TeamWorkflowPermission)
        .filter(TeamWorkflowPermission.workflow_id == response.saved_workflow_id)
        .one()
    )
    assert inherited_team.team_id == team.id
    assert inherited_team.auth_state == "operator"
    assert inherited_team.options == {"source": "team"}
    assert draft.request.session.workflow_id == response.saved_workflow_id

    execution_context = _canonical_workflow_execution_context(
        db_session,
        {
            "workflow_id": str(response.saved_workflow_id),
            "execution_id": str(uuid.uuid4()),
        },
    )
    assert execution_context["workflow_id"] == str(response.saved_workflow_id)
    assert execution_context["app_id"] == str(app.id)

    with pytest.raises(
        PermanentDeploymentExecutionError,
        match="workflow execution identity is invalid",
    ):
        _canonical_workflow_execution_context(
            db_session,
            {
                "workflow_id": str(old_workflow.id),
                "execution_id": str(uuid.uuid4()),
            },
        )


def test_new_workflow_apply_blocks_before_insert_when_active_deployment_exists(
    db_session,
):
    actor, _collaborator, organization, app, old_workflow, _team = _app_context(
        db_session
    )
    deployment = WorkflowDeployment(
        app_id=app.id,
        version=1,
        type=DeploymentType.CHATBOT,
        graph_snapshot=old_workflow.graph,
        created_by=actor.id,
        is_active=True,
    )
    db_session.add(deployment)
    db_session.flush()
    app.active_deployment_id = deployment.id
    draft = _ready_new_workflow_draft(
        db_session,
        actor=actor,
        organization=organization,
        app=app,
        expected_primary_workflow_id=old_workflow.id,
    )
    workflow_count_before = db_session.query(Workflow).count()
    service = AgentBuilderService(
        db_session,
        user=actor,
        organization_id=organization.id,
    )

    response = service.apply_draft(
        draft.id,
        AgentBuilderApplyRequest(
            action="apply_and_save",
            client_preview_graph_hash=calculate_graph_hash(draft.preview_graph),
        ),
    )

    assert response.outcome == "blocked"
    assert response.block_reason == "APP_ACTIVE_DEPLOYMENT_CONFLICT"
    assert db_session.query(Workflow).count() == workflow_count_before
    db_session.refresh(app)
    assert app.workflow_id == old_workflow.id
    assert app.active_deployment_id == deployment.id
