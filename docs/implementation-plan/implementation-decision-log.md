# 구현 결정 로그

Status: Draft
Authority: Implementation Plan
Source of Truth: No
Verified Against: dev @ c990b54e931b4de8023822f6dff14f43fc1d415f
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
