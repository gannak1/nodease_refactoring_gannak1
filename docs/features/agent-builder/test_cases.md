# Agent Builder Test Cases

Status: Draft
Verified Against: TBD

[PRD](../../PRD.md) 시나리오 1(1~3, 5단계)과 FR-001~FR-003을 검증한다. 비용 최적화(4단계)는 [cost-optimizer/test_cases.md](../cost-optimizer/test_cases.md)에서 다룬다.

## Unit Tests

- (FR-001) 프롬프트 → 그래프 생성 결과가 유효한 workflow graph 구조다: 노드 타입이 허용 목록 안에 있고, 엣지가 존재하는 노드만 참조하며, 트리거 노드에서 도달 가능한 그래프다.
- (FR-001) 생성된 graph가 기존 `workflows.graph` 스키마로 저장 가능한 형태다 (별도 변환 없이 저장 API에 전달 가능).
- (FR-003) credential/모델/권한 부족 판정 로직이 부족 항목 목록을 정확히 반환한다.

## API Tests

- (FR-001) 생성 요청 성공 시 노드 그래프를 반환한다. 대표 프롬프트: "고객 문의 이메일을 받아서 자동으로 분류하고 답변해줘" → Webhook/LLM/Condition/Mail 계열 노드 포함.
- (FR-003) 사용 가능한 credential이 없는 상태에서 생성 요청 → 부족한 credential/모델을 명시한 사전 안내 응답.
- 유효하지 않은 `X-Organization-Id` header → 실행 전 검증 오류로 거부.
- 해석 불가능한 프롬프트(예: 빈 문자열, 자동화와 무관한 요청) → 빈 workflow를 만들지 않고 명시적 실패 응답.

## E2E Tests

- **시나리오 1 완주**: 프롬프트 입력 → 그래프 초안이 캔버스에 표시 → 노드 설정 수정 → 테스트 실행 성공 → 배포. 사전 조작(미리 만들어둔 workflow) 없이 완주한다.
- 배포 완료 시 `audit_logs.action='workflow.deploy'` 기록이 남는다.
- 생성된 workflow가 기존 캔버스 편집기에서 일반 workflow와 동일하게 편집/실행된다 (FR-002: 별도 편집 경로 없음).

## Permission Tests

- workflow 생성 권한이 없는 사용자(viewer/operator)의 생성 요청 → `403 permission.denied` + audit 기록.
- 생성된 workflow는 일반 workflow와 동일한 RBAC를 받는다: 권한 없는 팀원의 실행 시도 → 403, 다른 조직에서의 접근 → 404.
- 생성 경로가 credential `use` 권한 판정을 우회하지 않는다: 권한 없는 credential은 생성 결과에 배정되지 않는다.

## Edge Cases

- 프롬프트에 secret처럼 보이는 값(API key 형식 문자열)이 포함돼도 로그/trace/audit metadata에 원문이 남지 않는다.
- 생성 중 LLM 호출 실패 → 부분 생성물 없이 실패 안내, workflow row가 생성되지 않는다.
- 허용 목록 밖 노드 타입을 유도하는 프롬프트 → 해당 노드 없이 생성되거나 명시적으로 거절된다 (허용 범위는 PRD Open Question 확정 후 고정).
