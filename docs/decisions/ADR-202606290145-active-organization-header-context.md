# ADR-202606290145: Active Organization Header Context 승인

Status: Accepted
Authority: Decision
Source of Truth: Yes
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f
Created At: 2026-06-29 01:45 KST
Related ADRs: [ADR-202606271559-active-organization](ADR-202606271559-active-organization.md)

## 배경

기존 active organization ADR은 header, cookie/session, 단일 primary organization 중 하나를 선택해야 한다고 Proposed 상태로 남겼다.

현재 코드에는 organization, team, permission API에서 `X-Organization-Id` header를 읽고, 해당 organization이 현재 user의 active team membership scope 안에 있는지 검증하는 흐름이 구현되어 있다. `GET /api/v1/organizations/current`도 서버 session에 active organization을 저장하지 않고 매 요청의 header 값을 검증한다.

## 결정

MVP 1 기준 active organization context는 request header 방식으로 승인한다.

1. API 요청은 `X-Organization-Id` header로 active organization을 전달한다.
2. 서버는 active organization을 session/cookie에 저장하지 않는다.
3. `GET /api/v1/organizations/current`는 header 값을 검증해 현재 요청의 active organization을 반환한다.
4. `GET /api/v1/organizations`는 사용자가 active membership으로 접근 가능한 organization 목록을 반환한다.
5. `PATCH /api/v1/organizations/{organization_id}`는 header organization과 path organization이 일치해야 하며, organization owner/manager만 수정할 수 있다.
6. header가 없는 legacy/과도기 경로에서는 첫 active team membership 기반 primary organization fallback을 제한적으로 사용할 수 있다.

## 구현 기준

- Organization API는 `X-Organization-Id`를 파싱하고 active membership scope를 검증한다.
- Team 관리 API와 permission grant/revoke API는 `X-Organization-Id`를 organization scope로 사용한다.
- Permission helper는 resource의 `organization_id`와 요청 organization이 다르면 fail-closed 처리한다.
- 신규 가입 또는 legacy resource 보정처럼 organization context가 아직 없는 흐름에서는 default organization bootstrap 또는 primary organization fallback을 사용할 수 있다.

## 기존 ADR과의 관계

이 ADR은 기존 Proposed ADR을 직접 수정하지 않는다. 다만 이 ADR의 승인 범위에서는 [ADR-202606271559-active-organization](ADR-202606271559-active-organization.md)의 미확정 문구보다 이 ADR이 우선한다.

## 영향

- 인증 API: [api/auth.md](../api/auth.md)
- Organization/RBAC API: [api/organization-rbac.md](../api/organization-rbac.md)
- 인증/RBAC 아키텍처: [architecture/auth-rbac.md](../architecture/auth-rbac.md)
- 권한 정책: [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md)
- MVP 1 구현 계획: [implementation-plan/mvp-1-development-issue-plan.md](../implementation-plan/mvp-1-development-issue-plan.md)

## 후속 검토

- 모든 resource CRUD API가 header organization을 일관되게 받는지 별도 회귀 테스트로 확인한다.
- 다중 organization switcher UX는 header context를 선택/전달하는 UI 문제로 분리한다.
- header 방식이 외부 API/SDK에 노출될 때 문서와 client helper를 함께 정리한다.
