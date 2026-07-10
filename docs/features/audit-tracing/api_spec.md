# Audit Tracing API Spec

Status: Draft
Verified Against: TBD

## Gateway Query Surface

Audit/Tracing feature는 별도 화면용 중복 endpoint를 만들지 않는다. Organization-scoped audit 검색/상세의 HTTP 계약은 [Admin Dashboard API spec](../admin-dashboard/api_spec.md)이 소유한다.

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| GET | `/api/v1/admin/audit-logs` | organization audit 검색/필터 | audit `auditor` 이상 |
| GET | `/api/v1/admin/audit-logs/{audit_log_id}` | sanitized audit detail와 optional change summary | audit `auditor` 이상 |

Actor access profile/team-membership/resource source/action은 [Organization API spec](../organization/api_spec.md)의 manager-only endpoint를 사용한다. Audit endpoint는 Organization/RBAC mutation을 수행하지 않는다.

## Request And Response Models

### `AuditLogDetailResponse`

기존 audit list item field와 sanitized `audit_metadata`를 포함한다. MBA-188 safe metadata에는 team membership action의 advisory `affected_resource_source_count`가 포함될 수 있다. MBA-188 target은 다음 additive field를 포함한다.

```json
{
  "change_summary": {
    "before": {
      "membership_state": "active"
    },
    "after": {
      "membership_state": "suspended"
    }
  }
}
```

`change_summary`는 object 또는 null이다.

| Action | Target | Allowed fields |
| --- | --- | --- |
| `organization.member.update` | `organization_membership` | `organization_id`, `user_id`, `membership_state`, `organization_auth_state` |
| `team_membership.created`, `team_membership.deleted` | `team_membership` | `grantee_organization_id`, `team_id`, `user_id` |
| `user_workflow_permission.created/updated/deleted` | `user_workflow_permission` | `grantee_organization_id`, `user_id`, `workflow_id`, `auth_state` |
| `user_knowledge_permission.created/updated/deleted` | `user_knowledge_permission` | `grantee_organization_id`, `user_id`, `knowledge_base_id`, `auth_state` |
| `user_llm_permission.created/updated/deleted` | `user_llm_permission` | `grantee_organization_id`, `user_id`, `llm_credential_id`, `auth_state` |
| `user_app_creation_permission.created`, `user_app_creation_permission.deleted` | `user_app_creation_permission` | `user_id`, `grantee_organization_id` |

Target/action이 allowlist에 없거나 safe field가 없으면 null을 반환한다. DB `before`/`after`의 allowlist 밖 key, nested payload, secret 계열 값은 반환하지 않는다.

MBA-188 manual audit은 update에도 target별 complete safe snapshot을 저장한다. Create는 `after`, delete는 `before`, update는 `before`와 `after`의 `organization_id`/`grantee_organization_id`가 모두 request organization과 일치해야 summary를 반환한다. Historical same-organization opaque UUID는 유지할 수 있지만 current resource name/path를 resolve하지 않는다. 필요한 snapshot의 organization provenance가 없거나 다르면 null이다.

`policy.block` failure event는 row 변경이 아니므로 `change_summary`가 null이다. Audit detail metadata allowlist는 `organization_id`, `request_id`, sanitized `reason`, existing safe `summary`, `target_user_id`, `requested_action`, `policy_reason`, `resource_type`, `resource_id`, `team_id`, advisory `affected_resource_source_count`다. Resource/team field는 scope를 확인한 policy block 또는 applied team action에서만 기록한다. 임의 nested request body, target name/email, expected/current snapshot은 포함하지 않는다.

### `AuditRecorder` application port

HTTP model이 아니라 신규 security mutation use case가 의존하는 internal contract다.

필수 입력:

- canonical action/category
- actor id/type
- target type/id
- organization id
- optional reason
- blocked attempt의 `requested_action`, `policy_reason`
- safe before/after
- request id와 safe actor snapshot

Recorder adapter는 caller의 DB transaction에 AuditLog row를 추가하고 commit하지 않는다. MBA-188은 durable outbox를 선택지로 구현하지 않는다.

Optional reason은 Organization API spec의 normalization/validation을 통과한 뒤 organization 설정으로 약화할 수 없는 shared fail-closed redaction baseline을 적용한 값만 recorder에 전달한다. Redaction 실패 시 recorder는 raw fallback을 저장하지 않고 use case transaction을 실패시킨다.

Applied mutation은 row-level canonical action을 사용한다. Membership/role과 App creation은 `category="action"`, team membership과 user direct permission은 `category="data_change"`다. Scope 안 policy block은 `action="policy.block"`, `category="action"`, `status="failure"`, scoped organization membership target과 safe `requested_action`/`policy_reason` metadata를 사용한다. Optional resource/team id는 scope 확인 뒤에만 metadata에 포함하고 name/email/raw expected state는 저장하지 않는다. Permission 부족은 `permission.denied`이며 target scope 확인 전에는 target-aware metadata를 남기지 않는다. Block result는 audit commit 후 HTTP error로 mapping하며, hidden 404와 validation/no-op은 actor access audit을 만들지 않는다.

Actor access `policy_reason` allowlist는 `access_management.self_control_forbidden`, `access_management.last_active_manager`, `access_management.manager_override_active`, `access_management.member_state_not_manageable`, `access_management.target_user_inactive`, `access_management.stale_state`다.

## Errors

| Status | Condition |
| ---: | --- |
| 400 | audit period 또는 organization header business validation 실패 |
| 401 | 미인증 |
| 403 | organization scope 안 audit reader 권한 부족 |
| 404 | scope 밖 또는 존재하지 않는 audit log |
| 422 | UUID/query schema validation 실패 |
| 500 | Access mutation/policy block의 required audit persistence 실패. Safe `audit.persistence_failed`만 반환 |

Actor access mutation의 400/403/404/409/422는 Organization API spec을 따른다.

## Permissions

- Audit list/detail은 `auditor` 이상이다.
- Actor access profile/mutation은 ADR-0009의 organization manager 판정을 통과한 caller 전용이다.
- `raw_auditor`는 trace visibility policy의 raw access 후보일 뿐 actor mutation 권한이 아니다.
- Organization scope 밖 audit/resource는 존재를 숨긴다.
