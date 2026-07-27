from __future__ import annotations

import csv
import json
import re
from dataclasses import replace
from pathlib import Path

import pytest

from tests.evaluation.agent_builder_cache_latency_report import (
    ARTIFACT_FILENAMES,
    RUNS_CSV_FIELDS,
    ArtifactSafetyError,
    ReportValidationError,
    build_summary,
    generate_bundle,
    inspect_artifact_safety,
    load_dataset,
    main,
    read_runs_csv,
    write_runs_csv,
)


DATASET_PATH = (
    Path(__file__).parent
    / "datasets"
    / "agent_builder_cache_latency_v1.json"
)


def test_synthetic_dataset_validates_comparison_and_pair_contract() -> None:
    dataset = load_dataset(DATASET_PATH)

    assert dataset.metadata.benchmark_kind == "synthetic_comparison"
    assert dataset.metadata.benchmark_id.startswith(
        "2026-07-21-081641384b17-"
    )
    assert {run.comparison_group for run in dataset.runs} == {
        "cache_disabled_baseline",
        "cold_miss",
        "exact_warm_hit",
        "normalization_warm_hit",
        "semantic_bypass",
        "negative_control",
        "redis_fail_open",
    }
    assert any(run.is_warmup for run in dataset.runs)
    assert any(not run.is_success for run in dataset.runs)


def test_runs_csv_round_trip_uses_exact_allowlisted_schema(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "runs.csv"

    write_runs_csv(dataset.runs, output)

    with output.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        assert tuple(reader.fieldnames or ()) == RUNS_CSV_FIELDS
    assert read_runs_csv(output) == dataset.runs


def test_csv_rejects_unknown_header_and_noncanonical_boolean(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "runs.csv"
    write_runs_csv(dataset.runs, output)
    original = output.read_text(encoding="utf-8")

    output.write_text(
        original.replace("result_fingerprint", "unexpected_field", 1),
        encoding="utf-8",
    )
    with pytest.raises(ReportValidationError, match="header"):
        read_runs_csv(output)

    write_runs_csv(dataset.runs, output)
    output.write_text(
        output.read_text(encoding="utf-8").replace(",true,", ",True,", 1),
        encoding="utf-8",
    )
    with pytest.raises(ReportValidationError, match="is_warmup"):
        read_runs_csv(output)


def test_schema_rejects_cache_on_disabled_outcome_and_protected_id() -> None:
    dataset = load_dataset(DATASET_PATH)
    cache_on = next(
        run for run in dataset.runs if run.comparison_group == "cold_miss"
    )

    with pytest.raises(ReportValidationError, match="disabled"):
        build_summary(
            [replace(cache_on, cache_outcome="disabled")],
            dataset.metadata,
            validate_pairs=False,
        )

    protected_id = "-".join(
        ["123e4567", "e89b", "12d3", "a456", "426614174000"]
    )
    with pytest.raises(ReportValidationError, match="protected identifier"):
        build_summary(
            [replace(cache_on, case_id=protected_id)],
            dataset.metadata,
            validate_pairs=False,
        )


@pytest.mark.parametrize(
    "comparison_group",
    ("cache_disabled_baseline", "cold_miss"),
)
def test_successful_provider_paths_reject_more_than_two_calls(
    comparison_group: str,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    run = next(
        item
        for item in dataset.runs
        if item.comparison_group == comparison_group and item.is_success
    )

    with pytest.raises(ReportValidationError, match="provider_call_count"):
        build_summary(
            [
                replace(
                    run,
                    provider_call_count=3,
                    repair_call_count=1,
                )
            ],
            dataset.metadata,
            validate_pairs=False,
        )


@pytest.mark.parametrize(
    ("provider_call_count", "repair_call_count"),
    ((1, 1), (2, 0), (2, 2)),
)
def test_provider_repair_counts_require_one_primary_and_at_most_one_repair(
    provider_call_count: int,
    repair_call_count: int,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    run = next(
        item
        for item in dataset.runs
        if (
            item.comparison_group == "cold_miss"
            and item.is_success
            and not item.is_warmup
        )
    )

    with pytest.raises(ReportValidationError, match="repair_call_count"):
        build_summary(
            [
                replace(
                    run,
                    provider_call_count=provider_call_count,
                    repair_call_count=repair_call_count,
                )
            ],
            dataset.metadata,
            validate_pairs=False,
        )

    accepted = build_summary(
        [replace(run, provider_call_count=2, repair_call_count=1)],
        dataset.metadata,
        validate_pairs=False,
    )
    assert accepted["groups"]["cold_miss"]["provider_call_count"] == 2
    assert accepted["groups"]["cold_miss"]["repair_call_count"] == 1


def test_success_requires_fingerprint_but_failed_row_may_omit_it() -> None:
    dataset = load_dataset(DATASET_PATH)
    success = next(run for run in dataset.runs if run.is_success)
    failed = next(run for run in dataset.runs if not run.is_success)

    with pytest.raises(ReportValidationError, match="result_fingerprint"):
        build_summary(
            [replace(success, result_fingerprint="")],
            dataset.metadata,
            validate_pairs=False,
        )

    summary = build_summary(
        [replace(failed, result_fingerprint="")],
        dataset.metadata,
        validate_pairs=False,
    )
    group = summary["groups"][failed.comparison_group]
    assert group["failed_run_count"] == 1



@pytest.mark.parametrize(
    "warm_group", ("exact_warm_hit", "normalization_warm_hit")
)
@pytest.mark.parametrize(
    ("terminal_status", "validation_passed", "result_fingerprint"),
    (
        ("success", True, None),
        ("provider_error", False, ""),
        ("validation_error", False, ""),
        ("timeout", False, ""),
        ("canceled", False, ""),
    ),
)
def test_hit_outcome_rejects_provider_calls_for_all_terminal_statuses(
    warm_group: str,
    terminal_status: str,
    validation_passed: bool,
    result_fingerprint: str | None,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    hit = next(
        run
        for run in dataset.runs
        if run.comparison_group == warm_group
        and run.is_success
        and not run.is_warmup
    )
    invalid_hit = replace(
        hit,
        provider_call_count=1,
        terminal_status=terminal_status,
        validation_passed=validation_passed,
        result_fingerprint=(
            hit.result_fingerprint
            if result_fingerprint is None
            else result_fingerprint
        ),
    )

    with pytest.raises(ReportValidationError, match="hit must not call provider"):
        build_summary(
            [invalid_hit],
            dataset.metadata,
            validate_pairs=False,
        )

def test_successful_pair_allows_independent_materialization_fingerprints() -> None:
    dataset = load_dataset(DATASET_PATH)
    pair = [
        run
        for run in dataset.runs
        if run.pair_id == "exact-01" and not run.is_warmup
    ]
    assert len(pair) == 2

    changed = [pair[0], replace(pair[1], result_fingerprint="0" * 64)]
    build_summary(changed, dataset.metadata)



def test_statistics_exclude_warmups_and_failed_rounds() -> None:
    dataset = load_dataset(DATASET_PATH)

    summary = build_summary(dataset.runs, dataset.metadata)
    cold = summary["groups"]["cold_miss"]

    assert cold["measured_run_count"] == 2
    assert cold["successful_run_count"] == 1
    assert cold["failed_run_count"] == 1
    assert cold["warmup_run_count"] == 1
    assert cold["failure_rate"] == 0.5
    assert cold["planning_latency_ms"] == {
        "mean_ms": 90.0,
        "p50_ms": 90.0,
        "p95_ms": 90.0,
        "stddev_ms": 0.0,
        "min_ms": 90.0,
        "max_ms": 90.0,
    }
    assert summary["groups"]["exact_warm_hit"][
        "planning_latency_ms"
    ] == {
        "mean_ms": 30.0,
        "p50_ms": 30.0,
        "p95_ms": 39.0,
        "stddev_ms": 10.0,
        "min_ms": 20.0,
        "max_ms": 40.0,
    }


def test_paired_delta_improvement_and_speedup_are_deterministic() -> None:
    dataset = load_dataset(DATASET_PATH)

    paired = build_summary(dataset.runs, dataset.metadata)[
        "paired_comparisons"
    ]["exact_warm_hit"]

    assert paired["paired_success_count"] == 2
    assert paired["excluded_pair_count"] == 1
    assert paired["planning_latency_ms"] == {
        "baseline_mean_ms": 120.0,
        "candidate_mean_ms": 30.0,
        "mean_paired_delta_ms": 90.0,
        "improvement_rate_percent": 75.0,
        "speedup": 4.0,
    }
    assert paired["end_to_end_latency_ms"] == {
        "baseline_mean_ms": 180.0,
        "candidate_mean_ms": 60.0,
        "mean_paired_delta_ms": 120.0,
        "improvement_rate_percent": 66.667,
        "speedup": 3.0,
    }


def test_failed_pair_is_counted_but_excluded_from_paired_latency() -> None:
    dataset = load_dataset(DATASET_PATH)

    cold = build_summary(dataset.runs, dataset.metadata)[
        "paired_comparisons"
    ]["cold_miss"]

    assert cold["paired_success_count"] == 1
    assert cold["excluded_pair_count"] == 2
    assert cold["planning_latency_ms"] == {
        "baseline_mean_ms": 100.0,
        "candidate_mean_ms": 90.0,
        "mean_paired_delta_ms": 10.0,
        "improvement_rate_percent": 10.0,
        "speedup": 1.111,
    }


def test_modeled_estimates_use_cold_and_both_warm_hit_groups() -> None:
    dataset = load_dataset(DATASET_PATH)

    summary = build_summary(dataset.runs, dataset.metadata)

    assert summary["modeled_estimates"] == [
        {
            "estimate_type": "modeled_estimate",
            "hit_rate": 0.25,
            "planning_latency_ms": 75.625,
            "end_to_end_latency_ms": 128.125,
        },
        {
            "estimate_type": "modeled_estimate",
            "hit_rate": 0.5,
            "planning_latency_ms": 61.25,
            "end_to_end_latency_ms": 106.25,
        },
        {
            "estimate_type": "modeled_estimate",
            "hit_rate": 0.75,
            "planning_latency_ms": 46.875,
            "end_to_end_latency_ms": 84.375,
        },
    ]
    assert summary["modeled_path_classification"] == {
        "warm": ["exact_warm_hit", "normalization_warm_hit"],
        "miss": [
            "cold_miss",
            "semantic_bypass",
            "negative_control",
            "redis_fail_open",
        ],
    }



@pytest.mark.parametrize(
    ("warm_group", "planning_latency_ms", "end_to_end_latency_ms"),
    (
        ("exact_warm_hit", 76.667, 129.167),
        ("normalization_warm_hit", 76.25, 128.75),
    ),
)
def test_modeled_estimates_exclude_warm_rehydration_fallback_miss(
    warm_group: str,
    planning_latency_ms: float,
    end_to_end_latency_ms: float,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    fallback = next(
        run
        for run in dataset.runs
        if run.comparison_group == warm_group
        and run.is_success
        and not run.is_warmup
    )
    rows = tuple(
        replace(
            row,
            cache_outcome="miss",
            provider_call_count=1,
            planning_latency_ms=200,
            end_to_end_latency_ms=260,
        )
        if row == fallback
        else row
        for row in dataset.runs
    )

    summary = build_summary(
        rows,
        dataset.metadata,
        validate_pairs=False,
    )
    assert summary["modeled_estimates"][0] == {
        "estimate_type": "modeled_estimate",
        "hit_rate": 0.25,
        "planning_latency_ms": planning_latency_ms,
        "end_to_end_latency_ms": end_to_end_latency_ms,
    }

def test_bundle_is_complete_deterministic_and_shows_every_round(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / dataset.metadata.benchmark_id

    generate_bundle(dataset, output)
    first = {
        name: (output / name).read_bytes() for name in ARTIFACT_FILENAMES
    }
    generate_bundle(dataset, output)
    second = {
        name: (output / name).read_bytes() for name in ARTIFACT_FILENAMES
    }

    assert first == second
    assert set(first) == {
        "README.md",
        "runs.csv",
        "summary.json",
        "summary.csv",
        "summary.md",
        "latency-comparison.svg",
        "cache-hit-scenarios.svg",
    }
    readme = first["README.md"].decode("utf-8")
    for relative_path in set(ARTIFACT_FILENAMES) - {"README.md"}:
        assert f"]({relative_path})" in readme

    latency_graph = first["latency-comparison.svg"].decode("utf-8")
    scenario_graph = first["cache-hit-scenarios.svg"].decode("utf-8")
    for graph_name in (
        "latency-comparison.svg",
        "cache-hit-scenarios.svg",
    ):
        graph = first[graph_name].decode("utf-8")
        assert graph.count('data-run="') == len(dataset.runs)
        for run in dataset.runs:
            assert run.artifact_key in graph

    for run in dataset.runs:
        warmup = str(run.is_warmup).lower()
        for graph in (latency_graph, scenario_graph):
            assert (
                f'data-run="{run.artifact_key}" '
                f'data-warmup="{warmup}"'
            ) in graph
        validation = str(run.validation_passed).lower()
        expected_title = (
            f"<title>{run.artifact_key} outcome={run.cache_outcome} "
            f"calls={run.provider_call_count}/{run.repair_call_count} "
            f"terminal={run.terminal_status} "
            f"validation_passed={validation}</title>"
        )
        assert expected_title in scenario_graph
        if run.is_warmup and run.is_success:
            for graph in (latency_graph, scenario_graph):
                marker = re.search(
                    rf'<g data-run="{re.escape(run.artifact_key)}".*?</g>',
                    graph,
                    re.DOTALL,
                )
                assert marker is not None
                assert 'fill="none"' in marker.group(0)


    parsed = json.loads(first["summary.json"])
    assert parsed["artifact_safety"] == {
        "status": "passed",
        "files_scanned": len(ARTIFACT_FILENAMES),
    }
    summary_rows = list(
        csv.DictReader(first["summary.csv"].decode("utf-8").splitlines())
    )
    assert {row["record_type"] for row in summary_rows} == {
        "measurement",
        "paired_comparison",
        "modeled_estimate",
    }
    inspect_artifact_safety(
        {name: content.decode("utf-8") for name, content in first.items()}
    )


@pytest.mark.parametrize(
    "unsafe_text",
    [
        "authorization: " + "Bear" + "er " + "fixture-value",
        "credential_" + "id," + "-".join(
            ["123e4567", "e89b", "12d3", "a456", "426614174000"]
        ),
        "provider_" + "payload={}",
        "s" + "k-fixture-value",
    ],
)
def test_artifact_safety_rejects_sensitive_or_protected_content(
    unsafe_text: str,
) -> None:
    with pytest.raises(ArtifactSafetyError):
        inspect_artifact_safety({"unsafe.txt": unsafe_text})


def test_failed_warmup_latency_svg_keeps_both_surfaces_and_warmup_state(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    warmup = next(
        item
        for item in dataset.runs
        if item.is_warmup and item.comparison_group == "exact_warm_hit"
    )
    failed = replace(
        warmup,
        terminal_status="validation_error",
        validation_passed=False,
        result_fingerprint="",
    )
    runs = tuple(
        failed if item == warmup else item for item in dataset.runs
    )
    output = tmp_path / "failed-warmup-bundle"

    generate_bundle(replace(dataset, runs=runs), output)

    graph = (output / "latency-comparison.svg").read_text(encoding="utf-8")
    marker = re.search(
        rf'<g data-run="{re.escape(failed.artifact_key)}".*?</g>',
        graph,
        re.DOTALL,
    )
    assert marker is not None
    contents = marker.group(0)
    assert 'data-warmup="true"' in contents
    assert contents.count('fill="none"') == 2
    assert contents.count('stroke="#dc2626"') == 2
    assert 'stroke="#2563eb"' in contents
    assert 'stroke="#16a34a"' in contents


def test_safety_failure_does_not_create_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "bundle"

    def fail_safety(_: object) -> None:
        raise ArtifactSafetyError("safe reason")

    monkeypatch.setattr(
        "tests.evaluation.agent_builder_cache_latency_report."
        "inspect_artifact_safety",
        fail_safety,
    )

    with pytest.raises(ArtifactSafetyError, match="safe reason"):
        generate_bundle(dataset, output)
    assert not output.exists()


def test_cli_generates_synthetic_bundle(tmp_path: Path) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "cli-bundle"

    assert main(
        ["--dataset", str(DATASET_PATH), "--output", str(output)]
    ) == 0
    assert (output / "README.md").is_file()
    assert dataset.metadata.benchmark_id in (
        output / "README.md"
    ).read_text(encoding="utf-8")


def test_csv_truncated_row_fails_with_validation_error(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "truncated.csv"
    source = tmp_path / "source.csv"
    write_runs_csv(dataset.runs, source)
    with source.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(rows[0])
        writer.writerow(rows[1][:8])

    with pytest.raises(ReportValidationError, match="validation_passed"):
        read_runs_csv(output)


def test_csv_value_error_includes_safe_row_number_and_field(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "invalid-value.csv"
    write_runs_csv(dataset.runs, output)
    with output.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.reader(handle))
    provider_index = RUNS_CSV_FIELDS.index("provider_call_count")
    rows[1][provider_index] = "not-an-integer"
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerows(rows)

    with pytest.raises(
        ReportValidationError,
        match=r"row 1 provider_call_count",
    ):
        read_runs_csv(output)


@pytest.mark.parametrize(
    "warm_group", ("exact_warm_hit", "normalization_warm_hit")
)
def test_failed_warm_rehydration_fallback_records_miss_observations(
    warm_group: str,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    warm_hit = next(
        run
        for run in dataset.runs
        if run.comparison_group == warm_group
        and not run.is_warmup
        and run.is_success
    )
    failed = replace(
        warm_hit,
        cache_outcome="miss",
        provider_call_count=2,
        repair_call_count=1,
        terminal_status="validation_error",
        validation_passed=False,
        result_fingerprint="",
    )

    summary = build_summary(
        [failed], dataset.metadata, validate_pairs=False
    )

    assert summary["groups"][warm_group]["failed_run_count"] == 1
    assert summary["groups"][warm_group]["provider_call_count"] == 2
    assert summary["groups"][warm_group]["repair_call_count"] == 1


def test_negative_control_accepts_non_hit_miss_outcome() -> None:
    dataset = load_dataset(DATASET_PATH)
    negative = next(
        run
        for run in dataset.runs
        if run.comparison_group == "negative_control" and run.is_success
    )

    summary = build_summary(
        [replace(negative, cache_outcome="miss")],
        dataset.metadata,
        validate_pairs=False,
    )

    assert summary["groups"]["negative_control"]["cache_outcome_counts"] == {
        "miss": 1
    }


def test_bundle_readme_and_markdown_include_detailed_values(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "detailed-bundle"

    summary = generate_bundle(dataset, output)
    readme = (output / "README.md").read_text(encoding="utf-8")
    markdown = (output / "summary.md").read_text(encoding="utf-8")

    cold = summary["groups"]["cold_miss"]
    exact = summary["groups"]["exact_warm_hit"]
    assert (
        "- Cold-miss measured mean (planning/end-to-end): "
        f"{cold['planning_latency_ms']['mean_ms']} / "
        f"{cold['end_to_end_latency_ms']['mean_ms']} ms"
    ) in readme
    assert (
        "- Exact warm-hit measured mean (planning/end-to-end): "
        f"{exact['planning_latency_ms']['mean_ms']} / "
        f"{exact['end_to_end_latency_ms']['mean_ms']} ms"
    ) in readme

    assert "## Modeled estimates" in readme
    for estimate in summary["modeled_estimates"]:
        expected = (
            f"| {estimate['hit_rate']} | "
            f"{estimate['planning_latency_ms']} | "
            f"{estimate['end_to_end_latency_ms']} |"
        )
        assert expected in readme
    for label in ("P50", "P95", "Stddev", "Min", "Max"):
        assert label in markdown


def test_artifact_safety_rejects_broader_protected_material() -> None:
    unsafe_samples = (
        "Bear" + "er fixture-value",
        "-".join(
            ["123e4567", "e89b", "72d3", "c456", "426614174000"]
        ),
        "AI" + "za" + "A" * 32,
        "gh" + "p_" + "a" * 24,
    )

    for unsafe_text in unsafe_samples:
        with pytest.raises(ArtifactSafetyError):
            inspect_artifact_safety({"unsafe.txt": unsafe_text})


def test_cli_consumes_runs_csv_with_explicit_metadata(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    runs_csv = tmp_path / "runs.csv"
    output = tmp_path / "csv-bundle"
    write_runs_csv(dataset.runs, runs_csv)
    metadata = dataset.metadata
    args = [
        "--runs-csv",
        str(runs_csv),
        "--output",
        str(output),
        "--dataset-version",
        metadata.dataset_version,
        "--cache-contract-version",
        metadata.cache_contract_version,
        "--run-date",
        metadata.run_date,
        "--git-sha",
        metadata.git_sha,
        "--benchmark-kind",
        metadata.benchmark_kind,
    ]

    assert main(args) == 0
    assert (output / "runs.csv").is_file()
    assert main(["--runs-csv", str(runs_csv), "--output", str(output)]) == 2


def test_bundle_rejects_unexpected_existing_entry_before_writes(
    tmp_path: Path,
) -> None:
    dataset = load_dataset(DATASET_PATH)
    output = tmp_path / "existing-bundle"
    output.mkdir()
    unexpected = output / "untracked.txt"
    unexpected.write_text("unrelated", encoding="utf-8")

    with pytest.raises(ReportValidationError, match="unexpected entries"):
        generate_bundle(dataset, output)

    assert unexpected.read_text(encoding="utf-8") == "unrelated"
    assert not any((output / name).exists() for name in ARTIFACT_FILENAMES)
