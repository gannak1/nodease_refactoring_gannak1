"""Actual PostgreSQL integration coverage for the App deletion lifecycle."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from apps.gateway.services.app_service import AppService
from apps.shared.db.models import (
    AgentBuilderDraft,
    AgentBuilderRequest,
    AgentBuilderSession,
    App,
    AuditLog,
    CostOptimizerExperiment,
    DeploymentParameterOptimizationPlan,
    LLMCredential,
    LLMModel,
    LLMNodeModelRoutingPolicy,
    LLMNodeModelRoutingPolicyUpdate,
    LLMNodeVersion,
    LLMProvider,
    LLMUsageLog,
    MailCredential,
    MailDraftEffect,
    MailMessageProcessing,
    Organization,
    Schedule,
    Team,
    TeamWorkflowPermission,
    TracePayload,
    User,
    UserWorkflowPermission,
    Workflow,
    WorkflowBudget,
    WorkflowDeployment,
    WorkflowNodeEffectAttempt,
    WorkflowNodeRun,
    WorkflowRun,
)
from apps.shared.db.models.audit_log import ActorType, AuditCategory, AuditStatus
from apps.shared.db.models.cost_optimizer import (
    CostOptimizerRecommendationVerification,
)
from apps.shared.db.models.workflow_deployment import DeploymentType
from apps.shared.db.models.workflow_run import (
    NodeRunStatus,
    RunStatus,
    RunTriggerMode,
)
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)
from apps.shared.services.tracing.access import TraceAccessService


ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_app_delete_service"
APP_NAME_SENTINEL = "app-name-must-not-enter-delete-audit"
GRAPH_SENTINEL = "graph-secret-must-not-enter-delete-audit"
DEPLOYMENT_CONFIG_SENTINEL = "deployment-config-must-not-enter-delete-audit"
TRACE_PAYLOAD_SENTINEL = "trace-payload-must-not-enter-delete-audit"
CREDENTIAL_SENTINEL = "credential-secret-must-not-enter-delete-audit"


def _run_alembic(database: str, config: DisposablePostgresConfig) -> None:
    result = subprocess.run(
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
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=180,
        check=False,
    )
    if result.returncode != 0:
        pytest.fail(
            f"alembic failed with exit code {result.returncode}; "
            "stdout/stderr omitted to avoid leaking local configuration"
        )


def _seed_app_lifecycle(db) -> dict[str, uuid.UUID]:
    ids = {
        name: uuid.uuid4()
        for name in (
            "user",
            "foreign_user",
            "organization",
            "team",
            "app",
            "workflow",
            "team_permission",
            "user_permission",
            "budget",
            "deployment",
            "schedule",
            "optimization_plan",
            "node_version",
            "run",
            "node_run",
            "trace",
            "provider",
            "model",
            "credential",
            "usage",
            "cost_experiment",
            "cost_verification",
            "routing_policy",
            "routing_update",
            "audit",
            "agent_session",
            "agent_request",
            "agent_draft",
            "mail_credential",
            "mail_processing",
            "mail_draft_effect",
            "external_effect",
        )
    }

    db.add_all(
        [
            User(
                id=ids["user"],
                email=f"app-delete-{ids['user']}@example.invalid",
                name="App deletion owner",
                social_provider="local",
            ),
            User(
                id=ids["foreign_user"],
                email=f"app-delete-foreign-{ids['foreign_user']}@example.invalid",
                name="Foreign user",
                social_provider="local",
            ),
        ]
    )
    db.flush()
    db.add(
        Organization(
            id=ids["organization"],
            name="App deletion organization",
            created_by=ids["user"],
        )
    )
    db.flush()
    db.add(
        Team(
            id=ids["team"],
            organization_id=ids["organization"],
            name="App deletion team",
            created_by=ids["user"],
        )
    )
    db.add(
        App(
            id=ids["app"],
            organization_id=ids["organization"],
            name=APP_NAME_SENTINEL,
            url_slug=f"app-delete-{ids['app']}",
            auth_secret=CREDENTIAL_SENTINEL,
            created_by=ids["user"],
        )
    )
    db.flush()
    db.add(
        Workflow(
            id=ids["workflow"],
            organization_id=ids["organization"],
            app_id=ids["app"],
            graph={"private": GRAPH_SENTINEL},
            features={},
            env_variables={},
            runtime_variables={},
            created_by=ids["user"],
        )
    )
    db.flush()
    app = db.get(App, ids["app"])
    assert app is not None
    app.workflow_id = ids["workflow"]

    db.add_all(
        [
            TeamWorkflowPermission(
                id=ids["team_permission"],
                grantee_organization_id=ids["organization"],
                team_id=ids["team"],
                workflow_id=ids["workflow"],
                auth_state="viewer",
                assigned_by=ids["user"],
            ),
            UserWorkflowPermission(
                id=ids["user_permission"],
                grantee_organization_id=ids["organization"],
                user_id=ids["user"],
                workflow_id=ids["workflow"],
                auth_state="manager",
                assigned_by=ids["user"],
            ),
            WorkflowBudget(
                id=ids["budget"],
                organization_id=ids["organization"],
                workflow_id=ids["workflow"],
                monthly_budget_usd=Decimal("10.00"),
                created_by=ids["user"],
            ),
        ]
    )
    db.add(
        WorkflowDeployment(
            id=ids["deployment"],
            app_id=ids["app"],
            version=1,
            type=DeploymentType.SCHEDULE,
            graph_snapshot={"private": DEPLOYMENT_CONFIG_SENTINEL},
            created_by=ids["user"],
        )
    )
    db.flush()
    app.active_deployment_id = ids["deployment"]
    db.add_all(
        [
            Schedule(
                id=ids["schedule"],
                deployment_id=ids["deployment"],
                node_id="schedule-node",
                cron_expression="0 9 * * *",
                timezone="Asia/Seoul",
            ),
            DeploymentParameterOptimizationPlan(
                id=ids["optimization_plan"],
                deployment_id=ids["deployment"],
                app_id=ids["app"],
                workflow_id=ids["workflow"],
                node_ids=["llm-node"],
            ),
            LLMNodeVersion(
                id=ids["node_version"],
                app_id=ids["app"],
                node_id="llm-node",
                version_number=1,
                source_workflow_id=ids["workflow"],
                provider="synthetic-provider",
                model_id="synthetic-model",
                created_by=ids["user"],
            ),
        ]
    )

    db.add(
        WorkflowRun(
            id=ids["run"],
            organization_id=ids["organization"],
            workflow_id=ids["workflow"],
            user_id=ids["user"],
            app_id=ids["app"],
            deployment_id=ids["deployment"],
            status=RunStatus.SUCCESS,
            trigger_mode=RunTriggerMode.MANUAL,
            inputs={},
        )
    )
    db.flush()
    db.add(
        WorkflowNodeRun(
            id=ids["node_run"],
            workflow_run_id=ids["run"],
            node_id="llm-node",
            node_type="llmNode",
            status=NodeRunStatus.SUCCESS,
            inputs={},
            process_data={},
        )
    )
    db.flush()
    db.add(
        TracePayload(
            id=ids["trace"],
            workflow_run_id=ids["run"],
            workflow_node_run_id=ids["node_run"],
            scope="node",
            payload_kind="output",
            redacted_payload={"result": TRACE_PAYLOAD_SENTINEL},
        )
    )

    db.add(
        LLMProvider(
            id=ids["provider"],
            name=f"provider-{ids['provider']}",
            type="custom",
            auth_type="api_key",
            doc_url="https://example.invalid",
        )
    )
    db.flush()
    db.add_all(
        [
            LLMModel(
                id=ids["model"],
                provider_id=ids["provider"],
                model_id_for_api_call="synthetic-model",
                name="Synthetic model",
                type="chat",
                context_window=1024,
                is_active=True,
            ),
            LLMCredential(
                id=ids["credential"],
                provider_id=ids["provider"],
                user_id=ids["user"],
                organization_id=ids["organization"],
                credential_name="Synthetic credential",
                encrypted_config=CREDENTIAL_SENTINEL,
            ),
        ]
    )
    db.flush()
    db.add(
        LLMUsageLog(
            id=ids["usage"],
            user_id=ids["user"],
            organization_id=ids["organization"],
            credential_id=ids["credential"],
            model_id=ids["model"],
            workflow_id=ids["workflow"],
            workflow_run_id=ids["run"],
            node_id="llm-node",
            prompt_tokens=3,
            completion_tokens=2,
            total_cost=Decimal("0.001"),
            latency_ms=10,
        )
    )
    db.add(
        CostOptimizerExperiment(
            id=ids["cost_experiment"],
            organization_id=ids["organization"],
            workflow_id=ids["workflow"],
            app_id=ids["app"],
            node_id="llm-node",
            baseline_node_run_id=ids["node_run"],
            baseline_workflow_run_id=ids["run"],
            baseline_node_options={},
            baseline_usage_summary={},
            baseline_trace_summary={},
            baseline_downstream_snapshot={},
            usage_summary={},
            created_by=ids["user"],
        )
    )
    db.add(
        CostOptimizerRecommendationVerification(
            id=ids["cost_verification"],
            organization_id=ids["organization"],
            workflow_id=ids["workflow"],
            node_id="llm-node",
            created_by=ids["user"],
            idempotency_key=f"verification-{ids['cost_verification']}",
            request_fingerprint="a" * 64,
            status="completed",
            experiment_id=ids["cost_experiment"],
            response_summary={"result": "synthetic"},
        )
    )
    db.add(
        LLMNodeModelRoutingPolicy(
            id=ids["routing_policy"],
            organization_id=ids["organization"],
            workflow_id=ids["workflow"],
            deployment_id=ids["deployment"],
            node_id="llm-node",
            status="active",
            active_policy={"model": "synthetic-model"},
        )
    )
    db.flush()
    db.add(
        LLMNodeModelRoutingPolicyUpdate(
            id=ids["routing_update"],
            policy_id=ids["routing_policy"],
            trigger="manual",
            status="completed",
            eligible_run_count=1,
            excluded_run_count=0,
            excluded_reason_summary={},
            input_summary={},
            output_summary={"selected": "synthetic-model"},
        )
    )
    db.add(
        AuditLog(
            id=ids["audit"],
            actor_id=ids["user"],
            actor_type=ActorType.USER,
            category=AuditCategory.ACTION,
            action="workflow.run",
            target_type="workflow",
            target_id=str(ids["workflow"]),
            status=AuditStatus.SUCCESS,
            audit_metadata={"organization_id": str(ids["organization"])},
        )
    )
    db.add(
        AgentBuilderSession(
            id=ids["agent_session"],
            organization_id=ids["organization"],
            user_id=ids["user"],
            workflow_id=ids["workflow"],
            app_id=ids["app"],
            status="completed",
        )
    )
    db.flush()
    db.add(
        AgentBuilderRequest(
            id=ids["agent_request"],
            session_id=ids["agent_session"],
            organization_id=ids["organization"],
            user_id=ids["user"],
            status="completed",
            structured_request={},
            response_payload={},
        )
    )
    db.flush()
    db.add(
        AgentBuilderDraft(
            id=ids["agent_draft"],
            request_id=ids["agent_request"],
            session_id=ids["agent_session"],
            organization_id=ids["organization"],
            user_id=ids["user"],
            draft_mode="create",
            workflow_id=ids["workflow"],
            app_id=ids["app"],
            preview_graph={},
            validation_result={},
        )
    )
    db.add(
        MailCredential(
            id=ids["mail_credential"],
            organization_id=ids["organization"],
            credential_name="Synthetic mail credential",
            provider="imap",
            email_address="synthetic@example.invalid",
            auth_type="password",
            imap_host="imap.example.invalid",
            imap_port=993,
            use_ssl=True,
            encrypted_secret="synthetic-ciphertext",
            encryption_key_version="v1",
            encryption_algorithm="synthetic",
            created_by=ids["user"],
        )
    )
    db.flush()
    now = datetime.now(timezone.utc)
    db.add(
        MailMessageProcessing(
            id=ids["mail_processing"],
            organization_id=ids["organization"],
            workflow_id=ids["workflow"],
            deployment_id=ids["deployment"],
            source_node_id="mail-node",
            credential_id=ids["mail_credential"],
            provider="imap",
            message_identity_hash="b" * 64,
            encrypted_source_reference="synthetic-source-reference",
            source_key_version="v1",
            source_algorithm="synthetic",
            status="succeeded",
            completed_at=now,
        )
    )
    db.flush()
    db.add(
        MailDraftEffect(
            id=ids["mail_draft_effect"],
            processing_id=ids["mail_processing"],
            node_id="mail-node",
            operation_key_hash="c" * 64,
            input_digest="d" * 64,
            status="succeeded",
            encrypted_draft_reference="synthetic-draft-reference",
            draft_key_version="v1",
            draft_algorithm="synthetic",
            completed_at=now,
        )
    )
    db.add(
        WorkflowNodeEffectAttempt(
            id=ids["external_effect"],
            organization_id=ids["organization"],
            app_id=ids["app"],
            workflow_id=ids["workflow"],
            execution_id=uuid.uuid4(),
            node_invocation_id=uuid.uuid4(),
            workflow_run_id=ids["run"],
            node_run_id=ids["node_run"],
            node_id="effect-node",
            operation="send",
            effect_sequence=0,
            provider="synthetic",
            provider_contract_version="v1",
            provider_replay_capability="unsupported",
            result_reuse_capability="unavailable",
            effect_input_digest="e" * 64,
            status="terminal",
            outcome="failed_before_effect",
            replay_decision="stop",
            claim_generation=1,
            terminal_at=now,
        )
    )
    db.commit()
    return ids


def _assert_all_seeded_rows_exist(db, ids: dict[str, uuid.UUID]) -> None:
    model_by_key = {
        "app": App,
        "workflow": Workflow,
        "team_permission": TeamWorkflowPermission,
        "user_permission": UserWorkflowPermission,
        "budget": WorkflowBudget,
        "deployment": WorkflowDeployment,
        "schedule": Schedule,
        "optimization_plan": DeploymentParameterOptimizationPlan,
        "node_version": LLMNodeVersion,
        "run": WorkflowRun,
        "node_run": WorkflowNodeRun,
        "trace": TracePayload,
        "usage": LLMUsageLog,
        "cost_experiment": CostOptimizerExperiment,
        "cost_verification": CostOptimizerRecommendationVerification,
        "routing_policy": LLMNodeModelRoutingPolicy,
        "routing_update": LLMNodeModelRoutingPolicyUpdate,
        "audit": AuditLog,
        "agent_session": AgentBuilderSession,
        "agent_request": AgentBuilderRequest,
        "agent_draft": AgentBuilderDraft,
        "mail_processing": MailMessageProcessing,
        "mail_draft_effect": MailDraftEffect,
        "external_effect": WorkflowNodeEffectAttempt,
    }
    for key, model in model_by_key.items():
        assert db.get(model, ids[key]) is not None, key


@pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable PostgreSQL App deletion integration",
)
def test_delete_app_is_atomic_and_applies_deletion_retention_policy() -> None:
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

        engine = create_engine(config.database_url(database))
        with engine.begin() as connection:
            connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        engine.dispose()
        engine = None

        _run_alembic(database, config)
        engine = create_engine(config.database_url(database))
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        ids = _seed_app_lifecycle(db)

        def fail_before_commit(_session) -> None:
            raise RuntimeError("injected commit failure")

        event.listen(db, "before_commit", fail_before_commit, once=True)
        with pytest.raises(RuntimeError, match="^injected commit failure$"):
            AppService.delete_app(db, str(ids["app"]), str(ids["user"]))
        _assert_all_seeded_rows_exist(db, ids)
        assert (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "app.delete",
                AuditLog.status == AuditStatus.SUCCESS,
                AuditLog.target_id == str(ids["app"]),
            )
            .count()
            == 0
        )

        assert AppService.delete_app(
            db, str(ids["app"]), str(ids["user"])
        ) is True

        delete_audits = (
            db.query(AuditLog)
            .filter(
                AuditLog.action == "app.delete",
                AuditLog.status == AuditStatus.SUCCESS,
                AuditLog.target_id == str(ids["app"]),
            )
            .all()
        )
        assert len(delete_audits) == 1
        delete_audit = delete_audits[0]
        assert delete_audit.actor_id == ids["user"]
        assert delete_audit.actor_type == ActorType.USER
        assert delete_audit.category == AuditCategory.ACTION
        assert delete_audit.target_type == "app"
        assert delete_audit.before is None
        assert delete_audit.after is None
        assert delete_audit.audit_metadata == {
            "organization_id": str(ids["organization"]),
            "actor_id": str(ids["user"]),
            "app_id": str(ids["app"]),
            "deleted_workflow_count": 1,
        }
        audit_projection = json.dumps(
            {
                "before": delete_audit.before,
                "after": delete_audit.after,
                "metadata": delete_audit.audit_metadata,
            },
            default=str,
            sort_keys=True,
        )
        for sentinel in (
            APP_NAME_SENTINEL,
            GRAPH_SENTINEL,
            DEPLOYMENT_CONFIG_SENTINEL,
            TRACE_PAYLOAD_SENTINEL,
            CREDENTIAL_SENTINEL,
        ):
            assert sentinel not in audit_projection

        for key, model in {
            "app": App,
            "workflow": Workflow,
            "team_permission": TeamWorkflowPermission,
            "user_permission": UserWorkflowPermission,
            "budget": WorkflowBudget,
            "deployment": WorkflowDeployment,
            "schedule": Schedule,
            "optimization_plan": DeploymentParameterOptimizationPlan,
            "node_version": LLMNodeVersion,
        }.items():
            assert db.get(model, ids[key]) is None, key

        retained_run = db.get(WorkflowRun, ids["run"])
        retained_usage = db.get(LLMUsageLog, ids["usage"])
        retained_experiment = db.get(CostOptimizerExperiment, ids["cost_experiment"])
        assert retained_run is not None
        assert retained_run.organization_id == ids["organization"]
        assert retained_run.workflow_id is None
        assert retained_run.app_id is None
        assert retained_run.deployment_id is None
        assert db.get(WorkflowNodeRun, ids["node_run"]) is not None
        assert db.get(TracePayload, ids["trace"]) is not None
        assert retained_usage is not None
        assert retained_usage.organization_id == ids["organization"]
        assert retained_usage.workflow_id is None
        assert retained_experiment is not None
        assert retained_experiment.organization_id == ids["organization"]
        assert retained_experiment.workflow_id is None
        assert retained_experiment.app_id is None
        retained_verification = db.get(
            CostOptimizerRecommendationVerification,
            ids["cost_verification"],
        )
        assert retained_verification is not None
        assert retained_verification.organization_id == ids["organization"]
        assert retained_verification.workflow_id is None

        # Routing evidence is historical data. Removing its deployment must leave a
        # disabled/tombstoned policy instead of cascading through the evidence chain.
        retained_policy = db.get(
            LLMNodeModelRoutingPolicy, ids["routing_policy"]
        )
        assert retained_policy is not None
        assert retained_policy.workflow_id is None
        assert retained_policy.enabled is False
        assert db.get(
            LLMNodeModelRoutingPolicyUpdate, ids["routing_update"]
        ) is not None

        assert db.get(AuditLog, ids["audit"]) is not None
        retained_agent_session = db.get(AgentBuilderSession, ids["agent_session"])
        retained_agent_draft = db.get(AgentBuilderDraft, ids["agent_draft"])
        assert retained_agent_session is not None
        assert retained_agent_session.workflow_id is None
        assert retained_agent_session.app_id is None
        assert db.get(AgentBuilderRequest, ids["agent_request"]) is not None
        assert retained_agent_draft is not None
        assert retained_agent_draft.workflow_id is None
        assert retained_agent_draft.app_id is None

        retained_mail = db.get(MailMessageProcessing, ids["mail_processing"])
        assert retained_mail is not None
        assert retained_mail.organization_id == ids["organization"]
        assert retained_mail.workflow_id is None
        assert retained_mail.deployment_id is None
        assert db.get(MailDraftEffect, ids["mail_draft_effect"]) is not None
        assert db.get(WorkflowNodeEffectAttempt, ids["external_effect"]) is not None

        owner = db.get(User, ids["user"])
        foreign_user = db.get(User, ids["foreign_user"])
        assert owner is not None
        assert foreign_user is not None
        assert TraceAccessService.check_trace_access(
            db, retained_run, owner
        ).allowed is True
        assert TraceAccessService.check_trace_access(
            db, retained_run, foreign_user
        ).allowed is False
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
