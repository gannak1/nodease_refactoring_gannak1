# Organization Component Spec

Status: Verified
Verified Against: feature/mba-119 @ 7aefa84

## Screens

- 스크린샷: 없음

### Dashboard Layout

- 출처: `apps/client/app/dashboard/layout.tsx`
- 경로: `/dashboard/*`
- 책임: dashboard 하위 화면을 렌더링하기 전에 active organization context를 준비한다.
- 구성:
  - `ActiveOrganizationGate`
  - `Sidebar`
  - dashboard child route content

### DashboardHomePage

- 출처: `apps/client/app/dashboard/page.tsx`
- 경로: `/dashboard`
- 책임: 현재 organization 이름, 내 organization 역할, workflow 접근 상태, manager용 team 요약을 조회해 표시한다.
- 현재 동작:
  - `/organizations`로 접근 가능한 organization 목록을 가져온다.
  - 저장된 active organization이 유효하면 사용하고, organization이 하나뿐이면 자동 선택한다.
  - `/organizations/current`로 현재 organization 상세를 가져온다.
  - manager면 `/teams`와 `/teams/{team_id}/members`를 조회해 team 현황을 표시한다.
  - organization state를 변경하지 않는다.

### AdminConsolePage

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 경로: `/dashboard/admin`
- 책임: organization manager가 organization member, team, workflow permission, LLM credential permission을 관리하는 주 UI다.
- 현재 동작:
  - `/organizations/current`와 `/auth/me`를 병렬로 조회한다.
  - manager가 아니면 `관리 권한 없음` 상태를 표시한다.
  - manager면 member/team/permission 데이터를 로드하고 tab UI로 관리한다.
  - LLM credential, knowledge, audit 관련 tab도 포함하지만, 이 문서에서는 organization-owned member/team/permission controls만 다룬다.

### SettingsPage

- 출처: `apps/client/app/dashboard/settings/page.tsx`
- 경로: `/dashboard/settings`
- 책임: 현재 organization 이름과 organization auth badge를 표시하고, visible tab에서는 organization member/team/permission 관리 경로를 제공하지 않음을 확인한다.
- 현재 동작:
  - code에는 access-management branch가 남아 있지만 `visibleTabs`에는 `access` tab이 포함되지 않는다.
  - 따라서 organization member/team/permission 관리의 현재 사용자 경로는 AdminConsolePage다.

## Components

### ActiveOrganizationGate

- 출처: `apps/client/app/features/dashboard/components/ActiveOrganizationGate.tsx`
- 책임: dashboard 진입 시 active organization을 확인하고 dashboard child를 렌더링할지, 선택 화면을 보여줄지 결정한다.
- 렌더링:
  - `loading`: 제목 `조직 확인 중`, 설명 `현재 작업할 조직을 확인하고 있습니다.`
  - `error`: 제목 `조직을 확인할 수 없습니다`, 오류 메시지
  - `select`: 제목 `작업 조직 선택`, organization 목록 버튼, manager 여부 라벨(`관리자`/`멤버`)
  - `ready`: child content
- 데이터:
  - `publicApiClient.get('/organizations')`
  - `moduly_active_organization_id` localStorage

### Sidebar

- 출처: `apps/client/app/features/dashboard/components/Sidebar.tsx`
- 책임: 현재 organization 이름과 manager 여부를 표시하고, manager-only navigation item을 제어한다.
- 렌더링:
  - organization 이름이 있으면 sidebar 하단에 organization badge block을 표시한다.
  - `isOrganizationManager`가 true일 때만 `관리` navigation item을 표시한다.
- 데이터:
  - `authApi.me()`
  - `apiClient.get('/organizations/current')`
  - `nodease-active-organization-changed` window event

### AdminShell

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: AdminConsolePage의 공통 page header, organization meta, refresh action, badge slot을 제공한다.
- 렌더링:
  - 제목 `관리`
  - 설명 `조직 멤버, 팀, 권한과 운영 리소스를 관리합니다.`
  - organization 이름 meta
  - refresh button

### MembersTab

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: organization member 목록을 검색/필터/페이지네이션하고 초대, 상태 변경, 권한 변경, 제거 action을 제공한다.
- 렌더링:
  - `멤버` panel
  - `초대` button
  - 이름/email 검색 input
  - membership state filter(`전체 상태`, `활성`, `초대 중`, `정지`, `제거`)
  - organization auth filter(`전체 권한`, `관리자`, `멤버`)
  - member table columns: 이름, 상태, 조직 권한, 초대, 수락, 작업
  - `MemberStateBadge`, `OrganizationAuthBadge`, `MemberActions`
- 제한:
  - removed member row는 action 대신 `제거됨`을 표시한다.
  - current user를 알 수 없으면 member action button을 비활성화한다.
  - 자기 자신이거나 마지막 active manager인 row는 `강등`, `제거` button을 비활성화한다.

### MemberActions

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: member 상태/권한 변경과 제거 action button을 렌더링한다.
- 렌더링:
  - active member: `정지`
  - suspended member: `재활성화`
  - active member auth=`member`: `관리자 승격`
  - active member auth=`manager`: `멤버로 강등`
  - non-removed member: `제거`
- 상호작용:
  - organization_auth_state 변경과 제거는 AdminConsolePage confirm dialog를 거친다.

### TeamsTab

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: team 목록을 검색/필터/페이지네이션하고 team 생성, 수정, 비활성화, 상세 side panel 진입을 제공한다.
- 렌더링:
  - `팀` panel
  - `팀 생성` button
  - team 이름/설명 검색 input
  - 상태 filter(`전체 상태`, `활성`, `비활성`)
  - member filter(`전체 멤버`, `멤버 있음`, `멤버 없음`)
  - team table columns: 팀, 상태, 멤버, 작업
  - API limit 100 경고
- 제한:
  - inactive team의 비활성화 button은 disabled다.

### Team Editor SidePanel

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: team 생성 또는 수정 form을 제공한다.
- 렌더링:
  - 제목 `팀 생성` 또는 `팀 수정`
  - `팀 이름` input
  - `설명` textarea
  - `신규 멤버 자동 추가` checkbox
  - cancel/submit action

### Team Detail SidePanel

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: selected team의 member 목록과 team member add/remove action을 제공한다.
- 렌더링:
  - team active/inactive badge
  - member count
  - active team이면 `ActiveOrganizationMemberPicker`와 `추가` button
  - inactive team이면 `비활성 팀에는 멤버를 추가할 수 없습니다.`
  - team member list와 remove button

### PermissionsTab

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: workflow/LLM credential resource permission을 team 또는 user direct 대상으로 부여/회수한다.
- 렌더링:
  - resource type select(`Workflow`, `LLM Credential`)
  - resource select
  - grantee type select(`Team`, `User direct`)
  - active team select 또는 `ActiveOrganizationMemberPicker`
  - auth state select(`viewer`, `operator`, `builder`, `manager`) with resource-specific labels
  - `저장` button
  - `Team permissions` list
  - `User direct permissions` list
- 제한:
  - 선택 가능한 resource, active team, active member가 없으면 grant button이 disabled다.
  - Knowledge permission grant/revoke UI는 현재 연결되어 있지 않다.

### OrganizationTab

- 출처: `apps/client/app/dashboard/admin/page.tsx`
- 책임: 현재 organization 설정 요약을 표시한다.
- 렌더링:
  - organization name
  - warning: `조직명 수정, 기본 팀, 위험 action은 정책과 API 범위 확정 후 연결합니다.`
- 제한:
  - backend에는 organization name/options PATCH가 있으나 현재 AdminConsolePage에서는 organization 수정 form이 연결되어 있지 않다.

### ActiveOrganizationMemberPicker

- 출처: `apps/client/app/features/organization/components/ActiveOrganizationMemberPicker.tsx`
- 책임: active organization members 중 제외 대상이 아닌 user를 select option으로 제공한다.
- props:
  - `members`, `value`, `onChange`
  - `excludedUserIds`
  - `disabled`
  - `placeholder`, `emptyLabel`, `className`
- 렌더링:
  - active member가 없으면 `emptyLabel` option을 표시하고 select를 disabled한다.
  - option label은 `{user_name} ({user_email})`이다.

### OrganizationAuthBadge

- 출처: `apps/client/app/features/organization/components/OrganizationAuthBadge.tsx`
- 책임: organization auth state를 badge로 표시한다.
- 렌더링:
  - `manager`: `관리자`, blue tone
  - `member`: `멤버`, gray tone

### MemberStateBadge

- 출처: `apps/client/app/features/organization/components/MemberStateBadge.tsx`
- 책임: membership state를 badge로 표시한다.
- 렌더링:
  - `invited`: `초대 중`, amber tone
  - `active`: `활성`, green tone
  - `suspended`: `정지`, red tone
  - `removed`: `제거됨`, gray tone

### organizationApi

- 출처: `apps/client/app/features/organization/api/organizationApi.ts`
- 책임: organization member API wrapper를 제공한다.
- 호출:
  - `listOrganizations()`: `GET /organizations`
  - `listMemberships()`: `GET /organizations/memberships`
  - `getCurrentOrganization()`: `GET /organizations/current`
  - `listMembers(organizationId, state?)`: `GET /organizations/{id}/members`
  - `inviteMember(organizationId, payload)`: `POST /organizations/{id}/members/invitations`
  - `acceptInvitation(organizationId)`: `POST /organizations/{id}/members/me/accept`
  - `updateMember(organizationId, userId, payload)`: `PATCH /organizations/{id}/members/{user_id}`
  - `removeMember(organizationId, userId)`: `DELETE /organizations/{id}/members/{user_id}`

### activeOrganization Helpers

- 출처: `apps/client/lib/activeOrganization.ts`
- 책임: client-side active organization id persistence와 request header attachment를 제공한다.
- 저장소:
  - key: `moduly_active_organization_id`
  - change event: `nodease-active-organization-changed`
- 함수:
  - `getStoredActiveOrganizationId`
  - `setActiveOrganizationId`
  - `resolveActiveOrganizationId`
  - `activeOrganizationHeaders`
  - `attachActiveOrganizationHeader`

## States

### ActiveOrganizationGate

- 초기 상태: `{ status: 'loading' }`
- ready 상태:
  - 저장된 organization id가 `/organizations` 응답 안에 있거나, 접근 가능한 organization이 하나뿐일 때 진입한다.
  - children을 렌더링한다.
- select 상태:
  - 접근 가능한 organization이 두 개 이상이고 저장된 organization id가 없거나 유효하지 않을 때 진입한다.
  - organization 선택 button 목록을 렌더링한다.
- error 상태:
  - organization 목록 응답이 배열이 아니거나 접근 가능한 organization이 없거나 요청이 실패할 때 진입한다.

### Sidebar

- user state:
  - `userName` 기본값은 `사용자`
  - `userEmail` 기본값은 빈 문자열
- organization state:
  - stored active organization id가 없으면 organization name을 비우고 manager flag를 false로 둔다.
  - `/organizations/current` 성공 시 name과 `is_manager`를 반영한다.
  - 조회 실패 시 name을 비우고 manager flag를 false로 둔다.
- dropdown state:
  - user footer click으로 logout dropdown을 열고 닫는다.

### AdminConsolePage

- loading 상태:
  - `관리 콘솔을 불러오는 중...` loading block을 표시한다.
- non-manager 상태:
  - organization이 있고 `is_manager=false`이면 `관리 권한 없음` panel을 표시하고 관리 데이터를 로드하지 않는다.
- data 상태:
  - organization 관리에 필요한 `members`, `teams`, `teamMembers`, `workflowPermissions`, `credentialPermissions`를 저장한다.
  - 같은 page state에는 다른 feature tab 데이터도 존재하지만, 각 tab의 상세 책임은 해당 feature 문서가 소유한다.
  - organization member 목록은 기본 member list와 removed member list를 합쳐 중복 제거한다.
- tab 상태:
  - 이 문서의 책임 tab은 `members`, `teams`, `permissions`, `organization`이다.
  - 같은 화면에는 `credentials`, `knowledge`, `audit` tab도 있지만 상세 동작은 각 feature 문서가 소유한다.
- member filter state:
  - query, membership state, organization auth state, page
- team filter state:
  - query, active/inactive, member count filter, page
- panel state:
  - invite side panel
  - team editor side panel
  - team detail side panel
  - confirm dialog
  - credential panel
- notice/error state:
  - member removal cleanup summary를 notice와 toast로 표시한다.
  - API 실패는 toast 또는 inline error로 표시한다.

### SettingsPage

- loading/error state를 가진다.
- visible tab은 현재 `credentials`, `activity`이다.
- organization name과 auth badge를 표시한다.
- `access` branch 상태와 handler는 코드에 존재하지만 visible navigation에서 선택할 수 없다.

## Interactions

### Active Organization Resolution

- Dashboard 진입 시 `ActiveOrganizationGate`가 `/organizations`를 호출한다.
- 저장된 organization id가 응답 목록에 있으면 그대로 사용한다.
- organization이 하나뿐이면 `setActiveOrganizationId`로 저장하고 ready 상태로 전환한다.
- organization이 여러 개면 select 상태를 보여주고, 사용자가 organization button을 클릭하면 localStorage를 갱신하고 ready 상태로 전환한다.
- `setActiveOrganizationId`는 `nodease-active-organization-changed` event를 dispatch한다.
- `apiClient` request interceptor는 `X-Organization-Id` header가 없는 요청에 저장된 organization id를 첨부한다.

### Dashboard And Sidebar

- DashboardHomePage는 active organization을 resolve한 뒤 `/organizations/current`, `/apps`, workflow permission summary를 조회한다.
- manager는 team summary를 볼 수 있고 `조직 접근 관리` button으로 `/dashboard/admin`에 이동한다.
- Sidebar는 active organization changed event를 받으면 `/organizations/current`를 다시 조회한다.
- Sidebar는 `isOrganizationManager`가 false면 `관리` nav item을 렌더링하지 않는다.

### Member Management

- AdminConsolePage는 manager일 때 `/organizations/{id}/members`와 `state=removed` 요청을 함께 실행한다.
- `초대` button은 invite side panel을 연다.
- 초대 side panel은 user UUID와 organization auth state를 입력받아 `organizationApi.inviteMember`를 호출한다.
- member state update는 `organizationApi.updateMember`를 호출한다.
- organization auth state 변경은 confirm dialog를 거친다.
- member removal은 confirm dialog를 거쳐 `organizationApi.removeMember`를 호출하고 cleanup count를 notice/toast로 표시한다.

### Team Management

- AdminConsolePage는 `/teams?limit=100`을 조회하고 각 team의 `/teams/{team_id}/members`를 조회한다.
- `팀 생성`은 team editor side panel을 열고 `POST /teams`를 호출한다.
- team edit은 같은 side panel에서 `PATCH /teams/{team_id}`를 호출한다.
- team deactivate는 confirm dialog를 거쳐 `DELETE /teams/{team_id}`를 호출한다.
- team detail side panel은 active team일 때만 member add control을 표시한다.
- team member add는 `POST /teams/{team_id}/members`, remove는 `DELETE /teams/{team_id}/members/{user_id}`를 호출한다.

### Permission Management

- Permission tab은 selected resource type에 따라 `/permissions/workflows/{workflow_id}` 또는 `/permissions/llm-credentials/{credential_id}`를 조회한다.
- grantee type이 team이면 active team select를 사용한다.
- grantee type이 user이면 `ActiveOrganizationMemberPicker`로 active member만 선택하게 한다.
- grant/save는 PUT permission endpoint를 호출한다.
- revoke는 confirm dialog를 거쳐 DELETE permission endpoint를 호출한다.
- LLM credential tab에서 permission tab으로 전달된 selected credential id가 있으면 permission tab의 resource selection에 반영한다.

### Settings Page

- SettingsPage는 `/organizations`와 `/organizations/current`로 organization context를 확인하고 organization name/auth badge를 표시한다.
- visible settings tab에서는 organization member/team mutation을 제공하지 않는다.

## Accessibility

- ActiveOrganizationGate의 organization 선택은 `<button>` 요소로 구현되어 키보드 조작이 가능하다.
- Sidebar nav는 Next `Link`를 사용하고, collapse button은 `<button>` 요소다. collapse button에는 `aria-expanded`가 없다.
- Sidebar collapsed logo button에는 `aria-label="대시보드 홈"`이 있다.
- Admin tab navigation은 `<button>` 요소로 구현되어 키보드 focus가 가능하지만 `role="tablist"`/`role="tab"` 속성은 없다.
- MembersTab과 TeamsTab은 table markup을 사용하고 header cell을 제공한다.
- Member/team/permission destructive actions는 confirm dialog를 거치지만, 현재 confirm dialog와 side panel에 명시적인 `role="dialog"`/`aria-modal` 연결은 확인되지 않는다.
- icon-only buttons 일부는 `title`을 제공한다.
- `ActiveOrganizationMemberPicker`는 native `<select>`를 사용한다. 별도 `<label>`은 호출자가 제공해야 한다.
- inline error/notice blocks는 시각적으로 구분되지만 `role="alert"`나 `aria-live`는 확인되지 않는다.
