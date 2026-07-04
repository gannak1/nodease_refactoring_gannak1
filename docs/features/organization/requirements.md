# Organization Requirements

Status: Draft
Related Features: auth, workflow, knowledge, llm-credentials, audit-tracing, admin-dashboard

## Purpose

조직(organization), 팀, 멤버십 관리와 RBAC 권한 부여/차단을 담당하는 기반 feature다. 이미 구현돼 있으며, [PRD](../../PRD.md) 시나리오 2(조직/권한 관리)의 본체이고 다른 모든 feature의 권한 판정 전제다.

권한 모델(auth_state, 판정 순서, team template)의 기준은 [data_model.md](../../data_model.md)의 RBAC 요약과 [ADR-0006](../../decisions/ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md)이며, 이 문서에서 재정의하지 않는다.

## User Stories

- 플랫폼 관리자로서, 조직에 멤버를 이메일로 초대하고 수락/상태 변경/제거를 관리하고 싶다.
- 플랫폼 관리자로서, 팀을 만들고 멤버를 배정하고 필요하면 팀을 비활성화하고 싶다.
- 플랫폼 관리자로서, 팀 또는 개인 단위로 workflow/LLM credential 권한(auth_state)을 부여/회수하고 싶다.
- 멤버로서, 초대를 수락하고 여러 조직 중 작업할 active organization을 선택하고 싶다.
- 멤버로서, 권한이 없는 리소스에 접근했을 때 왜 거부됐는지(403) 알 수 있어야 하고, 다른 조직의 리소스는 존재조차 몰라야 한다(404).

## Functional Requirements

- 조직 생성/수정/조회. 수정은 organization owner/manager만 가능하며 header 조직과 path 조직이 일치해야 한다 ([ADR-0009](../../decisions/ADR-0009-active-organization-header-context.md)).
- Active organization context: 모든 조직 scope API는 `X-Organization-Id` header로 조직을 결정하고, `GET /organizations/memberships`로 소속 목록을 제공한다.
- 멤버십 관리: 초대/수락/상태 변경/제거. 각각 `organization.invite`, `organization.member.accept`, `organization.member.update`, `organization.member.remove` audit을 기록한다 ([ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)).
- 팀 관리: 생성/목록/멤버 배정·제거/비활성화. 권한 판정과 조회는 `TeamService`가 소유한다 ([ADR-0011](../../decisions/ADR-0011-team-router-rbac-service-boundary.md)). `managed_by`는 같은 조직 scope 안의 active user만 허용한다.
- 권한 부여/회수: team/user × resource별 permission row를 생성/수정/삭제하고, row별 data-change audit(`team_workflow_permission.created` 등)을 기록한다.
- 권한 차단: scope 밖 리소스는 `404 resource.not_found`, scope 안 권한 부족은 `403 permission.denied` + audit ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)).
- 권한 신청 (PRD FR-041, 신규, [ADR-0014](../../decisions/ADR-0014-permission-request-and-app-creation-permission.md)): App 생성(`POST /apps`, "새 모듈")에 권한 검사를 도입한다. organization owner/manager 또는 `user_app_creation_permissions` row 보유자만 생성할 수 있고, 차단된 사용자에게는 안내와 함께 권한 신청 UI를 제공한다. 신청은 `permission_requests`에 요청 권한(`app.create`)과 신청 사유를 담아 저장하며, 같은 조직에 pending 신청이 있으면 새 신청을 거부하고 거절된 뒤에는 재신청할 수 있다. 배포 권한은 생성자에게 자동 부여되는 workflow manager permission으로 따라오므로 별도 신청 항목을 두지 않는다. 제출/승인/거절은 `permission_request.created/approved/rejected`, 승인에 따른 부여는 `user_app_creation_permission.created`로 audit에 기록한다 ([ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)). 관리자 측 목록 조회와 승인/거절은 [admin-dashboard](../admin-dashboard/requirements.md) FR-014의 범위다.

## Policies And Edge Cases

- 판정 순서와 우선순위 규칙은 [data_model.md](../../data_model.md)의 RBAC 요약을 따른다. invited/suspended/removed membership은 fail-closed이며, membership row가 없는 legacy owner/manager만 호환 fallback을 받는다.
- user direct permission은 additive allow 전용이다. team 권한을 낮추지 못하고 explicit deny는 없다.
- 멤버 제거 시 해당 user의 permission cleanup은 aggregate audit(`permission.revoke` + `reason='organization.member.remove'`)으로 기록한다. cleanup 대상에는 `user_app_creation_permissions`도 포함한다 ([ADR-0014](../../decisions/ADR-0014-permission-request-and-app-creation-permission.md) — 승인과 멤버 제거가 경합해도 최종 상태가 정리되는 안전망).
- 이미 inactive인 팀의 비활성화 요청은 같은 조직 manager라면 idempotent success로 처리한다 ([ADR-0011](../../decisions/ADR-0011-team-router-rbac-service-boundary.md)).
- permission grant 요청은 canonical auth_state 값만 받는다. legacy 값(`read/write/execute/admin`)은 기존 row 해석에만 사용하고 신규 요청에서는 거부한다.
- 서버는 active organization을 session/cookie에 저장하지 않는다. header가 없는 legacy 경로만 제한적 primary organization fallback을 사용한다.
- App 생성 권한 검사 도입 시 기존 member에 대한 backfill 마이그레이션은 하지 않는다 (실서비스 데이터 없음, [ADR-0014](../../decisions/ADR-0014-permission-request-and-app-creation-permission.md)). 데모/개발 환경은 seed가 계정별 권한을 구성한다 — 관리자는 owner/manager로 자동 허용, 기존 author 계정은 `user_app_creation_permissions` row 보유, 신입 계정은 row 없음.
- App 생성 차단은 [ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)에 따라 `403 permission.denied` + audit으로 기록하고, 클라이언트는 이 응답에서 권한 신청 UI로 연결한다.
- 이미 처리된(승인/거절) 권한 신청의 중복 처리 요청은 거부한다. pending 신청의 동시 승인/거절 경합이 중복 부여로 이어지지 않아야 한다.

## Open Questions

- Team template preset(Admin/Builder/Operator/Viewer/Auditor)의 자동 생성이 현재 코드에 구현돼 있는지 확인 필요 — 문서상 기준은 [data_model.md](../../data_model.md)의 Team Template 표.
- 멤버십 관리 UI의 범위: BE API는 구현돼 있으나 full 관리 UI는 후속 범위로 남아 있었다. 시나리오 2 데모에 필요한 최소 UI 범위 확정 필요.
- 다중 organization switcher UX (header context 선택/전달 UI).
