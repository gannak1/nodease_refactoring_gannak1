# Organization Requirements

Status: Verified
Verified Against: feature/mba-119 @ 7aefa84
Related Features: auth, workflow, knowledge, llm-credentials, audit-tracing

## Purpose

Organization 기능은 Nodease의 tenant-like 작업 경계와 RBAC 운영 기반을 담당한다. 현재 구현 범위는 기본 organization foundation 생성, active organization context 조회/선택, organization 이름/options 수정, organization membership 초대/수락/상태 변경/제거, team 생성/수정/멤버 배정/비활성화, workflow 및 LLM credential에 대한 team/user direct permission 조회/부여/회수이다.

Auth는 사용자를 인증하고 signup/Google OAuth 성공 시 기본 organization foundation 생성을 호출한다. Organization은 생성된 organization, membership, team, resource permission의 scope와 운영 변경을 소유한다. Workflow, Knowledge, LLM credential, Audit feature의 리소스별 동작 의미는 각 feature 문서가 소유하며, Organization 문서는 공통 scope/RBAC 경계와 현재 구현된 권한 관리 API만 정의한다.

권한 모델(`auth_state`, 판정 순서, team template 목표 모델)의 기준은 [data_model.md](../../data_model.md)의 RBAC 요약과 [ADR-0006](../../decisions/ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md)이다. 이 문서는 공통 용어와 matrix를 재정의하지 않고 organization feature가 책임지는 적용 지점만 명시한다.

## User Stories

- 신규 사용자는 signup 또는 Google OAuth 성공 후 기본 organization, manager membership, 기본 team을 가진 상태로 서비스를 시작할 수 있다.
- 사용자는 접근 가능한 active organization 목록을 보고 현재 작업할 organization을 선택할 수 있다.
- organization manager는 organization 이름과 options를 수정할 수 있다.
- organization manager는 가입된 user id를 기준으로 멤버를 초대하고, 멤버 상태와 organization 권한을 변경하거나 제거할 수 있다.
- 초대받은 사용자는 본인의 organization 초대를 수락할 수 있다.
- organization manager는 team을 만들고 수정하며, active organization member를 team에 배정하거나 team에서 제거할 수 있다.
- organization manager는 더 이상 운영에 쓰지 않는 team을 비활성화할 수 있다.
- organization manager 또는 대상 resource manager는 workflow/LLM credential 권한을 team 또는 user direct permission으로 부여하거나 회수할 수 있다.
- 멤버는 organization scope 안에서 부여된 resource 권한만 사용할 수 있고, scope 밖 resource는 존재 여부를 알 수 없어야 한다.

## Functional Requirements

- ORG-REQ-001: Auth signup 또는 Google OAuth 신규 사용자 생성 성공 시 시스템은 기본 organization, active manager membership, `Default` team, 기본 team membership을 준비해야 한다.
- ORG-REQ-002: 시스템은 standalone organization 생성 API를 제공하지 않는다. 기본 organization 생성은 auth 가입 경로에서 호출되는 foundation 생성 책임으로 제한한다.
- ORG-REQ-003: `GET /organizations`는 현재 사용자가 active membership으로 접근 가능한 active organization만 반환해야 한다.
- ORG-REQ-004: `GET /organizations/memberships`는 현재 사용자의 active 또는 invited organization membership 요약을 반환해야 한다.
- ORG-REQ-005: 조직 scope API는 `X-Organization-Id` header로 active organization을 결정해야 하며, 서버는 active organization을 session/cookie에 저장하지 않아야 한다 ([ADR-0009](../../decisions/ADR-0009-active-organization-header-context.md)).
- ORG-REQ-006: `GET /organizations/current`는 `X-Organization-Id`가 active organization membership scope 안에 있을 때 현재 organization 상세를 반환해야 한다.
- ORG-REQ-007: `GET /organizations/{organization_id}`는 현재 사용자가 접근 가능한 active organization 상세만 반환해야 한다.
- ORG-REQ-008: `PATCH /organizations/{organization_id}`는 path organization과 `X-Organization-Id`가 일치하고 현재 사용자가 organization manager일 때 `name` 또는 `options`를 수정해야 한다.
- ORG-REQ-009: organization 수정은 빈 PATCH body, blank name, null options를 거부해야 한다.
- ORG-REQ-010: organization 수정 성공은 `organization.update` audit을 기록해야 한다.
- ORG-REQ-011: organization member 목록 조회는 organization manager만 수행할 수 있어야 한다.
- ORG-REQ-012: member 목록 조회는 기본적으로 active, invited, suspended membership을 반환하고, `state=removed`가 지정되면 removed membership을 조회할 수 있어야 한다.
- ORG-REQ-013: organization manager는 active user id와 `organization_auth_state`(`member` 또는 `manager`)로 멤버를 초대할 수 있어야 한다.
- ORG-REQ-014: 멤버 초대는 자기 자신 초대를 거부해야 한다.
- ORG-REQ-015: 이미 active 또는 invited인 멤버를 다시 초대하면 기존 membership을 반환해야 한다.
- ORG-REQ-016: suspended 멤버 재초대는 거부하고, removed 멤버 재초대는 기존 membership을 invited 상태로 되살려야 한다.
- ORG-REQ-017: 멤버 초대 성공은 `organization.invite` audit을 기록해야 한다.
- ORG-REQ-018: 초대 수락은 초대받은 본인만 수행할 수 있으며 manager 권한을 요구하지 않아야 한다.
- ORG-REQ-019: active 초대를 다시 수락하면 현재 membership을 반환해야 하고, suspended/removed 초대 수락은 거부해야 한다.
- ORG-REQ-020: 초대 수락 성공은 `organization.member.accept` audit을 기록해야 한다.
- ORG-REQ-021: organization manager는 active member를 suspended로 변경하거나 suspended member를 active로 되돌릴 수 있어야 한다.
- ORG-REQ-022: organization manager는 active member의 `organization_auth_state`를 `member` 또는 `manager`로 변경할 수 있어야 한다.
- ORG-REQ-023: member update는 invited member의 강제 active/suspended 전환, removed member update, 자기 자신의 상태/권한 변경, 마지막 active manager 제거/강등을 거부해야 한다.
- ORG-REQ-024: member update 성공은 `organization.member.update` audit을 기록해야 하며, no-op update는 audit을 기록하지 않아야 한다.
- ORG-REQ-025: organization manager는 자기 자신과 마지막 active manager를 제외한 멤버를 removed 상태로 변경할 수 있어야 한다.
- ORG-REQ-026: 멤버 제거는 해당 user의 team membership, user workflow direct permission, user LLM credential direct permission을 함께 정리해야 한다.
- ORG-REQ-027: 멤버 제거 성공은 `organization.member.remove` audit과 cleanup aggregate `permission.revoke` audit을 기록해야 한다.
- ORG-REQ-028: 이미 removed인 멤버 제거 요청은 idempotent success로 처리해야 한다.
- ORG-REQ-029: team 목록/생성/수정/멤버 조회/멤버 추가/멤버 제거/비활성화는 organization manager만 수행할 수 있어야 한다 ([ADR-0011](../../decisions/ADR-0011-team-router-rbac-service-boundary.md)).
- ORG-REQ-030: team 목록 조회는 active/inactive team을 함께 반환하고, `limit`은 1 이상 100 이하로 제한해야 한다.
- ORG-REQ-031: team 생성은 active organization scope 안에서 unique team name, optional description, `is_auto_add` 값을 저장해야 한다.
- ORG-REQ-032: team 수정은 active team에 대해서만 name, description, managed_by, is_auto_add를 변경할 수 있어야 한다.
- ORG-REQ-033: team `managed_by`는 비활성 user나 organization scope 밖 user를 거부해야 한다.
- ORG-REQ-034: team member 추가는 active team과 active organization membership을 가진 user만 허용해야 한다.
- ORG-REQ-035: 기존 team membership 추가와 없는 team membership 제거는 idempotent하게 처리해야 한다.
- ORG-REQ-036: team 비활성화는 team을 삭제하지 않고 `is_active=false`, `deactivated_at` 설정으로 처리해야 하며, 이미 inactive인 team에는 idempotent success를 반환해야 한다.
- ORG-REQ-037: resource permission 관리 API는 workflow와 LLM credential에 대한 team permission 및 user direct permission 조회/부여/회수를 제공해야 한다.
- ORG-REQ-038: permission 조회/변경은 organization manager 또는 대상 workflow/LLM credential의 `manage` 권한 보유자만 수행할 수 있어야 한다.
- ORG-REQ-039: permission 부여는 active team 또는 active organization member user만 grantee로 허용해야 한다.
- ORG-REQ-040: permission 부여 요청은 canonical resource `auth_state`만 허용해야 한다. legacy 값(`read/write/execute/admin`)은 기존 row 해석에만 사용하고 신규 요청에서는 거부해야 한다.
- ORG-REQ-041: permission upsert/delete는 row 단위 data-change audit(`team_workflow_permission.created`, `team_workflow_permission.updated`, `team_workflow_permission.deleted`, `team_llm_permission.*`, `user_workflow_permission.*`, `user_llm_permission.*`)을 기록해야 한다.
- ORG-REQ-042: organization scope 밖 resource는 `404 resource.not_found`로 숨기고, scope 안 권한 부족은 `403 permission.denied`로 응답해야 한다 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)).
- ORG-REQ-043: 클라이언트는 active organization id를 localStorage의 `moduly_active_organization_id`에 저장하고, `apiClient` 요청에 `X-Organization-Id` header를 자동 첨부해야 한다.
- ORG-REQ-044: dashboard layout은 active organization을 확인하고, 하나뿐이면 자동 선택하며, 여러 개면 사용자가 선택하도록 해야 한다.
- ORG-REQ-045: dashboard sidebar는 현재 organization 이름과 manager 여부를 조회하고, manager가 아닌 사용자에게 관리 메뉴를 숨겨야 한다.
- ORG-REQ-046: admin console은 manager에게 멤버/팀/workflow permission/LLM credential permission 관리 UI를 제공하고, manager가 아닌 사용자에게 관리 권한 없음 상태를 표시해야 한다.

## Policies And Edge Cases

- Organization scope 판정과 resource permission 판정 순서는 [data_model.md](../../data_model.md)의 RBAC 요약을 따른다. active membership row가 우선이며, invited/suspended/removed membership은 fail-closed다.
- membership row가 없는 legacy organization `created_by` 또는 `managed_by` user만 manager fallback을 받는다.
- Organization membership 권한은 `member`와 `manager`만 사용한다. Resource permission `auth_state`(`none/viewer/operator/builder/manager`, audit용 `auditor/raw_auditor`)와 혼동하지 않는다.
- user direct permission은 additive allow 전용이다. team 권한을 낮추지 못하고 explicit deny는 없다.
- 현재 user direct permission API와 cleanup은 workflow와 LLM credential만 구현한다. user knowledge permission과 user audit permission은 현재 구현 범위가 아니다.
- Team knowledge permission model은 존재하지만 organization permission 관리 API/UI는 현재 knowledge permission grant/revoke를 제공하지 않는다.
- 기본 organization foundation은 `Default` team 하나를 만든다. data model의 Admin/Builder/Operator/Viewer/Auditor team template preset 자동 생성은 현재 구현 범위가 아니다.
- 멤버 초대 API는 email invitation이 아니라 가입된 user UUID 기반 초대다. email 검색/초대 UX는 현재 구현 범위가 아니다.
- Admin console은 organization 관리의 주 UI다. Settings page에는 일부 access-management 코드가 남아 있지만 현재 보이는 탭에서는 노출되지 않는다.
- 클라이언트의 manager-only 메뉴 숨김은 UX 차단이다. 최종 보안 판단은 Gateway endpoint와 shared permission helper가 수행한다.
- Audit metadata에는 actor snapshot, request metadata, permission cleanup count, resource id가 포함될 수 있다. secret value, raw credential, token 원문은 기록하지 않는다.

## Open Questions

- 별도 organization 생성/비활성화 API를 제공할지, 또는 auth 기반 기본 organization 생성만 유지할지 결정해야 한다.
- email 기반 멤버 초대와 user directory 검색을 organization 범위에 포함할지 결정해야 한다.
- data model에 있는 Team Template preset(Admin/Builder/Operator/Viewer/Auditor)을 실제 자동 생성할지 결정해야 한다.
- Knowledge permission grant/revoke와 audit permission grant/revoke를 organization 관리 API/UI 범위에 포함할지 결정해야 한다.
- Settings page의 숨겨진 access-management 코드를 제거할지, admin console과 통합할지 결정해야 한다.
