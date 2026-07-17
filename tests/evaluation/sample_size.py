"""Pre-registration sample and latency repetition planning helpers."""

from __future__ import annotations

import math
from dataclasses import dataclass
from statistics import NormalDist


@dataclass(frozen=True)
class QualitySamplePlan:
    method: str
    planned_n: int
    raw_n: int
    minimum_pilot_n: int
    minimum_clusters: int
    alpha: float
    power: float
    target_delta: float
    sd_delta: float
    design_effect: float


@dataclass(frozen=True)
class LatencyRepeatPlan:
    method: str
    repeats_per_session: int
    sessions: int
    total_repeats: int


def zero_event_sample_size(*, upper_risk: float, alpha: float) -> int:
    if not 0 < upper_risk < 1 or not 0 < alpha < 1:
        raise ValueError("invalid_zero_event_plan")
    return math.ceil(math.log(alpha) / math.log(1 - upper_risk))


def plan_paired_quality_sample_size(
    *,
    sd_delta: float,
    target_delta: float,
    alpha: float = 0.05,
    power: float = 0.80,
    design_effect: float = 1.0,
    attrition_fraction: float = 0.0,
    minimum_pilot_n: int = 100,
    minimum_clusters: int = 30,
) -> QualitySamplePlan:
    if (
        not math.isfinite(sd_delta)
        or sd_delta <= 0
        or not math.isfinite(target_delta)
        or target_delta <= 0
        or not 0 < alpha < 1
        or not 0.5 < power < 1
        or not math.isfinite(design_effect)
        or design_effect < 1
        or not math.isfinite(attrition_fraction)
        or not 0 <= attrition_fraction < 1
        or minimum_pilot_n < 1
        or minimum_clusters < 1
    ):
        raise ValueError("invalid_quality_sample_plan")
    normal = NormalDist()
    z_alpha = normal.inv_cdf(1 - alpha / 2)
    z_power = normal.inv_cdf(power)
    raw_n = math.ceil(
        ((z_alpha + z_power) * sd_delta / target_delta) ** 2 * design_effect
    )
    attrition_adjusted = math.ceil(raw_n / (1 - attrition_fraction))
    planned_n = max(minimum_pilot_n, minimum_clusters, attrition_adjusted)
    return QualitySamplePlan(
        method="paired_normal_cluster_design_v1",
        planned_n=planned_n,
        raw_n=raw_n,
        minimum_pilot_n=minimum_pilot_n,
        minimum_clusters=minimum_clusters,
        alpha=alpha,
        power=power,
        target_delta=target_delta,
        sd_delta=sd_delta,
        design_effect=design_effect,
    )


def plan_latency_repeats(
    *,
    sd_log_ratio: float,
    target_half_width: float,
    confidence_level: float = 0.95,
    minimum_repeats_per_session: int = 5,
    minimum_sessions: int = 3,
) -> LatencyRepeatPlan:
    if (
        not math.isfinite(sd_log_ratio)
        or sd_log_ratio <= 0
        or not math.isfinite(target_half_width)
        or target_half_width <= 0
        or not 0 < confidence_level < 1
        or minimum_repeats_per_session < 1
        or minimum_sessions < 1
    ):
        raise ValueError("invalid_latency_plan")
    z_value = NormalDist().inv_cdf(1 - (1 - confidence_level) / 2)
    required = math.ceil((z_value * sd_log_ratio / target_half_width) ** 2)
    sessions = max(minimum_sessions, math.ceil(math.sqrt(required)))
    repeats = max(minimum_repeats_per_session, math.ceil(required / sessions))
    return LatencyRepeatPlan(
        method="log_ratio_precision_v1",
        repeats_per_session=repeats,
        sessions=sessions,
        total_repeats=repeats * sessions,
    )
