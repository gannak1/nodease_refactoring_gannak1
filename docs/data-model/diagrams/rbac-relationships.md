# RBAC 참조관계 다이어그램

Status: Draft
Authority: Data Model Diagram
Source of Truth: No
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

이 문서는 [physical-data-model.md](../physical-data-model.md)와 [rbac-permission-policy.md](../rbac-permission-policy.md)의 RBAC 관련 table 참조관계를 시각화한 보조 문서다. 구현 기준은 이 다이어그램이 아니라 물리 데이터 모델과 RBAC 권한 정책 문서다.

```mermaid
erDiagram
  organization ||--o{ teams : owns
  organization ||--o{ team_memberships : scopes
  organization ||--o{ team_workflow_permissions : scopes
  organization ||--o{ team_knowledge_permissions : scopes
  organization ||--o{ team_llm_permissions : scopes
  organization ||--o{ team_audit_permissions : grants_audit_visibility
  organization ||--o{ user_workflow_permissions : scopes
  organization ||--o{ user_knowledge_permissions : scopes
  organization ||--o{ user_llm_permissions : scopes
  organization ||--o{ user_audit_permissions : grants_audit_visibility

  users ||--o{ team_memberships : joins
  users ||--o{ user_workflow_permissions : direct_grant
  users ||--o{ user_knowledge_permissions : direct_grant
  users ||--o{ user_llm_permissions : direct_grant
  users ||--o{ user_audit_permissions : direct_grant

  teams ||--o{ team_memberships : has_members
  teams ||--o{ team_workflow_permissions : grants
  teams ||--o{ team_knowledge_permissions : grants
  teams ||--o{ team_llm_permissions : grants
  teams ||--o{ team_audit_permissions : grants

  workflows ||--o{ team_workflow_permissions : authorized_by
  workflows ||--o{ user_workflow_permissions : authorized_by
  knowledge_bases ||--o{ team_knowledge_permissions : authorized_by
  knowledge_bases ||--o{ user_knowledge_permissions : authorized_by
  llm_credentials ||--o{ team_llm_permissions : authorized_by
  llm_credentials ||--o{ user_llm_permissions : authorized_by
```
