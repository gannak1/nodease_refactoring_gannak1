# Agent Builder Cache Offline Latency Summary

Benchmark: `2026-07-24-9cf2bd747fc4-mba350-live-v1-agent-builder-cache-v1`

## Measured groups

| Group | Surface | Measured | Success | Failed | Warm-up | Failure rate | Mean | P50 | P95 | Stddev | Min | Max |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| cache_disabled_baseline | planning_latency_ms | 150 | 88 | 62 | 5 | 0.413 | 8220.511 | 8671.0 | 11202.55 | 2106.458 | 4047.0 | 12250.0 |
| cache_disabled_baseline | end_to_end_latency_ms | 150 | 88 | 62 | 5 | 0.413 | 9036.057 | 9484.5 | 12009.3 | 2111.455 | 4829.0 | 13078.0 |
| cold_miss | planning_latency_ms | 30 | 26 | 4 | 1 | 0.133 | 9674.615 | 9648.5 | 11035.25 | 1174.251 | 6782.0 | 12656.0 |
| cold_miss | end_to_end_latency_ms | 30 | 26 | 4 | 1 | 0.133 | 10552.269 | 10500.0 | 11878.75 | 1154.391 | 7750.0 | 13500.0 |
| exact_warm_hit | planning_latency_ms | 30 | 0 | 30 | 1 | 1.0 | n/a | n/a | n/a | n/a | n/a | n/a |
| exact_warm_hit | end_to_end_latency_ms | 30 | 0 | 30 | 1 | 1.0 | n/a | n/a | n/a | n/a | n/a | n/a |
| normalization_warm_hit | planning_latency_ms | 30 | 0 | 30 | 1 | 1.0 | n/a | n/a | n/a | n/a | n/a | n/a |
| normalization_warm_hit | end_to_end_latency_ms | 30 | 0 | 30 | 1 | 1.0 | n/a | n/a | n/a | n/a | n/a | n/a |
| semantic_bypass | planning_latency_ms | 30 | 0 | 30 | 1 | 1.0 | n/a | n/a | n/a | n/a | n/a | n/a |
| semantic_bypass | end_to_end_latency_ms | 30 | 0 | 30 | 1 | 1.0 | n/a | n/a | n/a | n/a | n/a | n/a |
| negative_control | planning_latency_ms | 30 | 29 | 1 | 1 | 0.033 | 9899.414 | 9952.0 | 11837.4 | 1407.579 | 6952.0 | 13405.0 |
| negative_control | end_to_end_latency_ms | 30 | 29 | 1 | 1 | 0.033 | 10767.793 | 10781.0 | 12806.6 | 1417.309 | 7797.0 | 14265.0 |

## Paired comparisons

| Group | Surface | Pairs | Excluded | Delta ms | Improvement % | Speedup |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| cold_miss | planning_latency_ms | 26 | 5 | -624.808 | -6.904 | 0.935 |
| cold_miss | end_to_end_latency_ms | 26 | 5 | -673.654 | -6.819 | 0.936 |
| exact_warm_hit | planning_latency_ms | 0 | 31 | n/a | n/a | n/a |
| exact_warm_hit | end_to_end_latency_ms | 0 | 31 | n/a | n/a | n/a |
| normalization_warm_hit | planning_latency_ms | 0 | 31 | n/a | n/a | n/a |
| normalization_warm_hit | end_to_end_latency_ms | 0 | 31 | n/a | n/a | n/a |
| semantic_bypass | planning_latency_ms | 0 | 31 | n/a | n/a | n/a |
| semantic_bypass | end_to_end_latency_ms | 0 | 31 | n/a | n/a | n/a |
| negative_control | planning_latency_ms | 27 | 4 | -255.889 | -2.648 | 0.974 |
| negative_control | end_to_end_latency_ms | 27 | 4 | -312.519 | -2.984 | 0.971 |

## Modeled estimates

These values are `modeled_estimate`, not measured results.

| Hit rate | Planning expected mean ms | End-to-end expected mean ms |
| ---: | ---: | ---: |
| 0.25 | n/a | n/a |
| 0.5 | n/a | n/a |
| 0.75 | n/a | n/a |
