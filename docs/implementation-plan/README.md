# 구현 계획

Status: Draft
Authority: Implementation Plan
Source of Truth: Yes
Verified Against: dev @ ec576b4f24155697aed8843acc6e5a3fc835f7e1

구현 계획 문서는 source-of-truth 문서를 실제 작업 순서와 이슈로 분해한다.

| 문서 | 역할 |
| --- | --- |
| [mvp-1-development-issue-plan.md](mvp-1-development-issue-plan.md) | MVP 1 개발 이슈 생성 계획 |
| [mvp-2-0-organization-membership-invitation-foundation.md](mvp-2-0-organization-membership-invitation-foundation.md) | MVP 2 본작업 전 organization membership 및 초대 기반 구현 계획 |
| [risk-consistency-verification.md](risk-consistency-verification.md) | 리스크, 정합성, 검증 매트릭스 |
| [implementation-decision-log.md](implementation-decision-log.md) | 구현 중 작은 결정, 기본값, 임시 호환 처리 기록 |

## 진행 순서

현재 진행 계획은 MVP 1 foundation을 완료한 뒤, MVP 2 Governance/RAG/Audit 본작업에 들어가기 전에 [MVP 2-0 Organization Membership / Invitation Foundation](mvp-2-0-organization-membership-invitation-foundation.md)을 선행한다.

```text
MVP 1 Foundation / LLMOps Observability
  -> MVP 2-0 Organization Membership / Invitation Foundation
  -> MVP 2 Data Source Permission Enforcement
  -> MVP 2 Data Classification
  -> MVP 2 RAG Retrieval Trace Metadata
  -> MVP 2 Re-index Flow
  -> MVP 2 Audit Log Search
```

MVP 2-0에서는 `organization_memberships`를 organization 소속의 기준으로 추가하고, team membership과 user direct permission은 active organization membership을 전제로 동작하도록 전환한다. 이후 `user_knowledge_permissions`, knowledge base `use` enforcement, RAG node execution check를 구현한다.

## 권위

- 구현 계획이 requirements, architecture, data-model, api 문서와 충돌하면 구현 계획을 수정한다.
- 미결정 ADR을 구현 전제로 삼지 않는다.
- 새 policy, architecture, security, data-storage 결정은 [decisions/](../decisions/README.md)에 기록한다.
- 작은 구현 결정은 [implementation-decision-log.md](implementation-decision-log.md)에 기록하되, 상위 source-of-truth와 충돌하면 상위 문서를 따른다.
