# Tracing 및 Audit 아키텍처

Status: Draft
Authority: Architecture
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: ADR-202606271559-audit-log-rag-trace-storage

## 원칙

- Audit log와 trace payload는 서로 다른 관심사다.
- `audit_logs`는 사용자 action, policy result, data-change event를 기록한다.
- `trace_payloads`는 redaction, retention, visibility policy에 따라 redacted/raw payload record를 저장한다.
- Raw payload 접근에는 강한 권한과 visibility policy 허용이 모두 필요하다.
- Raw payload 접근 시도는 `trace_payload_access_events`에 기록한다.

## 단일 기준 문서

- Audit 및 trace table 설계: [data-model/physical-data-model.md](../data-model/physical-data-model.md)
- 권한 matrix: [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md)
- 저장 방식 결정: [ADR-202606271559-audit-log-rag-trace-storage](../decisions/ADR-202606271559-audit-log-rag-trace-storage.md)
