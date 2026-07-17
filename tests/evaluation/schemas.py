"""Strict contracts for the Flat/Hierarchical RAG benchmark.

These models deliberately separate sensitive benchmark input from sanitized
durable output. Raw queries only exist on ``BenchmarkQuestion`` and are never
copied into result models.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


SHA256_PATTERN = r"^sha256:[0-9a-f]{64}$"
OPAQUE_EVIDENCE_PATTERN = r"^ev:[0-9a-f]{32}$"
SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
SAFE_REASON_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")


class StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class DatasetManifest(StrictModel):
    schema_version: Literal["1"]
    dataset_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    dataset_version: str = Field(pattern=SAFE_ID_PATTERN, max_length=32)
    language: str = Field(pattern=r"^[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*$")
    question_count: int = Field(ge=1)
    development_count: int = Field(ge=0)
    holdout_count: int = Field(ge=0)
    sampling_cluster_count: int = Field(ge=1)
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    split_hash: str = Field(pattern=SHA256_PATTERN)
    source_manifest_hash: str = Field(pattern=SHA256_PATTERN)
    canonical_children_hash: str = Field(pattern=SHA256_PATTERN)
    question_set_hash: str = Field(pattern=SHA256_PATTERN)
    expected_evidence_hash: str = Field(pattern=SHA256_PATTERN)
    content_class: Literal["synthetic", "public", "approved_safe"]
    license_ref: str | None = Field(default=None, pattern=SAFE_ID_PATTERN, max_length=64)
    created_from: Literal["curated", "generated_reviewed", "public_benchmark"]

    @model_validator(mode="after")
    def validate_counts_and_license(self) -> "DatasetManifest":
        if self.development_count + self.holdout_count != self.question_count:
            raise ValueError("split_count_mismatch")
        if self.content_class == "public" and not self.license_ref:
            raise ValueError("public_dataset_license_required")
        return self


class BenchmarkQuestion(StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    sampling_cluster_ref: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    split: Literal["development", "holdout"]
    category: Literal[
        "single_fact",
        "section_context",
        "ambiguous_context",
        "multi_evidence",
        "distractor",
        "boundary",
        "unanswerable",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    answerable: bool
    query: str = Field(min_length=1, max_length=1000)
    safe_display_label: str | None = Field(default=None, min_length=1, max_length=120)
    required_evidence_refs: tuple[str, ...] = ()

    @field_validator("query", "safe_display_label")
    @classmethod
    def validate_safe_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            raise ValueError("benchmark_text_control_character")
        if re.search(
            r"(?i)(?:\bsk-[a-z0-9]{8,}|\b(?:api[_-]?key|token|authorization)\s*[:=])",
            value,
        ):
            raise ValueError("benchmark_text_secret_marker")
        return value

    @field_validator("required_evidence_refs")
    @classmethod
    def validate_required_refs(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate_required_evidence_ref")
        for value in values:
            if not re.fullmatch(OPAQUE_EVIDENCE_PATTERN, value):
                raise ValueError("invalid_evidence_ref")
        return values

    @model_validator(mode="after")
    def validate_answerability(self) -> "BenchmarkQuestion":
        if self.answerable and not self.required_evidence_refs:
            raise ValueError("answerable_question_requires_evidence")
        if not self.answerable and self.required_evidence_refs:
            raise ValueError("unanswerable_question_has_required_evidence")
        if self.answerable == (self.category == "unanswerable"):
            raise ValueError("question_category_answerability_mismatch")
        return self


class DatasetPackage(StrictModel):
    manifest: DatasetManifest
    questions: tuple[BenchmarkQuestion, ...]


class SourceBindingRecord(StrictModel):
    source_ref: str = Field(pattern=r"^src_[A-Za-z0-9_-]{16,64}$")
    relative_path: str = Field(min_length=1, max_length=512)
    content_hash: str = Field(pattern=SHA256_PATTERN)
    size_bytes: int = Field(ge=0)

    @field_validator("relative_path")
    @classmethod
    def safe_relative_path(cls, value: str) -> str:
        if "\\" in value or ":" in value:
            raise ValueError("non_portable_source_path")
        parts = value.split("/")
        if any(part in {"", ".", ".."} for part in parts):
            raise ValueError("unsafe_source_relative_path")
        return value


class SourceBindingSummary(StrictModel):
    binding_count: int = Field(ge=1)
    total_size_bytes: int = Field(ge=0)
    root_boundary_verified: Literal[True]
    content_hashes_verified: Literal[True]
    verification_version: Literal["local_source_binding_v1"]


class EmbeddingModelContract(StrictModel):
    safe_model_id: str = Field(pattern=SAFE_ID_PATTERN)
    immutable_version: str = Field(pattern=SAFE_ID_PATTERN)
    dimension: int = Field(ge=1, le=100_000)
    score_normalization_version: str = Field(pattern=SAFE_ID_PATTERN)


class RetrievalControlContract(StrictModel):
    hybrid_search: bool
    use_rerank: Literal[False]
    use_rewrite: Literal[False]
    top_k: Literal[5]
    threshold: float = Field(ge=-1, le=1)
    source_tier_policy: Literal["ignore"]


class SampleSizeContract(StrictModel):
    method: str = Field(pattern=SAFE_ID_PATTERN)
    alpha: float = Field(gt=0, lt=1)
    power: float = Field(gt=0.5, lt=1)
    target_recall_delta: float = Field(gt=0, le=1)
    paired_sd_delta: float = Field(gt=0, le=2)
    cluster_design_effect: float = Field(ge=1)
    planned_n: int = Field(ge=1)
    planned_answerable_n: int = Field(ge=0)
    planned_unanswerable_n: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_total(self) -> "SampleSizeContract":
        if self.planned_answerable_n + self.planned_unanswerable_n != self.planned_n:
            raise ValueError("sample_size_subgroup_total_mismatch")
        return self


class ClusterContract(StrictModel):
    minimum_independent_clusters: int = Field(ge=30)
    maximum_questions_per_cluster: int = Field(ge=1)
    equal_weight: Literal[True]


class PoolingContract(StrictModel):
    depth: int = Field(ge=5, le=100)
    blind_projection_version: str = Field(pattern=SAFE_ID_PATTERN)
    adjudication_version: str = Field(pattern=SAFE_ID_PATTERN)


class DecisionGateContract(StrictModel):
    confidence_level: Literal[0.95]
    bootstrap_iterations: int = Field(ge=100)
    recall_superiority_margin: float = Field(gt=0, le=1)
    safety_noninferiority_margin: float = Field(ge=0, lt=1)
    latency_ratio_noninferiority_margin: float = Field(gt=1)
    mrr_consistency_margin: float = Field(ge=0, lt=1)
    win_tie_loss_epsilon: float = Field(ge=0, lt=1)
    fixed_order: tuple[
        Literal["recall_superiority"],
        Literal["safety_noninferiority"],
        Literal["latency_noninferiority"],
        Literal["mrr_consistency"],
    ]


class TieContract(StrictModel):
    score_precision: int = Field(ge=0, le=15)
    complete_tie_group_cap: int = Field(ge=5, le=10_000)
    expected_metric_version: Literal["expected_tie_permutation_v1"]


class RetryContract(StrictModel):
    max_attempts_per_condition: int = Field(ge=1, le=5)
    symmetric: Literal[True]
    complete_pair_required: Literal[True]


class LatencyContract(StrictModel):
    method: Literal["question_session_median_ratio_v1"]
    repeats_per_session: int = Field(ge=5)
    session_count: int = Field(ge=3)
    randomized_ab_ba: Literal[True]
    monotonic_clock: Literal[True]
    target_ratio_ci_half_width: float = Field(gt=0)
    environment_profile_id: str = Field(pattern=SAFE_ID_PATTERN)
    cache_profile_id: str = Field(pattern=SAFE_ID_PATTERN)
    connection_pool_profile_id: str = Field(pattern=SAFE_ID_PATTERN)


class SeedContract(StrictModel):
    split: int = Field(ge=0)
    order: int = Field(ge=0)
    pool: int = Field(ge=0)
    bootstrap: int = Field(ge=0)


class FrozenProtocol(StrictModel):
    schema_version: Literal["1"]
    estimand: Literal["controlled_child_boundary_retrieval_effect"]
    study_phase: Literal["development", "confirmatory_holdout"]
    code_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    migration_head: str = Field(pattern=SAFE_ID_PATTERN)
    retrieval_config_hash: str = Field(pattern=SHA256_PATTERN)
    model_contract: EmbeddingModelContract
    retrieval_controls: RetrievalControlContract
    primary_metric: Literal["answerable_cluster_macro_recall_at_5"]
    decision_gates: DecisionGateContract
    sample_size_plan: SampleSizeContract
    cluster_plan: ClusterContract
    split_hash: str = Field(pattern=SHA256_PATTERN)
    pooling_plan: PoolingContract
    tie_policy: TieContract
    retry_attrition_policy: RetryContract
    latency_plan: LatencyContract
    permission_batch_limit: int = Field(ge=1, le=1_000)
    exclusion_policy: tuple[str, ...]
    seeds: SeedContract

    @field_validator("exclusion_policy")
    @classmethod
    def validate_exclusions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate_exclusion_reason")
        if any(not SAFE_REASON_PATTERN.fullmatch(value) for value in values):
            raise ValueError("invalid_exclusion_reason")
        return values

    @model_validator(mode="after")
    def validate_confirmatory_floors(self) -> "FrozenProtocol":
        minimum_scan_cap = max(
            self.pooling_plan.depth,
            self.retrieval_controls.top_k * 10,
        )
        if self.tie_policy.complete_tie_group_cap < minimum_scan_cap:
            raise ValueError("tie_group_cap_below_retrieval_bound")
        if self.study_phase == "confirmatory_holdout":
            if self.sample_size_plan.planned_n < 100:
                raise ValueError("confirmatory_sample_below_pilot_floor")
            if self.sample_size_plan.planned_answerable_n < 1:
                raise ValueError("confirmatory_answerable_sample_required")
            if self.sample_size_plan.planned_unanswerable_n < 59:
                raise ValueError("confirmatory_unanswerable_below_precision_floor")
            if self.decision_gates.bootstrap_iterations != 10_000:
                raise ValueError("confirmatory_bootstrap_iterations_must_be_10000")
        return self


class RetrievedEvidence(StrictModel):
    evidence_ref: str = Field(pattern=OPAQUE_EVIDENCE_PATTERN)
    score: float
    rank: int = Field(ge=1)

    @field_validator("score")
    @classmethod
    def validate_score(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("non_finite_score")
        return value


class ConditionOutcome(StrictModel):
    condition: Literal["flat", "hierarchical"]
    status: Literal["success", "operational_failure"]
    evidence: tuple[RetrievedEvidence, ...] = ()
    safe_reason_code: str | None = None
    latency_ms: float | None = Field(default=None, ge=0)
    tie_group_truncated: bool = False

    @model_validator(mode="after")
    def validate_status(self) -> "ConditionOutcome":
        if self.status == "success" and self.safe_reason_code is not None:
            raise ValueError("success_cannot_have_failure_reason")
        if self.status == "operational_failure":
            if not self.safe_reason_code or not SAFE_REASON_PATTERN.fullmatch(
                self.safe_reason_code
            ):
                raise ValueError("safe_failure_reason_required")
            if self.evidence:
                raise ValueError("failed_condition_cannot_have_evidence")
        refs = [item.evidence_ref for item in self.evidence]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_condition_evidence_ref")
        ranks = [item.rank for item in self.evidence]
        if ranks != list(range(1, len(ranks) + 1)):
            raise ValueError("non_contiguous_evidence_rank")
        scores = [item.score for item in self.evidence]
        if any(left < right for left, right in zip(scores, scores[1:])):
            raise ValueError("evidence_score_order_mismatch")
        return self


class PairedRetrievalSample(StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    sampling_cluster_ref: str = Field(pattern=SAFE_ID_PATTERN)
    category: str = Field(pattern=SAFE_ID_PATTERN)
    answerable: bool
    required_evidence_refs: tuple[str, ...]
    flat: ConditionOutcome
    hierarchical: ConditionOutcome

    @model_validator(mode="after")
    def validate_conditions(self) -> "PairedRetrievalSample":
        if self.flat.condition != "flat" or self.hierarchical.condition != "hierarchical":
            raise ValueError("condition_slot_mismatch")
        if len(self.required_evidence_refs) != len(set(self.required_evidence_refs)):
            raise ValueError("duplicate_required_evidence_ref")
        if any(
            not re.fullmatch(OPAQUE_EVIDENCE_PATTERN, value)
            for value in self.required_evidence_refs
        ):
            raise ValueError("invalid_required_evidence_ref")
        if self.answerable != bool(self.required_evidence_refs):
            raise ValueError("sample_answerability_evidence_mismatch")
        return self

    @property
    def complete(self) -> bool:
        return self.flat.status == self.hierarchical.status == "success"


class ArtifactLineage(StrictModel):
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    split_hash: str = Field(pattern=SHA256_PATTERN)
    config_hash: str = Field(pattern=SHA256_PATTERN)
    code_commit: str = Field(pattern=r"^[0-9a-f]{7,40}$")
    source_equality_verified: bool
    child_boundary_equality_verified: bool
    child_vector_equality: bool
    segmentation_contract_version: str = Field(pattern=SAFE_ID_PATTERN)
    vector_equality_check_version: str = Field(pattern=SAFE_ID_PATTERN)
    parent_builder_fingerprint: str = Field(pattern=SHA256_PATTERN)

    @property
    def confirmatory_ready(self) -> bool:
        return (
            self.source_equality_verified
            and self.child_boundary_equality_verified
            and self.child_vector_equality
        )


class BenchmarkRun(StrictModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=SAFE_ID_PATTERN)
    study_phase: Literal["development", "confirmatory_holdout"]
    estimand: Literal["controlled_child_boundary_retrieval_effect"] = (
        "controlled_child_boundary_retrieval_effect"
    )
    seed: int = Field(ge=0)
    lineage: ArtifactLineage
    samples: tuple[PairedRetrievalSample, ...]
    complete_pair_count: int = Field(ge=0)
    valid: bool
    attrition: dict[str, int]

    @model_validator(mode="after")
    def validate_run(self) -> "BenchmarkRun":
        if not self.samples:
            raise ValueError("empty_benchmark_run")
        ids = [sample.question_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_run_question_id")
        complete = sum(
            sample.complete
            and not sample.flat.tie_group_truncated
            and not sample.hierarchical.tie_group_truncated
            for sample in self.samples
        )
        if complete != self.complete_pair_count:
            raise ValueError("complete_pair_count_mismatch")
        if any(
            not SAFE_REASON_PATTERN.fullmatch(key) or value < 0
            for key, value in self.attrition.items()
        ):
            raise ValueError("invalid_attrition_summary")
        expected_attrition: Counter[str] = Counter()
        for sample in self.samples:
            for outcome in (sample.flat, sample.hierarchical):
                if outcome.status == "operational_failure":
                    expected_attrition[
                        f"{outcome.condition}.{outcome.safe_reason_code}"
                    ] += 1
                elif outcome.tie_group_truncated:
                    expected_attrition[f"{outcome.condition}.tie_group_truncated"] += 1
        if dict(sorted(expected_attrition.items())) != self.attrition:
            raise ValueError("attrition_summary_mismatch")
        expected_valid = (
            self.lineage.confirmatory_ready
            and complete == len(self.samples)
            and not self.attrition
        )
        if self.valid != expected_valid:
            raise ValueError("run_validity_mismatch")
        return self


class BlindPoolRecord(StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    evidence_ref: str = Field(pattern=OPAQUE_EVIDENCE_PATTERN)


class BlindPoolArtifact(StrictModel):
    schema_version: Literal["1"] = "1"
    sealed_output_hash: str = Field(pattern=SHA256_PATTERN)
    depth: int = Field(ge=1, le=100)
    tie_precision: int = Field(ge=0, le=15)
    pool_seed: int = Field(ge=0)
    records: tuple[BlindPoolRecord, ...]

    @model_validator(mode="after")
    def validate_records(self) -> "BlindPoolArtifact":
        keys = [(record.question_id, record.evidence_ref) for record in self.records]
        if not keys:
            raise ValueError("empty_judgment_pool")
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_judgment_pool_record")
        return self


class QrelRecord(StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    evidence_ref: str = Field(pattern=OPAQUE_EVIDENCE_PATTERN)
    relevance: int = Field(ge=0, le=2)
    required: bool = False


class QrelsArtifact(StrictModel):
    schema_version: Literal["1"] = "1"
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    sealed_output_hash: str = Field(pattern=SHA256_PATTERN)
    judgment_pool_hash: str = Field(pattern=SHA256_PATTERN)
    qrels_version: str = Field(pattern=SAFE_ID_PATTERN)
    records: tuple[QrelRecord, ...]

    @model_validator(mode="after")
    def validate_records(self) -> "QrelsArtifact":
        keys = [(record.question_id, record.evidence_ref) for record in self.records]
        if not keys:
            raise ValueError("empty_qrels")
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_qrel")
        return self


class ConfidenceInterval(StrictModel):
    method: str = Field(pattern=SAFE_ID_PATTERN)
    confidence_level: float = Field(gt=0, lt=1)
    lower: float
    point: float
    upper: float
    sample_count: int = Field(ge=1)
    cluster_count: int = Field(ge=1)
    exploratory: bool
    fallback_reason: str | None = Field(default=None, pattern=SAFE_ID_PATTERN)

    @model_validator(mode="after")
    def validate_interval(self) -> "ConfidenceInterval":
        values = (self.lower, self.point, self.upper)
        if not all(math.isfinite(value) for value in values):
            raise ValueError("non_finite_confidence_interval")
        if not self.lower <= self.point <= self.upper:
            raise ValueError("invalid_confidence_interval_order")
        return self


class MetricComparison(StrictModel):
    metric: str = Field(pattern=SAFE_ID_PATTERN)
    flat: float
    hierarchical: float
    delta: ConfidenceInterval

    @field_validator("flat", "hierarchical")
    @classmethod
    def finite_metric(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("non_finite_metric")
        return value


class SafetyComparison(StrictModel):
    method: str = Field(pattern=SAFE_ID_PATTERN)
    flat_false_evidence_rate: float = Field(ge=0, le=1)
    hierarchical_false_evidence_rate: float = Field(ge=0, le=1)
    risk_difference_lower: float
    risk_difference: float
    risk_difference_upper: float
    sample_count: int = Field(ge=1)

    @model_validator(mode="after")
    def validate_interval(self) -> "SafetyComparison":
        values = (
            self.risk_difference_lower,
            self.risk_difference,
            self.risk_difference_upper,
        )
        if not all(math.isfinite(value) and -1 <= value <= 1 for value in values):
            raise ValueError("invalid_safety_interval")
        if not self.risk_difference_lower <= self.risk_difference <= self.risk_difference_upper:
            raise ValueError("invalid_safety_interval_order")
        return self


class LatencyObservation(StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    sampling_cluster_ref: str = Field(pattern=SAFE_ID_PATTERN)
    session_ref: str = Field(pattern=SAFE_ID_PATTERN)
    condition: Literal["flat", "hierarchical"]
    repeat_index: int = Field(ge=1)
    pair_order: Literal["flat_first", "hierarchical_first"]
    latency_ms: float = Field(gt=0)

    @field_validator("latency_ms")
    @classmethod
    def finite_latency(cls, value: float) -> float:
        if not math.isfinite(value):
            raise ValueError("non_finite_latency")
        return value


class LatencyObservationArtifact(StrictModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=SAFE_ID_PATTERN)
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    config_hash: str = Field(pattern=SHA256_PATTERN)
    environment_profile_id: str = Field(pattern=SAFE_ID_PATTERN)
    cache_profile_id: str = Field(pattern=SAFE_ID_PATTERN)
    connection_pool_profile_id: str = Field(pattern=SAFE_ID_PATTERN)
    observations: tuple[LatencyObservation, ...]

    @model_validator(mode="after")
    def validate_observations(self) -> "LatencyObservationArtifact":
        keys = [
            (
                row.question_id,
                row.session_ref,
                row.condition,
                row.repeat_index,
            )
            for row in self.observations
        ]
        if not keys:
            raise ValueError("empty_latency_observations")
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_latency_observation")
        return self


class LatencyComparison(StrictModel):
    method: Literal["cluster_session_percentile_bootstrap_v1"]
    flat_p95_ms: float = Field(gt=0)
    hierarchical_p95_ms: float = Field(gt=0)
    ratio_lower: float = Field(gt=0)
    ratio: float = Field(gt=0)
    ratio_upper: float = Field(gt=0)
    session_count: int = Field(ge=3)
    cluster_count: int = Field(ge=1)
    repeats_per_session: int = Field(ge=5)

    @model_validator(mode="after")
    def validate_ratio_interval(self) -> "LatencyComparison":
        if not self.ratio_lower <= self.ratio <= self.ratio_upper:
            raise ValueError("invalid_latency_ratio_interval")
        return self


class SampleMetricSummary(StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN)
    sampling_cluster_ref: str = Field(pattern=SAFE_ID_PATTERN)
    category: str = Field(pattern=SAFE_ID_PATTERN)
    answerable: bool
    flat_recall_at_5: float = Field(ge=0, le=1)
    hierarchical_recall_at_5: float = Field(ge=0, le=1)
    flat_mrr: float = Field(ge=0, le=1)
    hierarchical_mrr: float = Field(ge=0, le=1)


class WinTieLossSummary(StrictModel):
    metric: Literal["recall_at_5"]
    epsilon: float = Field(ge=0, lt=1)
    wins: int = Field(ge=0)
    ties: int = Field(ge=0)
    losses: int = Field(ge=0)


class RegisteredDecisionGates(StrictModel):
    recall_superiority_margin: float = Field(gt=0, le=1)
    safety_noninferiority_margin: float = Field(ge=0, lt=1)
    latency_ratio_noninferiority_margin: float = Field(gt=1)
    mrr_consistency_margin: float = Field(ge=0, lt=1)
    confidence_level: Literal[0.95]


class BenchmarkResult(StrictModel):
    schema_version: Literal["1"] = "1"
    run_id: str = Field(pattern=SAFE_ID_PATTERN)
    study_phase: Literal["development", "confirmatory_holdout"]
    estimand: Literal["controlled_child_boundary_retrieval_effect"]
    protocol_hash: str = Field(pattern=SHA256_PATTERN)
    dataset_hash: str = Field(pattern=SHA256_PATTERN)
    sealed_output_hash: str = Field(pattern=SHA256_PATTERN)
    judgment_pool_hash: str = Field(pattern=SHA256_PATTERN)
    qrels_hash: str = Field(pattern=SHA256_PATTERN)
    valid: bool
    recommendation_status: Literal[
        "invalid", "hierarchical_benefit", "flat_benefit", "mixed", "inconclusive"
    ]
    complete_pair_count: int = Field(ge=0)
    independent_cluster_count: int = Field(ge=0)
    registered_gates: RegisteredDecisionGates
    win_tie_loss: WinTieLossSummary
    metric_comparisons: tuple[MetricComparison, ...]
    safety: SafetyComparison | None
    latency: LatencyComparison | None
    attrition: dict[str, int]
    samples: tuple[SampleMetricSummary, ...]

    @model_validator(mode="after")
    def validate_result(self) -> "BenchmarkResult":
        if self.valid == (self.recommendation_status == "invalid"):
            raise ValueError("result_validity_status_mismatch")
        if self.valid and self.complete_pair_count != len(self.samples):
            raise ValueError("valid_result_complete_pair_mismatch")
        if self.independent_cluster_count > len(self.samples):
            raise ValueError("result_cluster_count_mismatch")
        ids = [sample.question_id for sample in self.samples]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_result_question_id")
        answerable_count = sum(sample.answerable for sample in self.samples)
        direction = self.win_tie_loss
        if direction.wins + direction.ties + direction.losses != answerable_count:
            raise ValueError("win_tie_loss_count_mismatch")
        if self.recommendation_status in {"hierarchical_benefit", "flat_benefit"}:
            if self.safety is None or self.latency is None:
                raise ValueError("benefit_requires_safety_and_latency")
        if any(
            not SAFE_REASON_PATTERN.fullmatch(reason) or count < 0
            for reason, count in self.attrition.items()
        ):
            raise ValueError("invalid_result_attrition")
        return self
