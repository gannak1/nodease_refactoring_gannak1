# 문서 권위

Status: Draft
Authority: Foundation
Source of Truth: Yes
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f

## 목적

문서 간 충돌이 발생했을 때 어떤 문서를 기준으로 판단할지 정의한다.

## 권위 순서

| 충돌 주제 | 우선 문서 |
| --- | --- |
| 용어, 문서 상태, source-of-truth 규칙 | `foundation/*` |
| 제품 요구사항, MVP 완료 기준, 제외 범위 | `requirements/*` |
| 서비스 경계, 레이어, 런타임 흐름, 보안 경계 | `architecture/*` |
| 물리 데이터 모델, 테이블, 권한 정책, migration | `data-model/*` |
| HTTP API, request/response, error contract | `api/*` |
| 배포 런타임, 환경변수, 헬스체크, ingress, container entrypoint | `docker/**`, `infra/**`, `scripts/**`, root `README.md` |
| 중요 설계 결정의 근거 | `decisions/*` |
| 작업 순서, 이슈 분해, rollout | `implementation-plan/*` |
| 과거 조사, 메모, 폐기 초안 | `references/*` |

## 충돌 규칙

1. 같은 주제를 다루는 문서가 충돌하면 위 표의 권위 영역을 따른다.
2. `implementation-plan/*` 문서가 요구사항, 아키텍처, 데이터 모델, API 문서와 충돌하면 구현 계획을 수정한다.
3. `references/*` 문서는 구현 기준이 아니다.
4. `Status: Superseded` 문서는 active source of truth가 아니다.
5. 권위 영역을 바꾸는 결정은 ADR로 기록한다.

## 필수 메타데이터

새 active 문서는 가능하면 아래 메타 정보를 문서 상단에 둔다.

```md
Status: Draft | Accepted | Superseded
Authority: Foundation | Requirements | Architecture | Data Model | API | Decision | Implementation Plan | Reference
Source of Truth: Yes | No
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f
Related ADRs:
```

## 현재 기준

현재 active 문서 정합성 기준은 workspace code `dev`의 `c990b54e931b4de8023822f6dff14f43fc1d415f`다. 코드와 active 문서가 충돌하면 코드를 기준으로 active 문서를 수정한다.

`references/moduly-architecture/`는 과거 `main` 기준 역공학 문서다. 이 문서는 현재 코드의 ERD나 tracing/RBAC 구조를 완전히 반영하지 않으므로 구현 기준으로 사용하지 않는다.
