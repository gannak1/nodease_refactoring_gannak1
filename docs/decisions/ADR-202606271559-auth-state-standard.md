# ADR-202606271559: auth_state 표준화

Status: Proposed
Authority: Decision
Source of Truth: No
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Created At: 2026-06-27 15:59 KST

## 배경

현재 tracing RBAC 코드는 `read`, `write`, `execute`, `admin` 값을 사용한다. MVP 목표 권한 모델은 application-level 상태로 `none`, `viewer`, `operator`, `builder`, `manager`, `auditor`, `raw_auditor`를 사용한다.

두 체계를 동시에 방치하면 권한 판정, UI 표시, migration, 테스트 기준이 흔들릴 수 있다.

## 선택지

| 선택지 | 설명 | 장단점 |
| --- | --- | --- |
| 기존 값 유지 | `read/write/execute/admin`을 계속 사용한다. | 코드 변경은 적지만 제품 권한 vocabulary가 약하다. |
| MVP 상태로 전환 | `viewer/operator/builder/manager`와 audit 상태를 사용한다. | 제품 의미는 명확하지만 migration과 호환 처리가 필요하다. |
| 호환 mapping | 전환 기간에는 기존 값과 새 값을 모두 해석한다. | rollout은 안전하지만 코드 경로가 늘어난다. |

## 결정

아직 확정하지 않는다. 현재 계획은 MVP 상태를 표준으로 삼고, 기존 row에 `read/write/execute/admin`이 남아 있으면 compatibility mapping으로 해석하는 것이다.

## 영향

- 권한 정책: [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md)
- 아키텍처: [architecture/auth-rbac.md](../architecture/auth-rbac.md)
- API 계약: [api/organization-rbac.md](../api/organization-rbac.md)
- 구현 계획: [implementation-plan/mvp-1-development-issue-plan.md](../implementation-plan/mvp-1-development-issue-plan.md)

## 후속 검토

- migration 전 정확한 mapping 표를 확정한다.
- `apps/shared/services/tracing/rbac.py`의 권한 해석을 표준값 기준으로 정리한다.
- legacy 값과 신규 값 모두에 대한 테스트를 추가한다.
