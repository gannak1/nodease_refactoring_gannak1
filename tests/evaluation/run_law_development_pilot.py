"""Prepare paired law indexes, execute actual retrieval, and render a safe report."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select, text

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.shared.db.models.knowledge import KnowledgeBase
from apps.shared.db.session import SessionLocal
from apps.shared.services.llm_client.openai_client import OpenAIClient
from apps.workflow_engine.services.retrieval import RetrievalService
from tests.evaluation.law_development_pilot import (
    PilotDbManifest,
    TimedRetriever,
    build_article_parents,
    build_exploratory_result,
    load_pilot_inputs,
    manifest_to_json,
    pilot_dataset_hash,
    prepare_db_indexes,
    prepare_embedding_cache,
    render_exploratory_reports,
    timing_rows,
)
from tests.evaluation.paired_runner import (
    PairedBenchmarkRunner,
    RunnerConfig,
    WorkflowRetrievalAdapter,
)
from tests.evaluation.protocol import atomic_create_json, canonical_hash
from tests.evaluation.retrieval_observer import EvaluationRetrievalDiagnostics
from tests.evaluation.schemas import ArtifactLineage, FrozenProtocol


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _safe_status(**values) -> None:
    print(json.dumps(values, ensure_ascii=True, sort_keys=True))


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()


def _source_fingerprint() -> str:
    paths = (
        "apps/shared/services/rag_retrieval_diagnostics.py",
        "apps/workflow_engine/services/retrieval.py",
        "tests/evaluation/law_development_pilot.py",
        "tests/evaluation/paired_metrics.py",
        "tests/evaluation/paired_runner.py",
        "tests/evaluation/paired_statistics.py",
        "tests/evaluation/retrieval_observer.py",
        "tests/evaluation/run_law_development_pilot.py",
        "tests/evaluation/schemas.py",
    )
    rows = []
    for relative in paths:
        payload = (REPOSITORY_ROOT / relative).read_bytes()
        rows.append(
            {
                "path": relative,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    return canonical_hash(rows)


def _migration_head(db) -> str:
    rows = db.execute(text("SELECT version_num FROM alembic_version")).all()
    versions = sorted(str(row[0]) for row in rows)
    if len(versions) != 1:
        raise ValueError("pilot_database_not_single_head")
    return versions[0]


def _protocol(
    *,
    config: RunnerConfig,
    code_commit: str,
    migration_head: str,
    inputs,
) -> FrozenProtocol:
    split_hash = canonical_hash(
        [
            {
                "question_id": question.question_id,
                "sampling_cluster_ref": question.sampling_cluster_ref,
                "split": question.split,
            }
            for question in inputs.questions
        ]
    )
    return FrozenProtocol.model_validate(
        {
            "schema_version": "1",
            "estimand": "controlled_child_boundary_retrieval_effect",
            "study_phase": "development",
            "code_commit": code_commit,
            "migration_head": migration_head,
            "retrieval_config_hash": canonical_hash(config),
            "model_contract": {
                "safe_model_id": "text-embedding-3-small",
                "immutable_version": "provider-alias-unpinned",
                "dimension": 1536,
                "score_normalization_version": "workflow-rrf-v1",
            },
            "retrieval_controls": {
                "hybrid_search": config.hybrid_search,
                "use_rerank": False,
                "use_rewrite": False,
                "top_k": config.top_k,
                "threshold": config.threshold,
                "source_tier_policy": config.source_tier_policy,
            },
            "primary_metric": "answerable_cluster_macro_recall_at_5",
            "decision_gates": {
                "confidence_level": 0.95,
                "bootstrap_iterations": 1000,
                "recall_superiority_margin": 0.03,
                "safety_noninferiority_margin": 0.05,
                "latency_ratio_noninferiority_margin": 1.30,
                "mrr_consistency_margin": 0.01,
                "win_tie_loss_epsilon": 0.0,
                "fixed_order": [
                    "recall_superiority",
                    "safety_noninferiority",
                    "latency_noninferiority",
                    "mrr_consistency",
                ],
            },
            "sample_size_plan": {
                "method": "development-fixed-100-v1",
                "alpha": 0.05,
                "power": 0.8,
                "target_recall_delta": 0.03,
                "paired_sd_delta": 0.15,
                "cluster_design_effect": 1.0,
                "planned_n": len(inputs.questions),
                "planned_answerable_n": sum(
                    question.answerable for question in inputs.questions
                ),
                "planned_unanswerable_n": sum(
                    not question.answerable for question in inputs.questions
                ),
            },
            "cluster_plan": {
                "minimum_independent_clusters": 30,
                "maximum_questions_per_cluster": max(
                    sum(
                        item.sampling_cluster_ref == question.sampling_cluster_ref
                        for item in inputs.questions
                    )
                    for question in inputs.questions
                ),
                "equal_weight": True,
            },
            "split_hash": split_hash,
            "pooling_plan": {
                "depth": 5,
                "blind_projection_version": "blind-v1",
                "adjudication_version": "adjudication-v1",
            },
            "tie_policy": {
                "score_precision": 8,
                "complete_tie_group_cap": 100,
                "expected_metric_version": "expected_tie_permutation_v1",
            },
            "retry_attrition_policy": {
                "max_attempts_per_condition": config.max_attempts,
                "symmetric": True,
                "complete_pair_required": True,
            },
            "latency_plan": {
                "method": "question_session_median_ratio_v1",
                "repeats_per_session": 5,
                "session_count": 3,
                "randomized_ab_ba": True,
                "monotonic_clock": True,
                "target_ratio_ci_half_width": 0.10,
                "environment_profile_id": "local-docker-development",
                "cache_profile_id": "uncontrolled-single-pass",
                "connection_pool_profile_id": "sqlalchemy-default",
            },
            "permission_batch_limit": 10,
            "exclusion_policy": ["policy.revoked", "readiness.failed"],
            "seeds": {"split": 1, "order": config.seed, "pool": 3, "bootstrap": 279},
        }
    )


def _verify_reusable_manifest(db, manifest: PilotDbManifest) -> None:
    rows = db.execute(
        select(KnowledgeBase).where(
            KnowledgeBase.id.in_((manifest.flat_kb_id, manifest.hierarchical_kb_id))
        )
    ).scalars().all()
    if len(rows) != 2:
        raise ValueError("pilot_db_manifest_resource_missing")
    if any(
        row.lifecycle_state != "active"
        or row.user_id != manifest.actor_user_id
        or row.organization_id != manifest.organization_id
        for row in rows
    ):
        raise ValueError("pilot_db_manifest_scope_mismatch")


def _execute(args: argparse.Namespace) -> None:
    if args.env_file:
        load_dotenv(Path(args.env_file), override=False)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("pilot_openai_credential_missing")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    inputs = load_pilot_inputs(args.snapshot_dir, args.bundle_dir)
    parents, child_to_parent, parent_fingerprint = build_article_parents(
        inputs.children,
        target_chars=args.parent_target_chars,
    )
    client = OpenAIClient(
        model_id=args.embedding_model,
        credentials={"apiKey": api_key, "baseUrl": base_url},
    )
    vectors = asyncio.run(
        prepare_embedding_cache(
            client=client,
            inputs=inputs,
            parents=parents,
            cache_dir=run_root / "embedding-cache",
            embedding_model=args.embedding_model,
            batch_size=args.batch_size,
        )
    )
    if vectors.children.shape[1] != 1536:
        raise ValueError("pilot_unexpected_embedding_dimension")

    db = SessionLocal()
    try:
        manifest_path = run_root / "db-index-manifest.json"
        if manifest_path.exists():
            manifest = PilotDbManifest.model_validate(
                json.loads(manifest_path.read_text(encoding="utf-8"))
            )
            _verify_reusable_manifest(db, manifest)
        else:
            manifest = prepare_db_indexes(
                db=db,
                run_id=args.run_id,
                inputs=inputs,
                parents=parents,
                child_to_parent=child_to_parent,
                vectors=vectors,
                embedding_model=args.embedding_model,
                parent_builder_fingerprint=parent_fingerprint,
            )
            atomic_create_json(manifest_path, manifest_to_json(manifest))

        config = RunnerConfig(
            seed=279,
            study_phase="development",
            top_k=5,
            threshold=args.threshold,
            hybrid_search=args.hybrid_search,
            use_rerank=False,
            use_rewrite=False,
            max_attempts=1,
            source_tier_policy="ignore",
        )
        code_commit = _git_commit()
        protocol = _protocol(
            config=config,
            code_commit=code_commit,
            migration_head=_migration_head(db),
            inputs=inputs,
        )
        if protocol.model_contract.dimension != manifest.vector_dimension:
            raise ValueError("pilot_protocol_vector_dimension_mismatch")
        protocol_path = run_root / "protocol.json"
        if protocol_path.exists():
            stored_protocol = FrozenProtocol.model_validate(
                json.loads(protocol_path.read_text(encoding="utf-8"))
            )
            if stored_protocol != protocol:
                raise ValueError("pilot_protocol_changed")
        else:
            atomic_create_json(protocol_path, protocol)

        evidence_mapping = {
            "flat": manifest.flat_evidence_mapping,
            "hierarchical": manifest.hierarchical_evidence_mapping,
        }
        diagnostics = EvaluationRetrievalDiagnostics.from_protocol(
            evidence_mapping=evidence_mapping,
            protocol=protocol,
        )
        service = RetrievalService(
            db,
            manifest.actor_user_id,
            organization_id=manifest.organization_id,
            retrieval_diagnostics=diagnostics,
        )

        expected_ids = {
            "flat": manifest.flat_kb_id,
            "hierarchical": manifest.hierarchical_kb_id,
        }

        def preflight(condition: str, kb_id: str) -> None:
            if str(expected_ids[condition]) != str(kb_id):
                raise ValueError("pilot_kb_condition_mismatch")
            kb = db.get(KnowledgeBase, expected_ids[condition])
            if (
                kb is None
                or kb.lifecycle_state != "active"
                or kb.user_id != manifest.actor_user_id
                or kb.organization_id != manifest.organization_id
                or kb.safe_metadata.get("benchmark_fingerprint")
                != manifest.benchmark_fingerprint
            ):
                raise ValueError("pilot_kb_preflight_failed")

        adapter = WorkflowRetrievalAdapter(
            service=service,
            knowledge_base_ids={
                "flat": str(manifest.flat_kb_id),
                "hierarchical": str(manifest.hierarchical_kb_id),
            },
            evidence_mapping=evidence_mapping,
            preflight=preflight,
            diagnostics=diagnostics,
        )
        timed = TimedRetriever(adapter)
        vectors_by_query = {
            question.query: vectors.queries[index].tolist()
            for index, question in enumerate(inputs.questions)
        }
        lineage = ArtifactLineage(
            protocol_hash=canonical_hash(protocol),
            dataset_hash=pilot_dataset_hash(inputs),
            split_hash=protocol.split_hash,
            config_hash=canonical_hash(config),
            code_commit=code_commit,
            source_equality_verified=manifest.source_equality_verified,
            child_boundary_equality_verified=manifest.child_boundary_equality_verified,
            child_vector_equality=manifest.child_vector_equality,
            segmentation_contract_version="public-law-section-atomic-v1",
            vector_equality_check_version="exact-float32-db-roundtrip-v1",
            parent_builder_fingerprint=manifest.parent_builder_fingerprint,
        )
        runner = PairedBenchmarkRunner(
            retriever=timed,
            embed_query=lambda query: vectors_by_query[query],
            config=config,
            protocol=protocol,
        )
        run = runner.run(
            inputs.questions,
            run_id=args.run_id,
            artifact_lineage=lineage,
        )
        atomic_create_json(run_root / "retrieval-run.json", run)
        atomic_create_json(run_root / "timings.json", timing_rows(timed.records))
        result = build_exploratory_result(
            run=run,
            timings=timed.records,
            manifest=manifest,
            code_commit=code_commit,
            working_tree_diff_hash=_source_fingerprint(),
            source_snapshot_hash=inputs.question_summary.base_snapshot_hash,
            question_draft_hash=inputs.question_summary.question_draft_hash,
            embedding_model=args.embedding_model,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            controls={
                "top_k": config.top_k,
                "threshold": config.threshold,
                "hybrid_search": config.hybrid_search,
                "use_rerank": config.use_rerank,
                "use_rewrite": config.use_rewrite,
                "source_tier_policy": config.source_tier_policy,
                "parent_target_chars": args.parent_target_chars,
            },
            score_precision=protocol.tie_policy.score_precision,
        )
        render_exploratory_reports(result, run_root / "reports")
        _safe_status(
            status="law_development_pilot_completed",
            question_count=result.question_count,
            complete_pair_count=result.complete_pair_count,
            flat_recall_at_5=round(result.flat.recall_at_5, 6),
            hierarchical_recall_at_5=round(result.hierarchical.recall_at_5, 6),
            cluster_macro_delta=round(result.cluster_macro_recall_delta, 6),
            exploratory=True,
        )
    finally:
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Execute the actual public-law development retrieval pilot"
    )
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--parent-target-chars", type=int, default=2000)
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument(
        "--hybrid-search",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    parser.set_defaults(handler=_execute)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except Exception as exc:
        _safe_status(status="error", reason="law_development_pilot_failed", error_type=type(exc).__name__)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
