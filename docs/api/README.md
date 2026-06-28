# API 명세서

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

API 문서는 HTTP 계약의 source of truth다. 모든 endpoint는 기본적으로 `/api/v1` prefix 아래에 있다.

## 문서

| 문서 | 범위 |
| --- | --- |
| [auth.md](auth.md) | 인증, session/cookie, active organization context |
| [organization-rbac.md](organization-rbac.md) | organization, team, permission 관리 API |
| [apps-workflows.md](apps-workflows.md) | app/workflow CRUD, draft, execute, stream, run detail |
| [llm-credentials.md](llm-credentials.md) | LLM provider, credential, model, pricing |
| [knowledge-rag.md](knowledge-rag.md) | knowledge base, document, RAG retrieval |
| [tracing-audit.md](tracing-audit.md) | trace 조회, LLM trace, audit search, raw payload access |
| [deployments.md](deployments.md) | deployment 생성, 활성화, public info, run/webhook, MVP 3 운영 조회 |
| [errors.md](errors.md) | 공통 error response와 reason code |

## 표기

| Status | 의미 |
| --- | --- |
| `Implemented` | `origin/dev` Gateway route에 존재한다. |
| `Planned` | MVP 요구사항 또는 구현 계획에 있는 목표 계약이다. |
| `Proposed` | ADR 승인 또는 세부 설계 확정 전 후보 계약이다. |

## 공통 규칙

- 인증된 API는 session cookie 또는 bearer token을 사용한다.
- secret 원문은 API 응답, 로그, audit metadata에 노출하지 않는다.
- 권한이 필요한 API는 [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md)의 permission matrix를 따른다.
- active organization 전달 방식은 [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md)이 확정되기 전까지 Proposed 상태다.
- 오류 응답은 [errors.md](errors.md)를 따른다.
