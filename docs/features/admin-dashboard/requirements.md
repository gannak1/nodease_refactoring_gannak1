# Admin Dashboard Requirements

Status: Draft
Related Features: auth, organization, audit-tracing, cost-optimizer

## Purpose

이미 축적되는 `audit_logs`, `llm_usage_logs`, `workflow_runs` 데이터를 플랫폼 관리자와 감사자가 조회하는 UI를 제공한다. [PRD](../../PRD.md)의 FR-011~FR-014를 담당한다. 데이터 수집 경로는 구현돼 있으므로 이 feature의 범위는 조회/집계 UI와 그 권한 경계다.

## User Stories

- 플랫폼 관리자로서, 누가 언제 무엇을 했는지 audit log를 검색하고 싶다.
- 플랫폼 관리자로서, workflow별 LLM 사용량과 비용을 확인해 비용이 큰 workflow를 찾고 싶다.
- 플랫폼 관리자로서, 권한 차단 같은 비정상 접근 시도를 확인하고 필요하면 해당 유저를 비활성화하고 싶다.
- 감사자로서, 관리 권한 없이도 감사 목적의 조회를 하고 싶다.

## Functional Requirements

- FR-011: audit log를 행위자, action, 대상, 기간으로 검색/필터링한다. action은 [ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)의 canonical action을 기준으로 한다.
- FR-012: workflow별 LLM 사용량/비용을 집계해 표시한다. 원천은 `llm_usage_logs`다. 비용 집계 표시까지가 이 feature의 범위이며, 모델 비교/최적화 실행은 workflow 문맥의 [cost-optimizer](../cost-optimizer/requirements.md) 범위다 — 대시보드는 해당 workflow로 이동하는 진입만 제공한다.
- FR-013: `permission.denied` 등 차단 이벤트를 비정상 접근 시도로 표시한다.
- FR-014: 관리자가 유저를 비활성화할 수 있다. 기존 `deactivated_at` column을 사용하고, 비활성 유저는 권한 평가에서 거부된다.

## Policies And Edge Cases

- 대시보드 조회 자체에도 권한이 필요하다. audit 조회는 `auditor`/`manager`, raw payload 접근은 `raw_auditor` 기준을 따른다.
- 조회 범위는 요청 organization scope 안으로 제한한다.
- audit metadata의 raw payload, secret 계열 값은 대시보드에 노출하지 않는다.
- 유저 비활성화는 그 자체를 audit log로 기록한다.

## Open Questions

- "비정상 접근"의 판정 기준(단순 차단 이벤트 나열 vs 횟수 임계값/패턴) — PRD Open Question과 연결.
- 비용 집계의 기간 단위와 통화 표시 기준.
