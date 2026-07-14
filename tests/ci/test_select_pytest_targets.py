from pathlib import Path
import subprocess
import sys

import pytest

from scripts.ci.select_pytest_targets import select_pytest_targets


def _write(repo: Path, relative: str) -> None:
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")


def test_selector_module_entrypoint_is_runnable():
    repo_root = Path(__file__).resolve().parents[2]

    completed = subprocess.run(
        [sys.executable, "-m", "scripts.ci.select_pytest_targets", "--help"],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_selects_changed_test_file_directly(tmp_path: Path):
    target = "apps/gateway/tests/services/test_mail_credential_service.py"
    _write(tmp_path, target)
    _write(tmp_path, "apps/gateway/tests/architecture/test_boundaries.py")

    assert select_pytest_targets("gateway", [target], tmp_path) == [
        "apps/gateway/tests/architecture",
        target,
    ]


def test_selects_feature_tests_by_source_name(tmp_path: Path):
    target = "apps/gateway/tests/services/test_organization_member_service.py"
    _write(tmp_path, target)
    _write(tmp_path, "apps/gateway/tests/architecture/test_boundaries.py")

    assert select_pytest_targets(
        "gateway",
        ["apps/shared/schemas/organization_membership.py"],
        tmp_path,
    ) == ["apps/gateway/tests/architecture", target]


def test_falls_back_to_component_layer_when_no_feature_test_exists(tmp_path: Path):
    _write(tmp_path, "apps/gateway/tests/services/test_existing_service.py")
    _write(tmp_path, "apps/gateway/tests/architecture/test_boundaries.py")

    assert select_pytest_targets(
        "gateway",
        ["apps/gateway/services/new_capability.py"],
        tmp_path,
    ) == [
        "apps/gateway/tests/architecture",
        "apps/gateway/tests/services",
    ]


def test_broad_mode_uses_smoke_targets_instead_of_full_service_suite(tmp_path: Path):
    _write(
        tmp_path,
        "apps/gateway/tests/architecture/test_access_management_import_boundaries.py",
    )
    _write(tmp_path, "apps/gateway/tests/services/test_large_suite.py")

    assert select_pytest_targets(
        "gateway",
        ["scripts/ci/changed_scope.py"],
        tmp_path,
        broad=True,
    ) == ["apps/gateway/tests/architecture"]


def test_shared_schema_without_direct_match_uses_schema_test_group(tmp_path: Path):
    _write(tmp_path, "apps/shared/tests/test_rag_schema.py")
    _write(tmp_path, "apps/shared/tests/services/test_permissions.py")

    assert select_pytest_targets(
        "shared",
        ["apps/shared/schemas/new_contract.py"],
        tmp_path,
    ) == ["apps/shared/tests/test_rag_schema.py"]


def test_root_selector_excludes_evaluation_and_load_tests(tmp_path: Path):
    _write(tmp_path, "tests/ci/test_changed_scope.py")
    _write(tmp_path, "tests/evaluation/test_rag_baseline.py")
    _write(tmp_path, "tests/load/test_load_runtime.py")

    assert select_pytest_targets(
        "root",
        [
            "tests/ci/test_changed_scope.py",
            "tests/evaluation/test_rag_baseline.py",
            "tests/load/test_load_runtime.py",
        ],
        tmp_path,
    ) == ["tests/ci/test_changed_scope.py"]


def test_rejects_unknown_component(tmp_path: Path):
    with pytest.raises(ValueError, match="unsupported component"):
        select_pytest_targets("unknown", [], tmp_path)
