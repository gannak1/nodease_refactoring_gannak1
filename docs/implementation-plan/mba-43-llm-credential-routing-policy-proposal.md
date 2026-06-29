# MBA-43 LLM Credential Routing Policy Proposal

Status: Proposed
Authority: Implementation Plan
Source of Truth: No
Created At: 2026-06-29
Implementation Note: MBA-43 gateway/workflow runtime code follows this proposal unless a source-of-truth policy later overrides it.

이 문서는 MBA-43 구현 전 합의한 정책 초안이다. 기존 ADR, API, RBAC, data-model 문서를 대체하거나 수정하지 않는다. 구현 착수 전 기존 source-of-truth 정책 문서에 반영할지 별도 승인해야 한다.

## Scope

대상:

- Organization-level LLM credential routing
- LLM credential/model HTTP API의 active organization 처리
- Runtime LLM credential `use` 권한 적용
- Team/membership 기반 model restriction

이번 범위 제외:

- public app runtime LLM 권한 정책
- webhook runtime LLM 권한 정책
- scheduler runtime organization context 정책
- model 전용 permission table
- provider별 고급 routing, retry, fallback, cache
- API key별 cost limit

## Active Organization

- LLM credential/model HTTP API는 `X-Organization-Id` header를 우선 사용한다.
- `LLMCredentialCreate.organization_id`가 함께 들어온 경우 header organization과 일치해야 한다.
- Header organization과 body `organization_id`가 다르면 `400 Bad Request`로 실패한다.
- `X-Organization-Id`가 없으면 기존 active organization fallback 정책을 따른다.
- Credential 생성 scope 결정 순서는 `X-Organization-Id`, body `organization_id`, 기존 primary/default organization fallback 순서다.
- 개인 workspace는 가능하면 default organization id를 `X-Organization-Id`로 명시한다. 단, header가 없는 legacy/과도기 경로는 기존 fallback 정책을 따른다.

## Permission Tables

LLM credential 권한은 기존 table을 사용한다.

- `team_llm_permissions`
- `user_llm_permissions`

의미:

- `team_llm_permissions`: team이 특정 `llm_credentials`를 어떤 권한으로 쓸 수 있는지 나타낸다.
- `user_llm_permissions`: 특정 user에게 `llm_credentials` 권한을 additive allow로 직접 부여한다.

`user_llm_permissions`는 team 권한을 낮추거나 deny하지 않는다.

## Read vs Use

- Credential 목록 조회는 credential `read` 권한 기준으로 노출한다.
- Model 목록 조회와 embedding model 목록 조회도 credential `read` 권한과 verified credential-model relation 기준으로 노출한다.
- Model 목록 응답에는 저장값이 아닌 계산값 `can_use`를 포함한다.
- Runtime LLM node 실행은 credential `use` 권한 기준으로 판정한다.
- 사용자는 model 목록을 볼 수 있어도 `use` 권한이 없으면 실행할 수 없다.

`can_use`는 DB column이나 `options` 값이 아니다. 응답 생성 시 현재 user, active organization, team membership, credential permission, verified credential-model relation, model restriction policy를 기준으로 계산한다.

## Runtime 적용 범위

MBA-43에서 runtime `use` 권한 검사를 적용할 경로:

- manual/test workflow 실행
- private/auth required app 실행

정책 미확정으로 이번 범위에서 제외할 경로:

- public app 실행
- webhook 실행
- scheduler 실행

Private/auth required app 실행은 접속한 로그인 user를 실행 주체로 보고, 해당 user가 app organization scope 안에서 가진 team membership 및 user direct permission을 기준으로 LLM credential `use` 권한을 검사한다.

## Error Policy

- 권한 부족은 숨기지 않고 `403 Forbidden` 또는 `permission.denied`로 처리한다.
- Credential이 실제로 존재하지 않으면 `404 Not Found` 또는 `resource.not_found`로 처리한다.
- Credential은 존재하지만 organization scope 또는 permission이 맞지 않으면 `403`으로 처리한다.
- Runtime 실패 응답은 `403 permission.denied`로 단순화한다.
- Runtime 실패 상세 사유는 내부 log 또는 audit metadata에 남긴다.
- Secret, token, raw API key는 error message, log, audit metadata에 원문으로 남기지 않는다.

## Model Restriction Policy

Model restriction은 credential permission row가 아니라 team/membership options에 둔다.

저장 위치:

- `teams.options.model_policy.unallowed_model_patterns`
- `team_memberships.options.model_policy.unallowed_model_patterns`

의미:

- `teams.options`: team 전체 model 제한
- `team_memberships.options`: 해당 team 안의 특정 user membership 추가 제한

Pattern 문법:

- wildcard/glob 방식만 사용한다.
- `*`만 wildcard로 허용한다.
- `*`가 없으면 exact match처럼 동작한다.
- regex는 허용하지 않는다.
- 비교 전 pattern과 provider model id를 lowercase로 정규화한다.

우선순위:

- deny 우선이다.
- team policy deny는 membership policy보다 우선한다.
- membership policy는 추가 제한만 가능하다.
- membership policy로 team deny를 해제할 수 없다.
- 여러 team에 속한 user가 하나라도 model deny에 걸리면 runtime 사용을 거부한다.

예시:

- `gpt-5`: 정확히 `gpt-5`만 차단
- `gpt-5*`: `gpt-5`, `gpt-5-mini`, `gpt-5.1` 등 차단
- `*-preview`: preview 계열 차단
- `*vision*`: model id에 `vision`이 포함된 model 차단

## Existing Policy Relationship

이 문서는 기존 정책과 충돌하지 않도록 source-of-truth가 아닌 proposed 문서로 둔다.

주의할 기존 정책 지점:

- 기존 active organization 정책은 header 방식을 승인하면서도 legacy/default organization fallback을 일부 허용한다.
- 기존 LLM credential API 문서는 body `organization_id` 또는 default organization fallback 설명을 포함할 수 있다.
- 이 제안은 기존 fallback 정책을 제거하지 않고, `X-Organization-Id`가 있는 요청에서 header를 우선 scope로 사용하도록 정렬한다.

이번 구현 반영 사항:

- Header와 body `organization_id` mismatch는 `400 Bad Request`로 처리한다.
- Model 목록 응답의 `can_use`는 DB/options에 저장하지 않고 응답 생성 시 계산한다.
- Model restriction은 `teams.options`와 `team_memberships.options`의 `model_policy.unallowed_model_patterns`를 사용한다.

후속 결정 필요:

- 이 제안을 기존 ADR/API/RBAC source-of-truth 문서에 반영할지
- public app, webhook, scheduler runtime organization context를 후속 정책으로 언제 다룰지
