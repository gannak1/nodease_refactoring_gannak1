# Admin Console UI/UX

Status: Draft
Authority: Frontend Implementation Guide
Source of Truth: No
Verified Against: feature/mba-84 working tree

## 목적

이 문서는 organization manager 전용 관리 화면을 `/dashboard/settings`에서 분리해 `/dashboard/admin` 또는 동등한 manager-only 관리 콘솔로 구성할 때의 UI/UX 기준을 정리한다.

기존 Settings는 개인/계정/읽기 전용 확인 성격으로 남기고, 조직 멤버, 팀, 권한, LLM Credential, 지식 기반, 감사 로그처럼 조직 운영자가 반복적으로 조작하는 기능은 Admin Console로 이동한다.

## 범위

포함:

- dashboard sidebar에서 manager에게만 보이는 `관리` 1차 메뉴
- Admin Console 내부 상단 탭 정보 구조
- Settings와 Admin Console의 책임 분리
- manager-only 화면의 기본 layout, empty/loading/error 상태
- MBA-82/MBA-83/MBA-69에서 이어질 화면 확장 기준

제외:

- 신규 API 계약 설계
- backend permission enforcement 변경
- organization invitation/accept 상세 화면 구현
- 지식 기반 권한 API가 없는 영역의 세부 구현
- 모든 관리 action을 한 번에 구현하는 것

## 관련 기준 문서

| 영역 | 문서 |
| --- | --- |
| RBAC 화면 개요 | `docs/front/rbac-permission-ui-overview.md` |
| manager/member 홈·설정 분리 | `docs/front/rbac-mvp1-manager-member-home-settings.md` |
| organization member API/type/picker | `docs/front/rbac-permission-api-integration.md` |
| workflow 권한 관리 흐름 | `docs/front/rbac-permission-management-flow.md` |
| 내 모듈 권한/운영 목록 | `docs/front/module-list-access-operations-ui.md` |
| RBAC 정책 | `docs/data-model/rbac-permission-policy.md` |
| active organization | `docs/architecture/auth-rbac.md` |
| organization/team/permission API | `docs/api/organization-rbac.md` |

## 정보 구조

### Sidebar

Dashboard sidebar에는 manager에게만 `관리` 메뉴를 노출한다. Member에게는 메뉴 자체를 숨긴다.

```text
홈
내 모듈
지식 기반
통계
관리        # organization manager only
설정
```

`관리`는 Settings 하위 탭이 아니라 sidebar 1차 메뉴다. 조직 운영 기능은 사용 빈도와 책임이 Settings보다 크므로, Settings 안에 계속 누적하지 않는다.

### Admin Console Tabs

Admin Console 내부는 상단 탭으로 나눈다.

```text
관리
<Organization Name> · 관리자

[멤버] [팀] [권한] [LLM Credentials] [지식 기반] [감사 로그] [조직 설정]
```

MVP 우선순위:

| 순서 | 탭 | MVP 판단 |
| --- | --- | --- |
| 1 | 멤버 | MBA-82 manager 화면의 첫 진입점 |
| 2 | 팀 | team 기반 member 관리와 권한 부여의 기반 |
| 3 | 권한 | workflow/team/user direct permission 관리 |
| 4 | LLM Credentials | credential 등록, 삭제, 동기화, 접근 권한 |
| 5 | 지식 기반 | knowledge base 접근/관리 권한. API 준비 상태에 따라 read-only 또는 placeholder 가능 |
| 6 | 감사 로그 | 권한/멤버/credential 변경 이력 |
| 7 | 조직 설정 | 조직명, manager 목록, 기본 정책. MVP에서는 후순위 가능 |

첫 화면은 `멤버` 탭을 기본으로 한다. Manager가 가장 먼저 확인해야 하는 것은 “누가 이 조직에 있고 어떤 상태인가”이기 때문이다.

## Settings와 Admin Console 책임 분리

| 영역 | Settings | Admin Console |
| --- | --- | --- |
| 계정/개인 설정 | 표시 | 표시하지 않음 |
| 현재 organization membership 요약 | read-only 표시 가능 | 운영 header에 표시 |
| 조직 접근 관리 | 이동 링크만 표시하거나 제거 | 주 기능 |
| Team 생성/비활성화/member 추가 | 표시하지 않음 | 주 기능 |
| Workflow 권한 grant/revoke | 표시하지 않음 | 주 기능 |
| LLM Credential 목록 | member read-only 가능 | manager 관리 기능 |
| LLM Credential 등록/삭제/sync | 표시하지 않음 | 주 기능 |
| 지식 기반 접근 권한 | 표시하지 않음 | 주 기능 또는 후속 탭 |
| Activity/Audit | 내 활동 중심 | 조직 감사 로그 중심 |

Settings는 “내가 보는 설정”이고 Admin Console은 “조직을 운영하는 화면”이다. 이 구분을 화면 제목, navigation, empty state 문구에서도 유지한다.

## 탭별 화면 기준

### 멤버

목적: organization member 상태와 조직 권한을 관리한다.

주요 UI:

- 검색 input
- 상태 필터: 전체, 초대 중, 활성, 정지, 제거됨
- 조직 권한 필터: 전체, 멤버, 관리자
- 초대 button
- table: 이름, 이메일, 상태, 조직 권한, 소속 팀, 최근 변경, 작업

작업:

- 초대
- 정지/재활성화
- manager 승격/member 강등
- 제거
- 마지막 manager 보호 error 표시
- 자기 자신 강등/제거 guard 표시

초대 재전송/취소는 현재 확정 API 계약에 없으므로 기본 action으로 약속하지 않는다. 해당 UX가 필요하면 resend/cancel API 또는 기존 update/remove API로 대체 가능한지 별도 확인 후 후속 이슈로 분리한다.

MVP에서 invite/accept UI flow가 아직 연결되지 않은 경우 초대 action은 disabled 또는 후속 이슈 안내로 둔다. 단, 상태 badge와 active member picker 기반은 MBA-84 구현을 재사용한다.

### 팀

목적: active organization member를 team에 배정하고 team lifecycle을 관리한다.

주요 UI:

- 팀 생성 button
- active/inactive segmented control
- team table 또는 two-column layout
- team detail drawer: member list, member 추가, member 제거

작업:

- team 생성
- team 이름/설명 수정
- team 비활성화
- active organization member만 team에 추가
- 이미 team에 속한 member 중복 제외
- suspended/removed member가 기존 team에 남아 있는 경우 cleanup 안내

### 권한

목적: workflow resource에 대해 team/user direct permission을 관리한다.

주요 UI:

- resource selector: workflow 우선
- grantee type: team, user direct
- grantee picker: team list 또는 active organization member picker
- auth state selector: viewer, operator, builder, manager
- permission table: team permissions, user direct permissions

작업:

- team permission grant/update/revoke
- user direct permission grant/update/revoke
- 권한 출처 확인은 일반 member 화면에서는 `/apps/operations.permission_sources` 또는 `/permissions/me.sources`로 read-only 표시하고, Admin Console에서는 전체 권한 관리 표로 다룬다.

### LLM Credentials

목적: 조직에서 사용할 LLM credential을 등록하고 접근 권한을 관리한다.

주요 UI:

- provider별 credential list
- 등록 drawer/modal
- model sync action
- credential delete action
- credential permission 관리 진입

작업:

- credential 등록
- model sync
- credential 삭제
- credential별 team/user 접근 권한 부여

Member Settings에서는 credential 등록/삭제/sync를 노출하지 않는다. Manager action은 Admin Console로 이동한다.

### 지식 기반

목적: organization의 knowledge base와 접근 권한을 관리한다.

주요 UI:

- knowledge base list
- owner/관리자
- 연결 상태
- 문서 수 또는 sync 상태
- 권한 관리 action

작업 후보:

- knowledge base 생성/삭제 관리
- team/user 접근 권한 관리
- 문서 업로드/삭제 권한 관리

현재 API 계약이 부족한 경우 이 탭은 placeholder 또는 read-only list부터 시작한다. 구현 전에 API 문서와 실제 코드 기준을 다시 확인한다.

### 감사 로그

목적: 조직 운영 action의 이력을 추적한다.

주요 UI:

- 기간 필터
- actor 필터
- action type 필터
- target type 필터
- status 필터
- audit table

조직 전체 audit API가 확정된 뒤 목표로 삼을 표시 이벤트:

- member 초대/정지/제거/권한 변경
- team 생성/수정/비활성화/member 변경
- workflow permission grant/revoke
- LLM credential 등록/삭제/sync/권한 변경
- knowledge base 권한 변경

### 조직 설정

목적: 조직 자체의 기본 정보를 관리한다.

MVP에서는 후순위로 둔다.

후보:

- 조직명
- manager 목록
- 기본 team
- member 제거/정지 정책 안내
- 위험 action 영역

## 권한별 접근

| 사용자 | Sidebar `관리` | `/dashboard/admin` 직접 접근 | Admin API 호출 |
| --- | --- | --- | --- |
| organization manager | 표시 | 허용 | 허용 |
| organization member | 숨김 | permission denied 또는 Settings/Home으로 redirect | manager-only API 호출하지 않음 |
| workflow manager only | 숨김. organization manager가 아니면 Admin Console 진입 불가 | 차단 | 조직 관리 API 호출하지 않음 |
| anonymous | 숨김 | login redirect | 호출하지 않음 |

Workflow manager는 특정 workflow의 권한 관리 권한을 가질 수 있지만 organization member list API를 읽을 수 없을 수 있다. Admin Console은 organization manager 전용으로 제한한다. Workflow manager 전용 permission UI가 필요하면 별도 resource-level 관리 화면으로 분리한다.

## 화면 상태

| 상태 | UI |
| --- | --- |
| loading | Admin shell header와 tab skeleton을 먼저 보여주고 tab body에 table skeleton |
| no active organization | 조직을 선택하거나 생성해야 한다는 empty state |
| member 접근 | 관리 권한 없음 안내. sidebar에는 메뉴 미노출. manager-only API는 호출하지 않음 |
| manager API 403 | active organization mismatch 또는 권한 변경 가능성을 안내하고 새로고침 제공 |
| empty members | 초대 CTA. 초대 UI flow가 아직 연결되지 않았으면 후속 구현 안내 |
| empty teams | team 생성 CTA |
| empty permissions | 선택한 resource에 부여된 권한 없음 |
| empty credentials | credential 등록 CTA |
| tab API error | 전체 Admin shell은 유지하고 해당 tab body만 error state |

## Layout 기준

- Admin Console은 card-heavy landing page가 아니라 운영 콘솔이어야 한다.
- 상단에는 조직명, manager badge, 간단한 상태 요약을 둔다.
- Tabs는 상단 고정 영역 아래에 배치하고, body는 table/list 중심으로 구성한다.
- destructive action은 row action menu 또는 detail drawer 안에 두고 확인 dialog를 사용한다.
- 생성/초대/등록처럼 입력이 필요한 action은 modal보다 drawer를 우선 검토한다. 단순 form이면 modal도 가능하다.
- Settings에서 Admin Console로 이동하는 CTA는 manager에게만 표시한다.
- Member에게는 Admin Console의 존재를 과하게 노출하지 않는다.

## 현재 코드 연결

| 파일 | 역할 |
| --- | --- |
| `apps/client/app/features/dashboard/components/Sidebar.tsx` | organization manager에게만 sidebar `관리` 메뉴 노출 |
| `apps/client/app/dashboard/admin/page.tsx` | Admin Console UI shell과 상단 탭 구현 |
| `apps/client/app/features/organization/api/organizationApi.ts` | organization current/member 목록 조회 |
| `apps/client/app/features/organization/components/MemberStateBadge.tsx` | member 상태 badge |
| `apps/client/app/features/organization/components/OrganizationAuthBadge.tsx` | manager/member badge |
| `apps/client/app/features/organization/components/ActiveOrganizationMemberPicker.tsx` | active organization member만 선택하는 공통 picker |
| `apps/client/lib/activeOrganization.ts` | active organization header 생성과 organization 변경 event 발행 |
| `apps/client/app/dashboard/settings/page.tsx` | Settings의 조직 운영 탭 제거, credential/activity read-only 중심 정리 |
| `apps/client/app/dashboard/page.tsx` | manager의 조직 접근 CTA를 Admin Console로 연결 |

현재 Admin Console은 UI/UX 선행 구현이다. 연결 가능한 API는 실제 데이터를 사용하고, 정책/API 범위가 확정되지 않은 action은 disabled 또는 placeholder로 둔다.

| 탭 | 현재 데이터 연결 |
| --- | --- |
| 멤버 | `GET /organizations/{id}/members` 기본 응답 실제 연결. active/invited/suspended 표시, 초대/상태 변경 action은 disabled |
| 팀 | `GET /teams`, `GET /teams/{id}/members` 실제 연결. 생성/수정 action은 disabled |
| 권한 | legacy Settings permission UI 이동 예정 placeholder |
| LLM Credentials | provider/credential 목록 실제 연결. 등록/삭제/sync action은 disabled |
| 지식 기반 | 기존 knowledge base read list 실제 연결. Admin Console용 조직 관리 목록/권한 관리는 후속 API 확인 전까지 disabled |
| 감사 로그 | 현재는 `/users/me/audit-logs` 기반 read-only. 조직 전체 audit API 확정 후 전환 |
| 조직 설정 | 조직명 표시. 수정 action은 정책/API 확정 후 연결 |

## 현재 구현 스냅샷

MBA-84 기준 현재 구현은 "관리 콘솔의 정보 구조와 공통 organization member 기반"을 먼저 만든 상태다.

완료된 것:

- sidebar `관리` 메뉴는 active organization의 `is_manager`가 `true`인 경우에만 표시한다.
- `/dashboard/admin`은 manager guard를 먼저 수행하고, member에게는 manager-only API를 호출하지 않는다.
- Admin Console은 `멤버`, `팀`, `권한`, `LLM Credentials`, `지식 기반`, `감사 로그`, `조직 설정` 상단 탭을 제공한다.
- `멤버` 탭은 `GET /organizations/{id}/members` 기본 응답을 사용해 active/invited/suspended member를 read-only로 표시한다.
- `팀` 탭은 기존 team API와 team member API를 read-only로 연결한다.
- `LLM Credentials`, `지식 기반`, `감사 로그`는 기존 read API가 있는 범위만 연결하고 manager mutation action은 disabled로 둔다.
- Settings는 `조직 접근` 탭을 노출하지 않고, `LLM Credentials`와 `Activity` 중심으로 남긴다.
- Settings의 LLM Credentials는 manager/member 모두 read-only이며 등록, 삭제, model sync, permission grant/revoke action을 제공하지 않는다.
- active organization 변경 시 sidebar와 Admin Console이 같은 event를 기준으로 다시 조회된다.
- organization member 공통 타입/API client/badge/picker 기반은 `apps/client/app/features/organization/` 아래에 분리되어 있다.

아직 구현하지 않은 것:

- organization member invite/update/remove action 연결
- team create/update/deactivate/member add/remove action 연결
- workflow permission grant/update/revoke UI 이동
- LLM credential 등록/삭제/sync/권한 관리 action 연결
- knowledge base organization-level 관리 action 연결
- organization 전체 audit API 전환
- `removed` member를 기본 목록에 함께 보여줄지, 별도 필터 query로 조회할지에 대한 화면 정책

주의할 점:

- `GET /organizations/{id}/members` query가 없으면 removed member는 응답에 포함되지 않는다. 제거된 member까지 보여주는 화면은 `state=removed` query 또는 별도 필터 동작이 필요하다.
- 현재 Admin Console의 제거 member count는 기본 member 응답 기준이다. 전체 removed total을 의미하지 않으며, 정확한 제거 상태 집계는 `state=removed` 조회나 전용 summary API가 연결된 뒤 확정한다.
- Settings 내부에는 이전 `조직 접근` UI에 쓰이던 legacy branch/handler가 일부 남아 있을 수 있다. 현재 navigation에서는 접근되지 않지만, Admin Console mutation 전환이 완료되면 제거 범위를 다시 정리한다.
- Admin Console의 disabled action은 API가 없다는 뜻이 아니라, MBA-84에서는 공통 기반과 read-only 정보 구조만 확정한다는 뜻이다. 실제 조작 action은 MBA-82/MBA-83 또는 후속 이슈에서 연결한다.

## 구현 순서 제안

| 순서 | 작업 |
| --- | --- |
| 1 | Sidebar에 manager-only `관리` 메뉴 추가 |
| 2 | `/dashboard/admin` shell 생성: organization header, manager guard, top tabs |
| 3 | 기존 Settings의 조직 접근 구현을 Admin Console `팀`/`권한` 탭으로 이동할 수 있게 컴포넌트 분리 |
| 4 | `멤버` 탭에 organization member list/read-only 상태 badge부터 구현 |
| 5 | `팀` 탭에 team list를 먼저 표시하고, active member picker는 후속 action 연결 시 추가 |
| 6 | `권한` 탭에 workflow permission grant/update/revoke 연결 |
| 7 | LLM Credentials manager action을 Settings에서 Admin Console로 이동 |
| 8 | 지식 기반/감사 로그는 API 준비 상태에 따라 placeholder 또는 read-only list부터 연결 |
| 9 | Settings는 개인 설정/read-only credential/activity 중심으로 정리 |

## QA 체크리스트

- [ ] manager에게 sidebar `관리`가 보인다.
- [ ] member에게 sidebar `관리`가 보이지 않는다.
- [ ] member가 `/dashboard/admin` 직접 접근 시 manager-only API를 호출하지 않는다.
- [ ] Admin Console 상단에 organization name과 `관리자` badge가 보인다.
- [ ] Admin Console 탭이 `멤버`, `팀`, `권한`, `LLM Credentials`, `지식 기반`, `감사 로그`, `조직 설정` 순서로 보인다.
- [ ] `멤버` 탭에서 기본 member 목록의 invited/active/suspended 상태가 구분된다.
- [ ] `팀` 탭에서 team 목록과 기존 member가 read-only로 표시된다.
- [ ] `권한` 탭은 legacy Settings permission UI 이동 전까지 placeholder로 표시된다.
- [ ] LLM credential 등록/삭제/sync는 Admin Console에서 disabled manager action으로만 보인다.
- [ ] tab 하나의 API 실패가 전체 Admin Console을 깨지 않는다.

## 남은 결정

| 항목 | 결정 필요 |
| --- | --- |
| `/dashboard/admin` 경로명 | `admin`, `manage`, `organization` 중 제품 용어 확정 |
| Settings의 기존 `조직 접근` 구현 제거 시점 | Admin Console 기능 전환 완료 후 내부 legacy 코드를 제거할지 |
| 지식 기반 권한 API 범위 | manager가 실제로 어떤 knowledge base action을 관리할 수 있는지 |
| 감사 로그 API 범위 | 조직 전체 audit endpoint가 있는지, 현재 `/users/me/audit-logs`만 쓸지 |
| workflow manager 전용 관리 화면 | Admin Console과 별도 resource-level 권한 관리 UI가 필요한지 |
