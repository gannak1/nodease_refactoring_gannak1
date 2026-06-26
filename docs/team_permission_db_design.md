# Team Permission DB Design

## 목적

Team 기반 권한 모델을 GitHub식 구조에 맞춰 정리한다.

핵심 원칙은 다음과 같다.

- Team은 사용자 묶음이다.
- Team 자체에는 `auth_state`를 두지 않는다.
- 권한 단계는 리소스별 중간 테이블에 둔다.
- Team이 속한 조직과 권한 row의 조직이 다르면 DB에서 저장을 막는다.

## 최종 이름

| 개념 | 모델 | 테이블 |
| --- | --- | --- |
| Team | `Team` | `teams` |
| TeamMembership | `TeamMembership` | `team_memberships` |
| TeamWorkflowPermission | `TeamWorkflowPermission` | `team_workflow_permissions` |
| TeamKnowledgePermission | `TeamKnowledgePermission` | `team_knowledge_permissions` |
| TeamLLMPermission | `TeamLLMPermission` | `team_llm_permissions` |
| TeamAuditPermission | `TeamAuditPermission` | `team_audit_permissions` |

## Team

`teams`는 조직이 소유하는 팀이다.

| 컬럼 | 의미 |
| --- | --- |
| `id` | Team ID |
| `organization_id` | Team 소유 조직 |
| `name` | Team 이름 |
| `description` | Team 설명 |
| `created_by` | 생성자 |
| `managed_by` | 관리자 |
| `is_active` | 활성 여부 |
| `is_auto_add` | 자동 추가 여부 |
| `created_at` | 생성 시간 |
| `updated_at` | 수정 시간 |
| `deactivated_at` | 비활성화 시간 |

`teams.auth_state`는 없다.

같은 Team이라도 Workflow A에서는 `read`, Workflow B에서는 `admin`일 수 있으므로 권한 단계는 Team이 아니라 리소스 권한 중간 테이블에 둔다.

## 공통 Mixin

### TeamAssignmentMixin

Team을 어떤 조직 범위에 부여했는지 나타내는 공통 컬럼이다.

| 컬럼 | 의미 |
| --- | --- |
| `grantee_organization_id` | 권한을 받는 조직 |
| `team_id` | 권한을 받는 Team |
| `assigned_by` | 권한을 부여한 사용자 |
| `assigned_at` | 권한 부여 시간 |

### TeamResourcePermissionMixin

리소스별 권한 테이블에서 사용하는 공통 Mixin이다.

`TeamAssignmentMixin`에 다음 컬럼을 추가한다.

| 컬럼 | 의미 |
| --- | --- |
| `auth_state` | 리소스에 대한 권한 단계 |

권한 단계는 문자열로 관리한다.

```text
none
read
execute
write
manage
admin
```

## 리소스별 권한 테이블

### team_memberships

사용자가 어떤 Team에 속하는지 저장한다.

권한 단계가 아니라 멤버십만 나타내므로 `auth_state`가 없다.

| 컬럼 | 의미 |
| --- | --- |
| `id` | row ID |
| `grantee_organization_id` | Team 소속 조직 |
| `user_id` | Team에 들어간 사용자 |
| `team_id` | Team |
| `assigned_by` | 부여자 |
| `assigned_at` | 부여 시간 |

### team_workflow_permissions

Team이 어떤 Workflow에 어떤 권한을 가지는지 저장한다.

| 컬럼 | 의미 |
| --- | --- |
| `id` | row ID |
| `grantee_organization_id` | Team 소속 조직 |
| `workflow_id` | Workflow |
| `team_id` | Team |
| `auth_state` | Workflow 권한 단계 |
| `assigned_by` | 부여자 |
| `assigned_at` | 부여 시간 |

### team_knowledge_permissions

Team이 어떤 KnowledgeBase에 어떤 권한을 가지는지 저장한다.

| 컬럼 | 의미 |
| --- | --- |
| `id` | row ID |
| `grantee_organization_id` | Team 소속 조직 |
| `knowledge_base_id` | KnowledgeBase |
| `team_id` | Team |
| `auth_state` | Knowledge 권한 단계 |
| `assigned_by` | 부여자 |
| `assigned_at` | 부여 시간 |

### team_llm_permissions

Team이 어떤 LLM Credential에 어떤 권한을 가지는지 저장한다.

| 컬럼 | 의미 |
| --- | --- |
| `id` | row ID |
| `grantee_organization_id` | Team 소속 조직 |
| `llm_credential_id` | LLM Credential |
| `team_id` | Team |
| `auth_state` | LLM 권한 단계 |
| `assigned_by` | 부여자 |
| `assigned_at` | 부여 시간 |

### team_audit_permissions

Team이 어떤 조직 범위의 Audit 데이터를 볼 수 있는지 저장한다.

| 컬럼 | 의미 |
| --- | --- |
| `id` | row ID |
| `grantee_organization_id` | Team 소속 조직 |
| `target_organization_id` | Audit 대상 조직 |
| `team_id` | Team |
| `auth_state` | Audit 권한 단계 |
| `assigned_by` | 부여자 |
| `assigned_at` | 부여 시간 |

## Composite FK

문제 상황:

```text
teams.id = team_a
teams.organization_id = org_1

team_workflow_permissions.team_id = team_a
team_workflow_permissions.grantee_organization_id = org_2
```

이 row는 `team_a`가 실제로는 `org_1` 소속인데, 권한 row에서는 `org_2` 소속처럼 보인다.

이를 막기 위해 DB에 composite FK를 둔다.

먼저 `teams`에 다음 유니크 제약을 둔다.

```text
UNIQUE(id, organization_id)
```

그 다음 각 Team 관련 중간 테이블에서 다음 조합을 참조한다.

```text
(team_id, grantee_organization_id)
  -> teams(id, organization_id)
```

적용 대상:

| 테이블 | 제약 이름 |
| --- | --- |
| `team_memberships` | `fk_team_memberships_team_org` |
| `team_workflow_permissions` | `fk_team_workflow_permissions_team_org` |
| `team_knowledge_permissions` | `fk_team_knowledge_permissions_team_org` |
| `team_llm_permissions` | `fk_team_llm_permissions_team_org` |
| `team_audit_permissions` | `fk_team_audit_permissions_team_org` |

효과:

- Team 소속 조직과 권한 row의 조직이 다르면 DB insert/update가 실패한다.
- 서비스 코드에서 검사를 빠뜨려도 DB가 최종 방어한다.
- 권한 row만 봐도 어떤 조직의 Team 권한인지 바로 알 수 있다.

서비스 코드에서도 검사는 유지한다.

DB 제약은 무결성 방어용이고, 서비스 검사는 사용자에게 명확한 에러를 주기 위한 용도다.

## Organization Structure

조직 계층 조회를 빠르게 하기 위해 `organization_structure` 테이블을 추가했다.

| 컬럼 | 의미 |
| --- | --- |
| `ancestor_id` | 상위 조직 |
| `descendant_id` | 하위 조직 |
| `depth` | 거리 |

예시:

```text
admin
  -> company
      -> department
```

저장되는 row:

```text
ancestor_id   descendant_id   depth
admin         admin           0
admin         company         1
admin         department      2
company       company         0
company       department      1
department    department      0
```

상위 조직에서 하위 조직 리소스를 찾을 때 `organization_structure`를 사용한다.

## Migration

추가된 주요 migration:

```text
c7d8e9f0a1b2_team_resource_permissions_and_organization_structure.py
d8e9f0a1b2c3_rename_team_permission_tables.py
```

`c7d8e9f0a1b2`가 하는 일:

- 기존 `team_permission.auth_state` 제거
- 기존 `team_permission.organization_id`를 NOT NULL로 정리
- 기존 `user_team_permissions.organization_id`를 `grantee_organization_id`로 변경
- 기존 `user_team_permissions.team_permission_id`를 `team_id`로 변경
- 기존 `workflow_team_permissions.organization_id`를 `grantee_organization_id`로 변경
- 기존 `workflow_team_permissions.team_permission_id`를 `team_id`로 변경
- 기존 `workflow_team_permissions.auth_state` 추가
- `organization_structure` 생성
- `team_knowledge_permissions` 생성
- `team_llm_permissions` 생성
- `team_audit_permissions` 생성
- Team 관련 테이블에 composite FK 추가

`d8e9f0a1b2c3`가 하는 일:

- `team_permission`을 `teams`로 rename
- `user_team_permissions`를 `team_memberships`로 rename
- `workflow_team_permissions`를 `team_workflow_permissions`로 rename
- 관련 PK, FK, unique constraint, composite FK, index 이름을 최종 이름으로 rename

## 남은 결정 사항

- AuditLog 자체에 `organization_id`를 둘지 여부
- Admin bootstrap 로직을 어느 서비스 시작점에 넣을지 여부
