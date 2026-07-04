# Admin Dashboard Requirements

Status: Draft
Related Features: auth, organization, audit-tracing, cost-optimizer

## Purpose

이미 축적되는 `audit_logs`, `llm_usage_logs`, `workflow_runs` 데이터를 플랫폼 관리자와 감사자가 조회하는 관리자 화면을 제공한다. [PRD](../../PRD.md)의 FR-011~FR-015를 담당한다. 데이터 수집 경로는 구현돼 있으므로 이 feature의 범위는 조회/집계 UI와 그 권한 경계, 그리고 권한 신청의 관리자 측 처리(목록 조회/승인/거절)다.

권한 신청의 제출(신청자 측 차단 안내와 신청 폼)은 [organization](../organization/requirements.md) 범위(PRD FR-041)이고, workflow 예산의 설정/수정은 예산 관리 feature 범위(PRD FR-051, 문서 TBD)다. 이 feature는 그 결과 데이터를 조회하고 처리하는 표면이다.

## User Stories

- 플랫폼 관리자로서, 누가 언제 무엇을 했는지 audit log를 검색하고 개별 기록의 상세를 확인하고 싶다.
- 플랫폼 관리자로서, workflow별 LLM 사용량과 비용을 확인해 비용이 큰 workflow를 찾고 싶다.
- 플랫폼 관리자로서, 멤버의 workflow 생성/배포 권한 신청을 확인하고 승인/거절하고 싶다.
- 플랫폼 관리자로서, 이번 달 조직 LLM 비용과 예산 위험 workflow 비율을 한눈에 확인하고 싶다.
- 감사자로서, 관리 권한 없이도 감사 목적의 audit 조회를 하고 싶다.

## Functional Requirements

- FR-011: audit log를 행위자, action, 대상, 기간으로 검색/필터링하고, 개별 로그의 actor, action, target, status, timestamp를 상세 조회한다. action은 [ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)의 canonical action을 기준으로 하며, "workflow 차단" 같은 사용자 친화 라벨이 필요하면 canonical action에서 파생해 표시한다.
- FR-012: workflow별 LLM 사용량/비용을 집계해 표시한다. 원천은 `llm_usage_logs`다. 기본 조회 기간은 이번 달이고, 시작/끝 기간 필터를 제공한다. 목록은 비용 내림차순 정렬을 제공해 비용이 큰 workflow를 바로 찾을 수 있게 한다. 비용 집계 표시까지가 이 feature의 범위이며, 모델 비교/최적화 실행은 workflow 문맥의 [cost-optimizer](../cost-optimizer/requirements.md) 범위다 — 대시보드는 해당 workflow로 이동하는 진입만 제공한다.
- FR-013 (후순위): 차단 이벤트를 비정상 접근 시도로 표시한다. 현재 데모 시나리오에서 사용하지 않으며, 구현이 완료되면 PRD 시나리오 2와 함께 복원한다. 복원 시 두 단계로 구현한다.
  - 1단계: `permission.denied`, `auth.permission_denied` 등 차단 이벤트를 판정 로직 없이 목록으로 나열한다. 조직 scope 밖 접근은 404로 숨기고 audit을 기록하지 않으므로 목록에 포함되지 않는다 ([ADR-0010](../../decisions/ADR-0010-resource-access-403-404-policy.md)).
  - 2단계: 관리자 페이지 기능(FR-011, FR-012, FR-014, FR-015) 구현이 완료된 뒤 횟수 임계값/패턴 기반 판정으로 고도화한다.
- FR-014: workflow 생성/배포 권한 신청 목록을 조회하고 승인/거절한다. 목록에는 요청자, 요청 권한, 신청 사유를 표시한다. 요청 권한의 실체는 조직 수준 App 생성 능력(`app.create`)이며, 원천은 `permission_requests` 테이블이다 ([ADR-0014](../../decisions/ADR-0014-permission-request-and-app-creation-permission.md)). 승인 시 요청된 권한이 부여되고, 신청 제출/승인/거절은 canonical action `permission_request.created`/`permission_request.approved`/`permission_request.rejected`로 audit에 기록한다 (PRD FR-042, [ADR-0008](../../decisions/ADR-0008-audit-action-naming-standard.md)).
- FR-015: 조직의 이번 달 LLM 비용 합계와 예산 위험 workflow 비율을 요약해 표시한다. 예산 사용률(당월 비용 / 예산)이 90% 이상이면 위험, 100%를 초과하면 초과로 판정한다. 부적절한 접근/행동 탐지 건수 요약은 후순위 구현 항목이다 (FR-013과 함께 복원).

## Policies And Edge Cases

- 대시보드 조회 자체에도 서버(Gateway) 권한 판정이 필요하다 (NFR-001). audit 검색/상세(FR-011)는 audit auth_state `auditor` 이상, raw payload 접근은 `raw_auditor` 이상과 trace visibility policy를 따른다.
- 비용/예산 요약(FR-012, FR-015)과 권한 신청 목록/승인/거절(FR-014)은 organization owner/manager 전용이다. `auditor`/`raw_auditor`는 audit 조회(FR-011)만 접근할 수 있다.
- 조회 범위는 `X-Organization-Id` 요청 organization scope 안으로 제한한다 ([ADR-0009](../../decisions/ADR-0009-active-organization-header-context.md), NFR-002).
- audit metadata의 raw payload, secret 계열 값은 대시보드 응답에 노출하지 않는다 (NFR-004).
- 권한 신청 승인은 신청자에게 `user_app_creation_permissions` row를 생성해 조직 수준 App 생성 능력을 부여한다 ([ADR-0014](../../decisions/ADR-0014-permission-request-and-app-creation-permission.md)). 승인 audit은 `permission_request.approved`(신청 처리)와 `user_app_creation_permission.created`(권한 부여)를 각각 기록한다. 배포 권한은 생성자에게 자동 부여되는 workflow manager permission으로 따라오므로 별도 부여가 없다.
- 이미 처리된(승인/거절) 권한 신청에 대한 중복 처리 요청은 거부한다.
- 승인 시점에 신청자가 조직의 active member가 아니면(제거/정지) 승인을 거부한다. 권한 부여와 부여 audit은 발생하지 않는다.
- 예산이 설정되지 않은 workflow는 예산 위험/초과 판정 대상에서 제외한다.
- 시간대 규칙: 저장은 UTC(timestamptz) 그대로 두고, "이번 달" 경계와 예산 위험/초과 판정 같은 집계 경계는 KST(Asia/Seoul) 고정으로 계산한다. FR-011/FR-012의 기간 필터 입력도 KST 기준으로 해석한다. 개별 timestamp의 화면 표시만 사용자 로컬 시간대로 렌더링한다.
- 기간 필터와 집계 경계는 반개구간 `[start, end)`로 판정한다. 시작 시각과 정확히 같은 row는 포함하고, 끝 시각과 정확히 같은 row는 제외한다. 연속한 두 기간을 이어 붙여도 row가 중복되거나 누락되지 않는다.
- 검색 결과가 없는 기간/필터 조합은 빈 목록 정상 응답으로 처리한다.
- 비용 통화는 USD다 (LLM provider 크레딧이 USD 기준). 예산(PRD FR-051)의 통화도 USD를 전제하며, 이 전제는 예산 관리 feature 문서 작성 시 함께 확정한다.
- 비용 표시 자릿수: 노드/단건 상세는 소수점 6자리, workflow별 집계와 조직 합계는 소수점 2자리로 표시한다. 집계는 원본 정밀도(`NUMERIC(10,6)`)로 합산하고 반올림은 표시 직전에 한 번만 적용한다. 예산 사용률의 위험/초과 판정(FR-015)은 반올림 전 값으로 계산한다.
- 비용 집계에서 `total_cost`가 NULL인 row는 0으로 합산한다. 현재 기록 경로는 비용을 산정하지 못해도 NULL이 아니라 `0.0`을 기록하므로, NULL 처리는 legacy/예외 row 방어 목적이다.
- 알려진 한계 (수용): 가격 정보가 없는 모델의 호출은 `total_cost=0.0`으로 기록되어 "실제 비용 0"과 "가격 미산정"이 구분되지 않고, `llm_models`에 등록되지 않은 모델의 호출은 usage log 자체가 남지 않는다. 두 경우 모두 비용 합계가 실제보다 낮게 표시될 수 있다. 미산정 구분 기록(기록 경로 변경)은 이 feature 범위 밖이다.

## Open Questions

- FR-013 2단계 고도화의 판정 기준(차단 횟수 임계값, 패턴 정의, 조회 시점 집계 vs 백그라운드 탐지) — 고도화 착수 시 결정. PRD Open Question과 연결.
- FR-015 예산 위험 workflow 비율의 분모 (조직 전체 workflow vs 예산이 설정된 workflow). 예산 데이터 원천은 예산 관리 feature 문서(FR-051, TBD) 확정 시 함께 정한다.
