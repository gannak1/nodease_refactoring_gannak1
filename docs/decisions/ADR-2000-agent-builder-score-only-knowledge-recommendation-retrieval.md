# ADR-2000: Agent Builder Score-only Knowledge Recommendation Retrieval

Status: Accepted

Related ADRs: [ADR-0012](ADR-0012-metadata-aware-hierarchical-rag-boundary.md), [ADR-0027](ADR-0027-agent-builder-pre-intent-safe-kb-context.md), [ADR-0045](ADR-0045-agent-builder-direct-edit-parameter-guidance.md), [ADR-0046](ADR-0046-agent-builder-graph-mutation-and-cas-save.md), [ADR-0055](ADR-0055-agent-builder-intent-usage-attribution.md), [ADR-0061](ADR-0061-agent-builder-hierarchical-knowledge-selection.md)

## Context

Agent Builder는 현재 권한이 확인된 Knowledge Base의 안전한 metadata 문자열을 사용해 추천 관련도를 계산한다. 이 방식은 이름과 설명이 비어 있거나 실제 문서 내용과 다른 KB를 구분하기 어렵다. Knowledge ingestion은 이미 원본 문서의 큰 구간인 parent chunk embedding을 보유하므로, MBA-342는 새 문서 요약이나 summary embedding을 만들지 않고 이 자산을 추천 점수에 재사용하려 한다.

그러나 ADR-0045와 ADR-0046은 Agent Builder의 생성, 추천 및 GraphMutation lifecycle에서 Knowledge retrieval을 금지한다. ADR-0027이 허용하는 것도 권한이 먼저 적용된 안전한 KB metadata뿐이다. 따라서 feature 문서만 변경해서 parent chunk 검색을 추가할 수 없으며, 기존 금지 조항을 좁게 보정하는 새 권위 결정이 필요하다.

일반 workflow RAG는 답변 근거와 citation을 만들기 위해 document 및 chunk identity를 내부 trace에 다룬다. Agent Builder 추천은 답변 생성이나 evidence retrieval이 아니므로 그 계약을 그대로 재사용하면 필요한 정보보다 넓은 payload와 observability 경계가 유입된다.

## Decision

- ADR-0045와 ADR-0046의 일반적인 Knowledge retrieval 금지는 유지한다. 유일한 예외로, CandidateResolver의 권한·active organization·lifecycle 검증이 성공한 뒤부터 GraphMutation 생성 전까지 실행되는 read-only `score-only recommendation retrieval`을 허용한다.
- 이 예외는 Knowledge 후보의 정렬 점수를 계산하기 위한 내부 단계다. Planner 입력 보강, 답변 생성, citation 생성, workflow 실행 또는 GraphMutation 적용의 일부가 아니다.
- Agent Builder는 workflow runtime `RetrievalService`를 import하거나 호출하지 않는다. Application은 별도 `KnowledgeRecommendationRetrievalPort`에 의존하고, adapter가 query embedding과 parent score 조회를 조합한다.
- 안전한 bounded query는 이미 구조화된 사용자 요청에서 생성한다. 권한이 확인되지 않은 KB ID는 embedding cohort 구성이나 검색 SQL에 들어갈 수 없다. 권한 또는 active organization 검증 자체가 실패하면 외부 embedding 요청과 parent 검색을 실행하지 않고 fail-closed한다.
- 검색은 existing parent chunk embedding에 대한 cosine vector search만 사용한다. BM25, keyword/vector hybrid, RRF, L2 score fusion, LLM 생성 문서 요약 및 summary embedding은 이 결정의 범위가 아니다.
- 권한이 확인된 후보는 embedding model과 vector dimension으로 cohort를 나눈다. 요청당 cohort는 최대 4개이며, 각 cohort는 query embedding 1회와 bounded parent score SQL 1회만 사용한다. KB별 provider 호출과 KB별 SQL은 금지한다.
- 전체 semantic retrieval deadline은 10초다. 각 cohort의 embedding timeout은 남은 시간과 4초 중 작은 값, PostgreSQL statement timeout은 남은 시간과 2초 중 작은 값이다. Cohort 우선순위는 후보 수 내림차순 뒤 model/dimension의 안정 순서다. 늦게 완료된 취소·stale 결과는 적용하지 않는다.
- KB별 parent 관련도는 정규화 cosine 최고점 70%와 상위 최대 3개 평균 30%를 사용하는 결정적 집계다. 추가 양수 cutoff는 두지 않으며 같은 버전의 평가 fixture로 검증한다.
- 내부 score policy 식별자는 `parent_first_v1`로 고정한다. Parent 검색이 정상 완료되면 낮은 점수나 threshold 미달도 semantic 결과로 취급하며 metadata 점수로 덮어쓰지 않는다.
- Metadata ranking은 semantic 검색이 불가능한 권한 확인 후보에만 degraded fallback으로 사용한다. Flat KB, parent embedding 부재, 안전한 query 부재, cohort 상한 초과, provider/DB timeout 또는 semantic infrastructure 실패가 이에 해당한다. 일부 cohort만 실패하면 성공 cohort는 parent 점수, 실패 cohort는 metadata 점수를 사용한다. 권한·organization·source authorization 실패에는 fallback하지 않는다.
- 기존 관련도 외곽 조합인 source tier, availability 및 freshness 정책은 유지한다. Collection 점수, 동일 KB 중복 제거, 안정 정렬, 표시 상한은 ADR-0061을 따른다.
- Retrieval port가 application에 반환할 수 있는 값은 권한 확인된 KB ID, bounded score 및 성공·degraded 상태뿐이다. Parent 원문, document/chunk ID, embedding vector, provider request/response payload는 RecommendationService, Planner, Client, audit, trace 또는 log 경계로 전달하지 않는다.
- 이 조회는 일반 RAG answer retrieval이 아니므로 citation trace나 `rag.retrieve` payload를 만들지 않는다. 운영 관측은 민감한 후보 identity·내용·score·숨은 후보 개수 없이 cohort 수, timeout/failure 분류와 latency 같은 bounded 집계만 허용한다.
- 추천 score와 검색 결과는 graph, Agent Builder session, DB 또는 durable cache에 저장하지 않는다. 기존 opaque handle, hierarchy 선택 UI, GraphMutation, CAS save, acknowledgement 및 stale resolution 의미는 변경하지 않는다.
- Embedding credential의 사용 주체는 현재 Agent Builder 사용자다. Active organization과 `use` 권한이 확인된 credential만 provider 호출에 사용할 수 있다. Provider 비용은 해당 credential의 provider account에 귀속한다. MBA-342는 새 `llm_usage_logs`, 비용 API 또는 대시보드를 만들지 않고 내부 비용 과소계상 가능성을 문서화한다.
- 이 예외는 feature 계약과 보호 리소스 검증표가 동기화되고 PostgreSQL/provider 및 정량 release gate가 통과되기 전에는 Active로 전환하거나 merge하지 않는다.

## Alternatives Considered

### Metadata ranking 유지

권위 계약과 provider 비용은 단순하지만 metadata가 빈약한 KB의 실제 문서 관련도를 반영하지 못한다.

### Workflow runtime RetrievalService 재사용

검색 코드를 적게 추가할 수 있지만 citation, raw evidence 및 runtime trace 책임이 Agent Builder application 경계로 유입된다. 결합도가 높고 score-only 비노출 계약을 보장하기 어려워 채택하지 않는다.

### Hybrid keyword/vector 검색

Exact term에는 유리할 수 있지만 query 수와 점수 보정 변수가 늘어나며 MBA-342의 parent embedding 재사용 효과를 독립적으로 검증하기 어렵다. 첫 구현에서는 제외한다.

### Parent와 metadata 점수의 상시 혼합 또는 최댓값

Metadata 이름이 강한 무관 KB가 성공한 semantic 결과를 덮어쓸 수 있다. Semantic 검색 가능 여부와 관련도 낮음을 구분하기 위해 `parent_first_v1` degraded fallback을 채택한다.

## Consequences

- Metadata가 빈약해도 관련 parent 내용이 있는 KB를 추천할 수 있다.
- Permission 검증과 외부 I/O 순서가 명시되고 cohort 단위 호출 상한으로 비용과 latency가 제한된다.
- Flat 또는 provider 장애 후보는 기존 metadata 경로로 계속 추천할 수 있지만 degraded 상태를 안전하게 구분해야 한다.
- Recommendation adapter는 embedding provider와 PostgreSQL parent projection을 조합하되 application port 밖의 raw 검색 자료를 폐기해야 한다.
- 새 DB column, migration, embedding backfill, 사용자 설정 UI, runtime RAG 변경은 필요하지 않다.
- 최소 30개 deterministic case에서 metadata baseline과 비교한다. Recall@5와 MRR은 baseline 이상, Precision@5 저하는 2 percentage point 이내, metadata-poor subset Recall@5는 최소 10 percentage point 개선되어야 한다. Permission 및 content/identity leakage는 0이어야 한다.
- Semantic path의 latency gate는 p50 3초 이하, p95 8초 이하, hard deadline/fallback 10초 이하다. 5,000개 후보에서도 embedding/parent SQL은 각각 실제 cohort 수 이하이자 최대 4회이며 candidate-level N+1은 0이어야 한다.
- 실제 PostgreSQL 또는 provider 환경이 없으면 해당 검증은 성공으로 간주하지 않고 `Verification Blocked`로 기록한다. Gate 실패 상태에서는 feature 문서를 Active로 전이하거나 변경을 merge하지 않는다.
