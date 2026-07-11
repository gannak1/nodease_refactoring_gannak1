# Agent Builder API Spec

Status: Draft

## API Boundary

Agent Builder API는 workflow draft 생성, clarification, validation, draft preview, Preview Mode, 그리고 사용자가 `적용 및 저장`을 선택한 draft의 workflow graph 저장을 지원한다. Preview apply/save 경계는 [ADR-0019](../../decisions/ADR-0019-agent-builder-preview-apply-save-boundary.md)를 따르고 node/capability allowlist는 [ADR-0024](../../decisions/ADR-0024-agent-builder-node-capability-catalog.md)을 따른다. 내부 intent model 선택은 [ADR-0025](../../decisions/ADR-0025-agent-builder-intent-model-selection.md)를 따른다. 이 API는 workflow 실행, Knowledge Base retrieval, Slack/GitHub/HTTP/Mail 전송 또는 조회, workflow node credential 사용/변경, 외부 시스템 변경을 수행하지 않는다. AB-FR-003의 자연어 구조화를 위한 permission-aware 내부 planner 호출은 workflow node credential 실행과 구분한다.

모든 endpoint는 인증 사용자와 `X-Organization-Id` 기반 active organization membership을 먼저 검증한다. Request body의 `organization_id`는 권한 또는 scope 판단에 사용하지 않는다.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/api/v1/agent-builder/model-options` | Active organization과 credential `use` 권한 기준 내부 intent planner model option group 조회 |
| `POST` | `/api/v1/agent-builder/sessions` | Workflow Editor 안 Agent Builder chat session 생성 또는 복구 |
| `GET` | `/api/v1/agent-builder/sessions/{session_id}` | 최근 메시지, pending request, draft preview 상태 조회 |
| `POST` | `/api/v1/agent-builder/sessions/{session_id}/messages` | 사용자 자연어 요청 제출 |
| `POST` | `/api/v1/agent-builder/requests/{request_id}/cancel` | pending 또는 processing request 취소 |
| `POST` | `/api/v1/agent-builder/drafts/{draft_id}/preview-opened` | 사용자가 `도안 생성 미리보기`로 Preview Mode에 진입했음을 audit-safe event로 기록 |
| `POST` | `/api/v1/agent-builder/drafts/{draft_id}/apply` | 사용자가 Preview Mode에서 확인한 draft를 재검사 후 workflow graph로 저장 |

`session_id`는 server-issued identifier다. Server는 session을 인증 사용자, active organization, workflow/app scope, agent panel lifecycle에 묶어 관리한다. Client-generated session id는 권한, scope, organization, audit 판단에 사용하지 않는다.

`draft_mode=new_workflow`의 `apply_and_save`가 성공하면 server는 workflow graph 저장과 같은 transaction에서 해당 draft의 session scope를 새 `saved_workflow_id`와 app으로 재결합한다. Client는 응답의 `saved_workflow_id` route로 이동할 때 기존 server-issued session id만 새 workflow storage key로 이전하며, 새 id를 만들거나 다른 scope의 session을 재사용하지 않는다.

Session 조회/복구 response의 최근 메시지는 사용자 turn과 assistant response를 함께 복구할 수 있어야 한다. 사용자 turn은 redaction을 거친 `message_summary` 또는 동등한 safe content만 포함하고, assistant turn은 기존 Agent Builder message response와 같은 safe response payload를 포함한다. Legacy response-only message가 남아 있더라도 client는 이를 assistant turn으로 해석할 수 있지만, 신규 저장은 사용자 redacted turn과 assistant turn을 구분해야 한다. Top-level `draft_preview`는 해당 session의 최신 request와 `request_id`가 일치하는 ready draft에 대해서만 반환한다. 최신 request가 `failed`, `unsupported`, `validation_failed`이거나 과거 request의 draft만 남아 있으면 이전 preview를 현재 응답처럼 복구하지 않는다.

## Message Request

Client request body는 organization override를 포함하지 않는다.

| Field | Description |
| --- | --- |
| `message` | 사용자 자연어 요청 |
| `workflow_id` | 기존 workflow 수정 요청일 때 현재 workflow id |
| `app_id` | 새 workflow draft 생성 scope |
| `selected_node_id` | 현재 선택된 canvas node |
| `selected_edge_id` | 현재 선택된 canvas edge. "이 연결 사이에", "여기 사이에"처럼 edge 선택 문맥일 때 target resolution hint로만 사용하며 권한/scope 판단에 사용하지 않음 |
| `conversation_context_id` | 이어지는 clarification context |
| `selected_knowledge_candidate` | KB 후보 clarification에 대한 단일 사용자 선택. 호환용 필드이며 `candidate_id`, 선택적 `resolution_id`, 선택적 `requirement_id`만 포함하고 raw KB id, raw source id/path/url/title은 포함하지 않음 |
| `selected_knowledge_candidates` | KB 후보 clarification에 대한 사용자 선택 목록. 0개, 1개, 여러 개 선택을 표현하며 빈 배열은 표시된 후보를 선택하지 않고 Knowledge Base binding 없이 draft 생성을 계속한다는 뜻이다 |
| `intent_model_selection` | 내부 intent planner가 사용할 명시적 `credential_id`, `model_id` 쌍. Raw credential 또는 provider config를 포함하지 않음 |

`GET /model-options`는 provider group을 `openai`, `anthropic`, `google`, `llamaparse` 순서로 반환한다. 각 `options` item은 safe model schema, safe credential option, relation priority만 포함한다. Model은 provider별 최신 세대 우선, 같은 세대에서는 성능 tier가 높은 순으로 정렬한다. 후보가 없는 chat provider는 `no_authorized_model`, LlamaParse는 `chat_model_not_supported`를 반환한다.

이 endpoint의 순서는 내부 intent planner 선택 UI용이다. Draft generator가 LLM node를 만들 때는 같은 권한 확인 후보 집합에서 `openai`, `anthropic`, `google` provider 순서와 provider별 최신 세대, 같은 세대 `mini`, 이후 낮은 성능 tier 순서를 사용해 기본 model을 추천한다. Preview/draft graph에는 추천된 safe model id만 포함하고 credential id/config는 포함하지 않는다. 후보가 없으면 `model_id=null`, `configuration_state=unresolved`와 model 설정 필요 `configuration_issues`를 반환하며, 고정 환경변수 fallback으로 바꾸거나 draft 전체를 실패시키지 않는다.

Message submit은 `intent_model_selection`을 session, draft metadata, workflow graph 또는 별도 model-selection DB column에 저장하지 않는다. Server는 요청마다 credential organization/validity/`use` permission과 model active chat type/provider/verified relation을 다시 검사한다. 선택이 없거나 유효하지 않으면 hidden fallback model을 자동 선택하지 않는다. Permission/runtime 차단 audit에는 safe credential/model ID, reason, runtime surface를 기록할 수 있지만 credential 원문과 raw provider response는 포함하지 않는다.

MVP message request는 raw editor graph snapshot을 받지 않는다. Client는 선택된 node/edge hint만 보낼 수 있으며, unsaved editor graph를 draft base로 신뢰하지 않는다. Apply/save stale guard에 필요한 graph 비교는 apply request의 semantic graph hash로만 수행한다. Request body에 `client_graph_snapshot` 또는 동등한 raw graph payload가 포함되면 서버는 이를 권한/scope 판단이나 draft base로 사용하지 않고 거부해야 한다.

`selected_knowledge_candidate`와 `selected_knowledge_candidates`는 새 권한 판단 입력이 아니다. Server는 같은 authenticated user, active organization, workflow/app scope, agent panel session 안의 직전 미해결 KB 후보 clarification response만 조회하고, 선택된 각 `candidate_id`가 해당 response의 `clarification_options`에 있던 server-issued safe handle인지 확인해야 한다. `resolution_id` 또는 `requirement_id`가 함께 오면 원 clarification option의 값과 일치해야 한다. 이미 draft 생성, validation failure, 취소 또는 다른 후속 응답으로 해결된 과거 clarification을 재사용한 선택은 validation failure 또는 재선택 질문으로 닫고, raw KB id fallback으로 해석하지 않는다.

KB 후보 clarification의 `clarification_options`는 실제 선택 가능한 Knowledge Base 후보만 표시한다. Client가 현재 미해결 후보를 선택하지 않고 같은 요청을 다시 제출하면 `selected_knowledge_candidates=[]`를 보내고, Backend는 직전 clarification context가 유효한 경우에만 KB binding 없이 draft를 생성한다. 빈 선택은 raw KB id가 아니며 runtime KB reference로 materialize되지 않는다.

## Message Response

| Field | Description |
| --- | --- |
| `request_id` | agent request id |
| `status` | `draft_ready`, `clarification_required`, `validation_failed`, `unsupported`, `configuration_required`, `failed`, `canceled` |
| `structured_request` | 자연어 요청을 안전하게 구조화한 결과 |
| `clarification_questions` | 사용자 확인이 필요한 질문 |
| `clarification_options` | 사용자가 선택해야 하는 safe 후보 목록. KB 후보 clarification에서는 safe label, candidate safe handle, confidence, score, reason category를 포함 |
| `draft_preview` | 생성 또는 변경될 workflow draft preview |
| `validation_result` | validation outcome과 user-safe reason |
| `preview_prompt` | validation을 통과한 draft에만 표시되는 `도안 생성 미리보기` action |
| `warnings` | user-safe warning |

`structured_request`는 raw secret, raw provider response, raw KB content, hidden KB/source information을 포함하지 않는다.

Intent LLM request에는 backend가 현재 권한과 retrieval-visible 상태를 확인한 상위 20개 KB candidate의 `candidate_handle`, `safe_label`, `safe_topics`, `safe_description`, `runtime_availability`, `relevance_score`만 내부 safe context로 포함할 수 있다. 이 context는 public client request field가 아니며 raw KB UUID, collection/source/document/chunk identity를 포함하지 않는다.

일반 message submit은 server-side `LLMIntentExtractor`의 schema-validated JSON 결과를
semantic invariant로 재검증하고 `StructuredRequestBuilder`가 결정론적으로 정규화한 뒤 처리한다. Schema-valid 결과가 request type, draft mode, workflow context, 신규 capability, target, placement 계약과 모순되면 safe validation code만으로 정확히 한 번 repair를 요청한다. 두 번째 결과도 유효하지 않으면 `INTENT_EXTRACTION_FAILED`로 종료한다. 사용할 수 있는
permission-aware LLM runtime이 없으면 `status=configuration_required`와
`INTENT_MODEL_ROUTE_REQUIRED`를 반환한다. Provider 호출 또는 JSON/schema validation이
실패하면 `status=failed`와 `INTENT_EXTRACTION_FAILED`를 반환하고 partial draft를 저장하지
않으며 이 오류에는 repair를 시도하지 않는다. 모든 실패 응답과 repair prompt는 credential 원문과 raw provider response를 포함하지 않는다. KB 후보
clarification에 대한 선택 제출은 직전 저장된 `structured_request`를 재사용하므로 동일 사용자
요청을 다시 LLM으로 구조화하지 않는다.

내부 intent extraction은 명시적 GitHub Pull Request 요청을 `integration_actions[]`의 provider=`github`, resource=`pull_request`, operation=`read|comment|create`로 분류한다. `read`와 `comment`는 각각 catalog의 `github_pr_read`, `github_pr_comment`와 일치해야 하며 불일치는 한 번의 safe semantic repair 대상이다. `create`는 의미상 인식하지만 현재 API가 materialize할 실행 capability가 아니므로 `status=unsupported`와 안전한 미지원 사유를 반환한다. 사용자가 GitHub API를 HTTP로 호출하라고 명시하지 않은 한 이 operation을 `http_request`로 대체하지 않는다. `integration_actions`는 내부 planner contract이며 client가 지정하는 권한 또는 node 생성 입력이 아니다.

Redacted request가 GitHub Pull Request를 명시하고 첫 structured result가
GitHub action 없이 `http_request`를 반환하면 server는
`GITHUB_INTEGRATION_ACTION_REQUIRED` safe code로 정확히 한 번 repair한다. Server는
이 과정에서 operation을 만들지 않으며, 두 번째 structured result도 provider,
resource, operation과 capability 계약을 충족하지 못하면
`INTENT_EXTRACTION_FAILED`로 종료한다.

## StructuredRequest Fields

| Field | Description |
| --- | --- |
| `request_type` | `new_workflow`, `modify_workflow`, `clarification`, `unsupported`, `validation_failure` |
| `draft_mode` | `new_workflow`, `modify_workflow`, `replace_workflow`. 전체 교체는 `request_type=modify_workflow`, `draft_mode=replace_workflow`로 표현 |
| `intent_summary` | redaction-safe intent summary |
| `planned_steps` | draft generation 후보 step 목록 |
| `knowledge_requirements` | KB-backed step이 필요한 지식 요구사항 |
| `required_capabilities` | 필요한 capability 목록 |
| `pending_resolution` | resolver가 해결할 수 있는 unresolved slot |
| `missing_information` | 사용자가 직접 답해야 하는 정보 |
| `unsupported_requests` | 지원하지 않는 요청 |
| `risk_flags` | permission, external action, secret-like input 등 risk |
| `edit_operations` | 기존 workflow 수정 연산 목록. `operation`, `placement`, `step_refs`, `target`을 포함하며 target은 아직 해결되지 않은 자연어/selection reference를 표현 |

`knowledge_requirements[].suggested_candidate_handles`는 Intent LLM이 bounded safe context에서 관련 가능성이 있다고 제안한 opaque handle 목록이다. 자동 선택이나 권한 부여가 아니며, Recommendation Adapter가 현재 후보를 다시 조회하고 사용자가 clarification에서 선택하기 전에는 runtime KB reference로 materialize하지 않는다. Prompt에 없던 handle은 `UNKNOWN_KNOWLEDGE_CANDIDATE_HANDLE` semantic validation code로 거부한다.

`edit_operations[].operation`은 MVP에서 `insert`를 지원한다. `placement`는 `before`,
`after`, `between` 중 하나이며 `step_refs`는 새로 생성할 `planned_steps`만 참조한다.
`target.node_types`와 `target.capabilities`는 기존 graph 후보를 찾기 위한 safe semantic
reference이고, 최종 node/edge id는 server-side `TargetResolver`가 현재 저장된 workflow
graph에서 확정한다. Target 후보가 여러 개이면 response의 `clarification_options`에
`type=workflow_node`, `node_id`, safe label, node type을 반환할 수 있다.

`target.reference_type=selected_edge`는 같은 request의 server-validated `selected_edge_id`가 있고 해당 edge가 server-loaded graph에 존재할 때만 사용할 수 있다. Raw message regex는 이 결정을 대체하지 않는다.

`validation_result.issues[].code`는 catalog connection policy 위반에 대해 `START_NODE_HAS_INCOMING_EDGE`, `TRIGGER_NODE_HAS_INCOMING_EDGE`, `TERMINAL_NODE_HAS_OUTGOING_EDGE`, `INVALID_CONDITION_SOURCE_HANDLE`을 반환할 수 있다. 같은 validator를 preview와 apply/save에서 재사용하며 위반 graph는 저장하지 않는다.

## KB Recommendation Adapter Contract

Adapter는 public client endpoint가 아니라 Agent Builder backend에서 호출하는 Knowledge domain service로 시작한다.

### Adapter Input

| Field | Description |
| --- | --- |
| `intent_summary` | Agent Builder가 만든 안전 요약 |
| `target_step_ref` | KB 추천이 필요한 planned step |
| `node_purpose_summary` | 해당 LLM step의 지식 사용 목적 safe 요약 |
| `safe_workflow_context_summary` | 현재 workflow 목적, 기존 KB 참조, 관련 노드 역할을 요약한 safe context. Raw graph payload나 hidden source 정보는 포함하지 않음 |
| `knowledge_requirement` | `requirement_id`, `query_topics`, `expected_evidence_type`, `required` |
| `safe_query_topics` | Agent Builder가 사용자 요청에서 구조화한 KB 추천용 safe topics. 예: `사내 문서`, `문서 질의`. `웹훅`, `워크플로우`, `챗봇` 같은 action/UI terms는 제외한다 |
| `pending_resolution_ref` | `resolution_id`, `slot_type=knowledge_base`, `slot_key`, `blocking` |
| `mode` | `auto`, `auto_collection`, `explicit_kb`. `auto`는 adapter 내부 편의값이며 resolver 호출 전 bounded mode로 변환. `explicit_kb`는 Agent Builder backend 또는 Knowledge domain 내부 service call처럼 safe handle과 server-resolved context를 이미 통과한 trusted boundary에서만 사용하며, Agent Builder client가 raw KB id로 여는 public request mode가 아니다 |
| `authorized_safe_candidate_set_ref` | Knowledge side의 `KnowledgeCandidateResolver`가 만든 권한 확인된 safe 후보 집합을 가리키는 server-issued reference. Client body나 `StructuredRequestBuilder` 입력에서 오지 않음 |
| `constraints` | max recommendations, high risk domain, query rewrite policy |

Actor, organization, workflow/app scope는 request body가 아니라 server-resolved context에서 전달한다. Adapter는 `knowledge_requirement`와 `pending_resolution_ref`로 "무엇을 찾아야 하는지"를 알고, `authorized_safe_candidate_set_ref`로 "어디에서 찾을 수 있는지"를 제한한다. 같은 backend 내부 service call에서만 full `authorized_safe_candidate_set` 객체를 전달할 수 있으며, HTTP 또는 serialized boundary에서는 full 후보 집합을 request body로 전달하지 않는다.

### Adapter Output

| Field | Description |
| --- | --- |
| `status` | `recommended`, `clarification_required`, `no_candidate`, `unavailable` |
| `resolution_id` | 해결 대상 pending resolution |
| `requirement_id` | 해결 대상 knowledge requirement |
| `recommendations` | safe KB recommendation 목록. 각 item은 score, confidence, reason category, threshold result를 포함 |
| `clarification_options` | safe candidate selection options. `status=clarification_required`에서 권한 확인된 KB 후보가 있으면 비어 있으면 안 되며, 사용자가 어떤 KB를 선택할지 판단할 수 있는 safe label, candidate safe handle, confidence, score, reason category를 포함 |
| `user_safe_warning` | partial access, runtime availability 등 사용자 표시 경고 |
| `fallback_reason` | `adapter_unavailable`, `no_candidate` 같은 safe reason code |

`status=no_candidate`는 adapter가 정상 동작했지만 권한 확인된 safe 후보 집합 안에서 매칭되는 KB를 찾지 못한 상태다. Agent Builder는 이 상태를 권한 확장이나 hidden resource 노출로 처리하지 않고, 한국어 경고와 함께 Knowledge Base binding이 비어 있는 LLM node draft를 생성할 수 있다.

Client가 collection scope를 명시하지 않은 auto mode에서 route-allowed collection 후보가 비어 있으면, Adapter는 같은 active organization 안의 직접 권한 확인된 retrieval-visible KB를 safe candidate set으로 평가할 수 있다. 명시적으로 빈 collection scope를 보낸 경우에는 이 direct fallback을 적용하지 않는다.

권한 확인된 KB가 존재하지만 active ready document version 또는 legacy unversioned retrieval-visible chunk가 없어 아직 LLM node에서 사용할 수 없는 경우, Adapter는 이를 단순 `no_candidate`와 구분할 수 있는 safe warning 또는 fallback reason으로 반환해야 한다. 권장 `fallback_reason`은 `candidate_not_ready` 또는 `indexing_in_progress`이며, 응답은 raw document title/path/url, raw chunk content, hidden/denied resource detail을 포함하지 않는다. Client picker는 이 상태를 selectable ready KB로 취급하지 않지만, 사용자가 업로드한 KB가 아직 인덱싱 중임을 알 수 있게 disabled option 또는 warning으로 표시해야 한다.

Adapter가 unavailable이지만 권한 확인된 safe 후보 선택지를 제공할 수 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options`를 반환한다. Safe 후보 선택지도 제공할 수 없으면 `status=unavailable`과 safe `fallback_reason`을 반환하고, Agent Builder는 validation failure 또는 사용자 안내로 닫는다.

권한 확인된 추천 후보가 있으면 후보가 1개이고 top 후보가 high confidence여도 자동 선택하지 않고 `clarification_required` 응답을 반환한다. Agent Builder message response는 Adapter의 safe `clarification_options`를 최대 20개까지 함께 반환하고, client는 후보명, confidence, score, reason category를 표시해야 한다. 이 선택지는 raw source id/path/url/title, raw document/chunk content, hidden/denied resource detail을 포함하지 않는다.

사용자가 KB 후보를 선택하면 client는 후보 카드에 표시된 safe metadata 전체를 다시 보내지 않고 선택된 safe handle과 선택적 resolution/requirement reference만 보낸다. Backend는 원 clarification option과 같은 session/context 안에서 선택을 검증한 뒤, 해당 candidate handle만 resolved KB pending slot으로 사용한다. Adapter unavailable fallback으로 반환된 safe option도 같은 방식으로 검증해야 하며, 선택 검증 또는 apply/save 직전 materialization에 실패하면 draft 확정 또는 저장으로 이어지면 안 된다.

Recommendation item은 `candidate_type=knowledge_base`를 사용한다. `candidate_id`는 raw source id, raw source path, raw source URL, raw document title이 아니라 server-issued safe handle이다. Agent Builder draft metadata는 safe handle과 structured request safe context만 보존하고 runtime KB id mapping을 저장하지 않는다. Backend는 apply/save 직전에 이 handle을 권한 확인된 runtime Knowledge Base reference로 다시 해석한다. 이 materialization은 현재 recommendation top-N 결과에 다시 의존하지 않고, 권한 확인된 candidate set 안에서 safe handle을 직접 재검증해야 한다. Collection은 `source_collection_summary`로만 반환한다.

Recommendation item은 다음 판단 필드를 포함해야 한다.

| Field | Description |
| --- | --- |
| `score` | 후보 ranking에 사용한 normalized score. Raw retrieval score나 provider raw score가 아니라 Adapter가 노출 가능한 값으로 정규화한 점수 |
| `confidence` | `high`, `medium`, `low` 중 하나. 추천 강도를 표시하지만 Agent Builder는 KB 후보를 자동 선택하지 않고 사용자 선택 clarification을 요구한다 |
| `reason_category` | 추천 근거의 safe category. 예: topic keyword match, metadata match, collection context match |
| `threshold_result` | `high_confidence`, `close_score`, `below_threshold` 등 추천 강도와 warning/failure 분기를 설명하는 safe 결과 |

Agent Builder는 KB 후보가 1개이고 `threshold_result=high_confidence`이거나 `close_score` 이상이어도 pending KB resolution을 자동 해결하지 않는다. 권한 확인된 추천 후보가 있으면 최대 20개의 `clarification_options`를 표시하고, 사용자가 0개, 1개, 여러 개 후보 상태로 다시 제출한 뒤에만 pending KB resolution을 해결한다. 0개 선택은 KB binding 없이 draft 생성을 계속한다.

### Adapter Prohibited Data

Adapter input/output/trace에는 다음을 포함하지 않는다.

- raw natural language 전체
- raw source ACL
- raw source id/path/url/title
- raw document/chunk content
- hidden/denied resource list
- exact hidden/denied count
- credential/token/API key 원문
- provider raw response

## Draft Preview Mode

Draft preview response는 chatbot panel 요약과 Preview Mode 렌더링에 필요한 safe draft graph를 제공한다.

| Field | Description |
| --- | --- |
| `draft_id` | preview 대상 draft |
| `preview_graph` | actual editor graph와 분리해 렌더링할 draft graph |
| `base_graph_hash` | draft 생성 기준 graph hash |
| `base_workflow_version` | draft 생성 기준 workflow version. version을 사용하지 않는 workflow는 생략 가능 |
| `base_workflow_updated_at` | draft 생성 기준 workflow updated_at. version이 없을 때 stale check 기준으로 사용 |
| `draft_mode` | `new_workflow`, `modify_workflow`, `replace_workflow` |
| `node_detail_previews` | Node Detail Panel에 표시할 read-only safe node configuration |
| `validation_result` | preview 표시 기준 validation 결과 |
| `safety_notices` | draft preview와 apply/save 전후 공통 side effect 경계 안내. workflow 실행, Knowledge Base retrieval, Slack/GitHub/HTTP/Mail 외부 호출, workflow node credential 사용/변경, 외부 시스템 변경 없음 등 |
| `configuration_issues` | 미해결 설정이 있는 node별 목록. 각 항목은 `node_id`, `node_type`, 안전한 node 표시명, capability, `missing_parameters[{key,label}]`을 포함하며 같은 type의 node가 여러 개여도 node별로 유지한다. |

`preview_graph`, `node_detail_previews`, `configuration_issues`에는 credential 원문, raw KB content, raw source path/url/title, hidden resource detail이 포함되지 않는다. 공통 side-effect 안내는 `safety_notices`에 한 번만 표시하고, node별 미설정 항목은 문자열 경고를 파싱하지 않고 `configuration_issues`로 렌더링한다. Client는 `preview_graph`를 actual editor graph에 merge하지 않고 Preview Mode 전용 state로 렌더링한다.

## Draft Apply And Save

Apply request는 모든 scope 정보를 client가 다시 보내는 구조가 아니다. Server는 `draft_id`로 원 draft metadata를 조회한다.

Request:

| Field | Description |
| --- | --- |
| `action` | `apply_and_save` 또는 `cancel` |
| `client_preview_graph_hash` | 사용자가 확인한 preview graph의 semantic hash. `apply_and_save`에서는 필수이며, preview graph 자체를 request body로 보내지 않는다. |
| `client_latest_graph_hash` | editor가 알고 있는 최신 actual editor graph의 semantic hash. 기존 workflow 수정 draft에서는 필수이며, raw graph snapshot을 대체하지 않는다. |
| `client_workflow_version` | editor가 알고 있는 workflow version. stale hint로만 사용하며 권한/scope 판단에 사용하지 않음 |
| `client_workflow_updated_at` | editor가 알고 있는 workflow updated_at. stale hint로만 사용하며 권한/scope 판단에 사용하지 않음 |

`client_preview_graph_hash`와 `client_latest_graph_hash`는 node id, node type, semantic node data/config, edge source/target/handle 같은 workflow 의미 값만 기준으로 계산한다. viewport, selection, panel state, preview state, timestamp, dragging/hover/status 같은 UI-only metadata는 hash에 포함하지 않는다. Client crypto/hash 계산을 수행할 수 없으면 raw graph fallback을 보내지 않고 apply/save를 차단해야 한다.

Response:

| Field | Description |
| --- | --- |
| `apply_id` | apply/save attempt 식별자 |
| `outcome` | `saved`, `blocked`, `canceled`, `failed` |
| `saved_workflow_id` | 저장 성공 시 workflow id |
| `latest_graph_hash` | 저장 또는 차단 판단에 사용한 최신 graph hash |
| `latest_workflow_version` | 저장 또는 차단 판단에 사용한 최신 workflow version |
| `latest_workflow_updated_at` | 저장 또는 차단 판단에 사용한 최신 workflow updated_at |
| `block_reason` | 저장 차단 사유 |
| `failure_reason` | `outcome=failed`일 때 저장 시도 실패 사유. `blocked`의 차단 사유와 구분 |
| `stale_state` | stale 여부 |
| `permission_recheck_outcome` | 권한 재확인 결과 |
| `validation_state` | validation 재확인 결과 |
| `layout_optimization_applied` | `outcome=saved`에서 저장 전 자동 레이아웃 최적화가 적용되었는지 여부. 저장된 graph의 node position은 이 결과를 반영해야 한다. |
| `audit_recorded` | apply/save audit 기록 여부. `outcome=saved`에서는 반드시 `true`여야 하며, 저장 성공과 audit 기록 성공은 같은 완료 조건으로 취급한다. 저장 시도 후 audit 기록이 실패하면 `outcome=failed`, `failure_reason=SAVE_FAILED` 또는 동등한 safe failure로 반환한다. |
| `notices` | user-safe 한국어 안내 |

`apply_and_save`는 workflow graph 저장까지 수행할 수 있지만 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경을 수행하지 않는다. 저장으로 이어지는 경우 서버는 workflow graph 저장 전에 기존 Workflow Editor 레이아웃 최적화 UI 버튼과 동등한 자동 레이아웃 최적화를 적용하고, 저장 graph의 node position에 그 결과를 반영해야 한다. `outcome=saved`는 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 응답은 허용하지 않는다. 저장 성공으로 응답하기 전 apply/save audit event는 canonical audit store에 기록되었거나, workflow graph 저장과 같은 transaction 또는 동등한 내구성 경계의 outbox/durable queue에 enqueue되어야 한다. 저장 시도 또는 저장 성공 audit 기록이 실패하면 safe failure로 처리하고 Preview Mode를 유지한다. `cancel`은 preview graph를 저장하지 않고 draft apply audit에 취소 outcome만 남기며, validation을 통과한 ready draft를 terminal 폐기하지 않는다.

Stale check는 서버가 원 draft metadata의 `base_graph_hash`와 workflow version 또는 updated_at을 최신 workflow graph/context와 비교해 수행한다. Client가 보낸 graph hash, version, updated_at은 stale hint와 사용자 안내에만 사용하며 권한, scope, organization 판단을 대체하지 않는다.

저장 성공 시 client는 Preview Mode를 종료하고 저장된 최신 workflow graph를 표시한다. Client는 저장 성공 응답만으로 local `previewGraph`를 actual editor graph로 승격하지 않고, 저장된 workflow id를 기준으로 서버의 최신 workflow graph를 다시 조회하거나 동등한 서버 반환 graph로 reconcile한 뒤 표시해야 한다. 저장 차단 또는 실패 시 client는 Preview Mode를 유지하고 actual editor graph를 변경하지 않는다.

## Apply/Save Audit Events

| Event | Meaning |
| --- | --- |
| `DraftPreviewGenerated` | validation을 통과한 draft preview 생성 |
| `DraftPreviewOpened` | 사용자가 `도안 생성 미리보기`로 Preview Mode 진입 |
| `DraftPreviewBlocked` | preview-opened audit 전 draft 상태, 만료, validation, 또는 scope 재확인 실패로 Preview Mode 진입 차단 |
| `DraftApplySaveRequested` | 사용자가 `적용 및 저장` 요청 |
| `DraftApplySaveBlocked` | metadata, permission, stale, validation, unsaved change 등으로 저장 차단 |
| `DraftApplySaveSucceeded` | workflow graph 저장과 apply/save audit 기록 성공 |
| `DraftApplySaveFailed` | 저장 시도 실패 |
| `DraftApplyCanceled` | 사용자가 preview를 취소 |

Audit-safe metadata에는 `request_id`, `draft_id`, `apply_id`, `session_id`, `workflow_id` 또는 새 workflow 생성 scope, `draft_mode`, `base_graph_hash`, `latest_graph_hash`, `preview_graph_hash`, workflow version 또는 updated_at, apply/save outcome, `block_reason`, `failure_reason`, `permission_recheck_outcome`, `stale_state`, `validation_state`, `layout_optimization_applied`, `saved_workflow_id`, timestamp를 포함할 수 있다.

Audit metadata에는 credential 원문, raw KB content, raw source path/url/title, hidden KB/resource detail, raw provider response, secret-like user input 원문을 포함하지 않는다.

`DraftPreviewOpened` 기록에 실패하면 client는 Preview Mode에 진입하지 않고 사용자에게 재시도 안내를 표시해야 한다. Preview Mode 진입은 preview-opened audit-safe event 기록 성공 이후에만 가능하다.

## Error Codes

| Code | Meaning |
| --- | --- |
| `ACTIVE_ORGANIZATION_REQUIRED` | active organization context가 없음 |
| `WORKFLOW_PERMISSION_REQUIRED` | 기존 workflow read/write 권한 부족 |
| `APP_CREATE_PERMISSION_REQUIRED` | 새 workflow 생성 scope 권한 부족 |
| `DRAFT_VALIDATION_FAILED` | draft validation 실패 |
| `KB_CANDIDATE_UNAVAILABLE` | 권한 확인된 KB 후보 없음 |
| `KB_CANDIDATE_AMBIGUOUS` | KB 후보가 여러 개이며 자동 선택 불가 |
| `KB_PERMISSION_REQUIRED` | draft 생성 이후 KB use 권한, source ACL, runtime availability 재확인 실패 |
| `DRAFT_METADATA_NOT_FOUND` | apply 대상 draft metadata 없음 |
| `DRAFT_METADATA_EXPIRED` | apply 대상 draft metadata가 만료됨 |
| `DRAFT_NOT_APPLICABLE` | 이미 저장, 만료, 또는 terminal 처리된 draft라 다시 적용할 수 없음. Preview 취소 audit만으로 ready draft가 terminal 처리되지는 않음 |
| `DRAFT_STALE` | 최신 graph/context와 draft base가 맞지 않음 |
| `UNSAVED_EDITOR_CHANGES` | 현재 editor에 저장되지 않은 변경이 있어 apply/save 차단 |
| `SAVE_FAILED` | backend 저장 시도 또는 apply/save audit 기록 실패 |
| `ORGANIZATION_CONTEXT_MISMATCH` | draft 생성 시 active organization과 apply 시 active organization이 다름 |
| `UNSAVED_EDITOR_CHANGES` | 저장되지 않은 editor 변경이 있어 MVP 정책상 draft 생성, Preview Mode, 또는 apply/save를 진행할 수 없음 |
