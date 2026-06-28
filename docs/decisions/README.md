# 설계 결정 기록

Status: Draft
Authority: Decision
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1

중요한 정책, 아키텍처, 데이터 저장, 접근 제어 결정을 기록한다. 작은 구현 기본값은 각 도메인 문서나 구현 계획에 둔다.

## 작성 기준

- 여러 권위 문서나 여러 모듈에 영향을 주는 결정만 ADR로 남긴다.
- DB schema, RBAC, audit, data retention, organization boundary, 보안 경계는 ADR 후보로 본다.
- ADR은 결정의 이유와 선택지를 기록한다. 현재 구현 기준은 관련 source-of-truth 문서에도 반드시 반영한다.
- 파일명은 `ADR-YYYYMMDDHHmm-topic-slug.md` 형식을 사용한다.
- timestamp는 KST 기준 문서 생성 시각이다.

## 목록

`decisions/`의 ADR 본문은 작성 시점의 결정 과정을 보존하는 기록 문서다. `상태`는 해당 ADR 자체의 상태를 뜻하며, 현재 코드 기준은 `현재 코드 기준` 열을 따른다.

| ADR | 상태 | 주제 | 현재 코드 기준 |
| --- | --- | --- | --- |
| [ADR-202606271559-active-organization](ADR-202606271559-active-organization.md) | Proposed | Active organization 결정 방식 | [ADR-202606290145](ADR-202606290145-active-organization-header-context.md)에 따라 `X-Organization-Id` header 방식 구현 |
| [ADR-202606271559-auth-state-standard](ADR-202606271559-auth-state-standard.md) | Proposed | auth_state 표준화 | [ADR-202606290116](ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md)에 따라 `none/viewer/operator/builder/manager`와 legacy mapping 구현 |
| [ADR-202606271559-user-direct-permission](ADR-202606271559-user-direct-permission.md) | Proposed | User direct permission 도입 | [ADR-202606290116](ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md)에 따라 `user_workflow_permissions`, `user_llm_permissions` 구현 |
| [ADR-202606271559-audit-log-rag-trace-storage](ADR-202606271559-audit-log-rag-trace-storage.md) | Accepted | audit_logs와 RAG trace 저장 기준 | `audit_logs`, trace payload 계열 table 재사용 |
| [ADR-202606271559-data-model-document-structure](ADR-202606271559-data-model-document-structure.md) | Accepted | 데이터 모델 문서 구조 | `physical-data-model.md`와 `rbac-permission-policy.md` 분리 유지 |
| [ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission](ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md) | Accepted | RBAC auth_state 및 User Direct Permission 승인 | 현재 코드의 workflow/LLM credential RBAC 기준. `user_knowledge_permissions`, `user_audit_permissions`는 아직 구현되지 않음 |
| [ADR-202606290124-mvp2-classification-metadata-storage](ADR-202606290124-mvp2-classification-metadata-storage.md) | Accepted | MVP 2 classification metadata 저장 방식 | `documents.meta_info` 사용 가능. `knowledge_bases.classification`, `documents.classification` column 없음 |
| [ADR-202606290131-audit-action-naming-standard](ADR-202606290131-audit-action-naming-standard.md) | Accepted | Audit action naming 표준 | `AuditAction` 상수 기준으로 주요 action 구현. permission row 변경은 `*_permission.created/updated/deleted` data-change audit도 기록 |
| [ADR-202606290145-active-organization-header-context](ADR-202606290145-active-organization-header-context.md) | Accepted | Active organization header context 승인 | organization/team/permission API에서 `X-Organization-Id` 검증 구현 |

## 상태 의미

- `Proposed`: 작성 당시 제안 상태로 남은 기록이다. 현재 구현 기준은 반드시 `현재 코드 기준` 열과 active source-of-truth 문서를 따른다.
- `Accepted`: 채택된 결정 기록이다. 실제 구현 반영 여부와 범위는 `현재 코드 기준` 열을 따른다.
- `Superseded`: 다른 ADR 또는 문서로 대체됨.
