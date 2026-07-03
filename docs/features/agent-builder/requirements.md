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
- FR-004: Agent가 사내 지식을 사용할 때는 Knowledge feature의 collection routing/KB permission/source ACL helper 결과만 사용한다. Agent나 LLM planner가 raw permission row, raw source ACL, hidden KB 목록을 직접 해석하지 않는다.
- FR-005: Workflow runtime에서 Agent/LLM node가 RAG를 호출할 때는 run context의 명시적인 execution subject를 Knowledge service에 전달한다. Execution subject가 없거나 모호하면 workflow owner 권한으로 fallback하지 않고 preflight 실패로 처리한다.

## Policies And Edge Cases

- 생성된 workflow도 일반 workflow와 동일한 RBAC, audit, organization scope 규칙을 적용한다. 생성 경로라고 해서 권한 판정을 우회하지 않는다.
- 프롬프트와 생성 결과에 secret 원문이 포함되지 않도록 한다.
- 생성 실패 또는 해석 불가능한 프롬프트는 빈 캔버스가 아니라 명시적 실패 안내로 처리한다.
- Knowledge-backed Agent answer나 workflow generation에서 collection/KB 후보를 사용할 때는 권한 helper가 만든 safe candidate set만 LLM에 전달한다. Collection visibility는 child KB content access를 의미하지 않는다 ([ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)).
- Agent Builder나 A/B 테스트 UI가 `general RAG` baseline을 제공하더라도 production 실행에서는 KB permission/source ACL/final evidence gate를 우회할 수 없다. General mode는 authorized resource 안에서 넓게 검색하는 mode이고, task-aware mode는 같은 authorized resource 안에서 더 정밀하게 후보를 줄이는 mode다.
- A/B 테스트와 trace side panel은 raw source title/path/url, 권한 없는 문서명/ID, raw prompt/completion을 표시하지 않는다. 필요한 비교값은 RAG strategy summary와 token/cost/latency summary로 제한한다.

## Open Questions

- 생성 가능한 노드 타입 범위: 전체 허용 vs 안전한 부분집합(allowlist) — PRD Open Question과 연결.
- 생성 시 LLM 호출의 credential은 누구 것을 사용하는지(요청 빌더의 credential vs 플랫폼 공용).
- Knowledge tool이 auto collection 또는 multi-KB mode를 지원할 때, mixed hidden/denied/success 후보를 어떻게 사용자에게 설명할지.
