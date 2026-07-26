# Durable Intent Plan Repository Follow-up

Status: Draft

This is a future extension of [ADR-0063](../../decisions/ADR-0063-agent-builder-deterministic-intent-plan-cache.md) and the current [cache requirements](requirements.md).

## Purpose and current boundary

The current Agent Builder cache uses Redis as the only serving cache. PostgreSQL records only allowlisted diagnostic and audit facts; it does not store an Intent Plan, restore a Redis entry, or replay a request after Redis data loss.

This document reserves a separate future feature for a durable, tenant-scoped Intent Plan repository. It does not authorize a database table, migration, write path, read path, or production rollout in the current deterministic Redis-cache work. Redis loss remains a cold miss until that later feature has its own Accepted ADR and implementation issue.

The repository is not a graph cache, GraphMutation replay store, raw-request archive, provider-payload archive, or substitute for current authorization.

## Intended serving model

When the later feature is explicitly enabled, Redis remains L1 and the durable repository is an optional L2 candidate source.

1. Complete normal request admission, rate limiting, foreground serialization, active organization and resource permission checks.
2. Build the current deterministic key material and validate current graph, target, Catalog, planner runtime, credential relation and Knowledge state.
3. Query Redis. A valid Redis hit is rehydrated against the current state and returns without a provider call.
4. Only after a Redis miss, query the repository by a tenant-scoped, versioned HMAC lookup token. The raw request and Redis key digest are never lookup columns or diagnostic fields.
5. Verify the durable envelope and strict Intent Plan codec, then run the same current-state revalidation and rehydration used for a Redis hit.
6. Promote only that accepted plan to Redis with the normal TTL. An invalid, expired, unauthorized or stale repository record is not promoted and continues through the ordinary cold Planner path.

Neither L1 nor L2 may return a completed graph, old node/edge UUID, GraphMutation operation, ParameterTask identity, Knowledge selection handle, credential reference, or authorization decision.

## Future write process

The later implementation may create a durable record only after all of the following are true for the current request.

1. The Planner result has passed schema and semantic validation.
2. Cache admission accepts the request and the result can be projected into a fully canonical, strict `CachedIntentPlanV1`. An unrepresentable topic/guidance, explicit value, raw payload or unsafe field makes it store-ineligible.
3. The record is bound to the active organization and to every cache-contract version needed for deterministic invalidation. It records only bounded, allowlisted lifecycle metadata and an expiry; it does not copy current protected-resource identities or mutable authorization results.
4. The plan is encoded with the strict codec and a repository-specific, key-bound authenticated envelope. Its key domain differs from both the Redis key domain and Redis value-MAC domain.
5. The database write uses an isolated short transaction. Network/provider calls, Redis waits and graph materialization never run while that transaction is open.
6. A repository write failure becomes only an allowlisted diagnostic. It does not turn an already valid Agent Builder result into an API failure.

Redis and database writes are deliberately not a distributed transaction. The future ADR must choose synchronous best-effort persistence or an outbox-backed writer; it must not infer durable storage from an audit event.

## Logical record contract

The future migration defines an additive, tenant-scoped logical record. SQL names, types, indexes and retention duration are deferred to the future ADR and migration review.

| Category | Allowed contract | Forbidden contract |
| --- | --- | --- |
| Ownership | organization scope and lifecycle/retention state | cached permission decision or reusable actor session |
| Lookup | repository-specific HMAC token and deterministic contract versions | raw request, plaintext cache key, full Redis digest, provider payload |
| Payload | bounded strict safe-plan envelope authenticated to its lookup token | completed graph, GraphMutation, UUID binding, raw topic/guidance text, secret, credential or explicit parameter value |
| Validity | created/expiry timestamps and allowlisted invalidation state | DB replay without current revalidation |
| Diagnostics | outcome/reason/latency and bounded version identifiers | raw request, cache payload, key material or protected-resource identifier |

The schema must make tenant cleanup, retention expiry and key-version retirement executable without broad scans. It must not reuse PostgreSQL audit tables or turn audit rows into cache candidates.

## Authorization, lifecycle and deletion

Before every durable read and before Redis promotion, the serving request freshly verifies active actor and organization membership; current model, credential relation and `use` permission; current workflow topology, selected target and lifecycle; current Catalog and canonical-text registry version; and current Knowledge hierarchy, permission, lifecycle and readiness.

A durable row can narrow a lookup to an organization, but never grants access. Organization deletion, retention expiry, HMAC key retirement and a material contract-version change make records unreadable before or at the same time protected resources become unavailable. The future design must define cascade/tombstone behavior, legal retention, operator access and an audit-safe purge workflow before accepting a migration.

## Migration and rollout sequence

1. Accept a dedicated ADR covering data classification, retention, deletion, lookup-token construction, encryption/MAC policy, read/write consistency and rollback.
2. Add an additive migration with organization isolation, a narrow lookup index, expiry/lifecycle fields and a downgrade contract. Do not backfill from Redis or PostgreSQL audit data.
3. Ship the schema with durable write and durable read disabled.
4. Run a write-only, metrics-only phase with synthetic or explicitly approved test data. Verify redaction, retention and deletion before serving a database hit.
5. Enable L2 reads for a bounded cohort only after permission-revocation, lifecycle, stale-record, integrity, Redis-promotion, concurrent-write and rollback tests pass.
6. Keep a kill switch that disables durable reads first. Disabling either cache layer always falls back to the existing Planner path without replaying a database record.

## Required verification

- A Redis miss plus valid durable candidate avoids a provider call only after complete current-state revalidation and rehydration succeeds.
- Revoked membership, credential/model relation, target mismatch, Catalog change, Knowledge lifecycle/permission change, envelope/MAC failure, expiry and key-version retirement reject the durable candidate and use the ordinary Planner path.
- A record cannot be read across organizations, cannot be restored from audit, and does not expose raw request/key/payload/protected identifiers in a response, log, metric, trace or fixture.
- Redis/database partial-write and partial-read failures fail open to the Planner without holding a database transaction during Redis or provider I/O.
- Migration upgrade/downgrade, retention purge, organization deletion and rollout kill-switch behavior are integration-tested with the real database.

## Open decisions

- Whether the L2 plan envelope needs application-layer encryption in addition to database-at-rest controls.
- Exact retention periods and deletion/tombstone policy by organization and deployment class.
- Whether the write path uses synchronous best-effort persistence or an outbox-backed asynchronous writer.
- The dedicated issue sequence, migration ownership and production rollout evidence required before enabling durable reads.
