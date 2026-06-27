# 구현 결정 로그

Status: Draft
Authority: Implementation Plan
Source of Truth: No
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs:

## 목적

이 문서는 구현 중 발생하는 작은 결정, 기본값, 임시 호환 처리, 테스트/rollout 판단을 기록한다.

이 문서는 ADR이 아니다. Requirements, Architecture, Data Model, API, Decision 문서와 충돌하면 상위 source-of-truth 문서를 따른다.

## ADR과의 구분

| 구분 | 위치 | 예시 |
| --- | --- | --- |
| 큰 정책/아키텍처 결정 | `decisions/` ADR | active organization 방식, audit table 재사용, RBAC schema 확장 |
| 작은 구현 결정 | 이 문서 | RAG chunk 기본값, 임시 compatibility mapping, 테스트 fixture 선택 |
| 확정된 현재 기준 | 각 권위 문서 | API request/response, table/column, 권한 matrix |

## 기록할 것

- 구현 중 정한 기본값
- 한 모듈 안에서의 tradeoff
- 임시 compatibility 처리
- 테스트, rollout, fallback 결정
- 나중에 ADR로 승격할 수 있는 후보 결정

## 기록하지 않을 것

- secret, token, credential, `.env` 값
- 단순 코드 스타일 선택
- 이미 상위 문서에 명확히 정의된 기준
- 여러 권위 문서를 바꾸는 큰 결정

## ADR 승격 기준

아래 중 하나라도 해당하면 이 문서에만 두지 말고 ADR 후보로 올린다.

- 여러 권위 문서나 여러 모듈에 영향을 준다.
- DB schema, RBAC, audit, data retention, organization boundary, 보안 경계에 영향을 준다.
- 되돌리기 어렵거나 migration이 필요하다.
- 제품 요구사항/API 계약/운영 정책이 바뀐다.
- 선택지를 비교한 근거를 나중에 방어해야 한다.

## 기본 양식

```md
## YYYY-MM-DD

### 결정 제목

- 상태: Active | Superseded | Promoted to ADR
- 맥락:
- 결정:
- 근거:
- 범위:
- 영향 파일:
- 관련 문서:
- 후속 검토:
- ADR 승격 여부: Yes | No
```

## 2026-06-27

### 구현 계획 디렉터리명

- 상태: Active
- 맥락: `implementation/` 이름은 코드 구현 전반이나 실제 구현 파일을 담는 디렉터리로 오해될 수 있다.
- 결정: 구현 순서, 이슈 분해, 검증 계획 문서는 `implementation-plan/` 디렉터리 아래에 둔다.
- 근거: 현재 문서 체계에서 해당 영역은 실행 코드가 아니라 source-of-truth 문서를 작업 단위로 분해한 계획이므로 `implementation-plan`이 더 명확하다.
- 범위: 활성 문서 루트의 구현 계획 문서 링크와 권위 표기.
- 영향 파일: `README.md`, `foundation/document-authority.md`, `requirements/README.md`, `decisions/ADR-*.md`, `implementation-plan/README.md`.
- 관련 문서: [implementation-plan/README.md](README.md)
- 후속 검토: 실제 개발 이슈 관리 도구로 분리되면 이 디렉터리의 역할을 다시 검토한다.
- ADR 승격 여부: No. 문서 분류와 링크 명확화에 한정되며 아키텍처나 제품 정책을 바꾸지 않는다.

### RAG chunk 기본값

- 상태: Active
- 맥락: RAG document preview와 ingestion의 초기 chunk 기본값이 필요하다.
- 결정: `chunk_size=500`, `chunk_overlap=50`을 기본값으로 사용한다.
- 근거: 초기 preview 속도와 검색 품질의 균형을 위한 구현 기본값이다.
- 범위: RAG preview/ingestion 기본 request 값.
- 영향 파일: `api/knowledge-rag.md`, RAG ingestion 관련 구현 파일.
- 관련 문서: [api/knowledge-rag.md](../api/knowledge-rag.md)
- 후속 검토: 실제 검색 품질과 비용을 평가한 뒤 조정한다.
- ADR 승격 여부: No. 단, 모든 tenant에 강제되는 제품 정책이 되거나 재색인 migration에 영향을 주면 ADR 후보로 승격한다.

### MBA-44 / Issue #59 LLM trace endpoint 형태

- 상태: Active
- 맥락: MVP1 LLM trace는 run detail 응답 확장 또는 별도 endpoint 방식 중 하나로 구현할 수 있다.
- 결정: `GET /api/v1/workflows/{workflow_id}/runs/{run_id}/llm-traces`를 필수 endpoint로 구현한다. `node_id`, `limit`, `offset` query를 지원하고, 기본 정렬은 `created_at ASC`, `id ASC`로 둔다. `limit` 기본값은 `100`, 최대값은 `500`이다.
- 근거: LLM trace는 응답 크기와 필터링 요구가 커질 수 있고, 향후 raw/redacted payload 정책과 분리해야 하므로 run detail 전체 응답에 기본 포함하지 않는 편이 안전하다.
- 범위: GitHub Issue #59 / MBA-44 LLM trace 조회 API.
- 영향 파일: `apps/gateway/api/v1/endpoints/workflow.py`, `apps/gateway/services/llm_service.py`, `apps/shared/schemas/llm.py`, `apps/gateway/tests/api/test_workflow_llm_traces_api.py`.
- 관련 문서: [api/tracing-audit.md](../api/tracing-audit.md), [requirements/mvp-1-foundation-llmops.md](../requirements/mvp-1-foundation-llmops.md)
- 후속 검토: FE가 run detail summary를 별도로 요구하면 기존 응답 호환성을 확인한 뒤 summary field만 추가한다.
- ADR 승격 여부: No. Issue #59 endpoint 구현 기본값에 한정한다.

### MBA-44 / Issue #59 workflow read guard 과도기 호환

- 상태: Active
- 맥락: workflow run list/detail/stats와 LLM trace 조회가 workflow 존재 여부만 확인하면 다른 user가 run/trace 정보를 볼 수 있다. PR #65에서 `apps.gateway.auth.permissions.ensure_workflow_permission`과 `apps.shared.services.permissions` 기반 공통 resource permission helper가 도입되었다.
- 결정: Issue #59 범위에서는 별도 workflow read guard를 유지하지 않고 PR #65 공통 `ensure_workflow_permission(db, current_user, workflow_id, "read")`를 workflow run list/detail/stats와 LLM trace 조회 endpoint에 적용한다. read 허용 여부, active organization 확인, team/direct permission 해석, manager 판정은 `apps.shared.services.permissions`의 공통 evaluator를 따른다. workflow가 없거나 workflow id가 유효하지 않으면 404, 권한이 없으면 fail-closed 403으로 처리한다.
- 근거: 전용 guard를 유지하면 PR #65의 direct user permission, auth_state normalization, active organization 기준과 어긋날 수 있다. Issue #59의 목적은 조회 경계를 닫는 것이므로 새 공통 RBAC 경계를 재사용하는 편이 중복 정책과 drift를 줄인다.
- 범위: workflow run list/detail/stats, LLM trace 조회 권한.
- 영향 파일: `apps/gateway/auth/permissions.py`, `apps/shared/services/permissions.py`, `apps/gateway/api/v1/endpoints/workflow.py`, `apps/gateway/tests/api/test_workflow_llm_traces_api.py`, `apps/gateway/tests/api/test_workflow_stats_permissions.py`, `apps/gateway/tests/api/test_permission_helpers.py`.
- 관련 문서: [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md), [decisions/ADR-202606271559-active-organization.md](../decisions/ADR-202606271559-active-organization.md), [decisions/ADR-202606271559-auth-state-standard.md](../decisions/ADR-202606271559-auth-state-standard.md)
- 후속 검토: active organization과 `auth_state` 표준화 ADR이 변경되면 공통 evaluator 기준만 조정하고 endpoint별 별도 guard를 만들지 않는다.
- ADR 승격 여부: No. 단, 공통 evaluator의 compatibility mapping을 제품 정책으로 고정하려면 ADR 검토가 필요하다.

### MBA-44 / Issue #59 permission denied audit 기록 지점

- 상태: Active
- 맥락: 권한 실패를 전역 HTTPException handler에서만 기록하면 resource/action/effective permission context가 부족하고, guard와 handler가 동시에 기록하면 중복 audit이 생긴다.
- 결정: 공통 permission helper가 canonical `permission.denied` audit을 1회 기록하고, helper가 발생시킨 403 `HTTPException`에는 `audit_recorded=True`를 표시한다. 전역 401/403 handler는 이 표시가 있는 예외에 대해 추가 `auth.permission_denied` audit을 남기지 않는다. helper를 거치지 않은 인증/권한 실패는 기존처럼 전역 handler가 `auth.permission_denied`를 기록한다. `permission.denied` metadata에는 `policy_result='deny'`, `resource_type`, `resource_id`, `required_permission`을 포함해 사후 분석에 필요한 결정 context를 남긴다.
- 근거: permission helper는 resource type, target id, required permission, effective auth state를 가장 정확히 알고 있다. 전역 handler는 generic auth failure fallback으로 유지하되, 이미 resource-level audit이 기록된 실패는 중복 기록하지 않는다.
- 범위: Issue #59 workflow read 조회 차단과 PR #65 공통 permission helper 기반 권한 차단.
- 영향 파일: `apps/gateway/auth/permissions.py`, `apps/gateway/main.py`, `apps/shared/audit/actions.py`, `apps/gateway/tests/api/test_workflow_llm_traces_api.py`, `apps/gateway/tests/api/test_permission_helpers.py`.
- 관련 문서: [data-model/rbac-permission-policy.md](../data-model/rbac-permission-policy.md), [decisions/ADR-202606271559-audit-log-rag-trace-storage.md](../decisions/ADR-202606271559-audit-log-rag-trace-storage.md)
- 후속 검토: 다른 resource guard가 추가되면 전용 exception class를 늘리지 않고 공통 permission helper 또는 shared helper에서 `audit_recorded` 표시를 재사용한다.
- ADR 승격 여부: No. 기존 audit 저장 정책을 바꾸지 않고 구현 지점만 정한다.

### MBA-44 / Issue #59 LLM trace 민감 정보 제외와 legacy usage 호환

- 상태: Active
- 맥락: LLM trace는 node별 model/token/cost/latency/status를 보여야 하지만 credential value, raw prompt, raw completion은 기본 조회 응답에 포함하면 안 된다. 또한 기존 `LLMUsageLog.log_usage` 경로는 `workflow_id`를 채우지 않을 수 있다.
- 결정: LLM trace 응답은 whitelist schema만 사용한다. 허용 필드는 `id`, `workflow_id`, `workflow_run_id`, `node_id`, `model_id`, `model_name`, `provider`, `credential_id`, `prompt_tokens`, `completion_tokens`, `total_tokens`, `total_cost`, `latency_ms`, `status`, `created_at`이다. `credential_id`는 어떤 등록 credential로 호출됐는지 추적하기 위한 correlation identifier로만 허용한다. API key, credential config, raw prompt, raw completion, raw request/response body, Authorization/Cookie header는 반환하지 않는다. 새 usage log는 run context에서 `workflow_id`와 가능한 `organization_id`를 채운다. 명시된 `workflow_id` 또는 `workflow_run_id`가 invalid, missing, mismatch이면 credential 조회 전에 저장을 중단한다. 단, 레거시 workflow row의 `organization_id`가 비어 있거나 invalid인 경우에는 `organization_id=NULL`로 usage 저장을 허용한다. 조회 시에는 `run_id`가 path의 `workflow_id`에 속하는지 먼저 확인한 뒤 `llm_usage_logs.workflow_id`가 일치하거나 legacy `NULL`인 row만 반환한다.
- 근거: 기본 LLM trace endpoint는 observability endpoint이지 raw payload access endpoint가 아니다. 기존 usage row의 `workflow_id` 누락 때문에 실제 run trace가 비어 보이는 문제를 막되, `workflow_run_id` 검증으로 다른 workflow usage 혼입을 차단한다. 명시 context가 잘못된 row는 저장하지 않는 편이 cross-workflow trace 혼입보다 안전하다. 반면 workflow의 organization은 파생 scope이므로 레거시 데이터 결손 때문에 trace 저장 자체를 중단하지 않는다. `credential_id`는 secret이나 credential 설정값이 아니며, 이 id만으로 credential 원문을 조회할 수 없어야 한다.
- 범위: Issue #59 LLM trace 조회와 신규 LLM usage 기록 context 보강.
- 영향 파일: `apps/gateway/services/llm_service.py`, `apps/workflow_engine/services/llm_service.py`, `apps/shared/services/llm_usage_context.py`, `apps/shared/schemas/llm.py`, `apps/gateway/tests/api/test_workflow_llm_traces_api.py`, `apps/gateway/tests/services/test_llm_usage_log_context.py`.
- 관련 문서: [api/tracing-audit.md](../api/tracing-audit.md), [data-model/physical-data-model.md](../data-model/physical-data-model.md)
- 후속 검토: raw payload 조회가 필요하면 `raw_auditor` 또는 `manager` 권한과 `trace_visibility_policies`, `trace_payload_access_events`를 요구하는 별도 endpoint로 설계한다.
- ADR 승격 여부: No. 기존 raw trace 정책을 바꾸지 않고 기본 응답 whitelist와 legacy compatibility만 정한다.

### MBA-44 / Issue #59 LLM usage latency column 정합성

- 상태: Active
- 맥락: LLM usage latency는 API와 ORM에서 `latency_ms`로 노출되지만, 기존 초기 migration과 일부 문서에 물리 column명 오타가 남아 있었다.
- 결정: 새 schema, ORM, API, 문서는 모두 `latency_ms`를 사용한다. 기존 환경에 잘못 생성된 legacy latency column은 전용 Alembic migration에서 `latency_ms`로 rename하고, 이미 정정된 환경에서는 no-op으로 둔다.
- 근거: alias를 장기간 유지하면 raw SQL, ORM, 문서 간 source of truth가 갈라진다. 새 설치는 올바른 column으로 생성하고, 기존 설치는 migration으로 흡수하는 방식이 가장 단순하다.
- 범위: LLM usage latency column명과 migration compatibility.
- 영향 파일: `apps/shared/db/models/llm.py`, `apps/shared/alembic/versions/3d4d4f13ff35_initial_migration_with_all_tables.py`, `apps/shared/alembic/versions/f8a9b0c1d2e3_rename_llm_usage_latency_ms.py`, `apps/shared/tests/test_llm_usage_schema.py`, `docs/data-model/physical-data-model.md`, `docs/references/moduly-architecture/sections/06-data-model.md`, `docs/requirements/mvp-1-foundation-llmops.md`, `docs/implementation-plan/mvp-1-development-issue-plan.md`, `docs/implementation-plan/risk-consistency-verification.md`.
- 후속 검토: 배포 환경에서 migration 실행 전 legacy column 존재 여부를 점검하고, migration 이후 query와 dashboard가 `latency_ms`만 참조하는지 확인한다.
- ADR 승격 여부: No. schema naming 정정과 backward-compatible migration에 한정한다.

### MBA-44 / Issue #59 LLM call audit action 정합성

- 상태: Active
- 맥락: Issue #59는 workflow execute, permission denied, LLM call에 필요한 audit action 정리를 요구한다. LLM call 세부 관측값은 `llm_usage_logs`가 source of truth이지만 canonical audit action namespace에도 LLM call action이 필요하다.
- 결정: `AuditAction.LLM_CALL = "llm.call"`을 추가한다. 이번 issue에서는 LLM usage row를 audit log로 중복 저장하지 않고, `llm.call`은 향후 LLM 호출 audit event가 필요한 경로에서 사용할 canonical action으로 둔다.
- 근거: token, cost, latency, model/provider 관측 정보는 `llm_usage_logs`로 조회하는 것이 중복을 피한다. 단, action 상수는 audit skeleton의 명명 체계를 완성하고 후속 기록 지점을 안정화한다.
- 범위: Audit action namespace.
- 영향 파일: `apps/shared/audit/actions.py`, `apps/shared/tests/test_audit_actions.py`.
- 관련 문서: [requirements/mvp-1-foundation-llmops.md](../requirements/mvp-1-foundation-llmops.md), [api/tracing-audit.md](../api/tracing-audit.md)
- 후속 검토: 실제 LLM call audit event를 별도로 남길 경우, raw prompt/completion을 audit metadata에 저장하지 않는 whitelist 정책을 적용한다.
- ADR 승격 여부: No. action 상수 정합성 보강에 한정한다.

### MBA-44 / Issue #59 workflow execute audit 시점

- 상태: Active
- 맥락: workflow 실행 audit은 API 요청 수락 시점이 아니라 실제 실행 결과와 일치해야 한다.
- 결정: `workflow.execute` audit은 log worker의 `log.update_run_finish`와 `log.update_run_error`에서 실제 run 상태가 success/failure로 확정된 뒤 기록한다. 성공은 `status='success'`, 실패는 `status='failure'`를 사용한다. 권한 차단은 별도 `permission.denied` action으로 기록한다.
- 근거: API request accepted 시점에 success audit을 남기면 background task 실패를 반영하지 못한다. 실행 완료 로그 업데이트 지점이 실제 결과에 가장 가깝다.
- 범위: workflow run success/failure audit.
- 영향 파일: `apps/log_system/tasks.py`, `apps/shared/audit/actions.py`, `apps/log_system/tests/test_workflow_execute_audit.py`.
- 관련 문서: [requirements/mvp-1-foundation-llmops.md](../requirements/mvp-1-foundation-llmops.md), [data-model/physical-data-model.md](../data-model/physical-data-model.md)
- 후속 검토: 실행 시작 audit이 필요해지면 `workflow.execute.started` 같은 별도 action 도입을 검토한다.
- ADR 승격 여부: No. audit table/schema 정책 변경 없이 기록 시점만 정한다.

### MBA-44 / Issue #59 LLM trace UI fallback

- 상태: Active
- 맥락: run detail 화면은 새 LLM trace endpoint를 우선 사용해야 하지만, legacy run에는 `llm_usage_logs.workflow_id`가 비어 있거나 trace row가 없을 수 있다.
- 결정: workflow log detail의 token analysis는 `GET /api/v1/workflows/{workflow_id}/runs/{run_id}/llm-traces`를 우선 조회한다. 조회 결과가 있으면 trace row를 기준으로 node/model별 token, cost, latency, status를 표시한다. 0-token 또는 failed trace row도 숨기지 않고, `latency_ms=0`은 `0ms`로 표시한다. 조회 실패 또는 빈 결과에서는 기존 `node_runs.outputs.usage` 기반 표시를 유지하고, 실패 시에는 민감 정보 없이 안내 문구만 표시한다.
- 근거: 새 endpoint를 사용해 권한 검증과 whitelist 응답 경계를 적용하면서도 legacy 실행 로그의 관측 가능성을 유지한다. 실패 메시지에는 request/response body, credential, prompt, completion을 포함하지 않는다.
- 범위: workflow 실행 로그 상세 화면의 LLM token analysis.
- 영향 파일: `apps/client/app/features/workflow/api/workflowApi.ts`, `apps/client/app/features/workflow/types/Api.ts`, `apps/client/app/features/workflow/components/logs/LogDetail.tsx`, `apps/client/app/features/workflow/components/logs/detail-components/LogTokenAnalysis.tsx`.
- 관련 문서: [api/tracing-audit.md](../api/tracing-audit.md), [requirements/mvp-1-foundation-llmops.md](../requirements/mvp-1-foundation-llmops.md)
- 후속 검토: raw trace payload 조회 UI가 필요하면 기본 token analysis와 분리하고 별도 권한, audit, redaction 정책을 요구한다.
- ADR 승격 여부: No. Issue #59 UI 연결과 legacy fallback에 한정한다.
