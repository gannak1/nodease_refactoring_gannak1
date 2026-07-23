# Agent Builder Cache Live Benchmark Collector

Status: Draft

## Scope

This specification defines the MBA-350 evaluation collector that converts
permission-approved live observations into the CACHE-05 latency-report schema.
The collector itself does not invoke a provider, Redis, or an Agent Builder
endpoint. An environment-specific executor is connected only during an
explicitly authorized live run.

The collector measures these candidate groups against a separately executed
cache-disabled baseline:

- `cold_miss`
- `exact_warm_hit`
- `normalization_warm_hit`
- `semantic_bypass`
- `negative_control`

`semantic_bypass` and `negative_control` are cache-behavior controls. They do
not add semantic retrieval, Graph Template RAG, embeddings, or vector search.

## Runtime admission

Before an executor may run, the caller supplies a safe boolean preflight that
proves all of the following without persisting identifiers or secrets:

- current permission was checked;
- GPT-5.5 is available for the benchmark;
- the current server-loaded graph/context is ready; and
- the deterministic cache contract is ready.

An incomplete preflight rejects collection before any executor invocation. The
caller creates one safe, non-reversible `scenario_fingerprint` during preflight
for the current actor/organization, model and credential relation, generation
mode, and server-loaded graph/context. It contains none of those source values.
The collector rejects a case whose fingerprint differs from the preflight and
passes the accepted fingerprint unchanged to both sides of every pair.

The collector never receives a raw request, provider payload, cache key/value,
credential, protected ID, or graph content.

## Local diagnostic bridge

An authorized HTTP executor submits work through the existing Agent Builder
message endpoint. It may then read exactly one evaluation-only diagnostic from
the same Gateway process:

- `GET /api/v1/agent-builder/benchmark/diagnostics/{request_id}` is disabled
  unless `AGENT_BUILDER_CACHE_BENCHMARK_DIAGNOSTICS_ENABLED=true` is set when
  the local process starts.
- The bridge is forcibly disabled when `NODE_ENV` is `production` or `staging`,
  even if the local diagnostic flag is set.
- The endpoint accepts a direct loopback caller only, requires the ordinary
  authenticated user and `X-Organization-Id`, and returns `404` when disabled,
  unavailable, or outside that user/organization scope.
- The runner marks its ordinary `POST /sessions` calls with
  `X-Agent-Builder-Benchmark-Fresh-Session: true`. Gateway honors the marker
  only for this enabled loopback boundary, creating a new direct-edit session
  rather than restoring a prior active session; all other callers retain the
  normal restore-or-create behavior.
- The bounded process-local record has only `cache_outcome`,
  `planning_latency_ms`, `provider_call_count`, `repair_call_count`,
  benchmark terminal status, and validation status. It contains no request
  body, protected identifier, cache key/value, secret, credential, or provider
  payload.
- The runtime adapter derives an allowed result fingerprint from the normal
  message response in memory; it never sends a raw response to the collector
  or final artifact.

This bridge is evaluation infrastructure, not a product API or a serving
activation mechanism.

## Paired measurement contract

For each safe case label, candidate group, and round, the collector creates
one unique pair identifier and calls the executor once for the disabled
baseline and once for that candidate. The executor owns pair-local state setup
and must use the same current graph/context and `scenario_fingerprint` for both
calls. It returns only the allowlisted observation needed by CACHE-05 `RunRow`.

- Development confirmation: one recorded warm-up pair, then 10 measured rounds per candidate group.
- Final live measurement: one recorded warm-up pair, then 30 measured rounds per candidate group.
- Executor exceptions or invalid return values become one safe
  `provider_error` observation; no automatic retry hides a scheduled attempt.
- Measured rounds alternate baseline/candidate execution order within each group.
  The runner creates fresh pair-scoped baseline and candidate sessions from the
  same workflow through the enabled loopback-only fresh-session marker; a cache
  warm-up prime uses a separate disposable session and cannot become part of
  the measured context.
- A successful pair's result fingerprint is an HMAC of the semantic direct
  response only. Request/session/draft/operation and materialization identities
  are canonicalized; cache outcome, latency, and other diagnostic fields are
  excluded so the fingerprint tests materialization parity rather than timing.
- Every scheduled final baseline/candidate row, including failures, remains in
  raw data and is counted before finalization. Success rate never replaces row
  cardinality, deterministic outcome validation, or artifact safety checks.
- The CACHE-05 report validates provider counts, outcomes, fingerprints, and
  paired parity before it writes an artifact bundle. The live runner additionally
  rejects a successful candidate row unless cold miss is `miss`, exact and
  normalization warm hit are `hit`, and semantic bypass is `bypass`; failures
  remain preserved safe rows rather than being reclassified as measurements.

## Authorized loopback runner

`tests/evaluation/run_agent_builder_cache_latency_benchmark.py` connects the
collector to a real, local Agent Builder boundary only when an operator starts
an authorized run. It requires two distinct direct-loopback base URLs:

- cache-off Gateway: cache disabled;
- cache-on Gateway: deterministic cache enabled with its dedicated local Redis
  configuration; and
- both Gateways: the diagnostic bridge enabled and the same current eligible
  user, organization, workflow graph/context, credential-model relation, and
  GPT-5.5 model relation.

The runner calls `model-options` and reads the ordinary workflow metadata on
each Gateway before it permits a provider request. It privately requires equal
workflow ID, app ID, and `updated_at` values across both arms; it rechecks that
same context before every pair and records a safe failed row without a provider
call if it changes. It then creates an ordinary Agent Builder session on each
Gateway. Each message uses the existing session message endpoint and reads only
the corresponding scoped diagnostic. The cache configuration is also proven by
the actual candidate outcome in every recorded row; a mismatched outcome
prevents final bundle publication.

Authentication cookie value, protected IDs, fingerprint key, endpoints, and all raw messages
are supplied only through ignored local configuration. The runner never prints
them. It accepts the raw JSON scenario only from an ignored `.json` path below
`local/mba-350/` in its own worktree; a tracked or external path is rejected
before parsing. The private JSON scenario file uses
`schema_version=mba-350-live-scenarios-v1`, has `development` and `final`
sections, and holds one distinct entry for each group and round:

- development: 10 measured entries plus 1 warm-up entry per group;
- final: 30 measured entries plus 1 warm-up entry per group; and
- `normalization_warm_hit`: each entry has separate non-empty `prime` and
  `measure` messages; all other groups have one non-empty message.

A recorded warm-up pair runs before each group's measured pairs and always uses
its dedicated final scenario entry, so it cannot turn the first measured
`cold_miss` into a warm cache hit. A normal command is:

```powershell
python tests/evaluation/run_agent_builder_cache_latency_benchmark.py `
  --phase all `
  --scenarios local/mba-350/live-scenarios.json
```

The runner validates both development and final rows against the existing
CACHE-05 row, pair, outcome, and redaction contract before it writes local
proof or emits the final artifact bundle. Its repository root is fixed to the
worktree containing the runner; another Git worktree is rejected. Development
rows go only to an ignored `.csv` path below `local/mba-350/evidence/`; an
output outside that boundary or a trackable output is rejected before writing.
Final rows may produce the Git bundle only at the fixed path. It creates normal
Agent Builder session/request records in the local development environment but
never acknowledges a graph mutation.

## Artifact publication

The collector builds `live_measurement` metadata and delegates all rendering,
row validation, and artifact redaction to the staged CACHE-05 report tool.
The only final output path is:

```text
docs/features/agent-builder-cache/benchmarks/<safe-benchmark-id>/
```

The caller provides a structural tracking preflight before this directory is
written. It must reject ignored or otherwise untrackable destinations. The
report tool then permits only its allowlisted raw CSV, summary, README, and SVG
files. `local/mba-350` remains planning/evidence storage, not a final bundle.

## Non-goals

- actual GPT-5.5 calls during unit or static verification;
- production/staging serving activation;
- Graph RAG, semantic/vector search, product API/client, or Redis changes;
- a replacement for CACHE-05 reporting or artifact-redaction validation.
