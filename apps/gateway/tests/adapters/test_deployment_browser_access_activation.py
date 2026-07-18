from __future__ import annotations

import uuid

from apps.gateway.adapters.deployment_browser_access_activation import (
    DeploymentBrowserAccessActivationGuard,
)
from apps.gateway.composition import deployment as deployment_composition
from apps.gateway.application.deployment.browser_access_models import (
    BrowserAccessSourceSnapshot,
)


def test_activation_guard_revalidates_mail_credentials_and_runtime_preflight(
    monkeypatch,
) -> None:
    calls = []
    source = BrowserAccessSourceSnapshot(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        version=2,
        deployment_type="chatbot",
        graph_snapshot={"nodes": [], "edges": []},
        config={},
        input_schema=None,
        output_schema=None,
        description=None,
        url_slug="chatbot",
    )
    actor_id = uuid.uuid4()

    def validate_mail(db, graph, **kwargs):
        calls.append(("mail", db, graph, kwargs))

    class _Preflight:
        def enforce_active_publish(self, **kwargs):
            calls.append(("preflight", kwargs))

    def build_preflight(checked_source, checked_actor_id):
        calls.append(("build", checked_source, checked_actor_id))
        return _Preflight()

    monkeypatch.setattr(
        "apps.gateway.adapters.deployment_browser_access_activation."
        "WorkflowService.validate_mail_credential_references",
        validate_mail,
    )
    db = object()

    DeploymentBrowserAccessActivationGuard(
        db,
        preflight_factory=build_preflight,
    ).enforce(
        source,
        actor_id=actor_id,
    )

    assert calls[0] == (
        "mail",
        db,
        source.graph_snapshot,
        {
            "user_id": str(actor_id),
            "organization_id": source.organization_id,
            "require_resolved": True,
        },
    )
    assert calls[1][0] == "build"
    assert calls[1][1] is source
    assert calls[1][2] == actor_id
    assert calls[2] == (
        "preflight",
        {
            "deployment_type": "chatbot",
            "graph_snapshot": source.graph_snapshot,
        },
    )


def test_composition_builds_activation_preflight_with_actor_and_candidate(
    monkeypatch,
) -> None:
    source = BrowserAccessSourceSnapshot(
        id=uuid.uuid4(),
        app_id=uuid.uuid4(),
        workflow_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        version=2,
        deployment_type="chatbot",
        graph_snapshot={"nodes": [], "edges": []},
        config={},
        input_schema=None,
        output_schema=None,
        description=None,
        url_slug="chatbot",
    )
    actor_id = uuid.uuid4()
    db = object()
    expected = object()
    captured = {}

    def build_preflight(checked_db, **kwargs):
        captured.update({"db": checked_db, **kwargs})
        return expected

    monkeypatch.setattr(
        deployment_composition,
        "build_deployment_preflight_use_case",
        build_preflight,
    )

    use_case = deployment_composition.build_browser_access_revision_use_case(
        db,
        actor=object(),
    )
    result = use_case.activation_guard.preflight_factory(source, actor_id)

    assert result is expected
    assert captured == {
        "db": db,
        "organization_id": source.organization_id,
        "principal_id": actor_id,
        "candidate_graphs_by_app_id": {
            source.app_id: source.graph_snapshot,
        },
        "candidate_deployment_types_by_app_id": {
            source.app_id: source.deployment_type,
        },
    }
