from __future__ import annotations

import argparse
import fnmatch
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


_SHA_PATTERN = re.compile(r"^[0-9a-fA-F]{7,64}$")

_KNOWLEDGE_POSTGRES_PATTERNS = (
    "apps/shared/domain/knowledge_runtime_candidates.py",
    "apps/shared/services/knowledge_permission_service.py",
    "apps/shared/tests/db/test_knowledge_runtime_snapshot_disposable_postgres.py",
    "apps/shared/tests/domain/test_knowledge_runtime_candidates.py",
    "apps/shared/tests/services/test_knowledge_permission_runtime_bulk.py",
    "apps/workflow_engine/adapters/knowledge_runtime_candidates.py",
    "apps/workflow_engine/application/runtime_retrieval/**",
    "apps/workflow_engine/composition/runtime_retrieval.py",
    "apps/workflow_engine/tests/adapters/test_postgres_knowledge_runtime_candidate_adapter.py",
    ".github/workflows/test-knowledge-runtime-postgres.yml",
)

_WORKFLOW_POSTGRES_PATTERNS = (
    "apps/gateway/adapters/db/schedule_dispatch_repository.py",
    "apps/gateway/adapters/audit/sqlalchemy_schedule_dispatch_audit.py",
    "apps/gateway/application/deployment/schedule_occurrence.py",
    "apps/gateway/application/deployment/schedule_dispatch.py",
    "apps/gateway/services/scheduler_service.py",
    "apps/shared/alembic/**",
    "apps/shared/celery_app.py",
    "apps/shared/db/models/workflow_node_effect_attempt.py",
    "apps/shared/db/models/schedule_dispatch.py",
    "apps/shared/domain/schedule_dispatch.py",
    "apps/shared/services/schedule_dispatch_*.py",
    "apps/shared/tests/db/test_schedule_dispatch_disposable_postgres.py",
    "apps/shared/tests/db/test_external_effect_disposable_postgres.py",
    "apps/workflow_engine/adapters/db/external_effect_repository.py",
    "apps/workflow_engine/application/external_effect.py",
    "apps/workflow_engine/composition/external_effect_readiness.py",
    "apps/workflow_engine/adapters/schedule_dispatch_repository.py",
    "apps/workflow_engine/adapters/schedule_dispatch_audit.py",
    "apps/workflow_engine/application/schedule_dispatch.py",
    "apps/workflow_engine/tasks.py",
    "scripts/check_schedule_dispatch_rollback.py",
    ".github/workflows/deploy-eks-schedule-coordinated.yml",
    ".github/workflows/test-schedule-dispatch-postgres.yml",
)

_DOCUMENTATION_ROOT_FILES = {
    "AGENTS.md",
    "CONTRIBUTING.md",
    "README.md",
}

_DEPLOYMENT_ONLY_PREFIXES = (
    "dev/",
    "docker/",
    "infra/",
)

_DEPLOYMENT_ONLY_WORKFLOWS = (
    ".github/workflows/deploy-",
    ".github/workflows/publish-images.yml",
)


@dataclass
class ChangeScope:
    docs_only: bool = False
    python_lint: bool = False
    client: bool = False
    gateway_tests: bool = False
    workflow_tests: bool = False
    shared_tests: bool = False
    log_tests: bool = False
    sandbox_tests: bool = False
    root_tests: bool = False
    knowledge_postgres: bool = False
    workflow_postgres: bool = False
    broad_python: bool = False

    def enable_python_smoke(self) -> None:
        self.gateway_tests = True
        self.workflow_tests = True
        self.shared_tests = True
        self.log_tests = True
        self.sandbox_tests = True
        self.root_tests = True
        self.broad_python = True

    def github_outputs(self) -> dict[str, str]:
        outputs = {
            name: "true" if value else "false"
            for name, value in asdict(self).items()
        }
        outputs["gateway_job"] = (
            "true" if self.gateway_tests or self.root_tests else "false"
        )
        return outputs


def normalize_repo_path(raw_path: str) -> str:
    candidate = raw_path.replace("\\", "/")
    if candidate.startswith("/") or re.match(r"^[a-zA-Z]:/", candidate):
        raise ValueError(f"repository path must be relative: {raw_path!r}")
    normalized = candidate.strip("/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or ".." in path.parts:
        raise ValueError(f"invalid repository path: {raw_path!r}")
    return path.as_posix()


def parse_name_status_z(raw: bytes) -> list[str]:
    tokens = raw.decode("utf-8").split("\0")
    if tokens and not tokens[-1]:
        tokens.pop()

    paths: list[str] = []
    index = 0
    while index < len(tokens):
        status = tokens[index]
        index += 1
        if not status:
            raise ValueError("git diff returned an empty status")

        if status[0] in {"R", "C"}:
            if index + 1 >= len(tokens):
                raise ValueError(f"git diff returned an incomplete {status} record")
            paths.extend((tokens[index], tokens[index + 1]))
            index += 2
        else:
            if index >= len(tokens):
                raise ValueError(f"git diff returned an incomplete {status} record")
            paths.append(tokens[index])
            index += 1

    return list(dict.fromkeys(normalize_repo_path(path) for path in paths))


def changed_paths_from_git(base: str, head: str, repo_root: Path) -> list[str]:
    for revision in (base, head):
        if not _SHA_PATTERN.fullmatch(revision):
            raise ValueError(f"revision must be a commit SHA: {revision!r}")

    completed = subprocess.run(
        [
            "git",
            "diff",
            "--name-status",
            "-z",
            "--find-renames",
            base,
            head,
            "--",
        ],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return parse_name_status_z(completed.stdout)


def _matches_any(path: str, patterns: Iterable[str]) -> bool:
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def _is_documentation_path(path: str) -> bool:
    return (
        path.startswith("docs/")
        or path.startswith("docs_old/")
        or path in _DOCUMENTATION_ROOT_FILES
        or path.endswith(".md")
    )


def _is_deployment_only_path(path: str) -> bool:
    return path.startswith(_DEPLOYMENT_ONLY_PREFIXES) or path.startswith(
        _DEPLOYMENT_ONLY_WORKFLOWS
    )


def _is_ci_control_path(path: str) -> bool:
    return (
        path == ".github/workflows/pr-quality-gate.yml"
        or path.startswith("scripts/ci/")
        or path.startswith("tests/ci/")
    )


def classify_paths(raw_paths: Iterable[str]) -> ChangeScope:
    paths = list(dict.fromkeys(normalize_repo_path(path) for path in raw_paths))
    scope = ChangeScope(docs_only=bool(paths) and all(_is_documentation_path(path) for path in paths))

    if not paths:
        scope.client = True
        scope.enable_python_smoke()
        scope.knowledge_postgres = True
        scope.workflow_postgres = True
        return scope

    for path in paths:
        if _matches_any(path, _KNOWLEDGE_POSTGRES_PATTERNS):
            scope.knowledge_postgres = True
        if _matches_any(path, _WORKFLOW_POSTGRES_PATTERNS):
            scope.workflow_postgres = True

        if _is_documentation_path(path):
            continue
        if path.endswith(".py"):
            scope.python_lint = True
        if _is_deployment_only_path(path):
            continue

        if _is_ci_control_path(path):
            scope.client = True
            scope.enable_python_smoke()
            scope.knowledge_postgres = True
            scope.workflow_postgres = True
            continue

        if path.startswith("apps/client/"):
            scope.client = True
            continue

        if path.startswith("apps/gateway/"):
            scope.gateway_tests = True
            continue

        if path.startswith("apps/workflow_engine/"):
            scope.workflow_tests = True
            continue

        if path.startswith("apps/log_system/"):
            scope.log_tests = True
            continue

        if path.startswith("apps/sandbox/"):
            scope.sandbox_tests = True
            continue

        if path.startswith("apps/shared/"):
            scope.shared_tests = True
            scope.gateway_tests = True
            scope.workflow_tests = True

            if path.startswith(("apps/shared/db/", "apps/shared/schemas/")):
                scope.root_tests = True
                scope.log_tests = True
            if path.startswith("apps/shared/alembic/"):
                scope.root_tests = True
                scope.log_tests = True
                scope.knowledge_postgres = True
                scope.workflow_postgres = True
            if any(
                marker in path
                for marker in ("audit", "tracing", "security_alert", "celery")
            ):
                scope.log_tests = True
            continue

        if path.startswith("tests/"):
            if path.startswith(("tests/e2e/", "tests/evaluation/", "tests/load/")):
                continue
            scope.root_tests = True
            continue

        if path.startswith("scripts/") and path.endswith(".py"):
            scope.root_tests = True
            continue

        if path.startswith(".github/workflows/"):
            # Specialized PostgreSQL workflows are selected above. Other non-deploy
            # workflow changes are treated as CI control changes.
            if path in {
                ".github/workflows/test-knowledge-runtime-postgres.yml",
                ".github/workflows/test-schedule-dispatch-postgres.yml",
            }:
                continue
            scope.client = True
            scope.enable_python_smoke()
            continue

        if path in {".gitattributes", ".gitignore"}:
            continue

        # Unknown executable/configuration paths must not silently lose coverage.
        scope.client = True
        scope.enable_python_smoke()

    return scope


def changed_python_files(paths: Iterable[str], repo_root: Path) -> list[str]:
    candidates = []
    resolved_root = repo_root.resolve()
    for raw_path in paths:
        path = normalize_repo_path(raw_path)
        candidate = repo_root / path
        if not path.endswith(".py") or not candidate.is_file():
            continue
        if candidate.is_symlink():
            raise ValueError(f"changed Python path must not be a symlink: {path}")
        try:
            candidate.resolve().relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError(f"changed Python path escapes repository: {path}") from exc
        candidates.append(path)
    return sorted(set(candidates))


def _write_github_outputs(output_path: Path, scope: ChangeScope) -> None:
    with output_path.open("a", encoding="utf-8", newline="\n") as output:
        for name, value in scope.github_outputs().items():
            output.write(f"{name}={value}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify pull request change scope")
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--python-files0", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    paths = changed_paths_from_git(args.base, args.head, repo_root)

    if args.python_files0:
        files = changed_python_files(paths, repo_root)
        sys.stdout.buffer.write(b"".join(path.encode("utf-8") + b"\0" for path in files))
        return 0

    scope = classify_paths(paths)
    if args.github_output:
        _write_github_outputs(args.github_output, scope)
    print(json.dumps({"changed_paths": paths, "scope": asdict(scope)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
