from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

SCHEDULE_ENV_NAMES = (
    "SCHEDULE_DISPATCH_MODE",
    "SCHEDULE_DISPATCH_POLL_SECONDS",
    "SCHEDULE_OCCURRENCE_BATCH_SIZE",
    "SCHEDULE_DISPATCH_BATCH_SIZE",
    "SCHEDULE_RECOVERY_BATCH_SIZE",
    "SCHEDULE_CLEANUP_BATCH_SIZE",
    "SCHEDULE_DISPATCH_LEASE_SECONDS",
    "SCHEDULE_ENQUEUED_DELIVERY_TIMEOUT_SECONDS",
    "SCHEDULE_EXECUTION_DEADLINE_SECONDS",
    "SCHEDULE_WORKFLOW_RUN_VISIBILITY_TIMEOUT_SECONDS",
    "SCHEDULE_DISPATCH_MAX_ATTEMPTS",
    "SCHEDULE_DISPATCH_RETRY_BASE_SECONDS",
    "SCHEDULE_DISPATCH_RETENTION_DAYS",
    "SCHEDULE_DISPATCH_DEAD_LETTER_RETENTION_DAYS",
)


def _read(relative_path: str) -> str:
    return (REPOSITORY_ROOT / relative_path).read_text(encoding="utf-8")


def test_helm_values_explicitly_start_schedule_dispatch_disabled():
    for relative_path in (
        "infra/helm/moduly/values.yaml",
        "infra/helm/moduly/values-local.yaml",
        "infra/helm/moduly/values-production.yaml",
    ):
        content = _read(relative_path)
        assert "scheduleDispatch:" in content
        assert 'mode: "disabled"' in content


def test_helm_gateway_and_worker_use_one_schedule_dispatch_environment_contract():
    helper = _read("infra/helm/moduly/templates/_helpers.tpl")
    gateway = _read("infra/helm/moduly/templates/gateway-deployment.yaml")
    worker = _read("infra/helm/moduly/templates/worker-deployment.yaml")

    for env_name in SCHEDULE_ENV_NAMES:
        assert f"- name: {env_name}" in helper
    assert 'include "moduly.scheduleDispatchEnv"' in gateway
    assert 'include "moduly.scheduleDispatchEnv"' in worker


def test_raw_manifests_and_compose_keep_gateway_worker_schedule_settings_aligned():
    deployment_paths = (
        "infra/k8s/namespaces/default/gateway-deployment.yaml",
        "infra/k8s/namespaces/default/worker-deployment.yaml",
        "infra/k8s/namespaces/dev/gateway-deployment.yaml",
        "infra/k8s/namespaces/dev/worker-deployment.yaml",
    )
    compose = _read("docker/docker-compose.yml")

    for relative_path in deployment_paths:
        content = _read(relative_path)
        for env_name in SCHEDULE_ENV_NAMES:
            assert f"- name: {env_name}" in content
        assert 'value: "disabled"' in content

    for env_name in SCHEDULE_ENV_NAMES:
        assert f"{env_name}:" in compose
        assert f"${{{env_name}:-" in compose


def test_dev_deploy_runs_migration_before_application_rollout():
    workflow = _read(".github/workflows/deploy-dev-namespace.yml")
    migration = workflow.index("name: Run Alembic Migration")
    deployment = workflow.index("name: Deploy to dev namespace")
    assert migration < deployment


def test_eks_gateway_deploy_runs_migration_before_application_rollout():
    workflow = _read(".github/workflows/deploy-eks-gateway.yml")
    migration = workflow.index("name: Run Alembic Migration")
    deployment = workflow.index("name: Apply deployment configuration")
    assert migration < deployment
