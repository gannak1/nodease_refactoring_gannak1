# LLM 자격 증명 API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1
Related ADRs: [ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission](../decisions/ADR-202606290116-accept-rbac-auth-state-and-user-direct-permission.md)

## 범위

LLM provider, model, credential, model pricing, credential-model sync 계약을 정의한다.

## 엔드포인트

| Status | Method | Path | Request | Response | Permission |
| --- | --- | --- | --- | --- | --- |
| Implemented | `GET` | `/api/v1/llm/providers` | 없음 | `LLMProviderResponse[]` | authenticated |
| Implemented | `GET` | `/api/v1/llm/my-models` | 없음 | `LLMModelResponse[]` | credential `use` + verified credential-model relation |
| Implemented | `GET` | `/api/v1/llm/my-embedding-models` | 없음 | `LLMModelResponse[]` | credential `use` + verified credential-model relation |
| Implemented | `GET` | `/api/v1/llm/credentials` | 없음 | `LLMCredentialResponse[]` | credential `read` |
| Implemented | `POST` | `/api/v1/llm/credentials` | `LLMCredentialCreate` | `LLMCredentialResponse` | organization `manager` |
| Implemented | `DELETE` | `/api/v1/llm/credentials/{credential_id}` | 없음 | message | credential `write` |
| Implemented | `POST` | `/api/v1/llm/credentials/{credential_id}/sync-models` | 없음 | sync result | credential `write` |
| Implemented | `GET` | `/api/v1/llm/stats/top-models` | query | stats | authenticated |
| Implemented | `POST` | `/api/v1/llm/models/sync-pricing` | 없음 | result | system admin |
| Implemented | `PUT` | `/api/v1/llm/models/{model_id}/pricing` | `LLMModelPricingUpdate` | result | system admin |

## 스키마

### `LLMCredentialCreate`

| Field | Type | Required | 설명 |
| --- | --- | --- | --- |
| `provider_id` | UUID | Yes | provider id |
| `organization_id` | UUID | No | credential을 저장할 organization id. 없으면 현재 user의 기본 organization을 사용 |
| `credential_name` | string | Yes | 표시 이름 |
| `api_key` | string | Yes | 원문 API key. 저장 전 암호화해야 한다. |

`api_key`는 응답, 로그, audit metadata에 원문으로 남기지 않는다.

### `LLMCredentialResponse`

| Field | Type | 설명 |
| --- | --- | --- |
| `id` | UUID | credential id |
| `provider_id` | UUID | provider id |
| `user_id` | UUID | 생성 user |
| `credential_name` | string | 표시 이름 |
| `config_preview` | string | masking된 key preview |
| `is_valid` | boolean | 검증 상태 |
| `quota_type` | string | quota 유형 |
| `quota_limit` | integer | quota limit |
| `quota_used` | integer | quota used |

## MVP 1 변경 기준

- credential 조회/사용/삭제/sync는 organization scope와 credential permission을 기준으로 판정한다.
- 현재 코드에서 삭제와 sync는 `ensure_llm_credential_permission(..., "write")`를 호출한다. `write`의 최소 상태는 `manager`다.
- workflow engine LLM node는 credential `use` 권한이 없으면 실행을 차단한다.
- model 전용 permission table은 만들지 않는다. credential 권한과 `llm_rel_credential_models` 검증 상태로 사용 가능 모델을 제한한다.
