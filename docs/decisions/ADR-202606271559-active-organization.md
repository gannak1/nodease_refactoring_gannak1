# ADR-202606271559: Active Organization 결정 방식

Status: Accepted
Authority: Decision
Source of Truth: No
Verified Against: working tree (uncommitted)
Created At: 2026-06-27 15:59 KST
Decided At: 2026-06-27 KST

## 배경

RBAC 판정은 먼저 요청의 organization context를 결정해야 한다. 현재 dev 코드에는 첫 active team membership을 기준으로 organization을 찾는 primary organization helper가 있다. 다중 organization 사용자가 생기면 생성 scope, 조회 scope, 권한 판정 기준이 모호해질 수 있다.

## 선택지

| 선택지 | 설명 | 장단점 |
| --- | --- | --- |
| 단일 primary organization | MVP 1에서는 첫 membership만 사용한다. | 구현이 빠르지만 다중 조직 UX가 제한된다. |
| 명시적 header | API 요청에서 organization id를 header로 전달한다. | API 계약이 명확하지만 client 변경이 필요하다. |
| cookie/session context | active organization을 session/cookie에 저장한다. | UX는 자연스럽지만 상태 관리가 추가된다. |

## 결정

MVP 1의 active organization 전달 방식은 명시적 header로 확정한다.

클라이언트는 organization scope가 필요한 인증 API 요청에 `X-Organization-Id` header를 전달한다. Gateway는 이 값을 요청의 active organization context로 사용하고, 현재 사용자가 해당 organization의 active team membership을 갖는지 검증한다. 단, `organization.created_by` 또는 `organization.managed_by`가 현재 user이면 해당 organization scope 안에서 manager로 판정하므로 active team membership 없이도 접근할 수 있다.

서버는 active organization을 session/cookie나 organization row에 저장하지 않는다. 따라서 active organization 변경을 위한 `PATCH /api/v1/organizations/current` endpoint는 만들지 않는다. Header가 없는 과도기 요청은 기존 primary organization fallback을 제한적으로 사용할 수 있지만, 신규 organization-scoped API와 FE 요청은 header 전달을 기준으로 구현한다.

## 영향

- API 계약: [api/auth.md](../api/auth.md), [api/organization-rbac.md](../api/organization-rbac.md)
- 아키텍처: [architecture/auth-rbac.md](../architecture/auth-rbac.md)
- 권한 정책: [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md)
- 구현 계획: [implementation-plan/mvp-1-development-issue-plan.md](../implementation-plan/mvp-1-development-issue-plan.md)

## 후속 검토

- App, Workflow, LLM credential 생성 scope 테스트를 추가한다.
- FE nav에서 다중 organization switcher를 MVP 1에 포함할지 별도 결정한다.
