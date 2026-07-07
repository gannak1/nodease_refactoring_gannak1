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
| `client_graph_snapshot` | 현재 canvas graph의 client snapshot 또는 hash. MVP에서는 unsaved editor graph를 draft base로 신뢰하지 않고 dirty/stale 감지와 차단 안내에만 사용한다. |
| `conversation_context_id` | 이어지는 clarification context |

## Message Response

| Field | Description |
| --- | --- |
| `request_id` | agent request id |
| `status` | `draft_ready`, `clarification_required`, `validation_failed`, `unsupported`, `configuration_required`, `failed`, `canceled` |
| `structured_request` | 자연어 요청을 안전하게 구조화한 결과 |
| `clarification_questions` | 사용자 확인이 필요한 질문 |
| `draft_preview` | 생성 또는 변경될 workflow draft preview |
| `validation_result` | validation outcome과 user-safe reason |
| `preview_prompt` | validation을 통과한 draft에만 표시되는 `도안 보기` action |
| `warnings` | user-safe warning |

`structured_request`는 raw secret, raw provider response, raw KB content, hidden KB/source information을 포함하지 않는다.

## StructuredRequest Fields

| Field | Description |
| --- | --- |
| `request_type` | `new_workflow`, `modify_workflow`, `clarification`, `unsupported`, `validation_failure` |
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
| `node_purpose` | 해당 LLM step의 지식 사용 목적 |
| `knowledge_requirement` | `requirement_id`, `query_topics`, `expected_evidence_type`, `required` |
| `pending_resolution_ref` | `resolution_id`, `slot_type=knowledge_base`, `slot_key`, `blocking` |
| `candidate_scope` | `auto_collection` 또는 `explicit_kb` |
| `authorized_safe_candidate_set` | Knowledge side의 `KnowledgeCandidateResolver`가 만든 권한 확인된 safe 후보 집합. Client body나 `StructuredRequestBuilder` 입력에서 오지 않음 |
| `constraints` | max recommendations, high risk domain, query rewrite policy |

Actor, organization, workflow/app scope는 request body가 아니라 server-resolved context에서 전달한다. Adapter는 `knowledge_requirement`와 `pending_resolution_ref`로 "무엇을 찾아야 하는지"를 알고, `authorized_safe_candidate_set`으로 "어디에서 찾을 수 있는지"를 제한한다.

### Adapter Output

| Field | Description |
| --- | --- |
| `status` | `recommended`, `clarification_required`, `no_candidate`, `unavailable` |
| `resolution_id` | 해결 대상 pending resolution |
| `requirement_id` | 해결 대상 knowledge requirement |
| `recommendations` | safe KB recommendation 목록 |
| `clarification_options` | safe candidate selection options |
| `user_safe_warning` | partial access, runtime availability 등 사용자 표시 경고 |
| `fallback_reason` | unavailable 또는 no candidate 이유 |

Recommendation item은 `candidate_type=knowledge_base`를 사용한다. `candidate_id`는 raw source id, raw source path, raw source URL, raw document title이 아니라 server-issued safe handle이다. Agent Builder가 draft를 생성하거나 apply/save를 수행할 때 backend가 이 handle을 권한 확인된 runtime Knowledge Base reference로 다시 해석한다. Collection은 `source_collection_summary`로만 반환한다.

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
| `safety_notices` | 저장 전 실행/Knowledge Base retrieval/Slack 전송/credential 사용 없음 등 안내 |

`preview_graph`와 `node_detail_previews`에는 credential 원문, raw KB content, raw source path/url/title, hidden resource detail이 포함되지 않는다. Client는 `preview_graph`를 actual editor graph에 merge하지 않고 Preview Mode 전용 state로 렌더링한다.

## Draft Apply And Save

Apply request는 모든 scope 정보를 client가 다시 보내는 구조가 아니다. Server는 `draft_id`로 원 draft metadata를 조회한다.

Request:

| Field | Description |
| --- | --- |
| `action` | `apply_and_save` 또는 `cancel` |
| `client_preview_graph_hash` | 사용자가 확인한 preview graph hash |
| `client_latest_graph_hash` | editor가 알고 있는 최신 graph hash |
| `client_workflow_version` | editor가 알고 있는 workflow version. stale hint로만 사용하며 권한/scope 판단에 사용하지 않음 |
| `client_workflow_updated_at` | editor가 알고 있는 workflow updated_at. stale hint로만 사용하며 권한/scope 판단에 사용하지 않음 |

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
| `stale_state` | stale 여부 |
| `permission_recheck_outcome` | 권한 재확인 결과 |
| `validation_state` | validation 재확인 결과 |
| `audit_recorded` | apply/save audit 기록 여부 |
| `notices` | user-safe 한국어 안내 |

`apply_and_save`는 workflow graph 저장까지 수행할 수 있지만 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 수행하지 않는다. `cancel`은 preview graph를 저장하지 않고 draft apply audit에 취소 outcome만 남길 수 있다.

Stale check는 서버가 원 draft metadata의 `base_graph_hash`와 workflow version 또는 updated_at을 최신 workflow graph/context와 비교해 수행한다. Client가 보낸 graph hash, version, updated_at은 stale hint와 사용자 안내에만 사용하며 권한, scope, organization 판단을 대체하지 않는다.

저장 성공 시 client는 Preview Mode를 종료하고 저장된 최신 workflow graph를 표시한다. 저장 차단 또는 실패 시 client는 Preview Mode를 유지하고 actual editor graph를 변경하지 않는다.

## Apply/Save Audit Events

| Event | Meaning |
| --- | --- |
| `DraftPreviewGenerated` | validation을 통과한 draft preview 생성 |
| `DraftPreviewOpened` | 사용자가 `도안 보기`로 Preview Mode 진입 |
| `DraftApplySaveRequested` | 사용자가 `적용 및 저장` 요청 |
| `DraftApplySaveBlocked` | metadata, permission, stale, validation, unsaved change 등으로 저장 차단 |
| `DraftApplySaveSucceeded` | workflow graph 저장 성공 |
| `DraftApplySaveFailed` | 저장 시도 실패 |
| `DraftApplyCanceled` | 사용자가 preview를 취소 |

Audit-safe metadata에는 `request_id`, `draft_id`, `session_id`, `workflow_id` 또는 새 workflow 생성 scope, `draft_mode`, `base_graph_hash`, `latest_graph_hash`, `preview_graph_hash`, workflow version 또는 updated_at, `block_reason`, `permission_recheck_outcome`, `stale_state`, `validation_state`, `saved_workflow_id`, timestamp를 포함할 수 있다.

Audit metadata에는 credential 원문, raw KB content, raw source path/url/title, hidden KB/resource detail, raw provider response, secret-like user input 원문을 포함하지 않는다.

## Error Codes

| Code | Meaning |
| --- | --- |
| `ACTIVE_ORGANIZATION_REQUIRED` | active organization context가 없음 |
| `WORKFLOW_PERMISSION_REQUIRED` | 기존 workflow read/write 권한 부족 |
| `APP_CREATE_PERMISSION_REQUIRED` | 새 workflow 생성 scope 권한 부족 |
| `DRAFT_VALIDATION_FAILED` | draft validation 실패 |
| `KB_CANDIDATE_UNAVAILABLE` | 권한 확인된 KB 후보 없음 |
| `KB_CANDIDATE_AMBIGUOUS` | KB 후보가 여러 개이며 자동 선택 불가 |
| `DRAFT_METADATA_NOT_FOUND` | apply 대상 draft metadata 없음 |
| `DRAFT_METADATA_EXPIRED` | apply 대상 draft metadata가 만료됨 |
| `DRAFT_STALE` | 최신 graph/context와 draft base가 맞지 않음 |
| `SAVE_FAILED` | backend 저장 시도 실패 |
| `ORGANIZATION_CONTEXT_MISMATCH` | draft 생성 시 active organization과 apply 시 active organization이 다름 |
| `UNSAVED_EDITOR_CHANGES` | 저장되지 않은 editor 변경이 있어 MVP 정책상 draft 생성, Preview Mode, 또는 apply/save를 진행할 수 없음 |
