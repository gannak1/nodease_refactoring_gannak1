"""Aggregate-only MBA-342 recommendation release gate evaluator."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from statistics import mean
from typing import Any


REQUIRED_CASE_TAGS = {
    "metadata_poor",
    "name_only_irrelevant",
    "flat",
    "duplicate_collection",
    "denied_distractor",
    "korean",
    "english",
    "candidate_budget_5000",
}


def _ranking_metrics(cases: list[dict[str, Any]], field: str) -> dict[str, float]:
    relevant_cases = [case for case in cases if case["expected_relevant"]]
    precision_values = []
    recall_values = []
    reciprocal_ranks = []
    for case in relevant_cases:
        relevant = set(case["expected_relevant"])
        ranked = list(case[field])[:5]
        hits = sum(item in relevant for item in ranked)
        precision_values.append(hits / 5)
        recall_values.append(hits / len(relevant))
        reciprocal_ranks.append(
            next(
                (1.0 / rank for rank, item in enumerate(ranked, start=1) if item in relevant),
                0.0,
            )
        )
    return {
        "precision@5": mean(precision_values) if precision_values else 1.0,
        "recall@5": mean(recall_values) if recall_values else 1.0,
        "mrr": mean(reciprocal_ranks) if reciprocal_ranks else 1.0,
    }


def _no_result_accuracy(cases: list[dict[str, Any]], field: str) -> float:
    no_result_cases = [case for case in cases if not case["expected_relevant"]]
    if not no_result_cases:
        return 1.0
    return mean(1.0 if not case[field][:5] else 0.0 for case in no_result_cases)


def _recall_at_five(cases: list[dict[str, Any]], field: str) -> float:
    if not cases:
        return 1.0
    values = []
    for case in cases:
        relevant = set(case["expected_relevant"])
        if not relevant:
            continue
        values.append(len(relevant.intersection(case[field][:5])) / len(relevant))
    return mean(values) if values else 1.0


def _percentile(values: list[int], percentile: float) -> int:
    ordered = sorted(values)
    index = max(0, math.ceil(percentile * len(ordered)) - 1)
    return ordered[index]


def evaluate_release_gates(cases: list[dict[str, Any]]) -> dict[str, Any]:
    if len(cases) < 30:
        raise ValueError("MBA-342 release evidence requires at least 30 cases")

    required_fields = {
        "case_id",
        "case_tags",
        "metadata_poor",
        "expected_relevant",
        "baseline_ranked",
        "parent_first_ranked",
        "latency_ms",
        "authorized_candidate_count",
        "processed_cohort_count",
        "embedding_calls",
        "discovery_sql",
        "parent_sql",
        "candidate_sql",
        "leakage_count",
    }
    for case in cases:
        if required_fields - set(case):
            raise ValueError("MBA-342 evidence case is missing required aggregate input")
        if not isinstance(case["case_id"], str) or not case["case_id"]:
            raise ValueError("MBA-342 evidence requires a non-empty case_id")
        if not isinstance(case["case_tags"], list) or not all(
            isinstance(tag, str) for tag in case["case_tags"]
        ):
            raise ValueError("MBA-342 evidence case_tags must be a string list")
        operational_fields = (
            "latency_ms",
            "authorized_candidate_count",
            "processed_cohort_count",
            "embedding_calls",
            "discovery_sql",
            "parent_sql",
            "candidate_sql",
            "leakage_count",
        )
        if any(int(case[field]) < 0 for field in operational_fields):
            raise ValueError(
                "MBA-342 evidence requires non-negative operational evidence"
            )
        if (
            "candidate_budget_5000" in case["case_tags"]
            and int(case["authorized_candidate_count"]) != 5000
        ):
            raise ValueError(
                "candidate_budget_5000 evidence must use exactly 5000 candidates"
            )

    case_ids = [case["case_id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("MBA-342 release evidence requires unique case_id values")
    observed_tags = {tag for case in cases for tag in case["case_tags"]}
    if missing_tags := REQUIRED_CASE_TAGS - observed_tags:
        raise ValueError(
            "MBA-342 release evidence is missing required case categories: "
            + ", ".join(sorted(missing_tags))
        )

    metadata_poor_cases = [case for case in cases if case.get("metadata_poor")]
    if len(metadata_poor_cases) < 10:
        raise ValueError(
            "MBA-342 release evidence requires at least 10 metadata-poor cases"
        )

    baseline = _ranking_metrics(cases, "baseline_ranked")
    parent_first = _ranking_metrics(cases, "parent_first_ranked")
    baseline["no_result_accuracy"] = _no_result_accuracy(
        cases, "baseline_ranked"
    )
    parent_first["no_result_accuracy"] = _no_result_accuracy(
        cases, "parent_first_ranked"
    )
    metadata_poor_baseline_recall = _recall_at_five(
        metadata_poor_cases,
        "baseline_ranked",
    )
    metadata_poor_parent_recall = _recall_at_five(
        metadata_poor_cases,
        "parent_first_ranked",
    )
    latencies = [int(case["latency_ms"]) for case in cases]
    operational = {
        "p50_latency_ms": _percentile(latencies, 0.50),
        "p95_latency_ms": _percentile(latencies, 0.95),
        "max_latency_ms": max(latencies),
        "max_authorized_candidate_count": max(
            int(case["authorized_candidate_count"]) for case in cases
        ),
        "max_processed_cohort_count": max(
            int(case["processed_cohort_count"]) for case in cases
        ),
        "max_embedding_calls": max(int(case["embedding_calls"]) for case in cases),
        "max_discovery_sql": max(int(case["discovery_sql"]) for case in cases),
        "max_parent_sql": max(int(case["parent_sql"]) for case in cases),
        "max_candidate_sql": max(int(case["candidate_sql"]) for case in cases),
        "leakage_count": sum(int(case["leakage_count"]) for case in cases),
    }

    failed_gates = []
    if parent_first["recall@5"] < baseline["recall@5"]:
        failed_gates.append("recall_at_5")
    if parent_first["precision@5"] < baseline["precision@5"] - 0.02:
        failed_gates.append("precision_at_5")
    if parent_first["mrr"] < baseline["mrr"]:
        failed_gates.append("mrr")
    if metadata_poor_parent_recall < metadata_poor_baseline_recall + 0.10:
        failed_gates.append("metadata_poor_recall_at_5")
    if parent_first["no_result_accuracy"] < baseline["no_result_accuracy"]:
        failed_gates.append("no_result_accuracy")
    if operational["p50_latency_ms"] > 3000:
        failed_gates.append("p50_latency")
    if operational["p95_latency_ms"] > 8000:
        failed_gates.append("p95_latency")
    if operational["max_latency_ms"] > 10_000:
        failed_gates.append("hard_deadline")
    if operational["max_authorized_candidate_count"] > 5000:
        failed_gates.append("candidate_budget")
    if operational["max_processed_cohort_count"] > 4:
        failed_gates.append("cohort_budget")
    if operational["max_embedding_calls"] > 4:
        failed_gates.append("embedding_calls")
    if any(
        int(case["embedding_calls"]) > int(case["processed_cohort_count"])
        for case in cases
    ):
        failed_gates.append("embedding_calls_per_cohort")
    if any(
        int(case["parent_sql"]) > int(case["embedding_calls"])
        for case in cases
    ):
        failed_gates.append("parent_sql_per_embedding")
    if any(
        int(case["discovery_sql"])
        != (1 if int(case["authorized_candidate_count"]) > 0 else 0)
        for case in cases
    ):
        failed_gates.append("discovery_sql")
    if operational["max_parent_sql"] > 4:
        failed_gates.append("parent_sql")
    if operational["max_candidate_sql"] != 0:
        failed_gates.append("candidate_n_plus_one")
    if operational["leakage_count"] != 0:
        failed_gates.append("leakage")

    return {
        "passed": not failed_gates,
        "case_count": len(cases),
        "metadata_poor_case_count": len(metadata_poor_cases),
        "baseline": baseline,
        "parent_first": parent_first,
        "metadata_poor": {
            "baseline_recall@5": metadata_poor_baseline_recall,
            "parent_first_recall@5": metadata_poor_parent_recall,
        },
        "operational": operational,
        "failed_gates": failed_gates,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    cases = json.loads(args.evidence.read_text(encoding="utf-8"))
    if not isinstance(cases, list):
        raise ValueError("MBA-342 evidence must be a JSON list")
    report = evaluate_release_gates(cases)
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
