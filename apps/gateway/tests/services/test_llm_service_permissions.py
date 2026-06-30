import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1.endpoints import llm as llm_endpoint
from apps.gateway.services import llm_service
from apps.gateway.services.llm_service import (
    LLMCredentialNotAvailableError,
    LLMService,
)
from apps.shared.db.models.user import User
from apps.shared.schemas.llm import LLMCredentialCreate, LLMModelPricingUpdate


class FakeQuery:
    def __init__(self, value):
        self.value = value

    def join(self, *args, **kwargs):
        return self

    def options(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.value

    def all(self):
        return self.value


class FakeDb:
    def __init__(self, value):
        self.value = value

    def query(self, *args, **kwargs):
        return FakeQuery(self.value)


class FakeWizardRuntimeQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def options(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        if self.model is llm_service.LLMCredential:
            return self.db.credentials
        return []

    def first(self):
        if self.model is llm_service.LLMModel:
            return self.db.model
        if self.model is llm_service.LLMRelCredentialModel:
            return self.db.relations.pop(0)
        return None


class FakeWizardRuntimeDb:
    def __init__(self, credentials, model, relations):
        self.credentials = credentials
        self.model = model
        self.relations = list(relations)

    def query(self, *args, **kwargs):
        return FakeWizardRuntimeQuery(self, args[0])


class FakeCredentialRegisterQuery:
    def __init__(self, db, model):
        self.db = db
        self.model = model

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        if self.model is llm_service.LLMProvider:
            return self.db.provider
        if self.model is User:
            return SimpleNamespace(name="First User")
        return None


class FakeCredentialRegisterDb:
    def __init__(self, provider):
        self.provider = provider
        self.added = []
        self.flush_count = 0
        self.committed = False

    def query(self, *args, **kwargs):
        return FakeCredentialRegisterQuery(self, args[0])

    def add(self, row):
        self.added.append(row)

    def flush(self):
        self.flush_count += 1
        now = datetime.now(timezone.utc)
        for row in self.added:
            if getattr(row, "id", None) is None:
                row.id = uuid.uuid4()
            if getattr(row, "created_at", None) is None:
                row.created_at = now
            if getattr(row, "updated_at", None) is None:
                row.updated_at = now

    def commit(self):
        self.committed = True

    def refresh(self, row):
        self.refreshed = row


def test_delete_credential_preserves_permission_http_exception(monkeypatch):
    credential_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    seen = {}

    def deny(db, current_user, checked_credential_id, action):
        seen["action"] = action
        raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(llm_endpoint, "ensure_llm_credential_permission", deny)
    monkeypatch.setattr(
        "apps.gateway.utils.audit.record_audit",
        lambda **kwargs: None,
    )

    with pytest.raises(HTTPException) as exc_info:
        llm_endpoint.delete_credential(credential_id, FakeDb(None), user)

    assert exc_info.value.status_code == 403
    assert seen["action"] == "write"


def _route(path, method):
    for route in llm_endpoint.router.routes:
        if route.path == path and method in route.methods:
            return route
    raise AssertionError(f"route not found: {method} {path}")


def _dependency_calls(route):
    return [dependency.call for dependency in route.dependant.dependencies]


def test_llm_catalog_and_pricing_routes_require_current_user():
    protected_routes = [
        ("/providers", "GET"),
        ("/models/sync-pricing", "POST"),
        ("/models/{model_id}/pricing", "PUT"),
    ]

    for path, method in protected_routes:
        route = _route(path, method)
        assert llm_endpoint.get_current_user in _dependency_calls(route)


def test_sync_system_pricing_requires_system_admin(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())

    monkeypatch.setattr(
        llm_endpoint.TraceAccessService,
        "is_system_admin",
        staticmethod(lambda db, current_user: False),
    )
    monkeypatch.setattr(
        LLMService,
        "sync_system_prices",
        lambda *a, **k: pytest.fail("pricing sync should require system admin"),
    )

    with pytest.raises(HTTPException) as exc_info:
        llm_endpoint.sync_system_pricing(db=FakeDb(None), current_user=user)

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "system_admin_required"


def test_update_model_pricing_requires_system_admin(monkeypatch):
    user = SimpleNamespace(id=uuid.uuid4())
    pricing = LLMModelPricingUpdate(input_price_1k=0.1, output_price_1k=0.2)

    monkeypatch.setattr(
        llm_endpoint.TraceAccessService,
        "is_system_admin",
        staticmethod(lambda db, current_user: False),
    )
    monkeypatch.setattr(
        LLMService,
        "update_model_pricing",
        lambda *a, **k: pytest.fail("pricing update should require system admin"),
    )

    with pytest.raises(HTTPException) as exc_info:
        llm_endpoint.update_model_pricing(
            model_id=uuid.uuid4(),
            pricing=pricing,
            db=FakeDb(None),
            current_user=user,
        )

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "system_admin_required"


def test_register_credential_checks_organization_manager_before_remote_fetch(monkeypatch):
    organization_id = uuid.uuid4()
    provider = SimpleNamespace(id=uuid.uuid4(), name="openai", base_url="https://api.example")
    request = LLMCredentialCreate(
        provider_id=provider.id,
        organization_id=organization_id,
        credential_name="shared",
        api_key="sk-test",
    )

    monkeypatch.setattr(llm_service, "has_organization_manager_permission", lambda *a: False)
    monkeypatch.setattr(
        LLMService,
        "_fetch_remote_models",
        lambda *a, **k: pytest.fail("remote fetch should not run before permission check"),
    )

    with pytest.raises(PermissionError):
        LLMService.register_credential(FakeDb(provider), uuid.uuid4(), request)


def test_register_credential_flushes_default_organization_before_manager_check(
    monkeypatch,
):
    user_id = uuid.uuid4()
    provider = SimpleNamespace(
        id=uuid.uuid4(), name="openai", base_url="https://api.example"
    )
    request = LLMCredentialCreate(
        provider_id=provider.id,
        credential_name="first",
        api_key="sk-test",
    )
    db = FakeCredentialRegisterDb(provider)
    manager_check_flush_counts = []

    def has_manager_permission(db_arg, checked_user_id, organization_id):
        manager_check_flush_counts.append(db_arg.flush_count)
        assert checked_user_id == user_id
        return db_arg.flush_count > 0

    monkeypatch.setattr(
        llm_service,
        "has_organization_manager_permission",
        has_manager_permission,
    )
    monkeypatch.setattr(LLMService, "_fetch_remote_models", lambda *a, **k: [])
    monkeypatch.setattr(LLMService, "_sync_models_to_db", lambda *a, **k: [])
    monkeypatch.setattr(
        llm_service.LLMCredentialResponse,
        "model_validate",
        staticmethod(lambda credential: credential),
    )

    credential = LLMService.register_credential(db, user_id, request)

    assert manager_check_flush_counts == [1]
    assert credential.organization_id is not None
    assert db.committed is True


def test_get_user_credentials_filters_by_read_permission(monkeypatch):
    readable_id = uuid.uuid4()
    blocked_id = uuid.uuid4()
    credentials = [
        SimpleNamespace(id=readable_id),
        SimpleNamespace(id=blocked_id),
    ]
    seen_actions = []

    def can_read(db, user_id, credential_id, action):
        seen_actions.append(action)
        return credential_id == readable_id and action == "read"

    monkeypatch.setattr(llm_service, "has_llm_credential_permission", can_read)
    monkeypatch.setattr(
        llm_service.LLMCredentialResponse,
        "model_validate",
        staticmethod(lambda credential: credential),
    )

    result = LLMService.get_user_credentials(FakeDb(credentials), uuid.uuid4())

    assert result == [credentials[0]]
    assert seen_actions == ["read", "read"]


def test_get_my_available_models_filters_by_credential_use_permission(monkeypatch):
    allowed_credential_id = uuid.uuid4()
    blocked_credential_id = uuid.uuid4()
    shared_model = SimpleNamespace(id=uuid.uuid4(), name="Shared")
    blocked_model = SimpleNamespace(id=uuid.uuid4(), name="Blocked")
    rows = [
        (shared_model, blocked_credential_id),
        (shared_model, allowed_credential_id),
        (blocked_model, blocked_credential_id),
    ]
    seen_actions = []

    def can_use(db, user_id, credential_id, action):
        seen_actions.append(action)
        return credential_id == allowed_credential_id and action == "use"

    monkeypatch.setattr(llm_service, "has_llm_credential_permission", can_use)
    monkeypatch.setattr(
        llm_service.LLMModelResponse,
        "model_validate",
        staticmethod(lambda model: model),
    )

    result = LLMService.get_my_available_models(FakeDb(rows), uuid.uuid4())

    assert result == [shared_model]
    assert seen_actions == ["use", "use", "use"]


def test_wizard_runtime_uses_relation_priority_before_credential_created_at(
    monkeypatch,
):
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    provider = SimpleNamespace(id=uuid.uuid4(), name="openai")
    older_credential = SimpleNamespace(
        id=uuid.uuid4(),
        provider=provider,
        provider_id=provider.id,
        organization_id=organization_id,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        encrypted_config='{"apiKey": "older-key", "baseUrl": "https://older.example"}',
    )
    priority_credential = SimpleNamespace(
        id=uuid.uuid4(),
        provider=provider,
        provider_id=provider.id,
        organization_id=organization_id,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
        encrypted_config='{"apiKey": "priority-key", "baseUrl": "https://priority.example"}',
    )
    model = SimpleNamespace(
        id=uuid.uuid4(),
        provider_id=provider.id,
        model_id_for_api_call="gpt-4o-mini",
        is_active=True,
    )
    db = FakeWizardRuntimeDb(
        credentials=[older_credential, priority_credential],
        model=model,
        relations=[
            SimpleNamespace(priority=10),
            SimpleNamespace(priority=1),
        ],
    )
    client_configs = []

    monkeypatch.setattr(
        llm_service,
        "has_llm_credential_permission",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        llm_service,
        "get_llm_client",
        lambda **kwargs: client_configs.append(kwargs["credentials"])
        or SimpleNamespace(),
    )

    runtime = LLMService.get_wizard_client_for_user(
        db,
        user_id,
        {"openai": "gpt-4o-mini"},
        organization_id=organization_id,
        audit_on_failure=False,
    )

    assert runtime.credential_id == priority_credential.id
    assert client_configs == [
        {"apiKey": "priority-key", "baseUrl": "https://priority.example"}
    ]


def test_wizard_runtime_block_uses_unknown_target_without_credential(monkeypatch):
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    audit_calls = []

    monkeypatch.setattr(
        llm_service,
        "record_resource_permission_denied",
        lambda **kwargs: audit_calls.append(kwargs),
    )

    error = LLMCredentialNotAvailableError(
        "credential_not_available",
        "missing",
        model_id="gpt-4o-mini",
        organization_id=organization_id,
    )

    LLMService._record_wizard_runtime_block(  # noqa: SLF001 - MBA-43 audit helper
        user_id,
        error,
        "prompt_wizard",
    )

    assert audit_calls[0]["resource_type"] == "llm_credential"
    assert audit_calls[0]["resource_id"] == "unknown"
    assert audit_calls[0]["organization_id"] == organization_id
    assert audit_calls[0]["metadata"]["credential_id"] is None
    assert audit_calls[0]["metadata"]["model_id"] == "gpt-4o-mini"
    assert audit_calls[0]["metadata"]["reason"] == "credential_not_available"
