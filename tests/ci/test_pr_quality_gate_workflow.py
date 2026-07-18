from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
QUALITY_GATE_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "pr-quality-gate.yml"
HELM_CI_VALUES_PATH = (
    REPOSITORY_ROOT / "tests" / "ci" / "fixtures" / "helm-values-ci.yaml"
)
TERRAFORM_CI_FIXTURE_PATH = (
    REPOSITORY_ROOT / "tests" / "ci" / "fixtures" / "terraform-smoke" / "main.tf"
)
KNOWLEDGE_POSTGRES_PATH = (
    REPOSITORY_ROOT
    / ".github"
    / "workflows"
    / "test-knowledge-runtime-postgres.yml"
)
PROTECTED_CI_WORKFLOWS = (
    QUALITY_GATE_PATH,
    REPOSITORY_ROOT / ".github" / "workflows" / "pr-ci-control-guard.yml",
    KNOWLEDGE_POSTGRES_PATH,
    REPOSITORY_ROOT / ".github" / "workflows" / "test-schedule-dispatch-postgres.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "test-agent-builder-postgres.yml",
    REPOSITORY_ROOT / ".github" / "workflows" / "test-memory-postgres.yml",
)
EXTERNAL_ACTION_PATTERN = re.compile(
    r"^\s*(?:-\s*)?uses:\s+(?P<action>[^@\s]+)@(?P<reference>[^\s#]+)"
)


def test_deployment_validation_is_fail_closed_in_required_gate():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")

    assert "      deployment_validation:" in workflow
    assert "  deployment_validation:" in workflow
    assert "    name: deployment-config-validation" in workflow
    assert "      - deployment_validation" in workflow
    assert (
        '--conditional "deployment-validation=${{ '
        "needs.scope.outputs.deployment_validation }}=${{ "
        'needs.deployment_validation.result }}"'
    ) in workflow


def test_actionlint_validates_only_changed_workflow_files():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")

    assert 'git diff --name-only --diff-filter=ACMR "$BASE_SHA" "$HEAD_SHA"' in workflow
    assert "'.github/workflows/*.yml'" in workflow
    assert "'.github/workflows/*.yaml'" in workflow
    assert 'actionlint@v1.7.12 "${workflow_files[@]}"' in workflow


def test_action_reference_matcher_supports_sequence_item_syntax():
    mapping_match = EXTERNAL_ACTION_PATTERN.match(
        "      uses: actions/checkout@v4"
    )
    sequence_match = EXTERNAL_ACTION_PATTERN.match(
        "      - uses: actions/checkout@v4"
    )

    assert mapping_match is not None
    assert sequence_match is not None
    assert sequence_match.group("reference") == "v4"


def test_ci_control_changes_force_all_deployment_validators():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")
    ci_control_block = workflow.split(
        'if [[ "$CI_CONTROL_CHANGED" == "true" ]]; then',
        maxsplit=1,
    )[1].split("exit 0", maxsplit=1)[0]

    for validator in (
        "actions_validation",
        "helm_validation",
        "kubernetes_validation",
        "terraform_validation",
        "compose_validation",
        "dockerfile_validation",
    ):
        assert f"emit_boolean {validator} true" in ci_control_block


def test_ci_control_smoke_uses_protected_actionlint_and_all_dockerfile_targets():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")
    actionlint_block = workflow.split(
        "- name: Validate GitHub Actions workflows",
        maxsplit=1,
    )[1].split("- name: Set up Helm", maxsplit=1)[0]

    assert "ci_control_changed: ${{ steps.ci_control.outputs.changed }}" in workflow
    assert "CI_CONTROL_CHANGED: ${{ needs.scope.outputs.ci_control_changed }}" in workflow
    for workflow_path in PROTECTED_CI_WORKFLOWS:
        relative = workflow_path.relative_to(REPOSITORY_ROOT).as_posix()
        assert relative in actionlint_block
    assert "git ls-files -z -- '.github/workflows/*.yml'" not in actionlint_block
    assert "git ls-files -z -- ':(glob)**/Dockerfile'" in workflow


def test_compose_validation_combines_variant_with_base_file():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")

    assert "docker-compose.*.yml|docker-compose.*.yaml" in workflow
    assert (
        'docker compose --profile "*" --file "$base_path" --file "$path" '
        "config --quiet"
        in workflow
    )


def test_kubernetes_validation_uses_cluster_independent_schema_check():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")

    assert (
        "go run github.com/yannh/kubeconform/cmd/kubeconform@v0.7.0"
        in workflow
    )
    assert "kubeconform/cmd/kubeconform@v0.8.0" not in workflow
    assert "-kubernetes-version 1.31.0" in workflow
    assert "kubectl create --dry-run=client" not in workflow


def test_ci_control_terraform_smoke_uses_fixture_without_hiding_real_changes():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")

    assert TERRAFORM_CI_FIXTURE_PATH.is_file()
    assert (
        "terraform_config_changed: "
        "${{ steps.classify.outputs.terraform_config_changed }}"
        in workflow
    )
    assert (
        "TERRAFORM_CONFIG_CHANGED: "
        "${{ needs.scope.outputs.terraform_config_changed }}"
        in workflow
    )
    assert 'terraform_target="infra/terraform"' in workflow
    assert 'terraform_target="tests/ci/fixtures/terraform-smoke"' in workflow


def test_helm_validation_registers_chart_dependency_repositories():
    workflow = QUALITY_GATE_PATH.read_text(encoding="utf-8")

    assert "helm repo add bitnami https://charts.bitnami.com/bitnami" in workflow
    assert (
        "helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx"
        in workflow
    )
    assert workflow.index("helm repo add bitnami") < workflow.index(
        "helm dependency build infra/helm/moduly"
    )


def test_helm_static_render_fixture_uses_non_routable_database_host():
    values = HELM_CI_VALUES_PATH.read_text(encoding="utf-8")

    assert 'externalHost: "postgresql.ci.invalid"' in values


def test_knowledge_postgres_workflow_runs_durable_ingestion_contract():
    workflow = KNOWLEDGE_POSTGRES_PATH.read_text(encoding="utf-8")

    assert 'NODEASE_RUN_DISPOSABLE_DB_TEST: "1"' in workflow
    assert (
        "apps/gateway/tests/adapters/db/"
        "test_knowledge_document_ingestion_repository_postgres.py"
    ) in workflow
    assert ".venv-ci-knowledge-ingestion/bin/python -m pytest" in workflow
    assert '-e "apps/gateway[dev]"' in workflow


def test_protected_ci_workflows_pin_external_actions_to_commit_shas():
    violations: list[str] = []

    for workflow_path in PROTECTED_CI_WORKFLOWS:
        for line_number, line in enumerate(
            workflow_path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            match = EXTERNAL_ACTION_PATTERN.match(line)
            if match is None:
                continue
            reference = match.group("reference")
            if re.fullmatch(r"[0-9a-f]{40}", reference) is None:
                relative = workflow_path.relative_to(REPOSITORY_ROOT).as_posix()
                violations.append(
                    f"{relative}:{line_number} uses mutable reference {reference}"
                )

    assert violations == []
