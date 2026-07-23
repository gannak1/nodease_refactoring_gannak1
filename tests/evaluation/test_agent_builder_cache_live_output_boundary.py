from __future__ import annotations

from pathlib import Path

import pytest

from tests.evaluation.run_agent_builder_cache_latency_benchmark import (
    _resolve_development_output,
    _resolve_private_scenarios,
    _resolve_repository_root,
)


def _workspace_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_development_output_rejects_a_tracked_repository_path() -> None:
    root = _workspace_root()

    with pytest.raises(ValueError, match="development output"):
        _resolve_development_output(
            root / "docs" / "features" / "agent-builder-cache" / "leak.csv",
            root,
        )


def test_repository_root_rejects_another_worktree(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repository root"):
        _resolve_repository_root(tmp_path)


def test_private_scenarios_reject_a_tracked_repository_path() -> None:
    root = _workspace_root()

    with pytest.raises(ValueError, match="private scenario"):
        _resolve_private_scenarios(
            root / "docs" / "features" / "agent-builder-cache" / "scenario.json",
            root,
        )