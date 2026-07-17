"""Execute a real-DB chunk profile retrieval ablation on prepared safe corpora."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

import numpy as np
import tiktoken
from dotenv import load_dotenv
from sqlalchemy import delete, func, insert, select, text
from sqlalchemy.orm import Session

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from apps.shared.db.models.knowledge import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    SourceType,
)
from apps.shared.db.models.organization_membership import OrganizationMembership
from apps.shared.services.llm_client.openai_client import OpenAIClient
from apps.workflow_engine.services.retrieval import RetrievalService
from tests.evaluation.chunk_profile_experiment import (
    DEFAULT_PROFILE_SPECS,
    ChunkProfileExperimentResult,
    ChunkProfileInputs,
    ChunkProfileSpec,
    ProfileChunk,
    RankedProfileChunk,
    SCORE_PRECISION,
    aggregate_profile_metrics,
    build_profile_chunks,
    evaluate_question_profile,
    load_chunk_profile_inputs,
    render_chunk_profile_report,
)
from tests.evaluation.protocol import atomic_create_json, canonical_hash


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
PROFILE_NAMESPACE = uuid.UUID("462a4b73-0820-42c0-bddd-93bd9f667a87")
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


class BatchEmbeddingClient(Protocol):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


@dataclass(frozen=True)
class ProfileVectors:
    queries: np.ndarray
    profiles: Mapping[str, np.ndarray]


@dataclass(frozen=True)
class ProfileDbIndex:
    actor_user_id: uuid.UUID
    organization_id: uuid.UUID
    kb_ids: Mapping[str, uuid.UUID]
    chunks_by_id: Mapping[str, Mapping[str, ProfileChunk]]


def _safe_status(**values: Any) -> None:
    print(json.dumps(values, ensure_ascii=True, sort_keys=True))


def _git_commit() -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY_ROOT, text=True
    ).strip()


def _source_fingerprint() -> str:
    paths = (
        "apps/workflow_engine/services/retrieval.py",
        "tests/evaluation/chunk_profile_experiment.py",
        "tests/evaluation/run_chunk_profile_experiment.py",
        "tests/evaluation/paired_statistics.py",
    )
    rows = [
        {
            "path": relative,
            "sha256": "sha256:"
            + hashlib.sha256((REPOSITORY_ROOT / relative).read_bytes()).hexdigest(),
        }
        for relative in paths
    ]
    return canonical_hash(rows)


def _migration_head(db: Session) -> str:
    versions = sorted(
        str(row[0]) for row in db.execute(text("SELECT version_num FROM alembic_version"))
    )
    if len(versions) != 1:
        raise ValueError("profile_database_not_single_head")
    return versions[0]


def _stable_uuid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(PROFILE_NAMESPACE, ":".join(parts))


def _content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _save_array(path: Path, values: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            np.save(handle, values.astype(np.float32, copy=False), allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


async def _embed_with_retry(
    client: BatchEmbeddingClient,
    texts: list[str],
    *,
    attempts: int = 3,
) -> np.ndarray:
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            rows = await client.embed_batch(texts)
            values = np.asarray(rows, dtype=np.float32)
            if (
                values.ndim != 2
                or values.shape[0] != len(texts)
                or not np.isfinite(values).all()
            ):
                raise ValueError("profile_embedding_shape_invalid")
            return values
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(2**attempt)
    raise RuntimeError("profile_embedding_batch_failed") from last_error


async def prepare_profile_embedding_cache(
    *,
    client: BatchEmbeddingClient,
    inputs: ChunkProfileInputs,
    chunks_by_profile: Mapping[str, Sequence[ProfileChunk]],
    cache_dir: Path,
    embedding_model: str,
    batch_size: int,
) -> ProfileVectors:
    if batch_size < 1 or batch_size > 512:
        raise ValueError("invalid_profile_embedding_batch_size")
    groups: dict[str, tuple[list[str], list[str]]] = {
        "queries": (
            [question.query for question in inputs.questions],
            [question.question_id for question in inputs.questions],
        )
    }
    for profile_id, chunks in chunks_by_profile.items():
        groups[profile_id] = (
            [chunk.content for chunk in chunks],
            [chunk.chunk_ref for chunk in chunks],
        )
    plan = {
        "schema_version": "chunk_profile_embedding_cache_v1",
        "embedding_model": embedding_model,
        "batch_size": batch_size,
        "source_snapshot_hash": inputs.source_snapshot_hash,
        "question_draft_hash": inputs.question_draft_hash,
        "groups": {
            group: {
                "count": len(texts),
                "text_hash": canonical_hash(
                    [
                        {"ref": ref, "content_hash": _content_hash(content)}
                        for content, ref in zip(texts, refs)
                    ]
                ),
            }
            for group, (texts, refs) in groups.items()
        },
    }
    cache_dir.mkdir(parents=True, exist_ok=True)
    plan_path = cache_dir / "plan.json"
    if plan_path.exists():
        if json.loads(plan_path.read_text(encoding="utf-8")) != plan:
            raise ValueError("profile_embedding_cache_plan_mismatch")
    else:
        atomic_create_json(plan_path, plan)

    arrays: dict[str, np.ndarray] = {}
    for group, (texts, _refs) in groups.items():
        batches: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            stop = min(len(texts), start + batch_size)
            batch_path = cache_dir / f"{group}-{start:05d}-{stop:05d}.npy"
            if batch_path.exists():
                values = np.load(batch_path, allow_pickle=False)
                if values.ndim != 2 or values.shape[0] != stop - start:
                    raise ValueError("profile_embedding_cache_batch_invalid")
            else:
                values = await _embed_with_retry(client, texts[start:stop])
                _save_array(batch_path, values)
            batches.append(values.astype(np.float32, copy=False))
        arrays[group] = np.concatenate(batches, axis=0)
    dimensions = {array.shape[1] for array in arrays.values()}
    if len(dimensions) != 1:
        raise ValueError("profile_embedding_dimension_mismatch")
    return ProfileVectors(
        queries=arrays.pop("queries"),
        profiles=dict(arrays),
    )


def _active_evaluation_actor(db: Session) -> tuple[uuid.UUID, uuid.UUID]:
    row = db.execute(
        select(OrganizationMembership.user_id, OrganizationMembership.organization_id)
        .where(OrganizationMembership.membership_state == "active")
        .order_by(OrganizationMembership.created_at, OrganizationMembership.id)
        .limit(1)
    ).first()
    if row is None:
        raise ValueError("profile_active_organization_member_missing")
    return row.user_id, row.organization_id


def _insert_batches(db: Session, rows: Sequence[dict[str, Any]], *, size: int = 100) -> None:
    for start in range(0, len(rows), size):
        db.execute(insert(DocumentChunk.__table__), list(rows[start : start + size]))


def prepare_profile_db_indexes(
    *,
    db: Session,
    run_id: str,
    inputs: ChunkProfileInputs,
    specs: Sequence[ChunkProfileSpec],
    chunks_by_profile: Mapping[str, Sequence[ProfileChunk]],
    vectors: ProfileVectors,
    embedding_model: str,
) -> ProfileDbIndex:
    actor_user_id, organization_id = _active_evaluation_actor(db)
    kb_ids = {
        spec.profile_id: _stable_uuid(run_id, spec.profile_id, "kb") for spec in specs
    }
    existing = db.scalar(
        select(func.count()).select_from(KnowledgeBase).where(
            KnowledgeBase.id.in_(tuple(kb_ids.values()))
        )
    )
    if existing:
        raise FileExistsError("profile_db_indexes_exist")
    source_refs = tuple(dict.fromkeys(atom.source_ref for atom in inputs.atoms))
    chunks_by_id: dict[str, dict[str, ProfileChunk]] = {}
    try:
        for spec in specs:
            profile_id = spec.profile_id
            kb_id = kb_ids[profile_id]
            db.add(
                KnowledgeBase(
                    id=kb_id,
                    organization_id=organization_id,
                    user_id=actor_user_id,
                    name=f"[EVAL] {run_id} {profile_id}",
                    description="MBA-279 ignored-local chunk profile benchmark",
                    safe_metadata={
                        "benchmark": "chunk_profile_ablation",
                        "evaluation_run_id": run_id,
                        "profile_id": profile_id,
                    },
                    embedding_model=embedding_model,
                    top_k=5,
                    similarity_threshold=0.0,
                    sync_state="manual",
                    lifecycle_state="active",
                )
            )
        db.flush()

        document_ids: dict[tuple[str, str], uuid.UUID] = {}
        for spec in specs:
            profile_id = spec.profile_id
            for source_ref in source_refs:
                document_id = _stable_uuid(run_id, profile_id, "document", source_ref)
                document_ids[(profile_id, source_ref)] = document_id
                source_digest = hashlib.sha256(source_ref.encode("ascii")).hexdigest()
                db.add(
                    Document(
                        id=document_id,
                        knowledge_base_id=kb_ids[profile_id],
                        filename=f"eval-{source_digest[:16]}.json",
                        source_type=SourceType.API,
                        content_hash=source_digest,
                        status="completed",
                        chunk_size=spec.target_tokens or 0,
                        chunk_overlap=0,
                        meta_info={
                            "evaluation_run_id": run_id,
                            "profile_id": profile_id,
                        },
                        embedding_model=embedding_model,
                    )
                )
        db.flush()

        for spec in specs:
            profile_id = spec.profile_id
            chunks = chunks_by_profile[profile_id]
            profile_vectors = vectors.profiles[profile_id]
            if profile_vectors.shape[0] != len(chunks):
                raise ValueError("profile_chunk_vector_count_mismatch")
            mapping: dict[str, ProfileChunk] = {}
            rows: list[dict[str, Any]] = []
            for index, chunk in enumerate(chunks):
                chunk_id = _stable_uuid(run_id, profile_id, "chunk", chunk.chunk_ref)
                mapping[str(chunk_id)] = chunk
                rows.append(
                    {
                        "id": chunk_id,
                        "document_id": document_ids[(profile_id, chunk.source_ref)],
                        "document_version_id": None,
                        "knowledge_base_id": kb_ids[profile_id],
                        "content": chunk.content,
                        "embedding": profile_vectors[index].tolist(),
                        "chunk_index": chunk.ordinal,
                        "parent_chunk_id": None,
                        "chunk_level": "flat",
                        "section_path": list(chunk.hierarchy_path),
                        "heading": (
                            chunk.hierarchy_path[-1][:512]
                            if chunk.hierarchy_path
                            else None
                        ),
                        "token_count": chunk.token_count,
                        "metadata": {
                            "evaluation_run_id": run_id,
                            "profile_id": profile_id,
                            "chunk_ref": chunk.chunk_ref,
                        },
                    }
                )
            _insert_batches(db, rows)
            chunks_by_id[profile_id] = mapping
        db.commit()
    except Exception:
        db.rollback()
        raise
    return ProfileDbIndex(
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        kb_ids=kb_ids,
        chunks_by_id=chunks_by_id,
    )


def cleanup_profile_db_indexes(db: Session, index: ProfileDbIndex, run_id: str) -> None:
    try:
        kb_ids = tuple(index.kb_ids.values())
        rows = list(
            db.scalars(select(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))
        )
        for kb in rows:
            if kb.safe_metadata.get("evaluation_run_id") != run_id:
                raise ValueError("profile_cleanup_scope_mismatch")
            if kb.safe_metadata.get("benchmark") != "chunk_profile_ablation":
                raise ValueError("profile_cleanup_benchmark_mismatch")
        db.execute(
            delete(DocumentChunk).where(DocumentChunk.knowledge_base_id.in_(kb_ids))
        )
        db.execute(delete(Document).where(Document.knowledge_base_id.in_(kb_ids)))
        db.execute(delete(KnowledgeBase).where(KnowledgeBase.id.in_(kb_ids)))
        db.commit()
    except Exception:
        db.rollback()
        raise


def _atomic_create_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            raise ValueError("artifact_output_exists") from None
    finally:
        if temporary.exists():
            temporary.unlink()


def _execute(args: argparse.Namespace) -> None:
    if args.env_file:
        load_dotenv(Path(args.env_file), override=False)
    # DB settings are read at apps.shared.db.session import time.
    from apps.shared.db.session import SessionLocal

    if SAFE_RUN_ID.fullmatch(args.run_id) is None:
        raise ValueError("invalid_profile_run_id")
    if not 5 <= args.retrieval_depth <= 100:
        raise ValueError("invalid_profile_retrieval_depth")
    if not 64 <= args.context_budget_tokens <= 32_768:
        raise ValueError("invalid_profile_context_budget")
    if not 1_000 <= args.bootstrap_iterations <= 100_000:
        raise ValueError("invalid_profile_bootstrap_iterations")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("profile_openai_credential_missing")
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    run_root = Path(args.run_root)
    run_root.mkdir(parents=True, exist_ok=True)
    result_path = run_root / "result.json"
    if result_path.exists():
        raise ValueError("artifact_output_exists")

    inputs = load_chunk_profile_inputs(args.snapshot_dir, args.bundle_dir)
    encoder = tiktoken.get_encoding(args.tokenizer)
    specs = DEFAULT_PROFILE_SPECS
    chunks_by_profile = {
        spec.profile_id: build_profile_chunks(inputs, spec, encoder) for spec in specs
    }
    client = OpenAIClient(
        model_id=args.embedding_model,
        credentials={"apiKey": api_key, "baseUrl": base_url},
    )
    vectors = asyncio.run(
        prepare_profile_embedding_cache(
            client=client,
            inputs=inputs,
            chunks_by_profile=chunks_by_profile,
            cache_dir=run_root / "embedding-cache",
            embedding_model=args.embedding_model,
            batch_size=args.batch_size,
        )
    )
    if vectors.queries.shape[0] != len(inputs.questions):
        raise ValueError("profile_query_vector_count_mismatch")
    if vectors.queries.shape[1] != 1_536:
        raise ValueError("profile_unexpected_embedding_dimension")

    db = SessionLocal()
    index: ProfileDbIndex | None = None
    try:
        migration_head = _migration_head(db)
        index = prepare_profile_db_indexes(
            db=db,
            run_id=args.run_id,
            inputs=inputs,
            specs=specs,
            chunks_by_profile=chunks_by_profile,
            vectors=vectors,
            embedding_model=args.embedding_model,
        )
        service = RetrievalService(
            db,
            index.actor_user_id,
            organization_id=index.organization_id,
        )
        metrics_by_profile: dict[str, list] = {
            spec.profile_id: [] for spec in specs
        }
        for question_index, question in enumerate(inputs.questions):
            query_vector = vectors.queries[question_index].tolist()
            for spec in specs:
                profile_id = spec.profile_id
                started = time.perf_counter()
                previews = service.search_documents_sync(
                    question.query,
                    knowledge_base_id=index.kb_ids[profile_id],
                    top_k=args.retrieval_depth,
                    threshold=0.0,
                    hybrid_search=args.hybrid_search,
                    use_rerank=False,
                    hierarchy_mode="flat",
                    source_tier_policy="ignore",
                    query_vector=query_vector,
                )
                duration_ms = (time.perf_counter() - started) * 1_000
                mapping = index.chunks_by_id[profile_id]
                candidates: list[RankedProfileChunk] = []
                for preview in previews:
                    chunk = mapping.get(str(preview.chunk_id))
                    if chunk is None:
                        raise ValueError("profile_retrieval_mapping_missing")
                    candidates.append(
                        RankedProfileChunk(
                            chunk_ref=chunk.chunk_ref,
                            ordinal=chunk.ordinal,
                            score=float(preview.score),
                            token_count=chunk.token_count,
                            evidence_refs=chunk.evidence_refs,
                            content_fingerprint=chunk.content_fingerprint,
                        )
                    )
                metrics_by_profile[profile_id].append(
                    evaluate_question_profile(
                        question=question,
                        candidates=candidates,
                        context_budget_tokens=args.context_budget_tokens,
                        latency_ms=duration_ms,
                    )
                )

        aggregates = aggregate_profile_metrics(
            specs=specs,
            chunks_by_profile=chunks_by_profile,
            metrics_by_profile=metrics_by_profile,
            bootstrap_iterations=args.bootstrap_iterations,
            seed=args.seed,
        )
        result = ChunkProfileExperimentResult(
            run_id=args.run_id,
            generated_at_utc=datetime.now(timezone.utc).isoformat(),
            code_commit=_git_commit(),
            source_fingerprint=_source_fingerprint(),
            source_snapshot_hash=inputs.source_snapshot_hash,
            question_draft_hash=inputs.question_draft_hash,
            corpus_id=inputs.corpus_id,
            content_class=inputs.content_class,
            embedding_model=args.embedding_model,
            tokenizer=args.tokenizer,
            retrieval_controls={
                "migration_head": migration_head,
                "hybrid_search": args.hybrid_search,
                "threshold": 0.0,
                "rerank": False,
                "rewrite": False,
                "hierarchy_mode": "flat",
                "retrieval_depth": args.retrieval_depth,
                "metric_depth": 5,
                "score_precision": SCORE_PRECISION,
                "context_budget_tokens": args.context_budget_tokens,
                "source_tier_policy": "ignore",
                "seed": args.seed,
                "bootstrap_iterations": args.bootstrap_iterations,
            },
            question_count=len(inputs.questions),
            answerable_count=sum(question.answerable for question in inputs.questions),
            sampling_cluster_count=len(
                {question.sampling_cluster_ref for question in inputs.questions}
            ),
            profiles=aggregates,
            question_metrics={
                profile_id: tuple(rows)
                for profile_id, rows in metrics_by_profile.items()
            },
            limitations=(
                "development_questions_not_unseen_holdout",
                "machine_authored_required_evidence_not_human_reviewed",
                "embedding_model_alias_not_immutable",
                "retrieval_only_no_generation_quality_measurement",
                "deterministic_score_tie_break_not_confirmatory_tie_expectation",
                "single_pass_latency_not_latency_evidence",
                "tested_document_types_limited_to_structured_law_and_policy",
            ),
        )
        atomic_create_json(result_path, result)
        _atomic_create_text(run_root / "report.md", render_chunk_profile_report(result))
        _safe_status(
            status="chunk_profile_experiment_completed",
            corpus_id=result.corpus_id,
            question_count=result.question_count,
            profiles={
                profile.profile_id: round(profile.budget_recall, 6)
                for profile in result.profiles
            },
            exploratory=True,
        )
    finally:
        if index is not None:
            cleanup_profile_db_indexes(db, index, args.run_id)
        db.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a real-DB development chunk profile ablation"
    )
    parser.add_argument("--snapshot-dir", required=True)
    parser.add_argument("--bundle-dir", required=True)
    parser.add_argument("--run-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--env-file")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--tokenizer", default="cl100k_base")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--retrieval-depth", type=int, default=100)
    parser.add_argument("--context-budget-tokens", type=int, default=2_048)
    parser.add_argument("--bootstrap-iterations", type=int, default=1_000)
    parser.add_argument("--seed", type=int, default=279)
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
        _safe_status(
            status="error",
            reason="chunk_profile_experiment_failed",
            error_type=type(exc).__name__,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
