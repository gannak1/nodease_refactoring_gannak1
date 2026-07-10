# Audit Tracing Component Spec

Status: Draft
Verified Against: feature/mba-188 @ 59d1cc51

검증 값은 MBA-188 SafeChangeSummary와 audit actor management 연동에 적용한다. 다른 trace UI는 각 feature 구현 기준을 따른다.

## Screens

- Audit/Tracing은 MBA-188에서 별도 screen을 만들지 않는다.
- Organization audit list/detail과 actor management 진입 UI는 [Admin Dashboard component spec](../admin-dashboard/component_spec.md)의 `/dashboard/admin` AuditSearchTab, AuditDetailDrawer, ActorAccessDrawer가 소유한다.
- Organization member access semantics는 [Organization component spec](../organization/component_spec.md)이 소유한다.

## Components

### SafeChangeSummary

- Supported access-management event의 before/after safe field를 key/value 목록으로 표시한다.
- Unknown target/action 또는 empty summary면 렌더링하지 않는다.
- Raw JSON toggle이나 generic payload inspector를 제공하지 않는다.

### AuditRecorder

- UI component가 아니라 backend outbound adapter contract다.
- Mutation use case와 같은 UnitOfWork에서 AuditLog row를 준비한다.
- Async best-effort publish 성공을 security mutation 성공 조건으로 사용하지 않는다.

## States

- Change summary available: before/after를 구분해 표시한다.
- Change summary unavailable: 기존 audit detail만 표시하며 오류로 취급하지 않는다.
- Historical/system/null actor: audit detail은 표시하고 actor management control은 제공하지 않는다.
- Sanitization failure: raw payload fallback 없이 summary를 생략하거나 safe error state를 반환한다.

## Interactions

- Audit row click은 AuditDetailDrawer를 연다.
- User actor button은 organization manager에게만 ActorAccessDrawer 진입을 제공한다.
- Actor access mutation 성공 후 audit list/detail을 다시 조회해 canonical event를 확인할 수 있다.

## Accessibility

- Safe before/after는 색상만으로 구분하지 않고 `변경 전`, `변경 후` text label을 사용한다.
- Actor button, audit detail drawer, actor access drawer는 keyboard focus와 focus return을 제공한다.
