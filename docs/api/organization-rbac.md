# Organization 및 RBAC API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md), [ADR-202606271559-auth-state-standard](../decisions/ADR-202606271559-auth-state-standard.md), [ADR-202606271559-user-direct-permission](../decisions/ADR-202606271559-user-direct-permission.md)

## 범위

Organization context, organization member/invitation, team 관리, resource permission grant/revoke API 계약을 정의한다.

현재 dev Gateway에는 active organization 전용 endpoint가 없다. Team과 workflow/LLM resource permission endpoint는 MVP 1 RBAC foundation 기준으로 구현되어 있다. MVP 2-0 이후 active organization 목록과 user의 organization 소속은 `organization_memberships`를 기준으로 한다.

## Active Organization

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Planned | `GET` | `/api/v1/organizations` | authenticated | 사용자가 속한 organization 목록 |
| Planned | `GET` | `/api/v1/organizations/current` | authenticated | 현재 active organization 조회 |
| Proposed | `PATCH` | `/api/v1/organizations/current` | authenticated | active organization 변경 |

`PATCH /organizations/current`는 active organization 방식을 header로 확정하면 만들지 않을 수 있다.

`GET /organizations`는 MVP 2-0 이후 `organization_memberships`를 기준으로 active organization과 invited organization을 함께 반환한다. Invited organization은 초대 상태 표시와 accept action에는 사용할 수 있지만 resource 화면 진입과 permission 계산에는 사용할 수 없다.

## Organization Member / Invitation

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Planned | `GET` | `/api/v1/organizations/{organization_id}/members` | organization `manager` | organization member 목록 |
| Planned | `POST` | `/api/v1/organizations/{organization_id}/members/invitations` | organization `manager` | 기존 user를 organization에 초대 |
| Planned | `POST` | `/api/v1/organizations/{organization_id}/members/me/accept` | invited user 본인 | organization invitation 수락 |
| Planned | `PATCH` | `/api/v1/organizations/{organization_id}/members/{user_id}` | organization `manager` | member state 또는 organization auth state 변경 |
| Planned | `DELETE` | `/api/v1/organizations/{organization_id}/members/{user_id}` | organization `manager` | organization member 제거 및 team/direct permission cleanup |

Invitation/member API 규칙:

- invitation 대상은 MVP 2-0에서 기존 가입 user로 제한한다.
- 자기 자신 invite는 허용하지 않는다.
- 이미 active member이면 invite는 idempotent하게 기존 membership을 반환한다.
- invited 상태로 다시 invite하면 기존 invitation을 반환하거나 resend metadata만 갱신한다.
- suspended member를 다시 invite하면 `409`를 반환하고, manager는 update endpoint로 reactivate해야 한다.
- removed member를 다시 invite하면 새 `invited` 상태로 전환하되 과거 team/direct permission은 복구하지 않는다.
- accept는 invited user 본인만 수행한다. Manager-side 강제 accept는 MVP 2-0 범위가 아니다.
- member update는 `active`와 `suspended` 전환만 직접 처리하고, `removed`는 delete endpoint를 사용한다.
- suspended 전환 시 team/direct permission row는 유지하고 helper가 접근을 차단한다. Reactivate하면 유지되던 row가 다시 효력을 가진다.
- remove는 membership을 `removed`로 soft remove하고 해당 organization의 `team_memberships`와 `user_*_permissions`를 hard delete한다.
- 마지막 manager 제거, 마지막 manager suspend, self-remove, self-demote는 MVP 2-0에서 차단한다.

## Team 관리

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/teams` | organization `manager` | team 생성 |
| Implemented | `GET` | `/api/v1/teams` | organization `manager` | active organization의 team 목록 |
| Implemented | `PATCH` | `/api/v1/teams/{team_id}` | organization `manager` | team 이름/설명/관리자 설정 변경 |
| Implemented | `DELETE` | `/api/v1/teams/{team_id}` | organization `manager` | team 비활성화 |
| Implemented | `POST` | `/api/v1/teams/{team_id}/members` | organization `manager` | active organization member인 user를 team에 추가 |
| Implemented | `DELETE` | `/api/v1/teams/{team_id}/members/{user_id}` | organization `manager` | user를 team에서 제거 |

위 표의 `Implemented`는 endpoint 존재 기준이다. MVP 2-0 이후 `POST /teams/{team_id}/members`는 대상 user의 active organization membership을 추가로 검증해야 한다. `DELETE /teams/{team_id}/members/{user_id}`는 team 배정만 제거하며 organization membership은 제거하지 않는다.

## Resource Permission

| Status | Method | Path | Permission | 설명 |
| --- | --- | --- | --- | --- |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` | team workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | workflow `manage` 또는 organization `manager` | team workflow 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` | user direct workflow 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | workflow `manage` 또는 organization `manager` | user direct workflow 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` | team LLM credential 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/teams/{team_id}` | credential `manage` 또는 organization `manager` | team LLM credential 권한 회수 |
| Implemented | `PUT` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` | user direct LLM credential 권한 부여/수정 |
| Implemented | `DELETE` | `/api/v1/permissions/llm-credentials/{credential_id}/users/{user_id}` | credential `manage` 또는 organization `manager` | user direct LLM credential 권한 회수 |
| Planned | `PUT` | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/teams/{team_id}` | knowledge base `manage` 또는 organization `manager` | team knowledge base 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/teams/{team_id}` | knowledge base `manage` 또는 organization `manager` | team knowledge base 권한 회수 |
| Planned | `PUT` | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/users/{user_id}` | knowledge base `manage` 또는 organization `manager` | user direct knowledge base 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/knowledge-bases/{knowledge_base_id}/users/{user_id}` | knowledge base `manage` 또는 organization `manager` | user direct knowledge base 권한 회수 |
| Planned | `PUT` | `/api/v1/permissions/audit/organizations/{target_organization_id}/teams/{team_id}` | audit `manage` 또는 organization `manager` | team audit visibility 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/audit/organizations/{target_organization_id}/teams/{team_id}` | audit `manage` 또는 organization `manager` | team audit visibility 권한 회수 |
| Planned | `PUT` | `/api/v1/permissions/audit/organizations/{target_organization_id}/users/{user_id}` | audit `manage` 또는 organization `manager` | user direct audit visibility 권한 부여/수정 |
| Planned | `DELETE` | `/api/v1/permissions/audit/organizations/{target_organization_id}/users/{user_id}` | audit `manage` 또는 organization `manager` | user direct audit visibility 권한 회수 |

MVP 2-0 이후 모든 team/user permission grant는 대상 organization의 active membership을 먼저 검증한다.

- team permission grant는 team의 `organization_id`와 resource organization scope가 같아야 한다.
- user direct permission grant는 대상 user가 resource organization의 active `organization_memberships` row를 가져야 한다.
- team에 속하지 않은 active organization member에게도 user direct permission을 부여할 수 있다.
- invited, suspended, removed, non-member user에게는 user direct permission을 부여할 수 없다.
- organization member 제거 시 해당 organization의 `team_memberships`와 `user_*_permissions`는 cleanup된다.

## Permission Grant 요청

```json
{
  "auth_state": "viewer"
}
```

허용값은 [rbac-permission-policy.md](../data-model/rbac-permission-policy.md)의 resource matrix를 따른다.

대표 허용값:

| Resource | `auth_state` |
| --- | --- |
| workflow | `viewer`, `operator`, `builder`, `manager` |
| LLM credential | `viewer`, `operator`, `builder`, `manager` |
| knowledge base | `viewer`, `operator`, `builder`, `manager` |
| audit visibility | `auditor`, `raw_auditor`, `manager` |

`raw_auditor` 또는 audit `manager` 권한만으로 raw trace payload 조회가 자동 허용되지는 않는다. Raw trace 조회는 audit visibility permission과 `trace_visibility_policies`를 함께 통과해야 한다.

## Audit

권한 부여, 회수, 거부는 `audit_logs`에 남긴다.

| Event | `audit_logs.action` |
| --- | --- |
| 권한 부여 | `permission.grant` |
| 권한 회수 | `permission.revoke` |
| 권한 거부 | `permission.denied` |
| organization 초대 | `organization.invite` |
| organization 초대 수락 | `organization.member.accept` |
| organization member 변경 | `organization.member.update` |
| organization member 제거 | `organization.member.remove` |
