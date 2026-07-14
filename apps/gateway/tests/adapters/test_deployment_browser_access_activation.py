from __future__ import annotations

import uuid

from apps.gateway.adapters.deployment_browser_access_activation import (
    DeploymentBrowserAccessActivationGuard,
)
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
        auth_secret=None,
    )
    actor_id = uuid.uuid4()

    def validate_mail(db, graph, **kwargs):
        calls.append(("mail", db, graph, kwargs))

    class _Preflight:
        def enforce_active_publish(self, **kwargs):
            calls.append(("preflight", kwargs))

    def build_preflight(db, checked_source):
        calls.append(("build", db, checked_source))
        return _Preflight()

    monkeypatch.setattr(
        "apps.gateway.adapters.deployment_browser_access_activation."
        "WorkflowService.validate_mail_credential_references",
        validate_mail,
    )
    monkeypatch.setattr(
        "apps.gateway.adapters.deployment_browser_access_activation."
        "_build_preflight_use_case",
        build_preflight,
    )
    db = object()

    DeploymentBrowserAccessActivationGuard(db).enforce(
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
    assert calls[1][1] is db
    assert calls[1][2] is source
    assert calls[2] == (
        "preflight",
        {
            "deployment_type": "chatbot",
            "graph_snapshot": source.graph_snapshot,
        },
    )
