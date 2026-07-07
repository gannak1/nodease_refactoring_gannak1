# LLM Node Provider Selection API Spec

Status: Draft

## Endpoints

| Method | Path | 설명 | 권한 |
| --- | --- | --- | --- |
| GET | `/api/v1/llm/node-credential-options` | LLM node에서 선택 가능한 provider credential safe option을 반환한다. `model_id` query로 특정 model과 verified relation이 있는 credential만 필터링한다 | Active organization scope, credential visibility, credential `use`, verified credential-model relation |
| POST | `/api/v1/workflows` | 기존 workflow 생성. LLM node에 `credential_id`가 있으면 저장 검증을 수행한다 | 기존 권한 + credential 저장 검증 |
| POST | `/api/v1/workflows/{workflow_id}/draft` | 기존 draft 저장. LLM node에 `credential_id`가 있으면 저장 검증을 수행한다 | 기존 권한 + credential 저장 검증 |
| POST | `/api/v1/workflows/{workflow_id}/execute`, `/api/v1/workflows/{workflow_id}/execute/stream` | 기존 실행. 명시 `credential_id`는 실행 시점에 재검증된다 | 기존 권한 + credential 실행 재검증 |
| POST | `/api/v1/deployments` 및 배포 실행 경로 | 기존 배포/배포 실행. 명시 `credential_id`는 배포 실행 시점에 재검증된다 | 기존 권한 + credential 실행 재검증 |

기존 `/api/v1/llm/my-models`는 model listing surface로 유지한다. credential 구분이 필요한 노드 설정 UI는 `node-credential-options`를 사용한다.

## 요청과 응답 모델

### Node Credential Option

Request query:

- `model_id`: 노드에 선택된 model의 `model_id_for_api_call`. 필수. 이 model과 verified relation이 없는 credential은 응답에서 제외한다.

Response는 실행 선택을 위한 safe option schema다. [llm-credentials](../llm-credentials/api_spec.md)의 safe option schema 정책을 따른다.

- `credential_id`
- `credential_name`
- `provider_id`, `provider_name`
- `is_valid`
- 진단에 필요한 경우 relation 상태

credential value, `encrypted_config`, API key/token, raw quota detail, raw timestamp, owner/user metadata는 포함하지 않는다.

### LLM Node 설정

LLM node data에 다음 필드를 추가한다.

- `credential_id`: optional string(UUID). 선택된 provider credential 참조. 없으면 legacy 자동 선택 경로를 사용한다.

기존 `provider`(표시용), `model_id`, `fallback_model_id` 필드는 유지한다. `credential_id`는 workflow graph, draft, version snapshot에 식별자로만 저장된다.

### 저장 검증

`POST /api/v1/workflows`, `POST /api/v1/workflows/{workflow_id}/draft`는 graph 안의 LLM node에 `credential_id`가 있으면 저장 요청 사용자 기준으로 다음을 검증한다.

1. credential이 active organization scope 안에서 요청 사용자에게 보이는지
2. 요청 사용자가 credential `use` 권한을 갖는지
3. credential이 해당 노드의 `model_id`와 verified relation을 갖는지

검증 실패 시 저장 전체를 거부하고, 응답 오류에 문제가 된 node id와 reason을 포함한다.

### 실행/배포 재검증

실행 경로(테스트 실행, 배포된 app 실행)는 execution 사용자 기준으로 저장 검증과 동일한 항목을 재검증한다. 명시 `credential_id` 검증이 실패하면 같은 provider의 다른 credential로 대체하지 않고 fail-closed로 실패한다. `credential_id`가 없는 노드는 기존 runtime 자동 선택을 유지한다.

## 오류

- Active organization scope 밖이거나 보이지 않는 `credential_id`는 resource hiding 정책에 따라 `404 resource.not_found`로 숨긴다 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)).
- 보이지만 `use` 권한이 없는 credential은 `403 permission.denied`로 거부한다.
- 선택된 credential이 노드 `model_id`와 verified relation이 없으면 저장/실행을 거부한다(runtime reason: `model_relation_not_verified`).
- Runtime 실패 reason은 기존 세분화(`organization_scope_missing`, `credential_not_available`, `model_relation_not_verified`, `model_inactive`, `credential_use_denied`)를 재사용하고, 실패 metadata에서 명시 선택 실패와 legacy 자동 선택 실패를 구분할 수 있어야 한다.
- 선택된 credential이 삭제된 경우 존재 여부를 노출하지 않는 동일한 hiding 정책으로 처리한다(저장/옵션 조회는 `404 resource.not_found`, runtime은 `credential_not_available`).
- 오류 메시지와 audit metadata에는 credential 식별자와 reason만 포함하고 secret 원문을 포함하지 않는다.

## 권한

- Node credential option API는 요청 사용자가 현재 active organization context에서 실행 가능한 safe pair만 반환한다. 다른 사용자의 가시성이나 권한을 대신 평가하지 않는다.
- 저장 검증은 저장 요청 사용자 기준, 실행/배포 재검증은 execution 사용자 기준이다. 저장 통과가 실행 권한을 부여하지 않는다.
- Credential `use` 권한은 workflow 실행 권한, Knowledge KB/source ACL 권한, connector/connection 권한을 대체하지 않는다.
- 프론트 UI의 credential 목록 필터링은 UX 편의이며 최종 차단은 Gateway와 실행 경로가 수행한다.
