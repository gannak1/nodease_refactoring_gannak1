from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
SECURITY_KEYS = (
    "MEMORY_PUBLIC_CAPABILITY_HMAC_KEY",
    "MEMORY_PUBLIC_REPLAY_ENCRYPTION_KEY",
    "MEMORY_PUBLIC_ADMISSION_HMAC_KEY",
)


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def test_public_memory_is_explicitly_disabled_in_standard_deployment_defaults():
    compose = _read("docker/docker-compose.yml")
    values = _read("infra/helm/moduly/values.yaml")
    production_values = _read("infra/helm/moduly/values-production.yaml")
    raw_deployments = (
        _read("infra/k8s/namespaces/default/gateway-deployment.yaml"),
        _read("infra/k8s/namespaces/dev/gateway-deployment.yaml"),
    )

    assert "MEMORY_PUBLIC_CONVERSATION_ENABLED:-false" in compose
    assert "memoryPublicConversation:\n  enabled: false" in values
    assert "memoryPublicConversation:\n  enabled: false" in production_values
    for deployment in raw_deployments:
        assert "- name: MEMORY_PUBLIC_CONVERSATION_ENABLED\n              value: \"false\"" in deployment


def test_enabled_helm_and_compose_paths_wire_three_independent_secret_names():
    compose = _read("docker/docker-compose.yml")
    values = _read("infra/helm/moduly/values.yaml")
    secret_template = _read("infra/helm/moduly/templates/secrets.yaml")
    gateway_template = _read("infra/helm/moduly/templates/gateway-deployment.yaml")

    for key in SECURITY_KEYS:
        assert key in compose
        assert key in secret_template
        assert key in gateway_template
    for value_name in (
        "memoryPublicCapabilityHmacKey",
        "memoryPublicReplayEncryptionKey",
        "memoryPublicAdmissionHmacKey",
    ):
        assert f'{value_name}: ""' in values
        assert f"secrets.{value_name} is required" in secret_template
    assert "MEMORY_PUBLIC_REPLAY_BACKUP_ERASURE_MODE" in compose
    assert "MEMORY_PUBLIC_REPLAY_BACKUP_ERASURE_MODE" in gateway_template


def test_runtime_images_include_memory_and_helm_schedules_replay_retention():
    gateway_dockerfile = _read("docker/gateway/Dockerfile")
    logger_dockerfile = _read("docker/log_system/Dockerfile")
    values = _read("infra/helm/moduly/values.yaml")
    beat_template = _read("infra/helm/moduly/templates/beat-deployment.yaml")

    assert "COPY apps/memory /app/apps/memory" in gateway_dockerfile
    assert "COPY apps/memory /app/apps/memory" in logger_dockerfile
    assert "beat:\n  enabled: true" in values
    assert "default .Values.worker.image.repository" in beat_template
    assert "- apps.shared.celery_app:celery_app" in beat_template
    assert "- beat" in beat_template
