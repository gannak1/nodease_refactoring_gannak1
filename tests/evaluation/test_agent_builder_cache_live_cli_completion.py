from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.evaluation import run_agent_builder_cache_latency_benchmark as runner


def test_development_phase_does_not_claim_final_artifact_completion(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "development.csv"
    writes: list[Path] = []
    monkeypatch.setattr(runner, "_resolve_repository_root", lambda _value: tmp_path)
    monkeypatch.setattr(
        runner,
        "_resolve_development_output",
        lambda _value, _root: output,
    )
    monkeypatch.setattr(runner, "_resolve_private_scenarios", lambda value, _root: value)
    monkeypatch.setattr(runner, "load_private_scenarios", lambda _path: {})
    monkeypatch.setattr(
        runner, "validate_private_scenario_capacity", lambda _scenarios, _phase: None
    )
    monkeypatch.setattr(runner, "runtime_from_environment", lambda _env, _scenarios: object())
    monkeypatch.setattr(
        runner,
        "build_runtime_preflight",
        lambda _runtime: SimpleNamespace(scenario_fingerprint="a" * 64),
    )
    monkeypatch.setattr(runner, "run_live_phase", lambda **_kwargs: ())
    monkeypatch.setattr(runner, "build_live_metadata", lambda **_kwargs: object())
    monkeypatch.setattr(runner, "validate_live_rows", lambda _rows, *, metadata: {})
    monkeypatch.setattr(
        runner,
        "_write_development_rows",
        lambda _rows, path: writes.append(path),
    )

    assert (
        runner.main(
            [
                "--phase",
                "development",
                "--scenarios",
                "private.json",
                "--git-sha",
                "a" * 40,
            ]
        )
        == 0
    )

    assert writes == [output]
    stdout = capsys.readouterr().out
    assert "development confirmation" in stdout
    assert "validated artifacts" not in stdout


def test_development_validation_failure_reports_only_safe_stage(
    monkeypatch,
    tmp_path: Path,
    capsys,
) -> None:
    output = tmp_path / "development.csv"
    monkeypatch.setattr(runner, "_resolve_repository_root", lambda _value: tmp_path)
    monkeypatch.setattr(runner, "_resolve_development_output", lambda _value, _root: output)
    monkeypatch.setattr(runner, "_resolve_private_scenarios", lambda value, _root: value)
    monkeypatch.setattr(runner, "load_private_scenarios", lambda _path: {})
    monkeypatch.setattr(
        runner, "validate_private_scenario_capacity", lambda _scenarios, _phase: None
    )
    monkeypatch.setattr(runner, "runtime_from_environment", lambda _env, _scenarios: object())
    monkeypatch.setattr(
        runner,
        "build_runtime_preflight",
        lambda _runtime: SimpleNamespace(scenario_fingerprint="a" * 64),
    )
    monkeypatch.setattr(runner, "run_live_phase", lambda **_kwargs: ())
    monkeypatch.setattr(runner, "build_live_metadata", lambda **_kwargs: object())

    def reject_validation(_rows, *, metadata):
        raise ValueError("private detail must not be printed")

    monkeypatch.setattr(runner, "validate_live_rows", reject_validation)

    assert runner.main(["--phase", "development", "--scenarios", "private.json", "--git-sha", "a" * 40]) == 2

    stdout = capsys.readouterr().out
    assert "failure_stage=development_validation" in stdout
    assert "failure_reason=validation_contract" in stdout
    assert "private detail" not in stdout
