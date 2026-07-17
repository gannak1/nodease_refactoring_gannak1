from pathlib import Path

import pytest

from apps.gateway import knowledge_worker


ROOT = Path(__file__).parents[4]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_compose_worker_uses_gateway_image_and_only_knowledge_queue() -> None:
    compose = _read("docker/docker-compose.yml")
    section = compose.split("  knowledge_worker:", 1)[1].split(
        "  # Workflow Engine", 1
    )[0]

    assert "docker/gateway/Dockerfile" in section
    assert "apps.gateway.knowledge_worker:app" in section
    assert "--queues=knowledge" in section
    assert "--concurrency=2" in section
    assert "uvicorn" not in section
    assert "disable: true" in section
    assert "gateway:\n        condition: service_healthy" in section


def test_helm_worker_is_migration_first_and_has_bounded_concurrency() -> None:
    template = _read(
        "infra/helm/moduly/templates/knowledge-worker-deployment.yaml"
    )
    gateway_template = _read("infra/helm/moduly/templates/gateway-deployment.yaml")
    storage_template = _read(
        "infra/helm/moduly/templates/knowledge-storage-pvc.yaml"
    )
    values = _read("infra/helm/moduly/values.yaml")
    production = _read("infra/helm/moduly/values-production.yaml")
    local = _read("infra/helm/moduly/values-local.yaml")

    assert ".Values.knowledgeWorker.enabled" in template
    assert ".Values.gateway.image.repository" in template
    assert "apps.gateway.knowledge_worker:app" in template
    assert "--queues=knowledge" in template
    assert "--concurrency={{ .Values.knowledgeWorker.concurrency }}" in template
    assert "initContainers:" in template
    assert "apps.gateway.knowledge_worker_readiness" in template
    assert "claimName: {{ include \"moduly.knowledgeUploadClaimName\" . }}" in template
    assert "mountPath: /app/uploads" in template
    assert "mountPath: /app/uploads" in gateway_template
    assert "fsGroup: {{ .Values.knowledgeWorker.localStorage.fsGroup }}" in template
    assert (
        "fsGroup: {{ .Values.knowledgeWorker.localStorage.fsGroup }}"
        in gateway_template
    )
    assert "kind: PersistentVolumeClaim" in storage_template
    assert "knowledgeWorker:\n  enabled: false" in values
    assert "knowledgeWorker:\n  enabled: false" in production
    assert "knowledgeWorker:\n  enabled: true" in local
    assert "localStorage:\n    enabled: true" in local


def test_shared_celery_routes_and_recovers_knowledge_jobs() -> None:
    celery_source = _read("apps/shared/celery_app.py")
    worker_source = _read("apps/gateway/knowledge_worker.py")

    assert '"knowledge.*": {"queue": "knowledge"}' in celery_source
    assert '"task": "knowledge.document_ingestion.recover"' in celery_source
    assert 'os.environ.setdefault("CELERY_WORKER_ROLE", "knowledge")' in worker_source
    assert "require_knowledge_document_ingestion_ready" in worker_source


def test_worker_readiness_bootstep_propagates_startup_failure(monkeypatch) -> None:
    def fail_readiness() -> None:
        raise RuntimeError("safe readiness failure")

    monkeypatch.setattr(knowledge_worker, "_require_readiness", fail_readiness)

    with pytest.raises(RuntimeError, match="safe readiness failure"):
        step = knowledge_worker.KnowledgeSchemaReadinessStep(parent=object())
        step.start(object())
