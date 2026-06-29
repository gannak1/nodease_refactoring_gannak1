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
- `X-Organization-Id`가 없으면 body `organization_id`를 사용한다.
- Header와 body 모두 없으면 `400 Bad Request`와 `detail: "organization_id_required"`로 실패한다.
- 개인 workspace도 default organization id를 `X-Organization-Id` 또는 body `organization_id`로 명시해야 한다.

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
- Model 목록 조회와 embedding model 목록 조회는 credential `use` 권한과 verified credential-model relation 기준으로 노출한다.
- Model 목록 응답은 사용 가능한 model만 반환하며, 반환된 model의 `can_use`는 호환성을 위해 `true`로 표시한다.
- Runtime LLM node 실행은 credential `use` 권한 기준으로 판정한다.
- 사용자는 `use` 권한이 없거나 model restriction policy로 deny된 model을 목록에서 볼 수 없다.

`can_use`는 DB column이나 `options` 값이 아니다. 응답 생성 시 현재 user, active organization, team membership, credential `use` permission, verified credential-model relation, model restriction policy를 기준으로 계산하며, 반환된 model에서는 `true`이다.

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
- Runtime에서 사용할 수 있는 credential-model relation이 없으면 `404`로 처리하고, credential은 있으나 `use` 권한 또는 model restriction policy 때문에 거부되면 `403`으로 처리한다.
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

## Deferred Decisions

다음 항목은 MBA-43 현재 구현 범위에서 제외하고 후속 티켓에서 정책을 확정한다.

- RAG / ingestion LLM 실행 시 organization context 기준
  - 요청 사용자 active organization 기준인지 결정이 필요하다.
  - Knowledge Base 소유 organization 기준인지 결정이 필요하다.
  - 현재 구현은 이 경로의 organization context 전달을 MBA-43 범위에 포함하지 않는다.

- Scheduler LLM 실행 시 organization context 기준
  - scheduler 실행은 사용자가 직접 header를 보내는 요청이 아니므로 `X-Organization-Id`를 기대할 수 없다.
  - `deployment`, `workflow`, `app` 중 어느 resource의 `organization_id`를 execution context로 사용할지 결정이 필요하다.
  - 현재 구현은 scheduler execution context에 organization id를 추가하지 않는다.

- LLM usage / audit / cost attribution 기준
  - credential 소유 organization 기준으로 남길지 결정이 필요하다.
  - 실행 resource 소유 organization 기준으로 남길지 결정이 필요하다.
  - 두 기준이 다를 때 audit metadata에 어떤 값을 함께 남길지 결정이 필요하다.

- 개인/default organization 실행 UX
  - 개인 workspace 실행도 default organization id를 명시적으로 전달한다는 정책은 유지한다.
  - UI/API에서 default organization id를 사용자에게 어떻게 인식시키고 전달할지 결정이 필요하다.

이 항목들은 구현 누락이 아니라 정책 미확정으로 인한 의도적 제외 범위다.

## Current Policy Follow-up Checklist

현재 정책이 수정될 예정이므로 아래 항목은 즉시 구현하지 않고 후속 티켓에서 다시 검토한다.
이 목록은 현재 문서 기준으로 구현한다면 처리해야 하는 작업을 기록하기 위한 것이다.

### Client organization context propagation

현재 문서 기준을 유지한다면 LLM credential/model API와 wizard API를 직접 호출하는 client 경로는 active organization scope를 전달해야 한다.
정책이 header 필수 방식에서 fallback 또는 다른 context 방식으로 바뀌면 이 목록을 먼저 갱신한 뒤 구현한다.

확인 대상:

- `apps/client/app/features/workflow/components/nodes/llm/components/LLMNodePanel.tsx`
  - `/api/v1/llm/my-models`
- `apps/client/app/features/workflow/components/editor/memory/MemoryModeControls.tsx`
  - `/api/v1/llm/credentials`
- `apps/client/app/features/workflow/components/modals/CodeWizardModal.tsx`
  - `/api/v1/code-wizard/check-credentials`
  - `/api/v1/code-wizard/generate`
- `apps/client/app/features/workflow/components/modals/PromptWizardModal.tsx`
  - `/api/v1/prompt-wizard/check-credentials`
  - `/api/v1/prompt-wizard/improve`
- `apps/client/app/features/workflow/components/modals/TemplateWizardModal.tsx`
  - `/api/v1/template-wizard/check-credentials`
  - `/api/v1/template-wizard/improve`
- `apps/client/app/features/workflow/components/nodes/template/components/TemplateNodePanel.tsx`
  - `/api/v1/template-wizard/check-credentials`
- `apps/client/app/features/knowledge/components/change-embedding-model-modal/index.tsx`
  - `/api/v1/llm/my-embedding-models`
- `apps/client/app/features/knowledge/components/create-knowledge-modal/index.tsx`
  - `/api/v1/llm/my-embedding-models`
- `apps/client/app/features/knowledge/components/knowledge-search-modal/index.tsx`
  - `/api/v1/llm/my-models`
- `apps/client/app/features/knowledge/hooks/useGenericCredential.ts`
  - `/api/v1/llm/credentials`

### Runtime organization context propagation

현재 문서 기준을 유지한다면 runtime LLM 호출은 공통 client 생성 함수에 organization context를 전달해야 한다.
다만 아래 항목은 정책 기준이 아직 흔들릴 수 있으므로 이번 범위에서 구현하지 않고 deferred decision으로 유지한다.

- RAG / ingestion LLM 호출
- scheduler LLM 호출
- usage / audit / cost attribution 기준
- 개인/default organization 실행 UX

### Permission and error consistency

현재 문서 기준을 유지한다면 다음 일관성 검사를 후속 구현에서 확인한다.

- `X-Organization-Id`와 body `organization_id`가 함께 있으면 mismatch를 `400`으로 처리한다.
- organization scope가 없으면 credential/model API 요청은 fail-closed 한다.
- credential이 존재하지 않으면 `404`, 존재하지만 scope 또는 권한이 맞지 않으면 `403`으로 처리한다.
- model 목록 응답은 사용 가능한 model만 반환하고 `can_use=true`를 명시한다.
- team/membership model restriction은 `teams.options.model_policy.unallowed_model_patterns`와 `team_memberships.options.model_policy.unallowed_model_patterns` 기준으로 계산한다.

## Existing Policy Relationship

이 문서는 기존 정책과 충돌하지 않도록 source-of-truth가 아닌 proposed 문서로 둔다.

주의할 기존 정책 지점:

- LLM credential/model API는 header 방식을 우선 사용하고 body `organization_id`를 보조 scope로 허용한다.
- 기존 LLM credential API 문서의 default organization fallback 설명은 MBA-43 구현 기준과 맞지 않으므로 제거한다.
- 이 제안은 LLM credential/model API에서 요청마다 explicit organization scope를 요구한다.

이번 구현 반영 사항:

- Header와 body `organization_id` mismatch는 `400 Bad Request`로 처리한다.
- Model 목록은 사용 가능한 model만 반환하고 `can_use=true`를 호환성 필드로 표시한다.
- Model restriction은 `teams.options`와 `team_memberships.options`의 `model_policy.unallowed_model_patterns`를 사용한다.

후속 결정 필요:

- 이 제안을 기존 ADR/API/RBAC source-of-truth 문서에 반영할지
- public app, webhook, scheduler runtime organization context를 후속 정책으로 언제 다룰지
