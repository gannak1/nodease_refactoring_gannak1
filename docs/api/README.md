# API 명세서

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1

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
| [deployments.md](deployments.md) | deployment 생성, 활성화, public info, run/webhook |
| [supporting-endpoints.md](supporting-endpoints.md) | health, DB connector, prompt/code/template wizard helper API |
| [errors.md](errors.md) | 공통 error response와 reason code |

## 표기

| Status | 의미 |
| --- | --- |
| `Implemented` | 현재 코드의 Gateway route에 존재한다. |
| `Planned` | MVP 요구사항 또는 구현 계획에 있는 목표 계약이다. |
| `Proposed` | ADR 승인 또는 세부 설계 확정 전 후보 계약이다. |
| `Partial` | route 또는 권한 관문은 있으나 request/response 세부 계약이 완성되지 않았다. |

## 공통 규칙

- 인증된 API는 session cookie 또는 bearer token을 사용한다.
- secret 원문은 API 응답, 로그, audit metadata에 노출하지 않는다.
- 권한이 필요한 API는 [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md)의 permission matrix를 따른다.
- active organization은 [ADR-202606290145-active-organization-header-context](../decisions/ADR-202606290145-active-organization-header-context.md)에 따라 `X-Organization-Id` header로 전달한다.
- 오류 응답은 [errors.md](errors.md)를 따른다.
