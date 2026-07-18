"""Workflow Worker startup checks for external action credential use."""

from celery.signals import worker_init, worker_process_init

from apps.shared.services.external_action_credential import (
    require_external_action_credential_keyring_ready,
)


@worker_init.connect
def validate_external_action_credential_worker_readiness(**kwargs) -> None:
    """Reject a Worker before task consumption when the keyring is invalid."""
    require_external_action_credential_keyring_ready()


@worker_process_init.connect
def validate_external_action_credential_worker_process(**kwargs) -> None:
    """Recheck the keyring in each Worker child process."""
    require_external_action_credential_keyring_ready()
