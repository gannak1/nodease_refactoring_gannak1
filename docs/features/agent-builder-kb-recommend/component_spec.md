# Agent Builder KB Recommendation Component Specification

Status: Draft

## 1. Design Goals

- Agent Builder orchestration과 runtime RAG implementation의 직접 결합을 피한다.
- Authorization, retrieval, score composition 및 UI projection을 서로 다른 소유 경계에 둔다.
- Recommendation path에서 chunk 원문이 application 또는 presentation 계층으로 올라오지 않게 한다.
- Existing Collection/KB 선택 UI와 GraphMutation 저장 흐름을 유지한다.

## 2. Component Ownership

| Component | Ownership | Responsibility |
| --- | --- | --- |
| `AgentBuilderService` | Gateway orchestration | Structured request와 Knowledge timing을 조정한다 |
| `KnowledgeCandidateResolver` | Knowledge authorization | Organization, permission, lifecycle 및 candidate budget을 적용한다 |
| `KnowledgeRecommendationRetrievalPort` | Application boundary | Authorized IDs와 safe query를 받아 KB별 semantic score를 반환한다 |
| `RecommendationEmbeddingCredentialResolver` | Gateway credential authorization | Exact embedding model에 대해 active organization, verified relation과 actor `use` 권한을 적용하고 deterministic credential을 선택한다 |
| `PostgresParentRecommendationAdapter` | Gateway adapter | Cohort별 query embedding과 bounded parent score SQL을 수행한다 |
| `KnowledgeRAGRecommendationService` | Recommendation policy | Semantic available이면 parent relevance, unavailable이면 metadata relevance를 선택하고 operational signal을 결정적으로 적용한다 |
| `KnowledgeSelectionControl` | Client presentation | Existing hierarchy, score와 safe reason만 표시하고 선택을 관리한다 |

`apps/workflow_engine/services/retrieval.py`를 Agent Builder에서 직접 import하지 않는다. Runtime service는 citation, evidence content와 execution context까지 책임지므로 recommendation boundary보다 넓다. 공통화가 필요하면 content를 반환하지 않는 query predicate 및 score normalization helper만 `apps/shared/`의 순수 helper로 추출한다.

## 3. Dependency Direction

```text
Agent Builder orchestration
        |
        v
CandidateResolver -----> authorization adapters
        |
        v
RecommendationService --> RecommendationRetrievalPort
                                |
                                v
                         Postgres adapter
                                |
                                +--> embedding client
                                +--> pgvector cosine search

RecommendationService --> response mapper --> Client
```

금지 방향:

```text
Client -> DB
RecommendationService -> workflow runtime node
Retrieval adapter -> Agent Builder session write
Planner -> raw parent content
```

## 4. Sequence

```text
1. User request is structured
2. CandidateResolver builds authorized bounded candidate snapshot
3. Safe topics are normalized into a bounded recommendation query
4. Candidates are grouped by embedding model cohort
5. Each cohort embeds the query once
6. Parent-only score query runs for all cohort KBs
7. Adapter returns KB score projection without content
8. RecommendationService selects parent relevance for semantic success or metadata relevance for semantic-unavailable fallback
9. Collection scores are derived from unique child KB scores
10. Existing hierarchy response is rendered
11. User confirms Collection/KB selection
12. Existing selection endpoint, GraphMutation, CAS and acknowledgement run
```

## 5. Retrieval Port

Port implementation rules:

- Input candidate IDs must originate from one current CandidateResolver snapshot.
- The port accepts an absolute deadline and a live cancellation predicate bound to the current Agent Builder request. Same-process cancellation is read from a bounded TTL/count process-local marker without DB pool checkout or SQL; request-status CAS rejects cross-process late application. Predicate failure is fail-closed and its callable or error detail is never serialized.
- The port returns no ORM entity and no text.
- Result order has no product meaning; RecommendationService owns stable sorting.
- Partial cohort failures are represented as typed state, not exceptions containing provider details.
- Authorization infrastructure failure is not converted to partial success.

## 6. Query Adapter

### 6.1 Cohort discovery

After CandidateResolver succeeds, the adapter uses only the authorized candidate ID set in one bounded PostgreSQL bulk discovery. It projects candidate ID, active retrieval artifact embedding model and `vector_dims(parent_embedding)` needed for grouping and never loads chunk content. Candidate-level discovery queries are forbidden. Missing parent rows become hierarchy unavailable; multiple dimensions in one active artifact become artifact inconsistent. Both states remain authorized candidates and use metadata fallback without a provider call.

### 6.2 Parent search

Use one query embedding per unique cohort. For cohort authorized KB count \(C_c\), parent search uses one bounded SQL and a window function or equivalent grouping to aggregate the best \(P=3\) cosine parents per KB. It projects at most \(O_c\le C_c\) KB score rows and never projects parent rows or identity. Candidate count must not create one query per KB.

The exact query does not pre-limit parent rows by document/chunk order because that would bias relevance toward early content. The statement timeout is the smaller of 2 seconds and the remaining overall deadline. Timeout discards the cohort's partial semantic work and returns a typed metadata-fallback state. This issue does not add an ANN index or migration.

The adapter uses pgvector cosine distance only. It must not invoke BM25, PostgreSQL FTS, keyword retrieval, RRF or Euclidean/L2 score fusion.

The adapter receives an already authorized credential selection from `RecommendationEmbeddingCredentialResolver`; it does not search for an arbitrary key. The resolver orders eligible credentials by relation priority, creation time and credential ID. Missing, ambiguous, denied, undecryptable or provider-failed credentials become typed cohort-local fallback states without exposing credential identity.

### 6.3 Flat and unavailable candidates

The adapter contract accepts typed states for flat, hierarchy unavailable and provider unavailable candidates. The current PostgreSQL adapter emits `hierarchy_unavailable` when no usable parent exists because absence alone cannot prove that the source artifact is flat; `flat` is reserved for an explicit upstream adapter signal. It does not remove these candidates. RecommendationService applies metadata fallback.

## 7. Recommendation Policy

RecommendationService remains the only owner of:

- relevance composition
- operational signal composition
- confidence and reason category
- Collection score aggregation
- display cap and stable ordering

The retrieval adapter must not know Collection membership or UI limits.

## 8. Frontend

No new screen is introduced. Existing hierarchy is retained.

```text
Workflow Knowledge 설정

[ ] 사내 문서 Collection                         0.84
    Knowledge Base 문서 내용을 기준으로 평가했습니다.
    [ ] 인사 정책 KB                             0.90
    [ ] 복지 안내 KB                             0.76

[ ] 프로젝트 안내 KB                            0.52
    KB 설명을 기준으로 추천했습니다.

[Knowledge Base 없이 계속] [선택 적용]
```

Display rules:

- `content_match`: `Knowledge Base 문서 내용을 기준으로 평가했습니다.`
- `metadata_match`: `KB 설명과 주제가 요청과 관련됩니다.`
- `operational_fallback`: 상세 원인을 숨기고 generic fallback copy를 사용한다.
- `degraded`: 목록과 사용자의 기존 선택을 유지하고 상단에 재시도 가능한 일반 안내를 표시한다.
- Internal enum, raw score breakdown, parent identity와 provider 오류는 표시하지 않는다.

Credential catalog, verified relation과 `use` 권한 조회는 bounded retrieval transaction에서 수행한다. Decrypted config로 provider client를 구성한 뒤 이 transaction을 종료하고 실제 embedding HTTP I/O를 시작한다. Provider-native timeout은 credential lookup 경과 시간을 차감한 남은 cohort budget을 사용한다.

Selection state, Collection parent behavior, duplicate KB synchronization과 timing별 CTA는 기존 계층 선택 계약을 변경하지 않는다.

## 9. State Model

```text
idle
  -> authorizing
  -> retrieving
  -> ranked
  -> awaiting_selection

retrieving
  -> degraded_ranked
  -> awaiting_selection

authorizing
  -> failed_closed
```

`degraded_ranked`는 선택 가능한 정상 UI다. `failed_closed`는 hidden resource 정보를 표시하지 않고 현재 request를 안전하게 종료하거나 명시적 재시도만 제공한다.

## 10. Concurrency and Freshness

- Recommendation result is bound to current Agent Builder request and candidate snapshot.
- A stale response cannot replace a newer Knowledge resolution.
- Selection always rechecks permission, lifecycle and handle ownership.
- Candidate membership changes after rendering use the existing stale-handle refresh flow.
- Scores are not refreshed on a timer and are not persisted. The normal response path and stale hierarchy refresh share the same recursive recommendation-signal sanitizer.

## 11. Audit and Metrics

Allowed metrics:

- fixed strategy
- score profile
- candidate and result count bucket
- embedding cohort count bucket
- complete/degraded state
- latency and timeout bucket
- metadata fallback count bucket
- failed cohort count bucket

`AgentBuilderService` binds the observer to the current request and writes one action audit per semantic recommendation evaluation. The observer receives only these bounded fields. Candidate identity, query text, per-KB score and provider payload are not part of the observer type.

Forbidden metrics:

- raw query or topics
- parent/chunk/document identity
- raw similarity by KB
- source title/path/URL
- provider payload
- hidden or denied candidate distribution

## 12. Release And Rollback

- `parent_first_v1`은 사용자 선택이나 신규 generic feature flag가 아니다.
- ADR-2000, 문서 정합성, PostgreSQL/provider 검증과 정량 release gate가 모두 완료되기 전에는 기능 문서를 Active로 전환하거나 변경을 merge하지 않는다.
- Rollback은 일반 배포 rollback으로 이전 metadata-only 구현을 복원한다. Graph, session 또는 DB score migration은 없다.
