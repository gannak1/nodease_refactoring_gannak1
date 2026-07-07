# LLM Node Provider Selection Requirements

Status: Draft
Related Features: workflow, llm-credentials, organization, auth, deployment, cost-optimizer, audit-tracing

## Purpose

Organization은 동일 provider(회사)의 LLM credential을 여러 개 등록할 수 있다. 현재 workflow LLM node는 model만 선택하고, runtime이 verified credential-model relation priority와 credential 등록 시각 기준으로 credential을 자동 선택한다. 이 기능은 LLM node 설정에서 사용할 provider credential을 명시적으로 선택할 수 있게 하고, 선택된 credential을 workflow 저장, 실행, 배포 경로 모두에서 권한 검증을 통과한 경우에만 사용하도록 한다.

이 문서는 "credential을 누가 등록/삭제할 수 있는가"를 다루지 않는다. 그 경계는 [llm-credentials](../llm-credentials/requirements.md)가 소유한다. 이 문서는 이미 등록된 credential을 LLM node가 어떻게 선택하고, 그 선택이 어디에서 검증되는가를 다룬다.

## 현재 동작 (구현 기준)

Verified Against: feature/mba-126 @ b706d33

- `LLMNodeData`는 `model_id`, `fallback_model_id`를 저장하며 credential 참조 필드가 없다. `provider` 필드는 optional 표시용 문자열이다.
- Runtime은 `LLMService.get_runtime_client_for_user`가 model의 provider와 active organization scope 안에서 valid credential을 조회하고, verified relation priority → credential 등록 시각 → credential id 순으로 정렬해 credential `use` 권한을 통과하는 첫 credential을 선택한다.
- 선택 실패는 `organization_scope_missing`, `credential_not_available`, `model_relation_not_verified`, `model_inactive`, `credential_use_denied` reason으로 세분화되고 permission denied audit이 남는다.
- Workflow 저장(draft sync 포함) 경로는 LLM node의 credential 관련 검증을 수행하지 않는다.
- LLM node 설정 UI는 `/api/v1/llm/my-models`로 model 목록만 조회하며 credential 구분 UI가 없다.

## User Stories

- 빌더로서, 같은 회사의 credential이 여러 개일 때 어떤 credential로 LLM node가 실행되는지 명시적으로 선택하고 싶다.
- 빌더로서, 내가 `use` 권한을 가진 credential만 선택 목록에서 보고 싶다.
- 빌더로서, 선택해 둔 credential이 삭제되었거나 더 이상 쓸 수 없으면 노드 설정 화면에서 바로 알고 싶다.
- 관리자로서, 권한 없는 사용자가 credential id를 직접 지정해 저장/실행/배포하는 것을 UI가 아니라 Gateway와 실행 경로에서 차단하고 싶다.
- 운영자로서, 선택된 credential 기준 실행 실패가 어떤 이유(삭제, 권한 회수, relation 미검증, invalid)였는지 raw secret 없이 추적하고 싶다.

## Functional Requirements

- FR-001: LLM node 설정은 선택된 provider credential 참조(`credential_id`)를 저장할 수 있어야 한다. 저장하는 값은 식별자뿐이며 credential secret, `encrypted_config`, API key 값은 node 설정, workflow graph, version snapshot 어디에도 저장하지 않는다.
- FR-002: Credential 선택 옵션 조회는 요청 사용자 기준으로 active organization scope, credential visibility, credential `use` 권한, 노드에 선택된 model과의 verified credential-model relation을 모두 만족하는 safe option만 반환한다.
- FR-003: 동일 provider의 credential이 여러 개인 경우 `credential_name`, provider 표시명, `is_valid` 상태처럼 구분 가능한 metadata를 함께 제공한다. 옵션 응답은 [llm-credentials](../llm-credentials/api_spec.md)의 safe option schema 정책을 따르며 secret 원문을 포함하지 않는다.
- FR-004: 요청 사용자에게 보이지 않는 credential은 옵션 목록에서 제외한다(resource hiding, [ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)). 노드에 이미 저장된 `credential_id`가 현재 사용자에게 보이지 않으면 UI는 "사용할 수 없는 credential" 상태로만 표시하고 해당 credential의 존재 여부나 이름을 노출하지 않는다.
- FR-005: Workflow 저장(생성, draft sync) 시 Gateway는 LLM node에 `credential_id`가 있으면 저장 요청 사용자 기준으로 (a) active organization scope 내 visibility, (b) credential `use` 권한, (c) 노드 `model_id`와의 verified credential-model relation을 검증하고, 실패하면 저장을 거부한다.
- FR-006: Workflow 실행(테스트 실행 포함)과 배포된 app 실행 시 runtime은 실행 시점 execution 사용자 기준으로 FR-005와 동일한 검증을 다시 수행한다. 저장 시 검증 통과를 실행 권한으로 캐시하거나 재사용하지 않는다.
- FR-007: 명시 선택된 credential의 runtime 검증이 실패하면 fail-closed로 실행을 실패시킨다. 같은 provider의 다른 credential로 조용히 대체하지 않는다.
- FR-008: `credential_id`가 없는 기존 LLM node는 현재 runtime 자동 선택(verified relation priority → credential 등록 시각 → credential id, credential `use` 권한 필수)을 하위 호환으로 유지한다. 이 자동 선택은 legacy 호환 경로이며, [llm-credentials](../llm-credentials/requirements.md)의 default credential/preset 정책을 새로 도입하는 것이 아니다.
- FR-009: `credential_id`가 명시된 노드에서 `fallback_model_id`로 재시도할 때는 선택된 credential이 fallback model과 verified relation을 갖고 `use` 권한 검증을 통과하는 경우에만 fallback을 수행한다. 그렇지 않으면 fallback 없이 원래 오류로 실패한다.
- FR-010: 선택된 credential이 삭제되었거나, `use` 권한이 회수되었거나, `is_valid=false`로 바뀐 경우: UI는 노드를 오류/비활성 상태로 표시하고, 저장/실행/배포는 세분화된 reason으로 실패하며, 실패 audit metadata에는 credential 식별자와 reason만 남긴다.
- FR-011: Credential 원문, API key, token, `encrypted_config` 값은 옵션 API 응답, workflow graph/version, 실행 로그, trace, audit metadata, 오류 메시지 어디에도 노출하지 않는다.

## Policies And Edge Cases

- `credential_id`는 secret이 아니라 식별자다. 다만 존재 여부 자체는 resource hiding 정책을 따른다. Active organization scope 밖이거나 보이지 않는 credential id는 `404 resource.not_found`로 숨기고, 보이지만 `use` 권한이 없으면 `403 permission.denied`로 거부한다.
- 저장 요청 사용자와 실행 주체는 다를 수 있다. 저장 시 검증은 편집 UX와 조기 실패를 위한 경계이고, 최종 보안 판단은 실행/배포 경로의 재검증이다. 프론트 UI 차단만으로 권한을 처리하지 않는다.
- Workflow version이나 배포 snapshot에 `credential_id`가 저장되어 있어도 실행 시점 재검증을 생략하지 않는다.
- Cost Optimizer apply처럼 LLM node 설정을 변경하는 다른 저장 경로도 동일한 credential 검증 경계를 통과해야 한다.
- Credential 선택은 model 선택을 대체하지 않는다. 선택된 credential은 노드의 `model_id`와 verified relation이 있어야 하며, model을 변경하면 기존 credential 선택이 새 model과 relation이 없을 수 있다. 이 경우 UI는 저장 전에 재선택을 요구한다.
- LLM node RAG 옵션의 retrieval 권한(Knowledge KB permission, source ACL)과 credential `use` 권한은 서로를 대체하지 않는다. 실패도 구분해 기록한다.
- Credential `use` 권한이 있어도 organization/workflow의 예산 차단, model inactive 같은 다른 실행 게이트를 우회하지 않는다.
- 명시 선택 실패와 legacy 자동 선택 실패는 audit/오류 metadata에서 구분할 수 있어야 한다(예: selection source 표시).

## Open Questions

- 명시 `credential_id` 선택을 신규 LLM node에 필수로 강제할 시점과, legacy 자동 선택 경로를 언제 제거할지. 결정 전 임시 처리: `credential_id`는 optional로 두고 없으면 기존 자동 선택을 유지한다.
- `fallback_model_id`에 대해 별도 fallback credential 선택 필드를 둘지. 결정 전 임시 처리: FR-009대로 선택된 credential로만 fallback을 허용한다.
- 협업 편집에서 다른 사용자가 선택해 둔 credential에 저장 요청 사용자가 `use` 권한이 없는 경우, workflow 전체 저장을 거부할지 해당 노드만 오류로 반환할지. 결정 전 임시 처리: 저장을 거부하되 응답에 문제 node id와 reason을 포함해 어떤 노드가 막혔는지 알 수 있게 한다.
- 저장된 credential이 삭제된 workflow를 배포 상태로 유지할지, 배포 toggle/실행 시점에만 차단할지. 결정 전 임시 처리: 배포 상태는 유지하되 실행 시 fail-closed로 실패하고 오류 reason을 남긴다.
