# RBAC Permission API Integration

Status: Draft
Authority: Frontend Implementation Guide
Source of Truth: No
Verified Against: feature/mba-6 @ 5856452478494c2e2c6aa36993a6aafac9c7ebcf

## 목적

이 문서는 RBAC 프론트 구현에서 사용할 organization, team, workflow permission API 연결 방식과 프론트 상태 반영 기준을 정리한다.

API 계약의 최종 기준은 `api/organization-rbac.md`와 `api/apps-workflows.md`다. 이 문서에 코드 연결 편의를 위해 적은 endpoint가 API 문서에 없으면 확정 계약이 아니라 문서 보강 TODO로 취급한다.

## 범위

포함:

- active organization header 처리
- organization/team/member 로딩
- workflow permission 목록 조회
- workflow team/user permission grant/revoke
- 내 workflow permission 조회
- workflow 권한 기반 UI state 반영
- API error 처리

제외:

- API route 신규 설계
- 서버 permission helper 구현
- LLM credential permission 세부 UI

## 관련 기준 문서

| 문서 | 기준 |
| --- | --- |
| `api/organization-rbac.md` | organization/team/permission API |
| `api/apps-workflows.md` | workflow API |
| `architecture/auth-rbac.md` | `X-Organization-Id` active organization |
| `data-model/rbac-permission-policy.md` | permission matrix |

## 공통 요청 규칙

인증된 API는 cookie 기반 `credentials: include` 또는 axios `withCredentials: true`를 사용한다.

organization/team/permission 관리 API는 `X-Organization-Id` header가 필요하다.

```ts
headers: {
  'Content-Type': 'application/json',
  'X-Organization-Id': activeOrganizationId,
}
```

active organization은 서버 session에 저장하지 않는다. 프론트가 현재 선택한 organization id를 매 요청에 넣어야 한다.

## API 목록

### Organization

| API | 사용 시점 | 성공 시 state |
| --- | --- | --- |
| `GET /api/v1/organizations` | Settings 또는 app 초기화 | 접근 가능한 organization 목록 |
| `GET /api/v1/organizations/current` | active organization 검증 | 현재 organization |
| `GET /api/v1/organizations/{organization_id}` | 상세 필요 시 | organization detail |

### Team / Member

| API | 사용 시점 | 성공 시 state |
| --- | --- | --- |
| `GET /api/v1/teams` | Settings access tab | team 목록 |
| `GET /api/v1/teams/{team_id}/members` | team 목록 로드 후 | team별 member map |
| `POST /api/v1/teams` | team 생성 | team 목록 재조회 |
| `POST /api/v1/teams/{team_id}/members` | member 추가 | team member 재조회 |
| `DELETE /api/v1/teams/{team_id}/members/{user_id}` | member 제거 | team member 재조회 |

### Workflow permission 관리

| API | 사용 시점 | 성공 시 state |
| --- | --- | --- |
| `GET /api/v1/permissions/workflows/{workflow_id}` | 권한 관리 화면에서 workflow 선택 | team/user permission 목록 |
| `PUT /api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | team 권한 저장 | permission 목록 재조회 |
| `DELETE /api/v1/permissions/workflows/{workflow_id}/teams/{team_id}` | team 권한 회수 | permission 목록 재조회 |
| `PUT /api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | user direct 권한 저장 | permission 목록 재조회 |
| `DELETE /api/v1/permissions/workflows/{workflow_id}/users/{user_id}` | user direct 권한 회수 | permission 목록 재조회 |

### Workflow 사용 권한

| API | 사용 시점 | 성공 시 state |
| --- | --- | --- |
| `GET /api/v1/workflows/{workflow_id}` | workflow 진입 | metadata |
| `GET /api/v1/workflows/{workflow_id}/draft` | editor graph 로드 | graph |
| `POST /api/v1/workflows/{workflow_id}/draft` | 저장 | save status |
| `POST /api/v1/workflows/{workflow_id}/execute` | 실행 | run result |
| `POST /api/v1/workflows/{workflow_id}/stream` | streaming 실행 | event stream |

`GET /api/v1/workflows/{workflow_id}/permissions/me`는 현재 client 코드에서 내 workflow 권한 상태 조회에 사용하지만, `api/` 계약 문서에는 별도 endpoint로 정리되어 있지 않다. 프론트 구현에서는 임시 연동 지점으로 다루고, PR에서는 `api/apps-workflows.md` 또는 별도 API 문서 보강 여부를 함께 확인한다.

## Response 매핑

### Permission list

```ts
type ResourcePermissionListResponse = {
  resource_type: 'workflow';
  resource_id: string;
  organization_id: string;
  team_permissions: ResourcePermissionEntry[];
  user_permissions: ResourcePermissionEntry[];
};
```

UI 매핑:

| Response field | UI |
| --- | --- |
| `team_permissions` | Team permissions table |
| `user_permissions` | User direct permissions table |
| `auth_state` | 권한 badge/select |
| `assigned_at` | 부여 시각 |

### My workflow permission

```ts
type WorkflowPermissionResponse = {
  workflow_id: string;
  organization_id: string | null;
  auth_state: 'none' | 'viewer' | 'operator' | 'builder' | 'manager';
  can_read: boolean;
  can_write: boolean;
  can_execute: boolean;
  can_deploy: boolean;
  can_manage: boolean;
};
```

UI는 가능하면 `can_*` boolean을 직접 사용하고, 표시 badge에는 `auth_state`를 사용한다.

## Error 처리

| Status | 의미 | UI 처리 |
| --- | --- | --- |
| 400 | 잘못된 form 또는 auth_state | field error |
| 401 | 인증 만료 | login redirect 또는 session expired 안내 |
| 403 | 같은 organization scope 안이지만 action 권한 부족 | permission denied 안내 |
| 404 | resource 없음 또는 organization scope 밖 | not found 또는 접근 차단 안내 |
| 409 | 중복/동시성 충돌 가능성 | 재조회 후 다시 시도 |
| 500 | 서버 오류 | retry 안내 |
| Network | 서버 연결 실패 | 네트워크/서버 상태 확인 안내 |

## 상태 관리 기준

권장 상태:

```ts
type RbacState = {
  activeOrganizationId: string | null;
  organizations: OrganizationResponse[];
  teams: TeamResponse[];
  teamMembersByTeamId: Record<string, TeamMemberResponse[]>;
  selectedWorkflowId: string | null;
  workflowPermissionsById: Record<string, ResourcePermissionListResponse>;
  workflowAccessById: Record<string, WorkflowPermissionResponse>;
  loading: boolean;
  submitting: boolean;
  error: string | null;
};
```

권한 변경 후에는 optimistic update보다 재조회를 기본으로 한다. permission row upsert, audit, effective permission 계산이 서버 기준이기 때문이다.

## 현재 코드 연결 지점

| 파일 | 역할 |
| --- | --- |
| `apps/client/app/dashboard/settings/page.tsx` | organization/team/permission 관리 UI |
| `apps/client/lib/activeOrganization.ts` | active organization id 저장과 header 생성 |
| `apps/client/app/features/workflow/api/workflowApi.ts` | workflow API client |
| `apps/client/app/features/workflow/hooks/useWorkflowAppSync.ts` | workflow metadata와 내 permission 로드 |
| `apps/client/app/features/workflow/store/useWorkflowStore.ts` | workflow access state 저장 |

## 확인 필요

| 항목 | 이유 |
| --- | --- |
| `GET /api/v1/users?organization_id={id}` 공식 API 문서 위치 | Settings page에서 사용 중이나 RBAC API 문서에는 아직 명확히 정리되지 않음 |
| `GET /api/v1/workflows/app/{app_id}`의 workflow별 permission filtering | `none` workflow 목록 노출 정책과 직접 연결 |
| `permissions/me`가 `none` 상태에서도 응답할지 | 현재 read 권한이 있어야 호출 가능하면 `none`은 403이 먼저 발생할 수 있음 |

## QA 체크리스트

- [ ] 모든 permission 관리 API에 `X-Organization-Id`가 포함된다.
- [ ] organization 변경 시 team/member/permission state가 재조회된다.
- [ ] workflow 변경 시 permission list가 재조회된다.
- [ ] grant/update 성공 후 서버 목록과 UI가 일치한다.
- [ ] revoke 성공 후 row가 사라진다.
- [ ] 403 응답 시 권한 부족 메시지를 보여준다.
- [ ] 404 응답 시 존재 여부를 과도하게 노출하지 않는다.
