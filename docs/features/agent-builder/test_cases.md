# Agent Builder Test Cases

Status: Draft

## Unit Tests

- Agent Builder intent model option은 `openai`, `anthropic`, `google`, `llamaparse` provider 순서로 반환되고, Header와 generated LLM node는 같은 통합 추천 정책을 사용한다.
- Model option은 active organization의 `LLMCredential.is_valid=true`, `LLMModel.is_active=true`, `LLMModel.type=chat`, model과 credential의 provider 일치, `LLMRelCredentialModel.is_verified=true`, 사용자 credential `use` 권한을 모두 통과한 조합을 포함한다. 가장 높은 순위 후보가 invalid, inactive, non-chat, provider 불일치, unverified, permission denied 또는 특수 목적 모델이면 같은 provider의 다음 자격 후보를 선택하고, 해당 provider에 자격 후보가 없으면 다음 provider로 이동한다. 같은 model/credential의 verified relation이 중복이면 가장 낮은 relation priority 하나만 Header와 generated LLM node 추천에 사용한다.
- Provider 안에서는 최신 세대가 tier보다 먼저이며, 같은 세대의 모델은 `general`, `mini`, `nano`, `pro` 순서로 정렬된다. OpenAI의 `gpt-5.5`, `gpt-4o`, `gpt-4o-mini`, `o4-mini` 계열, Anthropic의 제품명 우선 및 `claude-3-5-sonnet` 같은 세대명 우선 형식, Google 기본형/flash/flash-lite/pro 대응을 각각 검증한다.
- 날짜 또는 release suffix가 붙은 `claude-sonnet-4-5-20250929`, `preview` suffix가 붙은 `gemini-3.1-pro-preview`, `latest` suffix가 붙은 모델은 원래 model ID를 유지하면서 세대와 tier만 해석한다. 같은 provider, 세대와 tier의 후보는 suffix가 없는 기본형, 날짜 또는 명시 release snapshot, `preview`, `latest` 순서다. 선행 `models/`, 대소문자와 앞뒤 공백은 비교용으로만 정규화한다.
- Sora, audio, transcribe, TTS, speech, Whisper, realtime, live, image, embedding, moderation, search, Codex, computer-use, robotics처럼 정규화한 API model ID로 특수 목적이 확정된 모델은 Agent Builder option과 generated LLM node 추천에서 제외된다. `gpt-4o-mini-tts`, `gpt-5.3-codex`, `gemini-2.5-flash-image-preview`, `gemini-2.5-computer-use-preview`는 완전한 token 또는 명시된 연속 token 규칙으로 제외되어야 한다. `gpt-livestream`, `gpt-researcher`, `gpt-audiophile`처럼 금지 token의 문자열 일부만 포함한 미분류 verified chat 모델은 단순 부분 문자열 일치로 제외하면 안 된다. 이 모델들은 임의 성능을 추측하지 않고 provider의 해석 가능한 후보 뒤에 안정적인 순서로 남아 Header에서 선택할 수 있고 두 경로의 fallback 후보로 사용된다. 입력 순서를 바꿔도 결과가 같아야 하며 전역 model catalog row는 변경하지 않는다.
- LlamaParse group은 option 없이 `chat_model_not_supported`를 반환한다.
- 같은 5.5 세대의 OpenAI general/mini/nano/pro 후보가 있으면 `gpt-5.5`, `gpt-5.5-mini`, `gpt-5.5-nano`, `gpt-5.5-pro` 순서로 정렬되어 MBA-240 회귀 사례를 충족한다. 같은 5.5 general 후보는 `gpt-5.5`, `gpt-5.5-2026-04-23`, `gpt-5.5-preview`, `gpt-5.5-latest` 순서이며, 더 최신 세대가 있으면 특정 `gpt-5.5` 고정 예외 없이 최신 세대를 먼저 선택한다.
- 동일한 자격 후보 집합에서 Header provider group을 펼친 첫 사용 가능 model ID와 새 generated LLM node의 추천 model ID가 같다.
- Agent Builder Header는 통합 정책의 첫 사용 가능 model을 기본 표시한다. 사용자가 다른 model을 선택하면 선택한 credential/model ID 쌍은 message request에만 포함하고 저장하지 않으며 generated LLM node 추천 model로 복사하지 않는다.
- Agent Builder model 선택 메뉴는 chat panel 가로 폭의 약 절반이며 모델 행 약 5개 높이를 넘는 option은 내부 세로 스크롤로 확인할 수 있다.
- Message submit 직전 선택이 아직 확정되지 않았으면 화면에 표시할 같은 option 목록을 조회해 첫 option을 확정하며, option이 없으면 message를 전송하지 않는다.
- Server는 선택된 credential/model 쌍을 매 요청 재검증하고 `use` 권한 또는 verified relation이 사라졌으면 LLM client를 생성하지 않는다.
- Intent model 선택 상태는 session, draft metadata, workflow graph 또는 별도 model-selection DB column에 저장되지 않는다. Permission/runtime 차단 audit은 safe credential/model ID와 reason만 기록하며 credential 원문과 raw provider response는 API response, audit, trace에 포함되지 않는다.
- Generated LLM node graph에는 추천 model id만 저장하고 credential id/config는 저장하지 않는다. DB 자격 후보가 없거나 특수 목적 모델을 제외한 뒤 후보가 없으면 `model_id`가 비어 있는 `configuration_state=unresolved` node와 model 설정 필요 issue를 만들며 draft는 계속 생성된다.
- Preview Mode에서는 generated LLM node model을 읽기 전용으로 표시하고 model picker를 제공하지 않는다. 신규 Agent draft를 적용 및 저장한 뒤 workflow를 다시 조회하면 추천 `model_id`가 유지된다. 기존 Agent 수정 시 기존 LLM node의 다른 model ID는 저장 후에도 유지되고, 새로 생성한 LLM node에만 현재 추천을 적용한다. 사용자는 적용 및 저장 후 기존 Workflow Editor에서 LLM node model을 다른 사용 가능한 값으로 변경해 저장할 수 있으며 이후 추천 정책이 이를 덮어쓰지 않는다.
- `apps/gateway/application/agent_builder`의 추천 정책 모듈은 SQLAlchemy, FastAPI, Pydantic response schema, provider SDK, credential service 또는 outer adapter를 import하지 않는다는 architecture import-boundary 테스트를 통과한다.
- `StructuredRequestBuilder`는 자연어 요청을 `request_type`, `intent_summary`, `planned_steps`, `knowledge_requirements`, `pending_resolution`, `missing_information`으로 분리한다.
- `LLMIntentExtractor`는 redaction된 요청, safe workflow context, permission/readiness를 통과한 상위 20개 bounded safe KB candidate context를 입력받고 JSON object를 반환하며, 절에 나타난 capability 순서와 기존 target/new step 역할을 보존한다.
- LLM 출력에 catalog 밖 capability, node/edge id, 잘못된 request type/draft mode 조합이 있으면 `StructuredRequestBuilder`는 이를 graph로 materialize하지 않는다.
- LLM 호출 실패 또는 JSON/schema validation 실패 시 deterministic 정규식 parser로 silent fallback하지 않고 partial draft 없이 실패한다.
- Pre-intent KB context는 opaque handle, safe label/topics/description, runtime availability, bounded relevance만 포함하며 raw KB UUID, collection/source/document/chunk identity, path/URL, hidden/denied count를 포함하지 않는다.
- LLM이 pre-intent context에 없는 candidate handle을 반환하면 정확히 1회 safe-code repair 후에도 유효하지 않을 경우 `INTENT_EXTRACTION_FAILED`로 종료한다.
- `StructuredRequestBuilder`는 LLM이 제안한 valid opaque handle을 `knowledge_requirements[].suggested_candidate_handles`에 보존하지만 자동 선택하지 않고 `pending_resolution(slot_type=knowledge_base)`을 생성한다.
- Knowledge Base처럼 resolver가 해결할 수 있는 값은 즉시 `missing_information`으로 올리지 않고 `pending_resolution`으로 둔다.
- `blocking` 최종값은 LLM hint가 아니라 product policy와 slot type 규칙으로 확정된다.
- `TargetResolver`는 자연어 target이 selected node보다 우선한다.
- `TargetResolver`는 LLM structured edit이 `selected_edge` target을 반환하고 server-loaded graph에 선택 edge가 존재할 때만 `selected_edge_id`를 위치 hint로 사용한다. Raw message 정규식은 이 결정을 대체하지 않는다.
- `selected_edge_id`가 확정된 기존 workflow 수정 draft는 선택된 edge의 source와 target 사이에 생성 step을 삽입하는 preview graph를 만들고, 저장 시 기존 선택 edge를 제거한 뒤 생성 step edge를 연결한다.
- 동일 type node가 여러 개이고 selected node가 후보가 아니면 clarification을 반환한다.
- GitHub PR 조회와 댓글 등록 node가 모두 존재하면 `TargetResolver`는 LLM이 구조화한 `github_pr_read`/`github_pr_comment` role과 safe title을 공통 `githubNode` type보다 우선한다.
- `WorkflowDraftValidator`는 unsupported node type, unresolved로 명시되지 않은 missing config, schema mismatch, permission shortage를 실패로 반환한다. Catalog가 draft-safe unresolved를 허용한 외부 node는 `configuration_state=unresolved`와 warning을 유지하고 외부 호출 없이 Preview/apply-save할 수 있지만 실제 실행 전 editor/runtime validation을 통과해야 한다.

## API Tests

- (FR-001) 생성 요청 성공 시 공통 Workflow Node Capability Catalog allowlist 안에서 노드 그래프를 반환한다. 대표 프롬프트: "사내 휴가 정책을 바탕으로 직원 질문에 답하고 결과를 Slack으로 보내줘" → Start/Input, Knowledge Base-backed LLM, Slack send, Answer 계열 노드 포함. Slack channel 또는 KB 후보가 모호하면 unresolved warning 또는 clarification 정책을 따른다.
- 공통 catalog의 `implemented=true` node type 16개 집합은 Workflow Editor node registry, React Flow renderer, Workflow Engine registry와 일치해야 한다. Agent Builder allowlist는 제품 가용성이 비활성인 `loopNode`를 제외한 15개이며, `implemented=false` 또는 `agent_builder_supported=false` node는 Builder capability guide와 draft에 들어가면 안 된다.
- "웹훅 노드로 받아서 PR 리뷰를 깃허브에 올려주는 워크플로우를 만들어줘" 요청은 Webhook Trigger, GitHub PR 조회, LLM 리뷰, GitHub PR 댓글, Answer node를 순서대로 포함한다. 두 GitHub node의 credential/repository/PR 설정은 원문 없이 `configuration_state=unresolved`여야 하며 draft 생성 중 GitHub API 호출이 없어야 한다.
- 업무 메일 수신 workflow 요청으로 생성된 Mail node는 `credential_id=null`, `configuration_state=unresolved`이며 email, password, token, provider endpoint를 포함하지 않는다. Draft 생성 중 credential 조회·복호화 또는 Mail provider 연결이 없어야 한다.
- Gmail 답장 초안 요청은 `max_results=1`인 durable Mail 검색, LLM, unresolved Gmail Draft와 Mail Acknowledge node를 순서대로 연결한다. 잘못 정렬된 intent extraction도 server에서 이 순서로 정규화하고 acknowledgement 단독 extraction은 unsupported로 거부한다. Preview/apply-save 중 OAuth token refresh, Gmail draft 생성, 읽음 처리 또는 send 호출이 없어야 한다.
- Agent Builder가 email send, reply-all, attachment를 요청받으면 지원하지 않는 capability로 명시하고 Gmail send node나 arbitrary HTTP fallback을 만들지 않는다.
- `새 워크플로우로 웹훅에서 요청을 받고 GitHub PR을 조회한 뒤 LLM으로 리뷰해서 GitHub PR에 댓글을 등록해줘` 요청은 `unsupported`가 아니라 Webhook Trigger, GitHub PR 조회, LLM, GitHub PR 댓글, Answer node를 반환해야 한다.
- `새 워크플로우로 GitHub PR을 조회한 뒤 LLM으로 리뷰해줘`처럼 댓글/게시 의도가 없는 요청은 GitHub PR 조회와 LLM을 포함하되 `github_pr_comment` capability를 추가하면 안 된다.
- "웹 훅으로 받고 깃허브에서 PR을 받고 분석해서 깃허브 PR에 리뷰 댓글을 올리는 노드를 생성해줘"처럼 `웹 훅`을 띄어 쓰거나 `올리는` 활용형을 사용해도 목적어가 댓글이면 같은 Webhook Trigger, GitHub PR 조회, LLM, GitHub PR 댓글, Answer 흐름을 생성해야 한다.
- 기존 LLM node가 있는 workflow에서 "LLM 뒤에 깃허브로 PR을 올리는 로직을 추가해줘"를 요청하면 provider=`github`, resource=`pull_request`, operation=`create`, target=`llm`, placement=`after`로 의미를 구분한다. 현재 `create_pr` runtime capability가 없으므로 `http_request` node로 대체하지 않고 `unsupported`와 `GitHub Pull Request 생성은 현재 지원되지 않습니다.`를 반환해야 한다.
- `기존 LLM 노드 뒤에 GitHub PR 생성 노드를 삽입`과 `기존 LLM 노드 뒤에 깃허브 PR 생성 노드를 삽입`의 첫 LLM 결과가 GitHub action 없이 `http_request`를 반환하면 `GITHUB_INTEGRATION_ACTION_REQUIRED`로 정확히 한 번 repair해야 한다. Repair 결과의 operation은 LLM이 `create`로 반환해야 하며 backend가 raw message 동사에서 직접 만들면 안 된다. 최종 응답은 현재 runtime 범위에 따라 `unsupported`이고 HTTP draft를 포함하지 않아야 한다.
- 기존 LLM node 뒤에 일반 REST API 호출을 삽입하는 요청은 GitHub provider guard를 타지 않고 `http_request` capability를 유지해야 한다. 기존 GitHub node를 target으로 지칭하면서 새 LLM node만 삽입하는 요청도 새 GitHub action 누락으로 오판하면 안 된다.
- GitHub PR 댓글 요청을 intent model이 `http_request`로 반환하면 `GITHUB_OPERATION_CAPABILITY_MISMATCH` safe code로 정확히 한 번 repair하고 `github_pr_comment`로 교정해야 한다. 두 번째 결과도 불일치하면 partial draft 없이 `INTENT_EXTRACTION_FAILED`로 종료한다.
- 공통 외부 호출 차단 안내는 `draft_preview.safety_notices`에 한 번만 표시한다. Slack 채널/credential과 GitHub credential/repository/PR처럼 미해결된 설정은 `configuration_issues`에 node별로 포함하고, GitHub 조회와 GitHub 댓글 node처럼 같은 type이 두 개 이상이어도 각각의 표시명과 필요한 파라미터 목록을 모두 렌더링해야 한다. Session restore 후에도 preview graph에서 같은 목록이 복구되어야 한다.
- 각 allowlist node type은 schema-compatible 기본 draft template과 최소 하나의 deterministic capability materialization test를 가져야 한다. 자연어 의미 추출 자체를 capability 정규식 목록으로 검증한다는 뜻은 아니다.
- (FR-003) 사용 가능한 credential이 없는 상태에서 생성 요청 → 부족한 credential/모델을 명시한 사전 안내 응답.
- Permission-aware intent model runtime이 없으면 `configuration_required/INTENT_MODEL_ROUTE_REQUIRED`, LLM response가 invalid JSON/schema이면 재시도 없이 `failed/INTENT_EXTRACTION_FAILED`를 반환하고 provider 응답 원문을 노출하지 않는다.
- Schema-valid LLM response가 request/draft mode, workflow context, 신규 capability, target/placement semantic invariant를 위반하면 safe validation code만 포함해 정확히 한 번 repair하고, 두 번째 결과도 유효하지 않으면 `failed/INTENT_EXTRACTION_FAILED`로 종료한다.
- 전체 교체는 `request_type=modify_workflow`, `draft_mode=replace_workflow`를 유지하며 완결된 graph가 되도록 entry와 Answer terminal을 정규화한다.
- Backend preview와 apply/save는 catalog connection policy로 complete candidate graph를 검증한다. Answer outgoing, Start/Webhook/Schedule incoming, 잘못된 Condition source handle은 각각 명시적 validation code로 차단되고 graph가 저장되지 않아야 한다.
- 유효하지 않은 `X-Organization-Id` header → 실행 전 검증 오류로 거부.
- 해석 불가능한 프롬프트(예: 빈 문자열, 자동화와 무관한 요청) → 빈 workflow나 `입력 -> LLM -> 출력` 기본 draft를 만들지 않고 `unsupported` 또는 동등한 명시적 실패 응답과 한국어 사용 힌트를 반환한다.
- "입력 - 출력 노드를 만들어줘"처럼 LLM, Knowledge Base, Slack 요구가 없는 단순 입출력 요청 → intent extractor runtime으로 요청을 구조화한 뒤 Start/Input과 Answer/Output 계열 draft를 생성하고 LLM node를 기본 삽입하지 않는다. 생성된 workflow의 LLM node model route는 필요하지 않지만 intent extractor runtime은 필요하다.
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
- 기존 `Start -> GitHub -> Answer` graph에서 `GitHub 노드 뒤에 LLM 노드를 추가해줘`를 요청하면 `StructuredRequest.required_capabilities`에는 신규 `llm`만 포함되고, preview는 기존 `GitHub -> Answer` edge를 `GitHub -> 새 LLM -> Answer`로 교체해야 한다. 새 Start, GitHub, Answer node 또는 분리된 component를 만들면 안 된다.
- 기존 `LLM -> GitHub PR 댓글 등록` graph에서 `llm 뒤에 응답 노드 하나 추가`를 요청하면 LLM structured output은 target `llm`, 신규 capability `answer`, placement `after`로 분리되고 preview는 `LLM -> 새 Answer -> GitHub PR 댓글 등록`으로 재연결되어야 한다.
- 자연어 target과 일치하는 기존 node가 여러 개이면 selected node가 후보 중 하나일 때만 해당 node를 사용하고, 그렇지 않으면 `clarification_required`와 safe workflow node 후보를 반환한다.
- 수정 target이 해결되지 않았거나 삽입 방향의 edge가 여러 개여서 위치가 모호하면 generic full workflow draft로 silent fallback하지 않는다.
- 기존 workflow가 열린 상태에서 `입력 출력 노드 생성해줘` 또는 `새 워크플로우로 schedule trigger에서 시작해서 REST API를 호출하고 LLM으로 결과를 요약한 뒤 Slack으로 보내줘`를 요청하면 `draft_mode=new_workflow`와 `status=draft_ready`를 반환해야 한다. 신규 graph가 기존 graph에 연결되지 않았다는 이유로 `DETACHED_GENERATED_COMPONENT`를 반환하면 안 되며, draft의 `workflow_id`와 `base_workflow_updated_at`은 비어 있고 `workflow_scope=new_workflow`여야 한다.
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
- 후보가 1개이고 high confidence 또는 `close_score` 이상이어도 KB pending resolution은 자동 resolved 처리되지 않는다.
- 권한 확인된 KB 후보가 있으면 후보 수나 score 차이와 무관하게 safe label, candidate safe handle, confidence, score, reason category를 포함한 clarification option이 표시된다. Client는 후보를 3개 카드 높이의 스크롤 목록으로 표시하고, 서버가 반환한 최대 20개 후보를 선택 가능하게 유지한다.
- 사용자가 clarification option 중 하나를 선택하면 client는 safe candidate handle과 선택적 resolution/requirement reference만 제출하고, backend는 원 clarification option과 같은 session/context인지 검증한 뒤 pending KB resolution을 resolved 처리한다.
- KB 선택 또는 빈 선택으로 후속 `draft_ready` 응답을 받은 뒤에는 client가 과거 clarification을 빈 입력 전송의 근거로 재사용하지 않아야 하며, 같은 요청으로 새 draft를 추가 생성하면 안 된다.
- Backend는 KB 선택 제출 시 직전 미해결 clarification만 허용해야 한다. 이미 `draft_ready`, validation failure, 취소 또는 다른 후속 응답으로 해결된 clarification을 다시 제출하면 validation failure로 닫고 새 draft를 만들면 안 된다.
- 원 clarification context와 맞지 않는 candidate handle, 만료된 option, 또는 apply/save 직전 materialization 실패는 draft 확정이나 저장으로 이어지지 않는다.
- 후보 0개이면 validation failure로 닫지 않고, 권한 확인된 KB 후보가 없다는 경고와 함께 Knowledge Base binding이 비어 있는 LLM node draft를 생성한다.
- Adapter unavailable이고 권한 확인된 safe 후보 선택지가 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options` 기반 fallback clarification을 반환한다.
- Adapter unavailable이고 safe 후보 선택지도 없으면 validation failure를 반환한다.
- 추천 결과는 LLM node의 `knowledgeBases`로 materialize 가능해야 한다.
- Collection은 preview 설명용 safe summary로만 표시되고 workflow runtime field로 저장되지 않는다.
- MVP에서 RAG retrieval signal과 LLM reranker는 비활성이다.
- 사용자가 Agent Builder에 요청을 보내거나 assistant 응답/pending 상태가 추가되면 chat panel의 대화 영역은 최신 메시지가 보이도록 맨 아래로 자동 스크롤되어야 한다. KB 후보 목록 자체의 내부 스크롤 위치는 이 동작과 분리되어야 한다.

- KB 후보 clarification에는 실제 선택 가능한 Knowledge Base 후보만 표시되어야 한다. 사용자가 아무 후보도 선택하지 않고 제출하면 client는 `selected_knowledge_candidates=[]`를 보내고, backend는 같은 prior clarification context인지 검증한 뒤 `knowledgeBases=[]`인 LLM node draft를 생성해야 한다.

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

- Draft 생성 시 workflow graph 저장, Knowledge Base retrieval, Slack/GitHub/HTTP/Mail 외부 호출, workflow 실행, workflow node credential 사용/변경, 외부 시스템 변경이 발생하지 않는다. Intent extractor의 permission-aware 내부 planner 호출은 별도이며 credential/provider 원문을 저장하지 않는다.
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
- 같은 workflow의 apply/save 성공 후 server graph reconcile로 `app_id`가 `null`에서 실제 값으로 채워져도 Agent Builder panel은 열린 상태와 기존 대화를 유지한다.
- 새 workflow draft는 생성 시점 App primary `workflow_id`를 server-owned expected value로 저장한다. Apply/save 시 App row를 잠근 뒤 current primary와 비교하며 값이 다르거나 expected metadata가 없거나 손상되었으면 새 Workflow를 만들지 않고 safe stale/metadata block으로 닫는다.
- 대상 App에 `active_deployment_id`가 있으면 새 workflow apply/save는 기존 배포를 자동 비활성화하지 않고 `APP_ACTIVE_DEPLOYMENT_CONFLICT`로 차단한다. App primary, 배포, 권한은 변경되지 않아야 한다.
- 새 workflow apply/save 성공 시 기존 primary의 같은 organization user/team Workflow permission과 option/flag를 새 Workflow로 승계하고 적용 actor의 manager 권한을 보장한다. DB session의 workflow scope와 App의 primary `workflow_id`가 `saved_workflow_id`로 같은 transaction에서 갱신되며, 새 route에서 같은 server-issued session id와 redaction된 대화를 복구한다.
- 권한 승계, apply/save audit 또는 commit이 실패하면 transaction을 rollback하고 기존 App primary와 권한을 유지한다.
- Refresh 후 session 복구는 redaction된 사용자 message summary와 assistant response를 함께 복구하고, secret-like user input 원문을 다시 표시하지 않는다.
- 최신 request가 `failed`, `unsupported`, `validation_failed`이고 session에 과거 ready draft가 남아 있어도 backend는 request ID가 다른 top-level `draft_preview`를 반환하지 않으며 client도 이를 도안 생성 미리보기로 복구하지 않는다. 최신 request와 draft의 `request_id`가 일치하면 정상적으로 preview를 복구한다.
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
- `DRAFT_METADATA_NOT_FOUND`, `DRAFT_METADATA_EXPIRED`, `WORKFLOW_PERMISSION_REQUIRED`, `APP_CREATE_PERMISSION_REQUIRED`, `APP_ACTIVE_DEPLOYMENT_CONFLICT`, `DRAFT_STALE`, `DRAFT_VALIDATION_FAILED`, `ORGANIZATION_CONTEXT_MISMATCH`, `UNSAVED_EDITOR_CHANGES`는 `outcome=blocked`와 `block_reason`으로 한국어 차단 안내를 표시한다.
- `SAVE_FAILED`는 `outcome=failed`와 `failure_reason`으로 한국어 실패 안내를 표시한다.
- `outcome=saved`는 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 응답은 허용되지 않는다.
- workflow graph 저장 시도 후 apply/save audit 기록이 실패하면 `SAVE_FAILED` 또는 동등한 safe failure로 처리되고 Preview Mode가 유지되며 actual editor graph는 변경되지 않는다.
- `적용 및 저장`이 저장으로 이어지면 저장 전에 기존 Workflow Editor 레이아웃 최적화 UI 버튼과 동등한 자동 레이아웃 로직이 적용된다.
- 저장된 workflow graph의 node position은 자동 레이아웃 최적화 결과와 일치해야 하며, 저장 성공 후 editor가 다시 조회하거나 reconcile해 표시하는 최신 graph도 같은 position을 사용해야 한다.
- 자동 레이아웃 최적화는 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경을 발생시키지 않는다.
- 저장 성공 시 Preview Mode가 종료되고 editor는 저장된 최신 workflow graph를 표시한다.
- 저장 성공 후 client는 local `previewGraph`를 actual editor graph로 직접 승격하지 않고, 저장된 workflow id를 기준으로 서버 최신 graph를 다시 조회하거나 동등한 서버 반환 graph로 reconcile해 표시한다.
- 저장 차단 또는 실패 시 Preview Mode가 유지되고 actual editor graph는 변경되지 않는다.
- 저장 성공 후에도 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경은 발생하지 않는다.
- Draft preview 생성, Preview Mode 진입, 적용 및 저장 요청, 저장 차단, 저장 성공, 저장 실패, 취소 audit event가 구분되어 기록된다.
- Audit event에는 safe metadata만 포함하고 credential 원문, raw KB content, raw source path/url/title, hidden KB/resource detail, raw provider response, secret-like user input 원문은 포함하지 않는다.

## E2E Demo

1. Workflow Editor를 연다.
2. 우측 하단 Agent Builder launcher를 클릭한다.
3. "사내 휴가 정책을 바탕으로 직원 질문에 답하는 workflow를 만들어줘"라고 입력한다.
4. 권한 확인된 KB 후보가 있으면 후보 수와 score 차이에 관계없이 선택 질문과 후보 목록이 표시된다.
5. 사용자가 KB 후보를 0개, 1개 또는 여러 개 선택한 상태로 다시 제출한다.
6. Agent Builder가 `[입력] -> [Knowledge Base-backed LLM] -> [응답]` draft preview를 생성한다.
7. Validation을 통과한 draft에만 `도안 생성 미리보기` action이 표시된다.
8. 사용자가 `도안 생성 미리보기`를 선택하면 Workflow Editor가 Preview Mode로 전환된다.
9. Preview Mode에서 draft graph가 읽기 전용으로 표시되고, 사용자는 node를 클릭해 Node Detail Panel에서 내부 설정을 확인한다.
10. 사용자가 `적용 및 저장`을 선택하면 backend가 draft metadata, 권한, stale, validation을 재확인한다.
11. 재확인을 통과하면 저장 전에 자동 레이아웃 최적화가 적용되고, apply/save audit 기록까지 성공하면 최적화된 node position이 포함된 workflow graph가 저장 성공으로 완료되며 audit-safe apply/save success event가 기록된다.
12. Preview Mode가 종료되고 editor는 저장된 최신 workflow graph를 표시한다.
13. 이 시점에도 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경은 발생하지 않는다.

## Security And Privacy Tests

- Secret-like input은 prompt, response, trace, audit, preview에 원문으로 남지 않는다.
- Raw provider response는 Agent Builder 응답에 포함되지 않는다.
- Raw KB document/chunk content는 draft generation 응답에 포함되지 않는다.
- Hidden KB 이름, raw source path/url/title, exact denied count는 사용자에게 표시되지 않는다.
- Scope 밖 workflow/app은 존재 추론을 피하는 응답으로 처리된다.
