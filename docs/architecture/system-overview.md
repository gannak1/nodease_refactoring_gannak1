# 시스템 개요

Status: Draft
Authority: Architecture
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

## 서비스

| 구성요소 | 책임 |
| --- | --- |
| Client | Workflow 편집, 설정, RBAC/observability UI |
| Gateway | 인증된 API와 resource permission enforcement 경계 |
| Workflow Engine | Workflow 실행과 node runtime |
| Sandbox | 격리된 코드 실행 |
| Shared | DB model, schema, 공통 service, tracing/audit utility |
| PostgreSQL | 영속 상태 저장 |
| Redis/Celery | 비동기 task queue와 실행 조율 |

## 경계 규칙

- Gateway endpoint는 비즈니스 판단을 service/helper layer에 위임한다.
- Workflow Engine은 가능한 경우 user, organization, workflow, run, node 식별자를 포함한 execution context를 받아야 한다.
- 공통 tracing/audit service가 trace 접근과 payload 처리의 경계다.
- Secret 값은 client 응답으로 반환하거나 log에 기록하지 않는다.

이전 Moduly 역공학 과정에서 정리한 상세 runtime 사실은 참조용이다: [references/moduly-architecture/](../references/moduly-architecture/README.md).
