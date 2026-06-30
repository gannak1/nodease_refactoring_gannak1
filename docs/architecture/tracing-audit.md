# Tracing 및 Audit 아키텍처

Status: Draft
Authority: Architecture
Source of Truth: Yes
Verified Against: dev @ ec576b4f24155697aed8843acc6e5a3fc835f7e1
Related ADRs: ADR-202606271559-audit-log-rag-trace-storage

## 원칙

- Audit log와 trace payload는 서로 다른 관심사다.
- `audit_logs`는 사용자 action, policy result, data-change event를 기록한다.
- `trace_payloads`는 redaction, retention, visibility policy에 따라 redacted/raw payload record를 저장한다.
- Raw payload 접근에는 강한 권한과 visibility policy 허용이 모두 필요하다.
- Raw payload 접근 시도는 `trace_payload_access_events`에 기록한다.

## 현재 접근 판정

- Trace policy/retention 관리 API의 system admin 판정은 `TraceRbacService` provider에 위임한다. 기본 provider는 deny-all이다.
- Trace 목록 조회는 system admin 또는 app owner 범위로 DB 후보를 줄인 뒤 run별 access check를 수행한다.
- Trace 상세와 payload 조회는 system admin, app owner, workflow effective `auth_state`, visibility policy를 함께 평가한다.
- Raw payload 응답은 `trace_payload_access_events` 기록이 선행되어야 하며, 허용된 raw 응답에서 기록 실패가 발생하면 요청도 실패한다.
- Policy management API는 현재 `global`과 `app` scope만 허용한다. 물리 schema의 `organization` scope는 현재 management API에서 지원하지 않는다.

## 단일 기준 문서

- Audit 및 trace table 설계: [data-model/physical-data-model.md](../data-model/physical-data-model.md)
- 권한 matrix: [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md)
- 저장 방식 결정: [ADR-202606271559-audit-log-rag-trace-storage](../decisions/ADR-202606271559-audit-log-rag-trace-storage.md)
