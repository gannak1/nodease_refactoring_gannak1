# 설계 결정 기록

Status: Draft
Authority: Decision
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

중요한 정책, 아키텍처, 데이터 저장, 접근 제어 결정을 기록한다. 작은 구현 기본값은 각 도메인 문서나 구현 계획에 둔다.

## 작성 기준

- 여러 권위 문서나 여러 모듈에 영향을 주는 결정만 ADR로 남긴다.
- DB schema, RBAC, audit, data retention, organization boundary, 보안 경계는 ADR 후보로 본다.
- ADR은 결정의 이유와 선택지를 기록한다. 현재 구현 기준은 관련 source-of-truth 문서에도 반드시 반영한다.
- 파일명은 `ADR-YYYYMMDDHHmm-topic-slug.md` 형식을 사용한다.
- timestamp는 KST 기준 문서 생성 시각이다.

## 목록

| ADR | 상태 | 주제 |
| --- | --- | --- |
| [ADR-202606271559-active-organization](ADR-202606271559-active-organization.md) | Proposed | Active organization 결정 방식 |
| [ADR-202606271559-auth-state-standard](ADR-202606271559-auth-state-standard.md) | Proposed | auth_state 표준화 |
| [ADR-202606271559-user-direct-permission](ADR-202606271559-user-direct-permission.md) | Proposed | User direct permission 도입 |
| [ADR-202606271559-audit-log-rag-trace-storage](ADR-202606271559-audit-log-rag-trace-storage.md) | Accepted | audit_logs와 RAG trace 저장 기준 |
| [ADR-202606271559-data-model-document-structure](ADR-202606271559-data-model-document-structure.md) | Accepted | 데이터 모델 문서 구조 |

## 상태 의미

- `Proposed`: 구현 전 승인 필요.
- `Accepted`: 현재 구현 기준.
- `Superseded`: 다른 ADR 또는 문서로 대체됨.
