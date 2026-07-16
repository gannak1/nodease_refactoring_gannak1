# LLM Credentials Component Spec

Status: Draft
## 화면

- Credential management/listing surface는 active organization의 credential 상태를 표시한다. 개인 사용자 credential 등록 화면을 제공하지 않는다.
- Credential 등록 UI는 organization manager에게만 노출한다. 일반 member, builder/operator, credential `use` 권한자에게는 등록 control을 숨기고 서버 403을 최종 경계로 둔다.
- Agent answer option surface는 실행 가능한 safe model/credential pair만 표시한다.

## 컴포넌트

- `CredentialRegistrationGate`: active organization manager 여부를 확인하고 credential 등록 control 노출을 결정한다.
- `CredentialPermissionService`: credential visibility와 `use` permission을 평가한다.
- `CredentialModelRelationResolver`: credential-model pair가 active이고 verified 상태인지 확인한다.
- `LlamaParseCredentialResolver`: document parsing 직전에 execution subject, active organization, `llamaparse` provider 호환성, valid 상태와 credential `use` 권한을 확인하고 단일 허용 credential의 parser 입력만 반환한다. FileProcessor는 ORM row나 저장 config를 직접 해석하지 않는다.
- `AgentAnswerOptionProvider`: credential secret이나 전체 owner metadata를 반환하지 않고 standalone RAG answer flow용 safe option schema를 만든다.
- `ProviderExecutionCapabilityIssuer`: 이 capability 계약의 authoritative owner다. Canonical runtime scope와 admission, server-derived credential principal, credential `use` decision revision, verified model relation, egress/pricing policy와 token·cost cap을 검증해 invocation/provider-attempt에 binding된 short-lived opaque capability identity/revision을 발급한다. Raw credential을 application/Memory에 반환하지 않는다.

## 상태

- credential: `valid`, `invalid`, `not_visible`, `use_denied`
- credential-model relation: `verified`, `not_verified`, `inactive`, `missing`

## 상호작용

- Organization manager가 credential을 등록하면 provider key 검증과 credential-model relation sync가 수행되고, UI는 raw key를 다시 표시하지 않는다.
- 일반 member가 직접 credential 등록 endpoint를 호출하면 UI 노출 여부와 무관하게 서버가 거부해야 한다.
- Standalone RAG answer는 answer-run 생성 전에 credential/model preflight를 호출한다.
- Auto collection mode는 explicit KB mode와 같은 generation credential/model preflight를 사용한다.
- Embedding credential readiness는 generation credential selection과 별개이며 `credential_id`에서 추론하면 안 된다.
- LlamaParse parsing은 provider 호출 전에 credential resolver를 통과해야 한다. 후보 없음/복수, revoke/invalid, 권한 상실, provider 불일치 또는 context 누락은 safe reason으로 종료하며 전역/환경 변수 fallback을 사용하지 않는다.
- Main generation과 Memory summary는 각각 purpose가 고정된 ProviderExecutionCapability를 사용한다. Summary는 `inherit_node`에서 별도 capability를 발급하고 organization default/owner credential을 추론하지 않는다.
- Capability identity/revision은 Memory lease, Budget reservation, provider attempt와 usage reconciliation에 전달한다. Credential revoke/permission revision 변경과 scope/admission/attempt/expiry mismatch는 새 claim·reservation·provider SDK 호출 전에 거부한다. Consumer는 credential principal이나 capability revision을 자체 합성하지 않는다.

## 접근성

- Credential/model option error는 text label을 가져야 하며 색상만으로 상태를 전달하지 않는다.
