import uuid
from types import SimpleNamespace

from apps.workflow_engine.services import llm_service
from apps.workflow_engine.services.llm_service import LLMService
from apps.shared.services.llm_errors import (
    LLMCredentialNotAvailableError,
    LLMModelPolicyDeniedError,
)


class FakeQuery:
    def __init__(self, value):
        self.value = value

    def join(self, *args, **kwargs):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return self.value


class FakeDb:
    def __init__(self, value):
        self.value = value

    def query(self, *args, **kwargs):
        return FakeQuery(self.value)


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
    # Verifies workflow runtime no-credential failures preserve not-found reason MBA-43
    try:
        LLMService._get_valid_credential_for_user(
            FakeDb([]),
            user_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            model_id_for_policy="gpt-4o",
            raise_on_failure=True,
        )
    except LLMCredentialNotAvailableError as exc:
        assert exc.status_code == 404
    else:
        raise AssertionError("expected LLMCredentialNotAvailableError")


def test_runtime_credential_selection_raises_model_policy_denied(monkeypatch):
    # Verifies workflow runtime model policy failures preserve forbidden reason MBA-43
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

    try:
        LLMService._get_valid_credential_for_user(
            FakeDb([credential]),
            user_id=uuid.uuid4(),
            model_id_for_policy="gpt-5",
            raise_on_failure=True,
        )
    except LLMModelPolicyDeniedError as exc:
        assert exc.status_code == 403
    else:
        raise AssertionError("expected LLMModelPolicyDeniedError")
