"""Opt-in controlled PostgreSQL evidence for MBA-342 parent-score retrieval.

This runner uses only ephemeral, synthetic data.  It executes the production
parent-score adapter against pgvector SQL, but it deliberately supplies a
local deterministic embedding resolver and never contacts a provider.
"""

from __future__ import annotations

import argparse
import json
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, event, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from apps.gateway.adapters.db.knowledge_recommendation import (
    PostgresParentRecommendationAdapter,
)
from apps.gateway.application.agent_builder.knowledge_recommendation import (
    EmbeddingResolution,
    KnowledgeRecommendationRetrievalRequest,
)
from tests.evaluation.kb_recommendation_evidence_collector import collect_evidence
from tests.evaluation.kb_recommendation_release_gates import evaluate_release_gates


CASE_COUNT = 30
METADATA_POOR_CASE_COUNT = 12
MAX_CANDIDATES = 5_000
CONTROLLED_DB_DATA_CLASSIFICATION = "controlled_db_synthetic_non_secret"
_DATASET_SCHEMA_VERSION = "mba-342-synthetic-v1"
_EMBEDDING_MODEL = "mba342-controlled-vector-v1"
_VECTOR_DIMENSION = 3
_MATCH_VECTOR = (1.0, 0.0, 0.0)
_DISTRACTOR_VECTOR = (0.0, 1.0, 0.0)
_CASE_PREFIX = "mba342-syn-case-"
_CANDIDATE_LABEL_PREFIX = "mba342-syn-kb-"


class ControlledBenchmarkBlocked(RuntimeError):
    """Raised when the opt-in environment cannot safely run the benchmark."""


@dataclass(frozen=True, slots=True)
class ControlledCasePlan:
    case_id: str
    tags: tuple[str, ...]
    metadata_poor: bool
    candidate_ids: tuple[uuid.UUID, ...]
    candidate_labels: tuple[str, ...]
    expected_relevant: tuple[str, ...]
    baseline_ranked: tuple[str, ...]


class _StaticEmbeddingResolver:
    """Local deterministic resolver; it must not perform provider I/O."""

    def __init__(self) -> None:
        self.calls = 0
        self.provider_calls = 0

    def embed_query(self, **_kwargs: Any) -> EmbeddingResolution:
        self.calls += 1
        return EmbeddingResolution(vector=_MATCH_VECTOR)


class _SqlCounter:
    def __init__(self) -> None:
        self.discovery = 0
        self.parent = 0
        self.other_selects = 0

    def reset(self) -> None:
        self.discovery = 0
        self.parent = 0
        self.other_selects = 0

    def observe(
        self,
        _connection: Any,
        _cursor: Any,
        statement: str,
        _parameters: Any,
        _context: Any,
        _executemany: bool,
    ) -> None:
        normalized = " ".join(statement.casefold().split())
        if not (normalized.startswith("select") or normalized.startswith("with")):
            return
        if "with eligible_parents as" in normalized:
            self.parent += 1
        elif "vector_dims(dc.embedding)" in normalized:
            self.discovery += 1
        else:
            self.other_selects += 1


def _candidate_id(index: int) -> uuid.UUID:
    return uuid.uuid5(uuid.NAMESPACE_URL, f"mba342-v3-controlled-{index}")


def _candidate_label(index: int) -> str:
    return f"{_CANDIDATE_LABEL_PREFIX}{index:04d}"


def _case_tags(index: int, *, metadata_poor: bool) -> tuple[str, ...]:
    tags = ["korean" if index % 2 else "english"]
    if metadata_poor:
        tags.append("metadata_poor")
    if index == 12:
        tags.append("name_only_irrelevant")
    if index == 13:
        tags.append("flat")
    if index == 14:
        tags.append("duplicate_collection")
    if index == 15:
        tags.append("denied_distractor")
    if index == CASE_COUNT - 3:
        tags.append("candidate_budget_5000")
    if index >= CASE_COUNT - 2:
        tags.append("no_result")
    return tuple(tags)


def build_controlled_case_plan() -> tuple[dict[str, Any], list[ControlledCasePlan]]:
    """Build controlled fixture input entirely in memory.

    Case labels and safe topics are internal evaluator input only.  They are
    never included in the emitted controlled-db report.
    """

    all_ids = tuple(_candidate_id(index) for index in range(MAX_CANDIDATES))
    all_labels = tuple(_candidate_label(index) for index in range(MAX_CANDIDATES))
    plans: list[ControlledCasePlan] = []
    dataset_cases: list[dict[str, Any]] = []

    for index in range(CASE_COUNT):
        metadata_poor = index < METADATA_POOR_CASE_COUNT
        no_result = index >= CASE_COUNT - 2
        tags = _case_tags(index, metadata_poor=metadata_poor)
        if "candidate_budget_5000" in tags:
            candidate_indices = tuple(range(MAX_CANDIDATES))
            target_index: int | None = 0
        elif no_result:
            candidate_indices = tuple(range(4_700 + (index - 28) * 5, 4_705 + (index - 28) * 5))
            target_index = None
        else:
            target_index = index
            candidate_indices = (target_index,) + tuple(
                range(200 + index * 4, 204 + index * 4)
            )

        candidate_ids = tuple(all_ids[item] for item in candidate_indices)
        candidate_labels = tuple(all_labels[item] for item in candidate_indices)
        expected_relevant = (
            (_candidate_label(target_index),) if target_index is not None else ()
        )
        if no_result:
            baseline_ranked: tuple[str, ...] = ()
        elif metadata_poor:
            baseline_ranked = candidate_labels[1:]
        else:
            baseline_ranked = (expected_relevant[0],)

        case_id = f"{_CASE_PREFIX}{index + 1:03d}"
        plans.append(
            ControlledCasePlan(
                case_id=case_id,
                tags=tags,
                metadata_poor=metadata_poor,
                candidate_ids=candidate_ids,
                candidate_labels=candidate_labels,
                expected_relevant=expected_relevant,
                baseline_ranked=baseline_ranked,
            )
        )
        dataset_cases.append(
            {
                "case_id": case_id,
                "case_tags": list(tags),
                "metadata_poor": metadata_poor,
                "query": f"controlled-topic-{index + 1}",
                "candidate_labels": list(candidate_labels),
                "expected_relevant": list(expected_relevant),
                "authorized_candidate_count": len(candidate_ids),
            }
        )

    return (
        {
            "schema_version": _DATASET_SCHEMA_VERSION,
            "data_classification": "synthetic_non_secret",
            "cases": dataset_cases,
        },
        plans,
    )


def _create_ephemeral_schema(connection: Any, schema_name: str) -> None:
    connection.exec_driver_sql(f'CREATE SCHEMA "{schema_name}"')
    connection.exec_driver_sql(f'SET LOCAL search_path TO "{schema_name}", public')
    connection.exec_driver_sql(
        """
        CREATE TABLE knowledge_bases (
            id uuid PRIMARY KEY,
            organization_id uuid NOT NULL,
            embedding_model text NOT NULL,
            lifecycle_state text NOT NULL,
            sync_state text NOT NULL,
            active_document_version_id uuid NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE documents (
            id uuid PRIMARY KEY,
            knowledge_base_id uuid NOT NULL,
            status text NOT NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE document_versions (
            id uuid PRIMARY KEY,
            knowledge_base_id uuid NOT NULL,
            organization_id uuid NOT NULL,
            status text NOT NULL,
            embedding_model text NULL
        )
        """
    )
    connection.exec_driver_sql(
        """
        CREATE TABLE document_chunks (
            id uuid PRIMARY KEY,
            document_id uuid NOT NULL,
            document_version_id uuid NULL,
            knowledge_base_id uuid NOT NULL,
            content text NOT NULL,
            embedding vector NOT NULL,
            chunk_level text NULL
        )
        """
    )


def _seed_controlled_candidates(connection: Any) -> uuid.UUID:
    organization_id = uuid.uuid5(uuid.NAMESPACE_URL, "mba342-v3-organization")
    candidate_ids = tuple(_candidate_id(index) for index in range(MAX_CANDIDATES))
    target_ids = {_candidate_id(index) for index in range(CASE_COUNT - 2)}
    kb_rows = [
        {
            "id": candidate_id,
            "organization_id": organization_id,
            "embedding_model": _EMBEDDING_MODEL,
            "lifecycle_state": "active",
            "sync_state": "synced",
        }
        for candidate_id in candidate_ids
    ]
    document_rows = [
        {
            "id": uuid.uuid5(uuid.NAMESPACE_URL, f"mba342-v3-document-{index}"),
            "knowledge_base_id": candidate_id,
            "status": "completed",
        }
        for index, candidate_id in enumerate(candidate_ids)
    ]
    chunk_rows = [
        {
            "id": uuid.uuid5(uuid.NAMESPACE_URL, f"mba342-v3-parent-{index}"),
            "document_id": document_rows[index]["id"],
            "knowledge_base_id": candidate_id,
            "content": "controlled synthetic parent",
            "embedding": "[1,0,0]" if candidate_id in target_ids else "[0,1,0]",
            "chunk_level": "parent",
        }
        for index, candidate_id in enumerate(candidate_ids)
    ]
    connection.execute(
        text(
            "INSERT INTO knowledge_bases "
            "(id, organization_id, embedding_model, lifecycle_state, sync_state) "
            "VALUES (:id, :organization_id, :embedding_model, :lifecycle_state, :sync_state)"
        ),
        kb_rows,
    )
    connection.execute(
        text(
            "INSERT INTO documents (id, knowledge_base_id, status) "
            "VALUES (:id, :knowledge_base_id, :status)"
        ),
        document_rows,
    )
    connection.execute(
        text(
            "INSERT INTO document_chunks "
            "(id, document_id, knowledge_base_id, content, embedding, chunk_level) "
            "VALUES (:id, :document_id, :knowledge_base_id, :content, "
            "CAST(:embedding AS vector), :chunk_level)"
        ),
        chunk_rows,
    )
    return organization_id


def _rank_parent_scores(
    plan: ControlledCasePlan,
    result: Any,
) -> list[str]:
    positions = {candidate_id: index for index, candidate_id in enumerate(plan.candidate_ids)}
    label_by_id = dict(zip(plan.candidate_ids, plan.candidate_labels, strict=True))
    ranked = [
        score
        for score in result.scores
        if score.semantic_state == "available"
        and score.parent_relevance is not None
        and score.parent_relevance > 0
    ]
    ranked.sort(
        key=lambda score: (-float(score.parent_relevance), positions[score.knowledge_base_id])
    )
    return [label_by_id[score.knowledge_base_id] for score in ranked[:5]]


def _run_adapter_for_plan(
    *,
    connection: Any,
    organization_id: uuid.UUID,
    plan: ControlledCasePlan,
    query_counter: _SqlCounter,
) -> dict[str, Any]:
    query_counter.reset()
    resolver = _StaticEmbeddingResolver()
    caller_session = Session(bind=connection, autoflush=False, expire_on_commit=False)

    def retrieval_session_factory() -> Session:
        return Session(bind=connection, autoflush=False, expire_on_commit=False)

    try:
        adapter = PostgresParentRecommendationAdapter(
            caller_session,
            embedding_resolver=resolver,
            retrieval_session_factory=retrieval_session_factory,
        )
        request = KnowledgeRecommendationRetrievalRequest(
            organization_id=organization_id,
            actor_id=uuid.uuid5(uuid.NAMESPACE_URL, "mba342-v3-actor"),
            safe_query_topics=("controlled-topic",),
            candidate_kb_ids=plan.candidate_ids,
            candidate_snapshot_ref="controlled-synthetic-snapshot",
        )
        started = time.perf_counter()
        result = adapter.retrieve(request)
        latency_ms = max(0, round((time.perf_counter() - started) * 1000))
    finally:
        caller_session.close()

    if (
        query_counter.discovery != 1
        or query_counter.parent != 1
        or query_counter.other_selects != 0
        or resolver.calls != 1
        or resolver.provider_calls != 0
        or result.cohort_count_bucket != "one"
    ):
        raise ControlledBenchmarkBlocked("adapter_query_contract_unavailable")

    return {
        "ranked_labels": _rank_parent_scores(plan, result),
        "latency_ms": latency_ms,
        "processed_cohort_count": 1,
        "embedding_calls": resolver.calls,
        "discovery_sql": query_counter.discovery,
        "parent_sql": query_counter.parent,
        "candidate_sql": query_counter.other_selects,
        "leakage_count": 0,
        "provider_calls": resolver.provider_calls,
    }


def _safe_gate_metrics(gate_report: dict[str, Any]) -> dict[str, Any]:
    return {
        "passed": bool(gate_report["passed"]),
        "case_count": int(gate_report["case_count"]),
        "metadata_poor_case_count": int(gate_report["metadata_poor_case_count"]),
        "baseline": dict(gate_report["baseline"]),
        "parent_first": dict(gate_report["parent_first"]),
        "metadata_poor": dict(gate_report["metadata_poor"]),
        "operational": dict(gate_report["operational"]),
        "failed_gates": list(gate_report["failed_gates"]),
    }


def build_controlled_db_report(
    *,
    gate_report: dict[str, Any],
    provider_calls: int,
    synthetic_embedding_resolver_calls: int,
) -> dict[str, Any]:
    """Project only aggregate metrics; never serialize evaluator inputs."""

    safe_metrics = _safe_gate_metrics(gate_report)
    report = {
        "schema_version": "mba-342-controlled-db-evidence-v1",
        "data_classification": CONTROLLED_DB_DATA_CLASSIFICATION,
        "evidence_scope": "controlled_db_not_release_evidence",
        "status": (
            "controlled_db_gate_passed"
            if safe_metrics["passed"]
            else "controlled_db_gate_failed"
        ),
        "release_ready": False,
        "provider_calls": int(provider_calls),
        "synthetic_embedding_resolver_calls": int(
            synthetic_embedding_resolver_calls
        ),
        "authorization_scope": "pre_authorized_synthetic_candidate_snapshot",
        "persistence": "ephemeral_schema_transaction_rollback",
        "metrics": safe_metrics,
    }
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    forbidden_fragments = (
        "candidate_labels",
        "expected_relevant",
        '"query"',
        "embedding_vector",
        _CANDIDATE_LABEL_PREFIX,
        "controlled-topic",
    )
    if any(fragment in serialized for fragment in forbidden_fragments):
        raise ControlledBenchmarkBlocked("report_redaction_contract_unavailable")
    return report


def run_controlled_postgres_benchmark(engine: Engine) -> dict[str, Any]:
    """Run adapter SQL in an ephemeral schema and always roll it back."""

    dataset, plans = build_controlled_case_plan()
    schema_name = f"mba342_v3_{uuid.uuid4().hex[:16]}"
    baseline_observations: list[dict[str, Any]] = []
    parent_observations: list[dict[str, Any]] = []
    provider_calls = 0
    synthetic_embedding_resolver_calls = 0

    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                _create_ephemeral_schema(connection, schema_name)
                organization_id = _seed_controlled_candidates(connection)
                query_counter = _SqlCounter()
                event.listen(connection, "before_cursor_execute", query_counter.observe)
                try:
                    for plan in plans:
                        parent_observation = _run_adapter_for_plan(
                            connection=connection,
                            organization_id=organization_id,
                            plan=plan,
                            query_counter=query_counter,
                        )
                        provider_calls += parent_observation.pop("provider_calls")
                        synthetic_embedding_resolver_calls += parent_observation[
                            "embedding_calls"
                        ]
                        baseline_observations.append(
                            {
                                "case_id": plan.case_id,
                                "ranked_labels": list(plan.baseline_ranked),
                                "authorized_candidate_count": len(plan.candidate_ids),
                            }
                        )
                        parent_observations.append(
                            {
                                "case_id": plan.case_id,
                                "ranked_labels": parent_observation["ranked_labels"],
                                "authorized_candidate_count": len(plan.candidate_ids),
                                "latency_ms": parent_observation["latency_ms"],
                                "processed_cohort_count": parent_observation[
                                    "processed_cohort_count"
                                ],
                                "embedding_calls": parent_observation[
                                    "embedding_calls"
                                ],
                                "discovery_sql": parent_observation["discovery_sql"],
                                "parent_sql": parent_observation["parent_sql"],
                                "candidate_sql": parent_observation["candidate_sql"],
                                "leakage_count": parent_observation["leakage_count"],
                            }
                        )
                finally:
                    event.remove(connection, "before_cursor_execute", query_counter.observe)
            finally:
                transaction.rollback()
    except ControlledBenchmarkBlocked:
        raise
    except SQLAlchemyError as exc:
        raise ControlledBenchmarkBlocked("controlled_postgres_unavailable") from exc

    evidence = collect_evidence(dataset, baseline_observations, parent_observations)
    gate_report = evaluate_release_gates(evidence)
    return build_controlled_db_report(
        gate_report=gate_report,
        provider_calls=provider_calls,
        synthetic_embedding_resolver_calls=synthetic_embedding_resolver_calls,
    )


def _blocked_report(reason: str) -> dict[str, Any]:
    return {
        "schema_version": "mba-342-controlled-db-evidence-v1",
        "data_classification": CONTROLLED_DB_DATA_CLASSIFICATION,
        "evidence_scope": "controlled_db_not_release_evidence",
        "status": "blocked",
        "release_ready": False,
        "blocker": reason,
    }


def _write_report(report: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(serialized, end="")
    else:
        output.write_text(serialized, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--run-controlled-postgres",
        action="store_true",
        help="allow ephemeral synthetic PostgreSQL schema creation and rollback",
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)

    if not args.run_controlled_postgres:
        _write_report(_blocked_report("opt_in_flag_required"), args.output)
        return 2

    try:
        from apps.shared.db.session import engine

        report = run_controlled_postgres_benchmark(engine)
    except ControlledBenchmarkBlocked as exc:
        _write_report(_blocked_report(str(exc)), args.output)
        return 2

    _write_report(report, args.output)
    return 0 if report["metrics"]["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
