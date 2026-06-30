from apps.shared.audit.actions import AuditAction


def test_mba_44_canonical_audit_actions_are_defined():
    assert AuditAction.WORKFLOW_EXECUTE == "workflow.execute"
    assert AuditAction.PERMISSION_DENIED == "permission.denied"
    assert AuditAction.LLM_CALL == "llm.call"
    assert AuditAction.RAG_RETRIEVE == "rag.retrieve"
    assert AuditAction.POLICY_WARN == "policy.warn"
    assert AuditAction.POLICY_BLOCK == "policy.block"
    assert AuditAction.DEPLOYMENT_ACTIVATE_PREVIOUS == "deployment.activate_previous"


def test_organization_membership_audit_actions_are_defined():
    assert AuditAction.ORGANIZATION_INVITE == "organization.invite"
    assert AuditAction.ORGANIZATION_MEMBER_ACCEPT == "organization.member.accept"
    assert AuditAction.ORGANIZATION_MEMBER_UPDATE == "organization.member.update"
    assert AuditAction.ORGANIZATION_MEMBER_REMOVE == "organization.member.remove"
