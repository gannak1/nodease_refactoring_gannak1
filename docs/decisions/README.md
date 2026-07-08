# 설계 결정 기록 (ADR)

중요한 정책, 아키텍처, 데이터 저장, 접근 제어 결정을 기록한다. 작은 구현 기본값은 각 도메인 문서나 feature 문서에 둔다.

## 작성 기준

- 여러 문서나 여러 모듈에 영향을 주는 결정만 ADR로 남긴다.
- DB schema, RBAC, audit, data retention, organization boundary, 보안 경계는 ADR 후보로 본다.
- ADR은 결정의 이유와 선택지를 기록한다. 현재 구현 기준은 관련 문서(`docs/`, `features/`)에도 반드시 반영한다.
- 파일명은 `ADR-NNNN-topic-slug.md` 형식을 사용한다. `NNNN`은 4자리 순번이다.
- ADR 본문은 작성 시점의 기록으로 보존하고 소급 수정하지 않는다. 결정이 바뀌면 새 ADR을 추가하고 이전 ADR을 참조한다. 단 머리말 `Status`는 기록이 아니라 상태이므로 `Superseded` 등으로 전이할 수 있다.
- 새 ADR의 메타 블록은 `Status`만 필수로 하고, 관련 결정이 있으면 `Related ADRs`를 선택적으로 추가한다. `Date`는 git history가 답하므로 넣지 않고, 구현 반영 여부는 이 README의 `현재 코드 기준` 열이 담당하므로 `Verified Against`도 넣지 않는다.
- 이관 ADR의 `Date`, `Original`, `Verified Against` 필드는 이관 당시 기록으로 보존하며, 새 ADR 기준으로 소급 정리하지 않는다.

기존 `docs_old/decisions/`의 `ADR-YYYYMMDDHHmm-*` 파일은 2026-07-02 문서 체계 개편 때 이 디렉토리로 이관했다. 각 ADR 머리말의 `Original:` 항목이 원본 파일명을 가리키며, 이관 시 본문은 보존하고 링크와 번호만 새 구조에 맞게 갱신했다.

## 목록

ADR 본문은 작성 시점의 결정 과정을 보존하는 기록 문서다. `상태`는 해당 ADR 자체의 상태를 뜻하며, 현재 코드 기준은 `현재 코드 기준` 열을 따른다.

| ADR | 상태 | 주제 | 현재 코드 기준 |
| --- | --- | --- | --- |
| [ADR-0001](ADR-0001-active-organization.md) | Proposed | Active organization 결정 방식 | [ADR-0009](ADR-0009-active-organization-header-context.md)에 따라 `X-Organization-Id` header 방식 구현 |
| [ADR-0002](ADR-0002-auth-state-standard.md) | Proposed | auth_state 표준화 | [ADR-0006](ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md)에 따라 `none/viewer/operator/builder/manager`와 legacy mapping 구현 |
| [ADR-0003](ADR-0003-user-direct-permission.md) | Proposed | User direct permission 도입 | [ADR-0006](ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md)에 따라 `user_workflow_permissions`, `user_llm_permissions` 구현 |
| [ADR-0004](ADR-0004-audit-log-rag-trace-storage.md) | Accepted | audit_logs와 RAG trace 저장 기준 | `audit_logs`, trace payload 계열 table 재사용 |
| [ADR-0005](ADR-0005-data-model-document-structure.md) | Superseded | 데이터 모델 문서 구조 | 2026-07-02 문서 체계 개편으로 대체됨. 데이터 모델 문서는 [docs/data_model.md](../data_model.md) 단일 문서 기준 |
| [ADR-0006](ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md) | Accepted | RBAC auth_state 및 User Direct Permission 승인 | 현재 코드의 workflow/LLM credential RBAC 기준. `user_knowledge_permissions`, `user_audit_permissions`는 아직 구현되지 않음 |
| [ADR-0007](ADR-0007-mvp2-classification-metadata-storage.md) | Accepted | MVP 2 classification metadata 저장 방식 | `documents.meta_info` 사용 가능. `knowledge_bases.classification`, `documents.classification` column 없음 |
| [ADR-0008](ADR-0008-audit-action-naming-standard.md) | Accepted | Audit action naming 표준 | MVP 1 주요 `AuditAction`과 organization membership invite/accept/update/remove action 구현. permission row 변경은 `*_permission.created/updated/deleted` data-change audit도 기록. `policy.warn`, `policy.block`, `rag.retrieve`는 MVP 2 목표 action이며, RAG Agent answer lifecycle/purge 목표 action은 `rag.answer.*`로 구분 |
| [ADR-0009](ADR-0009-active-organization-header-context.md) | Accepted | Active organization header context 승인 | organization/team/permission API와 app 생성/목록/복제, workflow 생성 API에서 `X-Organization-Id` 검증 구현. MBA-67 이후 scope 판정은 active organization membership을 기준으로 하며, membership row 자체가 없는 legacy owner/manager만 fallback을 받는다 |
| [ADR-0010](ADR-0010-resource-access-403-404-policy.md) | Accepted | Resource 접근 403/404 정책 | App/Workflow에서 organization scope 밖은 `404`, scope 안 action 권한 부족은 `403` |
| [ADR-0011](ADR-0011-team-router-rbac-service-boundary.md) | Accepted | Team API RBAC service boundary | Team 관리 권한 판정과 team/team member 조회는 `TeamService`가 소유하고, 등록 router는 기존 `team.py` 기준 유지 |
| [ADR-0012](ADR-0012-metadata-aware-hierarchical-rag-boundary.md) | Accepted | Metadata-aware 및 Hierarchical RAG 경계 | Metadata filter는 allowlist schema, metadata는 permission source가 아니며, RAG trace는 raw chunk content 없이 citation metadata를 저장 |
| [ADR-0013](ADR-0013-rag-answer-trace-usage-correlation-boundary.md) | Accepted | RAG Agent answer와 trace/usage correlation 경계 | Standalone Agent answer는 RAG-owned `rag_answer_runs`와 opaque `correlation_id`로 연결하고, trace/usage table에 RAG 전용 FK를 추가하지 않음 |
| [ADR-0014](ADR-0014-knowledge-base-document-atom-and-collection-boundary.md) | Accepted | Knowledge Base document atom과 Collection 경계 | 목표 KB 통합 모델에서 Knowledge Base는 document/source item 단위 permission/retrieval/sync/lifecycle atom이고, Knowledge Collection은 grouping/routing/ops 단위. RAG/embedding은 redacted canonical text만 사용하고 raw content는 opt-in protected artifact로만 별도 저장 가능. Destructive cutover는 별도 승인 대상이며, MBA-105의 source ACL/API/privacy baseline은 ADR-0017을 따른다 |
| [ADR-0015](ADR-0015-knowledge-skill-context-routing-boundary.md) | Accepted | Knowledge Skill과 LLM node RAG 옵션 구성 경계 | Knowledge Skill은 Workflow Builder가 LLM node의 RAG 옵션을 구성할 때 참고하는 provider-neutral 절차/context/routing artifact다. 권한 source나 source of truth가 아니며 실행 시점 RAG 권한을 부여하지 않는다 |
| [ADR-0016](ADR-0016-permission-request-and-app-creation-permission.md) | Accepted | 권한 신청과 App 생성 권한 모델 | App 생성(`POST /apps`) 권한 검사, `permission_requests`, `user_app_creation_permissions`, 신청/승인/거절 API와 audit 구현. Organization member 제거 시 App 생성 권한 row도 cleanup 대상 |
| [ADR-0017](ADR-0017-knowledge-integration-provisional-implementation-baseline.md) | Accepted | Knowledge 통합 임시 구현 baseline | MBA-105에서는 ADR-0014/0015의 남은 구현 gate에 대해 보수적 임시 baseline을 채택한다. Source ACL은 KB use를 대체하지 않고, auto-ingested KB use provisioning, active version finalization, protected source identity, LLM node RAG option runtime, query rewrite/evidence sufficiency, resource hiding, 운영 기본값을 이 ADR 기준으로 구현한다. Workflow RAG의 `execution_subject` 부재 처리는 MVP에서 [ADR-0018](ADR-0018-workflow-rag-anonymous-public-only-runtime.md)이 보정한다 |
| [ADR-0018](ADR-0018-workflow-rag-anonymous-public-only-runtime.md) | Accepted | Workflow RAG anonymous public-only runtime | Interactive 실행은 `execution_subject=current_user`를 전달한다. `execution_subject`가 없으면 workflow owner/user_id fallback 없이 active public collection 소속 KB만 anonymous public-only로 검색한다. Source-managed KB는 ADR-0020의 public exposure approval도 통과해야 한다. Private KB 자동 실행용 service account/operator/preflight는 후속 기능이다 |
| [ADR-0019](ADR-0019-agent-builder-preview-apply-save-boundary.md) | Accepted | Agent Builder preview apply/save boundary | Agent Builder draft는 Preview Mode에서 `previewGraph`로 검토하고, `적용 및 저장`은 backend 재검사와 apply/save audit 기록 성공을 통과한 경우 workflow graph 저장 성공으로 처리한다. 저장 성공 전 audit event는 canonical audit store에 기록되었거나 동등한 durable outbox/queue에 enqueue되어야 한다. 단 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경은 수행하지 않는다 |
| [ADR-0020](ADR-0020-knowledge-mcp-incremental-sync-boundary.md) | Accepted | Knowledge MCP incremental sync boundary | MCP/API source connector는 LLM 자유 tool-use가 아니라 Knowledge Source Connector 뒤의 allowlist adapter로 둔다. Live-linked source-side search는 requester-scoped 또는 opaque-ref-only flow만 허용하고, runtime source authorization은 batch 우선 primitive와 bounded fallback을 사용한다. Source-managed KB public exposure는 collection public flag와 별도 approval scope validation을 모두 통과해야 한다 |

## 참고 보고서

| 문서 | 성격 | 기준 |
| --- | --- | --- |
| `docs_old/decisions/docs-code-discrepancy-report-20260629.md` | docs와 code 불일치 조사 보고서. 현재 active source of truth가 아니라 정리 근거 기록이다. `docs_old/` 삭제 후에는 아카이브 커밋(eedd820)의 git history에서 확인한다. | `dev @ c990b54e931b4de8023822f6dff14f43fc1d415f` |

## 상태 의미

- `Proposed`: 작성 당시 제안 상태로 남은 기록이다. 현재 구현 기준은 반드시 `현재 코드 기준` 열을 따른다.
- `Accepted`: 채택된 결정 기록이다. 실제 구현 반영 여부와 범위는 `현재 코드 기준` 열을 따른다.
- `Superseded`: 다른 ADR 또는 문서로 대체됨.
