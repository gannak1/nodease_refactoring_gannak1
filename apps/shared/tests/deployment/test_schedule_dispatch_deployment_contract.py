from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]

SCHEDULE_ENV_NAMES = (
    "SCHEDULE_DISPATCH_MODE",
    "SCHEDULE_DISPATCH_MODE_FINGERPRINT",
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
    assert "nodease.io/schedule-dispatch-fingerprint:" in gateway
    assert "nodease.io/schedule-dispatch-fingerprint:" in worker
    assert 'define "moduly.scheduleDispatchFingerprint"' in helper
    assert (
        "metadata.annotations['nodease.io/schedule-dispatch-fingerprint']" in helper
    )


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
        assert 'nodease.io/schedule-dispatch-fingerprint: "v1|disabled|' in content
        assert (
            "metadata.annotations['nodease.io/schedule-dispatch-fingerprint']"
            in content
        )
        assert 'value: "disabled"' in content

    for env_name in SCHEDULE_ENV_NAMES:
        assert f"{env_name}:" in compose
        if env_name != "SCHEDULE_DISPATCH_MODE_FINGERPRINT":
            assert f"${{{env_name}:-" in compose
    assert 'SCHEDULE_DISPATCH_MODE_FINGERPRINT: "v1|' in compose
    assert "${SCHEDULE_DISPATCH_LEASE_SECONDS:-60}" in compose


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


def test_eks_worker_deploy_runs_migration_before_application_rollout():
    workflow = _read(".github/workflows/deploy-eks-worker.yml")
    migration = workflow.index("name: Run Alembic Migration")
    deployment = workflow.index("name: Apply deployment configuration")
    assert migration < deployment


def test_eks_gateway_and_worker_share_rollout_lock_and_fingerprint_preflight():
    gateway = _read(".github/workflows/deploy-eks-gateway.yml")
    worker = _read(".github/workflows/deploy-eks-worker.yml")

    for workflow in (gateway, worker):
        assert "group: production-schema-rollout" in workflow
        assert "name: Verify shared schedule dispatch fingerprint" in workflow
        assert "api-server worker" in workflow
        assert "require the coordinated rollout workflow" in workflow

    coordinated = _read(".github/workflows/deploy-eks-schedule-coordinated.yml")
    assert "group: production-schema-rollout" in coordinated
    assert "environment: production" in coordinated
    assert "name: Validate current and desired fingerprints" in coordinated
    assert "name: Run Alembic Migration" in coordinated
    assert "name: Render commit images and apply staged rollout" in coordinated
    assert "apiVersion: \"v1\"" in coordinated
    assert "github.run_attempt" in coordinated
    assert "trap cleanup_migration_pod EXIT" in coordinated
    assert "kubectl kustomize" in coordinated
    assert 'target_mode" == "claim"' in coordinated
    assert "previous_fingerprint:" in coordinated
    assert "apps.shared.domain.schedule_dispatch_rollout" in coordinated
    assert 'case "$schedule_rollout_action"' in coordinated
    assert "name: Check disabled rollback blockers" in coordinated
    assert "name: Check claim activation drain" in coordinated
    assert "check_schedule_dispatch_rollback.py" in coordinated
    assert coordinated.index("name: Run Alembic Migration") < coordinated.index(
        "name: Check claim activation drain"
    )
    assert coordinated.index("name: Run Alembic Migration") < coordinated.index(
        "name: Check disabled rollback blockers"
    )
    assert '"--purpose", "activation"' in coordinated
    assert '"--purpose", "rollback"' in coordinated
    assert '"$previous_mode" != "drain"' in coordinated
    assert "name: Verify both rollouts and fingerprints" in coordinated
