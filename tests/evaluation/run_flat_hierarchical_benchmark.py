"""CLI for the controlled Flat/Hierarchical RAG benchmark artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from tests.evaluation.assessment_resolver import AssessmentBundle, resolve_assessments
from tests.evaluation.comparison_report import render_reports, score_benchmark
from tests.evaluation.judgment_pool import build_blind_pool
from tests.evaluation.paired_index_preparer import (
    PreparedIndexManifest,
    verify_paired_index_manifests,
)
from tests.evaluation.protocol import (
    atomic_write_json,
    canonical_hash,
    load_json_model,
    read_sealed_artifact,
    validate_protocol,
    write_sealed_artifact,
)
from tests.evaluation.retrieval_stability import verify_retrieval_stability
from tests.evaluation.sample_size import (
    plan_latency_repeats,
    plan_paired_quality_sample_size,
    zero_event_sample_size,
)
from tests.evaluation.schemas import (
    BenchmarkResult,
    BenchmarkRun,
    BlindPoolArtifact,
    DatasetPackage,
    FrozenProtocol,
    LatencyObservationArtifact,
    QrelsArtifact,
)


class PilotSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    sd_delta: float = Field(gt=0)
    target_delta: float = Field(default=0.03, gt=0)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    power: float = Field(default=0.80, gt=0, lt=1)
    design_effect: float = Field(default=1.0, ge=1)
    attrition_fraction: float = Field(default=0.0, ge=0, lt=1)
    sd_log_latency_ratio: float = Field(gt=0)
    latency_ratio_ci_half_width: float = Field(gt=0)


def _safe_status(**values) -> None:
    print(json.dumps(values, ensure_ascii=True, sort_keys=True))


def _validate(args: argparse.Namespace) -> None:
    dataset = load_json_model(args.dataset, DatasetPackage)
    protocol = load_json_model(args.protocol, FrozenProtocol)
    validate_protocol(dataset, protocol)
    _safe_status(
        status="valid",
        question_count=dataset.manifest.question_count,
        sampling_cluster_count=dataset.manifest.sampling_cluster_count,
    )


def _plan_sample(args: argparse.Namespace) -> None:
    pilot = load_json_model(args.pilot, PilotSummary)
    quality = plan_paired_quality_sample_size(
        sd_delta=pilot.sd_delta,
        target_delta=pilot.target_delta,
        alpha=pilot.alpha,
        power=pilot.power,
        design_effect=pilot.design_effect,
        attrition_fraction=pilot.attrition_fraction,
    )
    latency = plan_latency_repeats(
        sd_log_ratio=pilot.sd_log_latency_ratio,
        target_half_width=pilot.latency_ratio_ci_half_width,
    )
    _safe_status(
        status="planned",
        quality_planned_n=quality.planned_n,
        minimum_independent_clusters=quality.minimum_clusters,
        unanswerable_zero_event_n=zero_event_sample_size(
            upper_risk=0.05, alpha=pilot.alpha
        ),
        latency_repeats_per_session=latency.repeats_per_session,
        latency_session_count=latency.sessions,
    )


def _seal_run(args: argparse.Namespace) -> None:
    run = load_json_model(args.input, BenchmarkRun)
    artifact_hash = write_sealed_artifact(args.output, "retrieval_output", run)
    _safe_status(status="sealed", artifact_hash=artifact_hash)


def _build_pool(args: argparse.Namespace) -> None:
    payload = read_sealed_artifact(args.sealed_input, expected_type="retrieval_output")
    run = BenchmarkRun.model_validate(payload)
    protocol = load_json_model(args.protocol, FrozenProtocol)
    if canonical_hash(protocol) != run.lineage.protocol_hash:
        raise ValueError("run_protocol_lineage_mismatch")
    pool = build_blind_pool(
        run,
        sealed_output_hash=canonical_hash(run),
        depth=protocol.pooling_plan.depth,
        score_precision=protocol.tie_policy.score_precision,
        pool_seed=protocol.seeds.pool,
    )
    atomic_write_json(args.output, pool)
    _safe_status(
        status="pool_built",
        record_count=len(pool.records),
        pool_hash=canonical_hash(pool),
    )


def _freeze_qrels(args: argparse.Namespace) -> None:
    payload = read_sealed_artifact(args.sealed_input, expected_type="retrieval_output")
    run = BenchmarkRun.model_validate(payload)
    pool = load_json_model(args.pool, BlindPoolArtifact)
    if pool.sealed_output_hash != canonical_hash(run):
        raise ValueError("sealed_output_pool_lineage_mismatch")
    bundle = load_json_model(args.assessments, AssessmentBundle)
    resolved = resolve_assessments(
        pool,
        bundle,
        protocol_hash=run.lineage.protocol_hash,
        dataset_hash=run.lineage.dataset_hash,
    )
    atomic_write_json(args.output, resolved.qrels)
    atomic_write_json(args.summary_output, resolved.summary)
    _safe_status(
        status="qrels_frozen",
        qrels_hash=canonical_hash(resolved.qrels),
        assessment_count=resolved.summary.assessment_count,
        adjudication_count=resolved.summary.adjudication_count,
    )


def _score(args: argparse.Namespace) -> None:
    payload = read_sealed_artifact(args.sealed_input, expected_type="retrieval_output")
    run = BenchmarkRun.model_validate(payload)
    protocol = load_json_model(args.protocol, FrozenProtocol)
    pool = load_json_model(args.pool, BlindPoolArtifact)
    qrels = load_json_model(args.qrels, QrelsArtifact)
    latency = (
        load_json_model(args.latency_observations, LatencyObservationArtifact)
        if args.latency_observations
        else None
    )
    result = score_benchmark(
        run,
        protocol=protocol,
        pool=pool,
        qrels=qrels,
        bootstrap_iterations=(
            protocol.decision_gates.bootstrap_iterations
            if args.bootstrap_iterations is None
            else args.bootstrap_iterations
        ),
        latency_observations=latency,
    )
    atomic_write_json(args.output, result)
    _safe_status(
        status="scored",
        recommendation_status=result.recommendation_status,
        complete_pair_count=result.complete_pair_count,
    )


def _render(args: argparse.Namespace) -> None:
    result = load_json_model(args.input, BenchmarkResult)
    render_reports(result, args.output_dir)
    _safe_status(status="rendered", report_count=3)


def _verify_indexes(args: argparse.Namespace) -> None:
    flat = load_json_model(args.flat_manifest, PreparedIndexManifest)
    hierarchical = load_json_model(args.hierarchical_manifest, PreparedIndexManifest)
    summary = verify_paired_index_manifests(flat, hierarchical)
    atomic_write_json(args.output, summary)
    _safe_status(
        status="index_pair_verified",
        child_count=summary.child_count,
        vector_dimension=summary.vector_dimension,
    )


def _verify_stability(args: argparse.Namespace) -> None:
    primary_payload = read_sealed_artifact(
        args.primary_sealed,
        expected_type="retrieval_output",
    )
    replicate_payload = read_sealed_artifact(
        args.replicate_sealed,
        expected_type="retrieval_output",
    )
    primary = BenchmarkRun.model_validate(primary_payload)
    replicate = BenchmarkRun.model_validate(replicate_payload)
    protocol = load_json_model(args.protocol, FrozenProtocol)
    if canonical_hash(protocol) != primary.lineage.protocol_hash:
        raise ValueError("run_protocol_lineage_mismatch")
    summary = verify_retrieval_stability(
        primary,
        replicate,
        score_precision=protocol.tie_policy.score_precision,
        selection_depth=protocol.pooling_plan.depth,
    )
    atomic_write_json(args.output, summary)
    _safe_status(
        status="stable",
        compared_question_count=summary.compared_question_count,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Controlled Flat/Hierarchical RAG benchmark artifact tool"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate")
    validate.add_argument("--dataset", required=True)
    validate.add_argument("--protocol", required=True)
    validate.set_defaults(handler=_validate)

    plan = subparsers.add_parser("plan-sample")
    plan.add_argument("--pilot", required=True)
    plan.set_defaults(handler=_plan_sample)

    seal = subparsers.add_parser("seal-run")
    seal.add_argument("--input", required=True)
    seal.add_argument("--output", required=True)
    seal.set_defaults(handler=_seal_run)

    pool = subparsers.add_parser("build-judgment-pool")
    pool.add_argument("--sealed-input", required=True)
    pool.add_argument("--protocol", required=True)
    pool.add_argument("--output", required=True)
    pool.set_defaults(handler=_build_pool)

    freeze = subparsers.add_parser("freeze-qrels")
    freeze.add_argument("--sealed-input", required=True)
    freeze.add_argument("--pool", required=True)
    freeze.add_argument("--assessments", required=True)
    freeze.add_argument("--output", required=True)
    freeze.add_argument("--summary-output", required=True)
    freeze.set_defaults(handler=_freeze_qrels)

    score = subparsers.add_parser("score")
    score.add_argument("--sealed-input", required=True)
    score.add_argument("--protocol", required=True)
    score.add_argument("--pool", required=True)
    score.add_argument("--qrels", required=True)
    score.add_argument("--output", required=True)
    score.add_argument("--latency-observations")
    score.add_argument("--bootstrap-iterations", type=int)
    score.set_defaults(handler=_score)

    render = subparsers.add_parser("render")
    render.add_argument("--input", required=True)
    render.add_argument("--output-dir", required=True)
    render.set_defaults(handler=_render)

    verify = subparsers.add_parser("verify-indexes")
    verify.add_argument("--flat-manifest", required=True)
    verify.add_argument("--hierarchical-manifest", required=True)
    verify.add_argument("--output", required=True)
    verify.set_defaults(handler=_verify_indexes)

    stability = subparsers.add_parser("verify-stability")
    stability.add_argument("--primary-sealed", required=True)
    stability.add_argument("--replicate-sealed", required=True)
    stability.add_argument("--protocol", required=True)
    stability.add_argument("--output", required=True)
    stability.set_defaults(handler=_verify_stability)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    try:
        args.handler(args)
    except Exception:
        print(
            json.dumps(
                {"reason": "benchmark_command_failed", "status": "error"},
                ensure_ascii=True,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        raise SystemExit(2) from None


if __name__ == "__main__":
    main()
