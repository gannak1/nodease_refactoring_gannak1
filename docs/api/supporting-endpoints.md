# Supporting Endpoint API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1

## 범위

주요 제품 도메인 문서에 속하지 않는 health, DB connector, prompt/code/template wizard helper API 계약을 정의한다.

## Health

| Status | Method | Path | Request | Response | 설명 |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/health` | 없음 | health payload | Gateway health check |

## Connector

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/connectors/test` | `DBConnectionTestRequest` | `DBConnectionTestResponse` | unauthenticated connection test helper |
| Implemented | `POST` | `/api/v1/connectors` | `DBConnectionTestRequest` | save result | authenticated; connection owner becomes current user |
| Implemented | `GET` | `/api/v1/connectors/{connection_id}` | 없음 | `DBConnectionDetailResponse` | connection owner |
| Implemented | `GET` | `/api/v1/connectors/{connection_id}/schema` | 없음 | schema payload | connection owner |

Connector response는 DB/SSH password, private key 같은 secret 원문을 반환하지 않는다. 현재 connector owner 기준 API는 MVP 2 connection policy 정렬 전의 current-user owner scope다.

## Wizard Helpers

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/prompt-wizard/check-credentials` | 없음 | `{ "has_credentials": boolean }` | authenticated; current user credential scope |
| Implemented | `POST` | `/api/v1/prompt-wizard/improve` | `PromptImproveRequest` | `PromptImproveResponse` | authenticated; current user credential scope |
| Implemented | `GET` | `/api/v1/code-wizard/check-credentials` | 없음 | `{ "has_credentials": boolean }` | authenticated; current user credential scope |
| Implemented | `POST` | `/api/v1/code-wizard/generate` | `CodeGenerateRequest` | `CodeGenerateResponse` | authenticated; current user credential scope |
| Implemented | `GET` | `/api/v1/template-wizard/check-credentials` | 없음 | `{ "has_credentials": boolean }` | authenticated; current user credential scope |
| Implemented | `POST` | `/api/v1/template-wizard/improve` | `TemplateImproveRequest` | `TemplateImproveResponse` | authenticated; current user credential scope |

Wizard helper API는 현재 코드에서 current user의 유효한 LLM credential을 직접 조회한다. MVP 1 LLM credential permission helper와 완전히 같은 organization-level routing 계약으로 정렬하는 것은 후속 보강 대상이다.
