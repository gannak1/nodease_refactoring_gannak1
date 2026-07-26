# Agent Builder Cache Offline Latency Bundle

- Benchmark: `2026-07-24-9cf2bd747fc4-mba350-live-v1-agent-builder-cache-v1`
- Kind: `live_measurement`
- Dataset: `mba350-live-v1`
- Cache contract: `agent-builder-cache-v1`

## Key result

- Measured success/failure: 143/157
- Cold-miss measured mean (planning/end-to-end): 9674.615 / 10552.269 ms
- Exact warm-hit measured mean (planning/end-to-end): n/a / n/a ms
- Artifact safety check: passed.

## Modeled estimates

These 25/50/75% values are modeled estimates, not live measurements.

| Hit rate | Planning expected mean ms | End-to-end expected mean ms |
| ---: | ---: | ---: |
| 0.25 | n/a | n/a |
| 0.5 | n/a | n/a |
| 0.75 | n/a | n/a |

## Artifacts

- [Round data](runs.csv)
- [Latency comparison graph](latency-comparison.svg)
- [Cache scenario graph](cache-hit-scenarios.svg)
- [JSON summary](summary.json)
- [CSV summary](summary.csv)
- [Markdown summary](summary.md)
