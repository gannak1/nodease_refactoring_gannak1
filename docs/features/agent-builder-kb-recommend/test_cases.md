# Agent Builder KB Recommendation Test Cases

Status: Draft

## 1. Test Policy

Implementation follows TDD. Each contract change starts with a test that fails for the intended reason. Tests must validate behavior at the narrowest authoritative boundary and avoid duplicating the same assertion across every layer.

PostgreSQL-specific vector, permission and query-count behavior is not considered verified by mocked unit tests.

## 2. Unit Tests

| ID | Case | Expected |
| --- | --- | --- |
| ABKR-U-001 | Parent scores contain one result | `0.7 * max + 0.3 * top-3 mean` equals that single normalized score |
| ABKR-U-002 | More than three parent scores | Exact `0.7 * s_(1) + 0.3 * mean(s_(1)..s_(3))` is used and lower scores do not contribute |
| ABKR-U-003 | Duplicate parent row produced by a relational join | Parent contributes once to the cosine aggregate |
| ABKR-U-004 | Semantic and metadata relevance both exist | `parent_first_v1` selects parent relevance only, even when metadata relevance is higher |
| ABKR-U-005 | Flat KB | Metadata relevance is preserved |
| ABKR-U-006 | Hierarchy unavailable | Candidate remains selectable with metadata fallback |
| ABKR-U-007 | Empty safe query | No embedding request and metadata-only ranking |
| ABKR-U-008 | Equal final scores | Safe label and opaque handle produce stable ordering |
| ABKR-U-009 | Same KB appears in multiple Collections | KB score is calculated once and reused |
| ABKR-U-010 | Collection children include duplicate KB | Collection aggregate deduplicates by KB ID |
| ABKR-U-011 | Cosine similarity is 0.83 | Normalized parent score is exactly 0.83 within numeric tolerance |
| ABKR-U-012 | Caller or transport supplies snake_case or camelCase score profile | Input is rejected as non-contract data, unrelated legacy extra fields keep compatibility and server-owned `parent_first_v1` remains fixed |
| ABKR-U-013 | Cosine similarity is zero or negative | Normalized parent score is 0 |
| ABKR-U-014 | Floating-point result exceeds cosine upper bound | Normalized parent score is at most 1 |
| ABKR-U-015 | Parent search succeeds and every normalized score is 0 | Semantic state remains available, parent relevance is 0 and metadata does not replace it |
| ABKR-U-016 | Selected relevance is 0 while source tier, availability and freshness are positive | Final KB recommendation score is exactly 0 |

## 3. Authorization Tests

| ID | Case | Expected |
| --- | --- | --- |
| ABKR-A-001 | Organization mismatch | Candidate never reaches retrieval port |
| ABKR-A-002 | KB use denied | KB ID is absent from embedding cohort and SQL parameters |
| ABKR-A-003 | Collection route allowed but child use denied | Child is not searched or scored |
| ABKR-A-004 | Authorization repository failure | Fail closed before provider and DB retrieval |
| ABKR-A-005 | Permission revoked after recommendation | Selection endpoint rejects stale handle safely |
| ABKR-A-006 | Source ACL revoked | Candidate is excluded before retrieval |
| ABKR-A-007 | Hidden candidates exist | Response and telemetry do not reveal identity or exact count |

## 4. PostgreSQL Retrieval Tests

| ID | Case | Expected |
| --- | --- | --- |
| ABKR-PG-001 | Hierarchical and child rows coexist | Query scores parent rows only |
| ABKR-PG-002 | Old and active document versions coexist | Active ready retrieval-visible version only |
| ABKR-PG-003 | Candidate set includes two KBs in one model cohort | One bounded search query returns per-KB scores |
| ABKR-PG-004 | Candidate set spans embedding models | One embedding/query sequence per cohort |
| ABKR-PG-005 | Authorized candidates span vector dimensions | One bulk discovery groups exact `vector_dims` into separate cohorts without candidate-level SQL |
| ABKR-PG-006 | 5,000 authorized candidates | Application projection is at most one KB score row per candidate and query count stays bounded |
| ABKR-PG-007 | Candidate has no parent rows | Typed hierarchy-unavailable result, no removal |
| ABKR-PG-008 | Projection inspection | SQL result contains no content, heading or document identity |
| ABKR-PG-009 | Permission changes during request | Selection revalidation prevents stale application |
| ABKR-PG-010 | One active artifact contains inconsistent parent dimensions | Candidate becomes artifact-inconsistent metadata fallback and no provider call is made for it |
| ABKR-PG-011 | Denied KB has parent embeddings | Its ID is absent from bulk dimension discovery parameters and results |
| ABKR-PG-012 | 5,000 authorized candidates across four cohorts | Cohort discovery SQL is exactly 1, parent search SQL is at most 4 and candidate-level SQL is 0 |
| ABKR-PG-013 | Parent search query contract is inspected | Query uses pgvector cosine distance and contains no FTS, BM25, keyword, RRF or L2 score path |
| ABKR-PG-014 | Relevant parent appears late in document order after many irrelevant parents | Exact cosine top-3 can select it; no document-order raw row cap excludes it |
| ABKR-PG-015 | Parent query exceeds its 2-second-or-remaining statement timeout | No partial semantic score is used and only the timed-out cohort uses metadata fallback |
| ABKR-PG-016 | More than four cohorts are discovered | Fifth and later cohorts use `cohort_budget_exceeded`, not timeout state |
| ABKR-PG-017 | One cohort has multiple KBs with many parent rows | SQL aggregates at most top 3 per KB and returns at most one score row per KB without content or identity |

## 5. Provider and Failure Tests

| ID | Case | Expected |
| --- | --- | --- |
| ABKR-F-001 | One cohort embedding provider fails | Other cohort results retained, failed cohort metadata fallback |
| ABKR-F-002 | All providers fail | Metadata-only ranked response with degraded warning |
| ABKR-F-003 | Deadline expires | Work stops within grace, no unbounded wait |
| ABKR-F-004 | Request cancellation | Same-process bounded marker probe performs no DB/SQL work, stops not-yet-started provider/DB/cohort work, and request-status CAS prevents cross-process late result application |
| ABKR-F-005 | Credential use denied | No provider call; affected cohort follows safe policy |
| ABKR-F-006 | Provider returns malformed embedding | Safe degraded result without raw response leakage |
| ABKR-F-007 | Authorization infrastructure fails after retry | No partial candidate response |
| ABKR-F-008 | Multiple authorized credentials support one cohort model | Lowest relation priority, then oldest creation time, then lowest credential ID selects exactly one credential |
| ABKR-F-009 | Stored model ID resolves to active embedding models from multiple providers | No provider is guessed; affected cohort uses metadata fallback with safe model-ambiguous state |
| ABKR-F-010 | Credential lookup consumes part of the embedding budget | Provider-native timeout receives only the remaining budget |
| ABKR-F-011 | Credential snapshot is ready before provider I/O | Retrieval transaction ends before the external embedding request starts |
| ABKR-F-012 | Credential is valid and verified but belongs to another organization | Credential is excluded and never used for a provider call |
| ABKR-F-013 | Credential exists but actor lacks `use` | Credential is excluded and its identity is absent from response, audit, trace and log |
| ABKR-F-014 | One credential has duplicate verified model relation rows | Rows collapse by credential ID using the lowest relation priority before deterministic selection; the credential remains eligible |

## 6. Service and API Tests

| ID | Case | Expected |
| --- | --- | --- |
| ABKR-S-001 | Relevant parent content, empty safe metadata | KB receives content-based recommendation |
| ABKR-S-002 | Metadata match, irrelevant parent content and successful parent search | Parent relevance remains authoritative and metadata does not raise the score |
| ABKR-S-003 | Flat and hierarchical candidates mixed | Both remain selectable and deterministically ordered |
| ABKR-S-004 | Collection and direct KB mixed | Existing hierarchy response and opaque handles are preserved |
| ABKR-S-005 | Retrieval complete | Safe `content_match` reason only |
| ABKR-S-006 | Retrieval degraded | Safe state and generic warning, no provider detail |
| ABKR-S-007 | No eligible candidates | Successful empty hierarchy and no-Knowledge action |
| ABKR-S-008 | Response serialization | No KB UUID, chunk/document identity or raw text |
| ABKR-S-009 | Knowledge selection submitted | Planner and recommendation retrieval are not called again |
| ABKR-S-010 | Retry same request | No graph write, duplicate audit or durable score record |
| ABKR-S-011 | Stale Knowledge selection handle refresh | Permission/lifecycle metadata hierarchy is refreshed without semantic port or Planner call, and its score/reason/state is not persisted |
| ABKR-S-012 | Recommendation observation | Action audit contains only fixed strategy/profile, bounded count/latency buckets and complete/degraded state; no candidate ID, query, per-KB score or provider payload |

## 7. Frontend Tests

| ID | Case | Expected |
| --- | --- | --- |
| ABKR-C-001 | `content_match` candidate | Safe Korean explanation rendered |
| ABKR-C-002 | `metadata_match` candidate | Metadata explanation rendered |
| ABKR-C-003 | Degraded result | Existing selection and list retained, generic warning shown |
| ABKR-C-004 | Unknown reason enum | Generic copy, internal enum not displayed |
| ABKR-C-005 | Existing client shape without new fields | Existing hierarchy remains functional |
| ABKR-C-006 | Collection/KB interaction | Existing selection semantics remain unchanged |

## 8. Redaction Tests

Inspect API response, error body, audit metadata, trace metadata and captured logs for:

- raw safe query topic values where durable storage is forbidden
- parent or child content
- heading, source title/path/URL
- document, version or chunk identity
- provider request/response
- credential value or reference
- hidden KB identity and exact denied count

Tests must use synthetic non-secret markers and assert their absence. Real tokens or sensitive content are forbidden in fixtures.

## 9. Evaluation Tests

| ID | Case | Expected |
| --- | --- | --- |
| ABKR-E-001 | Controlled aggregate dataset | At least 30 deterministic synthetic non-secret cases, including at least 10 metadata-poor cases; no production KB identity, raw query/content or ranked list is written |
| ABKR-E-002 | Baseline and parent-first release evaluation | Aggregate-only Precision@5, Recall@5, MRR, no-result accuracy, latency and bounded-call/query evidence is compared against the stated release gate |

Create an offline dataset containing:

- KB with unrelated name but relevant parent content
- KB with matching name but irrelevant content
- flat-only KB
- duplicated KB under multiple Collections
- permission-denied distractor KB
- Korean and English requests

Use at least 30 deterministic cases, including at least 10 metadata-poor cases with relevant parent content. Compare the metadata-only baseline and `parent_first_v1` on the same authorized candidate snapshot using Precision@5, Recall@5, MRR and no-result accuracy. Record p50, p95 and hard deadline latency, embedding calls, cohort discovery SQL, parent SQL and candidate-level SQL per request.

Release gate:

- Permission leakage: 0
- Raw content/document/chunk identity leakage: 0
- Recall@5: metadata-only baseline 이상
- Precision@5: metadata-only baseline 대비 하락 2 percentage point 이내
- MRR: metadata-only baseline 이상
- Metadata-poor subset Recall@5: metadata-only baseline 대비 최소 10 percentage point 개선
- No-result accuracy: metadata-only baseline 이상
- Semantic latency: p50 3초 이하, p95 8초 이하, hard deadline/fallback 10초 이하
- Embedding calls: 실제 처리 cohort 수 이하이자 최대 4회
- Cohort discovery SQL: 요청당 정확히 1회
- Parent SQL: 실제 처리 cohort 수 이하이자 최대 4회
- Candidate-level SQL N+1: 0
- 5,000 authorized candidate budget에서 위 호출·query budget 유지
- Timeout contract: bounded and reproducible, timed-out cohort metadata fallback

## 10. Planned Commands

Exact paths may change during implementation; the final matrix must record commands actually run.

```text
python -m pytest apps/gateway/tests/services/test_knowledge_rag_recommendation_service.py
python -m pytest apps/gateway/tests/services/test_knowledge_permission_phase2.py
python -m pytest apps/gateway/tests/integration/<recommendation_retrieval_postgres_test>.py
python -m pytest apps/shared/tests/services/test_rag_hierarchy.py
npm test -- app/features/workflow/components/agentBuilder/AgentBuilderPanel.test.tsx
npm run typecheck
npm run lint
git diff --check
```

Authenticated browser smoke verifies list ordering, degraded state, selection and save. It does not inspect hidden candidate content.
