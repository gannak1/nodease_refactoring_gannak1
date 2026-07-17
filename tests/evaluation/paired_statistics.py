"""Paired, sampling-cluster-aware inference for the RAG benchmark."""

from __future__ import annotations

import itertools
import math
import random
from collections import defaultdict
from dataclasses import dataclass
from statistics import NormalDist, mean, median

from tests.evaluation.schemas import LatencyObservation


@dataclass(frozen=True)
class PairedDelta:
    question_id: str
    cluster_ref: str
    delta: float

    def __post_init__(self) -> None:
        if not self.question_id or not self.cluster_ref:
            raise ValueError("missing_paired_delta_identity")
        if not math.isfinite(self.delta):
            raise ValueError("non_finite_delta")


@dataclass(frozen=True)
class ClusterInterval:
    method: str
    confidence_level: float
    lower: float
    point: float
    upper: float
    sample_count: int
    cluster_count: int
    question_micro: float
    exploratory: bool
    fallback_reason: str | None = None


@dataclass(frozen=True)
class WinTieLoss:
    wins: int
    ties: int
    losses: int


@dataclass(frozen=True)
class PairedBinaryInterval:
    method: str
    confidence_level: float
    lower: float
    point: float
    upper: float
    sample_count: int
    hierarchical_only: int
    flat_only: int


@dataclass(frozen=True)
class LatencyRatioInterval:
    method: str
    confidence_level: float
    flat_p95_ms: float
    hierarchical_p95_ms: float
    lower: float
    point: float
    upper: float
    session_count: int
    cluster_count: int
    repeats_per_session: int


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        raise ValueError("empty_quantile")
    ordered = sorted(values)
    probability = min(1.0, max(0.0, probability))
    position = probability * (len(ordered) - 1)
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    if lower_index == upper_index:
        return ordered[lower_index]
    fraction = position - lower_index
    return ordered[lower_index] * (1 - fraction) + ordered[upper_index] * fraction


def _cluster_means(rows: list[PairedDelta]) -> dict[str, float]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[row.cluster_ref].append(row.delta)
    return {cluster: mean(values) for cluster, values in grouped.items()}


def cluster_bca_interval(
    rows: list[PairedDelta],
    *,
    iterations: int = 10_000,
    seed: int = 279,
    confidence_level: float = 0.95,
) -> ClusterInterval:
    if not rows:
        raise ValueError("no_paired_deltas")
    if iterations < 100:
        raise ValueError("insufficient_bootstrap_iterations")
    if not 0 < confidence_level < 1:
        raise ValueError("invalid_confidence_level")

    cluster_values = list(_cluster_means(rows).values())
    cluster_count = len(cluster_values)
    point = mean(cluster_values)
    question_micro = mean(row.delta for row in rows)
    if all(value == cluster_values[0] for value in cluster_values):
        small_cluster_fallback = cluster_count < 3
        return ClusterInterval(
            method=(
                "percentile_cluster_bootstrap_v1"
                if small_cluster_fallback
                else "bca_cluster_bootstrap_v1"
            ),
            confidence_level=confidence_level,
            lower=point,
            point=point,
            upper=point,
            sample_count=len(rows),
            cluster_count=cluster_count,
            question_micro=question_micro,
            exploratory=cluster_count < 30,
            fallback_reason=(
                "insufficient_bca_clusters" if small_cluster_fallback else None
            ),
        )

    rng = random.Random(seed)
    bootstrap = [
        mean(rng.choice(cluster_values) for _ in range(cluster_count))
        for _ in range(iterations)
    ]
    alpha = 1 - confidence_level
    normal = NormalDist()

    if cluster_count < 3:
        lower = _quantile(bootstrap, alpha / 2)
        upper = _quantile(bootstrap, 1 - alpha / 2)
        return ClusterInterval(
            method="percentile_cluster_bootstrap_v1",
            confidence_level=confidence_level,
            lower=min(lower, point),
            point=point,
            upper=max(upper, point),
            sample_count=len(rows),
            cluster_count=cluster_count,
            question_micro=question_micro,
            exploratory=True,
            fallback_reason="insufficient_bca_clusters",
        )

    less = sum(value < point for value in bootstrap)
    equal = sum(value == point for value in bootstrap)
    proportion = (less + 0.5 * equal) / iterations
    proportion = min(1 - 0.5 / iterations, max(0.5 / iterations, proportion))
    bias_correction = normal.inv_cdf(proportion)

    jackknife = [
        mean(cluster_values[:index] + cluster_values[index + 1 :])
        for index in range(cluster_count)
    ]
    jackknife_mean = mean(jackknife)
    numerator = sum((jackknife_mean - value) ** 3 for value in jackknife)
    denominator_base = sum(
        (jackknife_mean - value) ** 2 for value in jackknife
    )
    if denominator_base == 0:
        acceleration = 0.0
        fallback_reason = "zero_jackknife_acceleration"
    else:
        acceleration = numerator / (6 * denominator_base**1.5)
        fallback_reason = None

    def adjusted_probability(raw_probability: float) -> float:
        z_value = normal.inv_cdf(raw_probability)
        denominator = 1 - acceleration * (bias_correction + z_value)
        if denominator == 0:
            return raw_probability
        return normal.cdf(
            bias_correction
            + (bias_correction + z_value) / denominator
        )

    lower_probability = adjusted_probability(alpha / 2)
    upper_probability = adjusted_probability(1 - alpha / 2)
    lower = _quantile(bootstrap, lower_probability)
    upper = _quantile(bootstrap, upper_probability)
    return ClusterInterval(
        method="bca_cluster_bootstrap_v1",
        confidence_level=confidence_level,
        lower=min(lower, point),
        point=point,
        upper=max(upper, point),
        sample_count=len(rows),
        cluster_count=cluster_count,
        question_micro=question_micro,
        exploratory=cluster_count < 30,
        fallback_reason=fallback_reason,
    )


def win_tie_loss(values: list[float], *, epsilon: float) -> WinTieLoss:
    if epsilon < 0 or not math.isfinite(epsilon):
        raise ValueError("invalid_epsilon")
    if any(not math.isfinite(value) for value in values):
        raise ValueError("non_finite_delta")
    return WinTieLoss(
        wins=sum(value > epsilon for value in values),
        ties=sum(abs(value) <= epsilon for value in values),
        losses=sum(value < -epsilon for value in values),
    )


def _binomial_cdf(x: int, n: int, probability: float) -> float:
    return sum(
        math.comb(n, k)
        * probability**k
        * (1 - probability) ** (n - k)
        for k in range(x + 1)
    )


def _binomial_survival(x: int, n: int, probability: float) -> float:
    return 1.0 - _binomial_cdf(x - 1, n, probability)


def _clopper_pearson_with_tail(
    successes: int, n: int, *, tail_probability: float
) -> tuple[float, float]:
    if successes == 0:
        lower = 0.0
    else:
        low, high = 0.0, successes / n
        for _ in range(80):
            midpoint = (low + high) / 2
            if _binomial_survival(successes, n, midpoint) < tail_probability:
                low = midpoint
            else:
                high = midpoint
        lower = (low + high) / 2

    if successes == n:
        upper = 1.0
    else:
        low, high = successes / n, 1.0
        for _ in range(80):
            midpoint = (low + high) / 2
            if _binomial_cdf(successes, n, midpoint) > tail_probability:
                low = midpoint
            else:
                high = midpoint
        upper = (low + high) / 2
    return lower, upper


def paired_binary_risk_difference_interval(
    *,
    flat: list[bool],
    hierarchical: list[bool],
    cluster_refs: list[str],
    confidence_level: float = 0.95,
) -> PairedBinaryInterval:
    if not flat or len(flat) != len(hierarchical) or len(flat) != len(cluster_refs):
        raise ValueError("invalid_paired_binary_lengths")
    if len(cluster_refs) != len(set(cluster_refs)):
        raise ValueError("duplicate_safety_cluster")
    if not 0 < confidence_level < 1:
        raise ValueError("invalid_confidence_level")

    n = len(flat)
    hierarchical_only = sum(not left and right for left, right in zip(flat, hierarchical))
    flat_only = sum(left and not right for left, right in zip(flat, hierarchical))
    point = (hierarchical_only - flat_only) / n

    # Each discordant-cell probability is binomial marginally. Two simultaneous
    # Clopper-Pearson intervals with Bonferroni allocation yield a conservative
    # matched-pair risk-difference interval without an independence assumption.
    tail = (1 - confidence_level) / 4
    h_lower, h_upper = _clopper_pearson_with_tail(
        hierarchical_only, n, tail_probability=tail
    )
    f_lower, f_upper = _clopper_pearson_with_tail(
        flat_only, n, tail_probability=tail
    )
    return PairedBinaryInterval(
        method="bonferroni_clopper_pearson_matched_v1",
        confidence_level=confidence_level,
        lower=max(-1.0, h_lower - f_upper),
        point=point,
        upper=min(1.0, h_upper - f_lower),
        sample_count=n,
        hierarchical_only=hierarchical_only,
        flat_only=flat_only,
    )


def latency_cluster_session_interval(
    observations: list[LatencyObservation],
    *,
    iterations: int = 10_000,
    seed: int = 279,
    confidence_level: float = 0.95,
) -> LatencyRatioInterval:
    if not observations:
        raise ValueError("no_latency_observations")
    if iterations < 100:
        raise ValueError("insufficient_bootstrap_iterations")
    if not 0 < confidence_level < 1:
        raise ValueError("invalid_confidence_level")

    question_clusters: dict[str, str] = {}
    grouped: dict[tuple[str, str, str, str], list[LatencyObservation]] = defaultdict(list)
    paired_rows: dict[tuple[str, str, int], list[LatencyObservation]] = defaultdict(list)
    for observation in observations:
        previous_cluster = question_clusters.setdefault(
            observation.question_id, observation.sampling_cluster_ref
        )
        if previous_cluster != observation.sampling_cluster_ref:
            raise ValueError("latency_question_cluster_mismatch")
        key = (
            observation.sampling_cluster_ref,
            observation.session_ref,
            observation.question_id,
            observation.condition,
        )
        grouped[key].append(observation)
        paired_rows[
            (
                observation.question_id,
                observation.session_ref,
                observation.repeat_index,
            )
        ].append(observation)

    order_counts: dict[tuple[str, str], dict[str, int]] = defaultdict(
        lambda: defaultdict(int)
    )
    for (question_id, session_ref, _repeat_index), rows in paired_rows.items():
        if len(rows) != 2 or {row.condition for row in rows} != {
            "flat",
            "hierarchical",
        }:
            raise ValueError("latency_pair_incomplete")
        orders = {row.pair_order for row in rows}
        if len(orders) != 1:
            raise ValueError("latency_pair_order_mismatch")
        order_counts[(question_id, session_ref)][orders.pop()] += 1
    for counts in order_counts.values():
        if abs(counts["flat_first"] - counts["hierarchical_first"]) > 1:
            raise ValueError("latency_ab_ba_imbalance")

    sessions = sorted({observation.session_ref for observation in observations})
    clusters = sorted({observation.sampling_cluster_ref for observation in observations})
    questions = sorted(question_clusters)
    if len(sessions) < 3:
        raise ValueError("latency_session_floor_not_met")

    paired_medians: dict[tuple[str, str, str], tuple[float, float]] = {}
    repeat_floor = math.inf
    for question_id in questions:
        cluster_ref = question_clusters[question_id]
        for session_ref in sessions:
            condition_values: dict[str, list[float]] = {}
            for condition in ("flat", "hierarchical"):
                rows = grouped.get((cluster_ref, session_ref, question_id, condition), [])
                repeat_indexes = sorted(row.repeat_index for row in rows)
                if repeat_indexes != list(range(1, len(rows) + 1)):
                    raise ValueError("latency_repeat_index_mismatch")
                if len(rows) < 5:
                    raise ValueError("latency_repeat_floor_not_met")
                condition_values[condition] = [row.latency_ms for row in rows]
                repeat_floor = min(repeat_floor, len(rows))
            if len(condition_values["flat"]) != len(condition_values["hierarchical"]):
                raise ValueError("latency_asymmetric_repeat_count")
            paired_medians[(cluster_ref, session_ref, question_id)] = (
                median(condition_values["flat"]),
                median(condition_values["hierarchical"]),
            )

    flat_values = [value[0] for value in paired_medians.values()]
    hierarchical_values = [value[1] for value in paired_medians.values()]
    flat_p95 = _quantile(flat_values, 0.95)
    hierarchical_p95 = _quantile(hierarchical_values, 0.95)
    if flat_p95 <= 0:
        raise ValueError("non_positive_flat_latency")
    point = hierarchical_p95 / flat_p95

    questions_by_cluster: dict[str, list[str]] = defaultdict(list)
    for question_id, cluster_ref in question_clusters.items():
        questions_by_cluster[cluster_ref].append(question_id)
    rng = random.Random(seed)
    bootstrap_ratios: list[float] = []
    for _ in range(iterations):
        sampled_clusters = [rng.choice(clusters) for _ in clusters]
        sampled_sessions = [rng.choice(sessions) for _ in sessions]
        sampled_flat: list[float] = []
        sampled_hierarchical: list[float] = []
        for cluster_ref in sampled_clusters:
            for session_ref in sampled_sessions:
                for question_id in questions_by_cluster[cluster_ref]:
                    flat_value, hierarchical_value = paired_medians[
                        (cluster_ref, session_ref, question_id)
                    ]
                    sampled_flat.append(flat_value)
                    sampled_hierarchical.append(hierarchical_value)
        sampled_flat_p95 = _quantile(sampled_flat, 0.95)
        if sampled_flat_p95 <= 0:
            raise ValueError("non_positive_bootstrap_flat_latency")
        bootstrap_ratios.append(
            _quantile(sampled_hierarchical, 0.95) / sampled_flat_p95
        )

    alpha = 1 - confidence_level
    lower = _quantile(bootstrap_ratios, alpha / 2)
    upper = _quantile(bootstrap_ratios, 1 - alpha / 2)
    return LatencyRatioInterval(
        method="cluster_session_percentile_bootstrap_v1",
        confidence_level=confidence_level,
        flat_p95_ms=flat_p95,
        hierarchical_p95_ms=hierarchical_p95,
        lower=min(lower, point),
        point=point,
        upper=max(upper, point),
        session_count=len(sessions),
        cluster_count=len(clusters),
        repeats_per_session=int(repeat_floor),
    )


def paired_cluster_randomization_p_value(
    cluster_deltas: dict[str, float],
    *,
    seed: int = 279,
    draws: int = 100_000,
) -> float:
    if not cluster_deltas:
        raise ValueError("no_cluster_deltas")
    values = list(cluster_deltas.values())
    if any(not math.isfinite(value) for value in values):
        raise ValueError("non_finite_delta")
    observed = abs(mean(values))
    tolerance = 1e-15
    if len(values) <= 20:
        estimates = [
            abs(mean(sign * value for sign, value in zip(signs, values)))
            for signs in itertools.product((-1, 1), repeat=len(values))
        ]
        return sum(value + tolerance >= observed for value in estimates) / len(estimates)
    if draws < 100_000:
        raise ValueError("insufficient_randomization_draws")
    rng = random.Random(seed)
    exceedances = 0
    for _ in range(draws):
        estimate = abs(mean(rng.choice((-1, 1)) * value for value in values))
        exceedances += estimate + tolerance >= observed
    return (exceedances + 1) / (draws + 1)


def holm_adjust(p_values: dict[str, float]) -> dict[str, float]:
    if any(not 0 <= value <= 1 for value in p_values.values()):
        raise ValueError("invalid_p_value")
    ordered = sorted(p_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    adjusted: dict[str, float] = {}
    running = 0.0
    for index, (name, value) in enumerate(ordered):
        running = max(running, min(1.0, (count - index) * value))
        adjusted[name] = running
    return adjusted
