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
    assert 'define "moduly.validateScheduleDispatchMode"' in helper
    assert (
        "non-disabled schedule dispatch requires the coordinated rollout workflow"
        in helper
    )
    assert 'include "moduly.validateScheduleDispatchMode"' in gateway
    assert 'include "moduly.validateScheduleDispatchMode"' in worker
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
    assert "name: Reject non-coordinated schedule mode transitions" in workflow
    assert (
        "Non-disabled schedule mode requires the coordinated rollout workflow."
        in workflow
    )
    assert "query_live_schedule_state api-server" in workflow
    assert "query_live_schedule_state worker" in workflow
    assert "Live claim/drain schedule mode requires" in workflow
    assert "A partial service deployment cannot bootstrap only one" in workflow
    assert (
        "A disabled schedule settings change must deploy Gateway and Worker together."
        in workflow
    )
    assert "Selected services do not change schedule dispatch components." in workflow
    assert (
        "kubectl rollout status deployment/api-server -n dev --timeout=5m || true"
        not in workflow
    )
    assert (
        "kubectl rollout status deployment/worker -n dev --timeout=5m || true"
        not in workflow
    )


def test_dev_schedule_guard_requires_live_gateway_and_worker_pod_convergence():
    workflow = _read(".github/workflows/deploy-dev-namespace.yml")

    assert "query_live_schedule_state()" in workflow
    assert 'state=$(kubectl get deployment "$deployment"' in workflow
    assert "observedGeneration" in workflow
    assert "updatedReplicas" in workflow
    assert "readyReplicas" in workflow
    assert "availableReplicas" in workflow
    assert "unavailableReplicas" in workflow
    assert 'kubectl get pods \\' in workflow
    assert '-n "$NAMESPACE" \\' in workflow
    assert '-l app="$deployment" \\' in workflow
    assert "select(.metadata.deletionTimestamp == null)" in workflow
    assert '.status.phase == "Running"' in workflow
    assert '.type == "Ready" and .status == "True"' in workflow
    assert (
        '.metadata.annotations["nodease.io/schedule-dispatch-fingerprint"] '
        "== $fingerprint"
    ) in workflow
    assert '"$generation" != "$observed_generation"' in workflow
    assert '"$updated_replicas" != "$desired_replicas"' in workflow
    assert '"$ready_replicas" != "$desired_replicas"' in workflow
    assert '"$available_replicas" != "$desired_replicas"' in workflow
    assert '"$unavailable_replicas" != "0"' in workflow
    assert '"$desired_replicas" == "0"' in workflow
    assert '"$pod_count" != "$desired_replicas"' in workflow
    assert '"$pods_converged" != "true"' in workflow
    assert "A live schedule dispatch deployment is not fully converged." in workflow


def test_dev_schedule_guard_preserves_safe_service_selection_contract():
    workflow = _read(".github/workflows/deploy-dev-namespace.yml")

    unrelated_exit = workflow.index(
        "Selected services do not change schedule dispatch components."
    )
    desired_fingerprint = workflow.index("gateway_desired=$(sed")
    gateway_query = workflow.index("query_live_schedule_state api-server")
    worker_query = workflow.index("query_live_schedule_state worker")
    assert unrelated_exit < desired_fingerprint < gateway_query < worker_query
    assert '"$gateway_live_exists" == "false"' in workflow
    assert '"$worker_live_exists" == "false"' in workflow
    assert '"$deploy_gateway" != "$deploy_worker"' in workflow
    assert '"$gateway_live_exists" != "true"' in workflow
    assert '"$worker_live_exists" != "true"' in workflow
    assert '"$gateway_live" != "$worker_live"' in workflow
    assert '"$live_mode" == "claim" || "$live_mode" == "drain"' in workflow
    assert '"$live_mode" != "disabled"' in workflow
    assert (
        '( "$deploy_gateway" != "true" || "$deploy_worker" != "true" )'
        in workflow
    )


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
    logger = _read(".github/workflows/deploy-eks-logger.yml")

    for workflow in (gateway, worker):
        assert "group: production-schema-rollout" in workflow
        assert "name: Verify shared schedule dispatch fingerprint" in workflow
        assert "api-server worker" in workflow
        missing_annotation = workflow.index('if [[ -z "$current" ]]')
        bootstrap_guard = workflow.index(
            '"$desired" == v1\\|disabled\\|*', missing_annotation
        )
        missing_error = workflow.index(
            "Schedule dispatch fingerprint is missing", missing_annotation
        )
        assert bootstrap_guard < missing_error
        assert "require the coordinated rollout workflow" in workflow
    assert "group: production-schema-rollout" in logger
    assert "cancel-in-progress: false" in logger

    coordinated = _read(".github/workflows/deploy-eks-schedule-coordinated.yml")
    assert "group: production-schema-rollout" in coordinated
    assert "environment: production" in coordinated
    assert "name: Validate current and desired fingerprints" in coordinated
    assert "Build or reuse Gateway, Worker, and Logger images" in coordinated
    assert "docker/log_system/Dockerfile" in coordinated
    assert "aws ecr describe-images" in coordinated
    assert '--image-ids imageTag="$IMAGE_TAG"' in coordinated
    assert 'if digest=$(lookup_ecr_digest "$repository_name")' in coordinated
    assert 'docker build -t "$tagged_image"' in coordinated
    assert 'gateway_image="$gateway_repository@$gateway_digest"' in coordinated
    assert 'worker_image="$worker_repository@$worker_digest"' in coordinated
    assert 'logger_image="$logger_repository@$logger_digest"' in coordinated
    assert "name: Run Alembic Migration" in coordinated
    assert "name: Render immutable deployment manifests" in coordinated
    assert "name: Apply and verify Logger prerequisite" in coordinated
    assert "name: Check final schedule ledger and transition drain" in coordinated
    assert "name: Apply staged Gateway and Worker rollout" in coordinated
    assert "apiVersion: \"v1\"" in coordinated
    assert "github.run_attempt" in coordinated
    assert "trap cleanup_migration_pod EXIT" in coordinated
    assert "kubectl kustomize" in coordinated
    assert "digest: $gateway_digest" in coordinated
    assert "digest: $worker_digest" in coordinated
    assert "digest: $logger_digest" in coordinated
    assert "/tmp/logger-rendered.yaml" in coordinated
    assert "apply_logger_and_verify" in coordinated
    logger_rollout = coordinated.index("name: Apply and verify Logger prerequisite")
    final_drain = coordinated.index(
        "name: Check final schedule ledger and transition drain"
    )
    staged_apply = coordinated.index("name: Apply staged Gateway and Worker rollout")
    assert coordinated.index("name: Run Alembic Migration") < logger_rollout
    assert logger_rollout < final_drain < staged_apply
    missing_annotation = coordinated.index('if [[ -z "$live_fingerprint" ]]')
    bootstrap_guard = coordinated.index(
        '"$gateway_desired" == v1\\|disabled\\|*', missing_annotation
    )
    missing_error = coordinated.index(
        "A live deployment is missing rollout identity", missing_annotation
    )
    assert bootstrap_guard < missing_error
    assert 'target_mode" == "claim"' in coordinated
    assert "previous_fingerprint:" in coordinated
    assert "python -S apps/shared/domain/schedule_dispatch_rollout.py" in coordinated
    assert "python -m apps.shared.domain.schedule_dispatch_rollout" not in coordinated
    assert '--gateway-ready "$gateway_current_ready"' in coordinated
    assert '--worker-ready "$worker_current_ready"' in coordinated
    assert 'case "$schedule_rollout_action"' in coordinated
    assert "check_schedule_dispatch_rollback.py" in coordinated
    transition_preflight = _read("scripts/check_schedule_dispatch_rollback.py")
    assert 'if args.purpose == "rollback":' not in transition_preflight
    assert "blockers = ScheduleRollbackPreflightUseCase().evaluate(" in transition_preflight
    assert "preflight_purpose=activation" in coordinated
    assert "preflight_purpose=rollback" in coordinated
    assert '"--purpose", $purpose' in coordinated
    assert '"--expected-worker-nodes", $expectedWorkers' in coordinated
    assert '"--stable-observations", "2"' in coordinated
    assert "Transition drain requires the complete Ready Worker set." in coordinated
    assert '"$previous_mode" != "drain"' in coordinated
    assert "name: Verify Logger, Gateway, and Worker convergence" in coordinated
    assert 'kubectl rollout status deployment/"$deployment"' in coordinated
    assert "observedGeneration" in coordinated
    assert "readyReplicas" in coordinated
    assert 'kubectl get pods -l app="$deployment" -o json' in coordinated
    assert ".status.containerStatuses" in coordinated
    assert ".imageID" in coordinated
    assert (
        "[.items[] | select(.metadata.deletionTimestamp == null)] as $pods"
        in coordinated
    )
    assert "pods_converged" in coordinated
    assert coordinated.count('verify_converged logger "$logger_image"') >= 2
