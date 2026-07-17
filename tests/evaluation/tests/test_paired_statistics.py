from __future__ import annotations

import math

import pytest

from tests.evaluation.paired_statistics import (
    PairedDelta,
    cluster_bca_interval,
    holm_adjust,
    latency_cluster_session_interval,
    paired_binary_risk_difference_interval,
    paired_cluster_randomization_p_value,
    win_tie_loss,
)
from tests.evaluation.schemas import LatencyObservation
from tests.evaluation.sample_size import (
    plan_latency_repeats,
    plan_paired_quality_sample_size,
    zero_event_sample_size,
)


def deltas(values: list[float]) -> list[PairedDelta]:
    return [
        PairedDelta(question_id=f"q-{index}", cluster_ref=f"c-{index}", delta=value)
        for index, value in enumerate(values)
    ]


def test_cluster_macro_gives_clusters_equal_weight() -> None:
    rows = [
        PairedDelta("q1", "large", 1.0),
        PairedDelta("q2", "large", 1.0),
        PairedDelta("q3", "large", 1.0),
        PairedDelta("q4", "small", -1.0),
    ]
    estimate = cluster_bca_interval(rows, iterations=1000, seed=279)
    assert estimate.point == pytest.approx(0.0)
    assert estimate.question_micro == pytest.approx(0.5)


def test_bca_is_deterministic_and_identical_pairs_are_zero() -> None:
    rows = deltas([0.0] * 5)
    first = cluster_bca_interval(rows, iterations=1000, seed=279)
    second = cluster_bca_interval(rows, iterations=1000, seed=279)
    assert first == second
    assert (first.lower, first.point, first.upper) == (0.0, 0.0, 0.0)

    one_cluster = cluster_bca_interval(deltas([0.0]), iterations=1000, seed=279)
    assert one_cluster.method == "percentile_cluster_bootstrap_v1"
    assert one_cluster.fallback_reason == "insufficient_bca_clusters"


def test_bca_rejects_missing_or_non_finite_data() -> None:
    with pytest.raises(ValueError, match="no_paired_deltas"):
        cluster_bca_interval([], iterations=1000)
    with pytest.raises(ValueError, match="non_finite_delta"):
        PairedDelta("q", "c", math.nan)


def test_win_tie_loss_uses_registered_epsilon() -> None:
    result = win_tie_loss([-0.02, -0.005, 0.0, 0.005, 0.02], epsilon=0.01)
    assert (result.wins, result.ties, result.losses) == (1, 3, 1)


def test_paired_binary_interval_requires_one_question_per_cluster() -> None:
    result = paired_binary_risk_difference_interval(
        flat=[False, False, True, True],
        hierarchical=[False, True, False, True],
        cluster_refs=["a", "b", "c", "d"],
    )
    assert result.point == pytest.approx(0.0)
    assert result.lower < 0 < result.upper
    assert (result.hierarchical_only, result.flat_only) == (1, 1)

    with pytest.raises(ValueError, match="duplicate_safety_cluster"):
        paired_binary_risk_difference_interval(
            flat=[False, True],
            hierarchical=[False, True],
            cluster_refs=["same", "same"],
        )


def test_zero_event_safety_interval_does_not_collapse_to_zero() -> None:
    result = paired_binary_risk_difference_interval(
        flat=[False] * 59,
        hierarchical=[False] * 59,
        cluster_refs=[f"c-{i}" for i in range(59)],
    )
    assert result.point == 0.0
    assert result.lower < 0 < result.upper
    assert result.upper <= 0.075


def test_sample_plans_apply_floors_and_are_monotonic() -> None:
    assert zero_event_sample_size(upper_risk=0.05, alpha=0.05) == 59
    base = plan_paired_quality_sample_size(
        sd_delta=0.15,
        target_delta=0.03,
        alpha=0.05,
        power=0.8,
        design_effect=1.0,
    )
    noisier = plan_paired_quality_sample_size(
        sd_delta=0.3,
        target_delta=0.03,
        alpha=0.05,
        power=0.8,
        design_effect=1.5,
    )
    assert base.planned_n >= 100
    assert base.minimum_clusters == 30
    assert noisier.planned_n >= base.planned_n

    loose = plan_latency_repeats(sd_log_ratio=0.1, target_half_width=0.1)
    tight = plan_latency_repeats(sd_log_ratio=0.2, target_half_width=0.05)
    assert loose.sessions >= 3 and loose.repeats_per_session >= 5
    assert tight.total_repeats >= loose.total_repeats


def test_cluster_randomization_and_holm_are_deterministic() -> None:
    cluster_values = {"a": 1.0, "b": 1.0, "c": -0.5}
    p_value = paired_cluster_randomization_p_value(cluster_values)
    assert 0.0 <= p_value <= 1.0
    assert p_value == paired_cluster_randomization_p_value(cluster_values)
    adjusted = holm_adjust({"m1": 0.01, "m2": 0.04, "m3": 0.03})
    assert adjusted == {"m1": pytest.approx(0.03), "m3": pytest.approx(0.06), "m2": pytest.approx(0.06)}


def latency_rows(*, sessions=3, repeats=5, ratio=1.2):
    rows = []
    for cluster_index in range(2):
        for session_index in range(sessions):
            for condition, multiplier in (("flat", 1.0), ("hierarchical", ratio)):
                for repeat_index in range(1, repeats + 1):
                    rows.append(
                        LatencyObservation(
                            question_id=f"q-{cluster_index}",
                            sampling_cluster_ref=f"c-{cluster_index}",
                            session_ref=f"s-{session_index}",
                            condition=condition,
                            repeat_index=repeat_index,
                            pair_order=(
                                "flat_first"
                                if repeat_index % 2
                                else "hierarchical_first"
                            ),
                            latency_ms=(100 + cluster_index + session_index) * multiplier,
                        )
                    )
    return rows


def test_latency_interval_uses_question_session_medians_and_is_deterministic() -> None:
    first = latency_cluster_session_interval(
        latency_rows(), iterations=1000, seed=279
    )
    second = latency_cluster_session_interval(
        latency_rows(), iterations=1000, seed=279
    )
    assert first == second
    assert first.point == pytest.approx(1.2)
    assert first.lower <= first.point <= first.upper
    assert first.session_count == 3
    assert first.repeats_per_session == 5


def test_latency_interval_enforces_session_and_repeat_floors() -> None:
    with pytest.raises(ValueError, match="latency_session_floor_not_met"):
        latency_cluster_session_interval(latency_rows(sessions=2), iterations=1000)
    with pytest.raises(ValueError, match="latency_repeat_floor_not_met"):
        latency_cluster_session_interval(latency_rows(repeats=4), iterations=1000)


def test_latency_interval_rejects_incomplete_or_unbalanced_ab_ba_pairs() -> None:
    incomplete = latency_rows()
    incomplete.pop()
    with pytest.raises(ValueError, match="latency_pair_incomplete"):
        latency_cluster_session_interval(incomplete, iterations=1000)

    unbalanced = [
        row.model_copy(update={"pair_order": "flat_first"}) for row in latency_rows()
    ]
    with pytest.raises(ValueError, match="latency_ab_ba_imbalance"):
        latency_cluster_session_interval(unbalanced, iterations=1000)
