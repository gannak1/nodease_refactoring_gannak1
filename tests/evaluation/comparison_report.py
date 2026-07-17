"""Scoring and sanitized static reporting for paired RAG retrieval."""

from __future__ import annotations

import html
import os
import tempfile
from collections import defaultdict
from pathlib import Path
from statistics import mean

from tests.evaluation.judgment_pool import validate_qrels_pool
from tests.evaluation.paired_metrics import RankedEvidence, tie_aware_metrics
from tests.evaluation.paired_statistics import (
    PairedDelta,
    cluster_bca_interval,
    latency_cluster_session_interval,
    paired_binary_risk_difference_interval,
    win_tie_loss,
)
from tests.evaluation.protocol import atomic_write_json, canonical_hash
from tests.evaluation.schemas import (
    BenchmarkResult,
    BenchmarkRun,
    BlindPoolArtifact,
    ConfidenceInterval,
    FrozenProtocol,
    LatencyComparison,
    LatencyObservationArtifact,
    MetricComparison,
    QrelsArtifact,
    RegisteredDecisionGates,
    SafetyComparison,
    SampleMetricSummary,
    WinTieLossSummary,
)


def _condition_cluster_macro(rows: list[tuple[str, float]]) -> float:
    grouped: dict[str, list[float]] = defaultdict(list)
    for cluster_ref, value in rows:
        grouped[cluster_ref].append(value)
    return mean(mean(values) for values in grouped.values())


def _confidence_interval(interval) -> ConfidenceInterval:
    return ConfidenceInterval(
        method=interval.method,
        confidence_level=interval.confidence_level,
        lower=interval.lower,
        point=interval.point,
        upper=interval.upper,
        sample_count=interval.sample_count,
        cluster_count=interval.cluster_count,
        exploratory=interval.exploratory,
        fallback_reason=interval.fallback_reason,
    )


def _recommendation_status(
    *,
    valid: bool,
    study_phase: str,
    recall_interval,
    mrr_interval,
    safety,
    latency,
    protocol: FrozenProtocol,
) -> str:
    if not valid:
        return "invalid"
    if study_phase != "confirmatory_holdout" or recall_interval is None:
        return "inconclusive"
    gates = protocol.decision_gates
    if recall_interval.exploratory or (mrr_interval and mrr_interval.exploratory):
        return "inconclusive"
    quality_hierarchical = (
        recall_interval.point >= gates.recall_superiority_margin
        and recall_interval.lower > 0
    )
    quality_flat = (
        recall_interval.point <= -gates.recall_superiority_margin
        and recall_interval.upper < 0
    )
    hierarchical_safety = (
        safety is not None
        and safety.upper <= gates.safety_noninferiority_margin
        and safety.sample_count >= protocol.sample_size_plan.planned_unanswerable_n
    )
    flat_safety = (
        safety is not None
        and safety.lower >= -gates.safety_noninferiority_margin
        and safety.sample_count >= protocol.sample_size_plan.planned_unanswerable_n
    )
    hierarchical_mrr = (
        mrr_interval is not None
        and mrr_interval.lower >= -gates.mrr_consistency_margin
    )
    flat_mrr = (
        mrr_interval is not None
        and mrr_interval.upper <= gates.mrr_consistency_margin
    )
    hierarchical_latency = (
        latency is not None
        and latency.upper <= gates.latency_ratio_noninferiority_margin
    )
    flat_latency = (
        latency is not None
        and latency.lower >= 1 / gates.latency_ratio_noninferiority_margin
    )
    if (
        quality_hierarchical
        and hierarchical_safety
        and hierarchical_mrr
        and hierarchical_latency
    ):
        return "hierarchical_benefit"
    if quality_flat and flat_safety and flat_mrr and flat_latency:
        return "flat_benefit"
    if quality_hierarchical or quality_flat:
        return "mixed"
    return "inconclusive"


def score_benchmark(
    run: BenchmarkRun,
    *,
    protocol: FrozenProtocol,
    pool: BlindPoolArtifact,
    qrels: QrelsArtifact,
    bootstrap_iterations: int = 10_000,
    latency_observations: LatencyObservationArtifact | None = None,
) -> BenchmarkResult:
    sealed_output_hash = canonical_hash(run)
    judgment_pool_hash = canonical_hash(pool)
    if pool.sealed_output_hash != sealed_output_hash:
        raise ValueError("sealed_output_pool_lineage_mismatch")
    if qrels.judgment_pool_hash != judgment_pool_hash:
        raise ValueError("pool_qrels_lineage_mismatch")
    if qrels.protocol_hash != run.lineage.protocol_hash:
        raise ValueError("run_qrels_protocol_lineage_mismatch")
    if qrels.dataset_hash != run.lineage.dataset_hash:
        raise ValueError("run_qrels_dataset_lineage_mismatch")
    if qrels.sealed_output_hash != sealed_output_hash:
        raise ValueError("run_qrels_sealed_output_lineage_mismatch")
    if canonical_hash(protocol) != run.lineage.protocol_hash:
        raise ValueError("run_protocol_lineage_mismatch")
    if protocol.study_phase != run.study_phase:
        raise ValueError("run_protocol_study_phase_mismatch")
    if protocol.code_commit != run.lineage.code_commit:
        raise ValueError("run_protocol_code_commit_mismatch")
    if protocol.split_hash != run.lineage.split_hash:
        raise ValueError("run_protocol_split_hash_mismatch")
    if protocol.retrieval_config_hash != run.lineage.config_hash:
        raise ValueError("run_protocol_config_hash_mismatch")
    if protocol.seeds.order != run.seed:
        raise ValueError("run_protocol_order_seed_mismatch")
    if bootstrap_iterations != protocol.decision_gates.bootstrap_iterations:
        raise ValueError("bootstrap_iteration_contract_mismatch")
    if len(run.samples) != protocol.sample_size_plan.planned_n:
        raise ValueError("run_protocol_sample_count_mismatch")
    answerable_count = sum(sample.answerable for sample in run.samples)
    unanswerable_count = len(run.samples) - answerable_count
    if answerable_count != protocol.sample_size_plan.planned_answerable_n:
        raise ValueError("run_protocol_answerable_count_mismatch")
    if unanswerable_count != protocol.sample_size_plan.planned_unanswerable_n:
        raise ValueError("run_protocol_unanswerable_count_mismatch")
    cluster_counts: dict[str, int] = defaultdict(int)
    unanswerable_clusters: set[str] = set()
    for sample in run.samples:
        cluster_counts[sample.sampling_cluster_ref] += 1
        if not sample.answerable:
            if sample.sampling_cluster_ref in unanswerable_clusters:
                raise ValueError("duplicate_unanswerable_safety_cluster")
            unanswerable_clusters.add(sample.sampling_cluster_ref)
    if any(
        count > protocol.cluster_plan.maximum_questions_per_cluster
        for count in cluster_counts.values()
    ):
        raise ValueError("run_protocol_cluster_cap_exceeded")
    if (
        run.study_phase == "confirmatory_holdout"
        and len(cluster_counts) < protocol.cluster_plan.minimum_independent_clusters
    ):
        raise ValueError("run_protocol_cluster_floor_not_met")
    if pool.depth != protocol.pooling_plan.depth:
        raise ValueError("pool_depth_protocol_mismatch")
    if pool.tie_precision != protocol.tie_policy.score_precision:
        raise ValueError("pool_score_precision_protocol_mismatch")
    if pool.pool_seed != protocol.seeds.pool:
        raise ValueError("pool_seed_protocol_mismatch")
    validate_qrels_pool(pool, qrels.records)

    qrel_by_question: dict[str, dict[str, int]] = defaultdict(dict)
    for qrel in qrels.records:
        qrel_by_question[qrel.question_id][qrel.evidence_ref] = qrel.relevance

    sample_summaries: list[SampleMetricSummary] = []
    recall_rows: list[PairedDelta] = []
    mrr_rows: list[PairedDelta] = []
    flat_recall_rows: list[tuple[str, float]] = []
    hierarchical_recall_rows: list[tuple[str, float]] = []
    flat_mrr_rows: list[tuple[str, float]] = []
    hierarchical_mrr_rows: list[tuple[str, float]] = []
    flat_false_evidence: list[bool] = []
    hierarchical_false_evidence: list[bool] = []
    safety_clusters: list[str] = []

    for sample in run.samples:
        if (
            not sample.complete
            or sample.flat.tie_group_truncated
            or sample.hierarchical.tie_group_truncated
        ):
            continue
        grades = qrel_by_question.get(sample.question_id, {})
        required = set(sample.required_evidence_refs) if sample.answerable else set()
        qrel_required = {
            qrel.evidence_ref
            for qrel in qrels.records
            if qrel.question_id == sample.question_id and qrel.required
        }
        if qrel_required != required:
            raise ValueError("qrels_required_evidence_mismatch")
        if sample.answerable:
            if any(grades.get(reference, 0) <= 0 for reference in required):
                raise ValueError("required_evidence_not_relevant")
        elif any(grade > 0 for grade in grades.values()):
            raise ValueError("unanswerable_qrels_has_relevant_evidence")
        flat = tie_aware_metrics(
            [RankedEvidence(item.evidence_ref, item.score) for item in sample.flat.evidence],
            grades,
            required_refs=required,
            answerable=sample.answerable,
            k=5,
            score_precision=protocol.tie_policy.score_precision,
            tie_group_truncated=sample.flat.tie_group_truncated,
        )
        hierarchical = tie_aware_metrics(
            [
                RankedEvidence(item.evidence_ref, item.score)
                for item in sample.hierarchical.evidence
            ],
            grades,
            required_refs=required,
            answerable=sample.answerable,
            k=5,
            score_precision=protocol.tie_policy.score_precision,
            tie_group_truncated=sample.hierarchical.tie_group_truncated,
        )
        sample_summaries.append(
            SampleMetricSummary(
                question_id=sample.question_id,
                sampling_cluster_ref=sample.sampling_cluster_ref,
                category=sample.category,
                answerable=sample.answerable,
                flat_recall_at_5=flat.recall,
                hierarchical_recall_at_5=hierarchical.recall,
                flat_mrr=flat.mrr,
                hierarchical_mrr=hierarchical.mrr,
            )
        )
        if sample.answerable:
            recall_rows.append(
                PairedDelta(
                    sample.question_id,
                    sample.sampling_cluster_ref,
                    hierarchical.recall - flat.recall,
                )
            )
            mrr_rows.append(
                PairedDelta(
                    sample.question_id,
                    sample.sampling_cluster_ref,
                    hierarchical.mrr - flat.mrr,
                )
            )
            flat_recall_rows.append((sample.sampling_cluster_ref, flat.recall))
            hierarchical_recall_rows.append(
                (sample.sampling_cluster_ref, hierarchical.recall)
            )
            flat_mrr_rows.append((sample.sampling_cluster_ref, flat.mrr))
            hierarchical_mrr_rows.append((sample.sampling_cluster_ref, hierarchical.mrr))
        else:
            flat_false_evidence.append(bool(flat.false_evidence))
            hierarchical_false_evidence.append(bool(hierarchical.false_evidence))
            safety_clusters.append(sample.sampling_cluster_ref)

    comparisons: list[MetricComparison] = []
    recall_interval = None
    mrr_interval = None
    if recall_rows:
        recall_interval = cluster_bca_interval(
            recall_rows,
            iterations=bootstrap_iterations,
            seed=protocol.seeds.bootstrap,
            confidence_level=protocol.decision_gates.confidence_level,
        )
        mrr_interval = cluster_bca_interval(
            mrr_rows,
            iterations=bootstrap_iterations,
            seed=protocol.seeds.bootstrap + 1,
            confidence_level=protocol.decision_gates.confidence_level,
        )
        comparisons.extend(
            (
                MetricComparison(
                    metric="recall_at_5",
                    flat=_condition_cluster_macro(flat_recall_rows),
                    hierarchical=_condition_cluster_macro(hierarchical_recall_rows),
                    delta=_confidence_interval(recall_interval),
                ),
                MetricComparison(
                    metric="mrr_at_5",
                    flat=_condition_cluster_macro(flat_mrr_rows),
                    hierarchical=_condition_cluster_macro(hierarchical_mrr_rows),
                    delta=_confidence_interval(mrr_interval),
                ),
            )
        )

    safety_interval = None
    safety_summary = None
    if safety_clusters:
        safety_interval = paired_binary_risk_difference_interval(
            flat=flat_false_evidence,
            hierarchical=hierarchical_false_evidence,
            cluster_refs=safety_clusters,
            confidence_level=protocol.decision_gates.confidence_level,
        )
        safety_summary = SafetyComparison(
            method=safety_interval.method,
            flat_false_evidence_rate=mean(flat_false_evidence),
            hierarchical_false_evidence_rate=mean(hierarchical_false_evidence),
            risk_difference_lower=safety_interval.lower,
            risk_difference=safety_interval.point,
            risk_difference_upper=safety_interval.upper,
            sample_count=safety_interval.sample_count,
        )

    latency_interval = None
    latency_summary = None
    if latency_observations:
        if latency_observations.run_id != run.run_id:
            raise ValueError("latency_run_lineage_mismatch")
        if latency_observations.protocol_hash != run.lineage.protocol_hash:
            raise ValueError("latency_protocol_lineage_mismatch")
        if latency_observations.config_hash != run.lineage.config_hash:
            raise ValueError("latency_config_lineage_mismatch")
        latency_plan = protocol.latency_plan
        if (
            latency_observations.environment_profile_id
            != latency_plan.environment_profile_id
            or latency_observations.cache_profile_id != latency_plan.cache_profile_id
            or latency_observations.connection_pool_profile_id
            != latency_plan.connection_pool_profile_id
        ):
            raise ValueError("latency_environment_lineage_mismatch")
        latency_interval = latency_cluster_session_interval(
            list(latency_observations.observations),
            iterations=bootstrap_iterations,
            seed=protocol.seeds.bootstrap + 2,
            confidence_level=protocol.decision_gates.confidence_level,
        )
        latency_summary = LatencyComparison(
            method=latency_interval.method,
            flat_p95_ms=latency_interval.flat_p95_ms,
            hierarchical_p95_ms=latency_interval.hierarchical_p95_ms,
            ratio_lower=latency_interval.lower,
            ratio=latency_interval.point,
            ratio_upper=latency_interval.upper,
            session_count=latency_interval.session_count,
            cluster_count=latency_interval.cluster_count,
            repeats_per_session=latency_interval.repeats_per_session,
        )
        if latency_summary.session_count != latency_plan.session_count:
            raise ValueError("latency_session_contract_mismatch")
        if latency_summary.repeats_per_session != latency_plan.repeats_per_session:
            raise ValueError("latency_repeat_contract_mismatch")

    valid = (
        run.valid
        and run.lineage.confirmatory_ready
        and run.complete_pair_count == len(run.samples)
        and len(sample_summaries) == len(run.samples)
    )
    status = _recommendation_status(
        valid=valid,
        study_phase=run.study_phase,
        recall_interval=recall_interval,
        mrr_interval=mrr_interval,
        safety=safety_interval,
        latency=latency_interval,
        protocol=protocol,
    )
    recall_win_tie_loss = win_tie_loss(
        [row.delta for row in recall_rows],
        epsilon=protocol.decision_gates.win_tie_loss_epsilon,
    )
    gates = protocol.decision_gates
    return BenchmarkResult(
        run_id=run.run_id,
        study_phase=run.study_phase,
        estimand=run.estimand,
        protocol_hash=run.lineage.protocol_hash,
        dataset_hash=run.lineage.dataset_hash,
        sealed_output_hash=sealed_output_hash,
        judgment_pool_hash=judgment_pool_hash,
        qrels_hash=canonical_hash(qrels),
        valid=valid,
        recommendation_status=status,
        complete_pair_count=run.complete_pair_count,
        independent_cluster_count=len(
            {sample.sampling_cluster_ref for sample in sample_summaries}
        ),
        registered_gates=RegisteredDecisionGates(
            recall_superiority_margin=gates.recall_superiority_margin,
            safety_noninferiority_margin=gates.safety_noninferiority_margin,
            latency_ratio_noninferiority_margin=(
                gates.latency_ratio_noninferiority_margin
            ),
            mrr_consistency_margin=gates.mrr_consistency_margin,
            confidence_level=gates.confidence_level,
        ),
        win_tie_loss=WinTieLossSummary(
            metric="recall_at_5",
            epsilon=gates.win_tie_loss_epsilon,
            wins=recall_win_tie_loss.wins,
            ties=recall_win_tie_loss.ties,
            losses=recall_win_tie_loss.losses,
        ),
        metric_comparisons=tuple(comparisons),
        safety=safety_summary,
        latency=latency_summary,
        attrition=run.attrition,
        samples=tuple(sample_summaries),
    )


def _atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _markdown(result: BenchmarkResult) -> str:
    lines = [
        f"# RAG Comparison: {result.run_id}",
        "",
        "Controlled diagnostic benchmark; not a production-traffic estimate.",
        "",
        f"- Estimand: `{result.estimand}`",
        f"- Study phase: `{result.study_phase}`",
        f"- Status: `{result.recommendation_status}`",
        f"- Complete pairs: {result.complete_pair_count}",
        f"- Independent clusters: {result.independent_cluster_count}",
        f"- Protocol: `{result.protocol_hash}`",
        f"- Dataset: `{result.dataset_hash}`",
        f"- Sealed output: `{result.sealed_output_hash}`",
        f"- Judgment pool: `{result.judgment_pool_hash}`",
        f"- Qrels: `{result.qrels_hash}`",
        "",
    ]
    if not result.valid:
        lines.extend(
            (
                "Invalid or partial run: metrics below are diagnostic only; no benefit inference is allowed.",
                "",
            )
        )
    lines.extend(
        (
            "## Quality",
            "",
            "| Metric | Flat | Hierarchical | Delta | 95% CI |",
            "| --- | ---: | ---: | ---: | ---: |",
        )
    )
    for comparison in result.metric_comparisons:
        interval = comparison.delta
        lines.append(
            f"| {comparison.metric} | {comparison.flat:.4f} | "
            f"{comparison.hierarchical:.4f} | {interval.point:.4f} | "
            f"[{interval.lower:.4f}, {interval.upper:.4f}] |"
        )
    summary = result.win_tie_loss
    lines.extend(
        (
            "",
            "## Per-Question Direction",
            "",
            f"- Wins / ties / losses: {summary.wins} / {summary.ties} / "
            f"{summary.losses} (epsilon={summary.epsilon:.4f})",
            "",
            "## Registered Gates",
            "",
            f"- Recall superiority margin: {result.registered_gates.recall_superiority_margin:.4f}",
            f"- Safety non-inferiority margin: {result.registered_gates.safety_noninferiority_margin:.4f}",
            f"- Latency ratio upper margin: {result.registered_gates.latency_ratio_noninferiority_margin:.4f}",
            f"- MRR consistency margin: {result.registered_gates.mrr_consistency_margin:.4f}",
        )
    )
    if result.safety:
        lines.extend(
            (
                "",
                "## Safety",
                "",
                f"Paired false-evidence risk difference: {result.safety.risk_difference:.4f} "
                f"[{result.safety.risk_difference_lower:.4f}, "
                f"{result.safety.risk_difference_upper:.4f}] "
                f"(`{result.safety.method}`, N={result.safety.sample_count}).",
            )
        )
    if result.latency:
        lines.extend(
            (
                "",
                "## Latency",
                "",
                f"Question-session-median p95 ratio: {result.latency.ratio:.4f} "
                f"[{result.latency.ratio_lower:.4f}, {result.latency.ratio_upper:.4f}] "
                f"(`{result.latency.method}`).",
            )
        )
    lines.extend(("", "## Attrition", ""))
    if result.attrition:
        lines.extend(f"- `{reason}`: {count}" for reason, count in result.attrition.items())
    else:
        lines.append("- None")
    lines.append("")
    return "\n".join(lines)


def _html(result: BenchmarkResult) -> str:
    def position(value: float) -> float:
        return max(0.0, min(100.0, (value + 1) * 50))

    rows = ""
    for comparison in result.metric_comparisons:
        if result.valid:
            visual = (
                '<div class="ci-axis" aria-label="confidence interval">'
                f'<span class="ci-range" style="left:{position(comparison.delta.lower):.2f}%;'
                f'width:{max(0.5, position(comparison.delta.upper) - position(comparison.delta.lower)):.2f}%"></span>'
                f'<span class="ci-point" style="left:{position(comparison.delta.point):.2f}%"></span>'
                "</div>"
            )
        else:
            visual = "Not eligible"
        method = comparison.delta.method
        if comparison.delta.exploratory:
            method += " (exploratory)"
        rows += (
            "<tr>"
            f"<td>{html.escape(comparison.metric)}</td>"
            f"<td>{comparison.flat:.4f}</td>"
            f"<td>{comparison.hierarchical:.4f}</td>"
            f"<td>{comparison.delta.point:.4f}</td>"
            f"<td>[{comparison.delta.lower:.4f}, {comparison.delta.upper:.4f}]</td>"
            f"<td>{html.escape(method)}</td>"
            f"<td>{visual}</td>"
            "</tr>"
        )
    attrition_rows = "".join(
        f"<tr><td>{html.escape(reason)}</td><td>{count}</td></tr>"
        for reason, count in result.attrition.items()
    ) or '<tr><td colspan="2">None</td></tr>'
    safety = "Not measured"
    if result.safety:
        safety = (
            f"{result.safety.risk_difference:.4f} "
            f"[{result.safety.risk_difference_lower:.4f}, "
            f"{result.safety.risk_difference_upper:.4f}]"
        )
    latency = "Not measured"
    if result.latency:
        latency = (
            f"{result.latency.ratio:.4f} "
            f"[{result.latency.ratio_lower:.4f}, {result.latency.ratio_upper:.4f}]"
        )
    direction = result.win_tie_loss
    direction_total = max(1, direction.wins + direction.ties + direction.losses)
    win_width = direction.wins / direction_total * 100
    tie_width = direction.ties / direction_total * 100
    loss_width = direction.losses / direction_total * 100
    sample_rows = "".join(
        "<tr>"
        f"<td>{html.escape(sample.question_id)}</td>"
        f"<td>{sample.flat_recall_at_5:.4f}</td>"
        f"<td>{sample.hierarchical_recall_at_5:.4f}</td>"
        f"<td>{sample.hierarchical_recall_at_5 - sample.flat_recall_at_5:.4f}</td>"
        "</tr>"
        for sample in result.samples
        if sample.answerable
    )
    gates = result.registered_gates
    invalid_notice = (
        '<p class="notice invalid">Invalid or partial run. Metrics are diagnostic only; '
        "no benefit inference is allowed.</p>"
        if not result.valid
        else ""
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>RAG Comparison {html.escape(result.run_id)}</title>
<style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f6f8;color:#17202a}}main{{max-width:980px;margin:auto;padding:32px}}
h1,h2{{letter-spacing:0}}.notice{{border-left:4px solid #b45309;padding:10px 14px;background:#fff7ed}}
.summary{{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:20px 0}}
.item{{background:white;border:1px solid #d6d9de;border-radius:6px;padding:14px}}.table-scroll{{width:100%;overflow-x:auto}}
table{{width:100%;min-width:680px;border-collapse:collapse;background:white}}
th,td{{border:1px solid #d6d9de;padding:9px;text-align:left}}th{{background:#eef1f4}}code{{overflow-wrap:anywhere}}
.invalid{{border-left-color:#b3261e;background:#fff1f0}}
.ci-axis{{position:relative;width:160px;height:14px;background:#eef1f4;border:1px solid #c8cdd3}}
.ci-axis::after{{content:"";position:absolute;left:50%;top:0;bottom:0;border-left:1px solid #555}}
.ci-range{{position:absolute;top:4px;height:6px;background:#2f6f9f}}
.ci-point{{position:absolute;top:1px;width:3px;height:12px;background:#111827}}
.direction{{display:flex;width:100%;height:24px;border:1px solid #c8cdd3;margin:8px 0 16px}}
.win{{background:#2e7d32}}.tie{{background:#7b8794}}.loss{{background:#b3261e}}
.legend{{display:flex;gap:18px;flex-wrap:wrap}}.legend span{{white-space:nowrap}}
@media(max-width:600px){{main{{padding:16px}}h1{{font-size:1.6rem}}}}
</style></head><body><main>
<h1>Flat / Hierarchical RAG Comparison</h1>
<p class="notice">Controlled diagnostic benchmark; not a production-traffic estimate.</p>
{invalid_notice}
<div class="summary"><div class="item"><strong>Status</strong><br>{html.escape(result.recommendation_status)}</div>
<div class="item"><strong>Complete pairs</strong><br>{result.complete_pair_count}</div>
<div class="item"><strong>Clusters</strong><br>{result.independent_cluster_count}</div></div>
<p>Estimand: <code>{html.escape(result.estimand)}</code></p>
<h2>Artifact lineage</h2><div class="table-scroll"><table><tbody><tr><th>Protocol</th><td><code>{html.escape(result.protocol_hash)}</code></td></tr><tr><th>Dataset</th><td><code>{html.escape(result.dataset_hash)}</code></td></tr><tr><th>Sealed output</th><td><code>{html.escape(result.sealed_output_hash)}</code></td></tr><tr><th>Judgment pool</th><td><code>{html.escape(result.judgment_pool_hash)}</code></td></tr><tr><th>Qrels</th><td><code>{html.escape(result.qrels_hash)}</code></td></tr></tbody></table></div>
<h2>Quality</h2><div class="table-scroll"><table><thead><tr><th>Metric</th><th>Flat</th><th>Hierarchical</th><th>Delta</th><th>95% CI</th><th>Method</th><th>CI visual (-1 to +1)</th></tr></thead><tbody>{rows}</tbody></table></div>
<h2>Per-question direction</h2>
<div class="direction" role="img" aria-label="{direction.wins} wins, {direction.ties} ties, {direction.losses} losses"><span class="win" style="width:{win_width:.2f}%"></span><span class="tie" style="width:{tie_width:.2f}%"></span><span class="loss" style="width:{loss_width:.2f}%"></span></div>
<p class="legend"><span>Wins: {direction.wins}</span><span>Ties: {direction.ties}</span><span>Losses: {direction.losses}</span><span>Epsilon: {direction.epsilon:.4f}</span></p>
<div class="table-scroll"><table><thead><tr><th>Question</th><th>Flat Recall@5</th><th>Hierarchical Recall@5</th><th>Delta</th></tr></thead><tbody>{sample_rows}</tbody></table></div>
<h2>Registered gates</h2><div class="table-scroll"><table><tbody><tr><th>Recall superiority</th><td>{gates.recall_superiority_margin:.4f}</td></tr><tr><th>Safety non-inferiority</th><td>{gates.safety_noninferiority_margin:.4f}</td></tr><tr><th>Latency ratio upper</th><td>{gates.latency_ratio_noninferiority_margin:.4f}</td></tr><tr><th>MRR consistency</th><td>{gates.mrr_consistency_margin:.4f}</td></tr></tbody></table></div>
<h2>Safety</h2><p>{html.escape(safety)}</p>
<h2>Latency</h2><p>{html.escape(latency)}</p>
<h2>Attrition</h2><div class="table-scroll"><table><thead><tr><th>Safe reason</th><th>Count</th></tr></thead><tbody>{attrition_rows}</tbody></table></div>
</main></body></html>"""


def render_reports(result: BenchmarkResult, output_dir: str | Path) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    atomic_write_json(target / "result.json", result)
    markdown_path = target / "report.md"
    html_path = target / "report.html"
    _atomic_write_text(markdown_path, _markdown(result))
    _atomic_write_text(html_path, _html(result))
    return markdown_path, html_path
