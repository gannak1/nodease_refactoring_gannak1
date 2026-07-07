# Agent Builder Requirements

Status: Draft
Related Features: workflow, knowledge, llm-credentials, deployment

## Purpose

자연어 프롬프트로부터 실행 가능한 workflow 초안을 자동 생성해, 비개발자와 빌더의 자동화 진입 장벽을 낮춘다. [PRD](../../PRD.md)의 FR-001~FR-003을 담당한다.

현재 코드에는 node 단위 wizard(prompt improve, code generate, template improve)만 있으며, 프롬프트에서 workflow 전체 그래프를 생성하는 기능은 신규 목표다.

## User Stories

- 빌더로서, "고객 문의 이메일을 분류하고 답변해줘" 같은 프롬프트를 입력하면 실행 가능한 workflow 초안을 받고 싶다.
- 빌더로서, 생성된 초안을 캔버스에서 수정하고 테스트 실행한 뒤 배포하고 싶다.
- 빌더로서, 생성된 workflow에 필요한 credential이나 권한이 없으면 실행 전에 미리 알고 싶다.

## Functional Requirements

- FR-001: 자연어 프롬프트를 입력받아 노드 그래프(예: `Webhook → LLM 분류 → Condition → LLM 답변 → 이메일`)를 생성하고 캔버스에 표시한다.
- FR-002: 생성된 workflow는 기존 캔버스 편집기와 테스트 실행 경로를 그대로 사용한다. 별도 편집/실행 경로를 만들지 않는다.
- FR-003: 생성 결과에 필요한 credential/모델/권한이 없으면 어떤 것이 부족한지 사전에 안내한다. 기존 wizard의 check-credentials 흐름을 참고한다.
- FR-004: Workflow Builder 또는 생성된 LLM node가 사내 지식을 사용할 때는 Knowledge feature의 collection routing/KB permission/source ACL helper 결과만 사용한다. Builder와 LLM planner가 raw permission row, raw source ACL, hidden KB 목록을 직접 해석하지 않는다.
- FR-005: Workflow runtime에서 LLM node가 RAG를 호출할 때 run context에 명시적인 execution subject가 있으면 이를 Knowledge service에 전달한다. Execution subject가 없으면 workflow owner 권한으로 fallback하지 않고 anonymous public-only로 낮추며, 모호한 subject는 private retrieval fail-closed로 처리한다.
- FR-006: Agent Builder는 Knowledge Skill을 workflow 생성/수정 제안과 LLM node의 RAG 옵션 구성에 사용할 수 있다. 이때 Skill은 provider-neutral 절차/context/routing artifact이며, 실행 시점 RAG 권한은 계속 Knowledge permission helper와 source ACL gate가 결정한다.
- FR-007: Agent Builder가 Skill을 prompt context로 사용할 경우 skill visibility, safe metadata display, freshness/eval gate를 통과한 Skill metadata/body/checklist만 사용한다. Skill이 제안한 collection/KB reference는 workflow 실행 시점에 execution subject 권한으로 다시 검증된다.
- FR-008: Agent Builder는 LLM node의 RAG 옵션인 `query_rewrite_mode`, `evidence_sufficiency_policy`, source tier hint 같은 후보를 제안할 수 있다. 기본값은 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)을 따른다. 이 설정은 workflow node 옵션일 뿐이며 권한 범위를 넓히거나 runtime data access를 부여하지 않는다.
- FR-009: Agent Builder의 KB/Collection picker와 workflow generation proposal은 builder actor의 권한뿐 아니라 intended execution subject/audience의 runtime availability를 safe warning으로 표시해야 한다. Hidden KB id/name/exact denied count는 표시하지 않는다.
- FR-010: Agent Builder가 자연어 workflow 생성 중 LLM node RAG 옵션을 제안할 때는 Knowledge RAG Recommendation Adapter를 사용한다. Builder는 Knowledge DB, permission row, source ACL row를 직접 조합하지 않는다.
- FR-011: 초기 recommendation 결과는 KB 단위로 materialize된다. Builder UI는 Collection 맥락을 safe `source_collection_summary`로 설명할 수 있지만, 현재 LLM node draft에는 `knowledgeBases` 중심으로 저장한다.

## Policies And Edge Cases

- 생성된 workflow도 일반 workflow와 동일한 RBAC, audit, organization scope 규칙을 적용한다. 생성 경로라고 해서 권한 판정을 우회하지 않는다.
- 프롬프트와 생성 결과에 secret 원문이 포함되지 않도록 한다.
- 생성 실패 또는 해석 불가능한 프롬프트는 빈 캔버스가 아니라 명시적 실패 안내로 처리한다.
- Knowledge-backed workflow generation이나 workflow 실행 시점 RAG 실행에서 collection/KB 후보를 사용할 때는 권한 helper가 만든 safe candidate set만 LLM에 전달한다. Execution subject가 없는 MVP runtime은 [ADR-0018](../../decisions/ADR-0018-workflow-rag-anonymous-public-only-runtime.md)에 따라 public collection 소속 KB만 후보로 사용한다. Collection visibility는 authenticated subject 기반 child KB content access를 의미하지 않는다 ([ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)).
- Knowledge Skill을 사용하더라도 raw skill body, hidden source reference, raw source title/path/url, restricted document list, raw prompt/completion/provider response를 LLM context, audit, trace에 넣지 않는다 ([ADR-0015](../../decisions/ADR-0015-knowledge-skill-context-routing-boundary.md)).
- Stale/review-required skill은 workflow 생성 제안에서 remediation 안내로 표시할 수 있지만 운영 실행 시점 RAG procedure로 자동 선택하지 않는다.
- Workflow Playground가 별도 실험 공간인지 canvas와 통합되는지, draft/unpublished skill을 workflow 테스트에 붙일 수 있는지, 배포 승인 요청에서 skill binding을 어떻게 검토할지는 아직 확정하지 않는다.
- Agent Builder나 A/B 테스트 UI가 `general RAG` baseline을 제공하더라도 운영 실행에서는 KB permission/source ACL/final evidence gate를 우회할 수 없다. General mode는 authorized resource 안에서 넓게 검색하는 mode이고, task-aware mode는 같은 authorized resource 안에서 더 정밀하게 후보를 줄이는 mode다.
- A/B 테스트와 trace side panel은 raw source title/path/url, 권한 없는 문서명/ID, raw prompt/completion을 표시하지 않는다. 필요한 비교값은 RAG strategy summary와 token/cost/latency summary로 제한한다.
- Query rewrite와 evidence sufficiency 옵션을 제안하더라도 raw rewritten query, hidden source reference, 권한 없는 문서명/ID는 Builder prompt, trace, audit에 넣지 않는다.
- LLM-assisted query rewrite, code-bearing skill, draft skill publication UX는 별도 승인 전까지 자동 제안/운영 실행에 포함하지 않는다.
- Builder가 recommendation 실패 또는 no recommendation을 받으면 기본적으로 사용자 확인 필요 상태로 둔다. 자동으로 RAG 없는 LLM node를 생성하는 fallback은 별도 Builder 정책 gate가 닫힌 경우에만 허용한다.

## Open Questions

- 생성 가능한 노드 타입 범위: 전체 허용 vs 안전한 부분집합(allowlist) — PRD Open Question과 연결.
- 생성 시 LLM 호출의 credential은 누구 것을 사용하는지(요청 빌더의 credential vs 플랫폼 공용).
- Knowledge tool이 auto collection 또는 multi-KB mode를 지원할 때, mixed hidden/denied/success 후보를 어떻게 사용자에게 설명할지.
- Skill authoring, test, publication/approval과 Agent Builder workflow generation 권한을 어떤 UI와 API로 연결할지.
- Workflow Playground와 canvas 작업 공간/사용 공간을 분리할지 통합할지, skill binding을 어느 단계에서 편집/검토할지.
