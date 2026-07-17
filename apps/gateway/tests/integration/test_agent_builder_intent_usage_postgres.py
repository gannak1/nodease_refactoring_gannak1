from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import sessionmaker

from apps.gateway.api.v1.endpoints import agent_builder as agent_builder_endpoint
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.composition import agent_builder as agent_builder_composition
from apps.gateway.main import app as gateway_app
from apps.gateway.api.v1.endpoints.llm import get_top_expensive_models
from apps.gateway.application.agent_builder.intent_usage import (
    AgentBuilderIntentUsageConflictError,
    AgentBuilderIntentUsageContext,
    AgentBuilderIntentUsageRecordingError,
    AgentBuilderIntentUsageSample,
)
from apps.gateway.services.admin_usage_service import AdminUsageService
from apps.gateway.services.agent_builder.intent_usage_service import (
    AgentBuilderIntentUsageService,
)
from apps.gateway.services.app_service import AppService
from apps.gateway.services.llm_service import LLMService
from apps.gateway.services.organization_member_service import (
    OrganizationMemberService,
)
from apps.gateway.services.workflow_budget_service import WorkflowBudgetService
from apps.shared.db.models.agent_builder import (
    AgentBuilderRequest,
    AgentBuilderSession,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.llm import (
    LLMCredential,
    LLMModel,
    LLMProvider,
    LLMRelCredentialModel,
    LLMUsageLog,
)
from apps.shared.db.models.organization import Organization
from apps.shared.db.models.organization_membership import (
    ORGANIZATION_AUTH_MANAGER,
    ORGANIZATION_AUTH_MEMBER,
    ORGANIZATION_MEMBERSHIP_ACTIVE,
    ORGANIZATION_MEMBERSHIP_REMOVED,
    ORGANIZATION_MEMBERSHIP_SUSPENDED,
    OrganizationMembership,
)
from apps.shared.db.models.user import User
from apps.shared.db.models.workflow import Workflow
from apps.shared.tests.helpers.disposable_postgres import (
    DisposablePostgresConfig,
    DisposablePostgresConfigurationError,
    quote_disposable_database_name,
)

ROOT_DIR = Path(__file__).resolve().parents[4]
RUN_ENV = "NODEASE_RUN_DISPOSABLE_DB_TEST"
DB_PREFIX = "mbased_agent_builder_intent_usage"
pytestmark = pytest.mark.skipif(
    os.getenv(RUN_ENV) != "1",
    reason=f"set {RUN_ENV}=1 to run disposable Agent Builder usage tests",
)


def _run_alembic_result(
    database: str,
    config: DisposablePostgresConfig,
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "alembic",
            "-c",
            "apps/shared/alembic.ini",
            *arguments,
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


def _run_alembic(
    database: str,
    config: DisposablePostgresConfig,
    *arguments: str,
) -> None:
    result = _run_alembic_result(database, config, *arguments)
    if result.returncode != 0:
        pytest.fail(
            "alembic failed for disposable Agent Builder usage database; "
            "stdout/stderr omitted to avoid leaking local configuration"
        )


@contextmanager
def _disposable_database(config: DisposablePostgresConfig):
    database = f"{DB_PREFIX}_{uuid.uuid4().hex[:12]}"
    quoted_database = quote_disposable_database_name(database, prefix=DB_PREFIX)
    admin_engine = create_engine(
        config.database_url(config.maintenance_database),
        isolation_level="AUTOCOMMIT",
    )
    engine = None
    database_created = False
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f"CREATE DATABASE {quoted_database}"))
        database_created = True
        extension_engine = create_engine(
            config.database_url(database),
            isolation_level="AUTOCOMMIT",
        )
        try:
            with extension_engine.connect() as connection:
                connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        finally:
            extension_engine.dispose()
        _run_alembic(database, config, "upgrade", "heads")
        engine = create_engine(config.database_url(database))
        yield engine, database
    except OperationalError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL is unavailable or rejected the connection; "
            "connection details omitted",
            pytrace=False,
        ) from None
    finally:
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


@pytest.fixture(scope="module")
def usage_database():
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL settings are not safely configured",
            pytrace=False,
        ) from None
    with _disposable_database(config) as database:
        yield database


def _seed_contract(session_factory):
    with session_factory.begin() as db:
        actor = User(
            email=f"intent-usage-{uuid.uuid4().hex}@example.invalid",
            name="Agent Builder Intent Usage",
            social_provider="local",
        )
        db.add(actor)
        db.flush()
        organization = Organization(
            name=f"Agent Builder Intent Usage {uuid.uuid4().hex}",
            created_by=actor.id,
            managed_by=actor.id,
        )
        db.add(organization)
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=organization.id,
                user_id=actor.id,
                membership_state=ORGANIZATION_MEMBERSHIP_ACTIVE,
                organization_auth_state=ORGANIZATION_AUTH_MANAGER,
                invited_by=actor.id,
                invited_at=datetime.now(timezone.utc),
                accepted_at=datetime.now(timezone.utc),
            )
        )
        app = App(
            organization_id=organization.id,
            name="Agent Builder Intent Usage",
            url_slug=f"agent-builder-intent-usage-{uuid.uuid4().hex}",
            auth_secret="",
            created_by=actor.id,
        )
        db.add(app)
        db.flush()
        workflow = Workflow(
            organization_id=organization.id,
            app_id=app.id,
            graph={"nodes": [], "edges": []},
            created_by=actor.id,
            updated_by=actor.id,
        )
        db.add(workflow)
        db.flush()
        app.workflow_id = workflow.id
        session = AgentBuilderSession(
            organization_id=organization.id,
            user_id=actor.id,
            workflow_id=workflow.id,
            app_id=app.id,
            status="active",
            protocol_version="direct_edit_v1",
        )
        db.add(session)
        db.flush()
        request = AgentBuilderRequest(
            session_id=session.id,
            organization_id=organization.id,
            user_id=actor.id,
            status="processing",
            message_summary="safe test summary",
            structured_request={},
            response_payload={},
        )
        provider = LLMProvider(
            name=f"intent-usage-provider-{uuid.uuid4().hex}",
            description="Agent Builder usage test provider",
            type="system",
            base_url="https://example.invalid/v1",
            auth_type="api_key",
            doc_url="https://example.invalid/docs",
        )
        db.add_all([request, provider])
        db.flush()
        model = LLMModel(
            provider_id=provider.id,
            model_id_for_api_call="intent-usage-model",
            name="Intent Usage Model",
            type="chat",
            context_window=8192,
            input_price_1k=Decimal("0.002000"),
            output_price_1k=Decimal("0.004000"),
            is_active=True,
        )
        credential = LLMCredential(
            provider_id=provider.id,
            user_id=actor.id,
            organization_id=organization.id,
            credential_name="Intent Usage Credential",
            encrypted_config=json.dumps({}),
            config_preview=None,
            is_valid=True,
        )
        db.add_all([model, credential])
        db.flush()
        db.add(
            LLMRelCredentialModel(
                credential_id=credential.id,
                model_id=model.id,
                is_verified=True,
                priority=0,
            )
        )
        return SimpleNamespace(
            user_id=actor.id,
            organization_id=organization.id,
            app_id=app.id,
            workflow_id=workflow.id,
            session_id=session.id,
            request_id=request.id,
            model_id=model.id,
            credential_id=credential.id,
        )


def _context(seed) -> AgentBuilderIntentUsageContext:
    return AgentBuilderIntentUsageContext(
        user_id=seed.user_id,
        organization_id=seed.organization_id,
        workflow_id=seed.workflow_id,
        session_id=seed.session_id,
        request_id=seed.request_id,
    )


def _sample(seed, *, attempt: int = 1) -> AgentBuilderIntentUsageSample:
    return AgentBuilderIntentUsageSample(
        credential_id=seed.credential_id,
        model_id=seed.model_id,
        model_api_id="intent-usage-model",
        attempt=attempt,
        prompt_tokens=1000,
        completion_tokens=500,
        latency_ms=125,
    )


def _reserve(
    service: AgentBuilderIntentUsageService,
    seed,
    *,
    context: AgentBuilderIntentUsageContext | None = None,
    attempt: int = 1,
):
    return service.reserve(
        context or _context(seed),
        credential_id=seed.credential_id,
        model_id=seed.model_id,
        model_api_id="intent-usage-model",
        attempt=attempt,
    )


def _record(
    service: AgentBuilderIntentUsageService,
    seed,
    *,
    attempt: int = 1,
):
    reservation = _reserve(service, seed, attempt=attempt)
    return service.record(reservation, _sample(seed, attempt=attempt))


def _workflow_usage_log(
    seed,
    *,
    user_id,
    organization_id,
    total_cost: Decimal,
    workflow_id=None,
) -> LLMUsageLog:
    return LLMUsageLog(
        id=uuid.uuid4(),
        user_id=user_id,
        organization_id=organization_id,
        credential_id=seed.credential_id,
        model_id=seed.model_id,
        workflow_id=workflow_id or seed.workflow_id,
        prompt_tokens=1,
        completion_tokens=1,
        total_cost=total_cost,
        latency_ms=1,
        status="success",
        created_at=datetime.now(timezone.utc),
    )


def test_usage_record_is_idempotent_and_included_in_existing_projections(
    usage_database,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)

    reservation = _reserve(service, seed)
    first_id = service.record(reservation, _sample(seed))
    second_id = service.record(reservation, _sample(seed))

    assert first_id == second_id
    now = datetime.now(timezone.utc)
    with session_factory() as db:
        rows = db.scalars(
            select(LLMUsageLog).where(LLMUsageLog.runtime_request_id == seed.request_id)
        ).all()
        assert len(rows) == 1
        assert rows[0].prompt_tokens == 1000
        assert rows[0].completion_tokens == 500
        assert Decimal(str(rows[0].total_cost)) == Decimal("0.004000")

        top_models = get_top_expensive_models(
            db=db,
            current_user=SimpleNamespace(id=seed.user_id),
        )
        assert len(top_models) == 1
        assert top_models[0]["model_name"] == "Intent Usage Model"
        assert top_models[0]["provider_name"].startswith("intent-usage-provider-")
        assert top_models[0]["total_cost"] == pytest.approx(0.004)
        assert top_models[0]["total_tokens"] == 1500

    with session_factory.begin() as db:
        db.execute(
            update(LLMModel)
            .where(LLMModel.id == seed.model_id)
            .values(is_active=False)
        )

    with session_factory() as db:
        top_models = get_top_expensive_models(
            db=db,
            current_user=SimpleNamespace(id=seed.user_id),
        )
        assert len(top_models) == 1
        assert top_models[0]["model_name"] == "Intent Usage Model"
        assert top_models[0]["total_cost"] == pytest.approx(0.004)
        assert top_models[0]["total_tokens"] == 1500

    with session_factory() as db:
        admin_usage = AdminUsageService.aggregate_workflow_usage(
            db,
            seed.organization_id,
            AdminUsageService.resolve_month_period_kst(now),
            now=now,
        )
        workflow_usage = next(
            item for item in admin_usage.items if item.workflow_id == seed.workflow_id
        )
        assert workflow_usage.prompt_tokens == 1000
        assert workflow_usage.completion_tokens == 500
        assert workflow_usage.total_cost == pytest.approx(0.004)
        assert workflow_usage.workflow_execution_cost == pytest.approx(0)
        assert workflow_usage.agent_builder_cost == pytest.approx(0.004)

        summary = AdminUsageService.get_organization_summary(
            db,
            seed.organization_id,
            now=now,
        )
        assert summary.total_cost == pytest.approx(0.004)
        assert summary.workflow_execution_cost == pytest.approx(0)
        assert summary.agent_builder_cost == pytest.approx(0.004)
        assert WorkflowBudgetService.get_current_month_cost(
            db,
            seed.workflow_id,
            now,
            organization_id=seed.organization_id,
        ) == Decimal("0.004000")
        metrics = AppService._operation_metrics_by_workflow_id(
            db,
            [seed.workflow_id],
            now=now,
        )
        assert metrics[seed.workflow_id]["current_month_cost"] == pytest.approx(0.004)
        assert metrics[seed.workflow_id][
            "current_month_workflow_execution_cost"
        ] == pytest.approx(0)
        assert metrics[seed.workflow_id][
            "current_month_agent_builder_cost"
        ] == pytest.approx(0.004)
        assert metrics[seed.workflow_id]["projected_month_cost"] >= 0.004


def test_member_current_month_usage_uses_primary_workflow_and_organization_scope(
    usage_database,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)

    _record(service, seed)
    _reserve(service, seed, attempt=2)

    with session_factory.begin() as db:
        removed_user = User(
            email=f"removed-member-{uuid.uuid4().hex}@example.invalid",
            name="Removed Member",
            social_provider="local",
        )
        other_organization = Organization(
            name=f"Other Organization {uuid.uuid4().hex}",
            created_by=seed.user_id,
            managed_by=seed.user_id,
        )
        secondary_workflow = Workflow(
            organization_id=seed.organization_id,
            app_id=seed.app_id,
            graph={"nodes": [], "edges": []},
            created_by=seed.user_id,
            updated_by=seed.user_id,
        )
        db.add_all([removed_user, other_organization, secondary_workflow])
        db.flush()
        db.add(
            OrganizationMembership(
                organization_id=seed.organization_id,
                user_id=removed_user.id,
                membership_state=ORGANIZATION_MEMBERSHIP_REMOVED,
                organization_auth_state=ORGANIZATION_AUTH_MEMBER,
                invited_by=seed.user_id,
                removed_at=datetime.now(timezone.utc),
            )
        )
        db.add_all(
            [
                _workflow_usage_log(
                    seed,
                    user_id=seed.user_id,
                    organization_id=seed.organization_id,
                    total_cost=Decimal("0.010000"),
                ),
                _workflow_usage_log(
                    seed,
                    user_id=seed.user_id,
                    organization_id=None,
                    total_cost=Decimal("0.020000"),
                ),
                _workflow_usage_log(
                    seed,
                    user_id=seed.user_id,
                    organization_id=other_organization.id,
                    total_cost=Decimal("0.500000"),
                ),
                _workflow_usage_log(
                    seed,
                    user_id=seed.user_id,
                    organization_id=seed.organization_id,
                    workflow_id=secondary_workflow.id,
                    total_cost=Decimal("0.700000"),
                ),
                _workflow_usage_log(
                    seed,
                    user_id=removed_user.id,
                    organization_id=seed.organization_id,
                    total_cost=Decimal("0.050000"),
                ),
            ]
        )

    with session_factory() as db:
        actor = db.get(User, seed.user_id)
        active_members = OrganizationMemberService.list_members(
            db,
            actor,
            seed.organization_id,
        )
        removed_members = OrganizationMemberService.list_members(
            db,
            actor,
            seed.organization_id,
            state=ORGANIZATION_MEMBERSHIP_REMOVED,
        )

    assert [member.user_id for member in active_members] == [seed.user_id]
    assert active_members[0].current_month_usage.total_cost == pytest.approx(0.034)
    assert (
        active_members[0].current_month_usage.workflow_execution_cost
        == pytest.approx(0.03)
    )
    assert (
        active_members[0].current_month_usage.agent_builder_cost
        == pytest.approx(0.004)
    )
    assert [member.user_id for member in removed_members] == [removed_user.id]
    assert removed_members[0].current_month_usage.total_cost == pytest.approx(0.05)


def test_concurrent_same_attempt_creates_one_usage_row(usage_database):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)
    reservation = _reserve(service, seed)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(service.record, reservation, _sample(seed))
            for _ in range(2)
        ]
        row_ids = [future.result(timeout=10) for future in futures]

    assert row_ids[0] == row_ids[1]
    with session_factory() as db:
        assert (
            db.scalar(
                select(func.count(LLMUsageLog.id)).where(
                    LLMUsageLog.runtime_request_id == seed.request_id
                )
            )
            == 1
        )


def test_same_attempt_with_different_billing_facts_fails_closed(usage_database):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)
    reservation = _reserve(service, seed)
    service.record(reservation, _sample(seed))

    with pytest.raises(AgentBuilderIntentUsageConflictError):
        service.record(
            reservation,
            replace(_sample(seed), completion_tokens=501),
        )


def test_request_session_cannot_attribute_usage_to_another_workflow(usage_database):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)

    with pytest.raises(AgentBuilderIntentUsageRecordingError):
        _reserve(
            service,
            seed,
            context=replace(_context(seed), workflow_id=uuid.uuid4()),
        )

    with session_factory() as db:
        assert (
            db.scalar(
                select(func.count(LLMUsageLog.id)).where(
                    LLMUsageLog.runtime_request_id == seed.request_id
                )
            )
            == 0
        )


def test_retry_after_commit_response_loss_reuses_existing_usage(usage_database):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)

    class CommitThenDisconnectService(AgentBuilderIntentUsageService):
        def __init__(self):
            super().__init__(session_factory=session_factory, max_record_attempts=2)
            self.calls = 0

        def _record_once(self, prepared):
            self.calls += 1
            row_id = super()._record_once(prepared)
            if self.calls == 1:
                raise OperationalError(
                    "usage commit acknowledgement",
                    {},
                    RuntimeError("connection unavailable"),
                )
            return row_id

    service = CommitThenDisconnectService()
    reservation = _reserve(service, seed)
    row_id = service.record(reservation, _sample(seed))

    assert service.calls == 2
    with session_factory() as db:
        rows = db.scalars(
            select(LLMUsageLog).where(LLMUsageLog.runtime_request_id == seed.request_id)
        ).all()
        assert [row.id for row in rows] == [row_id]


def test_retry_reuses_frozen_cost_after_price_change(usage_database):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)

    class CommitThenRepriceService(AgentBuilderIntentUsageService):
        def __init__(self):
            super().__init__(session_factory=session_factory, max_record_attempts=2)
            self.calls = 0

        def _record_once(self, prepared):
            self.calls += 1
            row_id = super()._record_once(prepared)
            if self.calls == 1:
                with session_factory.begin() as db:
                    db.execute(
                        update(LLMModel)
                        .where(LLMModel.id == seed.model_id)
                        .values(
                            input_price_1k=Decimal("0.200000"),
                            output_price_1k=Decimal("0.400000"),
                        )
                    )
                raise OperationalError(
                    "usage commit acknowledgement",
                    {},
                    RuntimeError("connection unavailable"),
                )
            return row_id

    service = CommitThenRepriceService()
    reservation = _reserve(service, seed)
    row_id = service.record(reservation, _sample(seed))

    with session_factory() as db:
        row = db.get(LLMUsageLog, row_id)
        assert row is not None
        assert Decimal(str(row.total_cost)) == Decimal("0.004000")


def test_reserved_usage_survives_configuration_changes_during_provider_call(
    usage_database,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)
    reservation = _reserve(service, seed)

    with session_factory.begin() as db:
        workflow = db.get(Workflow, seed.workflow_id)
        app = db.get(App, workflow.app_id)
        replacement = Workflow(
            organization_id=seed.organization_id,
            app_id=app.id,
            graph={"nodes": [], "edges": []},
            created_by=seed.user_id,
            updated_by=seed.user_id,
        )
        db.add(replacement)
        db.flush()
        app.workflow_id = replacement.id
        db.execute(delete(LLMCredential).where(LLMCredential.id == seed.credential_id))
        db.execute(delete(LLMModel).where(LLMModel.id == seed.model_id))

    row_id = service.record(reservation, _sample(seed))

    with session_factory() as db:
        row = db.get(LLMUsageLog, row_id)
        assert row is not None
        assert row.status == "success"
        assert row.credential_id is None
        assert row.model_id is None
        assert Decimal(str(row.total_cost)) == Decimal("0.004000")


def test_provider_failure_cancellation_removes_pending_usage(usage_database):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)
    reservation = _reserve(service, seed)

    now = datetime.now(timezone.utc)
    with session_factory.begin() as db:
        pending = db.get(LLMUsageLog, reservation.id)
        pending.prompt_tokens = 100
        pending.completion_tokens = 20
        pending.total_cost = Decimal("1.000000")
        pending.latency_ms = 10

    with session_factory() as db:
        usage = AdminUsageService.aggregate_workflow_usage(
            db,
            seed.organization_id,
            AdminUsageService.resolve_month_period_kst(now),
            now=now,
        )
        item = next(entry for entry in usage.items if entry.workflow_id == seed.workflow_id)
        assert item.call_count == 0
        assert item.total_cost == pytest.approx(0)
        assert get_top_expensive_models(
            db=db,
            current_user=SimpleNamespace(id=seed.user_id),
        ) == []
        metrics = AppService._operation_metrics_by_workflow_id(
            db,
            [seed.workflow_id],
            now=now,
        )
        assert metrics[seed.workflow_id]["current_month_cost"] == pytest.approx(0)
        assert WorkflowBudgetService.get_current_month_cost(
            db,
            seed.workflow_id,
            now,
            organization_id=seed.organization_id,
        ) == Decimal("0")

    with session_factory.begin() as db:
        pending = db.get(LLMUsageLog, reservation.id)
        pending.prompt_tokens = 0
        pending.completion_tokens = 0
        pending.total_cost = Decimal("0")
        pending.latency_ms = 0

    service.cancel(reservation)

    with session_factory() as db:
        assert db.get(LLMUsageLog, reservation.id) is None


def test_retry_reuses_committed_usage_after_model_and_credential_delete(
    usage_database,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)

    class CommitThenDeleteReferencesService(AgentBuilderIntentUsageService):
        def __init__(self):
            super().__init__(session_factory=session_factory, max_record_attempts=2)
            self.calls = 0

        def _record_once(self, prepared):
            self.calls += 1
            row_id = super()._record_once(prepared)
            if self.calls == 1:
                with session_factory.begin() as db:
                    db.execute(
                        delete(LLMCredential).where(
                            LLMCredential.id == seed.credential_id
                        )
                    )
                    db.execute(delete(LLMModel).where(LLMModel.id == seed.model_id))
                raise OperationalError(
                    "usage commit acknowledgement",
                    {},
                    RuntimeError("connection unavailable"),
                )
            return row_id

    service = CommitThenDeleteReferencesService()
    reservation = _reserve(service, seed)
    row_id = service.record(reservation, _sample(seed))

    with session_factory() as db:
        row = db.get(LLMUsageLog, row_id)
        assert row is not None
        assert row.model_id is None
        assert row.credential_id is None
        assert Decimal(str(row.total_cost)) == Decimal("0.004000")


def test_new_usage_rejects_workflow_that_is_no_longer_app_primary(
    usage_database,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)

    with session_factory.begin() as db:
        workflow = db.get(Workflow, seed.workflow_id)
        app = db.get(App, workflow.app_id)
        replacement = Workflow(
            organization_id=seed.organization_id,
            app_id=app.id,
            graph={"nodes": [], "edges": []},
            created_by=seed.user_id,
            updated_by=seed.user_id,
        )
        db.add(replacement)
        db.flush()
        app.workflow_id = replacement.id

    with pytest.raises(AgentBuilderIntentUsageRecordingError):
        _reserve(
            AgentBuilderIntentUsageService(session_factory=session_factory),
            seed,
        )

    with session_factory() as db:
        assert db.scalar(
            select(func.count(LLMUsageLog.id)).where(
                LLMUsageLog.runtime_request_id == seed.request_id
            )
        ) == 0


@pytest.mark.parametrize(
    "invalid_condition",
    [
        "credential_invalid",
        "model_inactive",
        "model_not_chat",
        "relation_unverified",
        "credential_use_denied",
        "membership_inactive",
    ],
)
def test_new_usage_revalidates_runtime_selection_before_reservation(
    usage_database,
    invalid_condition,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)

    with session_factory.begin() as db:
        if invalid_condition == "credential_invalid":
            db.get(LLMCredential, seed.credential_id).is_valid = False
        elif invalid_condition == "model_inactive":
            db.get(LLMModel, seed.model_id).is_active = False
        elif invalid_condition == "model_not_chat":
            db.get(LLMModel, seed.model_id).type = "embedding"
        elif invalid_condition == "relation_unverified":
            relation = db.scalar(
                select(LLMRelCredentialModel).where(
                    LLMRelCredentialModel.credential_id == seed.credential_id,
                    LLMRelCredentialModel.model_id == seed.model_id,
                )
            )
            relation.is_verified = False
        else:
            membership = db.scalar(
                select(OrganizationMembership).where(
                    OrganizationMembership.organization_id
                    == seed.organization_id,
                    OrganizationMembership.user_id == seed.user_id,
                )
            )
            if invalid_condition == "credential_use_denied":
                membership.organization_auth_state = ORGANIZATION_AUTH_MEMBER
            else:
                membership.membership_state = ORGANIZATION_MEMBERSHIP_SUSPENDED

    with pytest.raises(AgentBuilderIntentUsageRecordingError):
        _reserve(
            AgentBuilderIntentUsageService(session_factory=session_factory),
            seed,
        )

    with session_factory() as db:
        assert db.scalar(
            select(func.count(LLMUsageLog.id)).where(
                LLMUsageLog.runtime_request_id == seed.request_id
            )
        ) == 0


class _SequenceIntentClient:
    def __init__(self, payloads: list[dict]):
        self._payloads = list(payloads)
        self.calls = 0

    def invoke_sync(self, _messages, **_kwargs):
        payload = self._payloads[self.calls]
        self.calls += 1
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(payload, ensure_ascii=False),
                    }
                }
            ],
            "usage": {
                "prompt_tokens": self.calls * 10,
                "completion_tokens": self.calls * 2,
            },
        }


@pytest.mark.parametrize("requires_repair", [False, True])
def test_message_api_persists_each_provider_attempt_through_production_composition(
    usage_database,
    monkeypatch,
    requires_repair,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    with session_factory.begin() as db:
        db.get(AgentBuilderRequest, seed.request_id).status = "completed"

    valid_payload = {
        "request_type": "unsupported",
        "draft_mode": "new_workflow",
        "intent_summary": "지원 범위 확인",
        "ordered_capabilities": [],
        "unsupported_requests": ["테스트에서 지원하지 않는 요청"],
    }
    payloads = [valid_payload]
    if requires_repair:
        payloads.insert(
            0,
            {
                "request_type": "invalid",
                "draft_mode": "new_workflow",
                "intent_summary": "수정이 필요한 응답",
                "ordered_capabilities": [],
            },
        )
    client = _SequenceIntentClient(payloads)

    monkeypatch.setattr(
        LLMService,
        "get_wizard_client_for_selection",
        staticmethod(
            lambda **_kwargs: SimpleNamespace(
                client=client,
                credential_id=seed.credential_id,
                model_db_id=seed.model_id,
                model_id="intent-usage-model",
                organization_id=seed.organization_id,
            )
        ),
    )
    monkeypatch.setattr(
        agent_builder_composition,
        "AgentBuilderIntentUsageService",
        lambda: AgentBuilderIntentUsageService(session_factory=session_factory),
    )

    def override_db():
        with session_factory() as db:
            yield db

    gateway_app.dependency_overrides[agent_builder_endpoint.get_db] = override_db
    gateway_app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=seed.user_id
    )
    try:
        response = TestClient(gateway_app).post(
            f"/api/v1/agent-builder/sessions/{seed.session_id}/messages",
            json={
                "message": "지원 범위를 확인해줘",
                "workflow_id": str(seed.workflow_id),
                "intent_model_selection": {
                    "credential_id": str(seed.credential_id),
                    "model_id": str(seed.model_id),
                },
            },
            headers={"X-Organization-Id": str(seed.organization_id)},
        )
    finally:
        gateway_app.dependency_overrides = {}

    assert response.status_code == 200
    assert response.json()["status"] == "unsupported"
    assert client.calls == (2 if requires_repair else 1)
    with session_factory() as db:
        rows = db.scalars(
            select(LLMUsageLog)
            .where(LLMUsageLog.runtime_session_id == seed.session_id)
            .order_by(LLMUsageLog.runtime_attempt)
        ).all()
        assert [row.runtime_attempt for row in rows] == (
            [1, 2] if requires_repair else [1]
        )
        assert [row.prompt_tokens for row in rows] == (
            [10, 20] if requires_repair else [10]
        )


def test_deleted_model_and_credential_preserve_tokens_cost_and_aggregates(
    usage_database,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)
    row_id = _record(service, seed)

    with session_factory.begin() as db:
        db.execute(delete(LLMCredential).where(LLMCredential.id == seed.credential_id))
        db.execute(delete(LLMModel).where(LLMModel.id == seed.model_id))

    now = datetime.now(timezone.utc)
    with session_factory() as db:
        row = db.get(LLMUsageLog, row_id)
        assert row is not None
        assert row.credential_id is None
        assert row.model_id is None
        assert row.prompt_tokens == 1000
        assert row.completion_tokens == 500
        assert Decimal(str(row.total_cost)) == Decimal("0.004000")
        assert WorkflowBudgetService.get_current_month_cost(
            db,
            seed.workflow_id,
            now,
            organization_id=seed.organization_id,
        ) == Decimal("0.004000")
        summary = AdminUsageService.get_organization_summary(
            db,
            seed.organization_id,
            now=now,
        )
        assert summary.total_cost == pytest.approx(0.004)


def test_agent_builder_session_cleanup_preserves_usage_history(usage_database):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    service = AgentBuilderIntentUsageService(session_factory=session_factory)
    row_id = _record(service, seed)

    with session_factory.begin() as db:
        db.execute(
            delete(AgentBuilderSession).where(AgentBuilderSession.id == seed.session_id)
        )

    with session_factory() as db:
        assert db.get(AgentBuilderRequest, seed.request_id) is None
        row = db.get(LLMUsageLog, row_id)
        assert row is not None
        assert row.runtime_session_id == seed.session_id
        assert row.runtime_request_id == seed.request_id
        assert row.prompt_tokens == 1000
        assert row.completion_tokens == 500
        assert Decimal(str(row.total_cost)) == Decimal("0.004000")


def test_migration_has_nullable_history_links_and_agent_builder_attempt_key(
    usage_database,
):
    engine, _ = usage_database
    with engine.connect() as connection:
        nullable = dict(
            connection.execute(
                text(
                    """
                    SELECT column_name, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = 'llm_usage_logs'
                      AND column_name IN (
                        'credential_id', 'model_id', 'runtime_surface',
                        'runtime_session_id', 'runtime_request_id', 'runtime_attempt'
                      )
                    """
                )
            ).all()
        )
        index_definition = connection.execute(
            text(
                """
                SELECT indexdef
                FROM pg_indexes
                WHERE tablename = 'llm_usage_logs'
                  AND indexname = 'uq_llm_usage_logs_agent_builder_attempt'
                """
            )
        ).scalar_one()
        constraint_names = set(
            connection.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'llm_usage_logs'::regclass
                      AND conname IN (
                        'ck_llm_usage_logs_runtime_attempt_positive',
                        'ck_llm_usage_logs_agent_builder_runtime_identity',
                        'ck_llm_usage_logs_agent_builder_billing_facts'
                      )
                    """
                )
            ).scalars()
        )

    assert set(nullable) == {
        "credential_id",
        "model_id",
        "runtime_surface",
        "runtime_session_id",
        "runtime_request_id",
        "runtime_attempt",
    }
    assert set(nullable.values()) == {"YES"}
    assert "UNIQUE" in index_definition
    assert "agent_builder_intent" in index_definition
    assert constraint_names == {
        "ck_llm_usage_logs_runtime_attempt_positive",
        "ck_llm_usage_logs_agent_builder_runtime_identity",
        "ck_llm_usage_logs_agent_builder_billing_facts",
    }


@pytest.mark.parametrize(
    "invalid_runtime",
    [
        {
            "runtime_surface": None,
            "runtime_session_id": None,
            "runtime_request_id": None,
            "runtime_attempt": 0,
        },
        {
            "runtime_surface": "agent_builder_intent",
            "runtime_session_id": None,
            "runtime_request_id": uuid.uuid4(),
            "runtime_attempt": 1,
        },
        {
            "runtime_surface": "agent_builder_intent",
            "runtime_session_id": uuid.uuid4(),
            "runtime_request_id": uuid.uuid4(),
            "runtime_attempt": 1,
            "prompt_tokens": -1,
        },
        {
            "runtime_surface": "agent_builder_intent",
            "runtime_session_id": uuid.uuid4(),
            "runtime_request_id": uuid.uuid4(),
            "runtime_attempt": 1,
            "total_cost": Decimal("-0.000001"),
        },
    ],
)
def test_usage_runtime_check_constraints_reject_invalid_rows(
    usage_database,
    invalid_runtime,
):
    engine, _ = usage_database
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    seed = _seed_contract(session_factory)
    values = {
        "id": uuid.uuid4(),
        "user_id": seed.user_id,
        "organization_id": seed.organization_id,
        "credential_id": seed.credential_id,
        "model_id": seed.model_id,
        "workflow_id": seed.workflow_id,
        "workflow_run_id": None,
        "cost_optimizer_candidate_id": None,
        "node_id": None,
        "prompt_tokens": 1,
        "completion_tokens": 1,
        "total_cost": Decimal("0.000001"),
        "latency_ms": 1,
        "status": "success",
        "error_message": None,
        "created_at": datetime.now(timezone.utc),
        **invalid_runtime,
    }

    with pytest.raises(IntegrityError):
        with session_factory.begin() as db:
            db.execute(insert(LLMUsageLog).values(**values))


def test_migration_round_trip_on_empty_usage_history():
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL settings are not safely configured",
            pytrace=False,
        ) from None

    with _disposable_database(config) as (engine, database):
        engine.dispose()
        _run_alembic(database, config, "downgrade", "a7b8c9d0e1f2")
        downgraded_engine = create_engine(config.database_url(database))
        try:
            with downgraded_engine.connect() as connection:
                runtime_columns = connection.execute(
                    text(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_name = 'llm_usage_logs'
                          AND column_name LIKE 'runtime_%'
                        """
                    )
                ).all()
                required_links = dict(
                    connection.execute(
                        text(
                            """
                            SELECT column_name, is_nullable
                            FROM information_schema.columns
                            WHERE table_name = 'llm_usage_logs'
                              AND column_name IN ('credential_id', 'model_id')
                            """
                        )
                    ).all()
                )
            assert runtime_columns == []
            assert set(required_links.values()) == {"NO"}
        finally:
            downgraded_engine.dispose()

        _run_alembic(database, config, "upgrade", "heads")
        upgraded_engine = create_engine(config.database_url(database))
        try:
            with upgraded_engine.connect() as connection:
                assert (
                    connection.execute(
                        text("SELECT version_num FROM alembic_version")
                    ).scalar_one()
                    == "a8c9d0e1f2a3"
                )
        finally:
            upgraded_engine.dispose()


def test_migration_downgrade_rejects_agent_builder_usage_history():
    try:
        config = DisposablePostgresConfig.from_environment()
    except DisposablePostgresConfigurationError:
        raise pytest.fail.Exception(
            "disposable PostgreSQL settings are not safely configured",
            pytrace=False,
        ) from None

    with _disposable_database(config) as (engine, database):
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)
        seed = _seed_contract(session_factory)
        service = AgentBuilderIntentUsageService(session_factory=session_factory)
        _record(service, seed)
        engine.dispose()

        result = _run_alembic_result(
            database,
            config,
            "downgrade",
            "a7b8c9d0e1f2",
        )

        preserved_engine = create_engine(config.database_url(database))
        try:
            with preserved_engine.connect() as connection:
                preserved_usage_count = connection.execute(
                    text(
                        "SELECT count(*) FROM llm_usage_logs "
                        "WHERE runtime_surface = 'agent_builder_intent'"
                    )
                ).scalar_one()
                version = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
        finally:
            preserved_engine.dispose()

    assert result.returncode != 0
    output = result.stdout + result.stderr
    if "cannot downgrade Agent Builder usage migration" not in output:
        pytest.fail("downgrade rejection did not report the expected safe error")
    if "Agent Builder usage rows exist" not in output:
        pytest.fail("downgrade rejection did not report the preserved usage reason")
    assert preserved_usage_count == 1
    assert version == "a8c9d0e1f2a3"
