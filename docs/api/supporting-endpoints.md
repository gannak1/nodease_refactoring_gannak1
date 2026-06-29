# Supporting Endpoint API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f

## 범위

주요 제품 도메인 문서에 속하지 않는 health, DB connector, prompt/code/template wizard helper API 계약을 정의한다.

## Health

| Status | Method | Path | Request | Response | 설명 |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/health` | 없음 | health payload | Gateway 및 DB health check |

Gateway health 응답은 DB `SELECT 1`까지 확인한다.

성공:

```json
{
  "status": "ok",
  "service": "Moduly API",
  "database": "ok"
}
```

DB 연결 실패 시 HTTP status는 `503`이고 `database` 값에 오류 메시지를 포함한다.

Nginx 컨테이너의 `/health`는 Gateway health가 아니라 단순 reverse proxy health endpoint다. 현재 `docker/nginx/nginx.conf`는 `/health`에 대해 plain text `OK`를 즉시 반환한다.

## Connector

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/connectors/test` | `DBConnectionTestRequest` | `DBConnectionTestResponse` | unauthenticated connection test helper |
| Implemented | `POST` | `/api/v1/connectors` | `DBConnectionTestRequest` | save result | authenticated; connection owner becomes current user |
| Implemented | `GET` | `/api/v1/connectors/{connection_id}` | 없음 | `DBConnectionDetailResponse` | connection owner |
| Implemented | `GET` | `/api/v1/connectors/{connection_id}/schema` | 없음 | schema payload | connection owner |

Connector response는 DB/SSH password, private key 같은 secret 원문을 반환하지 않는다. 현재 connector owner 기준 API는 MVP 2 connection policy 정렬 전의 current-user owner scope다.

현재 지원 DB 타입은 `postgres`뿐이다. `POST /api/v1/connectors/test`는 인증 dependency가 없고, `POST /api/v1/connectors`는 저장 전 연결 테스트를 다시 수행한 뒤 DB/SSH secret을 암호화해서 저장한다.

`GET /api/v1/connectors/{connection_id}/schema`는 owner 확인 후 서버 내부에서 secret을 복호화해 DB에 접속한다. secret은 API 응답에 포함하지 않는다.

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

현재 wizard helper는 provider별로 효율 모델을 고정 선택한다. 코드/템플릿 위저드는 endpoint 내부 map을 사용하고, 프롬프트 위저드는 `LLMService.EFFICIENT_MODELS`를 사용한다. credential이 없으면 `400`과 `credentials_required=true` 성격의 detail을 반환한다.
