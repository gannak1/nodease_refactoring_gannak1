# 아키텍처

Status: Draft
Authority: Architecture
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1

아키텍처 문서는 서비스 경계, 런타임 흐름, 보안/RBAC 적용 위치를 정의한다.

| 문서 | 역할 |
| --- | --- |
| [system-overview.md](system-overview.md) | 상위 서비스 구조와 책임 |
| [auth-rbac.md](auth-rbac.md) | 인증, organization context, RBAC enforcement 위치 |
| [tracing-audit.md](tracing-audit.md) | audit/tracing 경계와 raw payload 접근 원칙 |

## 권위

- Controller에 비즈니스 로직을 넣지 않는다.
- Controller에서 DB를 직접 상세 조회해 권한 판단을 하지 않는다.
- RBAC, tracing access, audit recording은 service/helper 경계에서 수행한다.
- DB schema의 최종 기준은 [data-model/](../data-model/README.md)를 따른다.
