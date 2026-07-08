# Agent Builder Test Cases

Status: Draft

## Unit Tests

- `StructuredRequestBuilder`는 자연어 요청을 `request_type`, `intent_summary`, `planned_steps`, `knowledge_requirements`, `pending_resolution`, `missing_information`으로 분리한다.
- `StructuredRequestBuilder`는 KB 후보 목록이나 KB safe metadata 목록 없이도 KB가 필요한 요청에서 `knowledge_requirements`와 `pending_resolution(slot_type=knowledge_base)`을 생성한다.
- Knowledge Base처럼 resolver가 해결할 수 있는 값은 즉시 `missing_information`으로 올리지 않고 `pending_resolution`으로 둔다.
- `blocking` 최종값은 LLM hint가 아니라 product policy와 slot type 규칙으로 확정된다.
- `TargetResolver`는 자연어 target이 selected node보다 우선한다.
- `TargetResolver`는 사용자가 edge를 선택하고 자연어가 "여기 사이에", "이 연결에"처럼 edge 문맥을 지칭할 때 `selected_edge_id`를 위치 hint로 사용한다.
- `selected_edge_id`가 확정된 기존 workflow 수정 draft는 선택된 edge의 source와 target 사이에 생성 step을 삽입하는 preview graph를 만들고, 저장 시 기존 선택 edge를 제거한 뒤 생성 step edge를 연결한다.
- 동일 type node가 여러 개이고 selected node가 후보가 아니면 clarification을 반환한다.
- `WorkflowDraftValidator`는 unsupported node type, missing config, schema mismatch, permission shortage를 실패로 반환한다.

## API Tests

- (FR-001) 생성 요청 성공 시 MVP 허용 capability 안에서 노드 그래프를 반환한다. 대표 프롬프트: "사내 휴가 정책을 바탕으로 직원 질문에 답하고 결과를 Slack으로 보내줘" → Start/Input, Knowledge Base-backed LLM, Slack send, Answer 계열 노드 포함. 이 케이스는 capability coverage test이며, PRD demo happy path는 Slack을 제외한 Knowledge Base-backed LLM flow로 검증한다. Slack channel 또는 KB 후보가 모호하면 draft를 확정하지 않고 clarification을 반환한다.
- (FR-003) 사용 가능한 credential이 없는 상태에서 생성 요청 → 부족한 credential/모델을 명시한 사전 안내 응답.
- 유효하지 않은 `X-Organization-Id` header → 실행 전 검증 오류로 거부.
- 해석 불가능한 프롬프트(예: 빈 문자열, 자동화와 무관한 요청) → 빈 workflow나 `입력 -> LLM -> 출력` 기본 draft를 만들지 않고 `unsupported` 또는 동등한 명시적 실패 응답과 한국어 사용 힌트를 반환한다.
- "입력 - 출력 노드를 만들어줘"처럼 LLM, Knowledge Base, Slack 요구가 없는 단순 입출력 요청 → 승인된 draft generation model route가 없어도 Start/Input과 Answer/Output 계열 draft를 생성할 수 있고 LLM node를 기본 삽입하지 않는다.
- 사내 지식 검색 workflow 생성 요청에서 MVP Builder는 Knowledge Skill body/checklist를 prompt context로 직접 로드하지 않고 safe collection/KB display metadata와 ADR-0017 기본 RAG option 후보만 사용한다. 후속 기능에서 Skill을 사용하더라도 raw skill body, hidden source reference, raw source title/path/url은 prompt나 응답에 포함하지 않는다.
- LLM node RAG 옵션 후보 resolver는 intended execution subject/audience 기준 `available`, `warning`, `unavailable`, `unknown` runtime availability를 반환하고, hidden KB id/name, exact denied count, hidden source distribution을 반환하지 않는다.
- Agent Builder의 RAG 옵션 추천은 Knowledge RAG Recommendation Adapter를 통해서만 수행하며, Agent Builder가 Knowledge permission row, source ACL row, hidden KB 목록을 직접 읽지 않는다.
- Recommendation 결과는 초기 구현에서 KB 단위로 materialize되고, Collection은 safe `source_collection_summary`로만 표시된다. Builder draft에는 현재 LLM node schema의 `knowledgeBases` 중심으로 저장된다.
- Recommendation 후보가 0개이면 Builder는 권한 확인된 KB 후보가 없다는 경고를 표시하고, Knowledge Base binding이 비어 있는 LLM node draft를 생성할 수 있다.
- 후보가 source ACL stale/unmapped/ambiguous/unverified/revoked 또는 scope 밖 resource 때문에 제외된 경우 Builder 응답은 safe reason class와 required action만 표시하고 세부 source ACL state나 raw source path/title/url을 노출하지 않는다.
- `X-Organization-Id`가 없으면 Agent Builder request가 거부된다.
- Request body에 `organization_id`가 있어도 권한/scope 판단에는 사용되지 않는다.
- Request body의 `selected_edge_id`는 target resolution hint로만 쓰이고 권한/scope 판단에는 사용되지 않는다.
- 기존 workflow 편집 화면에서 Agent Builder를 열었더라도 자연어에 "이 연결 사이에", "선택한 노드 뒤에", "현재 workflow에"처럼 기존 graph 안의 삽입 또는 수정 대상이 없으면 새 workflow draft 생성을 기본값으로 본다.
- Message request에 `client_graph_snapshot` 또는 동등한 raw graph payload가 포함되면 서버는 이를 draft base나 권한/scope 판단에 사용하지 않고 거부한다.
- Apply/save request에 raw graph payload와 동등한 `graph`, `nodes`, `edges`, `preview_graph`, `workflow_graph` 같은 field가 포함되면 서버는 입력 값을 echo하지 않고 safe validation error로 거부한다.
- Agent Builder session id는 server-issued 값이어야 하며, client-generated session id는 권한/scope/audit 판단에 사용되지 않는다.
- 기존 workflow 수정 요청은 workflow read/write 권한이 없으면 `WORKFLOW_PERMISSION_REQUIRED`를 반환한다.
- 새 workflow draft 요청은 app 또는 workflow 생성 scope 권한이 없으면 `APP_CREATE_PERMISSION_REQUIRED`를 반환한다.
- Pending request 중복 submit은 거부되거나 기존 pending state를 반환한다.
- Cancel된 request의 late result는 draft preview를 만들지 않는다.

## Knowledge Recommendation Tests

- Agent Builder는 raw user input 전체가 아니라 `StructuredRequest`의 safe summary, `knowledge_requirement`, `pending_resolution_ref`, `safe_workflow_context_summary`로 adapter request를 만든다.
- Adapter request에는 raw source ACL, raw source id/path/url/title, raw document/chunk content, hidden/denied list, exact hidden/denied count가 포함되지 않는다.
- Adapter는 `StructuredRequest`의 `knowledge_requirement`와 `pending_resolution_ref`를 Knowledge side의 `KnowledgeCandidateResolver`가 반환한 server-issued reference 또는 같은 backend 내부 service call의 authorized safe candidate set 안에서만 매칭하고 추천한다. HTTP 또는 serialized boundary에서는 full candidate set이 아니라 reference만 사용한다.
- Recommendation `candidate_id`는 raw source id/path/url/title이 아니라 server-issued safe handle이어야 한다.
- Recommendation item은 score, confidence, reason category, threshold result를 포함해야 한다.
- Recommendation threshold 값은 구현 설정값으로 관리되고, 테스트 fixture에서는 고정되어 `high_confidence`, `close_score`, `below_threshold` 분기가 재현 가능해야 한다.
- LLM node Knowledge Base picker와 Agent Builder KB recommendation은 같은 후보 판정 기준을 사용한다. Active ready document version이 있거나 legacy unversioned retrieval-visible chunk가 있는 권한 확인 KB는 후보가 될 수 있다.
- 권한 확인된 KB에 문서 row나 chunk artifact가 있어도 아직 indexing/not-ready 상태라 retrieval-visible artifact가 없으면 selectable ready KB로 표시하지 않는다. 대신 "인덱싱 중/사용 준비 전" safe warning 또는 disabled option을 표시하고, 빈 목록이나 "권한 확인된 KB 후보 없음"으로만 조용히 닫지 않는다.
- Auto mode에서 route-allowed collection 후보가 비어 있고 client가 collection scope를 명시하지 않은 경우, 같은 active organization의 직접 권한 확인된 retrieval-visible KB를 safe candidate set fallback으로 평가할 수 있다. 명시적으로 빈 collection scope를 보낸 경우에는 direct fallback을 적용하지 않는다.
- Draft metadata에는 safe handle과 structured request safe context만 저장되고 runtime KB id mapping은 저장되지 않는다.
- Apply/save 직전에 backend가 candidate handle을 권한 확인된 runtime Knowledge Base reference로 다시 해석한다.
- 권한 없는 KB는 recommendation, preview, prompt, trace에 나타나지 않는다.
- 후보 1개 high confidence이면 KB pending resolution이 resolved 처리된다.
- 후보 1개가 `close_score` 이상이면 자동 resolved 처리될 수 있고, `below_threshold` 단일 후보는 clarification으로 남는다.
- 후보 여러 개 또는 점수 근접이면 질문만 표시하지 않고 safe label, candidate safe handle, confidence, score, reason category를 포함한 clarification option이 표시된다.
- 사용자가 clarification option 중 하나를 선택하면 client는 safe candidate handle과 선택적 resolution/requirement reference만 제출하고, backend는 원 clarification option과 같은 session/context인지 검증한 뒤 pending KB resolution을 resolved 처리한다.
- 원 clarification context와 맞지 않는 candidate handle, 만료된 option, 또는 apply/save 직전 materialization 실패는 draft 확정이나 저장으로 이어지지 않는다.
- 후보 0개이면 validation failure로 닫지 않고, 권한 확인된 KB 후보가 없다는 경고와 함께 Knowledge Base binding이 비어 있는 LLM node draft를 생성한다.
- Adapter unavailable이고 권한 확인된 safe 후보 선택지가 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options` 기반 fallback clarification을 반환한다.
- Adapter unavailable이고 safe 후보 선택지도 없으면 validation failure를 반환한다.
- 추천 결과는 LLM node의 `knowledgeBases`로 materialize 가능해야 한다.
- Collection은 preview 설명용 safe summary로만 표시되고 workflow runtime field로 저장되지 않는다.
- MVP에서 RAG retrieval signal과 LLM reranker는 비활성이다.

- KB 후보 clarification에는 `Knowledge Base 없이 생성` safe option이 표시되어야 한다. 사용자가 이 option을 선택하면 client는 `selected_knowledge_candidate.candidate_id=__agent_builder_no_kb__`와 선택적 resolution/requirement reference만 다시 보내고, backend는 같은 prior clarification context인지 검증한 뒤 `knowledgeBases=[]`인 LLM node draft를 생성해야 한다.

## Runtime RAG Boundary Tests

- 이 테스트는 draft 생성, preview, apply/save가 Knowledge Base retrieval을 수행한다는 뜻이 아니라, Agent Builder가 생성한 KB-backed LLM node가 별도 workflow 실행 시점에 ADR-0018 runtime RAG 경계를 지키는지 검증한다.
- Interactive authenticated workflow execution에서는 run context의 `execution_subject=current_user`를 Knowledge service에 전달하고, runtime KB access는 해당 subject 기준 Knowledge permission path로 평가되어야 한다.
- `execution_subject`가 있는 실행은 workflow owner, deployment owner, app creator, builder 권한으로 private KB 접근을 대체하지 않는다.
- `execution_subject`가 없는 public app, webhook, schedule, API secret 실행은 workflow owner, deployment owner, app creator, builder, `user_id` 권한으로 private KB를 조회하지 않는다.
- `execution_subject`가 없는 실행은 anonymous public-only retrieval로 낮추고, `safe_metadata["visibility"] == "public"`인 active Knowledge Collection에 연결된 active KB만 검색 대상으로 삼는다. Source-managed KB는 valid source/connector public exposure approval도 통과해야 한다.
- visibility가 없거나 public이 아닌 collection, archived/deleted collection, archived/deleted KB는 anonymous runtime에서 private 또는 unavailable로 처리한다.
- anonymous public-only filtering 이후 후보 KB 또는 evidence가 없으면 safe no-result를 반환한다. 단, node의 `ragFailurePolicy`가 node failure를 요구하면 실패로 처리한다.
- Agent Builder preview, prompt, trace, audit, test fixture는 hidden KB id/name, exact denied count, raw source path/url/title, raw document/chunk content를 노출하지 않는다.

## Draft Preview Mode And Apply Save Tests

- Draft 생성 시 workflow graph 저장, Knowledge Base retrieval, Slack 전송, workflow 실행, credential 사용/변경, 외부 시스템 변경이 발생하지 않는다.
- Draft preview는 생성/변경될 step, target 위치, missing info, validation result, warning을 표시한다.
- Validation 실패 draft에는 `도안 생성 미리보기` 또는 `적용 및 저장` action이 표시되지 않는다.
- Guardrail node 자동 생성 요청은 MBA-145 MVP에서 unsupported 또는 후속 기능 안내로 닫히며, Start/LLM/Answer 같은 다른 draft로 silent success 처리되지 않는다.
- Chatbot panel의 `도안 생성 미리보기`를 선택하면 Preview Mode가 열리고, actual editor graph는 변경되지 않는다.
- `도안 생성 미리보기`를 선택하면 `DraftPreviewOpened` 또는 동등한 preview-opened audit event가 safe metadata로 기록된다.
- `DraftPreviewOpened` audit 기록에 실패하면 Preview Mode에 진입하지 않고 재시도 안내를 표시한다.
- draft 상태, 만료, validation, 또는 scope 재확인 실패로 preview-opened가 차단되면 `DraftPreviewBlocked` 또는 동등한 audit-safe event를 기록하고 Preview Mode에 진입하지 않는다.
- Preview Mode는 agent draft graph를 `previewGraph`로 렌더링하고 actual editor graph와 분리한다.
- Preview Mode 중 URL `?node=` 또는 browser popstate가 들어와도 actual workflow node editor를 열지 않고, preview node detail 경계만 유지한다.
- Preview Mode action이 Agent Builder panel 안에 있으면 panel close를 차단해 `적용 및 저장`과 `취소` 경로가 유지된다.
- workflow/app route scope가 바뀌면 이전 scope의 Agent Builder session, pending state, preview graph가 새 scope로 이어지지 않는다.
- Refresh 후 session 복구는 redaction된 사용자 message summary와 assistant response를 함께 복구하고, secret-like user input 원문을 다시 표시하지 않는다.
- Preview Mode에서 node를 클릭하면 Node Detail Panel에 node type, 주요 설정, KB/Slack binding, credential 참조 상태, input/output mapping, validation 상태가 읽기 전용으로 표시된다.
- Preview Mode의 Node Detail Panel은 canvas 왼쪽 영역에 표시되어 우측 또는 우측 하단 Agent Builder chat panel, `적용 및 저장`, `취소` action을 가리지 않는다.
- Preview Mode의 Answer/Output 계열 node card는 output variable 목록이나 value selector mapping을 카드 본문에 직접 표시하지 않는다. 해당 정보는 Node Detail Panel 또는 기존 node 설정 패널에서 확인되며, canvas card 내용이 node border 밖으로 넘치지 않는다.
- Preview Mode의 Node Detail Panel에서는 node 설정, credential, KB, edge, delete action을 수정할 수 없다.
- `취소`를 선택하면 server-side apply/save audit에 canceled outcome이 기록되고 Preview Mode만 종료되며, actual editor graph는 Preview Mode 진입 전 상태를 유지한다. 이는 draft metadata terminal 폐기를 의미하지 않으며, 직전 draft가 만료되거나 새 draft로 대체되지 않았다면 사용자는 같은 draft를 다시 `도안 생성 미리보기`로 열 수 있다.
- `적용 및 저장` 이후 backend는 draft metadata 조회, 권한 재확인, stale check, validation 재확인을 수행한다.
- Stale check는 base graph hash와 latest graph hash를 비교하고, workflow version 또는 updated_at도 함께 비교한다.
- Base graph hash가 같아도 workflow version 또는 updated_at이 달라지면 stale draft로 저장되지 않는다.
- Workflow version 또는 updated_at이 같아도 graph hash가 달라지면 stale draft로 저장되지 않는다.
- Graph hash는 node id, node type, node data/config, edge source/target/handle 같은 workflow 의미 값만 반영하고 viewport, selection, panel state, preview state, timestamp, UI-only metadata, note/memo node와 해당 note/memo node에만 연결된 non-runtime edge는 반영하지 않는다.
- `apply_and_save` request에는 사용자가 확인한 `client_preview_graph_hash`가 필요하며, 기존 workflow 수정 draft에는 `client_latest_graph_hash`가 필요하다. Hash 계산이 불가능하면 raw graph fallback을 보내지 않고 apply/save를 차단한다.
- Stale draft는 저장되지 않고 user-safe block reason을 반환하며 Preview Mode를 유지한다.
- 기존 workflow 수정 draft는 workflow read/write 권한이 없으면 저장되지 않는다.
- 새 workflow draft는 app 또는 workflow 생성 scope 권한이 없으면 저장되지 않는다.
- 전체 교체 draft는 기존 workflow read/write 권한과 교체 validation을 모두 만족해야 저장된다.
- 저장되지 않은 editor 변경이 있으면 MVP에서는 draft 생성, Preview Mode 진입, 또는 `적용 및 저장`이 차단되고 저장/폐기 안내가 표시된다.
- 후속 확장 전까지 client graph snapshot만으로 unsaved editor graph를 draft base로 자동 포함하지 않는다.
- `DRAFT_METADATA_NOT_FOUND`, `DRAFT_METADATA_EXPIRED`, `WORKFLOW_PERMISSION_REQUIRED`, `APP_CREATE_PERMISSION_REQUIRED`, `DRAFT_STALE`, `DRAFT_VALIDATION_FAILED`, `ORGANIZATION_CONTEXT_MISMATCH`, `UNSAVED_EDITOR_CHANGES`는 `outcome=blocked`와 `block_reason`으로 한국어 차단 안내를 표시한다.
- `SAVE_FAILED`는 `outcome=failed`와 `failure_reason`으로 한국어 실패 안내를 표시한다.
- `outcome=saved`는 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 응답은 허용되지 않는다.
- workflow graph 저장 시도 후 apply/save audit 기록이 실패하면 `SAVE_FAILED` 또는 동등한 safe failure로 처리되고 Preview Mode가 유지되며 actual editor graph는 변경되지 않는다.
- `적용 및 저장`이 저장으로 이어지면 저장 전에 기존 Workflow Editor 레이아웃 최적화 UI 버튼과 동등한 자동 레이아웃 로직이 적용된다.
- 저장된 workflow graph의 node position은 자동 레이아웃 최적화 결과와 일치해야 하며, 저장 성공 후 editor가 다시 조회하거나 reconcile해 표시하는 최신 graph도 같은 position을 사용해야 한다.
- 자동 레이아웃 최적화는 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 발생시키지 않는다.
- 저장 성공 시 Preview Mode가 종료되고 editor는 저장된 최신 workflow graph를 표시한다.
- 저장 성공 후 client는 local `previewGraph`를 actual editor graph로 직접 승격하지 않고, 저장된 workflow id를 기준으로 서버 최신 graph를 다시 조회하거나 동등한 서버 반환 graph로 reconcile해 표시한다.
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
7. Validation을 통과한 draft에만 `도안 생성 미리보기` action이 표시된다.
8. 사용자가 `도안 생성 미리보기`를 선택하면 Workflow Editor가 Preview Mode로 전환된다.
9. Preview Mode에서 draft graph가 읽기 전용으로 표시되고, 사용자는 node를 클릭해 Node Detail Panel에서 내부 설정을 확인한다.
10. 사용자가 `적용 및 저장`을 선택하면 backend가 draft metadata, 권한, stale, validation을 재확인한다.
11. 재확인을 통과하면 저장 전에 자동 레이아웃 최적화가 적용되고, apply/save audit 기록까지 성공하면 최적화된 node position이 포함된 workflow graph가 저장 성공으로 완료되며 audit-safe apply/save success event가 기록된다.
12. Preview Mode가 종료되고 editor는 저장된 최신 workflow graph를 표시한다.
13. 이 시점에도 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경은 발생하지 않는다.

## Security And Privacy Tests

- Secret-like input은 prompt, response, trace, audit, preview에 원문으로 남지 않는다.
- Raw provider response는 Agent Builder 응답에 포함되지 않는다.
- Raw KB document/chunk content는 draft generation 응답에 포함되지 않는다.
- Hidden KB 이름, raw source path/url/title, exact denied count는 사용자에게 표시되지 않는다.
- Scope 밖 workflow/app은 존재 추론을 피하는 응답으로 처리된다.
