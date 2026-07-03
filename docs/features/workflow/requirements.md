# Workflow Requirements

Status: Draft
Related Features: auth, organization, agent-builder, audit-tracing, knowledge

## 목적

Workflow feature는 사용자가 업무 절차를 노드 그래프로 구성하고, 수동 실행·스케줄·웹훅·API trigger로 실행할 수 있게 한다. 이 문서는 전체 workflow runtime 요구사항 중 다른 도메인과 충돌하기 쉬운 권한·실행 주체·감사 경계를 우선 기록한다.

## 사용자 이야기

- 빌더로서, workflow를 만들고 테스트 실행하며 배포 전에 필요한 credential과 권한 누락을 확인하고 싶다.
- 운영자로서, schedule/webhook/API trigger로 실행된 workflow가 어떤 주체 권한으로 외부 호출과 RAG retrieval을 수행했는지 추적하고 싶다.
- 감사자로서, workflow owner와 실제 execution subject를 구분해 audit/trace에서 확인하고 싶다.

## 기능 요구사항

- FR-001: Workflow run context는 organization, workflow, workflow version, run id, node id, trigger mode, actor 또는 service account 정보를 전달한다.
- FR-002: Interactive 실행은 요청 사용자를 execution subject로 사용할 수 있다.
- FR-003: Schedule, webhook, API trigger처럼 요청 사용자가 명확하지 않은 실행은 배포 시 승인된 service account, assigned operator, 또는 별도 정책으로 확정된 execution subject를 사용한다.
- FR-004: Agent/LLM/RAG node가 Knowledge retrieval을 호출할 때 workflow runtime은 명시적으로 resolve한 `execution_subject`와 sanitized `subject_resolution_reason`을 Knowledge service에 전달한다.
- FR-005: `execution_subject`가 없거나 모호하면 Knowledge retrieval preflight를 fail-closed로 처리한다. Workflow owner 권한으로 조용히 fallback하지 않는다.
- FR-006: Workflow owner, deployment owner, execution subject는 audit/trace에서 구분할 수 있어야 한다. Owner는 소유권과 관리 표시에는 사용할 수 있지만, 명시 정책 없이 runtime data access 권한으로 사용하지 않는다.

## 정책과 Edge Case

- 생성된 workflow나 Agent Builder가 만든 workflow도 일반 workflow와 동일한 organization scope, RBAC, audit, trace 정책을 따른다.
- Workflow 실행 권한, LLM credential `use`, connector/connection 사용 권한, Knowledge KB/source ACL 권한은 서로를 대체하지 않는다.
- Workflow runtime HTTP/GitHub/Mail node의 전체 outbound egress policy는 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)의 Knowledge source collection egress boundary와 별도 gate다.
- RAG를 포함한 workflow 비교 실행이나 A/B 실행도 동일한 execution subject와 Knowledge permission/source ACL gate를 사용한다.
- Missing/ambiguous execution subject, suspended/removed membership, inactive service account는 fail-closed로 처리한다.

## 열린 질문

- Service account의 데이터 접근 범위와 승인 절차를 Auth/RBAC에서 어떤 table과 helper로 표현할지.
- Schedule/webhook/API trigger의 `execution_subject` resolution reason enum과 audit action 이름.
- Workflow runtime outbound egress guard를 Knowledge source egress guard와 통합할지 별도 runtime ADR로 둘지.
