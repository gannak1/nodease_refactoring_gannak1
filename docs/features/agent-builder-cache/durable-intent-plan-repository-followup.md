# Durable Intent Plan Repository Implementation Record

Status: In Progress

This document records the JEO-7 implementation sequence for the durable Agent Builder
Intent Plan repository. The authoritative decision is [ADR-0075](../../decisions/ADR-0075-agent-builder-durable-intent-plan-repository.md);
the feature contract is [requirements.md](requirements.md), [api_spec.md](api_spec.md) and
[test_cases.md](test_cases.md).

## Start Record

- Implementation starts from the current `dev` head on the Git branch configured by the JEO-7 Linear issue.
- No implementation state is carried from a pre-agreement branch. The first repository changes are the decision,
  feature-contract and test-plan records in this directory and `docs/decisions/`.

## Agreed Boundary

- Redis remains the L1 serving cache. PostgreSQL is an optional tenant-scoped L2 for encrypted strict `CachedIntentPlanV1` values only.
- L1 is checked first. Only an L1 miss in an allowlisted organization reaches L2; a valid L2 result must pass the same current revalidation and rehydration before L1 promotion.
- Cache-eligible cold results use synchronous DB-first persistence: an isolated L2 transaction commits before any L1 write. L2 failure preserves the Planner response but prevents that cold result from entering L1.
- L2 retention is immutable 30 days from creation. Reads do not extend it; bounded background purge hard-deletes expired rows without a per-row cache audit.
- L2 starts disabled, then can progress through `write_only` and `read` for a strict UUID allowlist. Production activation and actual allowlist values are not part of this issue.
- The existing request history records only `intent_cache_outcome`; it never records cache layer/source, keys, envelope, plan or protected identifiers.

## Implementation Sequence

1. Record the accepted decision, feature requirements, internal API contract, data model, test cases and protected-resource matrix before changing runtime behavior.
2. Write failing unit tests for repository lookup token/envelope integrity, keyring configuration, safe serialization and mode/allowlist admission.
3. Add the additive model and migration with organization cascade, unique lookup index, expiry index and downgrade guard; add PostgreSQL migration tests.
4. Implement the L2 repository with short independent transactions and no provider, Redis wait or request-owned transaction held during DB I/O.
5. Extend the existing coordinator from `L1 -> Planner` to `L1 -> L2 -> Planner`, preserving the L1 single-flight contract and enforcing DB-first write ordering.
6. Persist the single allowlisted request-history outcome, then add bounded retention purge scheduling without cache payload audit.
7. Run the targeted unit, service, migration and redaction tests; record unavailable PostgreSQL/runtime checks as blocked rather than inferred complete.

## Explicitly Deferred

- Graph Template RAG ([JEO-6](https://linear.app/jeong-yeong-hoon/issue/JEO-6/graph-template-rag-설계-문서-정의))
- LLM node cache storage or serving
- Client UI, public cache endpoint, DB-backed cohort management UI/API
- Redis/PostgreSQL production rollout, actual allowlist activation and operational capacity evidence
