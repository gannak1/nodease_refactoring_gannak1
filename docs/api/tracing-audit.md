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

## LLM Trace 엔드포인트

MVP 1에서 run/node 기준 LLM usage를 조회해야 한다. 아래 두 방식 중 하나만 채택한다.

| Status | Method | Path | 설명 |
| --- | --- | --- | --- |
| Planned | `GET` | `/api/v1/workflows/{workflow_id}/runs/{run_id}` | 기존 run detail 응답에 LLM usage 요약을 포함 |
| Planned | `GET` | `/api/v1/workflows/{workflow_id}/runs/{run_id}/llm-traces` | 별도 LLM trace endpoint |

중복 API를 만들지 않는다. 별도 endpoint를 선택하면 query parameter `node_id`를 지원한다.

## Raw Payload 규칙

- raw payload는 `raw_auditor` 또는 `manager` 수준 권한과 trace visibility policy가 모두 허용해야 반환한다.
- raw payload 접근 시도는 `trace_payload_access_events`에 남긴다.
- secret, token, credential 원문은 audit metadata에 저장하지 않는다.
