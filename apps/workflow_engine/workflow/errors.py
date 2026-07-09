"""Workflow runtime exception types."""


class NonRetryableWorkflowError(ValueError):
    """Workflow execution error that should fail immediately without Celery retry."""


class WorkflowNodeConfigurationError(NonRetryableWorkflowError):
    """Invalid workflow-node target, depth, or recursion configuration."""
