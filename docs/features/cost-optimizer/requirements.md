# Cost Optimizer Requirements

Status: Draft
Related Features: workflow, llm-credentials, observability

## Purpose

Cost Optimizer는 workflow 안의 LLM 노드 비용을 줄이기 위한 기능이다.

이 기능의 첫 번째 목표는 workflow 전체를 A/B 테스트하는 것이 아니라, 사용자가 선택한 특정 LLM 노드 하나에 대해 현재 설정과 후보 설정을 같은 입력 기준으로 비교할 수 있게 하는 것이다.

사용자는 비교 결과를 보고 더 저렴하면서도 결과가 충분히 괜찮은 설정을 선택해 현재 LLM 노드에 적용할 수 있어야 한다.

## Problem

LLM 노드는 workflow 실행 비용의 대부분을 차지할 수 있다.

현재 사용자는 실행 로그에서 토큰과 비용을 확인할 수 있지만, 다음 질문에 바로 답하기 어렵다.

- 이 LLM 노드를 더 저렴한 모델로 바꿔도 결과가 유지되는가?
- 프롬프트를 줄이면 비용이 얼마나 줄어드는가?
- `max_tokens`를 낮춰도 필요한 답변이 나오는가?
- 같은 입력에서 후보별 비용, 토큰, 실행 시간, 출력 결과가 어떻게 다른가?
- 더 저렴한 후보를 선택했을 때 뒤쪽 노드가 깨지지 않는가?
- 비교한 후보를 현재 LLM 노드 설정에 안전하게 적용할 수 있는가?

Cost Optimizer는 이 질문에 답하기 위한 기능이다.

## User Stories

- 빌더로서, workflow 안의 특정 LLM 노드를 선택해 비용 비교를 실행하고 싶다.
- 빌더로서, 현재 LLM 노드 설정과 후보 설정을 같은 입력으로 비교하고 싶다.
- 빌더로서, 후보별 비용, 토큰, 실행 시간, 출력 결과를 한 화면에서 보고 싶다.
- 빌더로서, 더 저렴하지만 결과가 충분한 후보를 현재 LLM 노드 설정에 적용하고 싶다.
- 빌더로서, 선택한 후보의 출력이 다음 노드에서 사용할 수 있는 형태인지 확인하고 싶다.
- 운영자로서, 비용 최적화 비교 실행에서 발생한 LLM 비용도 일반 실행 비용처럼 기록되기를 원한다.

## Functional Requirements

Functional Requirement 상태는 다음 기준으로 구분한다.

- `구현 완료`: 현재 코드에서 동작이 확인된 요구사항이다.
- `진행중`: 일부 기반은 있으나 Cost Optimizer 1차 구현 요구사항을 완전히 만족하지 못한 상태다.
- `미완료`: 요구사항은 정의됐지만 아직 구현되지 않은 상태다.

상태 상세는 현재 어디까지 진행됐는지를 더 구체적으로 표시한다.

- `문서화`: 요구사항만 문서화된 상태다.
- `구현 기반 있음`: 기존 코드에 재사용 가능한 기반은 있으나 Cost Optimizer 전용 구현은 없는 상태다.
- `구현 필요`: 코드 구현이 필요하다.
- `후속 기능`: 1차 구현 필수 범위가 아니라 후속 이슈로 분리할 기능이다.
- `버그`: 구현은 있으나 요구사항을 만족하지 못하는 결함 상태다.

시연 중요도는 다음 3단계로 구분한다.

- `P1`: 시연 핵심 흐름에 필수다. 없으면 Cost Optimizer 기능 설명이 어렵다.
- `P2`: 시연 품질과 설득력에 중요하다. 없으면 동작은 가능하지만 완성도가 낮아 보인다.
- `P3`: 장기 사용성과 확장성에 중요하다. 시연 필수는 아니며 후속으로 분리할 수 있다.

| ID | 기능명 | 시연 중요도 | 상태 | 상태 상세 | 요약 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | LLM 노드 단위 A/B 테스트 진입 | P1 | `미완료` | `문서화` | LLM 노드 상세 화면에서 해당 노드 기준 A/B 테스트를 시작한다. |
| FR-002 | A baseline 실행 로그 선택 | P1 | `미완료` | `문서화` | 최신 실행 로그 또는 사용자가 고른 이전 실행 로그를 A 기준으로 사용한다. |
| FR-003 | 비교 가능한 옵션 | P1 | `미완료` | `문서화` | 모델, prompt, `max_tokens`, `temperature`, 출력 형식을 바꿔 비교한다. |
| FR-004 | 동일 입력 기준 비교 | P1 | `미완료` | `문서화` | A baseline의 target LLM node 입력을 B 후보 실행 입력으로 고정한다. |
| FR-005 | 하이브리드 비교 | P1 | `미완료` | `문서화` | A는 과거 로그로 고정하고 B만 새 설정으로 실행해 비교한다. |
| FR-006 | A/B 비교 화면 | P1 | `진행중` | `구현 기반 있음` | A baseline, B candidate, Inspector 3영역으로 비용/토큰/trace를 비교한다. |
| FR-007 | Downstream 호환성 검증 | P1 | `미완료` | `문서화` | baseline graph와 현재 graph의 downstream 호환성을 3상태로 표시한다. |
| FR-008 | 후보 적용 | P1 | `미완료` | `문서화` | 사용자가 선택한 B 후보 설정을 현재 target LLM node draft에 적용한다. |
| FR-009 | 비용 기록 | P1 | `진행중` | `구현 기반 있음` | 비교 실행에서 발생한 LLM 비용도 usage log에 남긴다. |
| FR-010 | 권한 | P1 | `진행중` | `구현 기반 있음` | A/B 테스트와 후보 적용은 builder 이상 권한이 있는 사용자만 수행한다. |
| FR-011 | 모델 라우팅과 최적화 에이전트 후속 확장 | P3 | `미완료` | `후속 기능` | 모델 라우팅과 최적화 에이전트는 후속 기능으로 분리한다. |

### FR-001. LLM 노드 단위 A/B 테스트 진입

Cost Optimizer의 비교 단위는 workflow 전체가 아니라 특정 LLM 노드 하나다.

- 사용자는 workflow 편집 화면에서 LLM 노드를 선택해 비용 비교를 시작할 수 있어야 한다.
- LLM 노드 상세 화면에는 이 노드에 대해 `A/B 테스트하기` 액션이 있어야 한다.
- 비교 대상은 `llmNode`로 제한한다.
- LLM 노드가 아닌 노드에서는 비용 비교를 실행하지 않는다.

### FR-002. A baseline 실행 로그 선택

사용자는 A/B 테스트를 시작할 때 A 기준이 되는 baseline 실행 로그를 선택해야 한다.

A baseline은 특정 실행 시점의 target LLM node 입력, 출력, 설정, 비용, 토큰, trace를 가진 비교 기준이다.

A baseline의 canonical id는 `workflow_node_runs.id`다. `workflow_runs`는 baseline이 속한 전체 실행 컨텍스트이고, `llm_usage_logs`는 비용/토큰/모델 원천이며, `trace_payloads`는 redaction-safe input/output preview와 trace 존재 여부의 원천이다.

사용자는 다음 두 방식 중 하나로 A baseline을 정할 수 있어야 한다.

- 최신 실행 로그로 비교하기
- 이전 실행 로그 선택해서 비교하기

`최신 실행 로그로 비교하기`는 target LLM node의 가장 마지막 실행 로그를 A baseline으로 사용한다.

`이전 실행 로그 선택해서 비교하기`는 로그 선택 화면을 열고, 사용자가 특정 실행 로그를 직접 고르게 한다.

로그 선택 화면은 다음 정보를 제공해야 한다.

- 실행 시각
- 실행 상태
- 사용 모델
- target LLM node 비용
- target LLM node 토큰
- target LLM node 실행 시간
- 입력 preview
- 출력 preview
- trace 존재 여부
- downstream 호환성 상태

로그 선택 화면은 검색, 필터링, 정렬을 지원해야 한다. 필요한 경우 이를 위한 API를 새로 추가하는 것을 허용한다.

baseline input을 복원할 수 없는 실행 로그도 목록에는 표시한다. 다만 이런 row는 `비교 불가` 상태로 표시하고 A/B 비교 실행은 막는다.

### FR-003. 비교 가능한 옵션

사용자는 B 후보를 구성할 때 여러 설정을 바꿔가며 최적화할 수 있어야 한다.

1차 구현에서 후보별로 비교할 수 있는 옵션은 다음과 같다.

- 모델
- system prompt
- user prompt
- assistant prompt
- `max_tokens`
- `temperature`
- 출력 형식

출력 형식은 downstream 안정성에 영향을 줄 수 있으므로 비용 비교 옵션에 포함한다. 예를 들어 자유 텍스트 출력과 JSON 출력을 비교할 수 있어야 한다.

자동 모델 추천, 모델 라우팅, RAG strategy 비교, Knowledge Skill version 비교는 1차 구현의 필수 범위는 아니지만 후속 확장 후보로 둔다.

### FR-004. 동일 입력 기준 비교

후보 B는 A baseline 실행 로그의 target LLM node 입력을 기준으로 실행되어야 한다.

같은 입력 기준 비교가 필요한 이유는 후보 간 결과 차이가 입력 차이 때문인지 설정 차이 때문인지 섞이지 않게 하기 위해서다.

A baseline은 이미 실행된 로그이므로 A를 다시 실행하지 않아도 된다.

B 후보는 A baseline의 입력을 사용해 새 설정으로 실행한다.

A baseline의 target LLM node input을 복원할 수 없으면 B 후보 실행을 시작하지 않는다. 이 경우 사용자는 해당 실행 로그가 목록에 보이더라도 비교 기준으로 선택할 수 없거나, 선택 후 compare 실행 전에 차단 안내를 받아야 한다.

### FR-005. 하이브리드 비교

Cost Optimizer는 하이브리드 비교 방식을 사용한다.

하이브리드 비교란, 비교 대상 LLM 노드 앞단의 입력은 baseline 실행 로그에서 가져오고, 그 동일한 입력을 후보 LLM 설정에 넣어 비교하는 방식이다.

```text
A baseline 로그 선택
→ A의 target LLM node 입력 고정
→ B 후보 설정 실행
→ 후보별 비용/토큰/시간/결과 비교
```

### FR-006. A/B 비교 화면

A/B 비교 화면은 baseline A와 candidate B를 나란히 비교할 수 있어야 한다.

기본 레이아웃은 3개 영역으로 구성한다.

- 왼쪽: A baseline
- 가운데: B candidate
- 오른쪽: Inspector

오른쪽 Inspector는 A 또는 B의 상세 trace와 비교 보조 정보를 볼 수 있는 영역이다.

Inspector에는 다음 정보를 표시할 수 있어야 한다.

- input
- output
- prompt/messages 요약
- token/cost/latency breakdown
- LLM usage trace
- RAG를 사용한 경우 참조한 문서 또는 retrieval summary
- error
- downstream 호환성 상태

기존 고급 설정, 지식 베이스 설정, 비교 설정은 A/B 화면 안의 상단 탭 또는 Inspector 탭으로 접근할 수 있어야 한다. 별도 패널을 계속 중첩해서 열어 화면이 복잡해지지 않게 한다.

각 후보 결과에는 다음 항목을 표시해야 한다.

- 후보 이름
- 모델
- 실행 상태
- 출력 결과 미리보기
- prompt tokens
- completion tokens
- total tokens
- estimated cost
- latency
- error message

비용이 낮더라도 출력 결과가 부적절하면 사용자가 선택하지 않을 수 있어야 한다.

현재 코드에는 workflow 실행 결과의 비용, 토큰, latency를 표시하는 기반 UI와 trace 조회 경로가 있다. 다만 LLM 노드 비용 비교 후보별 결과 화면은 아직 구현되지 않았다.

### FR-007. Downstream 호환성 검증

선택한 A baseline 로그의 downstream과 현재 target LLM node의 downstream이 다를 수 있다.

downstream이 달라지면 A/B 비교 자체는 가능하더라도, 그 비교 결과가 현재 workflow에서 그대로 의미 있다고 보기 어렵다. 따라서 Cost Optimizer는 downstream 호환성 상태를 사용자에게 명확히 알려야 한다.

downstream 호환성은 다음 3상태로 표시한다.

- `검증 가능`: baseline 실행 시점의 target node 이후 downstream 구조와 현재 downstream 구조가 동일하거나 호환된다.
- `주의 필요`: downstream 구조는 달라졌지만 target node의 바로 다음 소비 노드는 동일하거나 입력 계약이 유지된다.
- `검증 불가`: target node 이후 소비 노드가 바뀌었거나 필요한 입력 계약이 달라져 downstream 검증을 신뢰할 수 없다.

상태별 의미는 다음과 같다.

- `검증 가능`: A/B 결과와 downstream 계약 검증을 현재 workflow 판단에 사용할 수 있다.
- `주의 필요`: LLM output 비교는 가능하지만, 최종 적용 전 현재 workflow 테스트 실행으로 확인해야 한다.
- `검증 불가`: LLM output 비교만 참고할 수 있고, downstream 성공 여부는 현재 workflow에서 별도로 검증해야 한다.

1차 구현에서는 downstream 전체를 자동 실행하지 않는다.

대신 선택 후보의 LLM output이 다음 소비 노드의 필수 입력 계약을 만족하는지 검증한다.

예:

- 다음 노드가 변수 추출 노드라면 필요한 값을 추출할 수 있는지 확인한다.
- 다음 노드가 조건 분기 노드라면 조건에 필요한 값이 존재하는지 확인한다.
- 다음 노드가 응답/Slack 노드라면 템플릿에 필요한 변수가 채워질 수 있는지 확인한다.

Slack 전송, HTTP 요청, DB write처럼 외부 side effect가 있는 노드는 1차 구현에서 자동 실행하지 않는다.

### FR-008. 후보 적용

사용자는 비교 결과 중 하나를 선택해 현재 LLM 노드 설정에 적용할 수 있어야 한다.

- 적용 대상은 현재 workflow draft의 target LLM node다.
- 적용 가능한 값은 비교 가능한 옵션과 같다.
- 적용 후 사용자는 기존 workflow 저장/테스트 실행 흐름을 그대로 사용할 수 있어야 한다.

후보 적용 시 A baseline의 과거 설정을 현재 draft에 되돌리는 동작이 아니라, 사용자가 선택한 B 후보 설정을 현재 target LLM node에 적용하는 동작이다.

downstream 호환성 상태가 `주의 필요` 또는 `검증 불가`인 경우, 적용 전에 현재 workflow에서 추가 검증이 필요하다는 안내를 표시해야 한다.

### FR-009. 비용 기록

비교 실행에서 발생한 LLM 호출도 일반 workflow 실행과 동일하게 usage log에 기록되어야 한다.

기록 대상은 다음과 같다.

- workflow id
- node id
- model
- prompt tokens
- completion tokens
- total tokens
- cost
- latency
- status

비용 최적화 기능 자체의 비용이 숨겨지면 안 된다.

현재 코드에는 일반 workflow LLM 호출의 token, cost, latency를 `llm_usage_logs`와 workflow run 집계에 기록하는 기반이 있다. 다만 Cost Optimizer 비교 실행을 이 기록 경로와 어떻게 연결할지는 아직 구현해야 한다.

### FR-010. 권한

비용 비교와 후보 적용은 workflow를 수정할 수 있는 builder 이상 권한이 있는 사용자만 수행할 수 있다.

Cost Optimizer의 A/B 테스트는 단순 실행 기능이 아니라, LLM 노드 설정 후보를 만들고 현재 draft에 적용할 수 있는 편집 도구다. 따라서 실행 권한만 가진 사용자가 비용 비교를 수행할 수 있게 하지 않는다.

- builder 이상 권한이 없으면 A/B 테스트를 실행할 수 없다.
- builder 이상 권한이 없으면 후보를 현재 노드에 적용할 수 없다.
- 사용할 수 없는 credential/model 후보는 실행하지 않거나 실패 후보로 표시한다.

현재 코드에는 workflow 실행/수정 권한과 LLM credential 사용 권한 검증 기반이 있다. 다만 Cost Optimizer 전용 비교 실행과 후보 적용 API에 builder 이상 권한 정책을 연결하는 작업은 남아 있다.

### FR-011. 모델 라우팅과 최적화 에이전트 후속 확장

Cost Optimizer는 후속 기능으로 모델 라우팅과 최적화 에이전트를 다룰 수 있어야 한다.

모델 라우팅은 작업 난이도나 작업 유형에 따라 더 저렴한 모델 또는 더 강한 모델을 선택하는 기능이다.

가능한 모델 라우팅 방식은 다음과 같다.

- 수동 라우팅: 사용자가 노드별 모델을 직접 선택한다.
- 규칙 기반 라우팅: 분류, 요약, 단순 추출은 저렴한 모델을 쓰고 복잡한 추론이나 고위험 답변은 강한 모델을 쓴다.
- LLM 기반 라우팅: 앞단에서 작은 모델 또는 별도 판단기가 요청 난이도를 분류해 적절한 모델을 선택한다.

최적화 에이전트는 실행 로그와 A/B 비교 결과를 바탕으로 모델, 프롬프트, `max_tokens`, 출력 형식 같은 최적화 후보를 제안하는 기능이다.

최적화 에이전트는 후속 기능으로 추가한다. 에이전트는 자동 적용하지 않고 제안만 제공해야 한다.

## Policies And Edge Cases

- 비교 실행은 실제 LLM 호출이므로 비용이 발생할 수 있다.
- 한 후보가 실패해도 다른 후보 결과는 표시한다.
- 비용 정보가 없는 모델은 비용 비교 불가 상태로 표시한다.
- credential 원문, API key, encrypted config는 응답이나 화면에 표시하지 않는다.
- 비교 결과는 비용만으로 승자를 정하지 않는다. 사용자가 출력 결과를 보고 판단한다.
- downstream 계약 검증은 안전성 보조 기능이며, 전체 workflow 성공을 보장하지 않는다.
- 최종 검증은 기존 workflow 테스트 실행으로 수행할 수 있어야 한다.
- baseline input이 보관 기간 만료, redaction, retention, 저장 누락으로 복원되지 않는 경우 해당 baseline은 목록에 표시하되 비교 실행은 허용하지 않는다.

## Deferred Scope

다음 항목은 Cost Optimizer 방향에는 포함되지만, 1차 구현의 필수 범위에서는 제외하고 후속 기능으로 분리한다.

- workflow 전체 A/B 테스트
- 자동 품질 점수 산정
- LLM judge 기반 평가
- 자동 모델 추천
- 모델 라우팅
- 최적화 에이전트
- LLM response cache
- budget guardrail
- 실패 지점부터 partial rerun
- downstream 전체 자동 실행
- side-effect node dry-run 인프라
- RAG strategy A/B 테스트
- Knowledge Skill version/freshness 기반 비교

## Knowledge/RAG Compare Policies

이 섹션은 Cost Optimizer의 기존 1차 범위를 대체하지 않고, RAG 포함 workflow 비교가 추가될 때 필요한 Knowledge/RAG 경계를 정의한다.

- 비교 실행에도 workflow 실행 권한과 대상 credential의 `use` 권한이 필요하다.
- 비교 실행에서 발생한 LLM 호출도 usage/비용으로 기록한다. 최적화 기능 자체의 비용이 숨겨지면 안 된다.
- 후보 모델은 요청 organization에서 사용 가능한(verified credential-model relation이 있는) 모델로 제한한다.
- RAG 포함 비교에서 `general RAG` baseline을 사용하더라도 권한 없는 문서가 prompt, citation, trace, audit, 비교 UI에 들어가면 안 된다.
- 비교 리포트에는 context token estimate, retrieved chunk count, citation count, cost, latency, policy result, query rewrite 적용 여부, evidence sufficiency 결과, source tier summary 같은 safe summary만 표시한다. 권한 없는 문서명/ID, raw source metadata, raw rewritten query, raw prompt/completion, raw chunk content는 표시하지 않는다.
- Skill 기반 비교 리포트에도 raw skill body, hidden source refs, raw source title/path/url, restricted document list, raw eval fixture를 표시하지 않는다.
- `llm_assisted` query rewrite는 별도 승인 전까지 비교 변수로 사용하지 않는다. 승인 후 비교 변수로 삼으면 rewrite LLM call의 usage/cost도 비교 비용에 포함해야 한다.

## Open Questions

Open Question 중요도는 다음 3단계로 나눈다.

- `Priority 1`: 현재 기능 구현 또는 데모 핵심 흐름을 막는 결정이다. 구현 전에 먼저 정해야 한다.
- `Priority 2`: 데모 안정성과 후속 구현 품질에 영향을 준다. 현재 구현은 fallback으로 진행할 수 있지만 PR 전후로 정리해야 한다.
- `Priority 3`: 장기 사용성, 성능, 확장성 결정이다. 현재 구현을 막지는 않으며 후속 이슈로 분리할 수 있다.

| Priority | 영역 | Question | 왜 중요한가 | 결정 전 임시 처리 |
| --- | --- | --- | --- | --- |
| Priority 1 | baseline 로그 | 최신 실행 로그를 자동 선택할 때 실패 로그도 포함할지, 성공 로그만 사용할지 | 실패 로그를 baseline으로 삼으면 원인 분석에는 좋지만 일반 최적화 비교에는 혼란이 생길 수 있다 | 기본은 성공 로그 우선, 사용자가 필터로 실패 로그를 선택할 수 있게 한다 |
| Priority 1 | 이전 로그 선택 API | target LLM node 실행 로그를 비용/토큰/시간 기준으로 검색·필터·정렬하는 API를 별도로 둘지 | 기존 workflow run list만으로는 노드 기준 baseline 선택 UX를 만들기 어렵다 | 필요한 API 추가를 허용한다 |
| Priority 1 | downstream 호환성 | baseline 실행 시점 graph와 현재 graph의 호환성을 어떤 기준으로 판정할지 | 다운스트림이 바뀐 상태에서 비교 결과를 잘못 해석할 수 있다 | `검증 가능`, `주의 필요`, `검증 불가` 3상태로 표시한다 |
| Priority 1 | 비교 결과 저장 | 비교 결과를 저장할지, 화면에서만 보여줄지 | 저장 여부에 따라 DB/API/화면 이력이 달라진다 | 1차 구현에서는 화면 표시 중심으로 시작하고 usage log는 반드시 남긴다 |
| Priority 1 | 적용 방식 | 선택 후보를 draft에 바로 적용할지, versioning과 연결할지 | 사용자가 실수로 기존 설정을 잃을 수 있다 | 1차 구현에서는 draft에 적용하고 기존 저장/되돌리기 흐름을 따른다 |
| Priority 2 | downstream 계약 검증 | 1차 구현에서 어떤 다음 노드 타입까지 계약 검증할지 | 지원하지 않는 노드가 있으면 검증 결과를 신뢰하기 어렵다 | 변수 추출, 조건 분기, 응답/Slack 템플릿부터 검토한다 |
| Priority 2 | 실패 후보 처리 | 후보 하나가 실패했을 때 전체 비교를 실패로 볼지 | 비교 UX가 달라진다 | 실패 후보만 실패로 표시하고 나머지 후보 결과는 유지한다 |
| Priority 3 | 자동 추천 | 가격표 기반으로 후보 모델을 자동 추천할지 | 사용성은 좋아지지만 정책과 품질 판단이 필요하다 | 1차 구현에서는 사용자가 직접 후보를 만든다 |
| Priority 3 | 모델 라우팅 | 수동, 규칙 기반, LLM 기반 라우팅 중 어떤 방식을 먼저 제공할지 | 비용 절감 효과는 크지만 잘못 라우팅하면 품질 문제가 생긴다 | 후속 기능으로 분리한다 |
| Priority 3 | 최적화 에이전트 | 에이전트가 어떤 근거로 모델/프롬프트/파라미터 최적화 후보를 제안할지 | 추천 자체도 비용이 들고 잘못된 추천은 workflow 품질을 해칠 수 있다 | 후속 기능으로 분리하고 자동 적용은 금지한다 |
| Priority 3 | cache/budget | LLM cache와 budget guardrail을 1차 구현에 넣을지 | 실제 비용 절감 효과는 크지만 범위가 커진다 | 별도 follow-up 이슈로 분리한다 |
