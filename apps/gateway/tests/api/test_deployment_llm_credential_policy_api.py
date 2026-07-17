from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1.endpoints import deployment as deployment_endpoint
from apps.shared.schemas.deployment import DeploymentLLMCredentialPolicyUpsert
from apps.shared.services.provider_execution_capability import (
    DeploymentCredentialPolicyView,
    ProviderExecutionPolicyError,
)


class _Db:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def test_policy_write_uses_active_org_and_returns_safe_projection(monkeypatch):
    organization_id = uuid.uuid4()
    deployment_id = uuid.uuid4()
    actor_id = uuid.uuid4()
    model_id = uuid.uuid4()
    credential_id = uuid.uuid4()
    db = _Db()
    captured = {}
    now = datetime.now(timezone.utc)
    policy = DeploymentCredentialPolicyView(
        id=uuid.uuid4(),
        deployment_id=deployment_id,
        deployment_version=3,
        node_id="llm-1",
        model_id=model_id,
        credential_id=credential_id,
        policy_revision=2,
        is_active=True,
        created_at=now,
        updated_at=now,
    )

    monkeypatch.setattr(
        deployment_endpoint,
        "resolve_active_organization_id",
        lambda *_args: organization_id,
    )

    def replace(_db, *, actor_id, command):
        captured["actor_id"] = actor_id
        captured["command"] = command
        return policy

    monkeypatch.setattr(
        deployment_endpoint.ProviderExecutionCapabilityService,
        "replace_deployment_policy",
        replace,
    )

    result = deployment_endpoint.replace_deployment_llm_credential_policy.__wrapped__(
        deployment_id,
        "llm-1",
        DeploymentLLMCredentialPolicyUpsert(
            model_id=model_id,
            credential_id=credential_id,
        ),
        request=object(),
        x_organization_id=str(organization_id),
        db=db,
        current_user=SimpleNamespace(id=actor_id),
    )

    assert db.commits == 1
    assert db.rollbacks == 0
    assert captured["actor_id"] == actor_id
    assert captured["command"].organization_id == organization_id
    assert captured["command"].deployment_id == deployment_id
    assert captured["command"].node_id == "llm-1"
    assert result.model_dump() == {
        "id": policy.id,
        "deployment_id": deployment_id,
        "deployment_version": 3,
        "node_id": "llm-1",
        "model_id": model_id,
        "credential_id": credential_id,
        "policy_revision": 2,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
    }
    assert "credential_principal_user_id" not in result.model_dump()


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_code"),
    [
        (ProviderExecutionPolicyError("permission_denied"), 403, None),
        (ProviderExecutionPolicyError("resource_not_found"), 404, None),
        (ProviderExecutionPolicyError("configuration_required"), 422, "configuration_required"),
        (ProviderExecutionPolicyError("selection_ambiguous"), 409, "selection_ambiguous"),
    ],
)
def test_policy_write_maps_only_safe_errors(
    monkeypatch,
    error,
    expected_status,
    expected_code,
):
    db = _Db()
    organization_id = uuid.uuid4()
    monkeypatch.setattr(
        deployment_endpoint,
        "resolve_active_organization_id",
        lambda *_args: organization_id,
    )
    monkeypatch.setattr(
        deployment_endpoint.ProviderExecutionCapabilityService,
        "replace_deployment_policy",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(HTTPException) as exc_info:
        deployment_endpoint.replace_deployment_llm_credential_policy.__wrapped__(
            uuid.uuid4(),
            "llm-1",
            DeploymentLLMCredentialPolicyUpsert(
                model_id=uuid.uuid4(),
                credential_id=uuid.uuid4(),
            ),
            request=object(),
            x_organization_id=str(organization_id),
            db=db,
            current_user=SimpleNamespace(id=uuid.uuid4()),
        )

    assert exc_info.value.status_code == expected_status
    assert db.commits == 0
    assert db.rollbacks == 1
    if expected_code is not None:
        assert exc_info.value.detail["code"] == expected_code
