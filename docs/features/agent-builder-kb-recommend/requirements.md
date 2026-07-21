# Agent Builder KB Recommendation Requirements

Status: Draft

Related Features: Agent Builder, Knowledge, Hierarchical RAG, Knowledge Collection, RBAC, LLM Credential, Audit and Tracing

## 1. Purpose

Agent Builder의 Knowledge 추천은 KB 이름과 안전한 설명만 비교하는 방식에서 벗어나, 권한이 확인된 hierarchical KB의 parent chunk 검색 결과를 KB 단위 관련도로 집계한다. 이 기능은 답변을 생성하는 RAG가 아니라 Agent Builder가 사용자에게 검토 가능한 Collection 및 KB 후보를 정렬하는 내부 retrieval 단계다.

이 문서는 MBA-342의 목표 계약이다. Accepted ADR-2000은 Agent Builder 생성 및 추천 중 retrieval을 금지하는 기존 일반 계약에 다음 좁은 예외를 승인한다.

> Agent Builder는 권한 검증된 후보 범위 안에서 원문을 반환하지 않는 recommendation retrieval을 수행할 수 있다. 검색 결과는 KB 단위 집계 점수로만 Recommendation Adapter에 전달하며 Planner, Client, audit, trace 및 log에 chunk 원문이나 identity를 전달하지 않는다.

이 feature의 P1-P8 구현은 MBA-342 integration worktree에 통합되었고 선택 회귀 402건의 실행 기록이 있다. 실제 PostgreSQL/provider/browser/observability 및 정량 release evidence가 아직 없으므로 `Draft`와 `Verification Blocked`를 유지한다.

## 2. Problem

현재 추천 관련도는 `safe_query_topics`와 다음 safe metadata의 문자열 일치를 사용한다.

- `safe_label`
- `kb_safe_description`
- `kb_safe_topics`

따라서 실제 문서 내용이 요청과 관련되어도 KB 이름과 설명이 추상적이거나 비어 있으면 관련도 점수가 0이 될 수 있다. 반대로 이름만 일치하고 실제 문서 근거가 빈약한 KB가 상위에 노출될 수 있다.

Knowledge runtime에는 parent chunk를 coarse retrieval에 사용하고 선택된 parent의 child chunk를 최종 근거로 사용하는 계층 검색이 이미 존재한다. 추천기는 이 중 parent 검색 의미만 재사용해야 한다.

## 3. Scope

### 3.1 Included

- StructuredRequest에서 파생한 bounded safe query 생성
- active organization 및 effective KB `use` 권한을 통과한 후보만 검색
- hierarchical KB의 retrieval-visible parent chunk에 대한 pgvector cosine vector-only 검색
- parent 검색 결과의 KB 단위 결정적 집계
- semantic 검색 성공 시 parent relevance를 선택하고 검색 불가능 시에만 safe metadata relevance fallback
- flat KB 및 hierarchy unavailable 후보의 metadata fallback
- 기존 Collection 및 direct KB 추천 점수 계산과의 통합
- 검색 budget, timeout, cancellation 및 degraded fallback
- raw content와 hidden resource 비노출
- 추천 정확도, 권한, query 수 및 redaction 테스트

### 3.2 Excluded

- LLM이 생성한 문서 요약 및 summary embedding
- 기존 문서 backfill 또는 신규 DB migration
- ingestion의 parent-child chunking 방식 변경
- workflow runtime의 parent-child retrieval 및 citation 변경
- Agent Builder Collection/KB 선택 UI 재설계
- Planner 재호출 또는 Knowledge 선택 뒤 자연어 재제출
- 콘텐츠가 같지만 ID가 다른 KB의 의미 중복 제거
- 추천 결과의 durable cache 및 새로운 replay 저장소
- BM25, PostgreSQL FTS, keyword retrieval, RRF 및 L2 score 결합

## 4. Terminology

- `Recommendation retrieval`: Agent Builder 후보 정렬을 위한 내부 검색. 답변 생성이나 citation 생성을 수행하지 않는다.
- `Parent relevance`: 안전한 질의와 retrieval-visible parent chunk embedding의 cosine 유사도를 KB 단위로 집계한 값이다.
- `Metadata relevance`: 기존 safe label, description 및 topics의 결정적 문자열 관련도다.
- `Degraded fallback`: semantic 검색을 수행할 수 없을 때 권한이 확인된 후보를 metadata relevance로만 정렬하는 상태다.
- `Eligible candidate`: active organization, permission, lifecycle 및 source visibility 검사를 통과해 추천 평가가 허용된 KB다.

## 5. Functional Requirements

### ABKR-FR-001 Authorization before retrieval

Recommendation retrieval은 후보 ID가 검색 SQL, embedding cohort 또는 점수 계산에 들어가기 전에 active organization과 effective KB `use` 권한을 확인해야 한다. 권한 판단 장애는 metadata fallback으로 낮추지 않고 fail-closed한다.

### ABKR-FR-002 Safe query

검색 질의는 StructuredRequest에서 파생한 `safe_query_topics`를 정규화해 만든다. 최대 topic 수와 전체 문자 수를 서버가 제한한다. Raw user message, raw graph, prompt, secret-like span과 source content는 query embedding 입력으로 사용하지 않는다.

### ABKR-FR-003 Embedding model cohorts

KB마다 embedding model이 다를 수 있으므로 eligible candidate를 embedding model별 cohort로 묶는다. cohort마다 질의 embedding을 최대 한 번 생성하고 해당 cohort의 KB를 한 번의 bounded parent 검색으로 평가한다. 서로 다른 차원의 vector를 같은 SQL 연산에 섞지 않는다.

CandidateResolver 권한 검증이 완료된 뒤 authorized candidate ID 집합만 사용해 요청당 한 번의 bounded PostgreSQL bulk discovery를 수행한다. Discovery projection은 KB ID, active retrieval artifact의 embedding model과 `vector_dims(parent_embedding)`으로 제한한다. Candidate별 dimension 조회는 금지한다. 조회 결과의 model/dimension 쌍으로 cohort를 만들며, usable parent row가 없는 KB는 hierarchy unavailable, 하나의 active artifact에서 여러 dimension이 발견된 KB는 artifact inconsistent로 분류해 metadata fallback한다.

각 model/dimension cohort의 query embedding credential은 다음 순서로 결정한다.

1. Parent artifact model ID와 정확히 일치하는 active embedding model catalog row를 찾는다.
2. 같은 model ID가 서로 다른 provider에 중복되어 parent provenance를 확정할 수 없으면 cohort를 model ambiguous로 분류한다.
3. Active organization 소속, valid 상태, 해당 model과 verified relation, 현재 Agent Builder actor의 credential `use` 권한을 모두 만족하는 credential만 남긴다.
4. Relation priority 오름차순, credential 생성 시각 오름차순, credential ID 오름차순으로 정렬해 첫 credential 하나를 선택한다.

동일 credential/model verified relation row가 중복되어도 credential ID별 lowest relation priority 하나로 축약한 뒤 위 순서를 적용한다. 중복 row가 정상 credential을 provider unavailable로 낮추어서는 안 된다.

선택 UI나 임의 provider fallback은 추가하지 않는다. Credential이 없거나 model이 모호하거나 복호화/provider 호출이 실패한 cohort는 metadata fallback한다. KB authorization 실패와 달리, 권한이 확인된 KB의 embedding credential unavailable은 해당 cohort의 degraded semantic-unavailable 상태다. 실제 provider 비용은 선택된 credential의 provider account에 귀속된다.

### ABKR-FR-004 Parent-only projection

검색은 다음 조건을 모두 만족하는 chunk만 사용한다.

- `chunk_level = parent`
- active ready document version 또는 승인된 legacy retrieval-visible 경계
- 현재 candidate KB 집합 소속
- 현재 organization 및 source visibility 경계 충족

Recommendation query는 chunk content를 application memory로 projection하지 않는다. DB adapter의 결과는 내부 KB ID와 정규화 전 거리 또는 점수로 제한한다.

### ABKR-FR-005 KB aggregation

질의 embedding을 \(q\), parent chunk embedding을 \(p\)라고 할 때 cosine similarity와 정규화 parent 점수는 다음과 같다.

\[
\operatorname{cos}(q,p)=\frac{q \cdot p}{\lVert q\rVert_2\lVert p\rVert_2}
\]

\[
s(q,p)=
\begin{cases}
0, & \operatorname{cos}(q,p)\le 0 \\
\operatorname{cos}(q,p), & 0<\operatorname{cos}(q,p)<1 \\
1, & \operatorname{cos}(q,p)\ge 1
\end{cases}
\]

pgvector cosine distance \(d_{\cos}=1-\operatorname{cos}(q,p)\)를 조회하는 경우에도 동일한 \(s(q,p)\)로 변환한다.

v1의 추가 cosine cutoff는 \(\tau=0\)이다.

\[
s_{\tau}(q,p)=
\begin{cases}
0, & s(q,p)\le 0 \\
s(q,p), & s(q,p)>0
\end{cases}
\]

따라서 usable parent embedding에 대한 검색이 정상 완료됐지만 모든 점수가 0인 경우에도 semantic 검색 성공으로 분류한다. 이 경우 parent relevance는 0이며 metadata relevance로 대체하지 않는다. 모델별 양수 threshold 보정은 v1 범위가 아니다.

한 KB의 정규화 parent 점수를 \(s_{(1)}\ge s_{(2)}\ge\cdots\ge s_{(m)}\)으로 정렬하고 \(k=\min(3,m)\)으로 둔다. `parent_first_v1`의 parent relevance는 다음 고정식으로 집계한다.

\[
R_{\mathrm{parent}}
=0.7s_{(1)}
+0.3\left(\frac{1}{k}\sum_{i=1}^{k}s_{(i)}\right)
\]

Parent 점수가 하나면 \(R_{\mathrm{parent}}=s_{(1)}\)이다.

검색 연산은 cosine vector search 하나만 사용한다. BM25, PostgreSQL FTS, keyword retrieval, RRF와 L2 결합은 실행하지 않는다. SQL join 등으로 동일 parent row가 중복되더라도 한 번만 집계한다. 점수가 없는 KB는 parent relevance를 0으로 둔다.

### ABKR-FR-006 Relevance composition

`parent_first_v1`에서 선택 관련도 \(R\)은 다음과 같다.

\[
R=
\begin{cases}
R_{\mathrm{parent}}, & \text{parent 검색 성공} \\
R_{\mathrm{metadata}}, & \text{parent 검색 불가능}
\end{cases}
\]

여기서 \(R_{\mathrm{parent}}\)는 ABKR-FR-005의 parent 집계 점수, \(R_{\mathrm{metadata}}\)는 기존 safe metadata 관련도이며 모두 범위는 \([0,1]\)이다. Parent 검색이 성공하면 metadata 관련도가 더 높아도 사용하지 않는다. Flat KB, hierarchy unavailable KB 또는 degraded cohort처럼 parent 검색이 불가능한 경우에만 \(R_{\mathrm{metadata}}\)를 사용한다.

최종 점수에 사용하는 나머지 변수는 다음과 같다.

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

모든 입력과 결과는 0과 1 사이로 제한한다. 고정 내부 정책 식별자는 `parent_first_v1`이며 응답에 내부 가중치나 raw distance를 노출하지 않는다.

### ABKR-FR-007 Collection aggregation

Collection 점수는 권한을 통과한 고유 하위 KB의 final score를 사용한다. 동일 KB가 여러 Collection에 연결되어도 parent 검색과 KB 점수 계산은 한 번만 수행한다. Collection 점수와 선택 의미는 계층형 Knowledge 선택 계약을 유지한다.

### ABKR-FR-008 Stable ordering

정렬은 final score 내림차순, safe label 오름차순, opaque handle 오름차순이다. 같은 입력, 같은 candidate snapshot과 같은 score profile은 같은 순서를 반환해야 한다.

### ABKR-FR-009 Budgets

- 전체 평가 KB 수는 기존 internal candidate budget을 넘지 않는다.
- 전체 authorized candidate budget은 최대 5,000 KB이고 처리 cohort는 최대 4개다.
- \(C_c\)는 한 cohort의 authorized KB 수, \(P\)는 KB별 집계 parent 수, \(O_c\)는 application projection의 KB score 행 수다. v1은 \(P=3\), \(O_c\le C_c\)를 적용해 SQL 내부에서 KB별 cosine 상위 3개를 집계하고 application에는 KB당 최대 한 행만 반환한다.
- Parent SQL은 처리 cohort당 한 번, 최대 4회이며 각 statement timeout은 남은 전체 deadline과 2초 중 작은 값이다.
- Raw parent를 document order나 chunk identity로 먼저 제한하지 않는다. 이러한 선행 cap은 뒤쪽의 관련 내용을 영구 제외하므로 v1 exact top-3 의미와 맞지 않는다.
- 현재 fixed-dimension ANN index와 migration을 이 이슈에 추가하지 않는다. Exact query가 statement timeout을 넘으면 해당 cohort를 metadata fallback한다.
- 현재 Agent Builder request의 cancellation predicate를 discovery 전후, provider 전후, parent SQL 전후와 cohort 사이에서 확인한다. 동일 Gateway process의 cancel API는 bounded TTL/count process-local marker를 기록하므로 이 predicate는 DB connection 또는 SQL을 소비하지 않는다. 다른 process에서 완료된 늦은 결과는 기존 request-status CAS가 최종 적용을 거부한다. timeout 또는 cancellation 뒤 아직 시작하지 않은 provider/DB 작업은 실행하지 않고, 이미 시작한 동기 provider/DB 작업의 늦은 결과는 적용하지 않는다.
- candidate 수에 비례한 KB별 N+1 SQL을 허용하지 않는다.

### ABKR-FR-010 Failure semantics

- Authorization, organization scope 또는 candidate snapshot 장애: fail-closed, retryable safe error
- 일부 embedding cohort provider 장애: 성공 cohort 유지, 실패 cohort metadata fallback, safe partial marker
- 전체 semantic retrieval 장애: metadata fallback과 safe degraded warning
- 후보 없음: 정상 empty result
- stale selection handle: 기존 Knowledge selection refresh 계약을 사용하되 refresh는 권한/lifecycle metadata hierarchy만 다시 계산하고 semantic recommendation retrieval 또는 Planner를 호출하지 않으며, refreshed hierarchy의 score/reason/state도 durable request payload에 저장하지 않음

장애 원문, provider response, SQL, hidden KB 수와 candidate identity는 반환하지 않는다.

### ABKR-FR-011 External response

외부 응답은 기존 opaque Collection/KB handle과 safe label을 유지한다. 추가 가능한 정보는 다음 allowlist로 제한한다.

- bounded final score
- `reason_category = content_match | metadata_match | operational_fallback`
- `recommendation_state = complete | degraded`
- safe retryability 및 generic warning

Parent chunk ID, document ID, raw distance, content preview 및 embedding model credential은 반환하지 않는다.

### ABKR-FR-012 No graph side effect

Recommendation retrieval은 workflow graph, Knowledge selection, ParameterTask, session history 또는 score를 저장하지 않는다. 사용자가 선택한 뒤에는 기존 GraphMutation, CAS save 및 acknowledgement를 사용한다.

## 6. Quality Requirements

- Permission filtering 결과와 recommendation query scope가 테스트에서 일치해야 한다.
- 5,000개 candidate budget에서도 query 수가 candidate 수에 선형으로 증가하지 않아야 한다.
- 관련 parent content가 있는 KB는 metadata-only baseline보다 precision 또는 recall이 악화되지 않아야 한다.
- Flat KB만 존재하는 조직에서 기존 추천 및 수동 선택 흐름이 유지되어야 한다.
- Recommendation action audit에는 safe strategy/score profile, latency bucket, candidate/result/cohort/metadata-fallback/failed-cohort count bucket과 complete/degraded 상태만 남긴다. Trace와 log에는 이 allowlist보다 넓은 payload를 추가하지 않는다.

## 7. Protected Resource Completion

MBA-331 기준에 따라 다음 경계를 하나의 기능으로 완료해야 한다.

| Boundary | Requirement |
| --- | --- |
| Contract/schema | Safe query, internal score projection, external allowlist |
| Authorization | Organization, KB use, source visibility before retrieval |
| Storage | Score, raw content 및 chunk identity 비영속화 |
| Preflight/runtime | 기존 실행 전 재검증과 의미가 달라지지 않음 |
| Lifecycle | Active ready parent만 semantic 평가, flat/degraded fallback |
| Provider | Embedding credential use, timeout, cost 및 partial failure |
| Audit/redaction | Raw query/content/provider response 비노출 |
| Test | Unit, PostgreSQL, integration, performance 및 evaluation |

## 8. Release Gate

다음 조건 전에는 Status를 Active로 변경하지 않는다.

1. Agent Builder recommendation retrieval 예외 ADR이 Accepted 상태다.
2. 관련 Agent Builder 및 Knowledge 문서가 같은 계약으로 갱신됐다.
3. PostgreSQL permission/query integration 테스트가 통과했다.
4. Precision/recall baseline과 latency budget이 기록됐다.
5. 보호 리소스 완결성 표의 필수 경계가 완료됐다.
