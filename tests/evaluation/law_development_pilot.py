"""Actual development-only Flat/Hierarchical retrieval pilot for public law data.

The module deliberately keeps resource IDs, vectors, source text, and queries in
ignored local artifacts. Sanitized reports contain aggregate metrics only. The
machine-authored required evidence remains provisional until human review.
"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import math
import os
import re
import tempfile
import time
import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Protocol

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from apps.shared.db.models.knowledge import (
    Document,
    DocumentChunk,
    KnowledgeBase,
    SourceType,
)
from apps.shared.db.models.organization_membership import OrganizationMembership
from tests.evaluation.corpus_authoring import PreparedCorpusSummary
from tests.evaluation.law_question_authoring import LawQuestionDraftSummary
from tests.evaluation.paired_metrics import (
    RankedEvidence,
    required_full_coverage_probability,
    tie_aware_metrics,
)
from tests.evaluation.paired_statistics import (
    PairedDelta,
    cluster_bca_interval,
    win_tie_loss,
)
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import BenchmarkQuestion, BenchmarkRun


PILOT_NAMESPACE = uuid.UUID("9a42ea4e-a6d5-4ca0-8b3e-5d91ca9a9279")
SAFE_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
ARTICLE_KEY = re.compile(r"^(article-[0-9]+)")
CHUNK_ID_ORDERING_VERSION = "shared-logical-ordinal-uuid-v1"
UUID_ORDINAL_BITS = 48


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class PilotDbManifest(_StrictModel):
    schema_version: str = "law_development_db_index_v2"
    run_id: str
    benchmark_fingerprint: str
    flat_kb_id: uuid.UUID
    hierarchical_kb_id: uuid.UUID
    actor_user_id: uuid.UUID
    organization_id: uuid.UUID
    child_count: int = Field(ge=1)
    parent_count: int = Field(ge=1)
    vector_dimension: int = Field(ge=1)
    source_count: int = Field(ge=1)
    child_vector_hash: str
    parent_vector_hash: str
    parent_builder_fingerprint: str
    chunk_id_ordering_version: str
    source_equality_verified: bool
    child_boundary_equality_verified: bool
    child_vector_equality: bool
    flat_evidence_mapping: dict[str, str]
    hierarchical_evidence_mapping: dict[str, str]


class ConditionAggregate(_StrictModel):
    hit_at_5: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    mrr_at_5: float = Field(ge=0, le=1)
    multi_evidence_full_coverage: float = Field(ge=0, le=1)
    non_empty_unanswerable_rate: float = Field(ge=0, le=1)
    latency_p50_ms: float = Field(ge=0)
    latency_p95_ms: float = Field(ge=0)


class CategoryAggregate(_StrictModel):
    category: str
    question_count: int = Field(ge=1)
    flat_recall_at_5: float = Field(ge=0, le=1)
    hierarchical_recall_at_5: float = Field(ge=0, le=1)
    delta: float = Field(ge=-1, le=1)


class PilotResult(_StrictModel):
    schema_version: str = "law_development_exploratory_result_v2"
    status: str = "exploratory_unreviewed_labels"
    run_id: str
    generated_at_utc: str
    code_commit: str
    working_tree_diff_hash: str
    source_snapshot_hash: str
    question_draft_hash: str
    embedding_model: str
    embedding_model_version: str
    parent_builder_fingerprint: str
    chunk_id_ordering_version: str
    question_count: int
    answerable_count: int
    unanswerable_count: int
    sampling_cluster_count: int
    child_count: int
    parent_count: int
    vector_dimension: int
    controls: dict[str, Any]
    equality: dict[str, bool]
    complete_pair_count: int
    attrition: dict[str, int]
    flat: ConditionAggregate
    hierarchical: ConditionAggregate
    cluster_macro_recall_delta: float
    question_micro_recall_delta: float
    recall_delta_ci_lower: float
    recall_delta_ci_upper: float
    recall_delta_ci_method: str
    recall_delta_exploratory: bool
    wins: int
    ties: int
    losses: int
    categories: tuple[CategoryAggregate, ...]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_counts(self) -> "PilotResult":
        if self.answerable_count + self.unanswerable_count != self.question_count:
            raise ValueError("pilot_question_count_mismatch")
        return self


@dataclass(frozen=True)
class PilotChild:
    evidence_ref: str
    source_ref: str
    ordinal: int
    section_key: str
    content_hash: str
    content: str
    hierarchy_path: tuple[str, ...]


@dataclass(frozen=True)
class PilotParent:
    parent_ref: str
    source_ref: str
    ordinal: int
    content: str
    hierarchy_path: tuple[str, ...]
    child_refs: tuple[str, ...]


@dataclass(frozen=True)
class PilotInputs:
    source_summary: PreparedCorpusSummary
    question_summary: LawQuestionDraftSummary
    children: tuple[PilotChild, ...]
    questions: tuple[BenchmarkQuestion, ...]


@dataclass(frozen=True)
class PilotVectors:
    children: np.ndarray
    parents: np.ndarray
    queries: np.ndarray
    child_vector_hash: str
    parent_vector_hash: str
    query_vector_hash: str


@dataclass(frozen=True)
class TimingRecord:
    condition: str
    question_id: str
    duration_ms: float
    succeeded: bool


class BatchEmbeddingClient(Protocol):
    async def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _content_hash(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _array_hash(values: np.ndarray, refs: Sequence[str]) -> str:
    digest = hashlib.sha256()
    digest.update(str(values.shape).encode("ascii"))
    digest.update(values.astype(np.float32, copy=False).tobytes(order="C"))
    for ref in refs:
        digest.update(ref.encode("ascii"))
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def _atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


def load_pilot_inputs(snapshot_dir: str | Path, bundle_dir: str | Path) -> PilotInputs:
    snapshot = Path(snapshot_dir)
    bundle = Path(bundle_dir)
    source_summary = PreparedCorpusSummary.model_validate(_json(snapshot / "summary.json"))
    question_summary = LawQuestionDraftSummary.model_validate(_json(bundle / "summary.json"))
    canonical_rows = _jsonl(snapshot / "canonical_children.jsonl")
    index_rows = _jsonl(snapshot / "index_input.jsonl")
    question_rows = _jsonl(bundle / "question_draft.jsonl")

    if canonical_hash(canonical_rows) != source_summary.canonical_children_hash:
        raise ValueError("pilot_canonical_hash_mismatch")
    if canonical_hash(question_rows) != question_summary.question_draft_hash:
        raise ValueError("pilot_question_hash_mismatch")
    expected_base_hash = canonical_hash(
        {
            "canonical_children_hash": source_summary.canonical_children_hash,
            "source_manifest_hash": source_summary.source_manifest_hash,
        }
    )
    if question_summary.base_snapshot_hash != expected_base_hash:
        raise ValueError("pilot_base_snapshot_hash_mismatch")
    if len(canonical_rows) != len(index_rows):
        raise ValueError("pilot_child_count_mismatch")

    canonical = {row["evidence_ref"]: row for row in canonical_rows}
    if len(canonical) != len(canonical_rows):
        raise ValueError("pilot_duplicate_canonical_evidence")
    index = {row["evidence_ref"]: row for row in index_rows}
    if len(index) != len(index_rows) or set(index) != set(canonical):
        raise ValueError("pilot_index_evidence_set_mismatch")

    children: list[PilotChild] = []
    for position, row in enumerate(index_rows):
        canonical_row = canonical[row["evidence_ref"]]
        content = row["content"]
        if not isinstance(content, str) or _content_hash(content) != canonical_row["content_hash"]:
            raise ValueError("pilot_index_content_hash_mismatch")
        children.append(
            PilotChild(
                evidence_ref=row["evidence_ref"],
                source_ref=row["safe_source_ref"],
                ordinal=position,
                section_key=row["section_key"],
                content_hash=canonical_row["content_hash"],
                content=content,
                hierarchy_path=tuple(str(item) for item in row["hierarchy_path"]),
            )
        )

    questions = tuple(BenchmarkQuestion.model_validate(row) for row in question_rows)
    if len(questions) != question_summary.question_count:
        raise ValueError("pilot_question_count_mismatch")
    known_refs = set(canonical)
    if any(
        evidence_ref not in known_refs
        for question in questions
        for evidence_ref in question.required_evidence_refs
    ):
        raise ValueError("pilot_question_evidence_missing")
    return PilotInputs(
        source_summary=source_summary,
        question_summary=question_summary,
        children=tuple(children),
        questions=questions,
    )


def pilot_dataset_hash(inputs: PilotInputs) -> str:
    """Hash the validated pilot labels using JSON-native values only."""
    return canonical_hash(
        {
            "summary": inputs.question_summary.model_dump(mode="json"),
            "questions": [
                question.model_dump(mode="json") for question in inputs.questions
            ],
        }
    )


def build_article_parents(
    children: Sequence[PilotChild],
    *,
    target_chars: int = 2_000,
) -> tuple[tuple[PilotParent, ...], dict[str, str], str]:
    if target_chars < 500 or target_chars > 20_000:
        raise ValueError("invalid_parent_target_chars")
    grouped: dict[tuple[str, str], list[PilotChild]] = {}
    for child in children:
        match = ARTICLE_KEY.match(child.section_key)
        article_key = match.group(1) if match else child.section_key
        grouped.setdefault((child.source_ref, article_key), []).append(child)

    parents: list[PilotParent] = []
    child_to_parent: dict[str, str] = {}
    for (_source_ref, _article_key), group in grouped.items():
        current: list[PilotChild] = []
        current_chars = 0

        def flush() -> None:
            nonlocal current, current_chars
            if not current:
                return
            key = "|".join(child.evidence_ref for child in current)
            parent_ref = f"parent_{hashlib.sha256(key.encode('ascii')).hexdigest()[:32]}"
            content = "\n\n".join(child.content for child in current)
            parents.append(
                PilotParent(
                    parent_ref=parent_ref,
                    source_ref=current[0].source_ref,
                    ordinal=len(parents),
                    content=content,
                    hierarchy_path=current[0].hierarchy_path[:2]
                    or current[0].hierarchy_path,
                    child_refs=tuple(child.evidence_ref for child in current),
                )
            )
            for child in current:
                if child.evidence_ref in child_to_parent:
                    raise ValueError("pilot_child_parent_duplicate")
                child_to_parent[child.evidence_ref] = parent_ref
            current = []
            current_chars = 0

        for child in group:
            added = len(child.content) + (2 if current else 0)
            if current and current_chars + added > target_chars:
                flush()
            current.append(child)
            current_chars += len(child.content) + (2 if len(current) > 1 else 0)
        flush()

    if set(child_to_parent) != {child.evidence_ref for child in children}:
        raise ValueError("pilot_child_parent_coverage_mismatch")
    fingerprint = canonical_hash(
        {
            "algorithm": "article_contiguous_greedy_v1",
            "target_chars": target_chars,
            "parents": [
                {
                    "parent_ref": parent.parent_ref,
                    "source_ref": parent.source_ref,
                    "child_refs": list(parent.child_refs),
                }
                for parent in parents
            ],
        }
    )
    return tuple(parents), child_to_parent, fingerprint


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
            if values.ndim != 2 or values.shape[0] != len(texts) or not np.isfinite(values).all():
                raise ValueError("pilot_embedding_shape_invalid")
            return values
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await asyncio.sleep(2**attempt)
    raise RuntimeError("pilot_embedding_batch_failed") from last_error


def _save_array(path: Path, values: np.ndarray) -> None:
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            np.save(handle, values.astype(np.float32, copy=False), allow_pickle=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


async def prepare_embedding_cache(
    *,
    client: BatchEmbeddingClient,
    inputs: PilotInputs,
    parents: Sequence[PilotParent],
    cache_dir: str | Path,
    embedding_model: str,
    batch_size: int = 256,
) -> PilotVectors:
    if batch_size < 1 or batch_size > 512:
        raise ValueError("invalid_embedding_batch_size")
    target = Path(cache_dir)
    target.mkdir(parents=True, exist_ok=True)
    kinds: dict[str, tuple[list[str], list[str]]] = {
        "children": (
            [child.content for child in inputs.children],
            [child.evidence_ref for child in inputs.children],
        ),
        "parents": (
            [parent.content for parent in parents],
            [parent.parent_ref for parent in parents],
        ),
        "queries": (
            [question.query for question in inputs.questions],
            [question.question_id for question in inputs.questions],
        ),
    }
    plan = {
        "schema_version": "law_embedding_cache_v1",
        "embedding_model": embedding_model,
        "batch_size": batch_size,
        "source_snapshot_hash": inputs.question_summary.base_snapshot_hash,
        "question_draft_hash": inputs.question_summary.question_draft_hash,
        "groups": {
            kind: {
                "count": len(texts),
                "text_hash": canonical_hash(
                    [
                        {"ref": ref, "content_hash": _content_hash(text)}
                        for text, ref in zip(texts, refs)
                    ]
                ),
            }
            for kind, (texts, refs) in kinds.items()
        },
    }
    plan_path = target / "plan.json"
    if plan_path.exists():
        if _json(plan_path) != plan:
            raise ValueError("pilot_embedding_cache_plan_mismatch")
    else:
        _atomic_json(plan_path, plan)

    combined: dict[str, np.ndarray] = {}
    for kind, (texts, _refs) in kinds.items():
        batches: list[np.ndarray] = []
        for start in range(0, len(texts), batch_size):
            stop = min(len(texts), start + batch_size)
            batch_path = target / f"{kind}-{start:05d}-{stop:05d}.npy"
            if batch_path.exists():
                values = np.load(batch_path, allow_pickle=False)
                if values.ndim != 2 or values.shape[0] != stop - start:
                    raise ValueError("pilot_embedding_cache_batch_invalid")
            else:
                values = await _embed_with_retry(client, texts[start:stop])
                _save_array(batch_path, values)
            batches.append(values.astype(np.float32, copy=False))
        combined[kind] = np.concatenate(batches, axis=0)

    dimensions = {values.shape[1] for values in combined.values()}
    if len(dimensions) != 1:
        raise ValueError("pilot_embedding_dimension_mismatch")
    result = PilotVectors(
        children=combined["children"],
        parents=combined["parents"],
        queries=combined["queries"],
        child_vector_hash=_array_hash(combined["children"], kinds["children"][1]),
        parent_vector_hash=_array_hash(combined["parents"], kinds["parents"][1]),
        query_vector_hash=_array_hash(combined["queries"], kinds["queries"][1]),
    )
    _atomic_json(
        target / "summary.json",
        {
            "schema_version": "law_embedding_cache_summary_v1",
            "embedding_model": embedding_model,
            "dimension": combined["children"].shape[1],
            "child_count": combined["children"].shape[0],
            "parent_count": combined["parents"].shape[0],
            "query_count": combined["queries"].shape[0],
            "child_vector_hash": result.child_vector_hash,
            "parent_vector_hash": result.parent_vector_hash,
            "query_vector_hash": result.query_vector_hash,
        },
    )
    return result


def _stable_uuid(*parts: str) -> uuid.UUID:
    return uuid.uuid5(PILOT_NAMESPACE, ":".join(parts))


def ordered_chunk_uuid(
    run_id: str,
    condition: str,
    chunk_kind: str,
    ordinal: int,
) -> uuid.UUID:
    """Create unique UUIDs whose relative order follows the shared logical ordinal."""
    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("invalid_pilot_run_id")
    if condition not in {"flat", "hierarchical"}:
        raise ValueError("invalid_pilot_condition")
    if chunk_kind not in {"child", "parent"}:
        raise ValueError("invalid_pilot_chunk_kind")
    if ordinal < 0 or ordinal >= 1 << UUID_ORDINAL_BITS:
        raise ValueError("invalid_pilot_chunk_ordinal")
    prefix = _stable_uuid(run_id, condition, chunk_kind, "ordered")
    suffix_mask = (1 << UUID_ORDINAL_BITS) - 1
    return uuid.UUID(int=(prefix.int & ~suffix_mask) | ordinal)


def _insert_batches(db: Session, rows: Sequence[dict[str, Any]], *, size: int = 100) -> None:
    for start in range(0, len(rows), size):
        db.execute(insert(DocumentChunk.__table__), list(rows[start : start + size]))


def _active_evaluation_actor(db: Session) -> tuple[uuid.UUID, uuid.UUID]:
    row = db.execute(
        select(OrganizationMembership.user_id, OrganizationMembership.organization_id)
        .where(OrganizationMembership.membership_state == "active")
        .order_by(OrganizationMembership.created_at, OrganizationMembership.id)
        .limit(1)
    ).first()
    if row is None:
        raise ValueError("pilot_active_organization_member_missing")
    return row.user_id, row.organization_id


def prepare_db_indexes(
    *,
    db: Session,
    run_id: str,
    inputs: PilotInputs,
    parents: Sequence[PilotParent],
    child_to_parent: Mapping[str, str],
    vectors: PilotVectors,
    embedding_model: str,
    parent_builder_fingerprint: str,
) -> PilotDbManifest:
    if SAFE_RUN_ID.fullmatch(run_id) is None:
        raise ValueError("invalid_pilot_run_id")
    if vectors.children.shape[0] != len(inputs.children):
        raise ValueError("pilot_child_vector_count_mismatch")
    if vectors.parents.shape[0] != len(parents):
        raise ValueError("pilot_parent_vector_count_mismatch")
    if vectors.children.shape[1] != vectors.parents.shape[1]:
        raise ValueError("pilot_index_vector_dimension_mismatch")

    actor_user_id, organization_id = _active_evaluation_actor(db)
    benchmark_fingerprint = canonical_hash(
        {
            "run_id": run_id,
            "base_snapshot_hash": inputs.question_summary.base_snapshot_hash,
            "question_draft_hash": inputs.question_summary.question_draft_hash,
            "embedding_model": embedding_model,
            "child_vector_hash": vectors.child_vector_hash,
            "parent_vector_hash": vectors.parent_vector_hash,
            "parent_builder_fingerprint": parent_builder_fingerprint,
            "chunk_id_ordering_version": CHUNK_ID_ORDERING_VERSION,
        }
    )
    flat_kb_id = _stable_uuid(run_id, "flat", "kb")
    hierarchical_kb_id = _stable_uuid(run_id, "hierarchical", "kb")
    if db.scalar(
        select(func.count()).select_from(KnowledgeBase).where(
            KnowledgeBase.id.in_((flat_kb_id, hierarchical_kb_id))
        )
    ):
        raise FileExistsError("pilot_db_indexes_exist")

    source_refs = list(dict.fromkeys(child.source_ref for child in inputs.children))
    flat_documents = {
        source_ref: _stable_uuid(run_id, "flat", "document", source_ref)
        for source_ref in source_refs
    }
    hierarchical_documents = {
        source_ref: _stable_uuid(run_id, "hierarchical", "document", source_ref)
        for source_ref in source_refs
    }
    safe_metadata = {
        "benchmark": "flat_hierarchical_law_development",
        "evaluation_run_id": run_id,
        "benchmark_fingerprint": benchmark_fingerprint,
    }
    try:
        db.add_all(
            [
                KnowledgeBase(
                    id=flat_kb_id,
                    organization_id=organization_id,
                    user_id=actor_user_id,
                    name=f"[EVAL] {run_id} Flat",
                    description="MBA-279 ignored-local development benchmark",
                    safe_metadata={**safe_metadata, "condition": "flat"},
                    embedding_model=embedding_model,
                    top_k=5,
                    similarity_threshold=0.0,
                    sync_state="manual",
                    lifecycle_state="active",
                ),
                KnowledgeBase(
                    id=hierarchical_kb_id,
                    organization_id=organization_id,
                    user_id=actor_user_id,
                    name=f"[EVAL] {run_id} Hierarchical",
                    description="MBA-279 ignored-local development benchmark",
                    safe_metadata={**safe_metadata, "condition": "hierarchical"},
                    embedding_model=embedding_model,
                    top_k=5,
                    similarity_threshold=0.0,
                    sync_state="manual",
                    lifecycle_state="active",
                ),
            ]
        )
        db.flush()
        for source_ref in source_refs:
            source_digest = hashlib.sha256(source_ref.encode("ascii")).hexdigest()
            db.add_all(
                [
                    Document(
                        id=flat_documents[source_ref],
                        knowledge_base_id=flat_kb_id,
                        filename=f"eval-{source_digest[:16]}.json",
                        source_type=SourceType.API,
                        content_hash=source_digest,
                        status="completed",
                        chunk_size=0,
                        chunk_overlap=0,
                        meta_info={"evaluation_run_id": run_id},
                        embedding_model=embedding_model,
                    ),
                    Document(
                        id=hierarchical_documents[source_ref],
                        knowledge_base_id=hierarchical_kb_id,
                        filename=f"eval-{source_digest[:16]}.json",
                        source_type=SourceType.API,
                        content_hash=source_digest,
                        status="completed",
                        chunk_size=0,
                        chunk_overlap=0,
                        meta_info={"evaluation_run_id": run_id},
                        embedding_model=embedding_model,
                    ),
                ]
            )
        db.flush()

        flat_mapping: dict[str, str] = {}
        hierarchical_mapping: dict[str, str] = {}
        flat_rows: list[dict[str, Any]] = []
        hierarchical_child_rows: list[dict[str, Any]] = []
        parent_rows: list[dict[str, Any]] = []
        parent_ids = {
            parent.parent_ref: ordered_chunk_uuid(
                run_id,
                "hierarchical",
                "parent",
                index,
            )
            for index, parent in enumerate(parents)
        }
        for index, parent in enumerate(parents):
            parent_rows.append(
                {
                    "id": parent_ids[parent.parent_ref],
                    "document_id": hierarchical_documents[parent.source_ref],
                    "document_version_id": None,
                    "knowledge_base_id": hierarchical_kb_id,
                    "content": parent.content,
                    "embedding": vectors.parents[index].tolist(),
                    "chunk_index": parent.ordinal,
                    "parent_chunk_id": None,
                    "chunk_level": "parent",
                    "section_path": list(parent.hierarchy_path),
                    "heading": parent.hierarchy_path[-1][:512]
                    if parent.hierarchy_path
                    else None,
                    "token_count": max(1, len(parent.content.split())),
                    "metadata": {"evaluation_run_id": run_id},
                }
            )
        for index, child in enumerate(inputs.children):
            flat_id = ordered_chunk_uuid(run_id, "flat", "child", index)
            hierarchical_id = ordered_chunk_uuid(
                run_id,
                "hierarchical",
                "child",
                index,
            )
            flat_mapping[str(flat_id)] = child.evidence_ref
            hierarchical_mapping[str(hierarchical_id)] = child.evidence_ref
            common = {
                "document_version_id": None,
                "content": child.content,
                "embedding": vectors.children[index].tolist(),
                "chunk_index": child.ordinal,
                "section_path": list(child.hierarchy_path),
                "heading": child.hierarchy_path[-1][:512]
                if child.hierarchy_path
                else None,
                "token_count": max(1, len(child.content.split())),
                "metadata": {
                    "evaluation_run_id": run_id,
                    "evidence_ref": child.evidence_ref,
                },
            }
            flat_rows.append(
                {
                    **common,
                    "id": flat_id,
                    "document_id": flat_documents[child.source_ref],
                    "knowledge_base_id": flat_kb_id,
                    "parent_chunk_id": None,
                    "chunk_level": "flat",
                }
            )
            hierarchical_child_rows.append(
                {
                    **common,
                    "id": hierarchical_id,
                    "document_id": hierarchical_documents[child.source_ref],
                    "knowledge_base_id": hierarchical_kb_id,
                    "parent_chunk_id": parent_ids[child_to_parent[child.evidence_ref]],
                    "chunk_level": "child",
                }
            )
        _insert_batches(db, parent_rows)
        _insert_batches(db, flat_rows)
        _insert_batches(db, hierarchical_child_rows)
        db.commit()
    except Exception:
        db.rollback()
        raise

    flat_vectors = {
        str(row.id): np.asarray(row.embedding, dtype=np.float32)
        for row in db.execute(
            select(DocumentChunk.id, DocumentChunk.embedding).where(
                DocumentChunk.knowledge_base_id == flat_kb_id,
                DocumentChunk.chunk_level == "flat",
            )
        )
    }
    hierarchical_vectors = {
        str(row.id): np.asarray(row.embedding, dtype=np.float32)
        for row in db.execute(
            select(DocumentChunk.id, DocumentChunk.embedding).where(
                DocumentChunk.knowledge_base_id == hierarchical_kb_id,
                DocumentChunk.chunk_level == "child",
            )
        )
    }
    vector_equal = len(flat_vectors) == len(hierarchical_vectors) == len(inputs.children)
    if vector_equal:
        for index, child in enumerate(inputs.children):
            flat_id = str(ordered_chunk_uuid(run_id, "flat", "child", index))
            hierarchical_id = str(
                ordered_chunk_uuid(run_id, "hierarchical", "child", index)
            )
            if not (
                np.array_equal(flat_vectors[flat_id], vectors.children[index])
                and np.array_equal(hierarchical_vectors[hierarchical_id], vectors.children[index])
                and np.array_equal(flat_vectors[flat_id], hierarchical_vectors[hierarchical_id])
            ):
                vector_equal = False
                break
    if not vector_equal:
        raise ValueError("pilot_db_child_vector_equality_failed")

    return PilotDbManifest(
        run_id=run_id,
        benchmark_fingerprint=benchmark_fingerprint,
        flat_kb_id=flat_kb_id,
        hierarchical_kb_id=hierarchical_kb_id,
        actor_user_id=actor_user_id,
        organization_id=organization_id,
        child_count=len(inputs.children),
        parent_count=len(parents),
        vector_dimension=vectors.children.shape[1],
        source_count=len(source_refs),
        child_vector_hash=vectors.child_vector_hash,
        parent_vector_hash=vectors.parent_vector_hash,
        parent_builder_fingerprint=parent_builder_fingerprint,
        chunk_id_ordering_version=CHUNK_ID_ORDERING_VERSION,
        source_equality_verified=True,
        child_boundary_equality_verified=True,
        child_vector_equality=True,
        flat_evidence_mapping=flat_mapping,
        hierarchical_evidence_mapping=hierarchical_mapping,
    )


class TimedRetriever:
    def __init__(self, delegate: Any) -> None:
        self.delegate = delegate
        self.records: list[TimingRecord] = []

    def retrieve(self, **kwargs: Any) -> Any:
        started = time.perf_counter_ns()
        succeeded = False
        try:
            result = self.delegate.retrieve(**kwargs)
            succeeded = True
            return result
        finally:
            self.records.append(
                TimingRecord(
                    condition=kwargs["condition"],
                    question_id=kwargs["question"].question_id,
                    duration_ms=(time.perf_counter_ns() - started) / 1_000_000,
                    succeeded=succeeded,
                )
            )


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = probability * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    fraction = position - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


def _question_metrics(
    outcome: Any,
    required: Sequence[str],
    *,
    score_precision: int,
) -> tuple[float, float, float, float]:
    required_set = set(required)
    candidates = [
        RankedEvidence(item.evidence_ref, item.score) for item in outcome.evidence
    ]
    metrics = tie_aware_metrics(
        candidates,
        required_set,
        required_refs=required_set,
        answerable=True,
        k=5,
        score_precision=score_precision,
        tie_group_truncated=outcome.tie_group_truncated,
    )
    full_coverage = required_full_coverage_probability(
        candidates,
        required_set,
        k=5,
        score_precision=score_precision,
        tie_group_truncated=outcome.tie_group_truncated,
    )
    return metrics.hit, metrics.recall, metrics.mrr, full_coverage


def build_exploratory_result(
    *,
    run: BenchmarkRun,
    timings: Sequence[TimingRecord],
    manifest: PilotDbManifest,
    code_commit: str,
    working_tree_diff_hash: str,
    source_snapshot_hash: str,
    question_draft_hash: str,
    embedding_model: str,
    generated_at_utc: str,
    controls: Mapping[str, Any],
    score_precision: int = 8,
) -> PilotResult:
    if controls.get("top_k") != 5:
        raise ValueError("pilot_report_requires_top_k_five")
    answerable = [sample for sample in run.samples if sample.answerable]
    unanswerable = [sample for sample in run.samples if not sample.answerable]
    per_condition: dict[str, list[tuple[float, float, float, float, bool]]] = {
        "flat": [],
        "hierarchical": [],
    }
    deltas: list[PairedDelta] = []
    category_rows: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for sample in answerable:
        flat_metric = _question_metrics(
            sample.flat,
            sample.required_evidence_refs,
            score_precision=score_precision,
        )
        hierarchical_metric = _question_metrics(
            sample.hierarchical,
            sample.required_evidence_refs,
            score_precision=score_precision,
        )
        is_multi = len(sample.required_evidence_refs) > 1
        per_condition["flat"].append((*flat_metric, is_multi))
        per_condition["hierarchical"].append((*hierarchical_metric, is_multi))
        delta = hierarchical_metric[1] - flat_metric[1]
        deltas.append(
            PairedDelta(
                question_id=sample.question_id,
                cluster_ref=sample.sampling_cluster_ref,
                delta=delta,
            )
        )
        category_rows[sample.category].append((flat_metric[1], hierarchical_metric[1]))

    interval = cluster_bca_interval(deltas, iterations=1_000, seed=279)
    wtl = win_tie_loss([row.delta for row in deltas], epsilon=0.0)
    timings_by_condition = {
        condition: [
            row.duration_ms
            for row in timings
            if row.condition == condition and row.succeeded
        ]
        for condition in ("flat", "hierarchical")
    }

    def aggregate(condition: str) -> ConditionAggregate:
        rows = per_condition[condition]
        multi_rows = [row for row in rows if row[4]]
        unanswerable_non_empty = [
            bool(getattr(sample, condition).evidence) for sample in unanswerable
        ]
        latencies = timings_by_condition[condition]
        return ConditionAggregate(
            hit_at_5=mean(row[0] for row in rows),
            recall_at_5=mean(row[1] for row in rows),
            mrr_at_5=mean(row[2] for row in rows),
            multi_evidence_full_coverage=(mean(row[3] for row in multi_rows) if multi_rows else 0.0),
            non_empty_unanswerable_rate=(
                mean(unanswerable_non_empty) if unanswerable_non_empty else 0.0
            ),
            latency_p50_ms=median(latencies) if latencies else 0.0,
            latency_p95_ms=_quantile(latencies, 0.95),
        )

    categories = tuple(
        CategoryAggregate(
            category=category,
            question_count=len(rows),
            flat_recall_at_5=mean(row[0] for row in rows),
            hierarchical_recall_at_5=mean(row[1] for row in rows),
            delta=mean(row[1] - row[0] for row in rows),
        )
        for category, rows in sorted(category_rows.items())
    )
    return PilotResult(
        run_id=run.run_id,
        generated_at_utc=generated_at_utc,
        code_commit=code_commit,
        working_tree_diff_hash=working_tree_diff_hash,
        source_snapshot_hash=source_snapshot_hash,
        question_draft_hash=question_draft_hash,
        embedding_model=embedding_model,
        embedding_model_version="provider-alias-unpinned",
        parent_builder_fingerprint=manifest.parent_builder_fingerprint,
        chunk_id_ordering_version=manifest.chunk_id_ordering_version,
        question_count=len(run.samples),
        answerable_count=len(answerable),
        unanswerable_count=len(unanswerable),
        sampling_cluster_count=len({sample.sampling_cluster_ref for sample in run.samples}),
        child_count=manifest.child_count,
        parent_count=manifest.parent_count,
        vector_dimension=manifest.vector_dimension,
        controls=dict(controls),
        equality={
            "source": manifest.source_equality_verified,
            "child_boundary": manifest.child_boundary_equality_verified,
            "child_vector": manifest.child_vector_equality,
        },
        complete_pair_count=run.complete_pair_count,
        attrition=run.attrition,
        flat=aggregate("flat"),
        hierarchical=aggregate("hierarchical"),
        cluster_macro_recall_delta=interval.point,
        question_micro_recall_delta=interval.question_micro,
        recall_delta_ci_lower=interval.lower,
        recall_delta_ci_upper=interval.upper,
        recall_delta_ci_method=interval.method,
        recall_delta_exploratory=interval.exploratory,
        wins=wtl.wins,
        ties=wtl.ties,
        losses=wtl.losses,
        categories=categories,
        limitations=(
            "machine_authored_required_evidence_not_human_reviewed",
            "six_source_clusters_below_confirmatory_floor",
            "embedding_model_alias_not_immutable",
            "single_pass_latency_not_protocol_latency_evidence",
            "development_questions_not_unseen_holdout",
            "unanswerable_rate_is_non_empty_retrieval_not_false_positive_rate",
        ),
    )


def _percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def render_exploratory_reports(result: PilotResult, output_dir: str | Path) -> tuple[Path, Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    result_path = target / "result.json"
    markdown_path = target / "report.md"
    html_path = target / "report.html"
    _atomic_json(result_path, result.model_dump(mode="json"))

    category_lines = [
        "| Category | N | Flat Recall@5 | Hierarchical Recall@5 | Delta |",
        "| --- | ---: | ---: | ---: | ---: |",
        *[
            f"| {row.category} | {row.question_count} | {_percent(row.flat_recall_at_5)} | {_percent(row.hierarchical_recall_at_5)} | {_percent(row.delta)} |"
            for row in result.categories
        ],
    ]
    markdown = "\n".join(
        [
            "# Flat·Hierarchical RAG Public-Law Development Pilot",
            "",
            "> Exploratory only. Required evidence is machine-authored and has not completed human review.",
            "",
            "## Result Summary",
            "",
            f"- Flat Recall@5: **{_percent(result.flat.recall_at_5)}**",
            f"- Hierarchical Recall@5: **{_percent(result.hierarchical.recall_at_5)}**",
            f"- Cluster-macro delta (Hierarchical - Flat): **{_percent(result.cluster_macro_recall_delta)}**",
            f"- Exploratory 95% CI: **[{_percent(result.recall_delta_ci_lower)}, {_percent(result.recall_delta_ci_upper)}]**",
            f"- Win / Tie / Loss: **{result.wins} / {result.ties} / {result.losses}**",
            f"- Complete pairs: **{result.complete_pair_count}/{result.question_count}**",
            "",
            "## Quality And Runtime",
            "",
            "| Metric | Flat | Hierarchical |",
            "| --- | ---: | ---: |",
            f"| Hit@5 | {_percent(result.flat.hit_at_5)} | {_percent(result.hierarchical.hit_at_5)} |",
            f"| Recall@5 | {_percent(result.flat.recall_at_5)} | {_percent(result.hierarchical.recall_at_5)} |",
            f"| MRR@5 | {_percent(result.flat.mrr_at_5)} | {_percent(result.hierarchical.mrr_at_5)} |",
            f"| Multi-evidence full coverage | {_percent(result.flat.multi_evidence_full_coverage)} | {_percent(result.hierarchical.multi_evidence_full_coverage)} |",
            f"| Unanswerable non-empty retrieval | {_percent(result.flat.non_empty_unanswerable_rate)} | {_percent(result.hierarchical.non_empty_unanswerable_rate)} |",
            f"| Single-pass latency p50 | {result.flat.latency_p50_ms:.2f} ms | {result.hierarchical.latency_p50_ms:.2f} ms |",
            f"| Single-pass latency p95 | {result.flat.latency_p95_ms:.2f} ms | {result.hierarchical.latency_p95_ms:.2f} ms |",
            "",
            "## Category Recall",
            "",
            *category_lines,
            "",
            "## Interpretation Boundary",
            "",
            "- This is a development measurement on six clusters, not confirmatory evidence.",
            "- Machine-authored evidence mappings require independent human review.",
            "- Latency is descriptive single-pass data, not the required 3-session/5-repeat latency estimand.",
            "- No production runtime setting was changed.",
            "",
        ]
    )
    markdown_path.write_text(markdown, encoding="utf-8")

    def bar(label: str, value: float, color: str) -> str:
        width = max(0.0, min(100.0, value * 100))
        return (
            f'<div class="bar-row"><span>{html.escape(label)}</span>'
            f'<div class="track"><div class="fill" style="width:{width:.2f}%;background:{color}"></div></div>'
            f'<strong>{width:.2f}%</strong></div>'
        )

    category_html = "".join(
        f"<tr><td>{html.escape(row.category)}</td><td>{row.question_count}</td>"
        f"<td>{_percent(row.flat_recall_at_5)}</td><td>{_percent(row.hierarchical_recall_at_5)}</td>"
        f"<td>{_percent(row.delta)}</td></tr>"
        for row in result.categories
    )
    control_summary = " / ".join(
        html.escape(str(result.controls.get(name, "n/a")))
        for name in ("top_k", "threshold", "hybrid_search")
    )
    document = f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Flat·Hierarchical RAG Development Pilot</title>
<style>
body{{font-family:Arial,sans-serif;margin:0;background:#f5f7f8;color:#182026}}main{{max-width:1040px;margin:auto;padding:28px}}
h1{{font-size:28px;margin:0 0 8px}}h2{{font-size:19px;margin-top:28px}}.notice{{border-left:5px solid #b42318;background:#fff1f0;padding:14px;margin:18px 0}}
.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}}.metric{{background:white;border:1px solid #d8dee3;padding:16px;border-radius:6px}}.metric strong{{display:block;font-size:24px;margin-top:8px}}
.panel{{min-width:0;background:white;border:1px solid #d8dee3;padding:18px;margin-top:14px;border-radius:6px}}.bar-row{{display:grid;grid-template-columns:150px 1fr 72px;gap:12px;align-items:center;margin:12px 0}}.track{{height:18px;background:#e8ecef}}.fill{{height:100%}}
table{{width:100%;table-layout:fixed;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid #d8dee3;text-align:right;overflow-wrap:anywhere}}th:first-child,td:first-child{{text-align:left}}code{{word-break:break-all}}@media(max-width:720px){{.grid{{grid-template-columns:1fr}}.bar-row{{grid-template-columns:110px 1fr 64px}}main{{padding:18px}}table{{font-size:13px}}th,td{{padding:7px 4px}}}}
</style></head><body><main>
<h1>Flat·Hierarchical RAG 법률 Development Pilot</h1><p>동일 child boundary와 동일 child vector를 사용한 실제 Workflow Engine retrieval 비교</p>
<div class="notice"><strong>탐색적 결과</strong><br>질문과 required evidence가 인간 검토를 완료하지 않았고 독립 cluster가 6개뿐이므로 확인적 결론으로 사용할 수 없습니다.</div>
<div class="grid"><div class="metric">Flat Recall@5<strong>{_percent(result.flat.recall_at_5)}</strong></div><div class="metric">Hierarchical Recall@5<strong>{_percent(result.hierarchical.recall_at_5)}</strong></div><div class="metric">Cluster-macro delta<strong>{_percent(result.cluster_macro_recall_delta)}</strong></div></div>
<section class="panel"><h2>Recall@5</h2>{bar('Flat', result.flat.recall_at_5, '#206b73')}{bar('Hierarchical', result.hierarchical.recall_at_5, '#b54708')}<p>Exploratory 95% CI: [{_percent(result.recall_delta_ci_lower)}, {_percent(result.recall_delta_ci_upper)}]</p><p>Win / Tie / Loss: {result.wins} / {result.ties} / {result.losses}</p></section>
<section class="panel"><h2>품질 지표</h2><table><thead><tr><th>Metric</th><th>Flat</th><th>Hierarchical</th></tr></thead><tbody><tr><td>Hit@5</td><td>{_percent(result.flat.hit_at_5)}</td><td>{_percent(result.hierarchical.hit_at_5)}</td></tr><tr><td>MRR@5</td><td>{_percent(result.flat.mrr_at_5)}</td><td>{_percent(result.hierarchical.mrr_at_5)}</td></tr><tr><td>Multi-evidence full coverage</td><td>{_percent(result.flat.multi_evidence_full_coverage)}</td><td>{_percent(result.hierarchical.multi_evidence_full_coverage)}</td></tr><tr><td>Unanswerable non-empty retrieval</td><td>{_percent(result.flat.non_empty_unanswerable_rate)}</td><td>{_percent(result.hierarchical.non_empty_unanswerable_rate)}</td></tr></tbody></table></section>
<section class="panel"><h2>카테고리별 Recall@5</h2><table><thead><tr><th>Category</th><th>N</th><th>Flat</th><th>Hierarchical</th><th>Delta</th></tr></thead><tbody>{category_html}</tbody></table></section>
<section class="panel"><h2>실행 정보</h2><table><tbody><tr><th>Complete pairs</th><td>{result.complete_pair_count}/{result.question_count}</td></tr><tr><th>Child / Parent</th><td>{result.child_count} / {result.parent_count}</td></tr><tr><th>Vector dimension</th><td>{result.vector_dimension}</td></tr><tr><th>Top-k / threshold / hybrid</th><td>{control_summary}</td></tr><tr><th>Flat latency p50 / p95</th><td>{result.flat.latency_p50_ms:.2f} / {result.flat.latency_p95_ms:.2f} ms</td></tr><tr><th>Hierarchical latency p50 / p95</th><td>{result.hierarchical.latency_p50_ms:.2f} / {result.hierarchical.latency_p95_ms:.2f} ms</td></tr></tbody></table></section>
<section class="panel"><h2>해석 제한</h2><ul><li>Machine-authored evidence mapping은 독립 검토 전입니다.</li><li>6개 cluster 결과의 CI는 탐색적입니다.</li><li>Latency는 단일 pass 기술 통계입니다.</li><li>Embedding model alias는 immutable version으로 고정되지 않았습니다.</li></ul></section>
</main></body></html>"""
    html_path.write_text(document, encoding="utf-8")
    return result_path, markdown_path, html_path


def manifest_to_json(manifest: PilotDbManifest) -> dict[str, Any]:
    return manifest.model_dump(mode="json")


def timing_rows(records: Sequence[TimingRecord]) -> list[dict[str, Any]]:
    return [asdict(record) for record in records]
