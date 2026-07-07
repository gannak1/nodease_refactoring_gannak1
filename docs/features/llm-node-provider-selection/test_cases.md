# LLM Node Provider Selection Test Cases

Status: Draft

## 단위 테스트

- Node credential option builder는 요청 사용자 기준 active organization scope, credential visibility, credential `use`, 대상 model과의 verified relation을 모두 만족하는 credential만 반환한다.
- Option 응답에는 credential value, `encrypted_config`, API key/token, raw owner metadata가 포함되지 않는다.
- 동일 provider credential이 여러 개일 때 응답은 `credential_name`, provider 표시명, `is_valid`로 구분 가능하다.
- Workflow 저장 검증기는 LLM node의 `credential_id`에 대해 비가시 credential(`404` hiding), `use` 권한 없음(`403`), relation 미검증을 각각 거부하고 문제 node id와 reason을 반환한다.
- Runtime credential resolver는 명시 `credential_id`가 있으면 해당 credential만 사용하고, 검증 실패 시 같은 provider의 다른 credential로 대체하지 않는다.
- `credential_id`가 없는 노드는 기존 자동 선택(verified relation priority → 등록 시각 → id, `use` 권한 필수)을 유지한다.
- 명시 credential이 선택된 노드의 `fallback_model_id` 재시도는 선택된 credential이 fallback model과 verified relation을 갖고 `use` 검증을 통과할 때만 수행된다.

## API 테스트

- `GET /api/v1/llm/node-credential-options?model_id=...`는 요청 사용자가 사용할 수 없는 credential을 포함하지 않고, 응답 body 어디에도 secret 원문이 없다.
- `model_id`와 verified relation이 없는 credential은 `use` 권한이 있어도 옵션에서 제외된다.
- Workflow 생성/draft 저장은 권한 없는 `credential_id`를 가진 LLM node가 있으면 실패하고, 성공 응답/저장된 graph에 secret 원문이 없다.
- Active organization scope 밖의 `credential_id` 저장 시도는 `404 resource.not_found`로 숨겨진다.
- 실행 API는 저장 시점에 유효했더라도 실행 시점에 권한이 회수된 명시 credential에 대해 fail-closed로 실패한다.
- 실행 실패 응답과 audit metadata는 reason과 credential 식별자만 포함하고 API key/`encrypted_config` 원문을 포함하지 않는다.

## 권한 테스트

- Credential `use` 권한이 없는 사용자는 옵션 조회, 저장, 실행 어디에서도 해당 credential을 사용할 수 없다.
- 저장 요청 사용자와 실행 사용자가 다를 때 각 경로는 각자의 사용자 기준으로 검증한다. 저장 통과가 실행 검증을 대체하지 않는다.
- 프론트에서 select를 우회해 API로 직접 `credential_id`를 넣어도 Gateway/실행 경로가 차단한다.
- Credential `use` 권한이 있어도 workflow 실행 권한, Knowledge KB/source ACL 권한이 없으면 해당 게이트에서 독립적으로 실패한다.

## E2E 테스트

- 빌더가 동일 provider의 credential 2개 중 하나를 LLM node에 선택 → 저장 → 테스트 실행하면 선택한 credential 기준으로 실행되고 usage log의 credential 식별자가 선택과 일치한다.
- 선택된 credential이 삭제된 뒤 노드 패널은 사용 불가 상태를 표시하고, 실행은 다른 credential로 대체되지 않고 실패한다.
- `credential_id` 없는 기존 workflow는 이 기능 도입 후에도 기존 자동 선택으로 정상 실행된다(하위 호환).
- 배포된 app 실행에서도 명시 credential 재검증이 수행되고 실패 시 fail-closed로 동작한다.

## Edge Case

- Model 변경 후 기존 선택 credential이 새 model과 relation이 없으면 저장이 거부된다.
- Cost Optimizer apply처럼 다른 경로로 LLM node 설정이 바뀌어도 동일한 credential 저장 검증이 적용된다.
- `is_valid=false`로 바뀐 credential은 옵션에서 제외되거나 선택 불가로 표시되고, 이미 선택된 노드의 실행은 실패한다.
- 명시 선택 실패와 legacy 자동 선택 실패는 audit/오류 metadata에서 구분된다.
