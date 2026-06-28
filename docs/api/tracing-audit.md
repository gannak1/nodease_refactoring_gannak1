# Tracing 및 Audit API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: [ADR-202606271559-audit-log-rag-trace-storage](../decisions/ADR-202606271559-audit-log-rag-trace-storage.md)

## 범위

Workflow run trace, span, payload, trace policy, retention purge, audit log 조회 계약을 정의한다.

## Trace 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/traces` | query | `TraceListResponse` | trace/audit `read` |
| Implemented | `GET` | `/api/v1/traces/{trace_id}` | 없음 | `TraceDetailSchema` | trace/audit `read` |
| Implemented | `GET` | `/api/v1/traces/{trace_id}/spans` | 없음 | `TraceSpanSchema[]` | trace/audit `read` |
| Implemented | `GET` | `/api/v1/traces/{trace_id}/payloads` | query | `TracePayloadSchema[]` | trace/audit `read` |
| Implemented | `GET` | `/api/v1/traces/{trace_id}/payloads/{payload_id}` | query | `TracePayloadSchema` | `view_raw` if raw |
| Implemented | `POST` | `/api/v1/tracing/retention/purge` | `RetentionPurgeRequest` | `RetentionPurgeResponse` | system admin |
| Implemented | `GET` | `/api/v1/tracing/policies/redaction` | query | `TracePolicyResponse` | system admin |
| Implemented | `PATCH` | `/api/v1/tracing/policies/redaction` | `TraceRedactionPolicyPatch` | `TracePolicyResponse` | system admin |
| Implemented | `GET` | `/api/v1/tracing/policies/retention` | query | `TracePolicyResponse` | system admin |
| Implemented | `PATCH` | `/api/v1/tracing/policies/retention` | `TraceRetentionPolicyPatch` | `TracePolicyResponse` | system admin |
| Implemented | `GET` | `/api/v1/tracing/policies/visibility` | query | `TracePolicyResponse` | system admin |
| Implemented | `PATCH` | `/api/v1/tracing/policies/visibility` | `TraceVisibilityPolicyPatch` | `TracePolicyResponse` | system admin |

## Audit 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/users/me/audit-logs` | pagination query | `AuditLogListResponse` | own audit read |
| Planned | `GET` | `/api/v1/audit/logs` | filter query | `AuditLogListResponse` | audit `read` |

`GET /api/v1/audit/logs`의 MVP 2 필터는 `start_at`, `end_at`, `actor_id`, `action`, `target_type`, `target_id`, `workflow_id`, `run_id`, `node_id`, `deployment_id`, `policy_result`, `status`를 지원한다. `action`은 `permission.*`, `policy.*`, `organization.*`, `rag.retrieve`, `rag.reindex`, `deployment.*`, `recommendation.*` 같은 canonical `audit_logs.action` 값을 사용한다.

MVP 2-0 이후 audit 조회도 active organization membership을 선검증한다. MVP 2의 audit search는 `team_audit_permissions` 중심으로 시작할 수 있지만, MVP 3에서는 `user_audit_permissions` direct grant까지 함께 평가한다. Invited, suspended, removed, non-member user는 audit permission row가 있어도 audit log와 trace payload 조회가 차단된다. Removed member의 과거 실행/audit row 자체는 삭제하지 않고, 조회 scope에서만 제외하거나 audit 권한이 있을 때 inactive member 집계로 구분한다.

## LLM Trace 엔드포인트

MVP 1에서 run/node 기준 LLM usage는 별도 LLM trace endpoint로 조회한다. 기존 run detail 응답에는 전체 trace row를 기본 포함하지 않는다.

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/runs/{run_id}/llm-traces` | `node_id?`, `limit?`, `offset?` query | `LLMTraceListResponse` | workflow `read` |

기본 정렬은 `created_at ASC`, `id ASC`이다. `limit` 기본값은 `100`, 최대값은 `500`이고 `offset` 기본값은 `0`이다. `run_id`가 path의 `workflow_id`에 속하지 않으면 `404`로 응답한다.

`LLMTraceListResponse.items`는 다음 whitelist field만 포함한다.

- `id`
- `workflow_id`
- `workflow_run_id`
- `node_id`
- `model_id`
- `model_name`
- `provider`
- `credential_id`
- `prompt_tokens`
- `completion_tokens`
- `total_tokens`
- `total_cost`
- `latency_ms`
- `status`
- `created_at`

API key, credential config, raw prompt, raw completion, raw request/response body, Authorization/Cookie header는 반환하지 않는다.

## Raw Payload 규칙

- raw payload는 `raw_auditor` 또는 `manager` 수준 권한과 trace visibility policy가 모두 허용해야 반환한다.
- `raw_auditor` 또는 audit `manager` 권한은 `team_audit_permissions`와 `user_audit_permissions`의 effective permission으로 계산한다.
- active organization membership이 없으면 raw trace 조회는 fail-closed 처리한다.
- raw payload 접근 시도는 `trace_payload_access_events`에 남긴다.
- secret, token, credential 원문은 audit metadata에 저장하지 않는다.
