# LLM Credentials Test Cases

Status: Draft
## 단위 테스트

- Credential registration gate는 organization manager만 통과시키고 일반 active member, builder/operator, credential `use` 권한자, credential `manage` 권한자를 새 credential 등록 권한자로 취급하지 않는다.
- Credential response builder는 저장 schema의 `user_id`를 개인 credential owner 표시로 노출하지 않거나, 노출이 필요한 기존 response에서는 등록 행위자 reference로만 취급한다.
- Agent answer option builder는 credential value, encrypted config, API key/token, raw owner metadata, 불필요한 raw timestamp를 제외한다.
- Credential-model relation resolver는 inactive, unverified, wrong-provider, missing relation case를 거부한다.
- LlamaParse credential resolver는 execution subject와 active organization이 모두 있을 때만 같은 organization의 valid `llamaparse` credential을 조회하고 `use` 권한을 다시 확인한다. 다른 user/organization credential, revoke/invalid, provider 불일치, 권한 상실, context 누락은 parser 호출 전에 차단한다.
- LlamaParse resolver는 허용 후보가 하나일 때만 parser 입력을 반환한다. 후보 없음 또는 둘 이상은 created_at/name/latest/default fallback 없이 fail-closed한다.
- LlamaParse credential 후보가 존재하지만 모두 subject의 `use` 권한이 없으면 parser 호출 전에 `permission.denied` audit을 한 번 기록한다. 허용 candidate가 있는 요청에서 다른 후보의 거부 때문에 audit을 추가하지 않으며, audit에는 credential config/API key/provider raw payload를 남기지 않는다.
- Generation credential preflight는 KB permission, collection route permission, source ACL authorization을 충족시키지 않는다.
- ProviderExecutionCapability issuer는 opaque identity/revision, organization/workflow/deployment version, node invocation/execution admission/provider attempt, provider/model/credential, server-derived credential principal, credential permission decision, purpose, verified relation/provider-routing·pricing revision, token·cost cap과 expiry를 모두 고정한다.
- Capability response/trace에는 raw credential, encrypted config와 capability token/scope 원문을 노출하지 않는다.
- Capability consumer가 client 값으로 credential principal 또는 permission revision을 덮어쓰려 하면 발급·사용을 거부한다.
- Credential config service는 active key round trip, 구키 decrypt, canonical JSON과 required `apiKey` validation을 수행한다.
- Encryption metadata가 모두 null인 legacy row만 평문 read를 허용한다. Metadata 일부 누락, unsupported algorithm, unknown key version, 손상 ciphertext 또는 invalid config는 평문 fallback 없이 실패한다.
- Gateway와 Workflow Engine의 신규 credential 등록은 raw config와 다른 ciphertext, active key version과 algorithm을 저장한다.
- Gateway·Workflow Engine·RAG answer·embedding·LlamaParse의 decrypt 실패 테스트는 provider/client mock 호출이 0회임을 검증한다.
- Deployment policy resolver는 immutable deployment graph의 exact `llmNode.model_id`만 읽고 `credential_id`/`credentialId`, fallback model, auto-routing이 있는 capability-required node를 거부한다. `node_id`는 255자까지 허용하고 256자 이상은 policy/capability row를 쓰기 전에 거부한다.
- 같은 deployment version/node에 model UUID가 다른 두 active policy를 만들 수 없고, concurrent 최초 policy write는 canonical deployment와 active policy를 순서대로 lock한 뒤 authorization 근거를 잠가 하나의 active revision으로 수렴하거나 safe `409`로 종료한다.
- Deployment policy write는 manager actor를 server-derived credential principal으로만 사용하고, request의 credential config/principal override를 받지 않는다. Same organization, active credential/provider, verified single relation, credential `use`를 만족하지 않으면 policy row를 만들지 않는다.
- Capability-required LLM node는 trusted node invocation control과 explicit token/cost cap이 없으면 provider client를 만들지 않으며, legacy user/app owner/default/name/order/fallback selection을 호출하지 않는다.
- Capability-required LLM node는 messages와 tools·response schema 등 provider-visible parameter 구조 전체의 UTF-8 byte upper bound, `max_tokens`와 canonical pricing 최대 비용 중 하나라도 cap을 넘으면 provider client/SDK를 호출하지 않는다. Output limit이 없으면 server cap을 적용하고 직렬화 불가 parameter, provider-specific output-limit alias와 missing pricing은 fail-closed한다.
- Capability-required LLM node는 request parameters의 `model`을 항상 거부하고 `n`과 `best_of`는 boolean/string을 포함해 정확한 정수 `1`이 아니면 provider client/SDK 호출 전에 거부한다.
- Capability-required LLM node에 Knowledge Base 또는 Collection이 설정되면 별도 embedding capability가 준비되기 전까지 candidate resolution, legacy credential selection, embedding provider와 main provider 호출을 모두 0회로 유지하고 fail-closed한다.
- Policy write와 capability issue/admission은 lock 전에 같은 Session에 적재된 organization, user, membership, grant, model, provider, credential, relation, policy와 capability row를 강제 갱신한다. Lock 대기 중 권한 회수·비활성화가 commit되면 이전 identity-map 상태로 manager/use 권한을 허용하지 않는다.
- Worker process와 PostgreSQL clock이 어긋나도 capability `expires_at`은 DB wall clock + TTL로 발급되고, admission은 lock 이후 DB wall clock으로 만료를 재검증한다.
- 서로 다른 provider의 model row가 같은 API model identifier를 사용해도 capability admission이 고른 canonical model UUID가 비용 계산과 `llm_usage_logs.model_id`에 유지된다.
- Capability config는 encrypted/legacy row 모두 Shared `LLMCredentialConfigService`만 읽는다. Client는 credential config의 과거 base URL snapshot이 아니라 admission에서 잠근 provider catalog URL을 사용한다. Config/client materialization 성공 뒤 전용 capability transaction을 provider SDK 호출 전에 commit하며 Workflow legacy/shared session은 전달·commit하지 않고 provider 실패 뒤에도 발급 row가 rollback되지 않는다.
- User/anonymous-public/system execution subject는 각각 동일 user/public/system audit actor와만 결합되고 organization billing principal은 capability organization과 일치해야 한다.
- Capability-required LLM node가 legacy `memory_mode`를 만나면 inline summary helper를 skip하고 history query 또는 legacy `get_client_for_user` provider call을 만들지 않는다. Main capability를 summary purpose로 재사용하지 않으며, dedicated Conversation Memory summarizer가 없는 상태에서 summary provider 호출을 추가하지 않는다.

## API 테스트

- `POST /api/v1/llm/credentials`는 active organization manager만 성공해야 하며, 일반 member는 `403 permission.denied`로 실패해야 한다.
- `POST /api/v1/llm/credentials`는 organization scope 밖 `organization_id`를 resource hiding 정책에 따라 거부해야 하며, 성공 응답과 audit metadata에 raw API key 또는 `encrypted_config` 원문을 포함하지 않아야 한다.
- `GET /api/v1/llm/agent-answer-options`는 active organization context에서 보이고 verified 상태인 model/credential pair만 반환한다.
- `DELETE /api/v1/llm/credentials/{credential_id}` 성공 뒤 DB row는 남고 `is_valid=false`여야 한다. 기존 credential-model relation과 `llm_usage_logs`가 cascade delete되지 않으며, 이후 option/capability/provider 호출은 거부돼야 한다.
- DELETE의 legacy success message가 `deleted`를 사용하더라도 secret physical purge 완료로 해석하지 않는다. 응답, audit와 log에는 저장 secret 원문을 포함하지 않는다.
- Knowledge target flow에서 `generation_model_id`/`credential_id`가 없거나 보이지 않으면 Knowledge API gate에 따라 answer-run 생성 전에 실패한다.
- Credential `use` denial은 sanitized error/audit metadata에서 KB permission denial 및 source ACL denial과 구분된다.
- `PUT /api/v1/deployments/{deployment_id}/llm-credential-policies/{node_id}`는 active organization manager만 성공하고, response에 credential principal, encrypted config, API key/token, raw capability scope를 포함하지 않는다.
- Policy endpoint는 다른 organization deployment를 `404`로 숨기고 manager denial은 `403 permission.denied`, invalid graph/relation은 safe `422`, concurrent/ambiguous selection은 safe `409`로 반환한다.

## E2E 테스트

- Standalone RAG answer explicit KB mode와 auto collection mode는 preset/default credential ADR이 승인되기 전까지 모두 명시 generation model/credential selection을 요구한다.
- Conversation Memory summary는 `inherit_node`만 허용하고 direct credential ID와 `organization_default`를 거부한다.
- Main capability를 summary purpose로 재사용하거나 summary capability를 main generation에 사용하면 provider 호출 전에 거부한다.
- Capability-required deployment LLM node는 selected model과 다른 fallback/auto-routed model로 provider SDK를 호출하지 않으며, current policy revision 또는 permission/relation/pricing/egress fingerprint가 달라지면 provider call 전에 거부한다.

## 권한 테스트

- Credential 등록 권한은 organization manager 전용이며, credential `use`/`manage` 권한은 등록 권한으로 승격되지 않는다.
- Credential read/list 권한만 있고 credential `use` 권한이 없는 사용자는 해당 credential로 Agent answer generation을 실행할 수 없다.
- 사용 가능한 credential이라도 요청 model과 verified relation이 없으면 Agent answer generation을 실행할 수 없다.
- Credential revoke/permission decision revision 변경/model relation 또는 provider-routing fingerprint 변경 뒤 stale capability는 새 Memory context claim, budget reservation, provider attempt admission과 provider 호출에 사용할 수 없다. 실제 egress policy 변경 검증은 authoritative LLM outbound guard가 연결된 뒤 해당 revision으로 대체한다.
- Policy write와 final admission은 credential, verified relation, User/Organization 상태와 현재 `use` 판정의 organization membership/direct/team permission 근거 row를 잠근 상태에서 manager/permission 및 revision을 다시 검증한다. Concurrent revoke, 사용자·조직 비활성화 또는 권한 회수가 먼저 commit되면 provider materialization이 0회이고, admission이 먼저 commit되면 해당 provider attempt만 변경보다 앞선 유효 실행으로 직렬화된다.
- Credential principal, billing principal, execution subject와 audit actor가 서로 다른 fixture에서도 credential owner가 private KB subject/public actor로 승격되지 않는다.

## Edge Case

- 여러 credential 또는 model이 있어도 name/order fallback selection을 하지 않는다.
- Default credential/preset ambiguity는 향후 ADR이 selection priority를 정의하기 전까지 gated/unsupported condition으로 반환한다.
- LlamaParse processing failure response, processing metadata, audit/trace/log fixture에는 credential ID, config 원문, API key, decrypted value 또는 provider raw payload가 없어야 한다.
- Capability의 deployment version, node invocation, model, pricing revision, token/cost cap 또는 expiry 중 하나가 mismatch이면 raw secret/provider call 없이 fail-closed한다.
- Capability의 execution admission 또는 provider attempt binding을 다른 run/attempt에서 재사용하면 provider SDK 호출 전에 fail-closed한다.
- Provider call 시작 뒤 credential이 revoke된 ambiguous outcome은 자동 재호출하지 않되 이미 발생한 usage reconciliation은 같은 capability/attempt safe reference로 한 번만 처리한다.
- Plaintext backfill과 key rotation은 batch size/max-batches를 지키고 concurrent worker가 `SKIP LOCKED`로 같은 row를 중복 처리하지 않으며 재실행해도 active row를 다시 쓰지 않는다.
- Malformed row가 포함된 rotation batch는 전체 rollback되고 운영 출력에는 config, API key, ciphertext, key 또는 원본 예외가 없어야 한다.
- Gateway, Workflow Worker와 Knowledge Worker는 missing/invalid keyring, active version 누락 또는 64자를 초과하는 active version에서 시작을 거부한다. Knowledge Worker는 init container와 Celery parent/child process에 같은 keyring을 주입받고, Log System deployment에는 LLM keyring이 주입되지 않는다.
- Encrypted metadata row가 존재하면 schema downgrade는 metadata 유실 전에 fail-closed한다.
