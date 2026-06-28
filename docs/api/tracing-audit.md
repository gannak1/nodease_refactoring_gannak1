# Tracing 및 Audit API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1
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

## LLM Trace 엔드포인트

현재 코드는 run/node 기준 LLM usage 조회를 별도 endpoint로 제공한다. 기존 run detail 응답에 LLM usage 요약을 포함하는 방식은 채택하지 않았다.

| Status | Method | Path | 설명 |
| --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/workflows/{workflow_id}/runs/{run_id}/llm-traces` | 별도 LLM trace endpoint. `node_id`, `limit`, `offset` query를 지원 |

중복 API를 만들지 않는다.

## Raw Payload 규칙

- raw payload는 `raw_auditor` 또는 `manager` 수준 권한과 trace visibility policy가 모두 허용해야 반환한다.
- raw payload 접근 시도는 `trace_payload_access_events`에 남긴다.
- secret, token, credential 원문은 audit metadata에 저장하지 않는다.
