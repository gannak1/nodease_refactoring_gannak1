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
- 권한 신청 (PRD FR-041, 신규): workflow 생성/배포 권한이 없는 사용자에게 차단 안내를 표시하고, 요청 권한과 신청 사유를 담은 권한 신청을 제출받는다. 현재 코드에는 초대(invite)만 있고 신청(request) 흐름은 없다. 제출/승인/거절은 `permission_request.created/approved/rejected`로 audit에 기록한다 ([ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)). 관리자 측 목록 조회와 승인/거절은 [admin-dashboard](../admin-dashboard/requirements.md) FR-014의 범위다.

## Policies And Edge Cases

- 판정 순서와 우선순위 규칙은 [data_model.md](../../data_model.md)의 RBAC 요약을 따른다. invited/suspended/removed membership은 fail-closed이며, membership row가 없는 legacy owner/manager만 호환 fallback을 받는다.
- user direct permission은 additive allow 전용이다. team 권한을 낮추지 못하고 explicit deny는 없다.
- 멤버 제거 시 해당 user의 permission cleanup은 aggregate audit(`permission.revoke` + `reason='organization.member.remove'`)으로 기록한다.
- 이미 inactive인 팀의 비활성화 요청은 같은 조직 manager라면 idempotent success로 처리한다 ([ADR-0011](../../decisions/ADR-0011-team-router-rbac-service-boundary.md)).
- permission grant 요청은 canonical auth_state 값만 받는다. legacy 값(`read/write/execute/admin`)은 기존 row 해석에만 사용하고 신규 요청에서는 거부한다.
- 서버는 active organization을 session/cookie에 저장하지 않는다. header가 없는 legacy 경로만 제한적 primary organization fallback을 사용한다.

## Open Questions

- 권한 신청의 저장 모델(테이블) — 현재 코드와 [data_model.md](../../data_model.md) 계획 테이블에 없는 신규 테이블이며, 이 feature 설계에서 data_model 갱신과 함께 정의한다.
- 권한 신청 승인이 부여하는 권한의 실체와 부여 메커니즘 — workflow 생성 권한은 리소스별 permission row로 표현할 수 없고 현재 생성 엔드포인트에는 권한 검사가 없다. membership 수준 auth_state 확장, Builder team 배정 등 후보 중 이 feature 설계에서 확정하며, 권한 판정 모델 변경이므로 ADR 후보다.
- Team template preset(Admin/Builder/Operator/Viewer/Auditor)의 자동 생성이 현재 코드에 구현돼 있는지 확인 필요 — 문서상 기준은 [data_model.md](../../data_model.md)의 Team Template 표.
- 멤버십 관리 UI의 범위: BE API는 구현돼 있으나 full 관리 UI는 후속 범위로 남아 있었다. 시나리오 2 데모에 필요한 최소 UI 범위 확정 필요.
- 다중 organization switcher UX (header context 선택/전달 UI).
