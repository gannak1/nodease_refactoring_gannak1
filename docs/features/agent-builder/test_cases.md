# Agent Builder Test Cases

Status: Draft

## Unit Tests

- `StructuredRequestBuilder`는 자연어 요청을 `request_type`, `intent_summary`, `planned_steps`, `knowledge_requirements`, `pending_resolution`, `missing_information`으로 분리한다.
- Knowledge Base처럼 resolver가 해결할 수 있는 값은 즉시 `missing_information`으로 올리지 않고 `pending_resolution`으로 둔다.
- `blocking` 최종값은 LLM hint가 아니라 product policy와 slot type 규칙으로 확정된다.
- `TargetResolver`는 자연어 target이 selected node보다 우선한다.
- 동일 type node가 여러 개이고 selected node가 후보가 아니면 clarification을 반환한다.
- `WorkflowDraftValidator`는 unsupported node type, missing config, schema mismatch, permission shortage를 실패로 반환한다.

## API Tests

- (FR-001) 생성 요청 성공 시 노드 그래프를 반환한다. 대표 프롬프트: "고객 문의 이메일을 받아서 자동으로 분류하고 답변해줘" → Webhook/LLM/Condition/Mail 계열 노드 포함.
- (FR-003) 사용 가능한 credential이 없는 상태에서 생성 요청 → 부족한 credential/모델을 명시한 사전 안내 응답.
- 유효하지 않은 `X-Organization-Id` header → 실행 전 검증 오류로 거부.
- 해석 불가능한 프롬프트(예: 빈 문자열, 자동화와 무관한 요청) → 빈 workflow를 만들지 않고 명시적 실패 응답.
- 사내 지식 검색 workflow 생성 요청에서 Builder는 safe skill metadata와 safe collection/KB display metadata만 사용하고 raw skill body, hidden source reference, raw source title/path/url을 prompt나 응답에 포함하지 않는다.
- LLM node RAG 옵션 후보 resolver는 intended execution subject/audience 기준 `available`, `warning`, `unavailable`, `unknown` runtime availability를 반환하고, hidden KB id/name, exact denied count, hidden source distribution을 반환하지 않는다.
- Workflow Builder의 RAG 옵션 추천은 Knowledge RAG Recommendation Adapter를 통해서만 수행하며, Agent Builder가 Knowledge permission row, source ACL row, hidden KB 목록을 직접 읽지 않는다.
- Recommendation 결과는 초기 구현에서 KB 단위로 materialize되고, Collection은 safe `source_collection_summary`로만 표시된다. Builder draft에는 현재 LLM node schema의 `knowledgeBases` 중심으로 저장된다.
- Recommendation이 없으면 Builder는 사용자 확인 필요 상태를 표시하고, 별도 정책 gate 없이 자동으로 RAG 없는 LLM node를 생성하지 않는다.
- 후보가 source ACL stale/unmapped/ambiguous/unverified/revoked 또는 scope 밖 resource 때문에 제외된 경우 Builder 응답은 safe reason class와 required action만 표시하고 세부 source ACL state나 raw source path/title/url을 노출하지 않는다.
- `X-Organization-Id`가 없으면 Agent Builder request가 거부된다.
- Request body에 `organization_id`가 있어도 권한/scope 판단에는 사용되지 않는다.
- 기존 workflow 수정 요청은 workflow read/write 권한이 없으면 `WORKFLOW_PERMISSION_REQUIRED`를 반환한다.
- 새 workflow draft 요청은 app 또는 workflow 생성 scope 권한이 없으면 `APP_CREATE_PERMISSION_REQUIRED`를 반환한다.
- Pending request 중복 submit은 거부되거나 기존 pending state를 반환한다.
- Cancel된 request의 late result는 draft preview를 만들지 않는다.

## Knowledge Recommendation Tests

- Agent Builder는 raw user input 전체가 아니라 `StructuredRequest`의 safe summary, `knowledge_requirement`, `pending_resolution_ref`로 adapter request를 만든다.
- Adapter request에는 raw source ACL, raw source id/path/url/title, raw document/chunk content, hidden/denied list, exact hidden/denied count가 포함되지 않는다.
- Adapter는 `KnowledgeCandidateResolver`가 반환한 safe candidate set 안에서만 추천한다.
- 권한 없는 KB는 recommendation, preview, prompt, trace에 나타나지 않는다.
- 후보 1개 high confidence이면 KB pending resolution이 resolved 처리된다.
- 후보 여러 개 또는 점수 근접이면 clarification option이 표시된다.
- 후보 0개이면 validation failure 또는 clarification으로 연결된다.
- Adapter unavailable이고 safe KB list가 있으면 fallback clarification을 반환한다.
- Adapter unavailable이고 safe KB list도 없으면 validation failure를 반환한다.
- 추천 결과는 LLM node의 `knowledgeBases`로 materialize 가능해야 한다.
- Collection은 preview 설명용 safe summary로만 표시되고 workflow runtime field로 저장되지 않는다.
- MVP에서 RAG retrieval signal과 LLM reranker는 비활성이다.

## Draft Preview Mode And Apply Save Tests

- Draft 생성 시 Knowledge Base retrieval, Slack 전송, workflow 실행이 발생하지 않는다.
- Draft preview는 생성/변경될 step, target 위치, missing info, validation result, warning을 표시한다.
- Validation 실패 draft에는 `도안 보기` 또는 `적용 및 저장` action이 표시되지 않는다.
- Chatbot panel의 `도안 보기`를 선택하면 Preview Mode가 열리고, actual editor graph는 변경되지 않는다.
- Preview Mode는 agent draft graph를 `previewGraph`로 렌더링하고 actual editor graph와 분리한다.
- Preview Mode에서 node를 클릭하면 Node Detail Panel에 node type, 주요 설정, KB/Slack binding, credential 참조 상태, input/output mapping, validation 상태가 읽기 전용으로 표시된다.
- Preview Mode의 Node Detail Panel에서는 node 설정, credential, KB, edge, delete action을 수정할 수 없다.
- `취소`를 선택하면 preview graph가 폐기되고 actual editor graph는 Preview Mode 진입 전 상태를 유지한다.
- `적용 및 저장` 이후 backend는 draft metadata 조회, 권한 재확인, stale check, validation 재확인을 수행한다.
- Stale check는 base graph hash와 latest graph hash를 비교하고, workflow version 또는 updated_at도 함께 비교한다.
- Base graph hash가 같아도 workflow version 또는 updated_at이 달라지면 stale draft로 저장되지 않는다.
- Workflow version 또는 updated_at이 같아도 graph hash가 달라지면 stale draft로 저장되지 않는다.
- Graph hash는 node id, node type, node data/config, edge source/target/handle 같은 workflow 의미 값만 반영하고 viewport, selection, panel state, preview state, timestamp, UI-only metadata는 반영하지 않는다.
- Stale draft는 저장되지 않고 user-safe block reason을 반환하며 Preview Mode를 유지한다.
- 기존 workflow 수정 draft는 workflow read/write 권한이 없으면 저장되지 않는다.
- 새 workflow draft는 app 또는 workflow 생성 scope 권한이 없으면 저장되지 않는다.
- 전체 교체 draft는 기존 workflow read/write 권한과 교체 validation을 모두 만족해야 저장된다.
- 저장되지 않은 editor 변경이 있으면 MVP에서는 draft 생성, Preview Mode 진입, 또는 `적용 및 저장`이 차단되고 저장/폐기 안내가 표시된다.
- 후속 확장 전까지 client graph snapshot만으로 unsaved editor graph를 draft base로 자동 포함하지 않는다.
- `DRAFT_METADATA_NOT_FOUND`, `DRAFT_METADATA_EXPIRED`, `WORKFLOW_PERMISSION_REQUIRED`, `APP_CREATE_PERMISSION_REQUIRED`, `DRAFT_STALE`, `DRAFT_VALIDATION_FAILED`, `SAVE_FAILED`, `ORGANIZATION_CONTEXT_MISMATCH`, `UNSAVED_EDITOR_CHANGES`는 각각 한국어 안내와 함께 저장을 차단하거나 실패 상태를 표시한다.
- 저장 성공 시 Preview Mode가 종료되고 editor는 저장된 최신 workflow graph를 표시한다.
- 저장 차단 또는 실패 시 Preview Mode가 유지되고 actual editor graph는 변경되지 않는다.
- 저장 성공 후에도 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경은 발생하지 않는다.
- Draft preview 생성, Preview Mode 진입, 적용 및 저장 요청, 저장 차단, 저장 성공, 저장 실패, 취소 audit event가 구분되어 기록된다.
- Audit event에는 safe metadata만 포함하고 credential 원문, raw KB content, raw source path/url/title, hidden KB/resource detail, raw provider response, secret-like user input 원문은 포함하지 않는다.

## E2E Demo

1. Workflow Editor를 연다.
2. 우측 하단 Agent Builder launcher를 클릭한다.
3. "사내 휴가 정책을 바탕으로 직원 질문에 답하는 workflow를 만들어줘"라고 입력한다.
4. Agent Builder가 `[입력] -> [Knowledge Base-backed LLM] -> [응답]` draft preview를 생성한다.
5. KB 후보가 하나이면 safe recommendation 근거와 함께 draft에 표시된다.
6. KB 후보가 여러 개이면 draft를 확정하지 않고 선택 질문을 표시한다.
7. Validation을 통과한 draft에만 `도안 보기` action이 표시된다.
8. 사용자가 `도안 보기`를 선택하면 Workflow Editor가 Preview Mode로 전환된다.
9. Preview Mode에서 draft graph가 읽기 전용으로 표시되고, 사용자는 node를 클릭해 Node Detail Panel에서 내부 설정을 확인한다.
10. 사용자가 `적용 및 저장`을 선택하면 backend가 draft metadata, 권한, stale, validation을 재확인한다.
11. 재확인을 통과하면 workflow graph가 저장되고 audit-safe apply/save success event가 기록된다.
12. Preview Mode가 종료되고 editor는 저장된 최신 workflow graph를 표시한다.
13. 이 시점에도 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경은 발생하지 않는다.

## Security And Privacy Tests

- Secret-like input은 prompt, response, trace, audit, preview에 원문으로 남지 않는다.
- Raw provider response는 Agent Builder 응답에 포함되지 않는다.
- Raw KB document/chunk content는 draft generation 응답에 포함되지 않는다.
- Hidden KB 이름, raw source path/url/title, exact denied count는 사용자에게 표시되지 않는다.
- Scope 밖 workflow/app은 존재 추론을 피하는 응답으로 처리된다.
