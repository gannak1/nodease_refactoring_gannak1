# ADR-0048: App/Workflow 삭제와 운영 기록 보존 경계

Status: Accepted
Related ADRs: ADR-0004, ADR-0010, ADR-0029, ADR-0035, ADR-0038

## Context

`AppService.delete_app()`은 `apps.workflow_id`를 끊고 `workflows.app_id`로
Workflow를 bulk delete한 뒤 App을 삭제한다. 그러나 현재 schema에는 Workflow를
참조하는 `RESTRICT/NO ACTION`, `CASCADE`, `SET NULL` FK가 섞여 있다.

- Team/User Workflow permission과 `llm_usage_logs.workflow_id`는 Workflow 삭제를
  막을 수 있다.
- `workflow_runs.workflow_id`는 `ON DELETE CASCADE`라서 Workflow를 지우면 보존
  대상인 run/trace가 함께 삭제된다.
- Cost Optimizer, model routing, Mail 처리처럼 보존 또는 멱등성에 필요한 기록도
  현재 Workflow cascade에 묶여 있다.
- Schedule dispatch claim과 external-effect attempt는 FK가 없으므로 삭제는
  막지 않지만, App 삭제와 경합할 때 별도 종료 정책이 없으면 재시도나 외부 효과
  중복 위험이 남는다.

App 삭제는 편집 가능한 리소스와 권한을 제거해야 하지만, 비용·감사·추적과
멱등성에 필요한 운영 기록까지 지워서는 안 된다.

## Decision

### Lifecycle boundary

App 삭제는 하나의 transaction 안에서 다음 순서를 따른다.

1. 대상 App과 canonical Workflow를 잠근다.
2. 잠금 뒤 canonical organization과 actor의 `manage` 권한을 다시 확인한다.
3. `apps.workflow_id`와 `workflows.app_id`를 함께 사용해 삭제 대상 Workflow를
   bounded하게 확정한다. 불일치 또는 복수 Workflow인 legacy row도 같은 App과
   organization 범위 안에서만 처리한다.
4. 진행 중인 schedule/external-effect 상태를 아래 운영 기록 정책에 따라 닫는다.
5. 명시적 lifecycle audit이 필요한 권한과 control-plane row를 service 경계에서
   정리한다.
6. 순환 참조를 끊고 Workflow와 App을 삭제한다.
7. 성공 audit과 모든 변경을 함께 commit한다. 중간 실패는 전체 rollback한다.

권한 확인 전에 cross-organization Workflow 존재 여부나 참조 개수를 응답 또는
audit에 노출하지 않는다.

### Delete with the App/Workflow

다음은 더 이상 실행하거나 관리할 수 없는 control-plane 데이터이므로 삭제한다.

| 데이터 | 정책 |
| --- | --- |
| `team_workflow_permissions`, `user_workflow_permissions` | Workflow 삭제 전에 명시적으로 삭제한다. Bulk delete로 required data-change audit/lifecycle hook을 우회하지 않는다. |
| `workflow_budgets` | Workflow 설정이므로 삭제한다. DB cascade를 사용할 수 있다. |
| `workflow_deployments`, `schedules` | 공개/API/스케줄 실행 표면이 남지 않도록 삭제한다. App cascade를 사용할 수 있다. |
| `deployment_parameter_optimization_plans` | 배포에 적용되는 현재 설정이므로 삭제한다. |
| `llm_node_versions` | 삭제된 App의 편집/적용 이력이므로 App과 함께 삭제한다. 삭제 audit에 graph나 node 설정 원문을 복사하지 않는다. |

`apps.active_deployment_id`와 `apps.forked_from`은 FK가 없는 application-level
reference다. 삭제 transaction은 active pointer를 실행 가능성 판단에 사용하지
않고, 삭제 대상 App 자체를 canonical source로 사용한다.

### Retain under the existing retention policy

다음은 App 삭제 후에도 정해진 보존 기간 또는 replay 안전 조건까지 유지한다.
명시된 보존 기간이 아직 없는 운영 기록은 MBA-87에서 임의로 삭제하지 않으며,
별도 retention 결정이 승인될 때까지 유지한다.

| 데이터 | 정책 |
| --- | --- |
| `audit_logs` | Append-only 기록으로 유지한다. App/Workflow UUID, organization, actor와 safe action metadata만 허용한다. |
| `workflow_runs`, `workflow_node_runs`, `trace_payloads`, trace access event | 기존 trace retention까지 유지한다. Workflow/App row 없이도 organization scope를 판정할 durable provenance가 있어야 한다. Graph, raw input/output 보존 범위는 기존 redaction/retention 정책을 따른다. |
| `llm_usage_logs` | 비용/usage 집계를 위해 유지한다. 삭제된 Workflow FK는 nullable reference로 끊고 durable organization provenance로 조회한다. |
| Cost Optimizer experiment/candidate/recommendation verification | 기존 metadata retention까지 유지한다. 삭제된 App/Workflow는 실행 권한 source가 아니며 immutable provenance로만 취급한다. |
| Model routing policy와 update/run/observation/validation evidence | 정책을 즉시 비활성 tombstone으로 전환하고 기존 evidence retention까지 유지한다. 삭제된 deployment/workflow ID는 실행 lookup에 사용하지 않는다. |
| Agent Builder session/request/draft | 현재 `SET NULL` 계약과 자체 expiry를 유지한다. 삭제된 App/Workflow를 다시 연결하거나 저장 대상으로 사용하지 않는다. |
| `mail_message_processings`, `mail_draft_effects` | 메시지/초안 멱등성 기간까지 유지한다. Workflow UUID는 immutable provenance이며 삭제 cascade 대상이 아니다. |
| `schedule_dispatch_claims` | lifecycle FK 없이 운영 ledger로 유지한다. pre-admission claim은 `app_not_found` 또는 `deployment_not_found`로 취소하고, running/post-admission claim은 기존 success/dead-letter 상태 전이로 종료한다. |
| `workflow_node_effect_attempts` | ADR-0035의 replay/cleanup 안전 조건이 끝날 때까지 유지한다. App/Workflow UUID는 이미 FK 없는 immutable provenance다. |

보존 row의 UUID는 접근 권한을 부여하지 않는다. 조회 API는 durable organization
provenance와 현재 actor 권한을 사용하며, 삭제된 resource display name을 복원하지
못하면 opaque UUID 또는 display 생략으로 안전하게 응답한다.

### FK strategy

- 삭제 대상 config는 `CASCADE` 또는 service의 명시적 delete 중 하나만 canonical
  ownership 방식으로 선택한다.
- 보존 대상은 parent 삭제에 의한 `CASCADE`를 사용하지 않는다.
- 단순 상관관계만 필요한 nullable reference는 `SET NULL`을 사용한다.
- replay/idempotency identity에 UUID가 필요한 ledger는 FK를 제거하고 UUID를
  immutable provenance로 유지한다.
- `workflow_runs`처럼 현재 organization provenance가 parent lookup에 의존하는
  기록에는 삭제 전에 durable organization provenance를 저장하고 backfill한다.
- ORM 선언과 Alembic head의 nullable/ondelete는 동일해야 한다.

### Concurrency and API result

- Deployment 생성/활성화와 같은 App lifecycle lock을 재사용한다.
- 잠금 뒤 App이 없으면 기존 resource hiding 계약에 따라 `404`를 반환한다. 따라서
  동시 삭제의 loser와 이미 삭제된 App 요청은 같은 `404` 결과다.
- 잠금 뒤 권한이 사라졌으면 scope 밖은 `404`, scope 안 action 권한 부족은 `403`을
  유지한다.
- App 삭제와 경합한 신규 run/schedule admission은 App, Workflow, deployment와
  active pointer를 다시 확인하고 non-retryable unavailable 결과로 종료한다.

### Audit

성공한 삭제는 `app.delete` 하나를 기록한다. 허용 metadata는 organization ID,
actor ID, App ID, 삭제된 Workflow 수와 request ID 같은 bounded safe scalar뿐이다.
App 이름, graph snapshot, deployment config, raw trace/usage payload, credential,
secret과 exception 원문은 기록하지 않는다. Rollback된 삭제는 success audit을
남기지 않는다.

## Current FK Inventory

아래 표는 MBA-87 조사 시점의 Alembic head와 SQLAlchemy metadata를 대조한 direct
App/Workflow FK다. `NO ACTION`은 PostgreSQL에서 parent 삭제를 막는다.

| Child reference | 현재 nullable/ondelete | 목표 정책 |
| --- | --- | --- |
| `apps.workflow_id -> workflows.id` | NULL / NO ACTION | transaction에서 명시적으로 detach |
| `workflows.app_id -> apps.id` | NOT NULL / NO ACTION | bounded Workflow 삭제 후 App 삭제 |
| `team_workflow_permissions.workflow_id` | NOT NULL / NO ACTION | 명시적 삭제 |
| `user_workflow_permissions.(workflow_id, organization_id)` | NOT NULL / NO ACTION | 명시적 삭제 |
| `workflow_budgets.(workflow_id, organization_id)` | NOT NULL / CASCADE | 삭제 유지 |
| `workflow_deployments.app_id` | NOT NULL / CASCADE | 삭제 유지 |
| `llm_node_versions.app_id` | NOT NULL / CASCADE | 삭제 유지 |
| `llm_node_versions.source_workflow_id` | NULL / SET NULL | `SET NULL` 유지 |
| `deployment_parameter_optimization_plans.app_id/workflow_id` | NOT NULL / CASCADE | 삭제 유지 |
| `workflow_runs.workflow_id` | NOT NULL / CASCADE | 보존 가능 schema로 변경 |
| `workflow_runs.app_id` | NULL / SET NULL | `SET NULL` 유지 |
| `llm_usage_logs.workflow_id` | NULL / NO ACTION | `SET NULL`로 변경 |
| `cost_optimizer_experiments.app_id` | NULL / SET NULL | `SET NULL` 유지 |
| `cost_optimizer_experiments.workflow_id` | NOT NULL / CASCADE | retention 가능한 immutable provenance로 변경 |
| `cost_optimizer_recommendation_verifications.workflow_id` | NOT NULL / CASCADE | retention 가능한 immutable provenance로 변경 |
| `llm_node_model_routing_policies.workflow_id` | NOT NULL / CASCADE | 비활성 tombstone/evidence 보존 가능 schema로 변경 |
| `agent_builder_sessions.workflow_id/app_id` | NULL / SET NULL | `SET NULL` 유지 |
| `agent_builder_drafts.workflow_id/app_id` | NULL / SET NULL | `SET NULL` 유지 |
| `mail_message_processings.workflow_id` | NOT NULL / CASCADE | immutable provenance로 변경 |

조사한 direct App/Workflow FK에서는 Alembic head와 현재 ORM 선언의
nullable/ondelete 불일치를 찾지 못했다. 문제는 선언 불일치보다 각 테이블의 삭제
동작이 제품 retention 정책과 맞지 않는 데 있다.

간접 cascade에는 deployment 아래의 `schedules`와 routing policy, WorkflowRun 아래의
node run/trace, Cost Optimizer experiment 아래의 candidate가 포함된다. 별도 FK가
없는 `schedule_dispatch_claims`, `workflow_node_effect_attempts`,
`apps.active_deployment_id`, `apps.forked_from`도 application lifecycle inventory에
포함한다.

## Consequences

장점:

- FK 500과 부분 삭제를 막는다.
- 권한과 배포는 제거하면서 비용·감사·추적·멱등성 기록은 유지한다.
- 삭제와 실행/스케줄 경합의 결과가 결정적이다.

비용:

- WorkflowRun organization provenance와 여러 FK의 additive migration/backfill이
  필요하다.
- 삭제 service가 permission audit, schedule claim 종료와 routing tombstone을
  조율해야 한다.
- 보존 데이터 조회는 삭제된 App/Workflow join에 의존할 수 없다.

## Verification

- Alembic head에서 direct/indirect FK inventory와 ORM metadata가 일치해야 한다.
- 실제 PostgreSQL에서 permission, usage, run/trace, optimizer, routing, Agent
  Builder, deployment/schedule와 external-effect row를 가진 App 삭제를 검증한다.
- 주입한 중간 실패에서 App, Workflow, permission, retained reference와 audit이 모두
  rollback되는지 검증한다.
- 동시 삭제, 동시 run/schedule admission과 이미 삭제된 App의 `404` 결과를 검증한다.
- retained usage/audit/trace 조회가 organization scope를 지키고 secret/raw payload를
  노출하지 않는지 검증한다.
