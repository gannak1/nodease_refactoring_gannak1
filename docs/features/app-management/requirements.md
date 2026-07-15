# App Management Requirements

Status: Draft
Related Features: auth, organization, workflow, deployment, budget-management

## Purpose

TBD

이 feature의 범위에는 앱 탐색/마켓플레이스(`dashboard/explore` 화면, `apps.is_market`)와 앱 복제(`apps.forked_from`)를 포함한다. 마켓플레이스 공개 정책 고도화는 PRD 제외 범위이며, 여기서는 이미 구현된 탐색·복제 동작을 다룬다.

## User Stories

- TBD

## Functional Requirements

- APP-REQ-010: `GET /apps`는 active organization context 기준으로 현재 사용자가 읽을 수 있는 App 목록을 반환한다. 각 App은 기본 정보, primary `workflow_id`, 활성 배포 요약, owner 표시명을 포함한다.
- APP-REQ-020: `GET /apps/operations`는 `/dashboard/mymodule`의 원천으로, 현재 사용자가 운영할 수 있는 App/Workflow row를 반환한다. 운영 가능 기준은 organization manager 또는 workflow `write` 이상 권한이다. Workflow `execute` 전용 사용자는 최종 사용자 실행 주체이므로 이 목록에 포함하지 않는다. 각 row는 App summary, workflow permission summary, deployment state, latest run state를 포함한다.
- APP-REQ-030: Budget Management 확장 시 `GET /apps`의 `AppResponse.budget_status`와 `GET /apps/operations`의 `row.app.budget_status`는 같은 안전 요약 shape를 사용한다. 계산 규칙, null 조건, 노출 금지 필드는 [budget-management requirements](../budget-management/requirements.md)의 BGT-REQ-011, BGT-REQ-022~023을 따른다. App의 primary workflow(`apps.workflow_id`)만 기준으로 하며, 같은 `app_id`의 과거/보조 Workflow row는 예산 상태 후보가 아니다. 사용량 합산은 실행 차단 판정과 동일하게 primary workflow id와 KST 월 경계 기준이며, `llm_usage_logs.organization_id`가 NULL인 기존 로그를 제외하지 않는다.
- APP-REQ-040: `GET /apps/operations`의 `row.app.operation_metrics`는 `/dashboard/mymodule`의 월 예상 비용, 전월 대비 증가 추세, 최적화 권장 표시의 원천이다. 계산은 App의 primary workflow(`apps.workflow_id`)에 연결된 `llm_usage_logs.total_cost`를 KST 달력 월 기준으로 grouped aggregate 한다. 당월 비용은 현재 KST 월 `[start, end)` 비용 합계이며, 월 예상 비용은 당월 경과 비율로 단순 projection 한다. 전월 비용이 0이거나 없으면 `trend_percent`는 null이다.
- APP-REQ-050: App 삭제는 [ADR-0048](../../decisions/ADR-0048-app-workflow-deletion-and-operational-retention.md)의 lifecycle transaction을 따른다. 유효한 manage actor가 삭제하면 App, bounded owned Workflow, Workflow 권한, budget, deployment, schedule과 현재 실행 설정은 제거되고, usage/audit/trace와 replay·멱등성 운영 기록은 각 retention 정책까지 유지되어야 한다.
- APP-REQ-051: 삭제는 App과 canonical Workflow lifecycle lock을 획득한 뒤 organization/manage 권한을 다시 확인해야 한다. `apps.workflow_id`와 `workflows.app_id`가 불일치하거나 같은 App에 여러 Workflow가 있는 legacy 데이터는 같은 App/organization 범위 안에서만 bounded 처리하며, 중간 실패 시 어떤 부분 삭제도 commit하지 않는다.
- APP-REQ-052: 삭제와 경합하는 run/schedule admission은 잠금 뒤 App, Workflow, deployment와 active pointer를 다시 확인하고 unavailable을 non-retryable로 종료해야 한다. 동시 삭제 loser와 이미 삭제된 App은 기존 resource hiding 계약에 따라 `404`를 반환한다.
- APP-REQ-053: `app.delete` 성공 audit은 organization/actor/resource의 bounded safe metadata만 포함해야 한다. App 이름, graph/deployment snapshot, raw usage/trace payload, credential, secret과 exception 원문을 포함하지 않는다.

## Policies And Edge Cases

- `budget_status`는 사용률과 상태만 포함한다. 예산 금액, 당월 비용 원문, credential, raw payload, secret 값은 App Management 응답에 포함하지 않는다.
- `operation_metrics`는 `/apps/operations` 전용 운영 지표다. `budget_status` shape를 확장하지 않으며, `GET /apps` 응답에는 포함하지 않는다.
- `/dashboard/mymodule`은 운영 표면이다. 일반 사원처럼 배포된 workflow를 실행만 하는 사용자는 챗봇 배포 링크나 내부 실행 링크를 사용하며, 비용/최근 실행/최적화 같은 운영 지표를 보지 않는다.
- `budget_status`가 null이어도 App 접근 권한, 배포 상태, 실행 상태의 기존 응답 의미는 바뀌지 않는다.
- App의 `workflow_id`가 null이거나 primary workflow에 활성 예산이 없으면 `budget_status`는 null이다. 같은 `app_id`의 다른 Workflow row에 활성 예산이 있어도 이를 대체값으로 사용하지 않는다.
- App의 `workflow_id`가 null이거나 해당 workflow에 당월 사용 로그가 없으면 `operation_metrics`는 null 또는 0 비용 지표로 처리하며, 클라이언트는 더미 비용/추세를 만들지 않는다.
- App/operations 목록 조회와 예산 수정·비활성화·삭제가 경합해도 목록 API는 5xx 없이 완료되어야 한다. 예산 상태는 같은 조회 스냅샷 기준으로 일관되게 계산하고, 경합 결과 활성 예산을 찾을 수 없으면 null로 반환한다.
- 삭제된 App/Workflow UUID를 가진 retained 운영 기록은 현재 리소스 권한 source가 아니다. 조회는 durable organization provenance와 현재 actor 권한으로 판정하며 삭제된 display resource를 찾지 못하면 opaque UUID 또는 display 생략으로 안전하게 응답한다.

## Open Questions

- TBD
