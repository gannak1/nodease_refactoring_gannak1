# LLM Credentials Requirements

Status: Draft
Related Features: auth, organization, cost-optimizer, audit-tracing, knowledge, agent-builder

## Purpose

LLM credential은 provider API 호출 권한과 모델 연결을 관리한다. RAG Agent answer와 Knowledge retrieval에서는 generation credential, embedding credential readiness, verified credential-model relation이 서로 다른 역할을 가진다.

## User Stories

- 빌더로서, 내가 사용할 수 있는 모델/credential 조합만 Agent answer 옵션으로 보고 싶다.
- 운영자로서, generation credential과 embedding credential readiness 실패를 raw secret 없이 추적하고 싶다.
- 관리자로서, credential 사용 권한이 KB/collection 권한을 우회하지 않도록 보장하고 싶다.

## Functional Requirements

- Agent answer generation은 explicit KB mode와 auto collection mode 모두에서 명시된 `generation_model_id`와 `credential_id`의 visibility, use permission, verified relation을 서버에서 다시 검증한다.
- Knowledge retrieval embedding은 KB embedding model readiness와 usable embedding credential을 preflight로 확인한다. 이 credential은 generation credential과 같다고 가정하지 않는다.
- Credential option API는 실행 가능한 safe option schema만 반환하고, credential value, encrypted config, user quota, raw timestamps처럼 실행 선택에 불필요한 metadata를 기본 노출하지 않는다.

## Policies And Edge Cases

- Credential id는 secret이 아니라 식별자지만, credential value/API key/token/encrypted_config 원문은 응답, audit, trace, usage metadata에 저장하지 않는다.
- Default credential/preset 자동 선택은 별도 ADR/API 계약 전에는 허용하지 않는다.
- Credential 권한 부족은 KB permission/source ACL 실패와 독립적으로 기록한다. Credential이 있다고 해서 KB content permission이나 source ACL authorization을 대체하지 않는다.
- Usage summary는 model/provider/credential 식별자와 token/cost/latency 집계만 포함한다.
- 목표 auto collection answer 구현 전에는 generation model/credential visibility, credential `use`, verified credential-model relation의 API error shape, answer-run 생성 여부, audit behavior를 Knowledge API gate와 LLM credential feature 문서에 함께 고정한다.

## Open Questions

- Default credential 또는 preset이 도입될 경우 selection priority와 ambiguity error를 어디서 공식화할지.
- Embedding credential readiness 실패의 canonical audit target/reason code를 LLM credential 도메인과 Knowledge 도메인 중 어디서 소유할지.
