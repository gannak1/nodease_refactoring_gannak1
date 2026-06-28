# 인증 및 RBAC 아키텍처

Status: Draft
Authority: Architecture
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: ADR-202606271559-active-organization, ADR-202606271559-auth-state-standard, ADR-202606271559-user-direct-permission

## 적용 경계

RBAC enforcement는 Gateway endpoint와 runtime service가 함께 사용하는 재사용 가능한 service/helper logic으로 구현한다. Controller가 resource permission 비즈니스 규칙을 소유하지 않는다.

## Organization Context

권한 판단에는 organization context가 필요하다. MVP 1의 과도기 구현은 첫 active team membership을 기반으로 primary organization을 추정하는 fallback을 가진다. MVP 2-0 이후에는 active `organization_memberships`를 primary organization과 organization 소속의 기준으로 사용한다. 최종 active organization 전달 전략은 아직 승인되지 않았으며 [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md)에서 추적한다.

## 권한 모델

현재 활성 데이터 모델은 organization membership 선검증 후 team permission을 기준으로 한다. User direct permission은 additive extension이며 active organization member에게만 부여한다. 관련 결정은 [ADR-202606271559-user-direct-permission](../decisions/ADR-202606271559-user-direct-permission.md)에서 추적한다.

물리 테이블 상세는 [data-model/physical-data-model.md](../data-model/physical-data-model.md)에 정의한다.
