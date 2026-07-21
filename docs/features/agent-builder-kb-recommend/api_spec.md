# Agent Builder KB Recommendation API Specification

Status: Draft

## 1. Boundary

MBA-342는 새로운 public retrieval endpoint를 추가하지 않는다. Agent Builder orchestration이 Knowledge candidate resolution 뒤 호출하는 내부 application port와 기존 Agent Builder Knowledge response의 safe provenance만 확장한다.

```text
Agent Builder orchestration
        |
        | StructuredRequest + authorized candidate snapshot
        v
KnowledgeRecommendationRetrievalPort
        |
        | internal KB score projection
        v
KnowledgeRAGRecommendationService
        |
        | opaque handles + safe scores
        v
existing Agent Builder response
```

Runtime RAG search response, citation response 및 workflow graph schema는 변경하지 않는다.

## 2. Internal Request

`KnowledgeRecommendationRetrievalRequest`는 process 내부 typed value object다. HTTP body 또는 durable session payload로 직렬화하지 않는다.

| Field | Type | Contract |
| --- | --- | --- |
| `organization_id` | UUID | Active organization과 일치해야 한다 |
| `actor_id` | UUID | Effective KB use 판정 subject |
| `safe_query_topics` | list[str] | 최대 20개, 정규화 후 전체 1,000자 이하 |
| `candidate_kb_ids` | list[UUID] | CandidateResolver가 권한 검증한 내부 ID |
| `candidate_snapshot_ref` | opaque string | 현재 request 범위의 authorization snapshot reference |
| `deadline_ms` | int | 서버 상한 이하의 절대 실행 예산 |
| `cancellation_predicate` | process-local callable | 동일 Gateway process의 bounded TTL/count cancel marker를 checkpoint에서 확인한다. DB/SQL을 사용하거나 직렬화하지 않으며 cross-process 늦은 적용은 request-status CAS가 차단한다 |

Raw message, raw graph, Collection/KB label, document/chunk content와 credential value는 request에 포함하지 않는다.

Score policy는 server-owned 상수 `parent_first_v1`이다. Request, HTTP field, session 또는 사용자 설정으로 다른 profile을 선택할 수 없다.

## 3. Internal Result

```text
KnowledgeRecommendationRetrievalResult
  state: complete | degraded
  scores:
    - knowledge_base_id: internal UUID
      parent_relevance: bounded float
      semantic_state: available | flat | hierarchy_unavailable
        | artifact_inconsistent | model_ambiguous | credential_unavailable
        | provider_unavailable | retrieval_unavailable
        | parent_search_timeout | cohort_budget_exceeded | deadline_exceeded
      safe_reason_code: fixed enum
  failed_cohort_count_bucket: zero | one | few | many
  latency_bucket: fixed enum
  candidate_count_bucket: zero | one | few | many
  result_count_bucket: zero | one | few | many
  cohort_count_bucket: zero | one | few | many
  metadata_fallback_count_bucket: zero | one | few | many
```

이 result는 Gateway process 안에서만 사용한다. `scores`만 KB별 score projection이며, 모든 count/latency bucket은 현재 authorization snapshot의 action audit observer를 위한 bounded aggregate telemetry다. 이 telemetry는 외부 response 또는 trace/log로 projection하지 않는다. 다음 값은 금지한다.

- parent 또는 child chunk ID
- document 및 document version ID
- content, preview 또는 heading
- vector 및 raw distance 배열
- provider request/response
- credential reference 또는 value
- 권한이 거부된 candidate identity 및 exact count

## 4. Provider Cohort Contract

1. CandidateResolver가 권한을 통과한 candidate snapshot을 만든다.
2. Retrieval adapter는 authorized candidate ID 집합만 사용해 한 번의 bounded bulk SQL로 candidate의 active retrieval artifact, embedding model과 `vector_dims(parent_embedding)`을 조회한다.
3. Candidate를 실제 embedding model과 vector dimension cohort로 그룹화한다. Parent row가 없거나 active artifact의 dimension이 일관되지 않은 candidate는 typed semantic-unavailable 상태로 분리한다.
4. safe query를 cohort별로 한 번 embed한다.
5. 하나의 bounded SQL query로 cohort의 parent chunk를 검색한다.
6. SQL 또는 adapter 계층에서 KB별 top parent score를 집계한다.
7. Application service에는 KB별 ID와 집계 입력 점수, 그리고 action audit observer에만 전달할 allowlisted bounded aggregate telemetry만 반환한다.

동일 model cohort 안에서 candidate별 embedding 호출이나 candidate별 SQL query를 수행하지 않는다.

Query budget은 cohort discovery bulk SQL 요청당 1회와 parent search SQL 처리 cohort당 1회로 구분한다. 처리 cohort는 최대 4개이므로 parent search SQL은 최대 4회이며 candidate-level N+1은 0이어야 한다.

\(C_c\)를 한 cohort의 authorized KB 수, \(P\)를 KB별 집계 parent 수, \(O_c\)를 application에 projection되는 KB score 행 수라고 한다. v1은 \(P=3\), \(O_c\le C_c\)다. SQL은 exact cosine 결과의 KB별 상위 3개를 내부 집계하고 KB당 최대 한 score 행만 projection한다. Raw parent row를 document/chunk order로 먼저 제한하지 않는다.

Parent statement timeout은 남은 전체 semantic deadline과 2초 중 작은 값이다. Timeout은 raw row cap이나 partial, order-biased score를 반환하지 않고 해당 cohort 전체를 semantic unavailable metadata fallback으로 처리한다. MBA-342는 fixed-dimension ANN index 또는 DB migration을 추가하지 않는다.

Query embedding 전에 credential resolver는 exact active embedding model catalog row를 요구한다. 서로 다른 provider의 catalog row가 같은 stored model ID와 일치하면 임의로 선택하지 않고 `model_ambiguous`로 degrade한다. Credential 후보는 active organization, valid 상태, verified model relation과 actor의 `use` 권한을 모두 만족해야 하며 다음 순서로 하나를 선택한다.

```text
relation_priority ASC
credential_created_at ASC
credential_id ASC
```

선택된 credential reference와 provider 세부정보는 retrieval request/result 또는 외부 응답에 projection하지 않는다. 일치 후보 부재, 복호화 실패 또는 provider 실패는 해당 cohort의 metadata fallback이며 다른 성공 cohort를 폐기하지 않는다.

## 5. Search Query Contract

검색 SQL은 다음 predicate를 모두 포함해야 한다.

```text
knowledge_base_id IN authorized_candidate_ids
chunk_level = 'parent'
document/document_version is retrieval-visible
organization scope matches request
embedding model cohort matches query vector
```

Parent similarity 연산은 pgvector cosine distance만 사용한다. BM25, PostgreSQL FTS, keyword retrieval, RRF, Euclidean/L2 distance 또는 이들과 cosine 점수의 결합은 이 port에서 허용하지 않는다.

Projection은 다음 값으로 제한한다.

```text
knowledge_base_id
normalized score or distance
per-KB rank needed for top-N aggregation
```

`DocumentChunk.content`를 select하거나 ORM entity 전체를 materialize하지 않는다.

## 6. Score Contract

### 6.1 Parent aggregation

질의 embedding \(q\)와 parent embedding \(p\)의 cosine similarity는 다음과 같다.

\[
\operatorname{cos}(q,p)=\frac{q \cdot p}{\lVert q\rVert_2\lVert p\rVert_2}
\]

pgvector가 반환한 cosine distance를 \(d_{\cos}\)라고 할 때 \(d_{\cos}=1-\operatorname{cos}(q,p)\)이며, parent 점수는 다음과 같이 제한한다.

\[
s(q,p)=
\begin{cases}
0, & 1-d_{\cos}\le 0 \\
1-d_{\cos}, & 0<1-d_{\cos}<1 \\
1, & 1-d_{\cos}\ge 1
\end{cases}
\]

v1은 추가 양수 cutoff를 적용하지 않으며 \(\tau=0\)이다. Parent query가 정상 완료된 경우 모든 \(s(q,p)\)가 0이어도 `semantic_state=available`과 `parent_relevance=0`을 반환한다. 이 상태는 metadata fallback 사유가 아니다.

한 KB의 정규화 parent 점수를 \(s_{(1)}\ge s_{(2)}\ge\cdots\ge s_{(m)}\)으로 정렬하고 \(k=\min(3,m)\)으로 둔다.

\[
R_{\mathrm{parent}}
=0.7s_{(1)}
+0.3\left(\frac{1}{k}\sum_{i=1}^{k}s_{(i)}\right)
\]

Parent 점수가 하나면 \(R_{\mathrm{parent}}=s_{(1)}\)이다. Parent score가 존재하지 않는 상태는 이 식에 빈 평균을 대입하지 않고 typed semantic-unavailable 상태로 반환한다.

### 6.2 KB relevance

선택 관련도 \(R\)의 범위는 \([0,1]\)이며 다음과 같다.

\[
R=
\begin{cases}
R_{\mathrm{parent}}, & \text{semantic available} \\
R_{\mathrm{metadata}}, & \text{semantic unavailable or flat}
\end{cases}
\]

\(R_{\mathrm{parent}}\)는 6.1의 parent 집계 점수이고 \(R_{\mathrm{metadata}}\)는 기존 safe metadata 관련도다. Semantic available이면 metadata 점수는 선택되지 않는다.

### 6.3 Final recommendation score

변수는 다음과 같다.

- \(T\): source tier 점수, 범위 \([0,1]\)
- \(A\): runtime availability 점수, 범위 \([0,1]\)
- \(F\): sync freshness 점수, 범위 \([0,1]\)
- \(S_{\mathrm{KB}}\): 최종 KB 추천 점수, 범위 \([0,1]\)

\[
S_{\mathrm{KB}}=
\begin{cases}
0, & R=0 \\
0.7R+0.1T+0.1A+0.1F, & R>0
\end{cases}
\]

Score는 요청 시 계산하며 DB, graph, Agent Builder session 또는 audit에 저장하지 않는다.

## 7. External Agent Builder Response

기존 `knowledge_resolution.collections[]`, `children[]`, `ungrouped_kbs[]` 구조를 유지한다. Candidate에는 기존 `score` 외 다음 safe field를 선택적으로 추가할 수 있다.

```json
{
  "kb_handle": "opaque",
  "selection_key": "opaque",
  "safe_label": "Knowledge Base",
  "score": 0.82,
  "reason_category": "content_match",
  "recommendation_state": "complete"
}
```

`flat`은 upstream adapter가 flat artifact임을 명시적으로 판정한 경우를 위한 내부 typed state다. 현재 PostgreSQL adapter는 usable parent row가 없다는 사실만으로 flat과 hierarchy 손실을 구분하지 않고 `hierarchy_unavailable`을 반환한다. 두 상태 모두 동일한 metadata fallback을 사용한다.

허용 enum:

| Field | Values |
| --- | --- |
| `reason_category` | `content_match`, `metadata_match`, `operational_fallback` |
| `recommendation_state` | `complete`, `degraded` |

Client는 이 값을 권한 또는 실행 준비 상태로 해석하지 않는다.

## 8. Error and Fallback Contract

| Condition | Result |
| --- | --- |
| Active organization mismatch | Existing resource-hidden or authorization failure |
| Candidate authorization infrastructure failure | Fail closed, retryable safe error |
| Safe query empty | Metadata-only recommendation |
| One embedding cohort unavailable | Other cohorts retained, failed cohort metadata fallback, degraded state |
| Embedding model maps to multiple providers | Affected cohort metadata fallback with safe `model_ambiguous` state |
| No authorized verified credential for cohort model | No provider call; affected cohort metadata fallback |
| All semantic cohorts unavailable | Metadata fallback, generic degraded warning |
| Query deadline exceeded | Completed bounded results plus safe degraded state, or metadata fallback |
| Parent statement timeout | Timed-out cohort returns no partial semantic scores and uses metadata fallback |
| No eligible candidate | Successful empty hierarchy |
| Stale handle at selection | Existing hierarchy refresh and reselect flow |

Provider exception, raw query, model response와 hidden candidate distribution을 FastAPI validation detail 또는 error message에 반사하지 않는다.

## 9. Persistence and Idempotency

- Recommendation retrieval은 read-only다.
- 정상 response 저장과 stale hierarchy refresh는 동일한 recursive recommendation-signal sanitizer를 거쳐 score, reason category와 recommendation/retrieval state를 durable request payload에서 제거한다.
- 같은 request retry가 graph write, audit data-change event 또는 external side effect를 만들지 않는다.
- Search score를 durable cache에 저장하지 않는다.
- Selection submission은 기존 operation ID, CAS 및 acknowledgement 계약을 유지한다.
- 정상 Knowledge 선택 materialization 뒤 recommendation retrieval과 Planner를 자동 재실행하지 않는다. Stale handle refresh도 권한/lifecycle metadata hierarchy만 갱신하며 semantic port를 구성하지 않는다.

## 10. Authorization and Redaction

- HTTP endpoint가 전달한 candidate ID를 신뢰하지 않는다.
- CandidateResolver의 current request snapshot만 internal request를 만들 수 있다.
- Adapter는 defense in depth로 organization 및 retrieval-visible predicate를 다시 적용한다.
- Recommendation action audit에는 `score_only_parent_cosine` strategy, fixed score profile, latency bucket, candidate/result/cohort/metadata-fallback/failed-cohort count bucket과 complete/degraded 상태만 기록한다.
- Trace에는 chunk, document 및 KB별 raw score를 저장하지 않는다.

## 11. Compatibility

- Existing client가 신규 safe field를 무시해도 선택과 저장이 동작한다.
- Flat KB는 기존 metadata-only ranking을 유지한다.
- Existing opaque handle과 graph materialization contract는 변경하지 않는다.
- Existing runtime RAG `hierarchy_mode`와 recommendation score profile은 서로 독립적이다.
