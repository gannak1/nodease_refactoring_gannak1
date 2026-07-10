import uuid
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.sql.operators import eq, in_op, is_, ne

from apps.gateway.services import deployment_service as deployment_module
from apps.gateway.services.deployment_service import DeploymentService
from apps.gateway.services.knowledge_deployment_preflight_service import (
    KnowledgeDeploymentPreflightService,
)
from apps.shared.db.models.app import App
from apps.shared.db.models.knowledge import (
    KnowledgeBase,
    KnowledgeCollection,
    KnowledgeCollectionItem,
)
from apps.shared.db.models.schedule import Schedule
from apps.shared.db.models.workflow import Workflow
from apps.shared.db.models.workflow_deployment import DeploymentType, WorkflowDeployment
from apps.shared.domain.deployment_runtime_policy import (
    DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
)
from apps.shared.schemas.deployment import DeploymentCreate


def test_preflight_blocks_private_kb_for_public_surface():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    db = _Db(
        {
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=None,
                )
            ]
        }
    )

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.CHATBOT,
        graph_snapshot=_llm_graph(kb_id),
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "private_kb_requires_execution_subject"
    assert result.safe_summary.affected_kb_count_bucket == "1"
    assert str(kb_id) not in result.model_dump_json()


def test_inactive_preflight_preview_downgrades_public_blockers_to_warning():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    db = _Db(
        {
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=None,
                )
            ]
        }
    )

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.CHATBOT,
        graph_snapshot=_llm_graph(kb_id),
        is_active=False,
    )

    assert result.status == "warning"
    assert result.nodes[0].status == "warning"
    assert result.warnings == ["private_kb_requires_execution_subject"]
    assert result.required_actions[0].action == (
        "remove_private_kb_or_use_authenticated_run"
    )


def test_preflight_allows_public_collection_kb_for_public_surface():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    db = _Db(
        {
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=None,
                )
            ],
            KnowledgeCollectionItem: [
                _row(
                    organization_id=organization_id,
                    collection_id=collection_id,
                    knowledge_base_id=kb_id,
                )
            ],
            KnowledgeCollection: [
                _row(
                    id=collection_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    safe_metadata={"visibility": "public"},
                )
            ],
        }
    )

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.API,
        graph_snapshot=_llm_graph(kb_id),
    )

    assert result.status == "passed"
    assert result.nodes == []


def test_preflight_blocks_source_managed_kb_even_if_collection_is_public():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    collection_id = uuid.uuid4()
    db = _Db(
        {
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=uuid.uuid4(),
                )
            ],
            KnowledgeCollectionItem: [
                _row(
                    organization_id=organization_id,
                    collection_id=collection_id,
                    knowledge_base_id=kb_id,
                )
            ],
            KnowledgeCollection: [
                _row(
                    id=collection_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    safe_metadata={"visibility": "public"},
                )
            ],
        }
    )

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.WEBHOOK,
        graph_snapshot=_llm_graph(kb_id),
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "source_public_exposure_required"


def test_workflow_node_preflight_uses_data_app_id_for_target_lookup():
    organization_id = uuid.uuid4()
    target_app_id = uuid.uuid4()
    target_deployment_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    db = _Db(
        {
            App: [
                _row(
                    id=target_app_id,
                    organization_id=organization_id,
                    active_deployment_id=target_deployment_id,
                )
            ],
            WorkflowDeployment: [
                _row(
                    id=target_deployment_id,
                    app_id=target_app_id,
                    is_active=True,
                    type=DeploymentType.WORKFLOW_NODE,
                    graph_snapshot=_llm_graph(kb_id),
                )
            ],
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=None,
                )
            ],
        }
    )
    graph = {
        "nodes": [
            {
                "id": "workflow-1",
                "type": "workflowNode",
                "data": {
                    "appId": str(target_app_id),
                    "workflowId": str(uuid.uuid4()),
                },
            }
        ],
        "edges": [],
    }

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.CHATBOT,
        graph_snapshot=graph,
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "private_kb_requires_execution_subject"


def test_workflow_node_preflight_rejects_non_workflow_node_active_deployment():
    organization_id = uuid.uuid4()
    target_app_id = uuid.uuid4()
    target_deployment_id = uuid.uuid4()
    db = _Db(
        {
            App: [
                _row(
                    id=target_app_id,
                    organization_id=organization_id,
                    active_deployment_id=target_deployment_id,
                )
            ],
            WorkflowDeployment: [
                _row(
                    id=target_deployment_id,
                    app_id=target_app_id,
                    is_active=True,
                    type=DeploymentType.API,
                    graph_snapshot={"nodes": [], "edges": []},
                )
            ],
        }
    )

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.CHATBOT,
        graph_snapshot=_workflow_node_graph(target_app_id),
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "workflow_node_target_unavailable"


def test_workflow_node_preflight_rejects_non_workflow_node_candidate_target():
    organization_id = uuid.uuid4()
    app_a_id = uuid.uuid4()
    app_b_id = uuid.uuid4()
    deployment_b_id = uuid.uuid4()
    db = _Db(
        {
            App: [
                _row(
                    id=app_a_id,
                    organization_id=organization_id,
                    active_deployment_id=uuid.uuid4(),
                ),
                _row(
                    id=app_b_id,
                    organization_id=organization_id,
                    active_deployment_id=deployment_b_id,
                ),
            ],
            WorkflowDeployment: [
                _row(
                    id=deployment_b_id,
                    app_id=app_b_id,
                    is_active=True,
                    type=DeploymentType.WORKFLOW_NODE,
                    graph_snapshot=_workflow_node_graph(app_a_id),
                )
            ],
        }
    )
    candidate_a_graph = _workflow_node_graph(app_b_id)

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
        candidate_graphs_by_app_id={app_a_id: candidate_a_graph},
        candidate_deployment_types_by_app_id={app_a_id: DeploymentType.CHATBOT},
    ).preview(
        deployment_type=DeploymentType.CHATBOT,
        graph_snapshot=candidate_a_graph,
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "workflow_node_target_unavailable"


def test_workflow_node_preflight_uses_candidate_graph_for_pending_workflow_node():
    organization_id = uuid.uuid4()
    app_a_id = uuid.uuid4()
    app_b_id = uuid.uuid4()
    deployment_b_id = uuid.uuid4()
    db = _Db(
        {
            App: [
                _row(
                    id=app_a_id,
                    organization_id=organization_id,
                    active_deployment_id=uuid.uuid4(),
                ),
                _row(
                    id=app_b_id,
                    organization_id=organization_id,
                    active_deployment_id=deployment_b_id,
                ),
            ],
            WorkflowDeployment: [
                _row(
                    id=deployment_b_id,
                    app_id=app_b_id,
                    is_active=True,
                    type=DeploymentType.WORKFLOW_NODE,
                    graph_snapshot=_workflow_node_graph(app_a_id),
                )
            ],
        }
    )
    candidate_a_graph = _workflow_node_graph(app_b_id)

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
        candidate_graphs_by_app_id={app_a_id: candidate_a_graph},
        candidate_deployment_types_by_app_id={app_a_id: DeploymentType.WORKFLOW_NODE},
    ).preview(
        deployment_type=DeploymentType.WORKFLOW_NODE,
        graph_snapshot=candidate_a_graph,
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "workflow_node_cycle_detected"


def test_workflow_node_deployment_blocks_unavailable_target_even_with_inherited_subject():
    organization_id = uuid.uuid4()
    missing_app_id = uuid.uuid4()

    result = KnowledgeDeploymentPreflightService(
        _Db(),
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.WORKFLOW_NODE,
        graph_snapshot=_workflow_node_graph(missing_app_id),
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "workflow_node_target_unavailable"
    assert result.warnings == []


def test_inactive_preview_keeps_workflow_node_structural_blockers_blocked():
    organization_id = uuid.uuid4()
    missing_app_id = uuid.uuid4()

    result = KnowledgeDeploymentPreflightService(
        _Db(),
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.WORKFLOW_NODE,
        graph_snapshot=_workflow_node_graph(missing_app_id),
        is_active=False,
    )

    assert result.status == "blocked"
    assert result.safe_summary.blocked_reason == "workflow_node_target_unavailable"
    assert result.warnings == []


def test_workflow_node_deployment_warns_for_inherited_subject_instead_of_blocking():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    db = _Db(
        {
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=None,
                )
            ]
        }
    )

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.WORKFLOW_NODE,
        graph_snapshot=_llm_graph(kb_id),
    )

    assert result.status == "warning"
    assert result.warnings == ["workflow_node_execution_subject_inherited"]


def test_enforced_preflight_raises_409_error_envelope():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    db = _Db(
        {
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=None,
                )
            ]
        }
    )
    service = KnowledgeDeploymentPreflightService(db, organization_id=organization_id)

    with pytest.raises(HTTPException) as exc_info:
        service.enforce_active_publish(
            deployment_type=DeploymentType.CHATBOT,
            graph_snapshot=_llm_graph(kb_id),
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"]["code"] == "deployment.preflight.blocked"


def test_preflight_audience_classifies_every_deployment_type():
    assert {
        deployment_type: KnowledgeDeploymentPreflightService.server_derived_audience(
            deployment_type
        )
        for deployment_type in DeploymentType
    } == {
        DeploymentType.API: "anonymous_public",
        DeploymentType.WEBAPP: "anonymous_public",
        DeploymentType.WIDGET: "anonymous_public",
        DeploymentType.CHATBOT: "anonymous_public",
        DeploymentType.MCP: "anonymous_public",
        DeploymentType.WORKFLOW_NODE: "workflow_node_inherited",
        DeploymentType.SCHEDULE: "anonymous_public",
        DeploymentType.WEBHOOK: "anonymous_public",
    }


def test_preflight_audience_hint_cannot_relax_public_surface():
    organization_id = uuid.uuid4()
    kb_id = uuid.uuid4()
    db = _Db(
        {
            KnowledgeBase: [
                _row(
                    id=kb_id,
                    organization_id=organization_id,
                    lifecycle_state="active",
                    source_identity_id=None,
                )
            ]
        }
    )

    result = KnowledgeDeploymentPreflightService(
        db,
        organization_id=organization_id,
    ).preview(
        deployment_type=DeploymentType.CHATBOT,
        graph_snapshot=_llm_graph(kb_id),
        audience_hint="authenticated_user",
    )

    assert result.audience == "anonymous_public"
    assert result.status == "blocked"


def test_create_preserves_preflight_http_exception(monkeypatch):
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    app = App(
        id=app_id,
        workflow_id=workflow_id,
        organization_id=uuid.uuid4(),
        url_slug="app-slug",
        auth_secret="existing-secret",
        created_by=uuid.uuid4(),
    )
    workflow = _row(
        id=workflow_id,
        organization_id=app.organization_id,
        app_id=app.id,
        created_by=app.created_by,
    )
    db = _Db({App: [app], Workflow: [workflow]})
    expected = HTTPException(
        status_code=409,
        detail={"error": {"code": "deployment.preflight.blocked"}},
    )

    monkeypatch.setattr(
        deployment_module, "has_workflow_permission", lambda *a, **k: True
    )
    monkeypatch.setattr(
        DeploymentService,
        "_enforce_knowledge_preflight",
        lambda *a, **k: (_ for _ in ()).throw(expected),
    )

    with pytest.raises(HTTPException) as exc_info:
        DeploymentService.create_deployment(
            db,
            DeploymentCreate(
                app_id=app_id,
                type=DeploymentType.CHATBOT,
                graph_snapshot={"nodes": [], "edges": []},
                is_active=True,
            ),
                user_id=app.created_by,
                runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["error"]["code"] == "deployment.preflight.blocked"


def test_inactive_create_does_not_mutate_active_surface(monkeypatch):
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    active_deployment_id = uuid.uuid4()
    app = App(
        id=app_id,
        workflow_id=workflow_id,
        organization_id=uuid.uuid4(),
        active_deployment_id=active_deployment_id,
        url_slug="app-slug",
        auth_secret="existing-secret",
        created_by=uuid.uuid4(),
    )
    workflow = _row(
        id=workflow_id,
        organization_id=app.organization_id,
        app_id=app.id,
        created_by=app.created_by,
    )
    db = _Db({App: [app], Workflow: [workflow]}, max_deployment_version=2)

    monkeypatch.setattr(
        deployment_module, "has_workflow_permission", lambda *a, **k: True
    )
    monkeypatch.setattr(
        DeploymentService,
        "_enforce_knowledge_preflight",
        lambda *a, **k: pytest.fail("inactive create must not enforce preflight"),
    )

    deployment = DeploymentService.create_deployment(
        db,
        DeploymentCreate(
            app_id=app_id,
            type=DeploymentType.CHATBOT,
            graph_snapshot={
                "nodes": [
                    {
                        "id": "schedule-1",
                        "type": "scheduleTrigger",
                        "data": {"cron_expression": "* * * * *"},
                    }
                ],
                "edges": [],
            },
            is_active=False,
        ),
        user_id=app.created_by,
        runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    )

    assert deployment.is_active is False
    assert deployment.version == 3
    assert app.active_deployment_id == active_deployment_id
    assert not db.rows_for(Schedule)


def test_workflow_node_create_does_not_create_schedule_surface(monkeypatch):
    app_id = uuid.uuid4()
    workflow_id = uuid.uuid4()
    app = App(
        id=app_id,
        workflow_id=workflow_id,
        organization_id=uuid.uuid4(),
        active_deployment_id=None,
        url_slug="module-slug",
        auth_secret="existing-secret",
        created_by=uuid.uuid4(),
    )
    workflow = _row(
        id=workflow_id,
        organization_id=app.organization_id,
        app_id=app.id,
        created_by=app.created_by,
    )
    db = _Db({App: [app], Workflow: [workflow], Schedule: []})
    scheduler = _Scheduler()

    monkeypatch.setattr(
        deployment_module, "has_workflow_permission", lambda *a, **k: True
    )
    monkeypatch.setattr(
        DeploymentService,
        "_enforce_knowledge_preflight",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "apps.gateway.services.scheduler_service.get_scheduler_service",
        lambda: scheduler,
    )

    deployment = DeploymentService.create_deployment(
        db,
        DeploymentCreate(
            app_id=app_id,
            type=DeploymentType.WORKFLOW_NODE,
            graph_snapshot={
                "nodes": [
                    {
                        "id": "schedule-1",
                        "type": "scheduleTrigger",
                        "data": {"cron_expression": "* * * * *"},
                    }
                ],
                "edges": [],
            },
            is_active=True,
        ),
        user_id=app.created_by,
        runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    )

    assert deployment.is_active is True
    assert app.active_deployment_id == deployment.id
    assert db.rows_for(Schedule) == []
    assert scheduler.added == []


def test_workflow_node_toggle_removes_legacy_schedule_surface(monkeypatch):
    app_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    schedule_id = uuid.uuid4()
    app = _row(id=app_id, active_deployment_id=None)
    deployment = _row(
        id=deployment_id,
        app_id=app_id,
        type=DeploymentType.WORKFLOW_NODE,
        is_active=False,
        graph_snapshot={
            "nodes": [
                {
                    "id": "schedule-1",
                    "type": "scheduleTrigger",
                    "data": {"cron_expression": "* * * * *"},
                }
            ],
            "edges": [],
        },
    )
    schedule = _row(
        id=schedule_id,
        deployment_id=deployment_id,
        cron_expression="* * * * *",
        timezone="UTC",
    )
    db = _Db({App: [app], WorkflowDeployment: [deployment], Schedule: [schedule]})
    scheduler = _Scheduler()

    monkeypatch.setattr(
        DeploymentService,
        "_enforce_knowledge_preflight",
        lambda *a, **k: None,
    )

    DeploymentService.toggle_deployment(
        db,
        deployment_id,
        scheduler,
        runtime_policy=DEFAULT_DEPLOYMENT_RUNTIME_POLICY,
    )

    assert deployment.is_active is True
    assert app.active_deployment_id == deployment_id
    assert db.rows_for(Schedule) == []
    assert scheduler.removed == [schedule_id]
    assert scheduler.added == []


def test_delete_active_deployment_does_not_auto_promote_other_deployment():
    app_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    other_deployment_id = uuid.uuid4()
    app = _row(id=app_id, active_deployment_id=deployment_id)
    deployment = _row(id=deployment_id, app_id=app_id)
    other_deployment = _row(
        id=other_deployment_id,
        app_id=app_id,
        is_active=True,
        version=2,
    )
    db = _Db(
        {
            App: [app],
            WorkflowDeployment: [deployment, other_deployment],
            Schedule: [],
        }
    )

    DeploymentService.delete_deployment(db, str(deployment_id))

    assert app.active_deployment_id is None
    assert deployment not in db.rows_for(WorkflowDeployment)
    assert other_deployment in db.rows_for(WorkflowDeployment)


def _llm_graph(kb_id: uuid.UUID) -> dict:
    return {
        "nodes": [
            {
                "id": "llm-1",
                "type": "llmNode",
                "data": {"knowledgeBases": [{"id": str(kb_id)}]},
            }
        ],
        "edges": [],
    }


def _workflow_node_graph(app_id: uuid.UUID) -> dict:
    return {
        "nodes": [
            {
                "id": "workflow-1",
                "type": "workflowNode",
                "data": {"appId": str(app_id)},
            }
        ],
        "edges": [],
    }


def _row(**kwargs):
    return SimpleNamespace(**kwargs)


class _Db:
    def __init__(self, rows_by_model=None, *, max_deployment_version=0):
        self.rows_by_model = {
            model: list(rows)
            for model, rows in (rows_by_model or {}).items()
        }
        self.max_deployment_version = max_deployment_version
        self.committed = False
        self.rolled_back = False

    def query(self, model, *rest):
        if model in {
            App,
            Workflow,
            WorkflowDeployment,
            Schedule,
            KnowledgeBase,
            KnowledgeCollection,
            KnowledgeCollectionItem,
        }:
            return _Query(self.rows_by_model.setdefault(model, []))
        return _ScalarQuery(self.max_deployment_version)

    def add(self, obj):
        self.rows_by_model.setdefault(type(obj), []).append(obj)

    def delete(self, obj):
        for rows in self.rows_by_model.values():
            if obj in rows:
                rows.remove(obj)
                return

    def flush(self):
        for deployment in self.rows_by_model.get(WorkflowDeployment, []):
            if getattr(deployment, "id", None) is None:
                deployment.id = uuid.uuid4()

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def refresh(self, obj):
        pass

    def rows_for(self, model):
        return self.rows_by_model.setdefault(model, [])


class _ScalarQuery:
    def __init__(self, value):
        self.value = value

    def filter(self, *expressions):
        return self

    def scalar(self):
        return self.value


class _Scheduler:
    def __init__(self):
        self.added = []
        self.removed = []

    def add_schedule(self, schedule, db):
        self.added.append(schedule)

    def remove_schedule(self, schedule_id):
        self.removed.append(schedule_id)


class _Query:
    def __init__(self, rows):
        self.rows = rows
        self.expressions = []

    def filter(self, *expressions):
        self.expressions.extend(expressions)
        return self

    def all(self):
        return [row for row in self.rows if self._matches(row)]

    def first(self):
        return next((row for row in self.rows if self._matches(row)), None)

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def _matches(self, row):
        return all(_matches_expression(row, expression) for expression in self.expressions)


def _matches_expression(row, expression):
    if not hasattr(expression, "left"):
        return True

    column_name = str(expression.left).split(".")[-1]
    if not hasattr(row, column_name):
        return True

    row_value = getattr(row, column_name)
    right_value = _right_value(expression.right)
    if expression.operator is eq:
        return row_value == right_value or str(row_value) == str(right_value)
    if expression.operator is ne:
        return row_value != right_value and str(row_value) != str(right_value)
    if expression.operator is in_op:
        return row_value in set(right_value or [])
    if expression.operator is is_:
        return row_value is right_value or bool(row_value) is bool(right_value)
    return True


def _right_value(right):
    if hasattr(right, "value"):
        return right.value
    if str(right).lower() == "true":
        return True
    if str(right).lower() == "false":
        return False
    return right
