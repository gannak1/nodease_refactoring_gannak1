import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from apps.gateway.api.v1.endpoints import llm as llm_endpoint
from apps.gateway.services import llm_service
from apps.gateway.services.llm_service import LLMService
from apps.shared.db.models.user import User
from apps.shared.schemas.llm import LLMCredentialCreate, LLMModelPricingUpdate
from apps.shared.services.llm_errors import (
    LLMCredentialNotAvailableError,
    LLMCredentialPermissionDeniedError,
    LLMModelPolicyDeniedError,
)


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
    # Verifies delete endpoint preserves permission failures with scoped checks MBA-43
    credential_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    user = SimpleNamespace(id=uuid.uuid4())
    seen = {}

    def deny(db, current_user, checked_credential_id, action, organization_id=None):
        # Fakes a scoped credential permission denial MBA-43
        seen["action"] = action
        seen["organization_id"] = organization_id
        raise HTTPException(status_code=403, detail="Forbidden")

    monkeypatch.setattr(llm_endpoint, "ensure_llm_credential_permission", deny)
    monkeypatch.setattr(
        "apps.gateway.utils.audit.record_audit",
        lambda **kwargs: None,
    )

    with pytest.raises(HTTPException) as exc_info:
        llm_endpoint.delete_credential(
            credential_id, FakeDb(None), user, x_organization_id=organization_id
        )

    assert exc_info.value.status_code == 403
    assert seen["action"] == "write"
    assert seen["organization_id"] == organization_id


def test_resolve_llm_organization_id_rejects_header_body_mismatch():
    # Verifies LLM API organization header/body mismatch is rejected MBA-43
    with pytest.raises(HTTPException) as exc_info:
        llm_endpoint._resolve_llm_organization_id(
            db=object(),
            current_user=SimpleNamespace(id=uuid.uuid4()),
            x_organization_id=uuid.uuid4(),
            body_organization_id=uuid.uuid4(),
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "organization_id_mismatch"


def test_resolve_llm_organization_id_requires_explicit_scope():
    # Verifies LLM API no longer mutates default organization on missing scope MBA-43
    with pytest.raises(HTTPException) as exc_info:
        llm_endpoint._resolve_llm_organization_id(
            db=object(),
            current_user=SimpleNamespace(id=uuid.uuid4()),
            x_organization_id=None,
            body_organization_id=None,
        )

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "organization_id_required"


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
    # Verifies credential listing uses read permission in organization scope MBA-43
    readable_id = uuid.uuid4()
    blocked_id = uuid.uuid4()
    credentials = [
        SimpleNamespace(id=readable_id),
        SimpleNamespace(id=blocked_id),
    ]
    seen_actions = []

    def can_read(db, user_id, credential_id, action, organization_id=None):
        # Fakes scoped credential read permission checks MBA-43
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


def test_runtime_model_policy_uses_credential_org_when_scope_omitted(monkeypatch):
    # Verifies omitted runtime organization scope still applies credential-org model policy MBA-43
    user_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    credential = SimpleNamespace(id=uuid.uuid4(), organization_id=organization_id)
    seen = {}

    def can_use(db, checked_user_id, credential_id, action, organization_id=None):
        # Captures credential permission scope for omitted organization runtime calls MBA-43
        seen["permission_organization_id"] = organization_id
        assert checked_user_id == user_id
        assert credential_id == credential.id
        assert action == "use"
        return True

    def blocks_model(db, user_id, organization_id, model_id):
        # Captures model policy scope for omitted organization runtime calls MBA-43
        seen["policy_organization_id"] = organization_id
        seen["policy_model_id"] = model_id
        return True

    monkeypatch.setattr(llm_service, "has_llm_credential_permission", can_use)
    monkeypatch.setattr(
        LLMService,
        "_is_model_blocked_for_user",
        staticmethod(blocks_model),
    )

    result = LLMService._get_valid_credential_for_user(
        FakeDb([credential]),
        user_id=user_id,
        model_id_for_policy="gpt-5",
    )

    assert result is None
    assert seen == {
        "permission_organization_id": organization_id,
        "policy_organization_id": organization_id,
        "policy_model_id": "gpt-5",
    }


def test_runtime_credential_selection_raises_not_available_when_no_candidate():
    # Verifies runtime no-credential failures map to a not-found error MBA-43
    with pytest.raises(LLMCredentialNotAvailableError) as exc_info:
        LLMService._get_valid_credential_for_user(
            FakeDb([]),
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            model_id_for_policy="gpt-4o",
            raise_on_failure=True,
        )

    assert exc_info.value.status_code == 404


def test_runtime_credential_selection_raises_permission_denied(monkeypatch):
    # Verifies runtime permission failures map to a forbidden error MBA-43
    credential = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())

    monkeypatch.setattr(
        llm_service,
        "has_llm_credential_permission",
        lambda *args, **kwargs: False,
    )

    with pytest.raises(LLMCredentialPermissionDeniedError) as exc_info:
        LLMService._get_valid_credential_for_user(
            FakeDb([credential]),
            user_id=uuid.uuid4(),
            model_id_for_policy="gpt-4o",
            raise_on_failure=True,
        )

    assert exc_info.value.status_code == 403


def test_runtime_credential_selection_raises_model_policy_denied(monkeypatch):
    # Verifies runtime model policy failures map to a forbidden error MBA-43
    credential = SimpleNamespace(id=uuid.uuid4(), organization_id=uuid.uuid4())

    monkeypatch.setattr(
        llm_service,
        "has_llm_credential_permission",
        lambda *args, **kwargs: True,
    )
    monkeypatch.setattr(
        LLMService,
        "_is_model_blocked_for_user",
        staticmethod(lambda *args, **kwargs: True),
    )

    with pytest.raises(LLMModelPolicyDeniedError) as exc_info:
        LLMService._get_valid_credential_for_user(
            FakeDb([credential]),
            user_id=uuid.uuid4(),
            model_id_for_policy="gpt-5",
            raise_on_failure=True,
        )

    assert exc_info.value.status_code == 403


def test_get_my_available_models_returns_only_usable_models(monkeypatch):
    # Verifies model listing hides models without runtime use permission MBA-43
    allowed_credential_id = uuid.uuid4()
    blocked_credential_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    shared_model = SimpleNamespace(
        id=uuid.uuid4(), name="Shared", model_id_for_api_call="gpt-4o"
    )
    blocked_model = SimpleNamespace(
        id=uuid.uuid4(), name="Blocked", model_id_for_api_call="gpt-5"
    )
    rows = [
        (shared_model, blocked_credential_id, organization_id),
        (shared_model, allowed_credential_id, organization_id),
        (blocked_model, allowed_credential_id, organization_id),
    ]
    seen_actions = []
    seen_policy_models = []

    def can_access(db, user_id, credential_id, action, organization_id=None):
        # Fakes scoped model use permission checks MBA-43
        seen_actions.append(action)
        return credential_id == allowed_credential_id and action == "use"

    monkeypatch.setattr(llm_service, "has_llm_credential_permission", can_access)
    monkeypatch.setattr(
        LLMService,
        "_is_model_blocked_for_user",
        staticmethod(
            lambda db, user_id, organization_id, model_id: seen_policy_models.append(
                model_id
            )
            or model_id == "gpt-5"
        ),
    )
    monkeypatch.setattr(
        llm_service.LLMModelResponse,
        "model_validate",
        staticmethod(lambda model: model),
    )

    result = LLMService.get_my_available_models(FakeDb(rows), uuid.uuid4())

    assert result == [shared_model]
    assert shared_model.can_use is True
    assert not hasattr(blocked_model, "can_use")
    assert seen_actions == ["use", "use", "use"]
    assert seen_policy_models == ["gpt-4o", "gpt-5"]


def test_get_my_embedding_models_returns_only_usable_models(monkeypatch):
    # Verifies embedding model listing hides models without runtime use permission MBA-43
    allowed_credential_id = uuid.uuid4()
    blocked_credential_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    allowed_model = SimpleNamespace(
        id=uuid.uuid4(), name="Embedding", model_id_for_api_call="text-embedding-3"
    )
    blocked_model = SimpleNamespace(
        id=uuid.uuid4(), name="Blocked", model_id_for_api_call="blocked-embedding"
    )
    rows = [
        (allowed_model, allowed_credential_id, organization_id),
        (blocked_model, blocked_credential_id, organization_id),
    ]

    def can_access(db, user_id, credential_id, action, organization_id=None):
        # Fakes scoped embedding model use permission checks MBA-43
        return credential_id == allowed_credential_id and action == "use"

    monkeypatch.setattr(llm_service, "has_llm_credential_permission", can_access)
    monkeypatch.setattr(
        LLMService,
        "_is_model_blocked_for_user",
        staticmethod(lambda *args, **kwargs: False),
    )
    monkeypatch.setattr(
        llm_service.LLMModelResponse,
        "model_validate",
        staticmethod(lambda model: model),
    )

    result = LLMService.get_my_embedding_models(FakeDb(rows), uuid.uuid4())

    assert result == [allowed_model]
    assert allowed_model.can_use is True
    assert not hasattr(blocked_model, "can_use")
