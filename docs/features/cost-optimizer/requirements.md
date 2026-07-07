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
| FR-001 | LLM 노드 단위 A/B 테스트 진입 | P1 | `구현 완료` | `테스트 통과` | LLM 노드 상세 화면에서 해당 노드 기준 A/B 테스트 진입 액션과 availability 검증을 제공한다. |
| FR-002 | A baseline 실행 로그 선택 | P1 | `구현 완료` | `테스트 통과` | 최신 실행 로그 또는 사용자가 고른 이전 실행 로그를 A 기준으로 선택하는 API/UI 경로를 제공한다. |
| FR-003 | 비교 가능한 옵션 | P1 | `구현 완료` | `테스트 갱신 필요` | 모델, fallback 모델, 자동 라우팅 상태, prompt, Knowledge/RAG, 고급 파라미터, 출력 형식을 바꿔 비교한다. 작업 유형은 사용자 선택값으로 노출하지 않는다. |
| FR-004 | 동일 입력 기준 비교 | P1 | `구현 완료` | `테스트 통과` | A baseline의 target LLM node 입력을 B 후보 실행 입력으로 고정한다. |
| FR-005 | 하이브리드 비교 | P1 | `구현 완료` | `테스트 통과` | A는 과거 로그로 고정하고 B만 새 설정으로 실행해 비교한다. |
| FR-006 | A/B 비교 화면 | P1 | `구현 완료` | `테스트 통과` | A baseline, B candidate, Inspector 3영역으로 비용/토큰/trace를 비교하고, 결과 분석 화면에서 B 후보를 현재 노드에 적용해도 되는지 판단 요약을 제공한다. |
| FR-007 | Downstream 호환성 검증 | P1 | `구현 완료` | `테스트 통과` | baseline graph와 현재 graph의 downstream 호환성을 3상태로 판정하고 결과 분석 화면에 표시한다. warning/incompatible 후보는 적용 전 사용자 확인이 필요하다. |
| FR-008 | 후보 적용 | P1 | `구현 완료` | `테스트 통과` | 사용자가 성공한 B 후보 설정 전체를 현재 target LLM node draft에 적용한다. downstream warning 확인과 schema 실패 후보 차단을 제공한다. draft conflict 처리는 후속 보강 대상이다. |
| FR-009 | 비용 기록 | P1 | `구현 완료` | `테스트 통과` | 결과 분석 화면은 A/B 비용, prompt/completion/total token, latency를 표시한다. 비교 실행은 전용 experiment/candidate row로 저장되고 usage row가 candidate를 직접 참조한다. 과거 결과 재조회 API와 trace metadata retention 기준 정리를 제공한다. |
| FR-010 | 권한 | P1 | `구현 완료` | `UI/API 권한 기반 구현, 테스트 통과` | A/B 테스트와 후보 적용은 builder 이상 권한이 있는 사용자만 수행한다. compare/apply/history API와 모델/Knowledge 후보 사용 가능성 검증이 적용됐다. |
| FR-011 | 모델 라우팅과 최적화 에이전트 후속 확장 | P3 | `진행중` | `프론트 UI 기반 구현, 라우터 API 후속` | LLM 노드 상세 화면은 자동 라우팅 토글과 cold start/warming up/optimized 정책 안내를 제공한다. 실제 실행 시점 모델 라우터와 최적화 에이전트는 후속 기능으로 분리한다. |

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

Baseline 후보는 target LLM node가 성공적으로 완료된 `workflow_node_runs` 중 output preview와 usage summary를 모두 제공할 수 있는 기록만 포함한다. 실패한 node run, output preview가 없는 node run, usage summary가 없는 node run은 Cost Optimizer baseline 후보에서 제외하며, 실패 원인 분석이나 불완전한 실행 기록 확인은 실행 로그/trace 화면의 책임으로 둔다.

사용자는 다음 두 방식 중 하나로 A baseline을 정할 수 있어야 한다.

- 최신 실행 로그로 비교하기
- 이전 실행 로그 선택해서 비교하기

`최신 실행 로그로 비교하기`는 target LLM node의 성공한 실행 기록 중 `input_available=true`, `output_available=true`, `usage_available=true`를 모두 만족하는 가장 최근 `workflow_node_runs`를 A baseline으로 사용한다.

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

baseline input을 복원할 수 없는 실행 로그도 목록에는 표시한다. 다만 이런 row는 `비교 불가` 상태로 표시하고 A/B 비교 실행은 막는다. output preview 또는 usage summary가 없는 실행 로그는 baseline 목록에서 제외한다.

### FR-003. 비교 가능한 옵션

사용자는 B 후보를 구성할 때 여러 설정을 바꿔가며 최적화할 수 있어야 한다.

B 후보는 빈 설정에서 시작하지 않는다. 사용자가 A/B 비교를 시작하면 B 후보는 현재 LLM 노드 설정의 복사본으로 초기화된다. 사용자는 복사된 설정에서 필요한 항목만 바꾸고 B 후보를 실행한다.

1차 구현에서 후보별로 비교할 수 있는 옵션은 다음과 같다.

- 모델
- fallback 모델
- 자동 라우팅 사용 여부
- system prompt
- user prompt
- assistant prompt
- `max_tokens`
- `temperature`
- 출력 형식: text 또는 JSON
- JSON schema
- Knowledge Base 선택
- `topK`
- `scoreThreshold`

모델 후보 목록은 기존 LLM 노드 상세 편집에서 사용하는 모델 조회 경로를 재사용한다. 현재 프론트의 기존 구현은 `GET /api/v1/llm/my-models`와 모델 선택 컴포넌트를 사용한다. Cost Optimizer는 별도 모델 목록 API를 새로 만들기보다, 동일한 모델/credential 접근 기준을 사용한다. 다만 compare API는 최종적으로 선택된 모델과 credential 사용 가능 여부를 다시 검증해야 한다.

일반 LLM 노드 상세 화면과 Cost Optimizer B 후보 화면은 같은 모델 노출 필터를 사용해야 한다. 두 화면에서 선택 가능한 모델이 다르면 사용자가 현재 노드에는 적용할 수 없는 후보를 A/B 테스트하거나, 반대로 원본 노드에서 선택 가능한 모델을 후보에서 찾지 못하는 문제가 생긴다.

모델 노출 정책은 다음을 따른다.

- alias 계열 모델만 기본 노출한다.
- 날짜 suffix가 붙은 버전 모델은 기본적으로 숨긴다.
- embedding, image, audio, realtime, moderation, tts, whisper, transcribe, sora, search-only 계열은 일반 LLM 노드와 Cost Optimizer 후보에서 모두 숨긴다.
- 최신 alias 모델은 provider와 무관하게 whitelist에 포함한다.
- 가격 정보가 없는 모델은 선택 가능하더라도 결과 분석에서 비용 계산 불가 상태로 표시한다.

LLM 노드 상세 화면과 Cost Optimizer B 후보 설정 화면은 `task type`을 사용자가 직접 고르는 입력으로 노출하지 않는다. 작업 유형은 라우터 또는 노드 실행 맥락에서 내부적으로 판단할 후속 정책값이며, 기존 저장/compare request 호환성을 위해 내부 데이터에는 기본값을 유지할 수 있다.

LLM 노드 상세 화면의 자동 라우팅 UX는 다음을 따른다.

- 자동 라우팅 ON: 기본 모델 선택 UI와 fallback 모델 선택 UI를 숨긴다.
- 자동 라우팅 ON: `자동 라우팅 사용 중` 상태와 라우팅 정책/예상 선택 기준을 보여준다.
- 자동 라우팅 ON: 라우터 API 연결 전까지 저장된 `model_id`는 실행 호환성을 위한 내부 fallback으로 유지할 수 있다.
- 자동 라우팅 OFF: 기존처럼 기본 모델과 fallback 모델을 직접 선택한다.
- 자동 라우팅 OFF: 작업 유형 입력은 표시하지 않는다.

자동 라우팅 정책은 로그 축적 정도에 따라 세 단계로 설명한다.

- `cold_start`: 해당 노드 실행 로그가 10회 미만이면 보수적 규칙 기반으로 mid/high 모델을 우선 고려하고 실패 시 상위 모델 fallback을 전제한다.
- `warming_up`: 실행 로그가 10~49회이면 기본 규칙에 schema pass rate, downstream success rate, fallback rate, retry rate, 평균 비용/latency를 함께 반영한다.
- `optimized`: 실행 로그가 50회 이상이면 노드별 실제 성공률, 비용, 품질 profile을 기준으로 cheap/mid/high 후보를 조정한다.

프롬프트 편집은 기존 LLM 노드 상세 편집과 마찬가지로 변수 삽입을 지원해야 한다. 사용자는 upstream output 변수를 system/user/assistant prompt에 삽입할 수 있어야 하며, 등록되지 않은 변수는 실행 전에 validation으로 드러나야 한다.

고급 설정으로 다음 옵션도 비교할 수 있어야 한다.

- `top_p`
- `presence_penalty`
- `frequency_penalty`
- `stop`

출력 형식과 JSON schema는 downstream 안정성에 영향을 줄 수 있으므로 비용 비교 옵션에 포함한다. 예를 들어 자유 텍스트 출력, JSON 출력, 특정 JSON schema를 만족하는 출력을 비교할 수 있어야 한다.

JSON schema 편집은 1차 구현에서 key-type 행 추가 UI로 제공한다. 각 행은 field key, type, required 여부를 가진다. type 후보는 `string`, `number`, `boolean`, `object`, `array`다.

Nested schema는 `object`나 `array` 타입 필드 안에 다시 하위 필드 구조를 정의하는 schema를 뜻한다. 예를 들어 `customer: { name: string, tier: string }`처럼 객체 안의 속성까지 편집하는 것이다. 1차 UI는 flat key-type 행 편집을 기본으로 하며, `object`와 `array` 타입은 선택할 수 있지만 하위 필드 편집 UI는 후속으로 둔다. nested 구조가 반드시 필요한 경우에는 raw schema 편집 또는 후속 schema editor에서 다룬다.

JSON schema를 지정한 B 후보가 LLM 호출에는 성공했지만 schema 검증에 실패한 경우, 후보 실행 자체는 비용/토큰/시간과 함께 결과로 남긴다. 다만 해당 후보의 결과 상태는 `schema_failed`로 표시하고, 현재 노드에 적용할 수 없게 한다.

Knowledge/RAG 설정은 후보 B에서 편집 가능하다. 같은 baseline input이라도 참조하는 Knowledge Base, 검색 개수, score threshold가 달라지면 출력 품질과 비용이 달라질 수 있기 때문이다.

Knowledge Base는 여러 개 선택할 수 있다.

RAG를 곁들인 LLM 노드는 비용을 줄이더라도 author가 직접 작성한 system/user/assistant prompt를 임의로 자르지 않는다. 비용 최적화 대상은 검색으로 주입되는 동적 context와 근거 품질 검증이다.

Knowledge/RAG 비용 최적화 옵션은 다음 4개를 우선 제공한다.

- 중복 근거 제거: 검색된 문서 조각 중 내용이 거의 같은 근거를 한 번만 사용한다.
- 참조 문서 길이 제한: Knowledge Base에서 가져온 문서 context의 최대 길이를 제한한다. 직접 작성한 prompt 3종은 이 제한 대상이 아니다.
- 검색 문서 압축: 검색된 문서를 그대로 넣지 않고 질문과 관련된 핵심 내용만 줄여 전달한다.
- 답변 근거 확인: 생성된 답변이 검색된 문서 내용으로 뒷받침되는지 확인한다.

B 실행 시 Knowledge/RAG를 사용하면 baseline의 과거 retrieval 결과를 재사용하지 않는다. B candidate의 현재 Knowledge Base 선택, `topK`, `scoreThreshold` 기준으로 retrieval을 새로 수행한다. 그래야 모델/prompt뿐 아니라 retrieval 설정 변경이 실제 후보 결과에 반영된다.

A baseline의 retrieval summary는 비교 기준 정보로만 표시한다. Inspector는 A가 어떤 Knowledge Base와 문서를 참고했는지, B가 새로 어떤 Knowledge Base와 문서를 참고했는지를 나란히 보여준다. 단, raw document content나 secret payload는 표시하지 않는다.

선택 불가능하거나 접근 권한이 없는 Knowledge Base는 프론트 목록에서 제외하는 것을 우선한다. 그러나 보안 경계는 API다. compare API는 request의 `knowledge_base_ids`가 현재 사용자와 organization/workflow scope에서 사용 가능한지 다시 검증하고, 사용할 수 없으면 `422 cost_optimizer.knowledge_unavailable`을 반환한다.

B 후보 설정을 현재 노드에 적용할 때는 선택 항목별 부분 적용을 제공하지 않는다. 사용자는 B 후보 설정 전체를 current draft의 target LLM node에 일괄 적용한다.

B 후보 설정 validation은 두 단계로 처리한다. 프론트는 명백히 잘못된 값이면 B 실행 버튼을 비활성화하거나 field-level message를 표시한다. API는 동일한 규칙을 최종 검증하고 잘못된 후보 설정이면 `400 cost_optimizer.invalid_candidate`를 반환한다. 프론트 validation은 UX이며, API validation이 최종 계약이다.

후보를 실행하면 비교 리포트가 생성된다. 사용자는 리포트에서 A baseline과 B candidate의 출력, 비용, 토큰, latency, schema 검증 상태, retrieval summary, downstream 호환성 상태를 확인한 뒤 B 설정을 적용할지 결정한다.

결과 분석 화면은 단순히 A/B 값을 나열하는 화면이 아니라, B 후보를 현재 LLM 노드에 적용해도 되는지 판단하게 하는 화면이어야 한다. 따라서 결과 분석 화면은 다음 정보를 우선순위 있게 보여준다.

1. 적용 판단 요약
2. 핵심 지표 비교
3. A/B 출력 품질 비교
4. 설정 차이, trace, downstream 영향 같은 상세 근거

적용 판단 요약은 다음 3상태 중 하나로 표시한다.

- `적용 후보로 적합`: B 실행이 성공했고, schema/downstream 치명 문제가 없으며 비용 또는 토큰 개선이 확인되는 상태다.
- `주의 필요`: B 실행은 성공했지만 latency 증가, 비용 증가, schema 경고, downstream warning처럼 적용 전 확인이 필요한 상태다.
- `적용 비추천`: B 실행 실패, schema 실패, downstream incompatible, 비용/토큰 악화만 확인되는 상태다.

판단 요약은 비용만으로 결정하지 않는다. 비용/토큰/latency 변화, schema 검증 상태, downstream 호환성, B 실행 상태를 함께 고려한다.

비교 실행은 일회성 응답으로만 버리지 않는다. B 후보 실행은 LLM 비용을 발생시키므로 비교 실행 기록, 후보 설정, 사용량, schema 검증 결과, retrieval summary, downstream 호환성 상태를 추적 가능하게 저장해야 한다.

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

이 화면은 범용 대시보드가 아니라 특정 workflow 안의 특정 LLM node에 종속된 A/B compare workspace다. 사용자는 workflow 편집 화면에서 target LLM node를 선택해 workspace로 진입하고, 이 workspace 안에서 같은 target node에 대한 baseline 선택, B 후보 편집, B 실행, 결과 비교, 재편집, 재실행, 적용까지 반복할 수 있어야 한다.

비교 루프는 클릭 수가 많지 않아야 한다. 사용자가 B 실행 결과를 확인한 뒤 모델, prompt, schema, Knowledge/RAG, 고급 파라미터를 수정하고 다시 실행하는 흐름은 같은 화면 안에서 이어져야 한다. B 후보 설정을 수정할 때마다 화면을 닫거나 baseline을 다시 선택하게 해서는 안 된다.

실험 설정 화면의 기본 레이아웃은 3개 영역으로 구성한다.

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

결과 분석 화면은 다음 순서로 구성한다.

1. `이전 실험 이력`: 같은 baseline 기준 B 후보 실행 이력을 상단 dense table로 표시하고 분석 대상을 선택한다.
2. `판단 요약`: 적용 후보로 적합, 주의 필요, 적용 비추천 중 하나와 그 이유를 표시한다.
3. `핵심 지표 비교`: 비용, prompt tokens, completion tokens, total tokens, latency, 실행 상태, schema, downstream을 A/B/변화값으로 비교한다.
4. `출력 품질 비교`: A 출력과 B 출력을 나란히 보여주고, JSON/schema가 있으면 필수 필드 충족 여부와 누락/타입 문제를 확인할 수 있게 한다.
5. `상세 Inspector`: 설정 차이, 근거/trace, 후속 노드 영향을 탭으로 제공한다.

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

비용이 낮더라도 출력 결과가 부적절하면 사용자가 선택하지 않을 수 있어야 한다. 결과 분석 화면은 비용 절감 결과와 품질/호환성 위험을 분리해서 보여줘야 한다.

현재 구현은 Cost Optimizer 전용 workspace에서 B 후보 실행 결과를 A baseline과 비교해 표시한다. 결과 분석 화면은 후보별 출력, 비용, 토큰, latency, schema 검증 상태, retrieval summary, downstream 호환성 상태를 함께 보여준다.

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

baseline 생성 또는 baseline 조회 시점에는 target LLM node의 downstream snapshot을 함께 만들어야 한다. 이 snapshot은 A baseline을 선택한 시점의 후속 소비 노드, edge, 입력 selector, 필수 output key/path, side-effect 여부를 담는 safe metadata다. raw payload, credential, prompt 원문, secret 값은 포함하지 않는다.

Compare 실행은 현재 workflow graph만으로 downstream을 판정하지 않는다. `workflow_node_runs.id`로 식별되는 A baseline의 downstream snapshot과 B candidate output을 기준으로 contract check를 수행해야 한다. snapshot이 없으면 legacy/retention 데이터로 보고 `unknown` fallback을 반환할 수 있지만, 신규 baseline 생성/조회 경로에서는 snapshot 누락을 정상 상태로 취급하지 않는다.

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
- 저장된 experiment 후보를 적용한 경우, 결과 이력에서 어떤 후보가 적용됐는지 확인할 수 있도록 해당 후보의 적용 상태와 적용 시각/사용자를 기록해야 한다.

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

비교 실행은 다음 두 저장 단위로 추적한다.

- `cost_optimizer_experiments`: 하나의 A/B 테스트 세션을 저장한다. 특정 workflow, target LLM node, A baseline `workflow_node_runs.id`, 시작 사용자, 세션 상태를 가진다.
- `cost_optimizer_candidates`: 하나의 세션 안에서 실행한 B 후보를 저장한다. 후보 설정 snapshot, 후보 실행 run/node run 참조, 비용/토큰/latency, schema 검증 결과, retrieval summary, downstream 호환성 결과, 적용 여부를 가진다.

A/B 테스트 시작 1회는 새 `cost_optimizer_experiments` 1개로 기록한다. 같은 baseline을 사용하더라도 사용자가 나중에 다시 A/B 테스트를 시작하면 기존 experiment를 재사용하지 않고 새 experiment를 만든다. 하나의 experiment 비용 합계는 해당 experiment에 속한 candidate 실행 비용만 포함한다. 같은 baseline 기준 누적 비용이 필요하면 `baseline_node_run_id`가 같은 여러 experiments를 합산한다.

결과 분석 화면은 같은 workflow, 같은 target LLM node, 같은 baseline 기준으로 과거 experiments와 candidates를 다시 조회할 수 있어야 한다. 사용자는 기간, 실행자, 후보 상태, 모델, 적용 여부, schema 검증 상태, downstream 상태 같은 조건으로 이전 실험 결과를 좁혀 볼 수 있어야 한다.

기존 `workflow_runs`, `workflow_node_runs`, `llm_usage_logs`, `trace_payloads`는 실행/trace/비용의 원천으로 유지한다. Cost Optimizer 전용 테이블은 이 원천 데이터를 대체하지 않고, A baseline과 여러 B 후보 실행을 하나의 비교 흐름으로 묶기 위한 메타데이터를 저장한다.

현재 코드에는 일반 workflow LLM 호출의 token, cost, latency를 `llm_usage_logs`와 workflow run 집계에 기록하는 기반이 있다. Cost Optimizer compare는 `comparison_id`가 되는 `cost_optimizer_experiments` row와 B 후보의 `cost_optimizer_candidates` row를 저장한다. B 후보 실행에서 생성되는 usage row는 `llm_usage_logs.cost_optimizer_candidate_id`로 후보 row를 직접 참조한다. 과거 experiment/candidate summary 재조회 API도 제공한다. experiment/candidate summary는 trace metadata retention 정책의 `metadata_retention_days`를 따르고, 만료된 experiment는 candidate와 함께 정리한다.

### FR-010. 권한

비용 비교와 후보 적용은 workflow를 수정할 수 있는 builder 이상 권한이 있는 사용자만 수행할 수 있다.

Cost Optimizer의 A/B 테스트는 단순 실행 기능이 아니라, LLM 노드 설정 후보를 만들고 현재 draft에 적용할 수 있는 편집 도구다. 따라서 실행 권한만 가진 사용자가 비용 비교를 수행할 수 있게 하지 않는다.

- builder 이상 권한이 없으면 A/B 테스트를 실행할 수 없다.
- builder 이상 권한이 없으면 후보를 현재 노드에 적용할 수 없다.
- 사용할 수 없는 credential/model 후보는 실행하지 않거나 실패 후보로 표시한다.

현재 Gateway의 Cost Optimizer availability, baseline 조회, experiment history, compare, apply API는 workflow `write` 권한을 요구한다. 프론트 진입 액션은 builder 미만 사용자에게 비활성화 상태와 권한 부족 안내를 제공한다. compare/apply API는 선택한 모델 후보가 현재 사용자의 사용 가능 모델 목록에 있는지 확인하고, Knowledge Base 후보가 현재 organization/workflow scope에서 `use` 가능한지 다시 검증한다.

### FR-011. 모델 라우팅과 최적화 에이전트 후속 확장

Cost Optimizer는 LLM 노드의 모델 라우팅과 최적화 에이전트를 단계적으로 다룰 수 있어야 한다.

모델 라우팅은 작업 난이도나 작업 유형에 따라 더 저렴한 모델 또는 더 강한 모델을 선택하는 기능이다.

현재 프론트 구현은 LLM 노드 상세 화면에 자동 라우팅 토글과 정책 안내를 제공한다. 자동 라우팅을 켜면 사용자가 기본 모델과 fallback 모델을 직접 고르는 UI를 숨기고, 로그 축적 단계별 라우팅 기준을 보여준다. 단, 실제 실행 시점에 모델을 고르는 라우터 API와 workflow engine 연동은 후속 구현이다.

가능한 모델 라우팅 방식은 다음과 같다.

- 수동 라우팅: 사용자가 노드별 모델을 직접 선택한다.
- 규칙 기반 라우팅: 분류, 요약, 단순 추출은 저렴한 모델을 쓰고 복잡한 추론이나 고위험 답변은 강한 모델을 쓴다.
- LLM 기반 라우팅: 앞단에서 작은 모델 또는 별도 판단기가 요청 난이도를 분류해 적절한 모델을 선택한다.

자동 모델 라우터는 처음부터 완성된 최적 라우터로 동작하지 않는다. 같은 LLM 노드에 쌓인 실행 로그 수와 품질 지표에 따라 `cold_start`, `warming_up`, `optimized` 3단계로 나누어 보수적으로 진화해야 한다.

라우터가 보는 로그는 workflow 전체 실행 횟수가 아니라 target LLM node 기준 실행 이력이다. 라우팅 단계 판단에는 사용 가능한 node run 수, 성공/실패 상태, usage, output, schema 검증 결과, downstream 호환성 결과를 함께 사용한다. 보관 기간 만료나 redaction 때문에 usage/output을 복원할 수 없는 run은 라우팅 프로파일 계산에서 제외한다.

| 라우팅 상태 | 진입 조건 | 목표 | 모델 선택 방식 | fallback 정책 |
| --- | --- | --- | --- | --- |
| `cold_start` | target LLM node의 사용 가능한 실행 로그가 10회 미만 | 품질을 망치지 않는 보수적 비용 절감 | 규칙 기반으로 시작한다. JSON 추출, 내부 triage, 짧은 분류처럼 위험이 낮고 schema가 단순한 작업은 mid 모델을 우선 검토한다. 고객에게 바로 나가는 답변, 장애/보상/보안/법무/SLA 판단, RAG 기반 정책 답변은 mid/high 이상을 우선한다. 애매하면 더 강한 모델을 고른다. | high 또는 현재 저장된 안정 모델을 fallback으로 둔다. 사용할 수 있는 credential/model이 없으면 실행하지 않고 명확한 실패 사유를 반환한다. |
| `warming_up` | 사용 가능한 실행 로그가 10회 이상 50회 미만 | 규칙 기반 판단에 해당 노드의 실제 성공률을 반영 | 기본 규칙을 유지하되, 최근 실행의 schema pass rate, downstream success rate, fallback rate, retry rate, 평균 비용, latency를 반영한다. 저렴한 후보는 품질 gate를 통과할 때만 기본 선택으로 승격한다. | 저렴한 모델에서 schema/downstream 실패나 fallback이 늘면 해당 후보를 제외하고 mid/high로 승격한다. confidence가 낮으면 작은 모델 판단 결과를 참고만 하고 강한 모델로 보낸다. |
| `optimized` | 사용 가능한 실행 로그가 50회 이상 | node별 실제 성능 프로파일 기반 비용 최적화 | 일반 task type보다 이 노드의 최근 성능 프로파일을 우선한다. 짧은 JSON triage처럼 안정적으로 성공한 노드는 cheap/mid 우선, 입력 난이도 편차가 큰 노드는 confidence 기반 라우팅, 실패 비용이 큰 노드는 high 고정 또는 매우 엄격한 downgrade를 적용한다. | 최근 window에서 schema 실패, downstream 실패, fallback, retry, human correction이 증가하면 즉시 더 강한 모델로 승격한다. |

모델을 더 저렴한 후보로 낮추는 조건은 비용 절감만으로 판단하지 않는다. 최소 조건은 다음과 같다.

- 최근 window의 schema pass rate가 기준 이상이다. 초기 기준은 98%로 둔다.
- downstream success rate가 기준 이상이다. 초기 기준은 99%로 둔다.
- fallback rate가 기준 이하이다. 초기 기준은 2% 이하로 둔다.
- retry rate와 human correction rate가 증가하지 않는다. human correction rate는 지표가 수집되기 전까지 `unknown`으로 취급한다.
- 평균 비용 절감이 의미 있는 수준이다. 초기 기준은 30% 이상으로 둔다.
- latency가 서비스 UX나 downstream timeout을 악화시키지 않는다.

라우터는 선택 결과를 설명 가능해야 한다. 실행 결과나 trace summary에는 최소한 다음 정보를 safe summary로 남긴다.

```json
{
  "routing_stage": "optimized",
  "selected_model": "gpt-4.1-mini",
  "fallback_model": "gpt-4.1",
  "reason": "최근 50회 실행에서 schema pass 98%, downstream success 100%, 평균 비용 76% 절감",
  "policy_version": "model-router-v1"
}
```

작업 유형은 사용자가 직접 고르는 입력값으로 두지 않는다. 라우터는 node 설정, output format/schema, prompt, RAG 사용 여부, downstream 계약, 과거 node run profile을 보고 내부적으로 판단한다.

자동 라우팅이 켜져 있어도 품질 gate를 통과하지 못하면 비용이 더 싼 모델을 선택하지 않는다. 이 기능의 기본 원칙은 `품질 유지 후 비용 절감`이다.

최적화 에이전트는 실행 로그와 A/B 비교 결과를 바탕으로 모델, 프롬프트, `max_tokens`, 출력 형식 같은 최적화 후보를 제안하는 기능이다.

최적화 에이전트는 후속 기능으로 추가한다. 에이전트는 자동 적용하지 않고 제안만 제공해야 한다.

## Policies And Edge Cases

- 비교 실행은 실제 LLM 호출이므로 비용이 발생할 수 있다.
- B 후보 실행이 실패해도 A baseline과 기존 experiment history는 유지한다. 해당 실행은 `failed` 후보로 기록하고 실패 사유를 결과 분석 화면에 표시한다.
- 비용 정보가 없는 모델은 비용 비교 불가 상태로 표시한다.
- credential 원문, API key, encrypted config는 응답이나 화면에 표시하지 않는다.
- 비교 결과는 비용만으로 승자를 정하지 않는다. 사용자가 출력 결과를 보고 판단한다.
- downstream 계약 검증은 안전성 보조 기능이며, 전체 workflow 성공을 보장하지 않는다.
- 최종 검증은 기존 workflow 테스트 실행으로 수행할 수 있어야 한다.
- 실패한 LLM node run은 Cost Optimizer baseline 후보에서 제외한다. credential 오류, provider 오류, timeout 같은 실패 원인은 비용 최적화가 아니라 실행 디버깅 영역에서 다룬다.
- output preview 또는 usage summary가 없는 LLM node run은 Cost Optimizer baseline 후보에서 제외한다.
- baseline input이 보관 기간 만료, redaction, retention, 저장 누락으로 복원되지 않는 경우 해당 baseline은 목록에 표시하되 비교 실행은 허용하지 않는다.

## Deferred Scope

다음 항목은 Cost Optimizer 방향에는 포함되지만, 1차 구현의 필수 범위에서는 제외하고 후속 기능으로 분리한다.

- workflow 전체 A/B 테스트
- 자동 품질 점수 산정
- LLM judge 기반 평가
- 자동 모델 추천
- 실행 시점 모델 라우터 API와 workflow engine 연동
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
| Priority 1 | 이전 로그 선택 API | target LLM node 실행 로그를 비용/토큰/시간 기준으로 검색·필터·정렬하는 API를 별도로 둘지 | 기존 workflow run list만으로는 노드 기준 baseline 선택 UX를 만들기 어렵다 | 결정: LLM node 기준 baseline latest/list API를 둔다. |
| Priority 1 | downstream 호환성 | baseline 실행 시점 graph와 현재 graph의 호환성을 어떤 기준으로 판정할지 | 다운스트림이 바뀐 상태에서 비교 결과를 잘못 해석할 수 있다 | 결정: `검증 가능`, `주의 필요`, `검증 불가` 3상태와 `unknown` fallback으로 표시한다. |
| Priority 1 | 비교 결과 저장 | 비교 결과를 저장할지, 화면에서만 보여줄지 | 저장 여부에 따라 DB/API/화면 이력이 달라진다 | 결정: experiment/candidate 전용 테이블에 저장하고 usage log는 candidate id로 직접 연결한다. |
| Priority 1 | 적용 방식 | 선택 후보를 draft에 바로 적용할지, versioning과 연결할지 | 사용자가 실수로 기존 설정을 잃을 수 있다 | 결정: 현재 draft target LLM node에 후보 설정 전체를 적용하고 기존 저장/되돌리기 흐름을 따른다. |
| Priority 2 | downstream 계약 검증 | 1차 구현에서 어떤 다음 노드 타입까지 계약 검증할지 | 지원하지 않는 노드가 있으면 검증 결과를 신뢰하기 어렵다 | 결정: target LLM node를 직접 참조하는 variable extraction mapping, condition selector, answer output selector, Slack referenced variable selector를 후보 출력 기준으로 검사한다. |
| Priority 2 | 실패 후보 처리 | B 후보 실행이 실패했을 때 workspace 전체를 실패로 볼지 | 비교 UX가 달라진다 | 해당 B 실행만 `failed` 후보로 기록하고 A baseline과 기존 history는 유지한다 |
| Priority 3 | 자동 추천 | 가격표 기반으로 후보 모델을 자동 추천할지 | 사용성은 좋아지지만 정책과 품질 판단이 필요하다 | 1차 구현에서는 사용자가 직접 후보를 만든다 |
| Priority 3 | 모델 라우팅 | 수동, 규칙 기반, LLM 기반 라우팅 중 어떤 방식을 먼저 제공할지 | 비용 절감 효과는 크지만 잘못 라우팅하면 품질 문제가 생긴다 | 후속 기능으로 분리한다 |
| Priority 3 | 최적화 에이전트 | 에이전트가 어떤 근거로 모델/프롬프트/파라미터 최적화 후보를 제안할지 | 추천 자체도 비용이 들고 잘못된 추천은 workflow 품질을 해칠 수 있다 | 후속 기능으로 분리하고 자동 적용은 금지한다 |
| Priority 3 | cache/budget | LLM cache와 budget guardrail을 1차 구현에 넣을지 | 실제 비용 절감 효과는 크지만 범위가 커진다 | 별도 follow-up 이슈로 분리한다 |
