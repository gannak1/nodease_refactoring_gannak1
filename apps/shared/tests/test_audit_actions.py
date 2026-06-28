from apps.shared.audit.actions import AuditAction


def test_mba_44_canonical_audit_actions_are_defined():
    assert AuditAction.WORKFLOW_EXECUTE == "workflow.execute"
    assert AuditAction.PERMISSION_DENIED == "permission.denied"
    assert AuditAction.LLM_CALL == "llm.call"
    assert AuditAction.DEPLOYMENT_ACTIVATE_PREVIOUS == "deployment.activate_previous"
