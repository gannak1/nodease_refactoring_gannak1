# 구현 결정 로그

Status: Draft
Authority: Implementation Plan
Source of Truth: No
Verified Against: feature/mba-85 plan @ 4926805 (base dev 4926805)
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

## 2026-06-30

### MBA-78 1차 구현 범위와 PR 분리

- 상태: Active
- 맥락: MBA-75에서 Metadata-aware/Hierarchical RAG 공식 문서와 ADR은 정리됐지만, 실제 RAG 구현은 MBA-78에서 진행한다. 구현 범위에는 metadata filter, KB `use` 권한, active organization header, retrieval trace/audit, hierarchy schema, ingestion, frontend UI가 함께 걸려 있어 한 PR에 모두 담으면 리뷰와 회귀 검증 범위가 과도해진다.
- 결정: MBA-78 1차 구현은 백엔드 계약 고정에 집중한다. 포함 범위는 RAG 요청 스키마, metadata filter validation, KB `use` effective permission helper, Gateway search-test의 `X-Organization-Id` 적용, Gateway/Workflow retrieval filter 적용, Workflow runtime RAG 권한 적용, `rag.retrieve` audit action과 `rag.retrieval` trace payload 경계의 최소 구현, hierarchy column migration과 flat fallback 기반이다. Full parent-child ingestion, ranking 품질 튜닝, frontend filter/citation UI, `user_knowledge_permissions` model/API는 범위가 커지면 후속 PR로 분리한다.
- 근거: 공식 문서는 `user_knowledge_permissions`를 MVP 2 목표 table로 두지만 현재 코드에는 model/migration이 없다. Phase 1 권한 원천은 organization manager override와 `team_knowledge_permissions`로 제한하고, active organization membership은 scope 전제 조건으로만 사용한다. Frontend와 full hierarchy ingestion은 backend contract 고정 이후 별도 검증이 더 적절하다.
- 범위: MBA-78 구현 계획과 1차 PR 분리 기준.
- 영향 파일: `local/mba-78/implementation-plan.md`, `local/mba-78/open-decisions.md`, RAG schema/permission/retrieval/trace 구현 파일.
- 관련 문서: [Knowledge/RAG API](../api/knowledge-rag.md), [Knowledge/RAG architecture](../architecture/knowledge-rag.md), [RBAC permission policy](../data-model/rbac-permission-policy.md), [metadata-aware hierarchical RAG ADR](../decisions/ADR-202606301045-metadata-aware-hierarchical-rag-boundary.md)
- 후속 검토: 1차 PR의 변경 파일과 테스트 범위가 커지면 hierarchy ingestion 또는 frontend를 후속 PR로 확정 분리한다. `user_knowledge_permissions` 추가 이슈가 생성되면 KB effective permission helper에서 additive direct grant를 연결한다.
- ADR 승격 여부: No. 공식 문서의 목표 계약을 PR/커밋 단위로 나누는 구현 계획이며 새 제품 정책을 만들지 않는다.

### MBA-78 org-scoped RAG의 legacy KB organization 처리

- 상태: Active
- 맥락: 기존 `knowledge_bases.organization_id`는 nullable이고 legacy row가 남을 수 있다. MBA-78 1차 구현은 RAG search-test와 Workflow runtime retrieval을 org-scoped KB `use` 권한으로 전환한다. 이때 KB `organization_id`가 없으면 요청의 `X-Organization-Id` 또는 workflow execution organization으로 보정할지, 아니면 scope 밖 resource로 닫을지 결정해야 한다.
- 선택지: 1) nullable KB를 요청 organization으로 보정한다. 2) nullable KB는 KB owner/current user fallback으로 허용한다. 3) org-scoped RAG에서는 KB `organization_id`를 필수로 보고 nullable KB를 fail-closed 처리한다.
- 결정: 3안을 따른다. Org-scoped RAG는 KB `organization_id`가 반드시 있어야 하며, `organization_id=null` legacy KB는 backfill/reassignment 전까지 scope 밖 resource로 처리한다.
- 근거: 공식 RAG/RBAC 문서는 active organization context와 KB `organization_id` 비교를 scope prerequisite로 둔다. 요청 header나 workflow context로 nullable KB를 보정하면 cross-tenant resource attribution이 불명확해지고, organization manager override와 team knowledge permission의 target organization도 방어하기 어렵다.
- 범위: RAG search-test API, Workflow Engine LLM node RAG retrieval, KB effective permission helper, RAG 권한 테스트.
- 영향 파일: `apps/shared/services/permissions.py`, `apps/shared/tests/services/test_permissions.py`, `docs/api/knowledge-rag.md`, `docs/architecture/knowledge-rag.md`
- 관련 문서: [Knowledge/RAG API](../api/knowledge-rag.md), [Knowledge/RAG architecture](../architecture/knowledge-rag.md), [metadata-aware hierarchical RAG ADR](../decisions/ADR-202606301045-metadata-aware-hierarchical-rag-boundary.md)
- 후속 검토: Legacy KB backfill 또는 reassignment 관리 API가 도입되면 nullable KB를 운영에서 어떻게 발견/정리할지 migration/runbook으로 분리한다.
- ADR 승격 여부: No. ADR의 org scope prerequisite를 구현에서 fail-closed로 적용한 범위이며, 별도 제품 정책을 새로 만들지 않는다.

### MBA-78 RAG credential routing, denial audit, trace summary 경계

- 상태: Active
- 맥락: RAG retrieval은 embedding/query rewrite/generation 단계에서 LLM credential을 사용한다. MBA-78 1차 구현에서 RAG는 active organization scope를 필수로 전환했으므로, multi-organization user가 다른 organization credential로 routing되는 것을 막아야 한다. 또한 KB `use` 권한 거부는 resource permission 실패이고, per-chunk evidence는 run/node metadata가 아니라 trace payload에 남겨야 한다.
- 선택지: 1) RetrievalService 내부 LLM 호출은 기존 user-only credential routing을 유지한다. 2) RetrievalService 생성 시 active organization을 전달하고 모든 내부 LLM client 조회에 사용한다. 3) Endpoint/runtime마다 credential을 미리 만들어 RetrievalService에 주입한다.
- 결정: 2안을 따른다. Gateway와 Workflow Engine `RetrievalService`는 `organization_id`를 선택 인자로 받고, embedding/query rewrite/generation client 조회 시 `LLMService.get_client_for_user(..., organization_id=...)`로 전달한다. Workflow runtime은 여러 KB를 검색하기 전에 모든 KB의 `use` 권한을 먼저 검증한다. KB `use` 거부는 `audit_logs.action='permission.denied'`로 한 번 기록하고, successful retrieval은 `rag.retrieve`로 기록한다. Run/node RAG metadata는 `retrieved_chunk_count`, `document_ids`, `citation_ids`, `score_summary` 등 summary field만 저장하고 per-chunk evidence는 `trace_payloads.payload_kind='rag.retrieval'`로 분리한다. Runtime payload body에는 `workflow_node_run_id`를 중복 저장하지 않고 logger가 `trace_payloads.workflow_node_run_id` 컬럼으로 연결한다.
- 근거: 공식 RAG/RBAC 문서는 active organization context와 KB organization scope 비교를 전제 조건으로 둔다. LLM credential routing에도 같은 organization context를 전달해야 cross-tenant credential 사용을 피할 수 있다. Permission denial과 policy block/warn은 audit action 의미가 다르므로 섞지 않는다. Run/node metadata에 per-chunk evidence를 복사하면 trace payload visibility/redaction 경계를 우회할 수 있다.
- 범위: MBA-78 RAG search-test, Workflow Engine LLM node RAG retrieval, RetrievalService LLM client routing, trace metadata sanitizer.
- 영향 파일: `apps/gateway/services/retrieval.py`, `apps/workflow_engine/services/retrieval.py`, `apps/gateway/api/v1/endpoints/rag.py`, `apps/workflow_engine/workflow/nodes/llm/llm_node.py`, `apps/shared/services/permission_audit.py`, `apps/shared/services/tracing/metadata.py`, `apps/workflow_engine/workflow/core/workflow_engine.py`, RAG/trace/RBAC 문서와 테스트.
- 관련 문서: [Knowledge/RAG API](../api/knowledge-rag.md), [Knowledge/RAG architecture](../architecture/knowledge-rag.md), [RBAC permission policy](../data-model/rbac-permission-policy.md), [audit action ADR](../decisions/ADR-202606290131-audit-action-naming-standard.md), [metadata-aware hierarchical RAG ADR](../decisions/ADR-202606301045-metadata-aware-hierarchical-rag-boundary.md)
- 후속 검토: `policy.warn`/`policy.block` document metadata enforcement가 연결되면 permission denial audit와 policy audit가 중복되지 않는지 테스트한다. Trace payload access policy가 raw/evidence 조회와 UI citation 표시를 어떻게 분리할지도 별도 검증한다.
- ADR 승격 여부: No. 기존 ADR/RBAC/trace 계약을 구현 경계에 적용한 결정이며 새 제품 정책을 추가하지 않는다.

### MBA-85 hierarchical ingestion/retrieval 2단계 구현 경계

- 상태: Active
- 맥락: MBA-78 1차는 hierarchy column과 flat fallback, RAG 권한/trace 경계를 고정했지만 실제 parent-child ingestion과 parent-child retrieval은 후속 범위로 남겼다. MBA-85는 이 후속 범위를 backend 중심으로 연결한다. 다만 source type, preview schema, chunk tuning 입력, 저장 transaction 순서를 명확히 하지 않으면 기존 flat ingestion과 preview UI, DB source semantics를 깨뜨릴 수 있다.
- 선택지: 1) 모든 source type에 hierarchical chunking을 열고 고급 chunk size 입력도 공개한다. 2) FILE/API source에만 opt-in hierarchical chunking을 열고 고급 입력은 내부 기본값으로 둔다. 3) ingestion 변경 없이 retrieval만 parent-child data가 있는 경우 처리한다.
- 결정: 2안을 따른다. 공개 API는 `chunkingMode`/`chunking_mode=flat|hierarchical`만 추가한다. `DocumentPreviewRequest` 계열 JSON 입력은 `chunkingMode` alias를 허용하지만 service layer 이후 내부 표준 field는 `chunking_mode`다. `parentChunkSize`, `childChunkSize`, `childChunkOverlap`, arbitrary depth 설정은 공개하지 않는다. Hierarchical ingestion은 FILE/API source에만 적용하고 DB source는 `400 unsupported_chunking_mode_for_source`로 닫는다. Workflow Engine DB sync와 shared `VectorStoreService`는 MBA-85에서 flat-only 경로로 유지하며, DB source의 `chunking_mode=hierarchical` 또는 non-flat parent/child payload를 조용히 flat으로 변환하지 않는다. `chunkingMode=hierarchical`과 `selection_mode=range` 조합은 `400 invalid_chunking_selection`으로 닫는다. Preview response schema는 확장하지 않고 child evidence content만 기존 `DocumentSegment` shape로 반환한다. Parent routing chunk는 LLM summary가 아니며 preview/final response의 독립 evidence content로 노출하지 않는다. 모든 parent/child embedding, encryption, keyword/token 준비가 성공한 뒤 같은 transaction에서 기존 chunk 삭제, parent insert/flush, child insert, document metadata 갱신, commit을 수행한다. Hierarchical path의 content 암호화 실패는 처리 실패로 닫고 평문 fallback을 만들지 않는다. `content_hash` 기반 skip은 `chunking_fingerprint_hash`까지 일치할 때만 허용한다. 최종 ranking score는 child/flat evidence score 기준이고 parent route score는 후보 제한/tie-break/boost 용도에 한정한다. Unknown `chunk_level`은 evidence 후보에서 제외한다. MBA-85는 run/node RAG metadata allowlist를 넓히지 않고, hierarchy diagnostic 값은 redacted trace payload에만 둔다.
- 근거: FILE/API 문서는 section/텍스트 블록 기반 hierarchy를 만들 수 있지만 DB source는 row/table/join 구조라 별도 설계가 필요하다. DB sync/shared vector store 경로는 현재 DB processor 결과를 flat chunk로 저장하는 책임을 갖고 있어, 여기에 parent/child semantics를 섞으면 DB hierarchy 정책이 암묵적으로 생긴다. 고급 tuning 입력을 공개하면 frontend/API/test 계약이 과도하게 넓어진다. Preview schema를 유지하면 frontend 변경 없이 backend hierarchy builder를 검증할 수 있다. 기존 chunk 삭제를 마지막 transaction으로 미루면 embedding/encryption 실패 시 기존 retrieval 가능 상태를 보존할 수 있다. 신규 hierarchy path에서 평문 fallback을 금지하면 기존 flat 경로의 호환성은 건드리지 않으면서 새 저장 경로의 보안 기준을 높일 수 있다. Fingerprint를 두지 않으면 원문이 같다는 이유로 `flat -> hierarchical` 전환이 조기 종료될 수 있다. Parent score와 evidence score를 단순 혼합하면 mixed hierarchy/flat KB ranking이 불안정해진다. Run/node metadata allowlist를 넓히지 않으면 trace 노출면을 유지하면서 diagnostic은 payload로 분리할 수 있다.
- 범위: MBA-85 backend hierarchical chunking, parent-child retrieval, preview/process/upload/confirm/sync 경로의 chunking mode 보존, RAG API/architecture/data-model/error 문서.
- 영향 파일: `docs/api/knowledge-rag.md`, `docs/architecture/knowledge-rag.md`, `docs/data-model/physical-data-model.md`, `docs/api/errors.md`, `local/mba-85/implementation-plan.md`, RAG ingestion/retrieval/schema/tests.
- 관련 문서: [Knowledge/RAG API](../api/knowledge-rag.md), [Knowledge/RAG architecture](../architecture/knowledge-rag.md), [physical data model](../data-model/physical-data-model.md), [metadata-aware hierarchical RAG ADR](../decisions/ADR-202606301045-metadata-aware-hierarchical-rag-boundary.md)
- 후속 검토: DB row/table 기반 hierarchical chunking, advanced tuning UI/API, preview hierarchy metadata 노출, frontend citation UI, LLM 기반 parent summary 생성, 기존 flat ingestion 암호화 실패 fallback 제거, hierarchy diagnostic run/node metadata 확장 여부는 별도 이슈로 분리한다.
- ADR 승격 여부: No. 기존 ADR의 parent-child retrieval 경계를 구현 단계로 좁히는 결정이며, DB source hierarchy나 LLM summary 같은 새 제품 정책은 후속으로 분리한다.

### MBA-67 organization membership helper 전환
- 상태: Active
- 맥락: MBA-66으로 `organization_memberships` DB/model/migration/backfill이 병합되었지만, 일부 permission helper와 API는 여전히 active team membership을 organization scope 전제로 사용했다. 공식 문서는 MVP 2-0 이후 organization membership을 조직 소속의 전제 조건으로 둔다.
- 선택지: 1) 기존 team membership 기반 scope 판정을 유지한다. 2) helper/API를 즉시 `organization_memberships` 기준으로 전환하되 legacy owner/manager fallback만 제한적으로 유지한다. 3) 실제 membership API가 모두 완성될 때까지 production code 전환을 보류한다.
- 결정: MBA-67은 `get_organization_auth_state`, `has_active_organization_membership`, `has_organization_manager_permission`, `has_organization_scope_access`를 실제 `OrganizationMembership` model 기준으로 구현한다. Resource permission helper는 active user와 active organization 안의 active organization member를 선행 조건으로 보고, active manager membership은 resource manager override로 본다. Invited/suspended/removed membership row는 fail-closed 처리하고, membership row 자체가 없을 때만 `organization.created_by`/`managed_by` legacy fallback을 manager로 허용한다. Team membership 조회는 organization membership을 생성하거나 대체하지 않는다. `GET /users` 같은 read API는 primary organization이 없거나 organization이 inactive/scope 밖이면 404로 닫고 default organization을 생성하지 않는다. `organization_id is null`인 legacy workflow는 active `created_by` user에게만 manager fallback을 허용한다.
- 근거: 문서상 목표 계약은 organization membership이 조직 소속의 기준이며, MBA-66 backfill이 기존 team membership과 owner/manager 정보를 이미 organization membership row로 이전한다. Legacy fallback은 backfill 누락이나 과거 데이터 호환을 위한 좁은 안전장치로만 남겨야 한다.
- 범위: organization scope helper, workflow/LLM credential effective permission helper, organization context fallback, organization/user/team/permission API의 scope 검증.
- 영향 파일: `apps/shared/services/permissions.py`, `apps/shared/services/permission_enforcement.py`, `apps/gateway/services/organization_context.py`, `apps/gateway/services/team_service.py`, `apps/gateway/api/v1/endpoints/organization.py`, `apps/gateway/api/v1/endpoints/users.py`, `apps/gateway/api/v1/endpoints/permissions.py`, `apps/gateway/auth/permissions.py`, `docs/architecture/auth-rbac.md`, `docs/data-model/rbac-permission-policy.md`, `docs/api/auth.md`, `docs/api/organization-rbac.md`, `docs/api/apps-workflows.md`, `docs/api/knowledge-rag.md`.
- 후속 검토: Manager 조회용 composite index 필요 여부를 query plan 기준으로 재검토한다. Organization membership invite/update API가 도입되면 legacy fallback 제거 시점과 마지막 manager guard를 별도 이슈에서 확정한다. Direct permission 회수는 stale row cleanup을 위해 대상 user의 현재 active membership을 요구하지 않는 정책을 유지할지 재검토한다.
- ADR 승격 여부: No. 공식 문서의 목표 계약을 구현 helper에 연결하는 범위이며, 새 제품 정책을 도입하지 않는다.

### MBA-66 organization_memberships migration 분리
- 상태: Active
- 맥락: MBA-66은 organization membership foundation DB/model/migration 추가가 범위이며, API/helper/FE 전환은 후속 이슈 범위다.
- 결정: `organization_memberships` schema migration과 backfill data migration을 별도 Alembic revision으로 분리한다. Data migration downgrade는 기존 source table로 역전파하지 않는 no-op으로 둔다.
- 근거: DDL과 DML 실패 원인을 분리하고, backfill 재실행성을 검증하기 쉽다. Backfill row를 기존 `team_memberships`, `organization.created_by`, `organization.managed_by`로 정확히 되돌리는 역변환은 안전하지 않다.
- 범위: MBA-66 Alembic migrations.
- 영향 파일: `apps/shared/alembic/versions/*_add_organization_memberships.py`, `apps/shared/alembic/versions/*_backfill_organization_memberships.py`.
- 관련 문서: [mvp-2-0 organization membership foundation](mvp-2-0-organization-membership-invitation-foundation.md), [physical data model](../data-model/physical-data-model.md)
- 후속 검토: 운영 데이터 규모가 커지면 backfill batch size와 lock 시간을 별도 migration runbook에서 검토한다.
- ADR 승격 여부: No

### MBA-66 backfill source와 conflict 처리
- 상태: Active
- 맥락: 기존 schema에는 organization 직접 membership row가 없고, 초기 membership은 legacy `team_memberships`, `organization.created_by`, `organization.managed_by`에서 유도해야 한다.
- 결정: `team_memberships` source는 active member로 upsert하고, `organization.created_by`와 `organization.managed_by` source는 active manager로 upsert한다. 같은 `(organization_id, user_id)`가 충돌하면 manager source를 우선해 `organization_auth_state='manager'`로 승격하고, manager row를 member로 낮추지 않는다. `team_memberships.assigned_by`가 유효하지 않으면 `organization.created_by`를 `invited_by` fallback으로 사용한다.
- 근거: MBA-66은 데이터 foundation을 만드는 이슈이므로 기존 팀 기반 소속과 organization owner/manager 정보를 모두 보존해야 한다. Invalid `assigned_by` 때문에 유효한 source row 전체를 잃는 것보다 organization creator fallback이 후속 audit/cleanup에 안전하다.
- 범위: MBA-66 backfill migration.
- 영향 파일: `apps/shared/alembic/versions/*_backfill_organization_memberships.py`.
- 관련 문서: [physical data model](../data-model/physical-data-model.md), [RBAC permission policy](../data-model/rbac-permission-policy.md)
- 후속 검토: MBA-67 helper 전환 시 legacy fallback 제거 또는 유지 기간을 재검토한다.
- ADR 승격 여부: No

### MBA-66 OrganizationMembership 모델 위치와 export
- 상태: Active
- 맥락: 공식 문서는 table schema를 정의하지만 SQLAlchemy model 파일 위치와 상태 상수 export 위치까지 고정하지 않는다.
- 결정: `OrganizationMembership`은 `apps/shared/db/models/organization_membership.py`에 별도 model로 두고, membership/auth state 문자열 상수와 함께 `apps/shared/db/models/__init__.py`에서 export한다.
- 근거: 기존 `team.py` 파일에 새 organization membership까지 합치면 후속 membership/permission 추상화가 더 어려워진다. 별도 파일은 MBA-66 범위를 지키면서도 후속 리팩터링에 유리하다.
- 범위: SQLAlchemy model registry.
- 영향 파일: `apps/shared/db/models/organization_membership.py`, `apps/shared/db/models/__init__.py`, `apps/shared/alembic/env.py`.
- 관련 문서: [physical data model](../data-model/physical-data-model.md)
- 후속 검토: 별도 refactor issue에서 team/user permission mixin 구조를 정리한다.
- ADR 승격 여부: No

### MBA-66 manager 조회용 추가 index 보류
- 상태: Active
- 맥락: `(organization_id, membership_state, organization_auth_state)` index는 후속 manager helper에서 유용할 수 있지만, Linear MBA-66 필수 index 범위에는 없다.
- 결정: MBA-66에서는 필수 index만 생성하고, manager 조회용 composite index는 만들지 않는다.
- 근거: MBA-66은 DB foundation 범위이므로 아직 구현되지 않은 helper query를 위해 schema를 선행 확장하지 않는다.
- 범위: `organization_memberships` index 설계.
- 영향 파일: `apps/shared/alembic/versions/*_add_organization_memberships.py`, `docs/data-model/physical-data-model.md`.
- 관련 문서: [physical data model](../data-model/physical-data-model.md)
- 후속 검토: MBA-67에서 `has_organization_manager_permission`, last-manager guard query가 확정되면 query plan 기준으로 추가 여부를 판단한다.
- ADR 승격 여부: No

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
- 맥락: RAG document preview/process와 upload ingestion의 초기 chunk 기본값이 필요하다.
- 결정: 현재 코드 기준 `DocumentPreviewRequest`/document process는 `chunk_size=500`, `chunk_overlap=50`을 기본값으로 사용한다. `POST /api/v1/rag/upload` Form과 `IngestionOrchestrator` 기본값은 `chunkSize=1000`, `chunkOverlap=200`이다. DB processor의 adaptive chunker fallback은 별도 source config가 없으면 `chunk_size=1000`, `overlap=150`을 사용한다.
- 근거: preview/process는 빠른 미리보기에 맞춘 값이고, upload ingestion은 기존 RAG upload contract와 저장된 document 기본 응답값에 맞춘 구현 기본값이다.
- 범위: RAG preview/process request 값, upload ingestion Form 기본값, DB source processor fallback 값.
- 영향 파일: `api/knowledge-rag.md`, RAG ingestion 관련 구현 파일.
- 관련 문서: [api/knowledge-rag.md](../api/knowledge-rag.md)
- 후속 검토: 실제 검색 품질과 비용을 평가한 뒤 조정한다.
- ADR 승격 여부: No. 단, 모든 tenant에 강제되는 제품 정책이 되거나 재색인 migration에 영향을 주면 ADR 후보로 승격한다.
