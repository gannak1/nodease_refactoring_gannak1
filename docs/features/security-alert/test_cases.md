# Security Alert Test Cases

Status: Draft

이 문서는 [requirements.md](requirements.md), [api_spec.md](api_spec.md), [component_spec.md](component_spec.md), [ADR-0028](../../decisions/ADR-0028-security-alert-detection-and-lifecycle.md)의 검증 기준을 정의한다.

현재 초안은 기능 완료를 판단하기 위한 인수조건을 먼저 고정한다. Unit, service, API, worker, component, E2E 상세 test matrix는 이 인수조건을 기준으로 확장한다.

## Acceptance Criteria

### AC-01 Eligible Audit Only

Given 인증된 actor와 검증된 organization이 있고 `category='action'`, `status='failure'`인 audit가 존재할 때,
When Security Alert detector가 event를 평가하면,
Then canonical `permission.denied` 또는 allowlist `policy.block`만 탐지 입력으로 사용해야 한다.

그리고 actor/organization 누락, `auth.permission_denied`, 로그인 실패, hidden 404, validation 실패, no-op, `budget.exceeded`는 alert occurrence에 포함하지 않아야 한다.

### AC-02 Audit Provenance Is Not Inferred

Given `permission.denied` audit에 `audit_metadata.organization_id`가 없거나 유효하지 않을 때,
When detector가 event를 처리하면,
Then target resource를 다시 조회해 organization을 추측하지 않고 event를 제외해야 한다.

### AC-03 Canonical Policy Reason

Given `policy.block` audit가 발생할 때,
When 신규 producer가 audit를 기록하면,
Then 최상위 `audit_metadata.policy_reason`은 `{domain}.{reason}` 형식의 canonical value여야 한다.

그리고 legacy `pii_policy_blocked`를 읽을 때는 기존 row를 수정하지 않고 `rag.pii_evidence_detected`로 정규화해야 한다.

### AC-04 Repeated Permission Denial Threshold

Given 같은 organization과 actor의 eligible `permission.denied`가 5분 window 안에 누적될 때,
When 네 번째 event까지 처리하면,
Then alert가 없어야 한다.

When 다섯 번째 event를 처리하면,
Then `repeated_permission_denied`, version `v1`, severity `medium`, status `open` alert가 정확히 하나 생성되어야 한다.

### AC-05 Multi-Resource Probe Threshold

Given 같은 organization과 actor가 10분 안에 안전한 서로 다른 `(target_type, target_id)`에 접근을 시도할 때,
When 서로 다른 target 네 개까지만 처리하면,
Then `multi_resource_permission_probe` alert가 없어야 한다.

When 다섯 번째 서로 다른 target을 처리하면,
Then version `v1`, severity `high`, status `open` alert가 정확히 하나 생성되어야 한다.

같은 target 반복과 안전하지 않은 target은 distinct count를 늘리지 않아야 한다.

### AC-06 Repeated Policy Block Threshold

Given 같은 organization, actor, canonical `policy_reason`의 eligible `policy.block`이 10분 안에 누적될 때,
When 두 번째 event까지 처리하면,
Then alert가 없어야 한다.

When 세 번째 event를 처리하면,
Then `repeated_policy_block`, version `v1`, severity `high`, status `open` alert가 정확히 하나 생성되어야 한다.

서로 다른 policy reason은 같은 threshold에 합산하지 않아야 한다.

### AC-07 Scope Isolation

Given 동일한 action이 서로 다른 organization, actor, rule version 또는 policy reason에서 발생할 때,
When detector가 threshold를 계산하면,
Then 서로 다른 detection key의 event를 합산하지 않아야 한다.

### AC-08 Window Boundary

Given event가 rule window 시작과 종료 경계에 위치할 때,
When `audit_logs.occurred_at` UTC 기준으로 평가하면,
Then `window_start <= occurred_at <= current_event.occurred_at`인 event만 포함해야 한다.

저장·처리 지연이 있어도 DB 저장 시각이 아니라 `occurred_at`을 사용해야 한다.

### AC-09 Idempotent Event Processing

Given 같은 `audit_log.id`가 실시간 task, retry, reconciliation에서 여러 번 전달될 때,
When 모든 처리가 끝나면,
Then evidence 연결과 occurrence count는 정확히 한 번만 증가해야 한다.

### AC-10 Cooldown Aggregation

Given 같은 detection key의 `open` 또는 `acknowledged` alert가 있고 마지막 탐지 이후 30분 cooldown 안에 새 event가 발생할 때,
When detector가 event를 처리하면,
Then 새 alert를 만들지 않고 기존 alert의 occurrence count, `last_detected_at`, evidence만 갱신해야 한다.

그리고 추가 `security_alert.detected` audit을 만들지 않아야 한다.

### AC-11 Resolved Recurrence

Given alert가 `resolved` 상태일 때,
When 같은 detection key의 새 event가 발생하면,
Then resolved alert에 evidence를 추가하지 않아야 한다.

그리고 resolve 이후 발생한 새 audit만으로 threshold를 다시 충족했을 때 새 `open` alert를 생성해야 하며 이전 alert의 audit을 재사용하지 않아야 한다.

### AC-12 Alert Creation Transaction

Given threshold에 도달한 event가 있을 때,
When alert를 최초 생성하면,
Then Security Alert row, 최초 evidence 연결, `security_alert.detected` audit을 같은 DB transaction에 기록해야 한다.

어느 하나라도 실패하면 세 기록 모두 commit되지 않아야 한다.

### AC-13 Lifecycle Transitions

Given 현재 alert status가 `open`일 때,
When owner/manager가 올바른 version으로 acknowledge하면,
Then status가 `acknowledged`가 되고 처리 관리자/시각과 `security_alert.acknowledged` audit이 같은 transaction에 기록되어야 한다.

Given 현재 status가 `acknowledged`일 때,
When reopen하면,
Then status가 `open`이 되고 `security_alert.reopened` audit이 기록되어야 한다.

Given 현재 status가 `open` 또는 `acknowledged`일 때,
When 유효한 resolution type과 reason으로 resolve하면,
Then status가 `resolved`가 되고 resolution과 `security_alert.resolved` audit이 기록되어야 한다.

### AC-14 Invalid Or Stale Transition

Given `expected_version`이 현재 lifecycle version과 다르거나 현재 status에서 허용되지 않는 action일 때,
When 상태 변경 API를 호출하면,
Then `409 stale_state`를 반환하고 alert mutation과 `security_alert.*` audit을 만들지 않아야 한다.

Occurrence 갱신은 lifecycle version을 증가시키지 않아야 한다.

### AC-15 Resolution Validation

Given resolve request의 type이 allowlist에 없거나 reason이 blank, 500 Unicode code point 초과, 금지 control character 포함 또는 sanitization 실패일 때,
When resolve를 요청하면,
Then `422 validation.failed`로 거부하고 alert, reason, lifecycle audit을 변경하지 않아야 한다.

유효한 reason은 정규화와 secret/PII redaction을 거친 값만 저장·반환해야 한다.

### AC-16 Current Manager Authorization

Given 현재 active organization의 owner/manager일 때,
When 해당 organization의 Alert 목록·summary·상세·evidence·상태 변경 API를 사용하면,
Then 허용해야 한다.

Given 일반 member, audit 전용 auditor/raw auditor, suspended/removed member 또는 강등된 이전 manager일 때,
When 같은 API를 사용하면,
Then `403 permission.denied`로 거부해야 한다.

### AC-17 Cross-Organization Hiding

Given 다른 organization의 `alert_id` 또는 scope 밖 alert를 요청할 때,
When 상세·evidence·상태 변경 API를 호출하면,
Then `404 resource.not_found`로 존재를 숨기고 target-aware Security Alert audit을 만들지 않아야 한다.

### AC-18 Admin List And Detail

Given organization에 여러 상태와 rule의 alert가 있을 때,
When Admin Dashboard 목록을 조회하면,
Then severity, status, rule, actor, 기간 filter와 pagination이 API 계약대로 동작해야 한다.

그리고 기본 정렬은 `last_detected_at DESC`, `id DESC`여야 하며 detail은 safe actor, count, 최초·최근 시각, lifecycle 요약만 표시해야 한다.

### AC-19 Safe Audit Evidence

Given Alert에 관련 audit가 연결되어 있을 때,
When evidence 목록을 조회하면,
Then 실제 연결된 audit만 paginated safe projection으로 반환해야 한다.

Raw `audit_metadata`, `before`, `after`, hidden target, email, IP, user-agent, exception, request body, token, credential, trace/document payload는 반환하지 않아야 한다.

### AC-20 Sidebar Badge And Summary

Given organization에 `open`, `acknowledged`, `resolved` alert가 함께 있을 때,
When owner/manager가 Sidebar summary를 조회하면,
Then badge와 `open_count`는 `open` alert만 세고 최근 open alert를 최대 5개 표시해야 한다.

일반 member에게는 Security Alert badge와 section을 표시하지 않되 기존 organization invitation 알림은 유지해야 한다.

### AC-21 Notification Overlay Navigation

Given owner/manager가 기존 알림 overlay를 열 때,
When Security Alert와 organization invitation이 모두 존재하면,
Then 두 source를 독립 section으로 표시하고 한 source의 오류가 다른 source를 숨기지 않아야 한다.

When Security Alert item을 선택하면,
Then overlay를 닫고 `/dashboard/admin?tab=security-alerts&alertId=<uuid>`로 이동해야 한다.

### AC-22 Deep Link And Drawer State

Given Security Alert deep link를 열거나 브라우저를 새로고침할 때,
When `tab=security-alerts&alertId=<uuid>`가 유효하면,
Then 보안 알림 탭과 해당 detail drawer를 복원해야 한다.

Invalid UUID 또는 404 alert는 다른 organization 존재 여부를 노출하지 않고 URL을 정리한 뒤 safe 안내를 표시해야 한다.

### AC-23 User Access Management Handoff

Given 관리 가능한 actor의 Security Alert detail이 열려 있을 때,
When `사용자 접근 관리`를 선택하면,
Then Security Alert drawer를 닫고 기존 `ActorAccessDrawer`를 열어야 하며 두 drawer를 동시에 표시하지 않아야 한다.

기존 actor access 보호 정책을 그대로 적용하고 수동 조치 성공만으로 alert를 자동 resolve하지 않아야 한다.

### AC-24 SSE Refresh And Recovery

Given Alert 생성·occurrence 갱신·상태 변경이 commit될 때,
When `notifications.changed`를 수신하면,
Then Client는 event payload를 source of truth로 사용하지 않고 summary와 필요한 목록/detail을 재조회해야 한다.

SSE reconnect나 event 누락 이후에도 영속 API 재조회로 현재 상태를 복구해야 한다.

### AC-25 Reconciliation Recovery

Given 실시간 task publish 실패, worker 중단 또는 window 경계 누락이 있을 때,
When reconciliation이 `(occurred_at, audit_log.id)` cursor와 overlap window로 실행되면,
Then 활성화 시점 이후 누락된 eligible event를 복구하고 중복 occurrence 없이 실시간 처리와 같은 결과를 만들어야 한다.

기능 활성화 이전 audit은 처리하지 않아야 한다.

### AC-26 Notification Failure Isolation

Given Alert 또는 lifecycle mutation commit 이후 notification publish가 실패할 때,
When 실패 처리를 수행하면,
Then 이미 commit된 Alert를 rollback하지 않고 notification만 재시도 가능해야 한다.

### AC-27 Data Minimization

Given Security Alert가 생성·조회·표시·로그·metric 처리될 때,
When 저장값과 출력값을 검사하면,
Then raw email, IP, user-agent, exception, request body, secret, credential, hidden resource detail, trace/document payload가 없어야 한다.

Actor snapshot을 Alert row에 복사하지 않고 삭제되거나 표시할 수 없는 actor는 opaque ID 또는 삭제된 사용자로 표시해야 한다.

### AC-28 Existing Flow Regression

Given Security Alert 기능이 활성화됐을 때,
When 기존 workflow 생성·저장·실행·배포, RAG 실행, audit 검색, organization invitation 수락·거절을 수행하면,
Then 기존 동작과 권한 경계가 유지되어야 한다.

Security Alert 탐지 실패가 원래 authorization 결과나 사용자 응답을 성공으로 바꾸거나 추가 실패시키면 안 된다.

### AC-29 Performance Target

Given eligible event가 threshold에 도달할 때,
When 정상 worker와 notification 경로가 동작하면,
Then 관리자 UI에 새 Alert가 1분 이내 반영되어야 한다.

### AC-30 Accessibility

Given keyboard 또는 screen reader 사용자가 Security Alert UI를 사용할 때,
When tab, filter, table action, drawer, resolve dialog, 알림 overlay를 조작하면,
Then 모든 기능에 접근할 수 있고 severity/status를 color 없이도 이해할 수 있어야 한다.

Drawer/dialog close와 drawer 간 전환 뒤 focus가 숨겨진 element에 남지 않아야 한다.

## Detailed Test Matrix

### Test Environment And Concurrency Rules

- 시간 의존 테스트는 wall clock을 직접 사용하지 않고 고정 UTC clock을 주입한다.
- Window 경계는 microsecond 단위의 직전·경계·직후 값을 사용한다.
- Rule evaluator unit test와 API schema test는 외부 broker 없이 실행할 수 있어야 한다.
- DB unique constraint, row lock, transaction isolation, concurrent upsert 검증은 SQLite가 아니라 PostgreSQL에서 실행한다.
- 동시성 테스트는 서로 다른 DB session/transaction을 사용하고 실제 commit 순서를 제어한다.
- Celery retry와 reconciliation 테스트는 같은 `audit_log.id`가 순서가 바뀌거나 중복 전달되는 경우를 포함한다.
- SSE E2E는 event 자체보다 event 수신 후 영속 API 재조회 결과를 검증한다.
- Secret/PII 테스트 fixture는 실제 credential이나 개인정보를 사용하지 않고 명백한 synthetic marker를 사용한다.

### Unit Tests

| ID | Related AC | Given / Input | Expected |
| --- | --- | --- | --- |
| SAL-TC-U001 | AC-01 | actor, organization, category, status 조합을 하나씩 깨뜨린 audit | 모든 필수 조건을 만족한 event만 eligible |
| SAL-TC-U002 | AC-01, AC-03 | `permission.denied`, allowlist `policy.block`, `auth.permission_denied`, `budget.exceeded`, unknown reason | 앞의 두 보안 event만 eligible |
| SAL-TC-U003 | AC-02 | organization ID 누락, invalid UUID, target으로 organization을 추론할 수 있는 event | 모두 제외하며 resource lookup 호출 없음 |
| SAL-TC-U004 | AC-03 | canonical reason과 대문자, dot 누락, 공백, 결과 중심 legacy reason | canonical regex를 만족한 값만 신규 입력으로 허용 |
| SAL-TC-U005 | AC-03 | `pii_policy_blocked`와 canonical `rag.pii_evidence_detected` | 둘 다 evaluator 내부 canonical 값은 `rag.pii_evidence_detected`, 원본 row mutation 없음 |
| SAL-TC-U006 | AC-04 | 5분 안의 permission denial 4건/5건 | 4건 false, 5건 threshold reached |
| SAL-TC-U007 | AC-05 | 같은 target 반복, type만 다른 같은 ID, ID만 다른 같은 type, unsafe target | distinct key는 `(type,id)`이며 unsafe target 제외 |
| SAL-TC-U008 | AC-06, AC-07 | 같은 actor의 policy reason 두 종류 | reason별 count 분리 |
| SAL-TC-U009 | AC-07 | organization, actor, rule version을 하나씩 다르게 구성 | detection key가 모두 다름 |
| SAL-TC-U010 | AC-08 | window 시작 직전, 정확한 시작, 정확한 현재 event 시각, 이후 event | 양 끝 포함 계약대로 count |
| SAL-TC-U011 | AC-10 | last detected 기준 30분 직전, 정확히 30분, 30분 이후 | ADR에서 정한 sliding cooldown 경계대로 기존 alert 갱신 또는 새 평가 |
| SAL-TC-U012 | AC-11 | resolved 시각 이전 evidence와 이후 새 audit | 이전 audit은 fresh threshold에서 제외 |
| SAL-TC-U013 | AC-13, AC-14 | 모든 status/action 조합 | 허용된 네 전이만 성공하고 나머지는 stale/invalid transition |
| SAL-TC-U014 | AC-14 | occurrence 갱신과 lifecycle mutation | occurrence는 lifecycle version 불변, lifecycle 성공은 1 증가 |
| SAL-TC-U015 | AC-15 | resolution type 3개와 unknown type | 세 canonical type만 허용 |
| SAL-TC-U016 | AC-15 | CRLF, blank, 500/501 code point, 금지 control, bidi, synthetic secret/PII | 정규화·길이·control·redaction 계약 준수 |
| SAL-TC-U017 | AC-18 | unknown rule/reason/status label | raw 값을 문장으로 노출하지 않고 safe fallback label |
| SAL-TC-U018 | AC-20 | open/acknowledged/resolved 혼합 목록 | summary count/recent item은 open만 포함 |
| SAL-TC-U019 | AC-27 | safe projection 입력에 raw metadata와 synthetic secret marker 포함 | allowlist 밖 field와 marker 제거 |
| SAL-TC-U020 | AC-29 | event time과 UI-visible time 비교 helper | 60초 이하/초과 판정이 timezone과 무관하게 결정적 |

### Service And Database Tests

| ID | Related AC | Scenario | Expected |
| --- | --- | --- | --- |
| SAL-TC-S001 | AC-09 | 동일 audit evidence를 두 번 insert | unique constraint로 한 row만 존재하고 occurrence 1회 |
| SAL-TC-S002 | AC-10 | 활성 alert가 없는 detection key | alert와 최초 evidence 생성 |
| SAL-TC-S003 | AC-10 | 같은 key의 open alert가 cooldown 안에 존재 | 기존 row count/time만 원자적 갱신 |
| SAL-TC-S004 | AC-10 | 같은 key의 acknowledged alert가 cooldown 안에 존재 | acknowledged 유지, 기존 row 갱신 |
| SAL-TC-S005 | AC-11 | 같은 key의 resolved alert 존재 | resolved row 불변, fresh threshold 충족 전 새 alert 없음 |
| SAL-TC-S006 | AC-12 | detected audit insert 실패 주입 | alert와 evidence도 rollback |
| SAL-TC-S007 | AC-12 | evidence insert 실패 주입 | alert와 detected audit도 rollback |
| SAL-TC-S008 | AC-13 | acknowledge/resolve/reopen 성공 | mutation과 canonical audit이 같은 transaction에 commit |
| SAL-TC-S009 | AC-13 | lifecycle audit insert 실패 주입 | 상태, version, 처리자, reason 모두 rollback |
| SAL-TC-S010 | AC-14 | 두 manager가 같은 expected version으로 동시에 acknowledge | 정확히 하나 성공, 하나 409/stale 결과, audit 한 건 |
| SAL-TC-S011 | AC-14 | occurrence update와 acknowledge가 동시에 실행 | occurrence 유실 없음, acknowledge 성공 가능, lifecycle version 정확 |
| SAL-TC-S012 | AC-10 | 같은 detection key threshold event 두 건을 서로 다른 transaction에서 동시에 처리 | 활성 alert 하나, evidence 둘 중 eligible한 연결 정확, count 중복/유실 없음 |
| SAL-TC-S013 | AC-07 | 같은 actor/rule이지만 organization이 다른 동시 insert | organization별 alert 한 건씩 생성 |
| SAL-TC-S014 | AC-09 | 동일 audit를 서로 다른 transaction이 동시에 연결 | evidence 한 건, occurrence 한 번, transaction deadlock 없이 종료 또는 안전한 retry |
| SAL-TC-S015 | AC-11 | resolve transaction과 새 event transaction 경합 | commit 순서에 따라 event가 기존 활성 alert 또는 resolve 이후 fresh 계산 중 정확히 한 쪽에만 귀속 |
| SAL-TC-S016 | AC-16, AC-17 | 조회 중 membership을 다른 transaction에서 suspend/강등 | 다음 authorization check부터 차단, cross-org data 없음 |
| SAL-TC-S017 | AC-27 | actor user 삭제/SET NULL 또는 membership removed | alert 보존, safe deleted/removed projection 반환 |
| SAL-TC-S018 | AC-18 | filter와 pagination에 충분한 다중 alert | total은 filter 적용 전체 수, page item 중복/누락 없음 |

### API Tests

| ID | Related AC | Request | Expected |
| --- | --- | --- | --- |
| SAL-TC-A001 | AC-16 | owner/manager가 list, summary, detail, evidence 호출 | 200과 현재 organization 데이터만 반환 |
| SAL-TC-A002 | AC-16 | 일반 member와 auditor/raw auditor가 각 endpoint 호출 | 403 `permission.denied`, alert payload 없음 |
| SAL-TC-A003 | AC-17 | 다른 organization alert ID로 detail/evidence/mutation 호출 | 모두 404 `resource.not_found`, 존재 차이 노출 없음 |
| SAL-TC-A004 | AC-18 | severity/status/ruleId/actorId/startAt/endAt 조합 | AND filter, total, 고정 정렬 정확 |
| SAL-TC-A005 | AC-18 | page 0, limit 0/101, invalid enum/UUID/datetime | 422 `validation.failed` |
| SAL-TC-A006 | AC-18 | `endAt <= startAt` | 400 `period.invalid`, query 실행 없음 |
| SAL-TC-A007 | AC-20 | open 4건(high 2), acknowledged/resolved 추가 | summary `open_count=4`, `high_open_count=2`, recent 최대 5 open |
| SAL-TC-A008 | AC-19 | evidence page 조회 | 연결된 safe AuditLogSchema만 반환, raw field 없음 |
| SAL-TC-A009 | AC-13 | open alert acknowledge, acknowledged reopen | 200, version +1, 응답/status/audit 정확 |
| SAL-TC-A010 | AC-13, AC-15 | open/acknowledged alert를 각 resolution type으로 resolve | 200, sanitized reason과 resolver 요약 반환 |
| SAL-TC-A011 | AC-14 | 잘못된 expected version 또는 status에서 mutation | 409 `stale_state`, DB와 lifecycle audit 불변 |
| SAL-TC-A012 | AC-15 | blank/too-long/control/unknown field/unknown resolution request | 422, 입력 reason durable 저장 없음 |
| SAL-TC-A013 | AC-17 | alert UUID 형식은 맞지만 존재하지 않음 | 404, 다른 org ID와 동일한 safe shape |
| SAL-TC-A014 | AC-01 | X-Organization-Id 누락/invalid, 세션 없음 | 각각 400/422/401 safe error |
| SAL-TC-A015 | AC-27 | list/detail/summary/evidence/error response 전체 schema 검사 | email/IP/raw metadata/secret-like key 없음 |
| SAL-TC-A016 | AC-12, AC-13 | canonical audit persistence 실패 주입 후 mutation API | 500 `audit.persistence_failed`, mutation rollback |
| SAL-TC-A017 | AC-16 | 요청 직전 manager 강등 후 기존 cookie로 mutation | 403, stale client 권한으로 성공하지 않음 |
| SAL-TC-A018 | AC-14 | 두 API client가 같은 version으로 동시에 resolve | 하나만 200, 다른 하나 409, resolution/audit 한 건 |

### Worker Tests

| ID | Related AC | Scenario | Expected |
| --- | --- | --- | --- |
| SAL-TC-W001 | AC-04 | 네 번째/다섯 번째 permission denial을 순서대로 task 처리 | 다섯 번째에서 alert 한 건 생성 |
| SAL-TC-W002 | AC-05 | distinct target 5개와 same-target retry 혼합 | distinct 5개 도달 시 한 건 생성 |
| SAL-TC-W003 | AC-06 | canonical/legacy PII reason과 access-management reason | canonical normalize 후 reason별 올바른 alert |
| SAL-TC-W004 | AC-01 | budget, auth, invalid organization, hidden/unsafe event | alert와 evidence 없음 |
| SAL-TC-W005 | AC-09 | task 성공 응답 유실로 Celery가 동일 audit 재전달 | count/evidence/detected audit 중복 없음 |
| SAL-TC-W006 | AC-09 | task가 evidence commit 전 실패 | retry가 transaction을 복구하고 정확히 한 번 반영 |
| SAL-TC-W007 | AC-09 | task가 commit 후 notification publish 전에 실패 | retry 시 alert 중복 없이 notification 재시도 가능 |
| SAL-TC-W008 | AC-10 | cooldown 안 occurrence 연속 처리 | 활성 alert 한 건과 정확한 count/last time |
| SAL-TC-W009 | AC-10 | event가 occurred_at 역순으로 도착 | window와 last time이 event time 계약에 맞고 count 유실 없음 |
| SAL-TC-W010 | AC-25 | 실시간 publish가 누락된 audit를 reconciliation이 스캔 | 누락 event 복구 |
| SAL-TC-W011 | AC-25 | reconciliation overlap 구간을 연속 두 번 실행 | 두 번째 실행에서 중복 증가 없음 |
| SAL-TC-W012 | AC-25 | cursor와 같은 occurred_at의 여러 UUID | `(occurred_at,id)` 순서로 모두 처리하고 누락 없음 |
| SAL-TC-W013 | AC-25 | 활성화 시점 직전/정확한 시점/직후 audit | 정책에 맞춰 이전 제외, 활성화 이후만 포함 |
| SAL-TC-W014 | AC-09, AC-25 | 실시간 task와 reconciliation이 동일 audit를 동시에 처리 | evidence/count 한 번, alert 한 건 |
| SAL-TC-W015 | AC-10 | 서로 다른 worker가 같은 detection key의 서로 다른 threshold event를 동시에 처리 | active unique 보장, count 유실 없음, 안전한 retry |
| SAL-TC-W016 | AC-07 | 여러 organization/actor queue event가 interleave | key별 독립 결과 |
| SAL-TC-W017 | AC-11 | resolve commit 직전/직후 event를 각각 처리 | event 귀속이 commit 순서와 fresh threshold 계약에 일치 |
| SAL-TC-W018 | AC-26 | Redis/SSE publish adapter 실패 | alert commit 유지, publish retry 기록, raw payload log 없음 |
| SAL-TC-W019 | AC-27 | worker exception에 synthetic secret marker 포함 | durable log/metric에 marker와 raw exception 없음 |
| SAL-TC-W020 | AC-29 | threshold event부터 notification publish까지 측정 | 정상 경로 60초 이내 |

### Component Tests

| ID | Related AC | UI Scenario | Expected |
| --- | --- | --- | --- |
| SAL-TC-C001 | AC-18 | manager가 Admin Dashboard 진입 | `보안 알림` 탭이 감사 로그 앞에 표시 |
| SAL-TC-C002 | AC-16 | 일반 member dashboard | 보안 알림 탭/section/badge 미표시, 직접 API 성공으로 간주하지 않음 |
| SAL-TC-C003 | AC-18 | filter draft 변경 후 조회, pagination 이동, 초기화 | applied filter와 page 상태 정확 |
| SAL-TC-C004 | AC-18 | initial loading, no alerts, filtered empty, retryable error, 403 | 각 전용 상태와 safe 문구 표시 |
| SAL-TC-C005 | AC-22 | `tab=security-alerts&alertId=<uuid>` render | tab과 detail 복원, close 시 alertId만 제거 |
| SAL-TC-C006 | AC-22 | invalid alertId 또는 detail 404 | detail 미노출, URL 정리, safe 안내 |
| SAL-TC-C007 | AC-13 | status별 detail action render | open/acknowledged/resolved action matrix와 일치 |
| SAL-TC-C008 | AC-15 | resolve dialog blank/length/control validation과 server failure | invalid submit 방지, 실패 시 입력 유지, raw error 미노출 |
| SAL-TC-C009 | AC-14 | mutation 409 | optimistic 상태 폐기, detail 재조회, stale 안내 |
| SAL-TC-C010 | AC-23 | 사용자 접근 관리 선택 | Alert drawer 닫힘 후 ActorAccessDrawer 하나만 열림, close 후 목록 복귀 |
| SAL-TC-C011 | AC-23 | deleted/removed/unmanageable actor | 접근 관리 disabled와 safe 설명, 자동 resolve 없음 |
| SAL-TC-C012 | AC-20, AC-21 | 보안 alert와 invitation 동시 overlay | 두 section 독립 렌더, open badge 정확, invitation action 유지 |
| SAL-TC-C013 | AC-21 | Security Alert item/모두 보기 click | overlay 닫고 정확한 deep link로 이동 |
| SAL-TC-C014 | AC-24 | `notifications.changed` 수신 | summary와 열린 list/detail 재조회, payload를 직접 state로 사용하지 않음 |
| SAL-TC-C015 | AC-24 | SSE reconnect와 한 source API 실패 | 재조회 복구, 다른 notification section 유지 |
| SAL-TC-C016 | AC-16, AC-24 | active organization 전환 또는 manager 권한 회수 | 이전 cache/list/detail/badge 제거 |
| SAL-TC-C017 | AC-30 | keyboard로 tab→filter→row→drawer→dialog 조작 | focus trap/restore, Escape, accessible label 정상 |
| SAL-TC-C018 | AC-30 | severity/status render | color 없이 text로 의미 전달 |

### End-To-End Tests

| ID | Related AC | End-To-End Flow | Expected |
| --- | --- | --- | --- |
| SAL-TC-E001 | AC-04, AC-20, AC-24 | 사용자 permission denial 5회 → worker → SSE → manager Sidebar | 1분 안에 medium open alert와 badge 1 표시 |
| SAL-TC-E002 | AC-05, AC-18, AC-19 | 서로 다른 resource 5개 denial → Admin tab/detail/evidence | high alert 한 건, safe evidence 5건, raw 정보 없음 |
| SAL-TC-E003 | AC-06 | 같은 PII policy block 3회 | canonical `rag.pii_evidence_detected` high alert 생성 |
| SAL-TC-E004 | AC-13, AC-20 | Sidebar item → deep link → acknowledge → resolve | URL/drawer/status/version/audit/badge가 일관되고 badge에서 제외 |
| SAL-TC-E005 | AC-23 | Alert actor 접근 관리 → membership suspend → alert 별도 resolve | 기존 protection/audit 적용, 자동 resolve 없음, 수동 resolve 성공 |
| SAL-TC-E006 | AC-16, AC-17 | 타 조직 manager가 copied alert URL 접근 | 404와 빈 cache, Sidebar/화면에 타 조직 정보 없음 |
| SAL-TC-E007 | AC-25 | worker 정지 중 threshold event 생성 → worker 복구/reconciliation | 누락 alert 한 건 생성, occurrence 중복 없음 |
| SAL-TC-E008 | AC-09, AC-10 | broker redelivery와 reconciliation overlap을 강제 | alert 한 건, evidence/count 정확, toast 폭주 없음 |
| SAL-TC-E009 | AC-14 | 두 manager browser가 같은 alert를 동시에 resolve | 한 명 성공, 다른 화면 stale refresh, audit/resolution 한 건 |
| SAL-TC-E010 | AC-16, AC-24 | Alert 화면을 연 manager를 다른 manager가 강등 | 다음 refresh/SSE 후 tab data와 badge 제거, API 403 |
| SAL-TC-E011 | AC-21, AC-28 | Security Alert와 organization invitation 동시 존재 | 보안 flow와 invitation 수락/거절 모두 정상 |
| SAL-TC-E012 | AC-28 | Security Alert worker 실패 상태에서 workflow/RAG permission denial | 원래 403/차단 결과 유지, 추가 5xx나 fail-open 없음 |
| SAL-TC-E013 | AC-27 | 전체 API/UI/SSE/log capture에 synthetic secret marker 주입 | 어느 durable/user-visible 출력에도 marker 없음 |
| SAL-TC-E014 | AC-30 | keyboard-only 관리자 전체 flow | Sidebar→alert→detail→resolve/접근 관리까지 mouse 없이 완료 |

### Concurrency Acceptance Gate

다음 테스트는 일반 unit suite 통과만으로 대체할 수 없는 merge gate다.

| Gate | Required Tests | Pass Condition |
| --- | --- | --- |
| Active alert uniqueness | SAL-TC-S012, SAL-TC-W015 | 같은 detection key의 활성 alert가 항상 하나 |
| Evidence idempotency | SAL-TC-S001, SAL-TC-S014, SAL-TC-W014 | 같은 audit evidence/count가 정확히 한 번 |
| Lost-update prevention | SAL-TC-S011, SAL-TC-W008 | occurrence와 lifecycle 변경이 서로를 덮어쓰지 않음 |
| Lifecycle optimistic concurrency | SAL-TC-S010, SAL-TC-A018, SAL-TC-E009 | 동시 상태 변경 중 하나만 성공 |
| Resolve/event race | SAL-TC-S015, SAL-TC-W017 | event가 기존 alert와 새 threshold에 중복 귀속되지 않음 |
| Reconciliation overlap | SAL-TC-W011, SAL-TC-W012 | cursor 경계 누락과 중복 없음 |

PostgreSQL concurrency gate를 실행하지 못한 경우 PR에서 미실행 이유와 남은 위험을 명시해야 하며, SQLite 결과만으로 위 gate를 통과 처리하면 안 된다.
