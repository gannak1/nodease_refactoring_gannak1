# 인증 및 RBAC 아키텍처

Status: Draft
Authority: Architecture
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: ADR-202606271559-active-organization, ADR-202606271559-auth-state-standard, ADR-202606271559-user-direct-permission

## 적용 경계

RBAC enforcement는 Gateway endpoint와 runtime service가 함께 사용하는 재사용 가능한 service/helper logic으로 구현한다. Controller가 resource permission 비즈니스 규칙을 소유하지 않는다.

## Organization Context

권한 판단에는 organization context가 필요하다. Active organization은 [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md)에 따라 `X-Organization-Id` header로 전달한다. Gateway는 header 값이 현재 사용자의 active team membership scope 안에 있는지 검증한 뒤 resource permission을 평가한다.

현재 코드는 첫 active team membership을 기반으로 primary organization을 추정하는 fallback을 가진다. 이 fallback은 header 미전달 과도기 요청에만 제한적으로 사용하고, 신규 organization-scoped API와 FE 요청은 header 전달을 기준으로 한다.

## 권한 모델

현재 활성 데이터 모델은 organization/team permission을 기준으로 한다. User direct permission은 additive extension 후보이며 [ADR-202606271559-user-direct-permission](../decisions/ADR-202606271559-user-direct-permission.md)에서 추적한다.

물리 테이블 상세는 [data-model/physical-data-model.md](../data-model/physical-data-model.md)에 정의한다.
