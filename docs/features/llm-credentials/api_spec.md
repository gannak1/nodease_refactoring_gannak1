# LLM Credentials API Spec

Status: Draft
Verified Against: current implementation baseline plus Knowledge target model ADR-0014

## Endpoints

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| GET | `/api/v1/llm/agent-answer-options` | RAG Agent answer generation에 사용할 수 있는 safe model/credential pair를 반환한다 | Active organization scope, credential `use`, verified credential-model relation |
| GET | `/api/v1/llm/my-models` | 현재 model listing surface | 현재 동작 |
| GET | `/api/v1/llm/credentials` | 현재 credential listing surface | 현재 동작. 목표 Agent answer option 계약이 아니다 |

## 요청과 응답 모델

### Agent Answer Option

Auto collection mode를 포함한 target Agent answer flow는 별도 ADR이 preset/default selection을 추가하기 전까지 명시 `generation_model_id`와 `credential_id`를 요구한다.

Option response는 전체 credential read schema가 아니라 실행 선택을 위한 safe schema다. 포함할 수 있는 값은 다음과 같다.

- `model_id`, `model_name`, provider/model display field, model type, context window
- `credential_id`, `credential_name`, provider id/name, `config_preview`, `is_valid`
- 진단에 필요한 경우 verified relation id 또는 relation status

별도 API 계약이 명시적으로 허용하지 않는 한 credential value, encrypted config, API key/token, selection에 필요 없는 raw quota detail, raw timestamp, owner/user metadata를 포함하지 않는다.

## 오류

- Knowledge target flow에서 generation model/credential이 없거나 보이지 않으면 answer run 생성 전에 실패한다.
- Credential `use` denial은 KB permission 및 source ACL authorization과 독립된 permission failure다.
- Verified credential-model relation이 없으면 fail-closed로 처리하며, client는 fallback model/credential selection을 추론하면 안 된다.
- Default credential/preset ambiguity는 향후 ADR/API 계약이 정의하기 전까지 이 API가 처리하지 않는다.

## 권한

- Agent answer generation preflight는 active organization scope, model visibility, credential visibility, credential `use`, verified credential-model relation을 검증해야 한다.
- UI option API는 현재 active organization context에서 실행 가능한 safe pair만 보여줄 수 있다.
- Credential 존재 또는 사용 가능 상태는 KB content permission, collection routing permission, source ACL authorization을 부여하지 않는다.
