# LLM Credentials Test Cases

Status: Draft
## 단위 테스트

- Credential registration gate는 organization manager만 통과시키고 일반 active member, builder/operator, credential `use` 권한자, credential `manage` 권한자를 새 credential 등록 권한자로 취급하지 않는다.
- Credential response builder는 저장 schema의 `user_id`를 개인 credential owner 표시로 노출하지 않거나, 노출이 필요한 기존 response에서는 등록 행위자 reference로만 취급한다.
- Agent answer option builder는 credential value, encrypted config, API key/token, raw owner metadata, 불필요한 raw timestamp를 제외한다.
- Credential-model relation resolver는 inactive, unverified, wrong-provider, missing relation case를 거부한다.
- LlamaParse credential resolver는 execution subject와 active organization이 모두 있을 때만 같은 organization의 valid `llamaparse` credential을 조회하고 `use` 권한을 다시 확인한다. 다른 user/organization credential, revoke/invalid, provider 불일치, 권한 상실, context 누락은 parser 호출 전에 차단한다.
- LlamaParse resolver는 허용 후보가 하나일 때만 parser 입력을 반환한다. 후보 없음 또는 둘 이상은 created_at/name/latest/default fallback 없이 fail-closed한다.
- Generation credential preflight는 KB permission, collection route permission, source ACL authorization을 충족시키지 않는다.
- ProviderExecutionCapability issuer는 opaque identity/revision, organization/workflow/deployment version, node invocation/execution admission/provider attempt, provider/model/credential, server-derived credential principal, credential permission decision, purpose, verified relation/egress·pricing revision, token·cost cap과 expiry를 모두 고정한다.
- Capability response/trace에는 raw credential, encrypted config와 capability token/scope 원문을 노출하지 않는다.
- Capability consumer가 client 값으로 credential principal 또는 permission revision을 덮어쓰려 하면 발급·사용을 거부한다.

## API 테스트

- `POST /api/v1/llm/credentials`는 active organization manager만 성공해야 하며, 일반 member는 `403 permission.denied`로 실패해야 한다.
- `POST /api/v1/llm/credentials`는 organization scope 밖 `organization_id`를 resource hiding 정책에 따라 거부해야 하며, 성공 응답과 audit metadata에 raw API key 또는 `encrypted_config` 원문을 포함하지 않아야 한다.
- `GET /api/v1/llm/agent-answer-options`는 active organization context에서 보이고 verified 상태인 model/credential pair만 반환한다.
- Knowledge target flow에서 `generation_model_id`/`credential_id`가 없거나 보이지 않으면 Knowledge API gate에 따라 answer-run 생성 전에 실패한다.
- Credential `use` denial은 sanitized error/audit metadata에서 KB permission denial 및 source ACL denial과 구분된다.

## E2E 테스트

- Standalone RAG answer explicit KB mode와 auto collection mode는 preset/default credential ADR이 승인되기 전까지 모두 명시 generation model/credential selection을 요구한다.
- Conversation Memory summary는 `inherit_node`만 허용하고 direct credential ID와 `organization_default`를 거부한다.
- Main capability를 summary purpose로 재사용하거나 summary capability를 main generation에 사용하면 provider 호출 전에 거부한다.

## 권한 테스트

- Credential 등록 권한은 organization manager 전용이며, credential `use`/`manage` 권한은 등록 권한으로 승격되지 않는다.
- Credential read/list 권한만 있고 credential `use` 권한이 없는 사용자는 해당 credential로 Agent answer generation을 실행할 수 없다.
- 사용 가능한 credential이라도 요청 model과 verified relation이 없으면 Agent answer generation을 실행할 수 없다.
- Credential revoke/permission decision revision 변경/model relation 또는 egress policy 변경 뒤 stale capability는 새 Memory context claim, budget reservation, provider attempt admission과 provider 호출에 사용할 수 없다.
- Credential principal, billing principal, execution subject와 audit actor가 서로 다른 fixture에서도 credential owner가 private KB subject/public actor로 승격되지 않는다.

## Edge Case

- 여러 credential 또는 model이 있어도 name/order fallback selection을 하지 않는다.
- Default credential/preset ambiguity는 향후 ADR이 selection priority를 정의하기 전까지 gated/unsupported condition으로 반환한다.
- LlamaParse processing failure response, processing metadata, audit/trace/log fixture에는 credential ID, config 원문, API key, decrypted value 또는 provider raw payload가 없어야 한다.
- Capability의 deployment version, node invocation, model, pricing revision, token/cost cap 또는 expiry 중 하나가 mismatch이면 raw secret/provider call 없이 fail-closed한다.
- Capability의 execution admission 또는 provider attempt binding을 다른 run/attempt에서 재사용하면 provider SDK 호출 전에 fail-closed한다.
- Provider call 시작 뒤 credential이 revoke된 ambiguous outcome은 자동 재호출하지 않되 이미 발생한 usage reconciliation은 같은 capability/attempt safe reference로 한 번만 처리한다.
