# LLM Credentials Test Cases

Status: Draft
Verified Against: current implementation baseline plus Knowledge target model ADR-0014

## 단위 테스트

- Agent answer option builder는 credential value, encrypted config, API key/token, raw owner metadata, 불필요한 raw timestamp를 제외한다.
- Credential-model relation resolver는 inactive, unverified, wrong-provider, missing relation case를 거부한다.
- Generation credential preflight는 KB permission, collection route permission, source ACL authorization을 충족시키지 않는다.

## API 테스트

- `GET /api/v1/llm/agent-answer-options`는 active organization context에서 보이고 verified 상태인 model/credential pair만 반환한다.
- Knowledge target flow에서 `generation_model_id`/`credential_id`가 없거나 보이지 않으면 Knowledge API gate에 따라 answer-run 생성 전에 실패한다.
- Credential `use` denial은 sanitized error/audit metadata에서 KB permission denial 및 source ACL denial과 구분된다.

## E2E 테스트

- Knowledge Agent answer explicit KB mode와 auto collection mode는 preset/default credential ADR이 승인되기 전까지 모두 명시 generation model/credential selection을 요구한다.

## 권한 테스트

- Credential read/list 권한만 있고 credential `use` 권한이 없는 사용자는 해당 credential로 Agent answer generation을 실행할 수 없다.
- 사용 가능한 credential이라도 요청 model과 verified relation이 없으면 Agent answer generation을 실행할 수 없다.

## Edge Case

- 여러 credential 또는 model이 있어도 name/order fallback selection을 하지 않는다.
- Default credential/preset ambiguity는 향후 ADR이 selection priority를 정의하기 전까지 gated/unsupported condition으로 반환한다.
