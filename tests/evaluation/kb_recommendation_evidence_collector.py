"""Safe MBA-342 evaluator-input collector for controlled synthetic runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


_SCHEMA_VERSION = "mba-342-synthetic-v1"
_DATA_CLASSIFICATION = "synthetic_non_secret"
_CASE_ID_PREFIX = "mba342-syn-case-"
_CANDIDATE_LABEL_PREFIX = "mba342-syn-kb-"
_DATASET_FIELDS = {"schema_version", "data_classification", "cases"}
_CASE_FIELDS = {
    "case_id",
    "case_tags",
    "metadata_poor",
    "query",
    "candidate_labels",
    "expected_relevant",
    "authorized_candidate_count",
}
_BASELINE_FIELDS = {
    "case_id",
    "ranked_labels",
    "authorized_candidate_count",
}
_PARENT_FIRST_FIELDS = _BASELINE_FIELDS | {
    "latency_ms",
    "processed_cohort_count",
    "embedding_calls",
    "discovery_sql",
    "parent_sql",
    "candidate_sql",
    "leakage_count",
}
_OPERATIONAL_FIELDS = (
    "latency_ms",
    "processed_cohort_count",
    "embedding_calls",
    "discovery_sql",
    "parent_sql",
    "candidate_sql",
    "leakage_count",
)


def _require_non_negative_int(value: Any, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


def _require_unique_strings(
    value: Any,
    *,
    field: str,
    prefix: str | None = None,
) -> list[str]:
    if not isinstance(value, list) or not all(
        isinstance(item, str) and item for item in value
    ):
        raise ValueError(f"{field} must be a string list")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} must contain unique values")
    if prefix is not None and any(not item.startswith(prefix) for item in value):
        raise ValueError(f"{field} must use controlled candidate labels")
    return list(value)


def _validate_dataset(dataset: Any) -> dict[str, Any]:
    if not isinstance(dataset, dict) or set(dataset) != _DATASET_FIELDS:
        raise ValueError("controlled dataset has an unsupported schema")
    if dataset["schema_version"] != _SCHEMA_VERSION:
        raise ValueError("controlled dataset has an unsupported schema version")
    if dataset["data_classification"] != _DATA_CLASSIFICATION:
        raise ValueError("controlled dataset must be synthetic and non-secret")
    cases = dataset["cases"]
    if not isinstance(cases, list) or not cases:
        raise ValueError("controlled dataset cases must be a non-empty list")

    observed_case_ids: set[str] = set()
    for case in cases:
        if not isinstance(case, dict) or set(case) != _CASE_FIELDS:
            raise ValueError("controlled dataset case has an unsupported schema")
        case_id = case["case_id"]
        if not isinstance(case_id, str) or not case_id.startswith(_CASE_ID_PREFIX):
            raise ValueError("controlled dataset must use synthetic case_id values")
        if case_id in observed_case_ids:
            raise ValueError("controlled dataset requires unique case_id values")
        observed_case_ids.add(case_id)

        tags = _require_unique_strings(case["case_tags"], field="case_tags")
        if not tags:
            raise ValueError("case_tags must not be empty")
        if not isinstance(case["metadata_poor"], bool):
            raise ValueError("metadata_poor must be a boolean")
        if ("metadata_poor" in tags) != case["metadata_poor"]:
            raise ValueError("metadata_poor tag and flag must agree")
        if not isinstance(case["query"], str) or not case["query"].strip():
            raise ValueError("controlled synthetic query must be non-empty")

        candidate_labels = _require_unique_strings(
            case["candidate_labels"],
            field="candidate_labels",
            prefix=_CANDIDATE_LABEL_PREFIX,
        )
        expected_relevant = _require_unique_strings(
            case["expected_relevant"],
            field="expected_relevant",
            prefix=_CANDIDATE_LABEL_PREFIX,
        )
        if not set(expected_relevant) <= set(candidate_labels):
            raise ValueError("expected_relevant must use controlled candidate labels")
        candidate_count = _require_non_negative_int(
            case["authorized_candidate_count"],
            field="authorized_candidate_count",
        )
        if candidate_count < len(candidate_labels):
            raise ValueError(
                "authorized_candidate_count cannot be smaller than controlled labels"
            )
        if "candidate_budget_5000" in tags and candidate_count != 5000:
            raise ValueError(
                "candidate_budget_5000 cases require exactly 5000 candidates"
            )
    return dataset


def load_controlled_dataset(path: Path) -> dict[str, Any]:
    dataset = json.loads(path.read_text(encoding="utf-8"))
    return _validate_dataset(dataset)


def _index_observations(
    observations: Any,
    *,
    allowed_fields: set[str],
    fixture_by_id: dict[str, dict[str, Any]],
    run_name: str,
) -> dict[str, dict[str, Any]]:
    if not isinstance(observations, list):
        raise ValueError(f"{run_name} observations must be a list")
    indexed: dict[str, dict[str, Any]] = {}
    for observation in observations:
        if not isinstance(observation, dict) or set(observation) != allowed_fields:
            raise ValueError(
                f"{run_name} observations may contain only safe aggregate fields"
            )
        case_id = observation["case_id"]
        if not isinstance(case_id, str) or case_id not in fixture_by_id:
            raise ValueError(f"{run_name} observation has an unknown case_id")
        if case_id in indexed:
            raise ValueError(f"{run_name} observations require unique case_id values")

        fixture_case = fixture_by_id[case_id]
        ranked_labels = _require_unique_strings(
            observation["ranked_labels"],
            field=f"{run_name} ranked_labels",
            prefix=_CANDIDATE_LABEL_PREFIX,
        )
        if len(ranked_labels) > 5:
            raise ValueError(f"{run_name} ranked_labels must be bounded to top five")
        if not set(ranked_labels) <= set(fixture_case["candidate_labels"]):
            raise ValueError(
                f"{run_name} ranked results must use controlled candidate labels"
            )
        _require_non_negative_int(
            observation["authorized_candidate_count"],
            field=f"{run_name} authorized_candidate_count",
        )
        for field in _OPERATIONAL_FIELDS:
            if field in observation:
                _require_non_negative_int(
                    observation[field],
                    field=f"{run_name} {field}",
                )
        indexed[case_id] = observation
    return indexed


def collect_evidence(
    dataset: dict[str, Any],
    baseline_observations: list[dict[str, Any]],
    parent_first_observations: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Join controlled observations without projecting query or raw identities."""

    validated_dataset = _validate_dataset(dataset)
    fixture_by_id = {
        case["case_id"]: case for case in validated_dataset["cases"]
    }
    baseline_by_id = _index_observations(
        baseline_observations,
        allowed_fields=_BASELINE_FIELDS,
        fixture_by_id=fixture_by_id,
        run_name="baseline",
    )
    parent_by_id = _index_observations(
        parent_first_observations,
        allowed_fields=_PARENT_FIRST_FIELDS,
        fixture_by_id=fixture_by_id,
        run_name="parent-first",
    )
    fixture_ids = set(fixture_by_id)
    if set(baseline_by_id) != fixture_ids or set(parent_by_id) != fixture_ids:
        raise ValueError(
            "controlled fixture and both runs must use the same case_id set"
        )

    evidence = []
    for fixture_case in validated_dataset["cases"]:
        case_id = fixture_case["case_id"]
        baseline = baseline_by_id[case_id]
        parent_first = parent_by_id[case_id]
        expected_count = fixture_case["authorized_candidate_count"]
        if (
            baseline["authorized_candidate_count"] != expected_count
            or parent_first["authorized_candidate_count"] != expected_count
        ):
            raise ValueError(
                "baseline and parent-first runs must use the controlled candidate snapshot"
            )
        evidence.append(
            {
                "case_id": case_id,
                "case_tags": list(fixture_case["case_tags"]),
                "metadata_poor": fixture_case["metadata_poor"],
                "expected_relevant": list(fixture_case["expected_relevant"]),
                "baseline_ranked": list(baseline["ranked_labels"]),
                "parent_first_ranked": list(parent_first["ranked_labels"]),
                "latency_ms": parent_first["latency_ms"],
                "authorized_candidate_count": expected_count,
                "processed_cohort_count": parent_first[
                    "processed_cohort_count"
                ],
                "embedding_calls": parent_first["embedding_calls"],
                "discovery_sql": parent_first["discovery_sql"],
                "parent_sql": parent_first["parent_sql"],
                "candidate_sql": parent_first["candidate_sql"],
                "leakage_count": parent_first["leakage_count"],
            }
        )
    return evidence


def _load_observations(path: Path) -> list[dict[str, Any]]:
    observations = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(observations, list):
        raise ValueError("observation input must be a JSON list")
    return observations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("dataset", type=Path)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("parent_first", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    evidence = collect_evidence(
        load_controlled_dataset(args.dataset),
        _load_observations(args.baseline),
        _load_observations(args.parent_first),
    )
    serialized = json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
