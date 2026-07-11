# LLM Credentials API Spec

Status: Draft
## Endpoints

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| GET | `/api/v1/llm/agent-answer-options` | RAG Agent answer generation에 사용할 수 있는 safe model/credential pair를 반환한다 | Active organization scope, credential `use`, verified credential-model relation |
| GET | `/api/v1/llm/my-models` | 현재 model listing surface | 현재 동작 |
| GET | `/api/v1/llm/credentials` | 현재 credential listing surface | 현재 동작. 목표 Agent answer option 계약이 아니다 |
| POST | `/api/v1/llm/credentials` | active organization에 LLM credential을 등록하고 provider 모델 relation을 동기화한다 | Organization manager only |
| DELETE | `/api/v1/llm/credentials/{credential_id}` | active organization의 LLM credential을 삭제한다 | Organization manager 또는 credential `manage` |

## 요청과 응답 모델

### Credential Registration

Credential registration은 개인 사용자 credential 생성 API가 아니다. 요청은 active organization context에서 처리되며, 요청자는 해당 organization manager여야 한다. 일반 member는 credential `use` 또는 기존 credential `manage` 권한을 갖고 있어도 새 credential을 등록할 수 없다.

Request:

- `provider_id`
- `organization_id`: 대상 organization. header 기반 active organization과 일치해야 한다. legacy fallback을 허용하는 구현에서도 결과 credential은 organization-scoped resource로 해석한다.
- `credential_name`
- `api_key`: raw secret. 저장 직후 응답, audit, trace, usage metadata에 원문을 반환하지 않는다.

Response는 `LLMCredentialResponse`를 사용할 수 있지만, `encrypted_config`, raw `api_key`, provider raw response는 포함하지 않는다. `user_id`가 포함되는 구현에서는 등록 행위자 reference로만 해석하고 개인 credential 소유권으로 표시하지 않는다.

### Agent Answer Option

Auto collection mode를 포함한 target Agent answer flow는 별도 ADR이 preset/default selection을 추가하기 전까지 명시 `generation_model_id`와 `credential_id`를 요구한다.

Option response는 전체 credential read schema가 아니라 실행 선택을 위한 safe schema다. 포함할 수 있는 값은 다음과 같다.

- `model_id`, `model_name`, provider/model display field, model type, context window
- `credential_id`, `credential_name`, provider id/name, `config_preview`, `is_valid`
- 진단에 필요한 경우 verified relation id 또는 relation status

별도 API 계약이 명시적으로 허용하지 않는 한 credential value, encrypted config, API key/token, selection에 필요 없는 raw quota detail, raw timestamp, owner/user metadata를 포함하지 않는다.

## 오류

- Credential 등록 요청자가 target organization manager가 아니면 `403 permission.denied`로 실패해야 한다.
- Organization scope 밖 `organization_id` 또는 credential id는 resource hiding 정책에 따라 `404 resource.not_found`로 숨긴다.
- Knowledge target flow에서 generation model/credential이 없거나 보이지 않으면 answer run 생성 전에 실패한다.
- Credential `use` denial은 KB permission 및 source ACL authorization과 독립된 permission failure다.
- Verified credential-model relation이 없으면 fail-closed로 처리하며, client는 fallback model/credential selection을 추론하면 안 된다.
- Default credential/preset ambiguity는 향후 ADR/API 계약이 정의하기 전까지 이 API가 처리하지 않는다.

## Target Provider Execution Capability Contract

이 contract는 Workflow/Conversation Memory composition이 호출하는 internal application port이며 raw credential을 반환하는 public HTTP endpoint가 아니다.

입력:

- canonical organization/workflow/deployment ID와 immutable version 또는 snapshot hash
- node/invocation reference
- execution subject 또는 public audience
- `purpose=main_generation | memory_summary`
- requested bounded input/output token과 cost ceiling

출력 opaque capability:

- provider/model/credential safe reference와 verified relation revision
- credential permission revision
- egress policy revision과 pricing revision
- approved token/cost cap, purpose와 expiry

Memory summary 초기 정책은 `inherit_node`만 허용한다. Main node의 approved scope에서 별도 `memory_summary` capability를 발급하며 direct credential ID, name/order fallback과 `organization_default`를 거부한다. Credential revoke/permission loss, model relation/egress/pricing revision mismatch, wrong deployment/node/purpose 또는 expiry는 context materialization·budget reservation·provider call 전에 fail-closed한다. Capability, credential principal과 public Access Grant는 execution subject나 audit actor가 아니다.

## 권한

- Credential 등록은 organization manager 전용이다. Credential `use`, credential `manage`, workflow manager, builder/operator 권한은 새 credential 등록 권한을 부여하지 않는다.
- 등록된 credential은 active organization scope에 속한다. 개인 사용자 credential scope를 만들지 않는다.
- Agent answer generation preflight는 active organization scope, model visibility, credential visibility, credential `use`, verified credential-model relation을 검증해야 한다.
- UI option API는 현재 active organization context에서 실행 가능한 safe pair만 보여줄 수 있다.
- Credential 존재 또는 사용 가능 상태는 KB content permission, collection routing permission, source ACL authorization을 부여하지 않는다.
- ProviderExecutionCapability는 credential secret을 포함하거나 client/API response에 노출되지 않는다. Consumer는 safe opaque reference/revision만 전달한다.
