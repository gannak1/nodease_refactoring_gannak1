# Organization Test Cases

Status: Draft
Verified Against: feature/mba-119 @ 7aefa84

## Minimum Failure Rule

이 문서는 정상 시나리오를 길게 반복하지 않고, 각 organization/RBAC 조건을 깨뜨리는 최소 입력, 상태, 또는 관찰값을 기준으로 테스트 케이스를 정의한다.

각 테스트는 해당 최소 조건 하나만으로 실패를 유도하거나, 성공 경로의 필수 관찰값 하나가 빠졌을 때 실패로 판단할 수 있어야 한다.

다음 항목은 이 문서의 test case로 늘리지 않는다.

- 단순 성공 경로 반복, 표시 문구/색상/레이아웃 세부값
- 다른 feature가 소유한 credentials, knowledge, audit tab 내부 동작
- API spec의 모든 field를 다시 나열하는 schema mirror test
- 같은 정책을 endpoint별로 반복하는 중복 happy-path test

## Current Coverage Notes

현재 backend coverage는 `apps/gateway/tests/api/test_organizations_api.py`, `apps/gateway/tests/api/test_teams_api.py`, `apps/gateway/tests/api/test_permissions_api.py`, `apps/gateway/tests/services/test_organization_member_service.py`, `apps/gateway/tests/services/test_team_service_permissions.py`, `apps/shared/tests/services/test_permissions.py`, `apps/shared/tests/services/test_permission_enforcement.py`, `tests/db/test_organization_user_schema.py`, `tests/db/test_team_permission_constraints.py`, `tests/test_permission_schema.py`, `apps/shared/tests/test_organization_membership_schema.py`에 분산되어 있다.

현재 client coverage는 active organization을 소비하는 knowledge/workflow 일부 테스트가 있으나, AdminConsolePage의 member/team/permission 관리 UI에 대한 직접 component test는 확인되지 않았다.

## Unit Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| ORG-TC-U001 | 기본 organization foundation은 organization, manager membership, Default team, team membership을 함께 만들어야 한다. | 신규 user에 대해 네 요소 중 하나가 없다. | 테스트 실패. |
| ORG-TC-U002 | 기본 organization foundation은 기존 active organization이 있으면 중복 생성하지 않아야 한다. | active membership이 이미 있는데 새 organization이 추가된다. | 기존 organization id 반환. |
| ORG-TC-U003 | active organization 목록은 active membership만 사용해야 한다. | invited/suspended/removed membership organization이 결과에 포함된다. | 테스트 실패. |
| ORG-TC-U004 | membership summary는 active/invited만 반환해야 한다. | invited membership이 빠지거나 removed/suspended membership이 포함된다. | 테스트 실패. |
| ORG-TC-U005 | member list 기본값은 removed를 제외하고, `state=removed`는 removed만 조회해야 한다. | 기본 조회에 removed가 포함되거나 removed 조회가 빈 목록이다. | 테스트 실패. |
| ORG-TC-U006 | organization auth state는 `member` 또는 `manager`만 허용해야 한다. | `owner`, `admin`, `viewer`가 organization auth state로 통과한다. | 테스트 실패. |
| ORG-TC-U007 | member invitation은 자기 자신 초대와 잘못된 재초대 상태 전이를 거부해야 한다. | self invite가 성공하거나 suspended member가 invitation으로 invited가 된다. | `400` 또는 `409`. |
| ORG-TC-U008 | removed member 재초대는 기존 membership을 invited로 되살려야 한다. | 새 duplicate membership을 만들거나 removed 상태가 유지된다. | 기존 row의 state가 invited로 변경된다. |
| ORG-TC-U009 | invited/removed member는 PATCH로 active/suspended 전환할 수 없어야 한다. | invited 또는 removed member update가 성공한다. | `409`. |
| ORG-TC-U010 | member update는 빈 update와 no-op audit을 구분해야 한다. | 빈 body가 성공하거나 no-op PATCH가 audit row를 만든다. | 빈 body는 `400`, no-op은 audit 없음. |
| ORG-TC-U011 | 자기 자신 또는 마지막 active manager의 상태/권한 변경은 거부해야 한다. | self update 또는 마지막 manager 강등/제거가 성공한다. | `400` 또는 `409`. |
| ORG-TC-U012 | member removal은 team membership, user direct permission, App 생성 권한 row를 정리해야 한다. | removed 처리 후 team membership, user workflow/LLM direct permission, `user_app_creation_permissions` row 중 하나가 남는다. | cleanup count와 삭제가 일치한다. |
| ORG-TC-U013 | 이미 removed인 member removal은 idempotent해야 한다. | removed member DELETE가 404 또는 409를 반환한다. | `status=removed`, cleanup count 0. |
| ORG-TC-U014 | team mutation은 organization manager scope 안에서만 수행되어야 한다. | scope 밖 user나 non-manager가 team create/update/member mutation에 성공한다. | `404` 또는 `403`. |
| ORG-TC-U015 | team `managed_by`와 team member add는 active organization user만 허용해야 한다. | scope 밖, inactive, membership 없는 user가 저장된다. | `400` 또는 `404`. |
| ORG-TC-U016 | permission grant는 active team 또는 active organization member만 grantee로 허용해야 한다. | inactive team이나 inactive/scope 밖 user에게 permission row가 생성된다. | `400` 또는 `404`. |
| ORG-TC-U017 | effective resource permission은 additive allow와 fail-closed를 지켜야 한다. | user direct가 team 권한을 낮추거나 invalid/audit-only auth_state가 operational permission을 허용한다. | 가장 강한 유효 권한 또는 deny. |

## API Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| ORG-TC-A001 | organization scope endpoint는 `X-Organization-Id` header를 요구해야 한다. | header 없이 scope endpoint를 호출한다. | `400`, `organization.required`. |
| ORG-TC-A002 | organization header와 UUID path/body 값은 형식을 검증해야 한다. | `X-Organization-Id=not-a-uuid` 또는 malformed UUID를 보낸다. | `422`, `validation.failed`. |
| ORG-TC-A003 | path organization과 header organization mismatch는 숨겨야 한다. | path id와 header id가 다르다. | `404`, `resource.not_found`. |
| ORG-TC-A004 | scope 밖 organization/resource/team/user는 숨겨야 한다. | active membership이 없는 organization 또는 다른 organization resource를 요청한다. | `404`, `resource.not_found`. |
| ORG-TC-A005 | scope 안 non-manager는 manager API를 사용할 수 없어야 한다. | active member가 organization/team/member manager endpoint를 호출한다. | `403`, `permission.denied`. |
| ORG-TC-A006 | organization PATCH는 빈 update, blank name, null options를 거부해야 한다. | `{}`, blank `name`, 또는 null `options`를 보낸다. | `400`, `validation.failed`. |
| ORG-TC-A007 | member list는 invalid state filter를 거부해야 한다. | `?state=unknown`. | `400`, `Invalid membership state.` |
| ORG-TC-A008 | member invite/update request는 unknown body field를 거부해야 한다. | body에 정의되지 않은 field를 추가한다. | `422` validation envelope. |
| ORG-TC-A009 | `/members/me/accept`는 literal `me` route로 처리되어야 한다. | `/members/me/accept`가 `{user_id}` route로 해석된다. | 테스트 실패. |
| ORG-TC-A010 | member removal response는 cleanup summary를 포함해야 한다. | 성공 응답에서 `removed_team_memberships` 또는 `revoked_user_permissions`가 빠진다. | 테스트 실패. |
| ORG-TC-A011 | team list는 invalid limit을 거부해야 한다. | `limit=0`, `limit=101`, 또는 non-integer. | `422`, `validation.failed`. |
| ORG-TC-A012 | team create/update는 duplicate name과 blank name을 거부해야 한다. | duplicate create 또는 blank name patch가 성공한다. | `409` 또는 `400`. |
| ORG-TC-A013 | team member add/remove/deactivate는 idempotent 조건을 지켜야 한다. | existing add, missing remove, inactive deactivate 중 하나가 error를 반환한다. | success 응답. |
| ORG-TC-A014 | permission list는 team/user direct entries를 분리해야 한다. | user direct permission이 `team_permissions`에 섞인다. | 테스트 실패. |
| ORG-TC-A015 | permission PUT은 organization manager 또는 target resource manager만 허용해야 한다. | manage 권한 없는 active member가 permission을 저장한다. | `403`, `permission.denied`. |
| ORG-TC-A016 | permission PUT은 canonical auth_state만 허용해야 한다. | `{ "auth_state": "admin" }` 또는 audit-only value가 통과한다. | `422`, `validation.failed`. |
| ORG-TC-A017 | permission DELETE는 missing row를 숨기고, existing direct row는 target user active 여부와 무관하게 회수해야 한다. | missing row가 success거나 deactivated/removed user의 existing direct row 삭제가 실패한다. | `404` 또는 permission row 삭제. |

## E2E Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| ORG-TC-E001 | dashboard 진입은 organization이 하나뿐이면 자동 선택하고 여러 개면 선택 화면을 보여야 한다. | 단일 organization인데 선택 화면이 유지되거나 복수 organization인데 임의 선택된다. | 자동 저장 또는 `작업 조직 선택` 표시. |
| ORG-TC-E002 | active organization 선택 후 API 요청은 organization header를 보내야 한다. | 선택 후 `/organizations/current` 요청에 header가 없다. | 테스트 실패. |
| ORG-TC-E003 | Sidebar와 AdminConsolePage는 non-manager에게 관리 표면을 숨겨야 한다. | `is_manager=false`인데 관리 nav 또는 관리 테이블이 보인다. | 관리 nav 숨김, `관리 권한 없음` 표시. |
| ORG-TC-E004 | member invite/update/remove UI는 필요한 payload와 confirm gate를 지켜야 한다. | invite payload가 비었거나 privilege/destructive action이 confirm 없이 호출된다. | API 미호출 또는 confirm 후 호출. |
| ORG-TC-E005 | self 또는 마지막 manager action은 강등/제거를 막아야 한다. | 자기 자신 또는 마지막 manager row에서 강등/제거 button이 활성화된다. | disabled button. |
| ORG-TC-E006 | inactive team detail은 member add control을 숨겨야 한다. | inactive team에서 `추가` button이 활성화된다. | `비활성 팀에는 멤버를 추가할 수 없습니다.` 표시. |
| ORG-TC-E007 | permission tab은 resource와 active grantee 없이는 grant를 막아야 한다. | workflow/credential id 없거나 inactive team/member로 PUT 요청이 나간다. | save disabled 또는 후보 제외. |
| ORG-TC-E008 | active organization 변경 event 후 Sidebar는 organization name/manager flag를 새로 조회해야 한다. | event dispatch 후 이전 organization 이름이 유지된다. | `/organizations/current` 재호출. |

## Permission Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| ORG-TC-P001 | organization scope는 active membership과 active organization/user를 기준으로 해야 한다. | invited/suspended/removed membership, inactive organization, deactivated user 중 하나가 scope access를 허용한다. | access false. |
| ORG-TC-P002 | legacy created_by/managed_by fallback은 membership row가 없을 때만 manager로 동작해야 한다. | membership row가 있는데 fallback이 우선하거나, row가 없는데 legacy owner가 거부된다. | 정책에 맞게 허용/거부. |
| ORG-TC-P003 | resource organization mismatch는 creator fallback을 사용하지 않아야 한다. | 다른 organization header로 workflow owner fallback이 허용된다. | 404 또는 permission false. |
| ORG-TC-P004 | organization manager override는 resource permission helper의 공통 scope 경계에서 적용되어야 한다. | manager가 scope 안 resource의 organization-level manage/use 판정에서 거부된다. | manager auth state. |
| ORG-TC-P005 | resource별 추가 gate는 organization manager override만으로 자동 우회되지 않아야 한다. | organization manager라는 이유만으로 resource feature가 소유한 추가 authorization gate가 생략된다. | 해당 feature gate에서 별도 판단. |
| ORG-TC-P006 | workflow permission source 목록은 team과 user direct source를 구분해야 한다. | source type 또는 grantee id/name이 누락된다. | source list schema validation 통과. |
| ORG-TC-P007 | permission denied는 scope 안 denial에만 기록되고 scope 밖 resource는 숨겨야 한다. | scope 안 denial audit이 없거나 scope 밖 접근에 403/permission.denied audit이 발생한다. | audit recorded 또는 `404 resource.not_found`. |
| ORG-TC-P008 | auth failure는 organization permission check보다 먼저 닫혀야 한다. | token 없음인데 organization query나 body validation이 먼저 실행된다. | `auth.required`. |
