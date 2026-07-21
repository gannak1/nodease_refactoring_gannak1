from __future__ import annotations

import argparse
import subprocess
from pathlib import Path
from typing import Iterable

from scripts.ci.changed_scope import (
    _UNSUPPORTED_DEPLOYMENT_EXACT_PATHS,
    _UNSUPPORTED_DEPLOYMENT_PREFIXES,
    normalize_repo_path,
)


def find_unsupported_deployment_paths(paths: Iterable[str]) -> list[str]:
    unsupported: list[str] = []
    for raw_path in paths:
        path = normalize_repo_path(raw_path)
        if path in _UNSUPPORTED_DEPLOYMENT_EXACT_PATHS or path.startswith(
            _UNSUPPORTED_DEPLOYMENT_PREFIXES
        ):
            unsupported.append(path)
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
    unsupported = find_unsupported_deployment_paths(tracked_paths(repo_root))
    if unsupported:
        print(
            "Unsupported EKS deployment surface is tracked; "
            "use Docker Compose or the provider-neutral Helm chart:"
        )
        for path in unsupported:
            print(f"- {path}")
        return 1
    print("Supported deployment surface check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
