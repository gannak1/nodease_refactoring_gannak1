from apps.shared.services import permission_audit


def test_user_permission_denial_preserves_user_actor(monkeypatch):
    calls = []
    monkeypatch.setattr(permission_audit, "record_audit", lambda **kwargs: calls.append(kwargs))

    permission_audit.record_resource_permission_denied(
        user_id="user-123",
        resource_type="knowledge_base",
        resource_id="kb-123",
        action="use",
        effective_auth_state="authenticated",
        organization_id="org-123",
    )

    assert calls[0]["actor_id"] == "user-123"
    assert calls[0]["actor_type"] == "user"
    assert calls[0]["metadata"]["organization_id"] == "org-123"


def test_system_permission_denial_has_no_synthetic_user_actor(monkeypatch):
    calls = []
    monkeypatch.setattr(permission_audit, "record_audit", lambda **kwargs: calls.append(kwargs))

    permission_audit.record_system_resource_permission_denied(
        resource_type="llm_credential",
        resource_id="unknown",
        action="use",
        effective_auth_state="none",
        organization_id=None,
        metadata={"runtime_surface": "workflow_llm_node"},
    )

    assert calls[0]["actor_id"] is None
    assert calls[0]["actor_type"] == "system"
    assert calls[0]["metadata"]["runtime_surface"] == "workflow_llm_node"
