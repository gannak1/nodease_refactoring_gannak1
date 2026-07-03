# LLM Credentials Requirements

Status: Draft
Related Features: auth, organization, cost-optimizer, audit-tracing, knowledge, agent-builder

## Purpose

LLM credential은 organization scope의 provider API 호출 권한과 모델 연결을 관리한다. 개인 사용자 credential은 허용하지 않으며, credential 등록 주체는 active organization이다. RAG Agent answer와 Knowledge retrieval에서는 generation credential, embedding credential readiness, verified credential-model relation이 서로 다른 역할을 가진다.

## User Stories

- 빌더로서, 내가 사용할 수 있는 모델/credential 조합만 Agent answer 옵션으로 보고 싶다.
- 운영자로서, generation credential과 embedding credential readiness 실패를 raw secret 없이 추적하고 싶다.
- 관리자로서, credential 사용 권한이 KB/collection 권한을 우회하지 않도록 보장하고 싶다.
- 관리자로서, organization 공용 LLM credential만 등록하고 일반 member의 개인 credential 등록을 차단하고 싶다.

## Functional Requirements

- LLM credential 등록은 active organization scope 안에서만 가능해야 하며, 요청자는 해당 organization의 manager여야 한다. 일반 member는 credential `use` 또는 resource `manage` 권한을 갖고 있더라도 새 credential을 등록할 수 없다.
- 등록된 LLM credential은 organization-scoped resource로 취급한다. 저장 schema의 `user_id`는 등록 행위자 또는 호환 owner reference로만 해석하고, 개인 사용자 전용 credential scope로 해석하지 않는다.
- Agent answer generation은 explicit KB mode와 auto collection mode 모두에서 명시된 `generation_model_id`와 `credential_id`의 visibility, use permission, verified relation을 서버에서 다시 검증한다.
- Knowledge retrieval embedding은 KB embedding model readiness와 usable embedding credential을 preflight로 확인한다. 이 credential은 generation credential과 같다고 가정하지 않는다.
- Credential option API는 실행 가능한 safe option schema만 반환하고, credential value, encrypted config, user quota, raw timestamps처럼 실행 선택에 불필요한 metadata를 기본 노출하지 않는다.
- LLM node RAG option의 `llm_assisted` query rewrite는 별도 승인 전까지 비활성이다. 승인 시 rewrite LLM call도 execution subject, model/credential visibility, credential `use`, verified relation, timeout, token/cost budget, usage logging을 통과해야 한다.

## Policies And Edge Cases

- Credential id는 secret이 아니라 식별자지만, credential value/API key/token/encrypted_config 원문은 응답, audit, trace, usage metadata에 저장하지 않는다.
- Organization manager가 credential을 등록하더라도 raw API key는 organization member, credential `use` 권한자, workflow runtime 응답에 노출하지 않는다.
- Credential `manage`/`use` 권한은 기존 credential의 권한 관리와 실행 사용을 위한 권한이며, 새 credential 등록 권한을 의미하지 않는다.
- Default credential/preset 자동 선택은 별도 ADR/API 계약 전에는 허용하지 않는다.
- Credential 권한 부족은 KB permission/source ACL 실패와 독립적으로 기록한다. Credential이 있다고 해서 KB content permission이나 source ACL authorization을 대체하지 않는다.
- Usage summary는 model/provider/credential 식별자와 token/cost/latency 집계만 포함한다.
- Auto collection answer와 LLM node RAG option runtime은 generation model/credential visibility, credential `use`, verified credential-model relation 실패를 Knowledge permission/source ACL 실패와 구분해 반환하고 기록한다. Raw credential value 또는 provider raw response는 audit/trace/usage에 저장하지 않는다.

## Open Questions

- Default credential 또는 preset이 도입될 경우 selection priority와 ambiguity error를 어디서 공식화할지.
- Embedding credential readiness 실패의 canonical audit target/reason code를 LLM credential 도메인과 Knowledge 도메인 중 어디서 소유할지.
