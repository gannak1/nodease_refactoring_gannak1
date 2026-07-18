# LLM Credentials Component Spec

Status: Draft
## 화면

- Credential management/listing surface는 active organization의 credential 상태를 표시한다. 개인 사용자 credential 등록 화면을 제공하지 않는다.
- Credential 제거 action은 물리 삭제로 오해되지 않도록 revoke/사용 중지 의미와 기존 usage·audit 이력 보존을 안내한다. Current API의 legacy `deleted` message를 secret purge 완료로 표시하지 않는다.
- Credential 등록 UI는 organization manager에게만 노출한다. 일반 member, builder/operator, credential `use` 권한자에게는 등록 control을 숨기고 서버 403을 최종 경계로 둔다.
- Agent answer option surface는 실행 가능한 safe model/credential pair만 표시한다.

## 컴포넌트

- `CredentialRegistrationGate`: active organization manager 여부를 확인하고 credential 등록 control 노출을 결정한다.
- `CredentialPermissionService`: credential visibility와 `use` permission을 평가한다.
- `CredentialModelRelationResolver`: credential-model pair가 active이고 verified 상태인지 확인한다.
- `LlamaParseCredentialResolver`: document parsing 직전에 execution subject, active organization, `llamaparse` provider 호환성, valid 상태와 credential `use` 권한을 확인하고 단일 허용 credential의 parser 입력만 반환한다. FileProcessor는 ORM row나 저장 config를 직접 해석하지 않는다.
- `AgentAnswerOptionProvider`: credential secret이나 전체 owner metadata를 반환하지 않고 standalone RAG answer flow용 safe option schema를 만든다.
- `DeploymentCredentialPolicyService`: manager-only deployment policy write/read boundary다. Canonical deployment row를 lock하고 immutable deployment graph의 exact LLM node/model과 organization-scoped credential, verified relation, credential `use`를 server-side에서 대조해 node당 단일 active revisioned policy row를 만든다. Graph, request body, public runtime actor가 credential principal을 선택하지 못하게 한다.
- `ProviderExecutionCapabilityIssuer`: 이 capability 계약의 authoritative owner다. Canonical runtime scope와 admission, server-derived credential principal, credential `use` decision revision, verified model relation, provider-routing/pricing revision과 실제 request token·cost upper bound를 검증해 invocation/provider-attempt에 binding된 short-lived opaque capability identity/revision을 발급한다. Raw credential을 application/Memory에 반환하지 않으며 Workflow legacy/shared session과 분리한 전용 unit-of-work에서 provider 호출 전에 control row를 commit한다.
- `LLMCredentialConfigService`: canonical config JSON을 active key로 암호화하고 row metadata를 기준으로 encrypted/legacy read를 구분한다. active version은 공백이 아니고 `llm_credentials.encryption_key_version` 저장 길이인 최대 64자를 넘지 않아야 한다. 복호화, JSON/schema validation과 safe error normalization의 유일한 application 경계다.
- `LLMCredentialRotationService`: legacy 평문과 non-active key row를 stable order와 `FOR UPDATE SKIP LOCKED` 제한 batch로 active key에 재암호화하고 남은 대상 수만 반환한다. 운영 명령은 migration·readiness 완료 뒤 Gateway image에서 실행하며 plaintext, ciphertext 또는 key를 출력하지 않는다.
- `LLMCredentialKeyringReadiness`: Gateway, Workflow Worker와 Knowledge Worker 시작 시 keyring JSON, Fernet key와 active version을 검증한다. Celery Worker는 parent와 child process에서 모두 검증한다.
- Legacy `LLMNode` inline summary helper는 Conversation Memory summarizer component가 아니다. Capability-required LLM execution에서는 helper를 skip해 legacy `user_id`/owner credential provider call을 만들지 않으며, future summarizer만 별도 `memory_summary` capability를 consume할 수 있다.

## 상태

- credential: `valid`, `revoked/invalid`, `not_visible`, `use_denied`
- credential-model relation: `verified`, `not_verified`, `inactive`, `missing`

## 상호작용

- Organization manager가 credential을 등록하면 provider key 검증과 credential-model relation sync가 수행되고, UI는 raw key를 다시 표시하지 않는다.
- Credential revoke 성공 뒤 UI는 해당 credential을 실행 가능한 option에서 제거하고 상태를 다시 조회한다. Secret physical purge가 완료됐다는 문구는 표시하지 않는다.
- 일반 member가 직접 credential 등록 endpoint를 호출하면 UI 노출 여부와 무관하게 서버가 거부해야 한다.
- Standalone RAG answer는 answer-run 생성 전에 credential/model preflight를 호출한다.
- Auto collection mode는 explicit KB mode와 같은 generation credential/model preflight를 사용한다.
- Embedding credential readiness는 generation credential selection과 별개이며 `credential_id`에서 추론하면 안 된다.
- LlamaParse parsing은 provider 호출 전에 credential resolver를 통과해야 한다. 후보 없음/복수, revoke/invalid, 권한 상실, provider 불일치 또는 context 누락은 safe reason으로 종료하며 전역/환경 변수 fallback을 사용하지 않는다.
- Main generation과 Memory summary는 각각 purpose가 고정된 ProviderExecutionCapability를 사용한다. Summary는 `inherit_node`에서 별도 capability를 발급하고 organization default/owner credential을 추론하지 않는다.
- Capability identity/revision은 Memory lease, Budget reservation, provider attempt와 usage reconciliation에 전달한다. Credential revoke/permission revision 변경과 scope/admission/attempt/expiry mismatch는 새 claim·reservation·provider SDK 호출 전에 거부한다. Consumer는 credential principal이나 capability revision을 자체 합성하지 않는다.
- 신규 credential write는 active encryption version만 사용한다. Legacy read는 encryption metadata 두 값이 모두 null인 row에만 허용하며 metadata pair 불일치 또는 encrypted row decrypt 실패에는 평문 fallback을 하지 않는다.
- Rotation은 신·구키 동시 배포, active version 전환, batch 재암호화, 구키 참조 0 확인, 구키 제거 순서로 수행한다. Alembic migration은 key를 읽거나 row를 암호화하지 않는다.
- Capability-required LLM node path는 trusted Workflow Engine control과 explicit bounded cap을 가진 server runtime에서만 활성화한다. 이 path는 client override, `fallback_model_id`, automatic model routing, legacy `user_id`/owner credential selection을 사용하지 않는다. Policy가 고른 safe credential reference는 내부 client materialization에만 사용하고 component response, trace, audit에는 raw config를 전달하지 않는다.
- Capability runtime adapter는 prompt UTF-8 byte upper bound와 generic `max_tokens`를 admission 요청량으로 전달하고 canonical pricing으로 최대 비용을 검증한다. Credential materialization은 `LLMCredentialConfigService`를 통과한 뒤 전용 capability transaction을 commit하고, provider network I/O는 그 transaction 밖에서 수행한다. Legacy/shared Workflow session은 이 commit 경계에 전달하지 않는다.

## 접근성

- Credential/model option error는 text label을 가져야 하며 색상만으로 상태를 전달하지 않는다.
