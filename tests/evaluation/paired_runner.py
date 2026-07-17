"""Deterministic paired retrieval orchestration.

The runner owns pairing, query-vector reuse, symmetric retry, and safe
attrition. Authorization and concrete retrieval stay behind injected ports.
"""

from __future__ import annotations

import random
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import (
    ArtifactLineage,
    BenchmarkQuestion,
    BenchmarkRun,
    ConditionOutcome,
    FrozenProtocol,
    PairedRetrievalSample,
    RetrievedEvidence,
    SAFE_REASON_PATTERN,
)


Condition = Literal["flat", "hierarchical"]


class RunnerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    seed: int = Field(default=279, ge=0)
    study_phase: Literal["development", "confirmatory_holdout"] = "development"
    top_k: int = Field(default=5, ge=1, le=100)
    threshold: float = Field(default=0.15, ge=-1, le=1)
    hybrid_search: bool = True
    use_rerank: bool = False
    use_rewrite: bool = False
    max_attempts: int = Field(default=2, ge=1, le=5)
    source_tier_policy: Literal["ignore"] = "ignore"

    @model_validator(mode="after")
    def primary_controls(self) -> "RunnerConfig":
        if self.use_rerank or self.use_rewrite:
            raise ValueError("primary_rerank_and_rewrite_must_be_off")
        return self


class BenchmarkOperationalError(RuntimeError):
    def __init__(self, safe_reason_code: str) -> None:
        if not SAFE_REASON_PATTERN.fullmatch(safe_reason_code):
            raise ValueError("invalid_safe_reason_code")
        super().__init__(safe_reason_code)
        self.safe_reason_code = safe_reason_code


@dataclass(frozen=True)
class RetrievalResponse:
    evidence: tuple[RetrievedEvidence, ...]
    tie_group_truncated: bool = False


class PairedRetriever(Protocol):
    def retrieve(
        self,
        *,
        condition: Condition,
        question: BenchmarkQuestion,
        query_vector: object,
        config: RunnerConfig,
    ) -> Sequence[RetrievedEvidence] | RetrievalResponse: ...


class FinalSelectionDiagnostics(Protocol):
    def start_condition(self, condition: Condition) -> None: ...

    def consume_final_selection(self) -> tuple[object | None, bool, bool]: ...


class PairedBenchmarkRunner:
    def __init__(
        self,
        *,
        retriever: PairedRetriever,
        embed_query: Callable[[str], object],
        config: RunnerConfig,
        protocol: FrozenProtocol | None = None,
    ) -> None:
        self._retriever = retriever
        self._embed_query = embed_query
        self._config = config
        self._protocol = protocol
        if config.study_phase == "confirmatory_holdout" and protocol is None:
            raise ValueError("confirmatory_protocol_required")
        if protocol is not None:
            self._validate_static_protocol()

    def _validate_static_protocol(self) -> None:
        protocol = self._protocol
        if protocol is None:
            return
        controls = protocol.retrieval_controls
        if protocol.study_phase != self._config.study_phase:
            raise ValueError("runner_protocol_study_phase_mismatch")
        if protocol.retrieval_config_hash != canonical_hash(self._config):
            raise ValueError("runner_protocol_config_hash_mismatch")
        if protocol.seeds.order != self._config.seed:
            raise ValueError("runner_protocol_order_seed_mismatch")
        if protocol.retry_attrition_policy.max_attempts_per_condition != self._config.max_attempts:
            raise ValueError("runner_protocol_retry_mismatch")
        if (
            controls.top_k != self._config.top_k
            or controls.threshold != self._config.threshold
            or controls.hybrid_search != self._config.hybrid_search
            or controls.use_rerank != self._config.use_rerank
            or controls.use_rewrite != self._config.use_rewrite
            or controls.source_tier_policy != self._config.source_tier_policy
        ):
            raise ValueError("runner_protocol_retrieval_control_mismatch")

    def _validate_run_protocol(
        self,
        questions: list[BenchmarkQuestion],
        artifact_lineage: ArtifactLineage,
    ) -> None:
        protocol = self._protocol
        if protocol is None:
            return
        if artifact_lineage.protocol_hash != canonical_hash(protocol):
            raise ValueError("runner_protocol_lineage_mismatch")
        if artifact_lineage.config_hash != canonical_hash(self._config):
            raise ValueError("runner_config_lineage_mismatch")
        if artifact_lineage.split_hash != protocol.split_hash:
            raise ValueError("runner_split_lineage_mismatch")
        if artifact_lineage.code_commit != protocol.code_commit:
            raise ValueError("runner_code_commit_lineage_mismatch")
        plan = protocol.sample_size_plan
        if len(questions) != plan.planned_n:
            raise ValueError("runner_planned_sample_count_mismatch")
        answerable = sum(question.answerable for question in questions)
        if answerable != plan.planned_answerable_n:
            raise ValueError("runner_planned_answerable_count_mismatch")
        if len(questions) - answerable != plan.planned_unanswerable_n:
            raise ValueError("runner_planned_unanswerable_count_mismatch")
        cluster_counts: Counter[str] = Counter(
            question.sampling_cluster_ref for question in questions
        )
        if any(
            count > protocol.cluster_plan.maximum_questions_per_cluster
            for count in cluster_counts.values()
        ):
            raise ValueError("runner_cluster_cap_exceeded")
        if (
            protocol.study_phase == "confirmatory_holdout"
            and len(cluster_counts) < protocol.cluster_plan.minimum_independent_clusters
        ):
            raise ValueError("runner_cluster_floor_not_met")
        if protocol.study_phase == "confirmatory_holdout":
            unanswerable_clusters = [
                question.sampling_cluster_ref
                for question in questions
                if not question.answerable
            ]
            if len(unanswerable_clusters) != len(set(unanswerable_clusters)):
                raise ValueError("runner_duplicate_unanswerable_safety_cluster")

    def _condition_order(
        self,
        index: int,
        *,
        flat_first_on_even_pairs: bool,
    ) -> tuple[Condition, Condition]:
        first_is_flat = flat_first_on_even_pairs == (index % 2 == 0)
        return ("flat", "hierarchical") if first_is_flat else ("hierarchical", "flat")

    def _retrieve(
        self,
        *,
        condition: Condition,
        question: BenchmarkQuestion,
        query_vector: object,
    ) -> ConditionOutcome:
        last_reason = "retrieval_internal_error"
        for _attempt in range(self._config.max_attempts):
            try:
                raw = self._retriever.retrieve(
                    condition=condition,
                    question=question,
                    query_vector=query_vector,
                    config=self._config,
                )
                if (
                    self._config.study_phase == "confirmatory_holdout"
                    and not isinstance(raw, RetrievalResponse)
                ):
                    raise BenchmarkOperationalError("final_diagnostics_missing")
                response = raw if isinstance(raw, RetrievalResponse) else RetrievalResponse(tuple(raw))
                return ConditionOutcome(
                    condition=condition,
                    status="success",
                    evidence=response.evidence,
                    tie_group_truncated=response.tie_group_truncated,
                )
            except BenchmarkOperationalError as exc:
                last_reason = exc.safe_reason_code
            except Exception as exc:
                reason = getattr(exc, "safe_reason_code", None)
                last_reason = (
                    reason
                    if isinstance(reason, str) and SAFE_REASON_PATTERN.fullmatch(reason)
                    else "retrieval_internal_error"
                )
        return ConditionOutcome(
            condition=condition,
            status="operational_failure",
            safe_reason_code=last_reason,
        )

    def run(
        self,
        questions: Iterable[BenchmarkQuestion],
        *,
        run_id: str,
        artifact_lineage: ArtifactLineage,
    ) -> BenchmarkRun:
        selected = list(questions)
        expected_split = (
            "holdout" if self._config.study_phase == "confirmatory_holdout" else "development"
        )
        if not selected:
            raise ValueError("empty_benchmark_question_set")
        if any(question.split != expected_split for question in selected):
            raise ValueError("study_phase_split_mismatch")
        if len({question.question_id for question in selected}) != len(selected):
            raise ValueError("duplicate_question_id")
        self._validate_run_protocol(selected, artifact_lineage)

        rng = random.Random(self._config.seed)
        rng.shuffle(selected)
        flat_first_on_even_pairs = rng.choice((True, False))
        samples: list[PairedRetrievalSample] = []
        attrition: Counter[str] = Counter()
        for index, question in enumerate(selected):
            try:
                query_vector = self._embed_query(question.query)
            except Exception:
                flat = ConditionOutcome(
                    condition="flat",
                    status="operational_failure",
                    safe_reason_code="embedding_failed",
                )
                hierarchical = ConditionOutcome(
                    condition="hierarchical",
                    status="operational_failure",
                    safe_reason_code="embedding_failed",
                )
            else:
                outcomes: dict[Condition, ConditionOutcome] = {}
                for condition in self._condition_order(
                    index,
                    flat_first_on_even_pairs=flat_first_on_even_pairs,
                ):
                    outcomes[condition] = self._retrieve(
                        condition=condition,
                        question=question,
                        query_vector=query_vector,
                    )
                flat = outcomes["flat"]
                hierarchical = outcomes["hierarchical"]

            for outcome in (flat, hierarchical):
                if outcome.status == "operational_failure":
                    attrition[f"{outcome.condition}.{outcome.safe_reason_code}"] += 1
                elif outcome.tie_group_truncated:
                    attrition[f"{outcome.condition}.tie_group_truncated"] += 1

            samples.append(
                PairedRetrievalSample(
                    question_id=question.question_id,
                    sampling_cluster_ref=question.sampling_cluster_ref,
                    category=question.category,
                    answerable=question.answerable,
                    required_evidence_refs=question.required_evidence_refs,
                    flat=flat,
                    hierarchical=hierarchical,
                )
            )

        complete = sum(
            sample.complete
            and not sample.flat.tie_group_truncated
            and not sample.hierarchical.tie_group_truncated
            for sample in samples
        )
        valid = (
            artifact_lineage.confirmatory_ready
            and complete == len(samples)
            and not attrition
        )
        return BenchmarkRun(
            run_id=run_id,
            study_phase=self._config.study_phase,
            seed=self._config.seed,
            lineage=artifact_lineage,
            samples=tuple(samples),
            complete_pair_count=complete,
            valid=valid,
            attrition=dict(sorted(attrition.items())),
        )


class WorkflowRetrievalAdapter:
    """Thin adapter over Workflow Engine synchronous retrieval.

    ``evidence_mapping`` is an ignored-local mapping from condition-specific
    chunk identity to the shared opaque evidence reference. It is intentionally
    not serialized by this adapter.
    """

    def __init__(
        self,
        *,
        service: object,
        knowledge_base_ids: dict[Condition, str],
        evidence_mapping: dict[Condition, dict[str, str]],
        preflight: Callable[[Condition, str], None],
        diagnostics: FinalSelectionDiagnostics | None = None,
    ) -> None:
        self._service = service
        self._knowledge_base_ids = knowledge_base_ids
        self._evidence_mapping = evidence_mapping
        self._preflight = preflight
        self._diagnostics = diagnostics

    def retrieve(
        self,
        *,
        condition: Condition,
        question: BenchmarkQuestion,
        query_vector: object,
        config: RunnerConfig,
    ) -> tuple[RetrievedEvidence, ...] | RetrievalResponse:
        kb_id = self._knowledge_base_ids[condition]
        self._preflight(condition, kb_id)
        if self._diagnostics is not None:
            self._diagnostics.start_condition(condition)
        hierarchy_mode = "flat" if condition == "flat" else "parent_child"
        search = getattr(self._service, "search_documents_sync")
        previews = search(
            question.query,
            knowledge_base_id=kb_id,
            top_k=config.top_k,
            threshold=config.threshold,
            hybrid_search=config.hybrid_search,
            use_rerank=False,
            hierarchy_mode=hierarchy_mode,
            source_tier_policy=config.source_tier_policy,
            query_vector=query_vector,
        )
        if self._diagnostics is not None:
            event, mapping_missing, tie_group_truncated = (
                self._diagnostics.consume_final_selection()
            )
            if event is None:
                raise BenchmarkOperationalError("final_diagnostics_missing")
            if mapping_missing:
                raise BenchmarkOperationalError("evidence_mapping_missing")
            candidates = getattr(event, "candidates")
            return RetrievalResponse(
                evidence=tuple(
                    RetrievedEvidence(
                        evidence_ref=candidate.evidence_ref,
                        score=float(candidate.score),
                        rank=rank,
                    )
                    for rank, candidate in enumerate(candidates, start=1)
                ),
                tie_group_truncated=tie_group_truncated,
            )
        mapping = self._evidence_mapping[condition]
        evidence: list[RetrievedEvidence] = []
        for rank, preview in enumerate(previews, start=1):
            internal_id = str(preview.chunk_id)
            try:
                evidence_ref = mapping[internal_id]
            except KeyError as exc:
                raise BenchmarkOperationalError("evidence_mapping_missing") from exc
            evidence.append(
                RetrievedEvidence(
                    evidence_ref=evidence_ref,
                    score=float(preview.score),
                    rank=rank,
                )
            )
        return tuple(evidence)
