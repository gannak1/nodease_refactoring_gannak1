# LLMOps Gateway

## 왜 중심 기능인가

메모에서 가장 반복적으로 나온 요구는 LLMOps Gateway를 제품의 중심에 두라는 것이다. 기업에서 LLM을 쓰면 단순 호출보다 운영 문제가 더 중요해진다.

- 어떤 모델을 썼는가?
- 누가 호출했는가?
- 비용은 얼마인가?
- 지연시간은 어느 정도인가?
- 실패했을 때 fallback이 있는가?
- 민감정보가 포함됐는가?
- 정책 위반 요청이 차단됐는가?
- 배포 후 사용량과 비용을 추적할 수 있는가?

## Gateway의 책임

| 책임 | 근거 수준 | 설명 |
| --- | --- | --- |
| Model Access Control | 원문 직접 | 사용자/역할/프로젝트별 사용 가능 모델 제한 |
| Tracing | 원문 직접 | 요청, 응답, 프롬프트, 모델, 노드, 워크플로우 연결 추적 |
| Cost Tracking | 원문 직접 | 토큰과 모델 단가 기반 비용 계산 |
| Caching | 원문 직접/후보 | 원문에 cost saving 예시로 등장. 실제 방식은 리서치 필요 |
| Policy Enforcement | 원문 파생 | 데이터 등급, PII, 비용 한도, 승인 정책 적용 |
| Routing | 원문 파생 | 비용, 품질, 지연시간 조건에 따라 모델 선택 |
| Evaluation Hook | 원문 파생 | 응답 품질 평가와 A/B 테스트 결과 수집 |
| Unified Interface | LLM Gateway 일반 기능 | 여러 모델 공급자를 동일 인터페이스로 호출 |
| Fallback | LLM Gateway 일반 기능 | 호출 실패 또는 품질 미달 시 대체 모델 실행 |
| Rate Limit | LLM Gateway 일반 기능 | 사용자/프로젝트/모델별 호출량 제한 |

## 요청 단위로 남겨야 할 정보

```text
LLM Request Trace
  request_id
  workflow_id
  node_id
  user_id
  organization_id
  model_provider
  model_name
  prompt_version
  input_token_count
  output_token_count
  estimated_cost
  latency_ms
  status
  error_type
  data_classification
  pii_detected
  policy_decision
  cache_hit
  fallback_used(optional)
  created_at
```

## UI에 보여줄 정보

### 워크플로우 캔버스

- 노드별 모델명
- 비용
- 토큰 수
- 지연시간
- 성공/실패 상태
- 정책 경고 또는 차단 상태

### Gateway 대시보드

- 모델별 총 비용
- 프로젝트별 총 비용
- 사용자별 호출량
- 실패율
- 평균 지연시간
- 캐시 적중률
- fallback 발생 횟수, 구현 시
- 정책 차단 횟수

### 추천 패널

- 더 싼 모델 추천
- 더 빠른 모델 추천
- 캐싱 가능 노드 추천
- 프롬프트 토큰 절감 제안
- 비용 한도 초과 예상 경고

## 정책 예시

```text
Policy Examples
  - PII 포함 입력은 외부 모델 호출 금지
  - HR 데이터는 HR 그룹만 실행 가능
  - 무료 사용자 또는 특정 팀은 고가 모델 사용 금지
  - 월 비용 한도 초과 시 실행 차단
  - Confidential 데이터는 추가 승인 후 실행
  - 실패율이 높은 모델은 fallback 적용 검토
```

## MCP Gateway와의 관계

LLMOps Gateway는 모델 호출을 운영하고 통제하는 계층이다. MCP Gateway는 외부 도구, 사내 시스템, 데이터 소스, 커스텀 액션을 연결하는 계층이다.

두 기능은 분리할 수 있지만, 데모에서는 다음처럼 연결하면 설득력이 높다.

```text
Agent / Workflow Node
  -> MCP Gateway
      -> Internal DB / Slack / Jira / GitHub / Approval System
  -> LLMOps Gateway
      -> Model Routing / Policy / Cost / Audit
```

## 리서치해야 할 질문

- LLM Gateway/LLMOps 제품들은 어떤 기능을 공통으로 제공하는가?
- 기업은 LLM Gateway 도입 후 어떤 운영 문제가 새로 생기는가?
- 비용 최적화와 품질 보장을 동시에 하려면 어떤 평가 루프가 필요한가?
- Gateway 로그가 많아질 때 저장/검색/보존 정책은 어떻게 가져가야 하는가?
