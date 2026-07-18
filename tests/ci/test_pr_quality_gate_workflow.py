from pathlib import Path
import re


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
QUALITY_GATE_PATH = REPOSITORY_ROOT / ".github" / "workflows" / "pr-quality-gate.yml"
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
    r"^\s*uses:\s+(?P<action>[^@\s]+)@(?P<reference>[^\s#]+)"
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
