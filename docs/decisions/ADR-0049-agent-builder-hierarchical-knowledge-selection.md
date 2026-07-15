# ADR-0049: Agent Builder Hierarchical Knowledge Selection

Status: Accepted

Related ADR: [ADR-0039](ADR-0039-knowledge-workflow-collection-routing-integration.md)

## Context

Agent Builder의 평면 Knowledge Base 후보 목록은 Collection 자동 라우팅과 특정 KB 직접 고정을 구분하지 못한다. 동일 KB가 여러 Collection에 연결된 경우에도 화면 위치별 상태가 분리되어 중복 선택과 중복 검색 위험이 있다.

## Decision

- 이 결정은 ADR-0039의 "Agent Builder recommendation은 direct KB만 materialize" 및 이를 후속 이슈로 미룬 조항을 대체한다. ADR-0039의 additive graph, save authorization, runtime 재검증, observability 비노출 경계는 그대로 유지한다.

- Agent Builder는 route 권한이 있고 operational 상태인 Collection과, 별도로 `use` 권한 및 operational 상태를 통과한 하위 KB만 계층 응답으로 제공한다.
- Collection route 권한은 하위 KB identity 열람 권한을 포함하지 않는다. 권한 없는 하위 KB의 ID, 이름, 개수는 응답하지 않는다.
- 외부 응답과 제출에는 실제 UUID 대신 서버가 발급한 opaque `collection_handle`, `kb_handle`, `selection_key`만 사용한다.
- 동일 KB는 어느 Collection에 나타나도 같은 `kb_handle`과 `selection_key`를 사용한다.
- Collection 선택은 실행 시 Collection membership을 해석하는 동적 라우팅이고, KB 선택은 graph에 직접 고정하는 참조다.
- GraphMutation은 `knowledgeCollections`와 `knowledgeBases`를 별도로 materialize한다. 선택 후 planner를 다시 호출하지 않는다.
- KB 점수는 관련도 0.70, source tier 0.10, availability 0.10, freshness 0.10으로 요청 시 계산한다.
- Collection 점수는 권한과 operational 검사를 통과한 전체 고유 하위 KB를 기준으로 최고 하위 KB 0.60, 상위 3개 평균 0.30, 안전한 Collection metadata 관련도 0.10으로 계산한다. 화면 표시 상한으로 잘린 KB도 점수에는 반영한다. Collection 크기 가산점과 중복 패널티는 사용하지 않는다.
- 점수는 DB와 graph에 저장하지 않는다. 점수 내림차순 뒤 safe label과 opaque handle로 안정 정렬한다.
- Runtime은 직접 KB와 선택 Collection의 authorized child KB를 ID 합집합으로 해석하고 KB당 한 번만 검색한다. 내부 provenance에는 직접 선택과 기여한 모든 Collection을 보존한다.
- 실행 직전에 Collection route 권한, KB use 권한, lifecycle과 operational 상태를 다시 확인한다.

## Consequences

- 기존 graph의 additive `knowledgeBases`와 `knowledgeCollections`를 사용하므로 DB migration은 필요하지 않다.
- 콘텐츠가 같지만 ID가 다른 KB의 의미 중복 판정은 이 결정의 범위가 아니다.
- 과거 direct-edit 세션의 평면 후보는 읽기 호환 경로로만 유지한다.
