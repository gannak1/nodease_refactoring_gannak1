# Audit Tracing Component Spec

Status: Draft
Verified Against: feature/mba-188 @ 59d1cc51

검증 값은 MBA-188 SafeChangeSummary와 audit actor management 연동에 적용한다. 다른 trace UI는 각 feature 구현 기준을 따른다.

## Screens

- Audit/Tracing은 MBA-188에서 별도 screen을 만들지 않는다.
- Organization audit list/detail과 actor management 진입 UI는 [Admin Dashboard component spec](../admin-dashboard/component_spec.md)의 `/dashboard/admin` AuditSearchTab, AuditDetailDrawer, ActorAccessDrawer가 소유한다.
- Security Alert 목록/detail/evidence와 lifecycle UI는 [Security Alert component spec](../security-alert/component_spec.md)의 Admin Dashboard `보안 알림` 탭이 소유한다. Audit/Tracing UI는 alert 상태를 별도로 계산하거나 저장하지 않는다.
- Organization member access semantics는 [Organization component spec](../organization/component_spec.md)이 소유한다.

## Components

### SafeChangeSummary

- Supported access-management event의 before/after safe field를 key/value 목록으로 표시한다.
- Unknown target/action 또는 empty summary면 렌더링하지 않는다.
- Raw JSON toggle이나 generic payload inspector를 제공하지 않는다.

### SafeDisplayReference

- Audit 목록과 상세에서 사람이 읽을 수 있는 label을 먼저 표시하고 canonical UUID를 보조 text와 복사 가능한 값으로 함께 표시한다.
- Actor는 감사 시점 snapshot label을 우선하고, target은 current organization의 allowlisted current label을 사용한다.
- Display projection이 없거나 대상이 삭제된 경우 오류를 표시하지 않고 기존 UUID만 표시한다.
- Allowlisted metadata/change summary의 UUID는 detail `resolved_references`에 일치하는 항목이 있을 때만 같은 방식으로 병기한다.

### AuditRecorder

- UI component가 아니라 backend outbound adapter contract다.
- Mutation use case와 같은 UnitOfWork에서 AuditLog row를 준비한다.
- Async best-effort publish 성공을 security mutation 성공 조건으로 사용하지 않는다.

### GenericAsyncAuditPublisher

- `record_audit()` 호출마다 audit event id를 먼저 고정하고 직렬화 payload를 한 번만 만든다.
- Caller SQLAlchemy session이 있으면 commit 없이 `audit_event_outbox` row를 같은 UnitOfWork에 추가한다. Session이 없는 legacy producer는 짧은 독립 session으로 Outbox를 commit한다.
- Rollout 4부터 `record_audit()`은 Outbox 저장만 수행하고 기존 `audit.record` Celery task를 발행하지 않는다. Outbox 저장 성공 시 audit id를 반환하고 실패 시 `None`을 반환한다.
- `audit.event_outbox.process`는 Beat가 30초마다 Log queue에서 실행한다. Due row를 `FOR UPDATE SKIP LOCKED`로 분배하고 lease/attempt를 먼저 commit한다.
- Worker는 `AuditLog` insert와 Outbox `succeeded` 전환을 같은 transaction으로 commit한다. 같은 audit id가 이미 있으면 멱등 성공이며, 실패는 safe reason code로 최대 5회 재시도한 뒤 dead-letter 처리한다.
- 성공 commit 뒤 Security Alert 탐지를 발행한다. 발행 실패는 저장 transaction을 되돌리지 않으며 기존 Security Alert reconciliation이 복구 경로다.
- 배포 전 broker에 들어간 메시지를 소진하기 위해 `audit.record` consumer는 호환성 task로 유지하지만 신규 producer에서는 사용하지 않는다.
- Outbox payload는 `workflow_run_id`/`workflow_node_run_id`를 top-level correlation으로 운반한다. 현재 producer의 기존 metadata 값도 호환 입력으로 승격하며 Outbox worker와 호환 consumer가 AuditLog typed FK 컬럼에 저장한다.
- Correlation migration은 정상 UUID와 실제 참조 row가 모두 확인된 기존 metadata 값만 backfill한다. FK는 nullable `ON DELETE SET NULL`이며 두 컬럼에 개별 조회 인덱스를 둔다.

## States

- Change summary available: before/after를 구분해 표시한다.
- Change summary unavailable: 기존 audit detail만 표시하며 오류로 취급하지 않는다.
- Display unavailable: ID-only fallback을 표시하며 목록/detail 조회 실패로 취급하지 않는다.
- Historical/system/null actor: audit detail은 표시하고 actor management control은 제공하지 않는다.
- Sanitization failure: raw payload fallback 없이 summary를 생략하거나 safe error state를 반환한다.

## Interactions

- Audit row click은 AuditDetailDrawer를 연다.
- User actor button은 organization manager에게만 ActorAccessDrawer 진입을 제공한다.
- Actor access mutation 성공 후 audit list/detail을 다시 조회해 canonical event를 확인할 수 있다.
- Security Alert evidence row에서 audit detail로 이동하면 기존 AuditDetailDrawer의 권한과 allowlist를 다시 적용한다. Alert drawer는 raw audit metadata를 직접 렌더링하지 않는다.

## Accessibility

- Safe before/after는 색상만으로 구분하지 않고 `변경 전`, `변경 후` text label을 사용한다.
- Actor button, audit detail drawer, actor access drawer는 keyboard focus와 focus return을 제공한다.
