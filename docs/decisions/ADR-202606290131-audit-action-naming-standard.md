# ADR-202606290131: Audit action naming 표준

Status: Accepted
Authority: Decision
Source of Truth: Yes
Verified Against: dev @ ec576b4f24155697aed8843acc6e5a3fc835f7e1
Created At: 2026-06-29 01:31 KST
Related ADRs: [ADR-202606271559-audit-log-rag-trace-storage](ADR-202606271559-audit-log-rag-trace-storage.md), [ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission](ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md)

## 배경

Active 문서 일부는 권한 또는 정책으로 workflow 실행이 막힌 사건을 `workflow.blocked`로 표현했다. 반면 RBAC 정책, API 문서, 구현 코드는 resource permission 부족을 `permission.denied`로 기록하고, workflow 실행 자체는 `workflow.execute`로 기록한다.

`workflow.blocked`는 결과 중심 이름이라 차단 원인이 RBAC인지, data/model/trace policy인지, 인증 실패인지 구분하기 어렵다. Audit 검색, dashboard aggregation, 테스트 기준을 안정화하려면 원인 중심 action 이름을 표준화해야 한다.

## 결정

`audit_logs.action`은 원인과 비즈니스 사건을 구분하는 canonical action 문자열로 기록한다.

| 사건 | Canonical action | 도입 시점 |
| --- | --- | --- |
| RBAC/resource permission 부족 | `permission.denied` | MVP 1 |
| team/user resource permission row 생성/수정 | `team_workflow_permission.created/updated`, `user_workflow_permission.created/updated`, `team_llm_permission.created/updated`, `user_llm_permission.created/updated` | MVP 1 현재 구현 |
| team/user resource permission row 회수 | `team_workflow_permission.deleted`, `user_workflow_permission.deleted`, `team_llm_permission.deleted`, `user_llm_permission.deleted` | MVP 1 현재 구현 |
| knowledge base permission API/enforcement 구현 시 row 생성/수정 | `team_knowledge_permission.created/updated`, `user_knowledge_permission.created/updated` | MVP 2 기능 구현 시 고정 |
| knowledge base permission API/enforcement 구현 시 row 회수 | `team_knowledge_permission.deleted`, `user_knowledge_permission.deleted` | MVP 2 기능 구현 시 고정 |
| data/model/trace policy 차단 | `policy.block` | MVP 2 |
| data/model/trace policy 경고 | `policy.warn` | MVP 2 |
| workflow 실행 시도와 결과 | `workflow.execute` | MVP 1 |
| 인증 전 또는 resource helper 밖의 전역 401/403 | `auth.permission_denied` | MVP 1 |
| deployment 생성 | `workflow.deploy` | MVP 1 |
| deployment 일반 활성/비활성 toggle | `deployment.toggle` | MVP 1 |
| 다른 deployment가 active인 상태에서 이전 deployment 재활성화 | `deployment.activate_previous` | MVP 1 |
| deployment 삭제 | `deployment.delete` | MVP 1 |

`workflow.blocked`는 `audit_logs.action`으로 저장하지 않는다. UI에서 "workflow 차단" 표시가 필요하면 `target_type='workflow'`, `status='failure'`, `action='permission.denied'` 또는 `action='policy.block'`, `audit_metadata.policy_result`를 조합해 파생한다.

Deployment의 기본 권한 enforcement는 MVP 1 구현 기준으로 본다. Deployment 조회/생성/toggle/delete route는 workflow 하위 resource로 판정하며, 각각 workflow `read`, `deploy`, `manage` 권한을 사용한다. MVP 3의 배포 범위는 이 기본 권한이 아니라 deploy checklist, version diff, trigger mode 정합성, operations dashboard 같은 운영 기능 강화다.

별도 rollback API나 rollback 전용 permission은 만들지 않는다. 이전 deployment 재활성화는 기존 `PATCH /deployments/{deployment_id}/toggle` 동작으로 수행하되, 다른 deployment가 이미 active인 상태에서 inactive였던 이전 deployment를 활성화하는 경우에는 `audit_logs.action='deployment.activate_previous'`로 기록한다. 일반 활성/비활성 toggle은 `deployment.toggle`로 기록한다.

## 구현 정합성

현재 코드의 주요 흐름은 이 결정과 같은 방향이다.

- Resource permission helper는 RBAC 거부를 `permission.denied`로 기록한다.
- 전역 HTTP 401/403 handler는 helper에서 이미 기록하지 않은 인증/권한 실패를 `auth.permission_denied`로 기록한다.
- 현재 등록된 `/api/v1/permissions/*` router의 team/user permission grant/update/revoke 흐름은 permission row별 data-change action인 `team_workflow_permission.created/updated/deleted`, `user_workflow_permission.created/updated/deleted`, `team_llm_permission.created/updated/deleted`, `user_llm_permission.created/updated/deleted`를 기록한다.
- Workflow 실행 기록은 `workflow.execute`를 사용하고, 성공/실패는 `audit_logs.status`와 metadata로 표현한다.
- Deployment 생성은 `workflow.deploy`, 일반 toggle은 `deployment.toggle`, 이전 deployment 재활성화는 `deployment.activate_previous`, 삭제는 `deployment.delete`를 사용한다.
- 현재 코드의 `AuditAction` 상수에는 `llm.call`도 구현되어 있다.
- `policy.warn`, `policy.block`은 이 ADR에서 MVP 2 목표 action으로 확정하지만, 현재 코드의 `AuditAction` 상수에는 아직 없다. Policy enforcement 구현 시 상수와 테스트를 함께 추가한다.

## 영향

- MVP 1 요구사항의 `workflow.blocked` action 표기를 제거하고 `permission.denied`와 `auth.permission_denied`로 분리한다.
- MVP 1에서 permission grant/update/revoke audit을 현재 permission row별 data-change action으로 기록하는 것을 명시한다.
- MVP 2 knowledge base permission API/enforcement를 구현할 때 grant/update/revoke도 같은 permission row별 data-change action 규칙을 고정한다.
- MVP 2 audit search는 `workflow.blocked`가 아니라 `permission.denied`, `policy.warn`, `policy.block`을 검색 대상으로 삼는다.
- Data model의 대표 action convention에 `permission.denied`와 `auth.permission_denied`를 포함한다.
- Deployment API 문서는 기본 권한 enforcement 구현 상태와 MVP 3 운영 기능 강화 범위를 구분한다.

## 후속 검토

- Policy enforcement 구현 시 `policy.block`과 `permission.denied`가 섞이지 않도록 service/helper 경계를 테스트한다.
- Audit UI가 "workflow 차단" 같은 사용자 친화 라벨을 canonical action에서 파생해 표시하는지 확인한다.
