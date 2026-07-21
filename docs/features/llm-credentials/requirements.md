# LLM Credentials Requirements

Status: Draft
Related Features: auth, organization, cost-optimizer, audit-tracing, knowledge, agent-builder, workflow, conversation-memory, budget-management

## Purpose

LLM credential은 organization scope의 provider API 호출 권한과 모델 연결을 관리한다. 개인 사용자 credential은 허용하지 않으며, credential 등록 주체는 active organization이다. RAG Agent answer와 Knowledge retrieval에서는 generation credential, embedding credential readiness, verified credential-model relation이 서로 다른 역할을 가진다.

## User Stories

- 빌더로서, 내가 사용할 수 있는 모델/credential 조합만 Agent answer 옵션으로 보고 싶다.
- 운영자로서, generation credential과 embedding credential readiness 실패를 raw secret 없이 추적하고 싶다.
- 관리자로서, credential 사용 권한이 KB/collection 권한을 우회하지 않도록 보장하고 싶다.
- 관리자로서, organization 공용 LLM credential만 등록하고 일반 member의 개인 credential 등록을 차단하고 싶다.
- 관리자로서, credential을 revoke하면 신규 호출은 즉시 차단하되 기존 비용·감사 이력의 의미는 보존하고 싶다.

## Functional Requirements

- LLM credential 등록은 active organization scope 안에서만 가능해야 하며, 요청자는 해당 organization의 manager여야 한다. 일반 member는 credential `use` 또는 resource `manage` 권한을 갖고 있더라도 새 credential을 등록할 수 없다.
- 등록된 LLM credential은 organization-scoped resource로 취급한다. 저장 schema의 `user_id`는 등록 행위자 또는 호환 owner reference로만 해석하고, 개인 사용자 전용 credential scope로 해석하지 않는다.
- Agent answer generation은 explicit KB mode와 auto collection mode 모두에서 명시된 `generation_model_id`와 `credential_id`의 visibility, use permission, verified relation을 서버에서 다시 검증한다.
- Knowledge retrieval embedding은 KB embedding model readiness와 usable embedding credential을 preflight로 확인한다. 이 credential은 generation credential과 같다고 가정하지 않는다.
- Credential option API는 실행 가능한 safe option schema만 반환하고, credential value, encrypted config, user quota, raw timestamps처럼 실행 선택에 불필요한 metadata를 기본 노출하지 않는다.
- 현재 credential DELETE는 `is_valid=false` revoke다. Row, credential-model relation, usage history와 secret material을 hard delete하지 않으며, revoke된 credential은 신규 option 선택, capability 발급과 provider 호출에 사용할 수 없어야 한다.
- LlamaParse document parsing은 explicit execution subject와 active organization이 있을 때만 실행한다. 해당 organization 범위에서 provider가 `llamaparse`이고 valid 상태이며 subject가 `use` 가능한 credential이 정확히 하나일 때만 parser에 전달한다. 후보 없음, 복수 후보, context 누락, revoke/invalid, provider 불일치와 권한 상실은 provider 호출 전에 fail-closed한다.
- LLM node RAG option의 `llm_assisted` query rewrite는 별도 승인 전까지 비활성이다. 승인 시 rewrite LLM call도 execution subject, model/credential visibility, credential `use`, verified relation, timeout, token/cost budget, usage logging을 통과해야 한다.
- LLM Credentials domain은 [ADR-0064](../../decisions/ADR-0064-provider-execution-capability-boundary.md)의 `ProviderExecutionCapability` schema, 발급, admission, revision과 revoke 검증의 authoritative owner다. Workflow/Conversation Memory provider call은 raw credential이나 client-selected owner가 아니라 server-issued capability를 사용해야 한다. Capability는 opaque identity/revision, organization/workflow/deployment ID/version, node/invocation/admission/provider-attempt binding, provider/model/credential safe reference, server-derived credential principal, credential permission decision revision, `main_generation|memory_summary` purpose, verified relation/provider-routing/pricing revision, token·cost cap과 expiry에 binding되어야 한다.
- Deployment credential policy는 graph 밖의 server-owned, revisioned row여야 하며 immutable deployment version의 LLM node마다 active policy를 최대 한 개만 허용해야 한다. Organization manager만 LLM node/model에 credential을 연결할 수 있으며, manager actor는 server-derived credential principal 후보로만 사용한다. Policy write와 provider admission은 같은 organization, deployment/version, exact graph model, active credential, provider match, verified relation, credential `use`를 재검증하고, 정책 없음·중복·직접 graph credential·fallback/auto-routing은 fail-closed한다.
- Main/summary provider adapter, Memory context lease, Budget reservation과 usage reconciliation은 같은 capability identity/revision과 자기 operation binding을 검증해야 한다. Capability는 short-lived single invocation scope이고 credential revoke, credential permission decision revision 변경, model relation/provider-routing fingerprint 변경 또는 expiry 뒤 새 lease claim, reservation, provider attempt admission이나 outbound call의 근거로 재사용할 수 없어야 한다. 현재 provider-routing fingerprint는 중앙 egress authorization을 뜻하지 않는다. 이미 시작된 provider attempt의 usage reconciliation은 stale capability로 새 호출을 허용하는 것과 분리해야 한다.
- Conversation Memory 초기 summary model policy는 `inherit_node`만 지원해야 한다. Node의 approved provider/model/credential scope에서 `purpose=memory_summary` capability를 별도로 발급하며, 조직 기본 credential/model preset이나 owner fallback을 추론해서는 안 된다.
- Credential principal은 capability 발급 시 서버가 canonical deployment/credential policy에서 파생하며 execution subject, billing principal과 audit actor와 구분해야 한다. Deployment creator는 명시 deployment policy가 canonical credential principal로 고정한 경우에만 capability 발급 근거가 될 수 있고 Knowledge subject나 public audit actor로 승격되지 않아야 한다. Memory, Workflow와 Budget consumer가 credential principal 또는 permission revision을 자체 합성해서는 안 된다. Capability 권한 거부 audit은 발급 입력의 typed user/public/system actor를 보존하고 runtime context에서 actor를 다시 추론하지 않아야 한다.
- LLM credential config는 `LLM_CREDENTIAL_ENCRYPTION_KEYS`의 active version을 사용하는 versioned encryption envelope로 저장해야 한다. active version은 공백이 아닌 최대 64자여야 하며 신규·갱신 row는 평문 JSON을 저장해서는 안 된다.
- Gateway, Workflow Engine, RAG answer, embedding과 parser는 Shared LLM credential config service를 통해서만 저장 config를 읽어야 한다. ORM row의 `encrypted_config`를 직접 parse하거나 decrypt 실패 뒤 평문 fallback을 수행해서는 안 된다.
- 기존 metadata 없는 평문 row는 제한된 전환 기간에만 dual-read할 수 있다. Encryption metadata가 일부만 있거나 algorithm/key version/ciphertext/config가 유효하지 않으면 외부 provider 호출 전에 fail-closed해야 한다.
- Gateway, Workflow Worker와 Knowledge Worker는 process startup에서 LLM keyring 형식과 active version을 검증해야 한다. Celery Worker는 parent와 child process 모두 task 소비 전에 검증한다. 세 process는 rotation 중 구키와 신키를 함께 받아야 하며 LLM credential을 사용하지 않는 Log System에는 keyring을 주입하지 않는다.
- 평문 backfill과 key rotation은 row lock과 제한 batch transaction을 사용하는 명시적 운영 경로로 수행해야 한다. 구키 참조 row가 0임을 확인하기 전에는 구키를 제거해서는 안 된다.

## Policies And Edge Cases

- Credential id는 secret이 아니라 식별자지만, credential value/API key/token/encrypted_config 원문은 응답, audit, trace, usage metadata에 저장하지 않는다.
- Organization manager가 credential을 등록하더라도 raw API key는 organization member, credential `use` 권한자, workflow runtime 응답에 노출하지 않는다.
- Credential `manage`/`use` 권한은 기존 credential의 권한 관리와 실행 사용을 위한 권한이며, 새 credential 등록 권한을 의미하지 않는다.
- Default credential/preset 자동 선택은 별도 ADR/API 계약 전에는 허용하지 않는다.
- `provider_execution_capability_required`는 client input/graph field가 아닌 server-owned target runtime activation flag다. 이 mode는 explicit execution subject 또는 explicit anonymous-public/system audience, trusted node invocation control, bounded token/cost limit을 요구하며 legacy `user_id`, app/deployment creator, owner, default/name/order fallback을 credential principal 또는 provider selection으로 승격하지 않는다. 기존 legacy runtime의 전체 activation/migration은 MBA-320 범위다.
- Capability admission은 발급 상한 자체가 아니라 provider-independent prompt UTF-8 byte upper bound, 실제 generic `max_tokens`와 canonical model pricing의 최대 비용을 비교해야 한다. `n`과 `best_of`는 정확한 정수 `1`만 허용한다. Output limit이 없으면 server cap을 적용하고 missing pricing, provider별 output-limit alias, 다중 생성 parameter 또는 상한 초과는 provider client 생성 전에 fail-closed한다. Capability usage projection은 canonical model row의 exact 가격만 사용하고, legacy usage projection은 exact row 가격이 없을 때만 shared catalog fallback을 명시적으로 사용할 수 있다.
- Policy write와 capability issue/admission의 row lock은 같은 Session identity map에 이미 적재된 ORM 객체도 `populate_existing`으로 갱신한 뒤 권한·상태·revision을 판정해야 한다. Capability 발급의 `created_at`, `updated_at`, `expires_at`과 admission 최종 만료 판정은 PostgreSQL wall clock을 사용해야 하며 worker process clock을 lifecycle 또는 TTL 권위로 사용하지 않는다.
- Capability 발급과 최종 admission은 Workflow legacy/shared session과 분리한 전용 transaction에서 provider client 반환 전에 commit해야 하며 provider 호출 실패가 발급 사실을 rollback해서는 안 된다. Network I/O 중 control transaction session을 유지하지 않고 장기 provider-start/outcome/usage reconciliation은 MBA-287 원장이 소유한다.
- 현재 legacy `LLMNode._build_memory_summary`는 Conversation Session/Access Grant/lease와 source authorization 재검증을 갖춘 Memory adapter가 아니다. 따라서 capability-required path에서는 이 inline helper를 skip하며 `user_id`/owner credential로 summary provider를 호출하지 않는다. `purpose=memory_summary` capability를 실제로 consume하는 dedicated Conversation Memory adapter는 해당 lifecycle·budget·usage contract가 준비된 후에만 추가한다.
- 현재 LLM node RAG query embedding은 별도 provider capability 없이 legacy user credential resolver를 사용한다. 따라서 capability-required path는 embedding 전용 capability와 principal·usage 계약이 준비되기 전까지 Knowledge candidate resolution과 embedding provider 호출 전에 fail-closed한다. Main generation capability를 embedding 권한으로 재사용하거나 owner/user fallback으로 RAG를 실행하지 않는다.
- LlamaParse parsing은 전역 최신 credential, 다른 organization credential, `LLAMA_CLOUD_API_KEY` 같은 환경 변수 fallback으로 권한 검증을 우회하지 않는다. system-owned parsing이 필요하면 system principal, organization binding과 lifecycle을 별도 계약으로 승인해야 한다.
- `organization_default` summary policy는 위 preset ADR/API 계약과 구현 전까지 unsupported다. Client가 해당 key 또는 direct credential ID를 Memory node config로 보내면 fail-closed한다.
- Credential 권한 부족은 KB permission/source ACL 실패와 독립적으로 기록한다. Credential이 있다고 해서 KB content permission이나 source ACL authorization을 대체하지 않는다.
- Usage summary는 model/provider/credential 식별자와 token/cost/latency 집계만 포함한다.
- LLM usage는 비용·감사의 historical fact로 취급하고 credential/model lifecycle에 cascade delete하지 않는다. Retention이 끝난 usage의 purge는 organization policy와 legal hold를 적용하며, credential secret purge와 같은 작업으로 묶지 않는다.
- Deployment credential policy와 아직 usage ledger에 연결되지 않은 provider capability는 실행 제어 row다. Workflow/deployment 삭제 시 policy와 capability는 함께 cascade delete해 기존 deployment delete contract를 막지 않는다. 장기 비용·감사·reconciliation 사실은 이 row에 의존하지 않으며 MBA-287의 durable usage ledger가 safe snapshot과 retention을 소유한다.
- Current revoke 뒤 secret material이 저장 row에 남는 것은 목표 상태가 아니다. Secret physical purge 또는 crypto-shred는 usage/audit가 provider/model/pricing/billing 의미를 유지할 tombstone 또는 safe snapshot 계약과 함께 별도 lifecycle로 도입한다.
- Auto collection answer와 LLM node RAG option runtime은 generation model/credential visibility, credential `use`, verified credential-model relation 실패를 Knowledge permission/source ACL 실패와 구분해 반환하고 기록한다. Raw credential value 또는 provider raw response는 audit/trace/usage에 저장하지 않는다.
- Credential 저장·복호화·등록 검증·rotation 중 config 평문, ciphertext, encryption key, provider 검증 raw payload와 원본 decrypt 예외는 API, audit, trace, usage, log, fixture, migration 또는 rotation 출력에 저장하지 않는다. 운영 결과는 safe 상태와 count만 제공한다.

## Open Questions

- Default credential 또는 preset이 도입될 경우 selection priority와 ambiguity error를 어디서 공식화할지.
- Embedding credential readiness 실패의 canonical audit target/reason code를 LLM credential 도메인과 Knowledge 도메인 중 어디서 소유할지.
- Credential revoke 뒤 secret material을 언제 crypto-shred 또는 physical purge할지와 legal hold 예외.
- Credential/model 삭제 뒤에도 usage fact의 비용 의미를 재구성하기 위한 최소 safe snapshot과 retention 기간.
