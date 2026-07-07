# Agent Builder Requirements

Status: Draft
Related Features: workflow, knowledge, llm-credentials, deployment

## Purpose

Agent Builder는 Workflow Editor 안에서 사용자가 자연어로 workflow draft를 만들거나 기존 workflow 수정 제안을 받을 수 있게 하는 기능이다. 이 기능은 workflow를 즉시 실행하지 않고, 사용자가 검토할 수 있는 draft와 preview, clarification, validation 결과를 제공한다.

## Scope

MVP는 다음을 포함한다.

- Workflow Editor 우측 하단 고정 launcher와 chatbot panel
- 자연어 요청을 `StructuredRequest`로 변환
- 새 workflow draft 생성과 기존 workflow 수정 제안 구분
- Start/Input, LLM, Knowledge Base-backed LLM, Answer, Slack send 같은 MVP 허용 capability 조합 제안
- 기존 workflow context와 selected node를 고려한 target resolution
- Knowledge Base 후보가 필요한 경우 safe candidate set 기반 추천
- draft preview, validation result, Preview Mode 기반 적용 및 저장 gating
- Preview Mode에서 읽기 전용 draft graph와 node 내부 설정 확인
- 사용자가 `적용 및 저장`을 선택한 경우에만 workflow graph 저장

MVP는 다음을 포함하지 않는다.

- workflow runtime 변경
- 승인 없는 workflow 실행
- draft 생성 시점 Knowledge Base retrieval
- Slack/Jira/GitHub/Wiki 실제 외부 action 실행
- credential 자동 생성 또는 credential 원문 사용
- 외부 MCP client/server 구현
- 모든 node type 자동 생성
- Guardrail node 자동 생성. MVP에서는 future allowlist 후보로만 남기고, 지원 capability로 노출하지 않는다.
- LLM-assisted KB reranking

## Users

- Workflow를 생성할 수 있는 조직 사용자
- 기존 workflow에 read/write 권한을 가진 조직 사용자
- 감사/운영 검토자는 workflow 권한을 부여받은 경우에만 해당 권한 범위에서 사용한다.

## Functional Requirements

### AB-FR-001: Chatbot Entry

Workflow Editor에는 평소 우측 하단에 작은 Agent Builder launcher가 표시되어야 한다. 사용자가 launcher를 클릭하면 workflow canvas 위 또는 옆에 chatbot panel이 열린다. Panel은 workflow canvas를 대체하지 않고, draft 생성과 검토를 돕는 보조 UI다.

### AB-FR-002: Request Context

모든 Agent Builder 요청은 인증 사용자와 `X-Organization-Id` 기반 active organization membership 검증으로 확정된 server context를 사용한다. Request body의 `organization_id`는 권한 판단, scope 판단, organization override에 사용하지 않는다.

기존 workflow 수정 요청은 대상 workflow가 active organization scope 안에 있고 사용자가 workflow read/write 권한을 가져야 한다. 새 workflow draft 생성은 대상 app 또는 workflow 생성 scope가 active organization 안에 있고 사용자가 해당 scope에서 workflow 생성 권한을 가져야 한다.

### AB-FR-003: Structured Request Builder

Agent Builder는 사용자 자연어를 바로 workflow graph로 변환하지 않는다. 먼저 `StructuredRequest`를 생성한다.

`StructuredRequest`는 다음 정보를 포함해야 한다.

- 요청 유형: 새 workflow, 기존 workflow 수정, clarification 필요, unsupported, validation failure
- 안전한 intent summary
- planned steps 후보
- required capabilities
- Knowledge Base가 필요한 경우 `knowledge_requirements`
- 후속 resolver가 해결할 수 있는 `pending_resolution`
- 사용자가 직접 답해야 하는 `missing_information`
- unsupported request와 risk flags

LLM은 의미 후보 추출에 사용될 수 있지만, 최종 schema 정규화, unsupported 판정, pending/missing 분리, blocking 여부, safe policy 적용은 deterministic normalization과 product policy를 따라야 한다.

`StructuredRequestBuilder`는 KB 후보 목록이나 KB safe metadata 목록을 입력으로 받지 않고, KB 후보를 선택하지도 않는다. 이 단계는 사용자 요청에서 어떤 지식이 필요한지(`knowledge_requirements`)와 어떤 값이 resolver로 해결되어야 하는지(`pending_resolution`)만 구조화한다.

### AB-FR-004: Pending Resolution

Knowledge Base, workflow target, supported capability처럼 다른 resolver가 해결할 수 있는 값은 즉시 `missing_information`으로 확정하지 않고 `pending_resolution`으로 둔다. Resolver가 해결하면 draft generation에 반영하고, 후보가 여러 개이거나 모호하면 clarification으로 승격한다.

### AB-FR-005: Existing Workflow Target Resolution

기존 workflow 편집 화면에서 Agent Builder를 열었더라도 사용자가 "이 연결 사이에", "선택한 노드 뒤에", "현재 workflow에"처럼 기존 graph 안의 삽입 위치나 수정 대상을 명시하지 않으면 새 workflow draft 생성을 기본값으로 본다. 기존 workflow 수정 요청에서는 자연어 target이 selected node/edge보다 우선한다. 자연어가 특정 node type 또는 role을 지칭하고 후보가 하나이면 그 후보를 기준으로 한다. 후보가 여러 개이면 selected node가 후보 안에 있을 때만 selected node를 기준으로 하고, 그렇지 않으면 clarification을 반환한다.

사용자가 canvas edge를 선택했고 자연어가 `여기 사이에`, `이 연결에`처럼 edge 문맥을 지칭하면 `selected_edge_id`를 target resolution hint로 사용할 수 있다. `selected_edge_id`는 위치 해석 보조 정보일 뿐이며 권한, scope, organization 판단에 사용하지 않는다.

`여기`, `이 노드`, `방금 만든 노드` 같은 문맥 의존 표현은 현재 selected node 또는 대화 맥락으로 특정 가능할 때만 사용한다.

### AB-FR-006: Knowledge Base-backed LLM Step

Knowledge Base가 필요한 요청은 draft 생성 시점에 실제 retrieval을 수행하지 않고, LLM node의 Knowledge Base 설정 또는 Knowledge Base-backed LLM step으로 표현한다.

Agent Builder는 Knowledge Base 권한을 직접 판단하지 않는다. Knowledge 도메인이 제공한 authorized safe candidate set과 safe metadata만 사용한다. Raw document/chunk content, raw source path/url/title, raw source ACL, hidden resource list, exact hidden/denied count, credential 원문은 Agent Builder prompt, response, preview, trace, audit에 포함하지 않는다.

Agent Builder가 draft에 포함한 LLM node가 사내 지식을 사용할 때는 Knowledge feature의 collection routing, KB permission, source ACL helper 결과만 사용한다. Builder와 LLM planner는 raw permission row, raw source ACL, hidden KB 목록을 직접 해석하지 않는다.

Workflow runtime에서 LLM node가 RAG를 호출할 때 run context에 명시적인 execution subject가 있으면 이를 Knowledge service에 전달한다. Execution subject가 없으면 workflow owner 권한으로 fallback하지 않고 anonymous public-only로 낮추며, source-managed KB는 collection public visibility와 별도 source/connector public exposure approval을 모두 통과해야 한다. 모호한 subject는 private retrieval fail-closed로 처리한다.

Agent Builder가 KB/Collection picker 또는 workflow generation proposal을 표시할 때는 builder actor의 권한뿐 아니라 intended execution subject/audience의 runtime availability를 safe warning으로 표시해야 한다. Hidden KB id/name/exact denied count는 표시하지 않는다.

### AB-FR-007: KB Recommendation Adapter

Agent Builder는 `StructuredRequest`의 `knowledge_requirements`와 관련 `pending_resolution`을 기반으로 KB Recommendation Adapter를 호출한다.

KB Recommendation Adapter는 `StructuredRequestBuilder`가 만든 지식 요구와 pending slot, 그리고 Knowledge side의 `KnowledgeCandidateResolver`가 만든 server-issued safe candidate set reference를 매칭한다. Authorized safe candidate set은 client request body나 `StructuredRequestBuilder` 입력에서 오지 않는다. 같은 backend 내부 service call에서는 full authorized safe candidate set 객체를 사용할 수 있지만, HTTP 또는 serialized boundary에서는 server-issued reference만 전달한다.

Adapter는 raw user input 전체가 아니라 다음 안전 요약을 사용해야 한다.

- intent summary
- target planned step
- node purpose summary
- knowledge requirement
- pending resolution reference
- safe workflow context summary
- server-resolved actor, active organization, workflow/app scope

MVP adapter는 keyword/metadata 기반 deterministic ranking만 사용한다. RAG retrieval signal과 LLM-assisted reranking은 후속 확장이다.

Recommendation item은 score, confidence, reason category, threshold result를 포함해야 한다. 이 값은 후보 1개 high confidence 자동 해결, 후보 여러 개 또는 점수 근접 clarification을 일관되게 판정하기 위한 safe metadata이며 raw retrieval score나 provider raw response를 노출하지 않는다.

Agent Builder가 자연어 workflow 생성 중 LLM node RAG 옵션을 제안할 때는 Knowledge RAG Recommendation Adapter를 사용한다. Builder는 Knowledge DB, permission row, source ACL row를 직접 조합하지 않는다.

Recommendation candidate 식별자는 raw source id, raw source path, raw source URL, raw document title이 아니라 server-issued safe handle이어야 한다. Draft preview와 clarification에는 safe metadata만 표시한다. Draft metadata에는 runtime KB id mapping을 저장하지 않고 safe handle과 structured request safe context만 보존한다. Agent Builder가 apply/save로 workflow graph를 저장하기 직전 backend는 candidate handle을 권한 확인된 runtime Knowledge Base reference로 다시 해석해야 하며, 이 재해석은 현재 recommendation top-N ranking 결과에 의존하지 않고 권한 확인된 후보 집합 안에서 safe handle을 직접 materialize해야 한다. Handle이 만료되었거나 권한 확인을 통과하지 못하면 validation failure 또는 재선택 질문으로 닫아야 한다.

초기 recommendation 결과는 KB 단위로 materialize된다. Builder UI는 Collection 맥락을 safe `source_collection_summary`로 설명할 수 있지만, 현재 LLM node draft에는 `knowledgeBases` 중심으로 저장한다.

MVP에서 Agent Builder가 제안하는 LLM node RAG 옵션은 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 기본값과 안전한 후보 설명으로 제한한다. `query_rewrite_mode`, `evidence_sufficiency_policy`, source tier hint의 자동 튜닝이나 품질 최적화는 후속 기능이다. 이 설정은 workflow node 옵션일 뿐이며 권한 범위를 넓히거나 runtime data access를 부여하지 않는다.

Knowledge Skill을 prompt context로 직접 사용하는 기능은 MBA-145 MVP 범위가 아니다. 후속 기능에서 Knowledge Skill을 사용할 경우에도 skill visibility, safe metadata display, freshness/eval gate를 통과한 safe field만 사용할 수 있으며, Skill이 제안한 collection/KB reference는 workflow 실행 시점에 execution subject 권한으로 다시 검증되어야 한다. Raw skill body, hidden source reference, raw source title/path/url, restricted document list, raw prompt/completion/provider response는 LLM context, audit, trace에 넣지 않는다.

### AB-FR-008: KB Recommendation Outcomes

KB recommendation 결과는 다음 중 하나여야 한다.

- 후보 1개 high confidence: 해당 pending KB resolution을 resolved 처리하고 draft 추천값으로 사용
- 후보 여러 개 또는 점수 근접: 사용자에게 KB 선택 clarification을 제공하고, safe label, candidate safe handle, confidence, score, reason category를 포함한 `clarification_options`를 함께 표시
- 후보 0개: 권한 확인된 KB 후보가 없다는 경고를 표시하고, Knowledge Base binding이 비어 있는 LLM node draft를 생성할 수 있음
- adapter unavailable: 권한 확인된 safe 후보 선택지가 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options`로 fallback clarification을 반환하고, safe 후보 선택지도 없으면 validation failure
- optional KB requirement unresolved: warning과 함께 KB 없는 draft 가능

Builder가 adapter unavailable 같은 recommendation 실패를 받으면 기본적으로 사용자 확인 필요 또는 validation failure 상태로 둔다. 다만 adapter가 정상 동작했고 권한 확인된 후보가 0개인 경우는 fail-open 권한 확장이 아니라 preview-only KB binding 미설정 상태로 보며, 한국어 경고와 함께 RAG 없는 LLM node draft를 생성할 수 있다. 이 draft는 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 수행하지 않는다.

KB 선택 clarification을 받은 사용자가 후보를 선택하면 Agent Builder는 safe handle과 선택적 resolution/requirement reference만 서버에 다시 보낸다. Backend는 같은 authenticated user, active organization, workflow/app scope, agent panel session의 원 clarification option 안에 있던 후보인지 검증해야 하며, 통과한 경우에만 해당 pending KB resolution을 resolved 처리한다. 선택이 원 clarification context와 맞지 않거나 만료되었거나 apply/save 직전 runtime KB reference로 다시 해석되지 않으면 draft 확정 또는 저장으로 이어지면 안 된다.

### AB-FR-009: Draft Generation

Draft는 기존 workflow model/schema와 지원 capability allowlist를 따라야 한다. Agent Builder는 임의 node type, edge structure, runtime rule을 만들 수 없다.

새 workflow draft는 시작 가능한 entry step을 포함해야 한다. 기존 workflow 수정 draft는 target resolution 결과와 graph validation을 만족해야 한다.

### AB-FR-010: Validation

Validation은 최소한 다음을 확인해야 한다.

- 지원하지 않는 node type
- 필수 설정 누락
- schema 불일치
- workflow/app scope 권한 부족
- 권한 없는 Knowledge Base, credential, channel 포함
- 승인 없는 외부 호출 가능성
- expired candidate handle
- stale workflow context

### AB-FR-011: Draft Preview Mode And Apply Save

Agent Builder는 validation을 통과한 draft에 대해 사용자가 저장 전 확인할 수 있는 Draft Preview를 제공해야 한다. 이 경계는 [ADR-0019](../../decisions/ADR-0019-agent-builder-preview-apply-save-boundary.md)를 따른다. Chatbot panel은 요약과 `도안 보기` 진입점을 제공하고, 상세 검토는 Workflow Editor의 Preview Mode에서 수행한다.

Preview Mode는 현재 editor graph를 덮어쓰지 않고, agent가 생성한 `previewGraph`를 실제 editor graph와 분리된 읽기 전용 graph로 렌더링해야 한다. 사용자는 preview graph의 node와 edge를 확인하고, node를 선택해 Node Detail Panel에서 node type, 주요 설정, Knowledge Base binding, Slack channel binding, credential 참조 상태, input/output mapping, validation 상태를 확인할 수 있어야 한다.

Preview Mode의 Node Detail Panel은 편집을 허용하지 않는다. 사용자가 draft 내용을 바꾸려면 채팅 후속 요청으로 수정해야 한다. Preview Mode에는 이 graph가 아직 저장되지 않은 도안이라는 안내와 `적용 및 저장`, `취소` action을 항상 접근 가능한 위치에 표시해야 한다. MVP에서는 이 action을 canvas banner/action bar 또는 Preview Mode 동안 닫을 수 없는 Agent Builder panel에 둘 수 있지만, 사용자가 panel을 닫아 적용/취소 경로를 잃게 해서는 안 된다.

`취소`를 선택하면 현재 Preview Mode를 종료하고 기존 editor state로 돌아간다. 이 event는 server-side apply/save audit에 `canceled` outcome으로 기록할 수 있어야 하지만, draft metadata 자체를 terminal 폐기한다는 뜻은 아니다. Validation을 통과한 직전 draft는 만료되거나 새 draft로 대체되기 전까지 다시 `도안 보기`로 열 수 있다. 기존 editor graph는 preview 진입만으로 변경되지 않았어야 하므로 rollback이 필요한 방식으로 구현하지 않는다.

`적용 및 저장`을 선택하면 backend는 원 draft metadata 조회, 요청 유형별 권한 재확인, stale check, validation 재확인을 통과한 경우에만 workflow graph를 저장한다. 기존 workflow 수정 draft는 workflow read/write 권한을 재확인하고, 새 workflow draft는 app 또는 workflow 생성 scope 권한을 재확인한다. 전체 교체 draft는 기존 workflow read/write 권한과 교체 validation을 모두 만족해야 한다.

Stale check는 draft 생성 시점의 `base_graph_hash`와 workflow `version` 또는 `updated_at`을 저장하고, 적용 및 저장 시점의 최신 graph hash와 최신 version/updated_at을 함께 비교한다. `base_graph_hash` 또는 version/updated_at 중 하나라도 달라지면 stale로 간주하고 저장을 차단한다. `base_graph_hash`에는 node id, node type, node data/config, edge source/target/handle처럼 workflow 의미에 영향을 주는 값만 포함하고, viewport, selection, panel state, preview state, timestamp, UI-only metadata, note/memo node와 해당 note/memo node에만 연결된 non-runtime edge는 포함하지 않는다.

`적용 및 저장`은 workflow graph 저장까지 의미하지만 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 의미하지 않는다. 저장 이후 workflow 실행은 기존 execution flow의 별도 사용자 동작으로만 수행된다.

저장 성공 시 Preview Mode를 종료하고 Workflow Editor는 저장된 최신 workflow graph를 표시한다. `outcome=saved`는 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 응답은 허용하지 않는다. 새 workflow draft 생성이 성공하면 새 workflow editor로 이동하거나 현재 editor context를 새 workflow로 전환한다. Agent Builder chatbot은 저장 완료와 별도 실행 필요 상태를 한국어로 안내한다.

저장 성공 후 Workflow Editor는 local `previewGraph`를 actual editor graph로 바로 승격하지 않는다. 저장된 workflow id를 기준으로 서버의 최신 workflow graph를 다시 조회하거나, 서버가 반환한 동등한 최신 저장 graph로 reconcile한 뒤 표시해야 한다. 이 경계는 preview-only graph가 실제 저장 결과와 달라지는 상황을 방지하기 위한 것이다.

저장 차단 또는 저장 시도 실패 시 Preview Mode를 유지하고 `actualEditorGraph`를 변경하지 않는다. 사용자는 차단 사유 또는 실패 사유를 확인한 뒤 재시도, 취소, 또는 채팅 후속 요청으로 draft 수정을 선택할 수 있어야 한다. `blocked` outcome은 draft metadata 없음, draft metadata 만료, workflow read/write 권한 부족, app 또는 workflow 생성 scope 권한 부족, stale draft, validation 실패, active organization mismatch, 저장되지 않은 editor 변경 같은 차단 사유를 `block_reason`으로 표현한다. `failed` outcome은 backend 저장 시도 실패 또는 apply/save audit 기록 실패 같은 실패 사유를 `failure_reason`으로 표현한다.

Preview Mode는 `actualEditorGraph`와 `previewGraph`를 섞지 않아야 한다. 진단을 위해 draft id, request id, apply id, session id, workflow id 또는 새 workflow 생성 scope, preview graph hash, base graph hash, latest graph hash, workflow version 또는 updated_at, draft mode, apply/save outcome, block reason, failure reason, permission recheck outcome, stale state, validation state, saved workflow id, timestamp를 audit-safe metadata로 추적할 수 있어야 한다. Audit metadata에는 credential 원문, raw KB content, raw source path/url/title, hidden KB/resource detail, raw provider response, secret-like user input 원문을 포함하지 않는다.

Apply/save audit event는 draft preview 생성, Preview Mode 진입, 적용 및 저장 요청, 저장 차단, 저장 성공, 저장 실패, 취소를 구분해야 한다. 저장 성공 event는 workflow graph 저장 완료와 audit 기록 성공을 함께 의미하지만 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 의미하지 않는다.

MVP에서는 editor에 저장되지 않은 변경이 있으면 Agent Builder draft 생성, Preview Mode 진입, 또는 `적용 및 저장`을 진행하지 않는다. 사용자는 먼저 기존 editor 변경을 저장하거나 폐기해야 한다. 이는 unsaved graph와 agent draft가 섞여 저장 충돌이나 rollback 문제를 만드는 것을 막기 위한 동시성 보호 정책이다.

MVP message request는 raw client graph snapshot을 받지 않는다. Client는 선택된 node/edge hint만 보낼 수 있고, apply/save 단계에서 `client_preview_graph_hash`와 `client_latest_graph_hash` 같은 semantic graph hash를 사용해 preview 확인 여부와 stale 여부를 검증한다. Hash 계산이 불가능하면 raw graph payload로 fallback하지 않고 apply/save를 차단해야 한다.

후속 확장에서는 현재 unsaved editor graph를 검증 가능한 client graph snapshot으로 서버에 전달하고, 서버가 snapshot hash와 schema를 검증한 뒤 해당 snapshot을 draft base로 삼는 방식을 고려할 수 있다. 이 확장 전까지는 unsaved editor graph를 draft base로 자동 포함하지 않는다.

### AB-FR-012: Conversation Session

Agent Builder chatbot session은 refresh 이후에도 최근 대화와 pending request 상태를 복구할 수 있어야 한다. 최근 대화 복구는 redaction을 거친 사용자 message summary와 assistant response를 함께 포함해야 하며, 사용자 원문 또는 secret-like value를 그대로 저장/표시하지 않는다. Session identifier는 server-issued 값이어야 하며, 인증 사용자, active organization, workflow/app scope, agent panel lifecycle에 묶여야 한다. Client가 임의로 생성한 session id는 권한, scope, audit, stale 판단의 근거로 사용할 수 없다.

Pending request가 있으면 중복 submit을 막고 cancel을 제공한다. Cancel된 request의 late result는 draft preview, Preview Mode 진입, apply/save로 이어질 수 없다.

## Success Criteria

- 사용자가 자연어 요청 후 preview 가능한 workflow draft 또는 clarification을 받을 수 있다.
- KB가 필요한 요청은 draft 생성 시점 retrieval 없이 Knowledge Base-backed LLM step으로 표현된다.
- KB 후보가 권한 확인된 safe metadata 안에서만 추천된다.
- 후보가 모호하면 임의 선택하지 않고 질문한다.
- `적용 및 저장` 전에는 workflow 저장, workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경이 발생하지 않는다.
- Demo happy path에서 draft preview, Preview Mode, 읽기 전용 Node Detail 확인, backend 재검사, workflow graph 저장, apply/save audit 기록 성공, Preview Mode 종료, 저장된 최신 graph 표시를 확인할 수 있다.

## Edge Cases

- 사용자가 권한 없는 workflow/app/KB/channel/credential을 언급하면 draft에 포함하지 않는다.
- scope 밖 resource는 존재 추론을 피하는 응답으로 처리한다.
- KB safe label이 없으면 raw name을 fallback으로 표시하지 않고 generic label을 사용한다.
- KB candidate handle이 만료되면 draft를 확정하지 않는다.
- 여러 KB topic이 필요한 요청은 topic별로 recommendation을 수행한다.
- LLM/model call timeout 또는 실패 시 부분 draft를 확정하지 않는다.
- 사용자 원문에 secret-like 값이 있으면 prompt, trace, audit, preview에 원문을 노출하지 않는다.
- Preview Mode에서 preview graph가 actual editor graph를 변경하면 안 된다.
- Preview Mode 중 node detail이 편집 가능 상태로 열리면 저장 전 검토 경계가 깨진 것으로 본다.
- `적용 및 저장` 시점에 base graph hash 또는 workflow version/updated_at이 최신 값과 다르면 stale draft로 차단한다.
- 저장되지 않은 editor 변경이 있으면 MVP에서는 draft 생성, Preview Mode 진입, apply/save를 차단하고 저장 또는 폐기를 안내한다.
- 저장 실패 또는 차단 시 Preview Mode를 유지하고 actual editor graph는 변경하지 않는다.
