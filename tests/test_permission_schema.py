import pytest
from pydantic import ValidationError

from apps.shared.schemas.permission import (
    AuditPermissionGrantRequest,
    KnowledgePermissionGrantRequest,
    LLMPermissionGrantRequest,
    PermissionGrantRequest,
    WorkflowPermissionGrantRequest,
)


@pytest.mark.parametrize(
    "schema",
    [
        PermissionGrantRequest,
        WorkflowPermissionGrantRequest,
        KnowledgePermissionGrantRequest,
        LLMPermissionGrantRequest,
    ],
)
def test_resource_permission_grant_requests_accept_operational_matrix(schema):
    assert schema(auth_state="MANAGER").auth_state == "manager"


@pytest.mark.parametrize(
    "schema",
    [
        PermissionGrantRequest,
        WorkflowPermissionGrantRequest,
        KnowledgePermissionGrantRequest,
        LLMPermissionGrantRequest,
    ],
)
def test_operational_permission_grant_requests_reject_audit_states(schema):
    with pytest.raises(ValidationError):
        schema(auth_state="raw_auditor")


def test_audit_permission_grant_request_accepts_audit_matrix():
    assert AuditPermissionGrantRequest(auth_state="RAW_AUDITOR").auth_state == (
        "raw_auditor"
    )


def test_audit_permission_grant_request_rejects_operational_states():
    with pytest.raises(ValidationError):
        AuditPermissionGrantRequest(auth_state="builder")
