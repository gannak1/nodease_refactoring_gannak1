"""Development-only chunk profile ablation for prepared RAG corpora.

The module keeps source text and internal identifiers out of durable reports.
One retrieval chunk may cover several canonical evidence references; metrics are
therefore calculated against the union of the covered atomic evidence refs.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tests.evaluation.corpus_authoring import PreparedCorpusSummary
from tests.evaluation.law_question_authoring import LawQuestionDraftSummary
from tests.evaluation.paired_statistics import PairedDelta, cluster_bca_interval
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import BenchmarkQuestion


ARTICLE_KEY = re.compile(r"^(article-[0-9]+)")
SAFE_PROFILE_ID = re.compile(r"^[a-z][a-z0-9_]{0,47}$")
SCORE_PRECISION = 8


class TokenEncoder(Protocol):
    def encode(self, text: str) -> list[int]: ...


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


class ChunkProfileSpec(_StrictModel):
    profile_id: str
    contextual: bool
    target_tokens: int | None = Field(default=None, ge=64, le=8_192)

    @model_validator(mode="after")
    def validate_profile(self) -> "ChunkProfileSpec":
        if SAFE_PROFILE_ID.fullmatch(self.profile_id) is None:
            raise ValueError("invalid_chunk_profile_id")
        if not self.contextual and self.target_tokens is not None:
            raise ValueError("raw_profile_cannot_group")
        return self


DEFAULT_PROFILE_SPECS = (
    ChunkProfileSpec(profile_id="raw_atomic", contextual=False),
    ChunkProfileSpec(profile_id="contextual_atomic", contextual=True),
    ChunkProfileSpec(profile_id="contextual_256", contextual=True, target_tokens=256),
    ChunkProfileSpec(profile_id="contextual_512", contextual=True, target_tokens=512),
    ChunkProfileSpec(profile_id="contextual_1024", contextual=True, target_tokens=1_024),
    ChunkProfileSpec(profile_id="contextual_2000", contextual=True, target_tokens=2_000),
)


@dataclass(frozen=True)
class AtomicEvidence:
    evidence_ref: str
    source_ref: str
    ordinal: int
    section_key: str
    content: str
    hierarchy_path: tuple[str, ...]


@dataclass(frozen=True)
class SourceContext:
    display_name: str
    version_label: str | None = None
    effective_date: str | None = None

    def prefix(self) -> str:
        values = [f"문서: {self.display_name}"]
        if self.version_label:
            values.append(f"버전: {self.version_label}")
        if self.effective_date:
            values.append(f"시행일: {self.effective_date}")
        return "[" + " | ".join(values) + "]"


@dataclass(frozen=True)
class ProfileChunk:
    chunk_ref: str
    profile_id: str
    source_ref: str
    ordinal: int
    content: str
    token_count: int
    content_fingerprint: str
    evidence_refs: tuple[str, ...]
    hierarchy_path: tuple[str, ...]


@dataclass(frozen=True)
class ChunkProfileInputs:
    corpus_id: str
    content_class: str
    source_snapshot_hash: str
    question_draft_hash: str
    atoms: tuple[AtomicEvidence, ...]
    questions: tuple[BenchmarkQuestion, ...]
    source_contexts: Mapping[str, SourceContext]


@dataclass(frozen=True)
class RankedProfileChunk:
    chunk_ref: str
    ordinal: int
    score: float
    token_count: int
    evidence_refs: tuple[str, ...]
    content_fingerprint: str


class QuestionProfileMetric(_StrictModel):
    question_id: str
    sampling_cluster_ref: str
    category: str
    answerable: bool
    hit_at_5: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    mrr_at_5: float = Field(ge=0, le=1)
    budget_hit: float = Field(ge=0, le=1)
    budget_recall: float = Field(ge=0, le=1)
    selected_chunk_count: int = Field(ge=0)
    selected_token_count: int = Field(ge=0)
    top_5_unique_content_rate: float = Field(ge=0, le=1)
    latency_ms: float = Field(ge=0)


class ProfileAggregate(_StrictModel):
    profile_id: str
    chunk_count: int = Field(ge=1)
    index_token_count: int = Field(ge=1)
    chunk_tokens_p50: float = Field(ge=0)
    chunk_tokens_p95: float = Field(ge=0)
    over_target_chunk_count: int = Field(ge=0)
    answerable_count: int = Field(ge=1)
    hit_at_5: float = Field(ge=0, le=1)
    recall_at_5: float = Field(ge=0, le=1)
    mrr_at_5: float = Field(ge=0, le=1)
    budget_hit: float = Field(ge=0, le=1)
    budget_recall: float = Field(ge=0, le=1)
    budget_selected_chunks_mean: float = Field(ge=0)
    budget_selected_tokens_mean: float = Field(ge=0)
    top_5_unique_content_rate: float = Field(ge=0, le=1)
    latency_p50_ms: float = Field(ge=0)
    latency_p95_ms: float = Field(ge=0)
    delta_vs_contextual_atomic: float = Field(ge=-1, le=1)
    delta_ci_lower: float = Field(ge=-1, le=1)
    delta_ci_upper: float = Field(ge=-1, le=1)
    delta_ci_method: str
    exploratory: bool = True


class ChunkProfileExperimentResult(_StrictModel):
    schema_version: str = "chunk_profile_experiment_v2"
    status: str = "exploratory_unreviewed_labels"
    run_id: str
    generated_at_utc: str
    code_commit: str
    source_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    source_snapshot_hash: str
    question_draft_hash: str
    corpus_id: str
    content_class: str
    embedding_model: str
    tokenizer: str
    retrieval_controls: dict[str, Any]
    question_count: int = Field(ge=1)
    answerable_count: int = Field(ge=1)
    sampling_cluster_count: int = Field(ge=1)
    profiles: tuple[ProfileAggregate, ...]
    question_metrics: dict[str, tuple[QuestionProfileMetric, ...]]
    limitations: tuple[str, ...]

    @model_validator(mode="after")
    def validate_profiles(self) -> "ChunkProfileExperimentResult":
        profile_ids = [profile.profile_id for profile in self.profiles]
        if len(profile_ids) != len(set(profile_ids)):
            raise ValueError("duplicate_result_profile")
        if set(profile_ids) != set(self.question_metrics):
            raise ValueError("result_profile_metric_mismatch")
        if "contextual_atomic" not in profile_ids:
            raise ValueError("contextual_atomic_baseline_missing")
        return self


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _sha256(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode('utf-8')).hexdigest()}"


def _source_context_from_json(snapshot: Path, source_ref: str) -> SourceContext | None:
    path = snapshot / "source-json" / f"{source_ref}.json"
    if not path.exists():
        return None
    payload = _json(path)
    law = payload.get("법령") if isinstance(payload, dict) else None
    basic = law.get("기본정보") if isinstance(law, dict) else None
    if not isinstance(basic, dict):
        return None
    title = basic.get("법령명_한글")
    if not isinstance(title, str) or not title.strip():
        return None
    version = "연혁" if "_history_" in source_ref else "현행"
    effective = basic.get("시행일자")
    return SourceContext(
        display_name=title.strip(),
        version_label=version,
        effective_date=str(effective) if effective else None,
    )


def _fallback_source_context(source_ref: str) -> SourceContext:
    categories = {
        "expense_rule": "비용 규정",
        "leave_policy": "휴가 정책",
        "records_rule": "기록 관리 규정",
        "security_std": "보안 기준",
    }
    stem = source_ref.removeprefix("src_")
    display_name = stem.replace("_", " ")
    for prefix, label in categories.items():
        if stem.startswith(prefix):
            suffix = stem.removeprefix(prefix).strip("_")
            display_name = f"{label} {suffix}".strip()
            break
    version = None
    if "_history_" in source_ref:
        version = "연혁"
    elif source_ref.endswith("_current"):
        version = "현행"
    return SourceContext(display_name=display_name, version_label=version)


def load_chunk_profile_inputs(
    snapshot_dir: str | Path,
    bundle_dir: str | Path,
) -> ChunkProfileInputs:
    snapshot = Path(snapshot_dir)
    bundle = Path(bundle_dir)
    source_summary = PreparedCorpusSummary.model_validate(_json(snapshot / "summary.json"))
    canonical_rows = _jsonl(snapshot / "canonical_children.jsonl")
    index_rows = _jsonl(snapshot / "index_input.jsonl")
    question_rows = _jsonl(bundle / "question_draft.jsonl")
    if canonical_hash(canonical_rows) != source_summary.canonical_children_hash:
        raise ValueError("profile_canonical_hash_mismatch")
    if len(canonical_rows) != source_summary.canonical_child_count:
        raise ValueError("profile_canonical_count_mismatch")
    if len(canonical_rows) != len(index_rows):
        raise ValueError("profile_atomic_count_mismatch")

    expected_source_hash = canonical_hash(
        {
            "canonical_children_hash": source_summary.canonical_children_hash,
            "source_manifest_hash": source_summary.source_manifest_hash,
        }
    )

    bundle_summary = _json(bundle / "summary.json")
    if "base_snapshot_hash" in bundle_summary:
        law_summary = LawQuestionDraftSummary.model_validate(bundle_summary)
        question_hash = law_summary.question_draft_hash
        if law_summary.base_snapshot_hash != expected_source_hash:
            raise ValueError("profile_bundle_snapshot_mismatch")
        source_snapshot_hash = expected_source_hash
        expected_question_count = law_summary.question_count
    else:
        prepared_summary = PreparedCorpusSummary.model_validate(bundle_summary)
        if (
            prepared_summary.corpus_id != source_summary.corpus_id
            or prepared_summary.canonical_children_hash
            != source_summary.canonical_children_hash
            or prepared_summary.source_manifest_hash
            != source_summary.source_manifest_hash
        ):
            raise ValueError("profile_bundle_corpus_mismatch")
        question_hash = prepared_summary.question_draft_hash
        source_snapshot_hash = expected_source_hash
        expected_question_count = prepared_summary.question_count
    if canonical_hash(question_rows) != question_hash:
        raise ValueError("profile_question_hash_mismatch")
    if len(question_rows) != expected_question_count:
        raise ValueError("profile_question_count_mismatch")

    canonical = {row["evidence_ref"]: row for row in canonical_rows}
    if len(canonical) != len(canonical_rows):
        raise ValueError("profile_duplicate_evidence_ref")
    index_refs = [row["evidence_ref"] for row in index_rows]
    if len(index_refs) != len(set(index_refs)) or set(index_refs) != set(canonical):
        raise ValueError("profile_index_evidence_set_mismatch")
    atoms: list[AtomicEvidence] = []
    for ordinal, row in enumerate(index_rows):
        evidence_ref = row["evidence_ref"]
        canonical_row = canonical.get(evidence_ref)
        if canonical_row is None or _sha256(row["content"]) != canonical_row["content_hash"]:
            raise ValueError("profile_content_hash_mismatch")
        atoms.append(
            AtomicEvidence(
                evidence_ref=evidence_ref,
                source_ref=row["safe_source_ref"],
                ordinal=ordinal,
                section_key=row["section_key"],
                content=row["content"],
                hierarchy_path=tuple(str(item) for item in row["hierarchy_path"]),
            )
        )
    questions = tuple(BenchmarkQuestion.model_validate(row) for row in question_rows)
    if len({question.question_id for question in questions}) != len(questions):
        raise ValueError("profile_duplicate_question_id")
    known_refs = set(canonical)
    if any(
        ref not in known_refs
        for question in questions
        for ref in question.required_evidence_refs
    ):
        raise ValueError("profile_question_evidence_missing")
    source_refs = tuple(dict.fromkeys(atom.source_ref for atom in atoms))
    contexts = {
        source_ref: _source_context_from_json(snapshot, source_ref)
        or _fallback_source_context(source_ref)
        for source_ref in source_refs
    }
    return ChunkProfileInputs(
        corpus_id=source_summary.corpus_id,
        content_class=source_summary.content_class,
        source_snapshot_hash=source_snapshot_hash,
        question_draft_hash=question_hash,
        atoms=tuple(atoms),
        questions=questions,
        source_contexts=contexts,
    )


def _structural_group(atom: AtomicEvidence) -> str:
    match = ARTICLE_KEY.match(atom.section_key)
    return match.group(1) if match else "document"


def _chunk_ref(profile_id: str, source_ref: str, refs: Sequence[str]) -> str:
    payload = "|".join((profile_id, source_ref, *refs))
    return "chunk_" + hashlib.sha256(payload.encode("ascii")).hexdigest()[:32]


def _render_chunk_content(
    atoms: Sequence[AtomicEvidence],
    context: SourceContext,
    *,
    contextual: bool,
) -> str:
    body = "\n\n".join(atom.content.strip() for atom in atoms)
    return f"{context.prefix()}\n{body}" if contextual else body


def build_profile_chunks(
    inputs: ChunkProfileInputs,
    spec: ChunkProfileSpec,
    encoder: TokenEncoder,
) -> tuple[ProfileChunk, ...]:
    grouped: list[list[AtomicEvidence]] = []
    previous_key: tuple[str, str] | None = None
    for atom in inputs.atoms:
        key = (atom.source_ref, _structural_group(atom))
        if key != previous_key:
            grouped.append([])
            previous_key = key
        grouped[-1].append(atom)

    chunks: list[ProfileChunk] = []

    def append_chunk(atoms: Sequence[AtomicEvidence]) -> None:
        source_ref = atoms[0].source_ref
        content = _render_chunk_content(
            atoms,
            inputs.source_contexts[source_ref],
            contextual=spec.contextual,
        )
        refs = tuple(atom.evidence_ref for atom in atoms)
        chunks.append(
            ProfileChunk(
                chunk_ref=_chunk_ref(spec.profile_id, source_ref, refs),
                profile_id=spec.profile_id,
                source_ref=source_ref,
                ordinal=len(chunks),
                content=content,
                token_count=max(1, len(encoder.encode(content))),
                content_fingerprint=_sha256(
                    "\n\n".join(atom.content.strip() for atom in atoms)
                ),
                evidence_refs=refs,
                hierarchy_path=atoms[0].hierarchy_path,
            )
        )

    if spec.target_tokens is None:
        for atom in inputs.atoms:
            append_chunk((atom,))
    else:
        for atoms in grouped:
            current: list[AtomicEvidence] = []
            for atom in atoms:
                candidate = (*current, atom)
                candidate_content = _render_chunk_content(
                    candidate,
                    inputs.source_contexts[atom.source_ref],
                    contextual=True,
                )
                if current and len(encoder.encode(candidate_content)) > spec.target_tokens:
                    append_chunk(current)
                    current = [atom]
                else:
                    current.append(atom)
            if current:
                append_chunk(current)

    covered = [ref for chunk in chunks for ref in chunk.evidence_refs]
    expected = [atom.evidence_ref for atom in inputs.atoms]
    if covered != expected:
        raise ValueError("profile_atomic_coverage_mismatch")
    if len({chunk.chunk_ref for chunk in chunks}) != len(chunks):
        raise ValueError("profile_duplicate_chunk_ref")
    return tuple(chunks)


def stable_rank(candidates: Sequence[RankedProfileChunk]) -> tuple[RankedProfileChunk, ...]:
    if any(not math.isfinite(candidate.score) for candidate in candidates):
        raise ValueError("profile_non_finite_score")
    return tuple(
        sorted(
            candidates,
            key=lambda item: (
                -round(item.score, SCORE_PRECISION),
                item.ordinal,
                item.chunk_ref,
            ),
        )
    )


def evaluate_question_profile(
    *,
    question: BenchmarkQuestion,
    candidates: Sequence[RankedProfileChunk],
    context_budget_tokens: int,
    latency_ms: float,
) -> QuestionProfileMetric:
    if context_budget_tokens < 1:
        raise ValueError("invalid_context_budget")
    ranked = stable_rank(candidates)
    required = set(question.required_evidence_refs)
    top_five = ranked[:5]
    top_refs = {ref for chunk in top_five for ref in chunk.evidence_refs}
    relevant_ranks = [
        rank
        for rank, chunk in enumerate(top_five, start=1)
        if required.intersection(chunk.evidence_refs)
    ]

    selected: list[RankedProfileChunk] = []
    selected_tokens = 0
    for chunk in ranked:
        if selected and selected_tokens + chunk.token_count > context_budget_tokens:
            break
        selected.append(chunk)
        selected_tokens += chunk.token_count
        if selected_tokens >= context_budget_tokens:
            break
    budget_refs = {ref for chunk in selected for ref in chunk.evidence_refs}

    if required:
        hit_at_5 = float(bool(required.intersection(top_refs)))
        recall_at_5 = len(required.intersection(top_refs)) / len(required)
        budget_hit = float(bool(required.intersection(budget_refs)))
        budget_recall = len(required.intersection(budget_refs)) / len(required)
        mrr_at_5 = 1.0 / min(relevant_ranks) if relevant_ranks else 0.0
    else:
        hit_at_5 = recall_at_5 = budget_hit = budget_recall = mrr_at_5 = 0.0
    unique_rate = (
        len({chunk.content_fingerprint for chunk in top_five}) / len(top_five)
        if top_five
        else 1.0
    )
    return QuestionProfileMetric(
        question_id=question.question_id,
        sampling_cluster_ref=question.sampling_cluster_ref,
        category=question.category,
        answerable=question.answerable,
        hit_at_5=hit_at_5,
        recall_at_5=recall_at_5,
        mrr_at_5=mrr_at_5,
        budget_hit=budget_hit,
        budget_recall=budget_recall,
        selected_chunk_count=len(selected),
        selected_token_count=selected_tokens,
        top_5_unique_content_rate=unique_rate,
        latency_ms=latency_ms,
    )


def _quantile(values: Sequence[float], probability: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1 - weight) + ordered[upper] * weight)


def aggregate_profile_metrics(
    *,
    specs: Sequence[ChunkProfileSpec],
    chunks_by_profile: Mapping[str, Sequence[ProfileChunk]],
    metrics_by_profile: Mapping[str, Sequence[QuestionProfileMetric]],
    bootstrap_iterations: int = 1_000,
    seed: int = 279,
) -> tuple[ProfileAggregate, ...]:
    baseline = {
        row.question_id: row
        for row in metrics_by_profile["contextual_atomic"]
        if row.answerable
    }
    aggregates: list[ProfileAggregate] = []
    for spec in specs:
        chunks = chunks_by_profile[spec.profile_id]
        rows = list(metrics_by_profile[spec.profile_id])
        answerable = [row for row in rows if row.answerable]
        if not answerable:
            raise ValueError("profile_answerable_rows_missing")
        deltas = [
            PairedDelta(
                question_id=row.question_id,
                cluster_ref=row.sampling_cluster_ref,
                delta=row.budget_recall - baseline[row.question_id].budget_recall,
            )
            for row in answerable
        ]
        interval = cluster_bca_interval(
            deltas,
            iterations=bootstrap_iterations,
            seed=seed,
        )
        token_counts = [chunk.token_count for chunk in chunks]
        over_target = (
            sum(count > spec.target_tokens for count in token_counts)
            if spec.target_tokens is not None
            else 0
        )
        aggregates.append(
            ProfileAggregate(
                profile_id=spec.profile_id,
                chunk_count=len(chunks),
                index_token_count=sum(token_counts),
                chunk_tokens_p50=median(token_counts),
                chunk_tokens_p95=_quantile(token_counts, 0.95),
                over_target_chunk_count=over_target,
                answerable_count=len(answerable),
                hit_at_5=mean(row.hit_at_5 for row in answerable),
                recall_at_5=mean(row.recall_at_5 for row in answerable),
                mrr_at_5=mean(row.mrr_at_5 for row in answerable),
                budget_hit=mean(row.budget_hit for row in answerable),
                budget_recall=mean(row.budget_recall for row in answerable),
                budget_selected_chunks_mean=mean(
                    row.selected_chunk_count for row in answerable
                ),
                budget_selected_tokens_mean=mean(
                    row.selected_token_count for row in answerable
                ),
                top_5_unique_content_rate=mean(
                    row.top_5_unique_content_rate for row in rows
                ),
                latency_p50_ms=median(row.latency_ms for row in rows),
                latency_p95_ms=_quantile([row.latency_ms for row in rows], 0.95),
                delta_vs_contextual_atomic=interval.point,
                delta_ci_lower=interval.lower,
                delta_ci_upper=interval.upper,
                delta_ci_method=interval.method,
            )
        )
    return tuple(aggregates)


def render_chunk_profile_report(result: ChunkProfileExperimentResult) -> str:
    lines = [
        f"# Chunk Profile Experiment: {result.corpus_id}",
        "",
        f"- Status: `{result.status}`",
        f"- Run: `{result.run_id}`",
        f"- Questions: {result.question_count} ({result.answerable_count} answerable)",
        f"- Context budget: {result.retrieval_controls['context_budget_tokens']} tokens",
        f"- Embedding: `{result.embedding_model}`",
        f"- Tokenizer: `{result.tokenizer}`",
        "",
        "## Aggregate Results",
        "",
        "| Profile | Chunks | Token p50/p95 | Hit@5 | Recall@5 | MRR@5 | Budget recall | Delta vs contextual atomic (95% CI) | Top-5 unique content |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for profile in result.profiles:
        lines.append(
            "| "
            + " | ".join(
                (
                    f"`{profile.profile_id}`",
                    str(profile.chunk_count),
                    f"{profile.chunk_tokens_p50:.0f}/{profile.chunk_tokens_p95:.0f}",
                    f"{profile.hit_at_5:.3f}",
                    f"{profile.recall_at_5:.3f}",
                    f"{profile.mrr_at_5:.3f}",
                    f"{profile.budget_recall:.3f}",
                    f"{profile.delta_vs_contextual_atomic:+.3f} [{profile.delta_ci_lower:+.3f}, {profile.delta_ci_upper:+.3f}]",
                    f"{profile.top_5_unique_content_rate:.3f}",
                )
            )
            + " |"
        )
    lines.extend(
        (
            "",
            "## Interpretation Boundary",
            "",
            "이 결과는 development 질문과 기계 생성 required evidence를 사용한 retrieval-only 탐색 실험이다. "
            "production 기본값, 답변 품질 또는 모든 문서 유형의 우열을 확정하지 않는다.",
            "",
            "## Limitations",
            "",
        )
    )
    lines.extend(f"- `{item}`" for item in result.limitations)
    return "\n".join(lines) + "\n"
