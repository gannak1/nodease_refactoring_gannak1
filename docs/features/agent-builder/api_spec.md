# Agent Builder API Spec

Status: Draft

## API Boundary

Agent Builder API는 workflow draft 생성, clarification, validation, draft preview, Preview Mode, 그리고 사용자가 `적용 및 저장`을 선택한 draft의 workflow graph 저장을 지원한다. Preview apply/save 경계는 [ADR-0019](../../decisions/ADR-0019-agent-builder-preview-apply-save-boundary.md)를 따른다. 이 API는 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 수행하지 않는다.

모든 endpoint는 인증 사용자와 `X-Organization-Id` 기반 active organization membership을 먼저 검증한다. Request body의 `organization_id`는 권한 또는 scope 판단에 사용하지 않는다.

## Endpoints

| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/api/v1/agent-builder/sessions` | Workflow Editor 안 Agent Builder chat session 생성 또는 복구 |
| `GET` | `/api/v1/agent-builder/sessions/{session_id}` | 최근 메시지, pending request, draft preview 상태 조회 |
| `POST` | `/api/v1/agent-builder/sessions/{session_id}/messages` | 사용자 자연어 요청 제출 |
| `POST` | `/api/v1/agent-builder/requests/{request_id}/cancel` | pending 또는 processing request 취소 |
| `POST` | `/api/v1/agent-builder/drafts/{draft_id}/preview-opened` | 사용자가 `도안 보기`로 Preview Mode에 진입했음을 audit-safe event로 기록 |
| `POST` | `/api/v1/agent-builder/drafts/{draft_id}/apply` | 사용자가 Preview Mode에서 확인한 draft를 재검사 후 workflow graph로 저장 |

`session_id`는 server-issued identifier다. Server는 session을 인증 사용자, active organization, workflow/app scope, agent panel lifecycle에 묶어 관리한다. Client-generated session id는 권한, scope, organization, audit 판단에 사용하지 않는다.

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

MVP message request는 raw editor graph snapshot을 받지 않는다. Client는 선택된 node/edge hint만 보낼 수 있으며, unsaved editor graph를 draft base로 신뢰하지 않는다. Apply/save stale guard에 필요한 graph 비교는 apply request의 semantic graph hash로만 수행한다. Request body에 `client_graph_snapshot` 또는 동등한 raw graph payload가 포함되면 서버는 이를 권한/scope 판단이나 draft base로 사용하지 않고 거부해야 한다.

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
| `preview_prompt` | validation을 통과한 draft에만 표시되는 `도안 보기` action |
| `warnings` | user-safe warning |

`structured_request`는 raw secret, raw provider response, raw KB content, hidden KB/source information을 포함하지 않는다.

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
| `clarification_options` | safe candidate selection options. `status=clarification_required`에서 KB 후보가 여러 개이거나 score가 근접하면 비어 있으면 안 되며, 사용자가 어떤 KB를 선택할지 판단할 수 있는 safe label, candidate safe handle, confidence, score, reason category를 포함 |
| `user_safe_warning` | partial access, runtime availability 등 사용자 표시 경고 |
| `fallback_reason` | `adapter_unavailable`, `no_candidate` 같은 safe reason code |

`status=no_candidate`는 adapter가 정상 동작했지만 권한 확인된 safe 후보 집합 안에서 매칭되는 KB를 찾지 못한 상태다. Agent Builder는 이 상태를 권한 확장이나 hidden resource 노출로 처리하지 않고, 한국어 경고와 함께 Knowledge Base binding이 비어 있는 LLM node draft를 생성할 수 있다.

Adapter가 unavailable이지만 권한 확인된 safe 후보 선택지를 제공할 수 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options`를 반환한다. Safe 후보 선택지도 제공할 수 없으면 `status=unavailable`과 safe `fallback_reason`을 반환하고, Agent Builder는 validation failure 또는 사용자 안내로 닫는다.

후보 여러 개 또는 score 근접으로 자동 선택하지 않는 `clarification_required` 응답은 질문만 반환하지 않는다. Agent Builder message response는 Adapter의 safe `clarification_options`를 함께 반환하고, client는 후보명, confidence, score, reason category를 표시해야 한다. 이 선택지는 raw source id/path/url/title, raw document/chunk content, hidden/denied resource detail을 포함하지 않는다.

Recommendation item은 `candidate_type=knowledge_base`를 사용한다. `candidate_id`는 raw source id, raw source path, raw source URL, raw document title이 아니라 server-issued safe handle이다. Agent Builder draft metadata는 safe handle과 structured request safe context만 보존하고 runtime KB id mapping을 저장하지 않는다. Backend는 apply/save 직전에 이 handle을 권한 확인된 runtime Knowledge Base reference로 다시 해석한다. Collection은 `source_collection_summary`로만 반환한다.

Recommendation item은 다음 판단 필드를 포함해야 한다.

| Field | Description |
| --- | --- |
| `score` | 후보 ranking에 사용한 normalized score. Raw retrieval score나 provider raw score가 아니라 Adapter가 노출 가능한 값으로 정규화한 점수 |
| `confidence` | `high`, `medium`, `low` 중 하나. 후보 1개 high confidence 자동 해결과 사용자 선택 clarification을 구분하는 기준 |
| `reason_category` | 추천 근거의 safe category. 예: topic keyword match, metadata match, collection context match |
| `threshold_result` | `high_confidence`, `close_score`, `below_threshold` 등 자동 해결, clarification, failure 분기를 설명하는 safe 결과 |

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
| `safety_notices` | draft preview와 apply/save 전후 side effect 경계 안내. workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경 없음 등 |

`preview_graph`와 `node_detail_previews`에는 credential 원문, raw KB content, raw source path/url/title, hidden resource detail이 포함되지 않는다. Client는 `preview_graph`를 actual editor graph에 merge하지 않고 Preview Mode 전용 state로 렌더링한다.

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
| `audit_recorded` | apply/save audit 기록 여부. `outcome=saved`에서는 반드시 `true`여야 하며, 저장 성공과 audit 기록 성공은 같은 완료 조건으로 취급한다. 저장 시도 후 audit 기록이 실패하면 `outcome=failed`, `failure_reason=SAVE_FAILED` 또는 동등한 safe failure로 반환한다. |
| `notices` | user-safe 한국어 안내 |

`apply_and_save`는 workflow graph 저장까지 수행할 수 있지만 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 수행하지 않는다. `outcome=saved`는 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 응답은 허용하지 않는다. 저장 성공으로 응답하기 전 apply/save audit event는 canonical audit store에 기록되었거나, workflow graph 저장과 같은 transaction 또는 동등한 내구성 경계의 outbox/durable queue에 enqueue되어야 한다. 저장 시도 또는 저장 성공 audit 기록이 실패하면 safe failure로 처리하고 Preview Mode를 유지한다. `cancel`은 preview graph를 저장하지 않고 draft apply audit에 취소 outcome만 남길 수 있다.

Stale check는 서버가 원 draft metadata의 `base_graph_hash`와 workflow version 또는 updated_at을 최신 workflow graph/context와 비교해 수행한다. Client가 보낸 graph hash, version, updated_at은 stale hint와 사용자 안내에만 사용하며 권한, scope, organization 판단을 대체하지 않는다.

저장 성공 시 client는 Preview Mode를 종료하고 저장된 최신 workflow graph를 표시한다. Client는 저장 성공 응답만으로 local `previewGraph`를 actual editor graph로 승격하지 않고, 저장된 workflow id를 기준으로 서버의 최신 workflow graph를 다시 조회하거나 동등한 서버 반환 graph로 reconcile한 뒤 표시해야 한다. 저장 차단 또는 실패 시 client는 Preview Mode를 유지하고 actual editor graph를 변경하지 않는다.

## Apply/Save Audit Events

| Event | Meaning |
| --- | --- |
| `DraftPreviewGenerated` | validation을 통과한 draft preview 생성 |
| `DraftPreviewOpened` | 사용자가 `도안 보기`로 Preview Mode 진입 |
| `DraftPreviewBlocked` | preview-opened audit 전 draft 상태, 만료, validation, 또는 scope 재확인 실패로 Preview Mode 진입 차단 |
| `DraftApplySaveRequested` | 사용자가 `적용 및 저장` 요청 |
| `DraftApplySaveBlocked` | metadata, permission, stale, validation, unsaved change 등으로 저장 차단 |
| `DraftApplySaveSucceeded` | workflow graph 저장과 apply/save audit 기록 성공 |
| `DraftApplySaveFailed` | 저장 시도 실패 |
| `DraftApplyCanceled` | 사용자가 preview를 취소 |

Audit-safe metadata에는 `request_id`, `draft_id`, `apply_id`, `session_id`, `workflow_id` 또는 새 workflow 생성 scope, `draft_mode`, `base_graph_hash`, `latest_graph_hash`, `preview_graph_hash`, workflow version 또는 updated_at, apply/save outcome, `block_reason`, `failure_reason`, `permission_recheck_outcome`, `stale_state`, `validation_state`, `saved_workflow_id`, timestamp를 포함할 수 있다.

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
| `DRAFT_NOT_APPLICABLE` | 이미 취소, 저장, 만료, 또는 terminal 처리된 draft라 다시 적용할 수 없음 |
| `DRAFT_STALE` | 최신 graph/context와 draft base가 맞지 않음 |
| `UNSAVED_EDITOR_CHANGES` | 현재 editor에 저장되지 않은 변경이 있어 apply/save 차단 |
| `SAVE_FAILED` | backend 저장 시도 또는 apply/save audit 기록 실패 |
| `ORGANIZATION_CONTEXT_MISMATCH` | draft 생성 시 active organization과 apply 시 active organization이 다름 |
| `UNSAVED_EDITOR_CHANGES` | 저장되지 않은 editor 변경이 있어 MVP 정책상 draft 생성, Preview Mode, 또는 apply/save를 진행할 수 없음 |
