# Agent Builder Requirements

Status: Draft
Related Features: workflow, knowledge, llm-credentials, deployment

## Purpose

Agent Builder는 Workflow Editor 안에서 사용자가 자연어로 workflow draft를 만들거나 기존 workflow 수정 제안을 받을 수 있게 하는 기능이다. 이 기능은 workflow를 즉시 실행하지 않고, 사용자가 검토할 수 있는 draft와 preview, clarification, validation 결과를 제공한다.

## Scope

MVP는 다음을 포함한다.

- Workflow Editor 우측 하단 고정 launcher와 chatbot panel
- Chatbot header의 permission-aware intent planner model selector
- 생성 LLM node의 permission-aware 기본 model 추천
- 자연어 요청을 `StructuredRequest`로 변환
- 새 workflow draft 생성과 기존 workflow 수정 제안 구분
- 공통 Workflow Node Capability Catalog에서 `implemented=true`, `agent_builder_supported=true`로 승인된 node capability 조합 제안
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
- workflow node credential 자동 생성, graph 주입, 원문 노출 또는 runtime 실행. 단, AB-FR-003의 자연어 구조화를 위한 permission-aware 내부 LLM planner 호출과 AB-FR-009의 safe model id 추천은 제외한다.
- 외부 MCP client/server 구현
- catalog에 등록되지 않았거나 `implemented=false`인 node type 자동 생성
- Guardrail node 자동 생성. MVP에서는 future allowlist 후보로만 남기고, 지원 capability로 노출하지 않는다.
- LLM-assisted KB reranking

## Users

- Workflow를 생성할 수 있는 조직 사용자
- 기존 workflow에 read/write 권한을 가진 조직 사용자
- 감사/운영 검토자는 workflow 권한을 부여받은 경우에만 해당 권한 범위에서 사용한다.

## Functional Requirements

### AB-FR-001: Chatbot Entry

Workflow Editor에는 평소 우측 하단에 작은 Agent Builder launcher가 표시되어야 한다. 사용자가 launcher를 클릭하면 workflow canvas 위 또는 옆에 chatbot panel이 열린다. Panel은 workflow canvas를 대체하지 않고, draft 생성과 검토를 돕는 보조 UI다.

Panel header는 [ADR-0025](../../decisions/ADR-0025-agent-builder-intent-model-selection.md)에 따라 Agent Builder 내부 intent planner가 사용할 model을 표시하고 변경할 수 있어야 한다. Provider group은 `openai`, `anthropic`, `google`, `llamaparse` 순서로 표시하며, 사용 가능한 model/credential 조합만 선택할 수 있다. LlamaParse는 chat model을 지원하지 않는 disabled group으로 표시한다.

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
- 기존 workflow 수정 요청인 경우 신규 step과 기존 graph target의 역할을 분리한 `edit_operations`

`edit_operations`는 최소한 `operation`, `placement`, 새로 만들 step을 가리키는
`step_refs`, 기존 graph 안의 대상을 표현하는 `target`을 포함한다. 기존
node를 지칭한 단어는 새로 만들 capability로 다시 추가하지 않는다. 예를 들어
`GitHub 노드 뒤에 LLM 노드를 추가해줘`는 신규 capability `llm`, target node type
`githubNode`, `operation=insert`, `placement=after`로 구조화해야 한다.

운영 message 처리 경로는 permission-aware LLM structured output으로 의미 후보를 추출해야 한다. LLM 호출 전 [ADR-0027](../../decisions/ADR-0027-agent-builder-pre-intent-safe-kb-context.md)에 따라 권한과 retrieval-visible gate를 통과한 KB 후보를 metadata relevance로 정렬하고 상위 20개의 opaque handle, safe label/topics/description, runtime availability, bounded relevance만 safe context로 제공한다. LLM 출력은 `request_type`, `draft_mode`, 순서가 유지된 capability 후보, 지식 필요 여부와 safe topic, 관련 candidate handle, 명시적 integration의 provider/resource/operation, 기존 workflow 수정 시 target/placement 후보까지만 제공한다. LLM이 반환한 node id, edge id, credential, 임의 capability 또는 graph는 신뢰하지 않는다.

명시적인 GitHub Pull Request 요청은 provider=`github`, resource=`pull_request`, operation=`read|comment|create`로 먼저 구분한다. PR 또는 diff 조회는 `github_pr_read`, 기존 PR에 댓글이나 리뷰 결과를 등록하는 요청은 `github_pr_comment`와 일치해야 하며 불일치는 safe semantic repair 대상이다. 새 PR 생성, 열기 또는 `PR을 올려`처럼 PR 자체를 생성하는 요청은 `create`로 인식하지만 현재 실행 capability에는 포함하지 않는다. 사용자가 GitHub API의 HTTP 호출을 명시하지 않은 한 GitHub PR operation을 `http_request`로 대체하지 않으며, `create`는 `unsupported`와 안전한 미지원 사유로 종료한다.

Redacted request가 GitHub와 Pull Request를 명시했는데 LLM 결과가
`http_request`를 새 capability로 반환하고 GitHub Pull Request action을 누락하면
backend는 `GITHUB_INTEGRATION_ACTION_REQUIRED`로 한 번 repair를 요구한다. Backend는
이 검사에서 raw message 동사를 operation으로 변환하거나 action을 직접 추가하지
않는다. Operation은 repair된 LLM structured output에서만 가져온다.

LLM 의미 후보는 서버에서 다시 검증한다. 최종 schema 정규화, capability catalog allowlist, unsupported 판정, pending/missing 분리, blocking 여부, external-action risk, target node/edge 확정과 graph 생성은 deterministic normalization, `TargetResolver`, product policy를 따라야 한다. Schema-valid 출력도 request type, draft mode, workflow context, 신규 capability, target, placement의 semantic invariant를 통과해야 한다. Semantic invariant 위반은 safe validation code만 포함해 최대 한 번 repair하고, 두 번째 결과도 유효하지 않으면 실패로 닫는다. Provider/JSON/schema 실패는 repair 또는 정규식 기반 graph 생성으로 fallback하지 않는다.

구조화 LLM runtime은 인증 사용자와 active organization 범위에서 `use` 권한과 verified model relation을 통과한 credential/model 조합만 사용할 수 있다. Client는 화면에 표시된 조합 중 하나의 `credential_id`, `model_id`를 message request에 포함하고, server는 모든 요청에서 organization, credential validity, `use` 권한, active chat model, provider 일치, verified relation을 다시 검증한다. 선택 상태는 session, draft metadata, workflow graph 또는 별도 model-selection DB column에 저장하지 않는다. Permission/runtime 차단 audit은 safe credential/model ID와 reason을 기록할 수 있다. Credential 원문과 raw provider response는 prompt, API response, draft metadata, trace, audit에 저장하지 않는다. 사용할 runtime이 없으면 `configuration_required`, LLM 호출 또는 schema validation이 실패하면 `failed`를 반환하며 부분 draft를 확정하지 않는다.

Model option은 provider별 최신 세대 우선, 같은 세대에서는 성능 tier가 높은 순으로 정렬한다. 이후 relation priority와 safe display name으로 결정적 순서를 보장한다. Agent Builder는 provider별 고정 저비용 model map으로 선택값을 숨겨 대체하지 않는다.

이 순서는 intent planner header 표시 순서다. Generated workflow LLM node의 기본 model 추천은 AB-FR-009의 별도 비용 친화적 순서를 사용하며, header에서 사용자가 선택한 intent planner model을 workflow node model로 복사하지 않는다.

`StructuredRequestBuilder`는 raw KB 목록이나 runtime KB id mapping을 입력으로 받지 않고 KB를 자동 선택하지도 않는다. Intent extractor가 권한 확인된 bounded safe candidate context에서 반환한 opaque handle은 `knowledge_requirements[].suggested_candidate_handles`에 hint로만 보존한다. 이 단계는 어떤 지식이 필요한지와 어떤 값이 resolver로 해결되어야 하는지를 구조화하며, 최종 후보 순위와 선택은 Recommendation Adapter와 사용자 clarification이 결정한다.

### AB-FR-004: Pending Resolution

Knowledge Base, workflow target, supported capability처럼 다른 resolver가 해결할 수 있는 값은 즉시 `missing_information`으로 확정하지 않고 `pending_resolution`으로 둔다. Resolver가 해결하면 draft generation에 반영하고, 후보가 여러 개이거나 모호하면 clarification으로 승격한다.

### AB-FR-005: Existing Workflow Target Resolution

기존 workflow 편집 화면에서 Agent Builder를 열었더라도 사용자가 "이 연결 사이에", "선택한 노드 뒤에", "현재 workflow에"처럼 기존 graph 안의 삽입 위치나 수정 대상을 명시하지 않으면 새 workflow draft 생성을 기본값으로 본다. 기존 workflow 수정 요청에서는 자연어 target이 selected node/edge보다 우선한다. 자연어가 특정 node type 또는 role을 지칭하고 후보가 하나이면 그 후보를 기준으로 한다. 후보가 여러 개이면 selected node가 후보 안에 있을 때만 selected node를 기준으로 하고, 그렇지 않으면 clarification을 반환한다.

Target resolution이 완료되지 않은 기존 workflow 수정 요청은 새 entry/answer chain이나
분리된 graph component를 생성해서는 안 된다. `insert` 수정 draft는 요청에서 신규로
지정한 step만 생성하고, resolved target의 기존 edge를 재배선해야 한다. 후보가 없거나
여러 개이거나 target node의 삽입 방향에 여러 edge가 있어 위치가 모호하면 draft 생성
대신 clarification으로 닫는다.

분리된 generated component 검증은 `draft_mode=modify_workflow`에서만 기존 graph 연결을
요구한다. 기존 Workflow Editor에서 Agent Builder를 열었더라도
`draft_mode=new_workflow`로 구조화된 요청은 기존 graph에 연결하지 않는 독립 graph가
정상이며, draft metadata의 `workflow_id`, base graph, stale 기준도 새 workflow 생성
scope로 기록해야 한다.

사용자가 canvas edge를 선택했고 LLM structured edit이 `selected_edge` target을 반환하면 `selected_edge_id`를 target resolution hint로 사용할 수 있다. Backend는 해당 edge가 server-loaded workflow graph에 실제로 존재하는지 다시 확인한다. Raw message 정규식은 selected edge 사용 여부를 결정하지 않으며, `selected_edge_id`는 권한, scope, organization 판단에 사용하지 않는다.

`여기`, `이 노드`, `방금 만든 노드` 같은 문맥 의존 표현은 현재 selected node 또는 대화 맥락으로 특정 가능할 때만 사용한다.

### AB-FR-006: Knowledge Base-backed LLM Step

Knowledge Base가 필요한 요청은 draft 생성 시점에 실제 retrieval을 수행하지 않고, LLM node의 Knowledge Base 설정 또는 Knowledge Base-backed LLM step으로 표현한다.

Agent Builder는 Knowledge Base 권한을 직접 판단하지 않는다. Knowledge 도메인이 제공한 authorized safe candidate set과 safe metadata만 사용한다. Raw document/chunk content, raw source path/url/title, raw source ACL, hidden resource list, exact hidden/denied count, credential 원문은 Agent Builder prompt, response, preview, trace, audit에 포함하지 않는다.

Agent Builder가 draft에 포함한 LLM node가 사내 지식을 사용할 때는 Knowledge feature의 collection routing, KB permission, source ACL helper 결과만 사용한다. Builder와 LLM planner는 raw permission row, raw source ACL, hidden KB 목록을 직접 해석하지 않는다.

Workflow runtime에서 LLM node가 RAG를 호출할 때 run context에 명시적인 execution subject가 있으면 이를 Knowledge service에 전달한다. Execution subject가 없으면 workflow owner 권한으로 fallback하지 않고 anonymous public-only로 낮추며, source-managed KB는 collection public visibility와 별도 source/connector public exposure approval을 모두 통과해야 한다. 모호한 subject는 private retrieval fail-closed로 처리한다.

Agent Builder가 KB/Collection picker 또는 workflow generation proposal을 표시할 때는 builder actor의 권한뿐 아니라 intended execution subject/audience의 runtime availability를 safe warning으로 표시해야 한다. Hidden KB id/name/exact denied count는 표시하지 않는다.

### AB-FR-007: KB Recommendation Adapter

Agent Builder는 pre-intent safe candidate context를 사용해 `StructuredRequest`의 `knowledge_requirements`와 관련 `pending_resolution`을 만든 뒤 KB Recommendation Adapter를 호출한다. Pre-intent 후보 조회와 post-intent recommendation은 같은 permission/readiness 경계를 사용하지만, 후자는 현재 전체 후보를 다시 조회해 최종 점수를 계산한다.

KB Recommendation Adapter는 `StructuredRequestBuilder`가 만든 지식 요구와 pending slot, 그리고 Knowledge side의 `KnowledgeCandidateResolver`가 만든 server-issued safe candidate set reference를 매칭한다. Authorized safe candidate set은 client request body에서 오지 않는다. Intent LLM에는 full candidate 객체가 아니라 상위 20개 bounded safe projection만 전달하며, 같은 backend 내부 service call에서만 full authorized safe candidate set 객체를 ranking input으로 사용할 수 있다. HTTP 또는 serialized boundary에서는 server-issued reference만 전달한다.

Adapter는 raw user input 전체가 아니라 다음 안전 요약을 사용해야 한다.

- intent summary
- target planned step
- node purpose summary
- knowledge requirement
- structured safe query topics for KB relevance scoring
- pending resolution reference
- safe workflow context summary
- server-resolved actor, active organization, workflow/app scope

MVP adapter는 keyword/metadata 기반 deterministic ranking만 사용한다. RAG retrieval signal과 LLM-assisted reranking은 후속 확장이다.

Recommendation item은 score, confidence, reason category, threshold result를 포함해야 한다. 이 값은 추천 강도와 사용자 선택 clarification을 일관되게 표시하기 위한 safe metadata이며 raw retrieval score나 provider raw response를 노출하지 않는다.

Agent Builder의 KB 추천과 LLM node Knowledge Base picker는 동일한 retrieval-visible 후보 판정 기준을 사용해야 한다. 사용 가능한 후보는 Knowledge side가 권한 확인을 끝낸 safe candidate set 중 active ready document version이 있거나, 전환기 legacy unversioned retrieval-visible chunk가 있는 KB로 제한한다. 권한 확인된 KB에 문서 row나 chunk artifact가 있지만 아직 indexing/not-ready 상태라 retrieval-visible artifact가 없으면, 이를 조용히 숨기거나 "권한 확인된 KB 후보가 없음"으로만 표현하지 말고 safe warning 또는 disabled option으로 "아직 인덱싱 중/사용 준비 전" 상태를 표시해야 한다.

Auto scope에서 collection link 후보가 없고 client가 collection scope를 명시하지 않은 경우, Adapter는 같은 active organization 안의 직접 권한 확인된 retrieval-visible KB도 safe candidate set으로 평가할 수 있다. 이 fallback은 KB use 권한과 safe metadata 경계를 그대로 적용하며, raw KB name/source/document 정보를 표시하거나 명시적으로 비운 collection scope를 우회하지 않는다.

Agent Builder가 자연어 workflow 생성 중 LLM node RAG 옵션을 제안할 때는 Knowledge RAG Recommendation Adapter를 사용한다. Builder는 Knowledge DB, permission row, source ACL row를 직접 조합하지 않는다.

Recommendation candidate 식별자는 raw source id, raw source path, raw source URL, raw document title이 아니라 server-issued safe handle이어야 한다. Draft preview와 clarification에는 safe metadata만 표시한다. Draft metadata에는 runtime KB id mapping을 저장하지 않고 safe handle과 structured request safe context만 보존한다. Agent Builder가 apply/save로 workflow graph를 저장하기 직전 backend는 candidate handle을 권한 확인된 runtime Knowledge Base reference로 다시 해석해야 하며, 이 재해석은 현재 recommendation top-N ranking 결과에 의존하지 않고 권한 확인된 후보 집합 안에서 safe handle을 직접 materialize해야 한다. Handle이 만료되었거나 권한 확인을 통과하지 못하면 validation failure 또는 재선택 질문으로 닫아야 한다.

초기 recommendation 결과는 KB 단위로 materialize된다. Builder UI는 Collection 맥락을 safe `source_collection_summary`로 설명할 수 있지만, 현재 LLM node draft에는 `knowledgeBases` 중심으로 저장한다.

MVP에서 Agent Builder가 제안하는 LLM node RAG 옵션은 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 기본값과 안전한 후보 설명으로 제한한다. `query_rewrite_mode`, `evidence_sufficiency_policy`, source tier hint의 자동 튜닝이나 품질 최적화는 후속 기능이다. 이 설정은 workflow node 옵션일 뿐이며 권한 범위를 넓히거나 runtime data access를 부여하지 않는다.

Knowledge Skill을 prompt context로 직접 사용하는 기능은 MBA-145 MVP 범위가 아니다. 후속 기능에서 Knowledge Skill을 사용할 경우에도 skill visibility, safe metadata display, freshness/eval gate를 통과한 safe field만 사용할 수 있으며, Skill이 제안한 collection/KB reference는 workflow 실행 시점에 execution subject 권한으로 다시 검증되어야 한다. Raw skill body, hidden source reference, raw source title/path/url, restricted document list, raw prompt/completion/provider response는 LLM context, audit, trace에 넣지 않는다.

### AB-FR-008: KB Recommendation Outcomes

KB recommendation 결과는 다음 중 하나여야 한다.

- 후보가 1개이고 high confidence 또는 `close_score` 이상이어도 pending KB resolution을 자동 해결하지 않는다.
- 권한 확인된 후보가 있으면 후보 수나 score 차이와 무관하게 사용자에게 KB 선택 clarification을 제공하고, safe label, candidate safe handle, confidence, score, reason category를 포함한 `clarification_options`를 함께 표시한다. Agent Builder client는 최대 20개 후보를 3개 카드 높이의 스크롤 목록으로 표시한다.
- 후보 0개: 권한 확인된 KB 후보가 없다는 경고를 표시하고, Knowledge Base binding이 비어 있는 LLM node draft를 생성할 수 있음
- 권한 확인된 KB는 있지만 indexing/not-ready 상태라 retrieval-visible 후보가 0개: 사용 준비 전 경고를 표시하고, 자동 선택하지 않음
- adapter unavailable: 권한 확인된 safe 후보 선택지가 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options`로 fallback clarification을 반환하고, safe 후보 선택지도 없으면 validation failure
- optional KB requirement unresolved: warning과 함께 KB 없는 draft 가능

Builder가 adapter unavailable 같은 recommendation 실패를 받으면 기본적으로 사용자 확인 필요 또는 validation failure 상태로 둔다. 다만 adapter가 정상 동작했고 권한 확인된 후보가 0개인 경우는 fail-open 권한 확장이 아니라 preview-only KB binding 미설정 상태로 보며, 한국어 경고와 함께 RAG 없는 LLM node draft를 생성할 수 있다. 이 draft는 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경을 수행하지 않는다.

KB 선택 clarification을 받은 사용자가 후보를 선택하면 Agent Builder는 safe handle과 선택적 resolution/requirement reference만 서버에 다시 보낸다. 사용자는 0개, 1개, 여러 개 KB 후보를 선택할 수 있다. Backend는 같은 authenticated user, active organization, workflow/app scope, agent panel session의 원 clarification option 안에 있던 후보인지 검증해야 하며, 통과한 경우에만 해당 pending KB resolution을 resolved 처리한다. 선택이 원 clarification context와 맞지 않거나 만료되었거나 apply/save 직전 runtime KB reference로 다시 해석되지 않으면 draft 확정 또는 저장으로 이어지면 안 된다.

KB 선택 clarification은 별도의 `Knowledge Base 없이 생성` option을 표시하지 않는다. 사용자가 아무 후보도 선택하지 않고 다시 제출하면 Agent Builder는 이전 clarification context가 유효한지 검증한 뒤, Knowledge Base binding을 비운 LLM node draft를 생성하고 safe warning을 표시한다. 이 선택은 raw KB id fallback, hidden KB 접근, runtime retrieval을 수행하지 않는다.

### AB-FR-009: Draft Generation

Draft는 기존 workflow model/schema와 지원 capability allowlist를 따라야 한다. Agent Builder는 임의 node type, edge structure, runtime rule을 만들 수 없다.

지원 capability allowlist는 [ADR-0024](../../decisions/ADR-0024-agent-builder-node-capability-catalog.md)의 공통 Workflow Node Capability Catalog를 기준으로 한다. 현재 구현된 16개 node type 중 `agent_builder_supported=true`인 `startNode`, `webhookTrigger`, `scheduleTrigger`, `llmNode`, `workflowNode`, `codeNode`, `conditionNode`, `fileExtractionNode`, `variableExtractionNode`, `answerNode`, `httpRequestNode`, `slackPostNode`, `templateNode`, `githubNode`, `mailNode` 15개를 포함한다. `loopNode`는 runtime 구현 여부와 별개로 현재 제품 가용성이 비활성 상태이므로 Agent Builder allowlist와 intent capability guide에서 제외한다. `githubNode`는 현재 PR 조회와 PR 댓글 등록 capability를 구분하며, 요청에 두 동작이 모두 필요하면 별도 node로 생성한다. PR 생성 operation은 자연어 의미로는 인식하지만 runtime, editor, catalog capability가 준비되기 전까지 draft node로 materialize하지 않는다.

외부 action 또는 필수 runtime 설정이 필요한 node는 draft에 포함할 수 있지만 Agent Builder가 credential, token, password, repository, channel, URL, target workflow 같은 값을 임의 생성하거나 원문으로 채우지 않는다. 해결되지 않은 값은 빈 값과 `configuration_state=unresolved`로 표시하고 node별 `configuration_issues`에 필요한 파라미터를 남긴다. 같은 type의 node가 여러 개여도 issue를 합치지 않는다. Draft 생성, Preview Mode, apply/save는 해당 node를 실행하지 않으며, 실제 실행 전 기존 editor/runtime validation과 별도 사용자 동작이 필요하다.

Generated LLM node의 기본 `model_id`는 active organization의 valid credential, active chat model, verified relation, 사용자 `use` 권한을 통과한 model 후보에서 추천한다. Provider는 `openai`, `anthropic`, `google` 순서로 평가하고, provider 안에서는 최신 세대, 같은 세대 `mini`, 이후 낮은 성능 tier 순으로 추천한다. Workflow graph에는 model id만 저장하며 추천에 사용된 credential id나 원문은 저장하지 않는다. 후보가 없으면 model id를 비우고 `configuration_state=unresolved`와 model 설정 필요 warning을 남기며, 고정 환경변수 model route 때문에 draft 생성을 실패시키지 않는다.

새 workflow draft는 시작 가능한 entry step을 포함해야 한다. 기존 workflow 수정 draft는 target resolution 결과와 graph validation을 만족해야 한다.

### AB-FR-010: Validation

Validation은 최소한 다음을 확인해야 한다.

- 지원하지 않는 node type
- 필수 설정 누락. 단 catalog가 draft-safe unresolved를 허용한 node에서 값이 비어 있고 `configuration_state=unresolved`인 경우는 Preview/apply-save warning으로 유지하며, 실제 실행 전 editor/runtime validation에서 차단한다.
- schema 불일치
- workflow/app scope 권한 부족
- 권한 없는 Knowledge Base, credential, channel 포함
- 승인 없는 외부 호출 가능성
- expired candidate handle
- stale workflow context
- entry/trigger node로 들어오는 edge
- terminal node에서 나가는 edge
- Condition의 Default 또는 설정된 case가 아닌 source handle

연결 정책은 [ADR-0026](../../decisions/ADR-0026-agent-builder-intent-and-connection-validation.md)의 catalog v2 계약을 사용해 complete candidate graph에 적용한다. Preview validation과 apply/save 재검증은 같은 backend validator를 사용하며, 연결 정책 위반 graph는 저장하지 않는다.

### AB-FR-011: Draft Preview Mode And Apply Save

Agent Builder는 validation을 통과한 draft에 대해 사용자가 저장 전 확인할 수 있는 Draft Preview를 제공해야 한다. 이 경계는 [ADR-0019](../../decisions/ADR-0019-agent-builder-preview-apply-save-boundary.md)를 따른다. Chatbot panel은 요약과 `도안 생성 미리보기` 진입점을 제공하고, 상세 검토는 Workflow Editor의 Preview Mode에서 수행한다.

Preview Mode는 현재 editor graph를 덮어쓰지 않고, agent가 생성한 `previewGraph`를 실제 editor graph와 분리된 읽기 전용 graph로 렌더링해야 한다. 사용자는 preview graph의 node와 edge를 확인하고, node를 선택해 Node Detail Panel에서 node type, 주요 설정, Knowledge Base binding, Slack channel binding, credential 참조 상태, input/output mapping, validation 상태를 확인할 수 있어야 한다.

Preview Mode에서 Node Detail Panel은 canvas 왼쪽 영역에 표시해야 한다. Agent Builder chatbot panel과 apply/save action이 우측 또는 우측 하단에 머무를 수 있으므로, node detail을 우측에 열어 chat panel과 겹치게 해서는 안 된다. 좁은 viewport에서는 왼쪽 drawer 또는 non-overlapping responsive layout을 사용해 node detail, chat panel, apply/save action 경로가 서로 가려지지 않게 해야 한다.

Preview Mode의 canvas node card는 workflow 구조를 빠르게 파악하기 위한 요약 표면이다. Answer/Output 계열 node card는 내부 output variable 목록이나 value selector mapping을 카드 본문에 직접 렌더링하지 않아야 하며, 해당 상세 정보는 Node Detail Panel 또는 기존 node 설정 패널에서 확인해야 한다.

Preview Mode의 Node Detail Panel은 편집을 허용하지 않는다. 사용자가 draft 내용을 바꾸려면 채팅 후속 요청으로 수정해야 한다. Preview Mode에는 이 graph가 아직 저장되지 않은 도안이라는 안내와 `적용 및 저장`, `취소` action을 항상 접근 가능한 위치에 표시해야 한다. MVP에서는 이 action을 canvas banner/action bar 또는 Preview Mode 동안 닫을 수 없는 Agent Builder panel에 둘 수 있지만, 사용자가 panel을 닫아 적용/취소 경로를 잃게 해서는 안 된다.

`취소`를 선택하면 현재 Preview Mode를 종료하고 기존 editor state로 돌아간다. 이 event는 server-side apply/save audit에 `canceled` outcome으로 기록할 수 있어야 하지만, draft metadata 자체를 terminal 폐기한다는 뜻은 아니다. Validation을 통과한 직전 draft는 만료되거나 새 draft로 대체되기 전까지 다시 `도안 생성 미리보기`로 열 수 있다. 기존 editor graph는 preview 진입만으로 변경되지 않았어야 하므로 rollback이 필요한 방식으로 구현하지 않는다.

`적용 및 저장`을 선택하면 backend는 원 draft metadata 조회, 요청 유형별 권한 재확인, stale check, validation 재확인을 통과한 경우에만 workflow graph를 저장한다. 기존 workflow 수정 draft는 workflow read/write 권한을 재확인하고, 새 workflow draft는 app 또는 workflow 생성 scope 권한을 재확인한다. 전체 교체 draft는 기존 workflow read/write 권한과 교체 validation을 모두 만족해야 한다.

`적용 및 저장`이 저장으로 이어지는 경우, Agent Builder는 workflow graph를 저장하기 전에 기존 Workflow Editor의 레이아웃 최적화 UI 버튼과 동등한 자동 레이아웃 최적화 로직을 draft graph에 적용해야 한다. 저장된 workflow graph의 node position은 이 최적화 결과를 반영해야 하며, 저장 성공 후 사용자가 보는 최신 graph도 같은 position을 표시해야 한다. 이 자동 레이아웃은 graph 배치만 조정하며 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경을 수행하지 않는다.

Stale check는 draft 생성 시점의 `base_graph_hash`와 workflow `version` 또는 `updated_at`을 저장하고, 적용 및 저장 시점의 최신 graph hash와 최신 version/updated_at을 함께 비교한다. `base_graph_hash` 또는 version/updated_at 중 하나라도 달라지면 stale로 간주하고 저장을 차단한다. `base_graph_hash`에는 node id, node type, node data/config, edge source/target/handle처럼 workflow 의미에 영향을 주는 값만 포함하고, viewport, selection, panel state, preview state, timestamp, UI-only metadata, note/memo node와 해당 note/memo node에만 연결된 non-runtime edge는 포함하지 않는다.

`적용 및 저장`은 workflow graph 저장까지 의미하지만 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경을 의미하지 않는다. 저장 이후 workflow 실행은 기존 execution flow의 별도 사용자 동작으로만 수행된다.

저장 성공 시 Preview Mode를 종료하고 Workflow Editor는 저장된 최신 workflow graph를 표시한다. `outcome=saved`는 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 응답은 허용하지 않는다. 새 workflow draft 생성이 성공하면 새 workflow editor로 이동하거나 현재 editor context를 새 workflow로 전환한다. Agent Builder chatbot은 저장 완료와 별도 실행 필요 상태를 한국어로 안내한다.

저장 성공 후 Workflow Editor는 local `previewGraph`를 actual editor graph로 바로 승격하지 않는다. 저장된 workflow id를 기준으로 서버의 최신 workflow graph를 다시 조회하거나, 서버가 반환한 동등한 최신 저장 graph로 reconcile한 뒤 표시해야 한다. 이 경계는 preview-only graph가 실제 저장 결과와 달라지는 상황을 방지하기 위한 것이다.

저장 차단 또는 저장 시도 실패 시 Preview Mode를 유지하고 `actualEditorGraph`를 변경하지 않는다. 사용자는 차단 사유 또는 실패 사유를 확인한 뒤 재시도, 취소, 또는 채팅 후속 요청으로 draft 수정을 선택할 수 있어야 한다. `blocked` outcome은 draft metadata 없음, draft metadata 만료, workflow read/write 권한 부족, app 또는 workflow 생성 scope 권한 부족, stale draft, validation 실패, active organization mismatch, 저장되지 않은 editor 변경 같은 차단 사유를 `block_reason`으로 표현한다. `failed` outcome은 backend 저장 시도 실패 또는 apply/save audit 기록 실패 같은 실패 사유를 `failure_reason`으로 표현한다.

Preview Mode는 `actualEditorGraph`와 `previewGraph`를 섞지 않아야 한다. 진단을 위해 draft id, request id, apply id, session id, workflow id 또는 새 workflow 생성 scope, preview graph hash, base graph hash, latest graph hash, workflow version 또는 updated_at, draft mode, apply/save outcome, block reason, failure reason, permission recheck outcome, stale state, validation state, saved workflow id, timestamp를 audit-safe metadata로 추적할 수 있어야 한다. Audit metadata에는 credential 원문, raw KB content, raw source path/url/title, hidden KB/resource detail, raw provider response, secret-like user input 원문을 포함하지 않는다.

Apply/save audit event는 draft preview 생성, Preview Mode 진입, 적용 및 저장 요청, 저장 차단, 저장 성공, 저장 실패, 취소를 구분해야 한다. 저장 성공 event는 workflow graph 저장 완료와 audit 기록 성공을 함께 의미하지만 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경을 의미하지 않는다.

MVP에서는 editor에 저장되지 않은 변경이 있으면 Agent Builder draft 생성, Preview Mode 진입, 또는 `적용 및 저장`을 진행하지 않는다. 사용자는 먼저 기존 editor 변경을 저장하거나 폐기해야 한다. 이는 unsaved graph와 agent draft가 섞여 저장 충돌이나 rollback 문제를 만드는 것을 막기 위한 동시성 보호 정책이다.

MVP message request는 raw client graph snapshot을 받지 않는다. Client는 선택된 node/edge hint만 보낼 수 있고, apply/save 단계에서 `client_preview_graph_hash`와 `client_latest_graph_hash` 같은 semantic graph hash를 사용해 preview 확인 여부와 stale 여부를 검증한다. Hash 계산이 불가능하면 raw graph payload로 fallback하지 않고 apply/save를 차단해야 한다.

후속 확장에서는 현재 unsaved editor graph를 검증 가능한 client graph snapshot으로 서버에 전달하고, 서버가 snapshot hash와 schema를 검증한 뒤 해당 snapshot을 draft base로 삼는 방식을 고려할 수 있다. 이 확장 전까지는 unsaved editor graph를 draft base로 자동 포함하지 않는다.

### AB-FR-012: Conversation Session

Agent Builder chatbot session은 refresh 이후에도 최근 대화와 pending request 상태를 복구할 수 있어야 한다. 최근 대화 복구는 redaction을 거친 사용자 message summary와 assistant response를 함께 포함해야 하며, 사용자 원문 또는 secret-like value를 그대로 저장/표시하지 않는다. Session identifier는 server-issued 값이어야 하며, 인증 사용자, active organization, workflow/app scope, agent panel lifecycle에 묶여야 한다. Client가 임의로 생성한 session id는 권한, scope, audit, stale 판단의 근거로 사용할 수 없다.

같은 workflow의 `적용 및 저장` 성공 후 server graph를 reconcile하면서 기존에 비어 있던 `app_id`가 채워지는 것은 route scope 변경으로 보지 않는다. 이 경우 Agent Builder panel의 열린 상태와 현재 대화를 유지해야 한다. Workflow id가 실제로 바뀌거나 workflow가 없는 app-only route의 app id가 바뀌면 이전 scope의 session, pending state, preview graph를 이어받지 않는다.

`draft_mode=new_workflow`의 저장 성공으로 새 workflow route로 이동하는 경우에는 저장 transaction 안에서 현재 Agent Builder session scope를 새 workflow와 해당 app으로 재결합해야 한다. Client는 같은 server-issued session id를 새 workflow storage key로 이전하고 panel을 다시 열어 redaction된 최근 대화를 복구한다. 임의 session id 생성이나 다른 사용자/조직 session 이전은 허용하지 않는다.

Pending request가 있으면 중복 submit을 막고 cancel을 제공한다. Cancel된 request의 late result는 draft preview, Preview Mode 진입, apply/save로 이어질 수 없다.

## Success Criteria

- 사용자가 자연어 요청 후 preview 가능한 workflow draft 또는 clarification을 받을 수 있다.
- KB가 필요한 요청은 draft 생성 시점 retrieval 없이 Knowledge Base-backed LLM step으로 표현된다.
- KB 후보가 권한 확인된 safe metadata 안에서만 추천된다.
- 후보가 모호하면 임의 선택하지 않고 질문한다.
- `적용 및 저장` 전에는 workflow 저장, workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경이 발생하지 않는다. 자연어 구조화를 위한 AB-FR-003 내부 planner 호출은 이 runtime side-effect 금지와 구분한다.
- Demo happy path에서 draft preview, Preview Mode, 읽기 전용 Node Detail 확인, backend 재검사, 자동 레이아웃 최적화가 반영된 workflow graph 저장, apply/save audit 기록 성공, Preview Mode 종료, 저장된 최신 graph 표시를 확인할 수 있다.

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
