# LLM Credentials Component Spec

Status: Draft
Verified Against: current implementation baseline plus Knowledge target model ADR-0014

## 화면

- Credential management/listing surface는 현재 사용자와 organization의 credential 상태를 표시한다.
- Agent answer option surface는 실행 가능한 safe model/credential pair만 표시한다.

## 컴포넌트

- `CredentialPermissionService`: credential visibility와 `use` permission을 평가한다.
- `CredentialModelRelationResolver`: credential-model pair가 active이고 verified 상태인지 확인한다.
- `AgentAnswerOptionProvider`: credential secret이나 전체 owner metadata를 반환하지 않고 standalone RAG answer flow용 safe option schema를 만든다.

## 상태

- credential: `valid`, `invalid`, `not_visible`, `use_denied`
- credential-model relation: `verified`, `not_verified`, `inactive`, `missing`

## 상호작용

- Standalone RAG answer는 answer-run 생성 전에 credential/model preflight를 호출한다.
- Auto collection mode는 explicit KB mode와 같은 generation credential/model preflight를 사용한다.
- Embedding credential readiness는 generation credential selection과 별개이며 `credential_id`에서 추론하면 안 된다.

## 접근성

- Credential/model option error는 text label을 가져야 하며 색상만으로 상태를 전달하지 않는다.
