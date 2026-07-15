# App Management Test Cases

Status: Draft
Verified Against: TBD

## Acceptance Criteria

### AC-1. App 목록 예산 상태 (APP-REQ-010, APP-REQ-030)

- Given 사용자가 읽을 수 있는 App의 primary workflow에 활성 예산이 있고 당월 비용이 기록되어 있다, When `GET /apps`를 호출한다, Then 해당 App의 `budget_status`는 `usage_ratio`와 `status`만 포함한다.
- Given 활성 예산이 없거나 App의 `workflow_id`가 null이다, When `GET /apps`를 호출한다, Then 해당 App의 `budget_status`는 null이고 기존 App 필드는 유지된다.
- Given App의 primary workflow에는 활성 예산이 없고 같은 `app_id`의 과거/보조 workflow에는 활성 예산이 있다, When `GET /apps`를 호출한다, Then 해당 App의 `budget_status`는 null이고 보조 workflow 상태를 표시하지 않는다.
- Given 사용자가 읽을 수 없는 App/Workflow가 있다, When `GET /apps`를 호출한다, Then 해당 리소스와 예산 상태는 응답에 포함되지 않는다.

### AC-2. 운영 현황 예산 상태 (APP-REQ-020, APP-REQ-030)

- Given `/dashboard/mymodule`에 표시되는 App row의 primary workflow에 활성 예산이 있다, When `GET /apps/operations`를 호출한다, Then `row.app.budget_status`는 `GET /apps`와 동일한 shape로 반환된다.
- Given `/dashboard/mymodule`에 표시되는 App row의 primary workflow에 당월/전월 `llm_usage_logs` 비용이 있다, When `GET /apps/operations`를 호출한다, Then `row.app.operation_metrics`는 당월 비용, 월 예상 비용, 전월 비용, 전월 대비 증감률을 반환한다.
- Given 전월 비용이 0이거나 없다, When `GET /apps/operations`를 호출한다, Then `row.app.operation_metrics.trend_percent`는 null이고 클라이언트는 더미 증가율을 만들지 않는다.
- Given `/dashboard/mymodule`에 표시되는 App row의 `workflow_id`가 null이고 같은 `app_id`의 과거/보조 workflow에 활성 예산이 있다, When `GET /apps/operations`를 호출한다, Then `row.app.budget_status`는 null이다.
- Given `row.app.budget_status.status`가 `exceeded`다, When 클라이언트가 `/dashboard/mymodule`을 렌더링한다, Then row는 예산 상태 badge와 "실행 차단" 표시를 보여준다.
- Given `row.app.budget_status`가 null이다, When 클라이언트가 `/dashboard/mymodule`을 렌더링한다, Then 예산 관련 텍스트 없이 기존 row 레이아웃을 유지한다.
- Given `row.app.operation_metrics`가 null이다, When 클라이언트가 `/dashboard/mymodule`을 렌더링한다, Then 월 예상 비용/증가 추세/최적화 권장 UI는 "운영 비용 없음" 또는 "비교 데이터 없음"을 표시하고 deterministic dummy 값을 생성하지 않는다.

### AC-3. 안전 요약 노출 제한

- Given `GET /apps` 또는 `GET /apps/operations` 응답을 확인한다, Then `budget_status`에는 `usage_ratio`와 `status`만 포함되고 `monthly_budget_usd`, `current_month_cost`, credential, raw payload, secret 값은 포함되지 않는다.
- Given workflow `execute` 전용 일반 사용자가 있다, When `GET /apps/operations`를 호출한다, Then 해당 workflow row와 운영 비용/최근 실행/최적화 지표는 응답에 포함되지 않는다.
- Given 같은 사용자가 배포 내부 실행 링크(`/modules/{workflow_id}/run?deploymentId={deployment_id}`)를 사용한다, When workflow 실행을 요청한다, Then workflow `execute` 권한과 RAG 실행 주체 권한으로 실행 가능 여부를 판단한다.

### AC-4. 조회 성능과 동시성

- Given 여러 App row가 같은 응답에 포함된다, When `budget_status`를 계산한다, Then 응답 대상 workflow id를 모아 grouped query로 계산하고 App row마다 개별 비용 집계를 반복하지 않는다.
- Given App의 primary workflow usage 중 `llm_usage_logs.organization_id`가 NULL인 기존/마이그레이션 row가 있다, When `GET /apps` 또는 `GET /apps/operations`의 `budget_status`를 계산한다, Then 해당 비용도 합산해 실행 차단 판정과 같은 상태를 반환한다.
- Given 예산 수정/비활성화와 `GET /apps` 또는 `GET /apps/operations` 조회가 동시에 발생한다, When 응답을 생성한다, Then 요청은 5xx 없이 완료되고 각 row의 `usage_ratio`와 `status`는 같은 DB 조회 스냅샷 기준으로 일관된다.
- Given 조회 도중 App의 primary workflow 또는 예산 row가 삭제된다, When 응답을 생성한다, Then 이미 응답 대상인 App은 기존 접근 정책을 유지하고 예산 상태를 계산할 수 없으면 `budget_status=null`로 처리한다.

### AC-5. 예산 상태 경계값

- Given 예산 100 USD와 당월 비용 79.99 USD인 App, When `GET /apps` 또는 `GET /apps/operations`를 호출한다, Then `budget_status.status`는 `normal`이고 `usage_ratio`는 0.7999다.
- Given 예산 100 USD와 당월 비용 80.00 USD인 App, When 조회한다, Then `status`는 `at_risk`이고 `usage_ratio`는 0.8다.
- Given 예산 100 USD와 당월 비용 100.00 USD인 App, When 조회한다, Then `status`는 `at_risk`이고 실행 차단 표시는 표시하지 않는다.
- Given 예산 100 USD와 당월 비용 100.000001 USD인 App, When 조회한다, Then `status`는 `exceeded`이고 `/dashboard/mymodule`은 "실행 차단" 표시를 보여준다.
- Given `total_cost`가 NULL인 usage row만 있는 App, When 조회한다, Then 비용은 0으로 합산되어 `usage_ratio=0`, `status=normal`이다.
- Given KST 월 경계의 usage row가 있다, When KST 7월 기준 조회한다, Then KST 7월 1일 00:00:00 row는 포함하고 KST 8월 1일 00:00:00 row는 제외한다.

### AC-6. App 삭제 lifecycle (APP-REQ-050~053)

- Given Team/User Workflow permission이 있는 App, When 유효한 manage actor가 삭제한다, Then App/owned Workflow/permission이 삭제되고 FK 500이 발생하지 않는다.
- Given deployment와 schedule이 있는 App, When 삭제한다, Then 실행 가능한 deployment/schedule/active pointer가 남지 않는다.
- Given usage/run/trace/audit가 있는 App, When 삭제한다, Then 기록은 retention 정책대로 유지되고 durable organization provenance로만 접근을 판정한다.
- Given Cost Optimizer, model routing, Agent Builder, Mail processing 또는 external-effect 기록이 있는 App, When 삭제한다, Then 현재 실행 설정은 제거되고 evidence/history/idempotency ledger는 ADR-0048의 retention 정책을 따른다.
- Given `apps.workflow_id`와 `workflows.app_id`가 불일치하거나 복수 Workflow가 연결된 legacy App, When 삭제한다, Then 같은 App/organization의 bounded 대상만 처리하고 다른 App/organization Workflow는 변경하지 않는다.
- Given 삭제 중 FK/audit/lifecycle 처리 실패가 발생한다, When transaction이 종료된다, Then App, Workflow, permission, retained reference와 audit은 요청 전 상태로 rollback된다.
- Given 같은 App을 두 요청이 동시에 삭제한다, When lifecycle lock 뒤 결과를 확인한다, Then 한 요청만 성공하고 loser는 `404`이며 부분 삭제나 500이 없다.
- Given 권한이 없거나 cross-organization App ID를 요청한다, When 삭제한다, Then 기존 `403/404` resource hiding 계약을 유지하고 target-aware audit metadata를 노출하지 않는다.
- Given 삭제 성공 audit을 조회한다, Then organization/actor/App/Workflow count/request의 safe metadata만 있고 App 이름, graph, deployment config, raw payload와 secret은 없다.

## App Deletion Test Cases

### 공통 fixture

별도 조건이 없는 App 삭제 테스트는 다음 데이터를 사용한다.

- `organization_a`에는 App `app_a`와 canonical Workflow `workflow_a1`이 있다. `app_a.workflow_id=workflow_a1.id`, `workflow_a1.app_id=app_a.id`다.
- `organization_a`에는 같은 App에 연결된 legacy Workflow `workflow_a2`가 있다. `workflow_a2.app_id=app_a.id`지만 `app_a.workflow_id`는 가리키지 않는다.
- `organization_a`에는 삭제 대상이 아닌 App `app_b`와 Workflow `workflow_b1`이 있다.
- `organization_b`에는 App `app_c`와 Workflow `workflow_c1`이 있다. legacy 오염 fixture에서는 `app_a.workflow_id=workflow_c1.id`처럼 다른 organization 참조를 별도로 만든다.
- actor는 organization manager인 `manager_a`, Workflow manage 권한만 가진 `workflow_manager_a`, manage 권한이 없는 `member_a`, 다른 organization 사용자인 `manager_b`를 둔다.
- 삭제 설정 fixture에는 Workflow permission, budget, deployment, deployment optimization plan, schedule, LLM node version을 각각 최소 1건 둔다.
- 보존 기록 fixture에는 audit, Workflow run/node run/trace, LLM usage, Cost Optimizer 실험·추천 검증, model routing evidence, Agent Builder history, mail processing ledger, schedule claim, external-effect attempt를 각각 최소 1건 둔다.
- 민감정보 검증을 위해 graph/config/payload/credential 위치에는 고유 sentinel 문자열을 넣는다. sentinel은 API 응답, audit metadata, 애플리케이션 로그에 나타나면 안 된다.
- 모든 fixture에는 삭제 대상과 무관한 `app_b`, `workflow_b1`, `app_c`, `workflow_c1`의 대조 데이터를 함께 둔다. 삭제 후 이 row들의 값과 개수는 바뀌면 안 된다.

### 데이터별 성공·실패 기대값

| 데이터 분류 | 삭제 성공 후 | 삭제 실패 후 |
| --- | --- | --- |
| App, owned Workflow | 삭제 | 모두 유지 |
| Workflow permission | Workflow보다 먼저 삭제 | 모두 유지 |
| budget, deployment, schedule, optimization plan, LLM node version | 삭제 | 모두 유지 |
| run, node run, trace, audit | organization provenance와 함께 유지 | 원래 참조까지 유지 |
| LLM usage | 유지하고 삭제 Workflow 참조는 nullable reference 정책에 따라 분리 | 원래 참조 유지 |
| Cost Optimizer, model routing evidence | 이력은 유지하고 현재 실행 정책으로 사용하지 않음 | 원래 상태 유지 |
| Agent Builder history | 이력은 유지하고 삭제 App/Workflow 표시 참조는 분리 | 원래 참조 유지 |
| mail processing, schedule claim, external-effect attempt | 중복 방지와 재처리 안전 기간 동안 유지 | 원래 상태 유지 |
| 성공 audit | transaction 안에서 1건 기록 | 기록하지 않음 |
| 다른 App/Workflow/organization 데이터 | 변경 없음 | 변경 없음 |

### Service와 transaction

#### APP-DEL-SVC-001. lifecycle lock 뒤 권한 재검증

- Given `manager_a`가 삭제 요청을 시작한 뒤 lifecycle lock을 기다리는 동안 manage 권한을 잃는다.
- When service가 `app_a`와 canonical Workflow를 lock하고 권한을 다시 확인한다.
- Then 삭제를 거절하고 App, Workflow, 종속 설정, 보존 기록을 하나도 변경하지 않는다.
- And 권한 확인이 lifecycle lock보다 먼저 한 번 수행되더라도, 그 결과만으로 삭제를 확정하지 않는다.

#### APP-DEL-SVC-002. 삭제 대상 없음

- Given 존재하지 않거나 이미 삭제된 App ID다.
- When 삭제 service를 호출한다.
- Then not-found 결과를 반환하고 commit, 성공 audit, 종속 row 삭제를 수행하지 않는다.

#### APP-DEL-SVC-003. Workflow permission 선행 정리

- Given Team/User Workflow permission이 `workflow_a1`, `workflow_a2`를 참조한다.
- When `app_a`를 삭제한다.
- Then permission을 Workflow보다 먼저 명시적으로 삭제해 FK violation이 발생하지 않는다.
- And `workflow_b1`, `workflow_c1`의 permission은 유지한다.

#### APP-DEL-SVC-004. 단일 transaction 성공

- Given 공통 fixture의 삭제 설정과 보존 기록이 모두 있다.
- When 삭제 service가 성공한다.
- Then App 삭제, Workflow 정리, 참조 분리, 성공 audit을 하나의 transaction으로 commit한다.
- And service 내부에서 부분 상태를 확정하는 중간 commit을 호출하지 않는다.

#### APP-DEL-SVC-005. 오류 발생 시 전체 rollback

- Given permission 삭제 뒤 또는 retained reference 분리 뒤 강제로 FK/flush/audit 오류를 발생시킨다.
- When transaction이 종료된다.
- Then App, Workflow, permission, 설정, 보존 기록의 참조가 요청 전 상태로 돌아간다.
- And 성공 audit은 남지 않으며 같은 요청을 다시 시도할 수 있다.

#### APP-DEL-SVC-006. canonical Workflow 정상 삭제

- Given `app_a.workflow_id`와 `workflow_a1.app_id`가 서로 일치한다.
- When `app_a`를 삭제한다.
- Then `app_a`, `workflow_a1`과 삭제 정책 대상 설정만 제거한다.
- And 보존 기록과 무관한 App/Workflow는 변경하지 않는다.

#### APP-DEL-SVC-007. legacy 복수 Workflow 처리

- Given `workflow_a1`, `workflow_a2`가 같은 `app_a`와 `organization_a`에 연결돼 있다.
- When `app_a`를 삭제한다.
- Then canonical Workflow와 `app_id`로 확인한 bounded legacy Workflow를 함께 처리한다.
- And 처리한 Workflow 수를 safe audit metadata에 기록한다.

#### APP-DEL-SVC-008. 다른 organization Workflow 배제

- Given 손상된 legacy 데이터가 `app_a.workflow_id=workflow_c1.id`처럼 다른 organization Workflow를 가리킨다.
- When `manager_a`가 `app_a`를 삭제한다.
- Then `workflow_c1`과 그 종속 데이터는 삭제하거나 수정하지 않는다.
- And 다른 organization 식별자나 존재 여부를 응답과 audit metadata에 노출하지 않는다.

### Schema와 PostgreSQL integration

#### APP-DEL-DB-001. ORM·Alembic FK 정책 일치

- Given 빈 PostgreSQL DB에 Alembic head를 적용한다.
- When App/Workflow를 직접 참조하는 FK의 `on delete`, nullable, ORM relationship 설정을 점검한다.
- Then 현재 ORM metadata와 실제 PostgreSQL constraint가 ADR-0048의 삭제·보존 정책과 일치한다.
- And SQLite 결과만으로 이 케이스를 통과 처리하지 않는다.

#### APP-DEL-DB-002. permission과 usage가 있는 실제 삭제

- Given PostgreSQL에 Workflow permission과 LLM usage가 모두 있는 `app_a`를 만든다.
- When App 삭제 API의 실제 service 경로를 실행한다.
- Then FK 500 없이 완료되고 permission은 삭제되며 usage는 유지된다.
- And usage의 삭제 Workflow 참조는 `SET NULL` 또는 동등한 명시적 분리 결과가 된다.

#### APP-DEL-DB-003. 운영 기록의 durable organization provenance

- Given run, node run, trace, usage가 삭제 Workflow를 참조한다.
- When App과 Workflow를 삭제한다.
- Then 각 보존 기록은 남고 App/Workflow join 없이 organization 범위를 판정할 수 있다.
- And organization provenance가 없거나 모호한 기존 row는 다른 organization에 노출되지 않는다.

#### APP-DEL-DB-004. 운영 evidence 비연쇄 삭제

- Given Cost Optimizer 실험·추천 검증, model routing evidence, mail processing ledger가 있다.
- When App을 삭제한다.
- Then 이력과 idempotency 증거는 cascade로 삭제되지 않는다.
- And 삭제된 정책이나 배포를 현재 실행 설정으로 다시 선택하지 않는다.

#### APP-DEL-DB-005. Agent Builder 표시 참조 분리

- Given Agent Builder history가 삭제 App 또는 Workflow를 표시용으로 참조한다.
- When App을 삭제한다.
- Then history는 유지되고 삭제 대상 참조는 null 또는 안전한 tombstone 표현으로 분리된다.
- And history 조회가 dangling FK 때문에 500을 반환하지 않는다.

#### APP-DEL-DB-006. 실행 설정 cascade

- Given budget, deployment, active deployment pointer, schedule, deployment optimization plan, LLM node version이 있다.
- When App을 삭제한다.
- Then 해당 설정은 모두 제거되고 실행 가능한 deployment, schedule, active pointer가 남지 않는다.
- And retained evidence까지 함께 cascade하지 않는다.

#### APP-DEL-DB-007. migration upgrade와 기존 데이터 보정

- Given 변경 전 schema와 legacy nullable/불일치 데이터를 가진 DB다.
- When 삭제 정책 migration을 적용한다.
- Then migration은 실패하지 않고 보존 row에 필요한 organization provenance를 안전하게 채운다.
- And 채울 근거가 없는 row를 임의 organization에 연결하지 않는다.
- And migration 후 ORM metadata와 PostgreSQL constraint가 일치한다.

#### APP-DEL-DB-008. 실패 주입 rollback

- Given 공통 PostgreSQL fixture에서 삭제 과정 중 flush 또는 audit insert가 실패하도록 주입한다.
- When transaction을 rollback한다.
- Then 데이터별 성공·실패 기대값 표의 실패 후 상태와 정확히 일치한다.
- And 재시도한 정상 삭제는 성공한다.

### API와 permission

#### APP-DEL-API-001. 정상 삭제 응답

- Given `manager_a` 또는 유효한 manage actor가 `app_a`를 관리할 수 있다.
- When `DELETE /api/v1/apps/{app_id}`를 호출한다.
- Then 기존 API 명세의 성공 status와 response shape를 정확히 반환한다.
- And 같은 App을 조회하거나 다시 삭제하면 `404`를 반환한다.

#### APP-DEL-API-002. organization 안의 권한 부족

- Given `member_a`가 `app_a`의 manage 권한이 없다.
- When 삭제 API를 호출한다.
- Then 기존 계약에 따라 `403`을 반환하고 어떤 row도 변경하지 않는다.
- And target Workflow 개수와 내부 참조 정보를 응답에 포함하지 않는다.

#### APP-DEL-API-003. cross-organization resource hiding

- Given `manager_b`가 `organization_a`의 `app_a` ID로 삭제를 요청한다.
- When API가 접근 범위를 확인한다.
- Then `404`를 반환하고 App 존재 여부, 이름, Workflow ID, 종속 row 수를 노출하지 않는다.
- And target-aware 성공 audit을 만들지 않는다.

#### APP-DEL-API-004. 존재하지 않거나 이미 삭제된 App

- Given 임의 ID 또는 이미 성공적으로 삭제된 `app_a` ID다.
- When 삭제 API를 호출한다.
- Then `404`를 반환하고 응답 shape는 cross-organization `404`와 구별되지 않는다.

#### APP-DEL-API-005. 내부 오류 응답과 rollback

- Given lifecycle 도중 FK/audit 오류를 강제로 발생시킨다.
- When 삭제 API를 호출한다.
- Then 기존 안전한 오류 envelope로 응답하며 SQL, constraint 이름, graph/config/payload를 노출하지 않는다.
- And DB는 요청 전 상태로 rollback된다.

### Audit와 민감정보

#### APP-DEL-AUD-001. 성공 audit 1건

- Given 유효한 actor가 App을 삭제한다.
- When transaction이 commit된다.
- Then `app.delete` 성공 audit을 정확히 1건 남긴다.
- And organization, actor, App ID, 처리한 Workflow 수, request correlation 값만 허용된 safe metadata로 기록한다.

#### APP-DEL-AUD-002. 실패 transaction의 성공 audit 제거

- Given audit insert 전후에 transaction 오류가 발생한다.
- When 삭제가 실패한다.
- Then 성공 audit과 부분 data-change audit이 commit되지 않는다.
- And 실패 audit이 별도 경계에서 필요하다면 삭제 대상의 민감 metadata 없이 기록한다.

#### APP-DEL-AUD-003. secret 비노출

- Given graph, deployment config, credential, trace payload에 서로 다른 sentinel secret을 넣는다.
- When 성공·권한 실패·내부 오류 삭제 요청을 각각 수행한다.
- Then API response body/header, audit metadata, captured application log 어디에도 sentinel이 없다.
- And App 이름, raw graph, deployment config, raw payload 원문을 성공 audit에 넣지 않는다.

### Retention과 조회

#### APP-DEL-RET-001. usage 보존 조회

- Given `workflow_a1`의 usage가 있다.
- When App을 삭제한 뒤 organization usage를 조회한다.
- Then 비용·모델·시간 정보는 보존되고 삭제 Workflow 표시 참조는 null 또는 "삭제됨"으로 안전하게 표현된다.
- And 삭제된 Workflow ID만으로 새 권한을 부여하지 않는다.

#### APP-DEL-RET-002. run·node run·trace 보존 조회

- Given 완료·실패 상태의 run, node run, trace가 있다.
- When App 삭제 뒤 `manager_a`가 기록을 조회한다.
- Then organization provenance로 기록을 조회할 수 있고 dangling relationship 때문에 500이 발생하지 않는다.
- And `manager_b`와 권한 없는 사용자는 같은 기록을 조회할 수 없다.

#### APP-DEL-RET-003. optimizer·routing evidence 보존 조회

- Given optimizer 결과와 model routing evidence가 있다.
- When App을 삭제한다.
- Then 과거 결정 증거는 조회 가능하지만 삭제된 Workflow의 활성 추천·routing policy로 실행되지 않는다.

#### APP-DEL-RET-004. mail·external-effect 중복 방지

- Given mail processing, schedule claim, external-effect attempt에 idempotency key가 있다.
- When App을 삭제한 뒤 같은 외부 이벤트가 재전달된다.
- Then 보존 기간 안에는 기존 ledger로 중복 처리를 막는다.
- And 삭제된 App을 되살리거나 새 실행을 만들지 않는다.

#### APP-DEL-RET-005. retention 만료 정리

- Given 보존 기간 안과 밖의 기록이 함께 있다.
- When retention cleanup job을 실행한다.
- Then 기간 밖의 기록만 기존 retention 정책에 따라 정리한다.
- And App 삭제 요청 자체가 보존 기간 안의 기록을 즉시 삭제하지 않는다.

### Deployment, schedule과 실행 admission

#### APP-DEL-RUN-001. 새 실행 차단

- Given App 삭제가 commit됐다.
- When 이전 Workflow/Deployment ID로 새 실행을 요청한다.
- Then non-retryable `app_not_found` 또는 `deployment_not_found` 계열 결과로 종료한다.
- And 새 run/node run/external effect를 만들지 않는다.

#### APP-DEL-RUN-002. 이미 admission된 실행

- Given 실행이 admission을 통과하고 실제 작업 중이다.
- When 같은 App 삭제가 경합한다.
- Then 정의된 lifecycle 순서에 따라 실행 완료 또는 안전한 terminal/dead-letter 상태 중 하나로 끝난다.
- And 실행을 조용히 유실하거나 같은 외부 효과를 중복 수행하지 않는다.

#### APP-DEL-SCH-001. schedule과 claim 처리

- Given 활성 schedule과 아직 admission되지 않은 claim이 있다.
- When App을 삭제한다.
- Then schedule은 제거되고 claim은 삭제된 App/Deployment 때문에 재시도되지 않는 terminal 결과가 된다.
- And 삭제 commit 뒤 새 claim을 만들지 않는다.

### 동시성

#### APP-DEL-CON-001. delete 대 delete

- Given 두 transaction이 같은 `app_a`를 동시에 삭제한다.
- When lifecycle lock을 획득한다.
- Then 한 요청만 성공하고 다른 요청은 `404`를 반환한다.
- And 500, deadlock 노출, 중복 audit, 부분 삭제가 없다.

#### APP-DEL-CON-002. delete 대 deployment 변경

- Given deployment 생성 또는 활성화와 App 삭제가 동시에 시작된다.
- When 동일 lifecycle 대상에 대한 lock 순서를 적용한다.
- Then 삭제가 이기면 새 deployment/active pointer가 남지 않고, deployment 변경이 먼저 commit되면 삭제가 이를 함께 정리한다.
- And 양쪽 모두 성공했는데 실행 가능한 orphan deployment가 남는 결과는 허용하지 않는다.

#### APP-DEL-CON-003. delete 대 run admission

- Given 새 run admission과 App 삭제가 동시에 시작된다.
- When lifecycle lock 경계에서 순서가 정해진다.
- Then admission이 먼저 확정된 실행만 APP-DEL-RUN-002를 따르고, 삭제가 먼저 확정되면 새 실행을 만들지 않는다.

#### APP-DEL-CON-004. delete 대 schedule admission

- Given schedule claim admission과 App 삭제가 동시에 시작된다.
- When lifecycle lock 경계에서 순서가 정해진다.
- Then 삭제 후 admission은 non-retryable unavailable 결과가 되고 새 run을 만들지 않는다.
- And admission이 먼저 확정된 경우에만 기존 실행 lifecycle을 따른다.

#### APP-DEL-CON-005. lock 대기 중 권한 변경

- Given actor가 lifecycle lock을 기다리는 동안 manage 권한이 회수되거나 organization membership이 제거된다.
- When lock 획득 후 권한을 다시 확인한다.
- Then 기존 resource hiding 계약에 맞는 `403` 또는 `404`로 종료하고 삭제하지 않는다.

### 실행 기준

- Service unit test는 fake/session spy로 lock 순서, 권한 재검증, Workflow 대상 집합, permission 선행 삭제, commit 횟수, rollback을 검증한다.
- Schema test는 ORM metadata를 빠르게 검증하되 PostgreSQL integration test를 대신하지 않는다.
- PostgreSQL integration test는 disposable DB에 Alembic head를 적용하고 공통 fixture 전체를 생성한 뒤 성공·rollback 결과를 검증한다.
- API test는 실제 dependency와 transaction 경계를 사용해 `200/403/404/500` 계약과 resource hiding을 검증한다.
- 동시성 test는 서로 다른 DB connection과 명시적 barrier를 사용한다. 단순 순차 호출이나 mock lock만으로 통과 처리하지 않는다.
- 로그 검증은 capture된 response, audit metadata, application log 전체에서 sentinel secret 부재를 확인한다.

## Unit Tests

- `AppService.get_user_apps`
  - Given 활성 예산이 있는 App의 primary workflow, When App 목록을 조회하면, Then `AppResponse.budget_status`는 `usage_ratio`와 `status`만 포함한다.
  - Given 예산이 없거나 `workflow_id`가 null인 App, When App 목록을 조회하면, Then `budget_status`는 null이다.
  - Given primary workflow에는 예산이 없고 같은 `app_id`의 보조 workflow에 예산이 있는 App, When 목록을 조회하면, Then 보조 workflow 예산 상태를 `AppResponse.budget_status`로 붙이지 않는다.
  - Given 여러 App을 조회, When `budget_status`를 계산하면, Then primary workflow별 당월 비용은 grouped query로 계산하고 App별 개별 집계 쿼리를 반복하지 않는다.
  - Given primary workflow의 당월 usage 중 `organization_id`가 NULL인 기존 로그가 있다, When `budget_status`를 계산하면, Then 해당 비용도 포함한다.
  - Given 예산 수정/비활성화가 App 목록 조회와 경합한다, When service가 `budget_status`를 붙인다, Then 예외를 전파하지 않고 일관된 before/after 상태 또는 null 중 하나를 반환한다.
  - Given 경계 비용(79.99/80.00/100.00/100.000001, 예산 100), When `budget_status`를 계산하면, Then `normal`/`at_risk`/`at_risk`/`exceeded`를 반환한다.
- `AppService.list_app_operations`
  - Given 활성 예산이 있는 App의 primary workflow, When operations row를 생성하면, Then `row.app.budget_status`는 `GET /apps`와 같은 shape다.
  - Given App의 `workflow_id`가 null이고 같은 `app_id`의 보조 workflow에 예산이 있다, When operations row를 생성하면, Then `row.app.budget_status`는 null이다.
  - Given 안전 요약 응답, Then 예산 금액과 당월 비용 원문은 포함하지 않는다.
  - Given workflow `execute` 전용 사용자가 App을 읽거나 실행할 수 있다, When operations row를 조회하면, Then 해당 App은 운영 현황 목록에서 제외된다.
  - Given workflow `write` 이상 사용자가 App을 조회한다, When operations row를 조회하면, Then 해당 App은 운영 현황 목록에 포함될 수 있다.
  - Given operations page/batch에 여러 App의 primary workflow가 포함된다, When rows를 생성하면, Then primary workflow id 기준 batch 단위 grouped query로 예산 상태를 계산한다.
  - Given primary workflow의 당월 usage 중 `organization_id`가 NULL인 기존 로그가 있다, When rows를 생성하면, Then 해당 비용도 포함해 `row.app.budget_status`를 계산한다.
  - Given KST 월초 직후(예: 2026-07-31 16:00 UTC = 2026-08-01 01:00 KST), When rows를 생성하면, Then 8월 KST 비용 기준으로 `budget_status`를 계산한다.

## API Tests

- `GET /api/v1/apps`
  - 활성 예산 workflow가 있는 App은 `budget_status.usage_ratio`와 `budget_status.status`를 반환한다.
  - 예산 미설정 App 또는 `workflow_id=null` App은 `budget_status=null`을 반환한다.
  - 같은 `app_id`의 과거/보조 workflow에 활성 예산이 있어도 primary workflow 예산이 아니면 `budget_status=null`을 반환한다.
  - 응답에는 `monthly_budget_usd`, `current_month_cost`가 포함되지 않는다.
  - 90%, 100%, 100% 초과 경계에서 `status`가 각각 `at_risk`, `at_risk`, `exceeded`로 반환된다.
- `GET /api/v1/apps/operations`
  - `/dashboard/mymodule` row의 `app.budget_status`가 활성 예산 상태를 반환한다.
  - 예산 미설정 row는 기존 운영 현황 필드를 유지하고 `app.budget_status=null`을 반환한다.
  - `row.app.workflow_id`가 null이면 같은 `app_id`의 보조 workflow 예산 상태를 노출하지 않고 `app.budget_status=null`을 반환한다.
  - workflow `execute` 전용 사용자와 권한이 없는 App/Workflow는 목록에서 제외되며, 예산 상태만으로 노출되지 않는다.
  - organization manager 또는 workflow `write` 이상 사용자는 운영 현황 row를 조회할 수 있다.
  - KST 월 경계 row 포함/제외 기준이 `GET /apps`와 동일하다.

## E2E Tests

- 빌더가 `/dashboard/mymodule`에 진입하면 예산 위험/초과 workflow row에 `BudgetStatusBadge`가 표시된다.
- 초과 상태 row는 실행 상태 영역에 "실행 차단"을 표시하지만, row 열기/조회 진입은 기존 권한 조건을 따른다.
- 실행 전용 사용자는 사이드바에서 `/dashboard/mymodule` 운영 메뉴를 보지 않고, 내부 실행 화면의 뒤로가기는 기본 대시보드로 이동한다.

## Permission Tests

- `budget_status`는 App/Workflow 목록 또는 운영 현황 권한을 통과한 row에만 붙는다. 권한 없는 workflow와 operations 권한이 없는 execute-only workflow의 예산 상태는 응답에 포함하지 않는다.

## Concurrency Tests

- `GET /apps` 조회와 같은 workflow의 `PUT /admin/workflow-budgets/{workflow_id}`가 경합해도 `GET /apps`는 5xx를 반환하지 않는다. 응답은 수정 전 또는 수정 후 중 하나의 일관된 `budget_status`를 반환할 수 있다.
- `GET /apps/operations` 조회와 예산 비활성화가 경합하면 row 자체는 기존 App/Workflow 접근 정책대로 유지하고, 예산 상태는 수정 전 값 또는 null 중 하나로 반환한다.
- 동시에 여러 사용자가 `GET /apps/operations`를 호출해도 예산 조회는 read-only이며 budget/audit row를 생성하거나 갱신하지 않는다.

## Edge Cases

- 당월 비용이 없으면 활성 예산 workflow의 `usage_ratio`는 0이고 `status`는 `normal`이다.
- 같은 primary workflow의 당월 usage row는 `llm_usage_logs.organization_id`가 NULL이어도 `budget_status` 비용 합산에 포함한다.
- 비활성 예산은 `budget_status=null`로 취급한다.
- 예산 row는 활성화되어 있으나 관련 workflow가 응답 대상 App의 `workflow_id`와 연결되지 않으면 `budget_status=null`이다.
- 같은 `app_id`의 과거/보조 Workflow row에 활성 예산이 있어도 App의 primary `workflow_id`와 다르면 `budget_status`에는 반영하지 않는다.
- `monthly_budget_usd`가 0 이하인 비정상 row가 기존 데이터에 남아 있어도 안전 요약에서는 `budget_status=null`로 취급한다.
- KST 월초 직후에도 `budget_status`는 현재 KST 달력 월 기준으로 계산한다.
