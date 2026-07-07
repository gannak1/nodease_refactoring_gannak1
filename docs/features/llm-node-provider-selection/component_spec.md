# LLM Node Provider Selection Component Spec

Status: Draft

## 화면

- LLM node 설정 패널(`LLMNodePanel`)의 model 선택 아래에 provider credential 선택 필드를 추가한다.
- 선택 목록은 현재 사용자가 사용할 수 있는 credential만 표시하고, 동일 provider의 credential이 여러 개면 `credential_name`과 provider 표시명으로 구분한다.
- 선택 필드는 credential 식별 정보만 표시하며 API key, `encrypted_config` 등 secret 관련 값은 어떤 형태로도 표시하지 않는다.

## 컴포넌트

- `LLMNodeCredentialSelect`: 노드의 현재 `model_id` 기준으로 `/api/v1/llm/node-credential-options`를 조회해 선택 가능한 credential 목록을 렌더링한다. 선택 결과를 node data의 `credential_id`에 저장한다.
- `useNodeCredentialOptions(modelId)`: option 조회/로딩/오류 상태를 관리하는 hook. model 변경 시 재조회한다.
- 저장/실행 오류 매핑: Gateway의 credential 검증 오류(node id + reason)를 해당 노드의 오류 상태와 사용자 메시지로 변환한다.

## 상태

- credential 선택: `unselected`(legacy 자동 선택), `selected_valid`, `selected_unavailable`(삭제·비가시·권한 상실 — 존재 여부를 구분해 표시하지 않는다), `selected_invalid`(`is_valid=false`), `relation_mismatch`(현재 model과 verified relation 없음)
- 옵션 목록: `loading`, `loaded`, `empty`(선택 가능한 credential 없음), `error`

## 상호작용

- 사용자가 model을 변경하면 credential 옵션을 재조회한다. 기존 선택이 새 model과 verified relation이 없으면 `relation_mismatch` 상태로 표시하고 저장 전에 재선택을 요구한다.
- `selected_unavailable`/`selected_invalid` 상태의 노드는 패널과 캔버스 노드에 오류 표시를 노출한다. UI는 실행을 막는 최종 경계가 아니며, 상태 계산과 무관하게 Gateway/실행 경로 검증이 수행된다.
- `unselected` 노드는 기존 동작(자동 선택)을 유지하고, UI는 자동 선택 중임을 알 수 있는 표시를 제공할 수 있다. UI가 특정 credential이 선택될 것이라고 예측해 표시하지 않는다.
- 옵션이 `empty`면 credential 등록 권한 안내가 아니라 "사용 가능한 credential 없음" 상태만 표시한다. credential 등록 UI 노출 규칙은 [llm-credentials](../llm-credentials/component_spec.md)를 따른다.
- 저장 시 서버가 credential 검증으로 거부하면 응답의 node id/reason을 해당 노드 오류로 표시하고 저장 실패를 명확히 알린다.

## 접근성

- credential 상태(`selected_unavailable`, `selected_invalid`, `relation_mismatch`)는 색상만이 아니라 text label로 전달한다.
- 선택 필드는 keyboard 조작과 screen reader label을 지원한다.
