# 데이터 모델 개요 다이어그램

Status: Draft
Authority: Data Model Diagram
Source of Truth: No
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

이 문서는 [physical-data-model.md](../physical-data-model.md)의 table 참조관계를 시각화한 보조 문서다. 구현 기준은 Mermaid 다이어그램이 아니라 물리 데이터 모델 문서의 table, column, relationship 설명이다.

```mermaid
erDiagram
  users ||--o{ organization : creates_manages
  users ||--o{ organization_memberships : belongs_to
  organization ||--o{ organization_memberships : has_members
  organization ||--o{ teams : owns
  organization ||--o{ apps : scopes
  organization ||--o{ workflows : scopes
  organization ||--o{ knowledge_bases : scopes
  organization ||--o{ llm_credentials : scopes
  organization ||--o{ llm_usage_logs : scopes

  users ||--o{ team_memberships : joins
  teams ||--o{ team_memberships : has_members
  teams ||--o{ team_workflow_permissions : grants
  teams ||--o{ team_knowledge_permissions : grants
  teams ||--o{ team_llm_permissions : grants
  teams ||--o{ team_audit_permissions : grants
  users ||--o{ user_workflow_permissions : direct_grant
  users ||--o{ user_knowledge_permissions : direct_grant
  users ||--o{ user_llm_permissions : direct_grant
  users ||--o{ user_audit_permissions : direct_grant

  apps ||--o{ workflows : has
  apps ||--o{ workflow_deployments : deploys
  apps ||--o{ workflow_runs : runs

  workflows ||--o{ workflow_runs : runs
  workflows ||--o{ llm_usage_logs : logs
  workflows ||--o{ team_workflow_permissions : authorized_by
  workflows ||--o{ user_workflow_permissions : authorized_by

  workflow_deployments ||--o| schedules : may_have
  workflow_deployments ||--o{ workflow_runs : runs

  workflow_runs ||--o{ workflow_node_runs : has
  workflow_runs ||--o{ trace_payloads : stores
  workflow_runs ||--o{ trace_payload_access_events : audited_by
  workflow_runs ||--o{ llm_usage_logs : records

  workflow_node_runs ||--o{ trace_payloads : stores

  knowledge_bases ||--o{ documents : contains
  knowledge_bases ||--o{ document_chunks : denormalizes
  knowledge_bases ||--o{ team_knowledge_permissions : authorized_by
  knowledge_bases ||--o{ user_knowledge_permissions : authorized_by
  documents ||--o{ document_chunks : contains

  llm_providers ||--o{ llm_models : provides
  llm_providers ||--o{ llm_credentials : has
  llm_credentials ||--o{ llm_rel_credential_models : enables
  llm_models ||--o{ llm_rel_credential_models : enabled_by
  llm_credentials ||--o{ llm_usage_logs : logs
  llm_credentials ||--o{ team_llm_permissions : authorized_by
  llm_credentials ||--o{ user_llm_permissions : authorized_by
  llm_models ||--o{ llm_usage_logs : logs

  users ||--o{ audit_logs : acts
```
