from __future__ import annotations

import argparse
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable

from scripts.ci.changed_scope import (
    is_github_composite_action_path,
    is_github_workflow_path,
    is_unsupported_deployment_path,
    normalize_repo_path,
)


_APPROVED_WORKFLOW_PATHS = frozenset(
    {
        ".github/workflows/pr-ci-control-guard.yml",
        ".github/workflows/pr-quality-gate.yml",
        ".github/workflows/publish-images.yml",
        ".github/workflows/test-agent-builder-postgres.yml",
        ".github/workflows/test-knowledge-runtime-postgres.yml",
        ".github/workflows/test-memory-postgres.yml",
        ".github/workflows/test-schedule-dispatch-postgres.yml",
    }
)

_PROVIDER_SPECIFIC_EXECUTABLE_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"aws-actions\s*/\s*configure-aws-credentials",
        r"aws-actions\s*/\s*amazon-ecr-login",
        r"\baws\s+eks\b",
        r"\beksctl\b",
        r"\.dkr\.ecr\.",
        r"eks\.amazonaws\.com",
    )
)

_MAX_GITHUB_EXECUTABLE_BYTES = 1024 * 1024


def _github_executable_content_is_unsupported(repo_root: Path, path: str) -> bool:
    root = repo_root.resolve()
    candidate = root.joinpath(*PurePosixPath(path).parts)
    if candidate.is_symlink() or not candidate.is_file():
        return True

    try:
        candidate.resolve().relative_to(root)
        if candidate.stat().st_size > _MAX_GITHUB_EXECUTABLE_BYTES:
            return True
        content = candidate.read_text(encoding="utf-8")
    except (OSError, UnicodeError, ValueError):
        return True

    return any(
        pattern.search(content) is not None
        for pattern in _PROVIDER_SPECIFIC_EXECUTABLE_PATTERNS
    )


def find_unsupported_deployment_paths(
    paths: Iterable[str],
    *,
    repo_root: Path | None = None,
    require_complete_workflow_allowlist: bool = False,
) -> list[str]:
    normalized_paths = list(
        dict.fromkeys(normalize_repo_path(raw_path) for raw_path in paths)
    )
    unsupported: list[str] = []
    for path in normalized_paths:
        if is_unsupported_deployment_path(path):
            unsupported.append(path)
            continue
        if is_github_workflow_path(path) and (
            path not in _APPROVED_WORKFLOW_PATHS
            or (
                repo_root is not None
                and _github_executable_content_is_unsupported(repo_root, path)
            )
        ):
            unsupported.append(path)
            continue
        if (
            is_github_composite_action_path(path)
            and repo_root is not None
            and _github_executable_content_is_unsupported(repo_root, path)
        ):
            unsupported.append(path)

    if require_complete_workflow_allowlist:
        tracked_workflows = {
            path for path in normalized_paths if is_github_workflow_path(path)
        }
        unsupported.extend(sorted(_APPROVED_WORKFLOW_PATHS - tracked_workflows))
    return list(dict.fromkeys(unsupported))


def tracked_paths(repo_root: Path) -> list[str]:
    completed = subprocess.run(
        ["git", "ls-files", "-z", "--"],
        cwd=repo_root,
        check=True,
        capture_output=True,
    )
    return [
        path
        for path in completed.stdout.decode("utf-8").split("\0")
        if path
    ]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Reject deployment surfaces outside the supported boundary"
    )
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    unsupported = find_unsupported_deployment_paths(
        tracked_paths(repo_root),
        repo_root=repo_root,
        require_complete_workflow_allowlist=True,
    )
    if unsupported:
        print(
            "Unsupported or unapproved deployment surface is tracked; "
            "use Docker Compose or the provider-neutral Helm chart:"
        )
        for path in unsupported:
            print(f"- {path}")
        return 1
    print("Supported deployment surface check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
