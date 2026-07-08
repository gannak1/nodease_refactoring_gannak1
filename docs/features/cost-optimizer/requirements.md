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
| FR-003 | 비교 가능한 옵션 | P1 | `구현 완료` | `테스트 통과` | 모델, fallback 모델, prompt, Knowledge/RAG, 고급 파라미터, 출력 형식을 바꿔 비교한다. 작업 유형은 사용자 선택값으로 노출하지 않는다. |
| FR-004 | 동일 입력 기준 비교 | P1 | `구현 완료` | `테스트 통과` | A baseline의 target LLM node 입력을 B 후보 실행 입력으로 고정한다. |
| FR-005 | 하이브리드 비교 | P1 | `구현 완료` | `테스트 통과` | A는 과거 로그로 고정하고 B만 새 설정으로 실행해 비교한다. |
| FR-006 | A/B 비교 화면 | P1 | `구현 완료` | `테스트 통과` | A baseline, B candidate, Inspector 3영역으로 비용/토큰/trace를 비교하고, 결과 분석 화면에서 B 후보를 현재 노드에 적용해도 되는지 판단 요약을 제공한다. |
| FR-007 | Downstream 호환성 검증 | P1 | `구현 완료` | `테스트 통과` | baseline graph와 현재 graph의 downstream 호환성을 3상태로 판정하고 결과 분석 화면에 표시한다. warning/incompatible 후보는 적용 전 사용자 확인이 필요하다. |
| FR-008 | 후보 적용 | P1 | `구현 완료` | `테스트 통과` | 사용자가 성공한 B 후보 설정 전체를 현재 target LLM node draft에 적용한다. downstream warning 확인과 schema 실패 후보 차단을 제공한다. draft conflict 처리는 후속 보강 대상이다. |
| FR-009 | 비용 기록 | P1 | `구현 완료` | `테스트 통과` | 결과 분석 화면은 A/B 비용, prompt/completion/total token, latency를 표시한다. 비교 실행은 전용 experiment/candidate row로 저장되고 usage row가 candidate를 직접 참조한다. 과거 결과 재조회 API와 trace metadata retention 기준 정리를 제공한다. |
| FR-010 | 권한 | P1 | `구현 완료` | `UI/API 권한 기반 구현, 테스트 통과` | A/B 테스트와 후보 적용은 builder 이상 권한이 있는 사용자만 수행한다. compare/apply/history API와 모델/Knowledge 후보 사용 가능성 검증이 적용됐다. |
| FR-011 | 정책 기반 자동 모델 라우팅 | P2 | `진행중` | `문서화, 구현 필요` | LLM 노드는 자동 모델 라우팅을 켜면 저장된 active policy로 실행 시점 모델을 선택한다. Judge LLM은 매 실행마다 호출하지 않고, 배포 후 운영 로그 20회 누적 또는 사용자의 수동 갱신 요청 시 정책 갱신에만 사용한다. |
| FR-012 | LLM 파라미터 추천 룰셋 | P2 | `미완료` | `문서화, 구현 필요` | 운영 로그와 trace summary를 기반으로 `max_tokens`, `temperature`, RAG context 같은 후보 조정안을 추천한다. LLM은 후보 생성/품질 평가 보조로만 사용하고, 추천 적용은 A/B 후보 생성 후 사용자 확인을 거친다. |

### FR-001. LLM 노드 단위 A/B 테스트 진입

Cost Optimizer의 비교 단위는 workflow 전체가 아니라 특정 LLM 노드 하나다.

- 사용자는 workflow 편집 화면에서 LLM 노드를 선택해 비용 비교를 시작할 수 있어야 한다.
- LLM 노드 상세 화면에는 이 노드에 대해 A/B 테스트를 시작하는 액션이 있어야 한다.
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

LLM 노드 상세 화면의 모델 설정 UX는 다음을 따른다.

- 자동 모델 라우팅 OFF 상태에서는 기본 모델과 fallback 모델 선택 UI를 표시한다.
- 자동 모델 라우팅 ON 상태에서는 기본 모델과 fallback 모델 선택 UI를 숨기고 active policy 상태를 표시한다.
- 실행 시점 자동 라우팅은 active policy를 사용하며, judge LLM을 매 실행마다 호출하지 않는다.
- 정책 갱신은 배포 후 운영 실행 20회 누적 또는 사용자의 `자동 정책 갱신하기` 요청으로 수행한다.
- 작업 유형 입력은 표시하지 않는다.

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

RAG strategy 비교, Knowledge Skill version 비교, 최적화 에이전트는 1차 구현의 필수 범위는 아니지만 후속 확장 후보로 둔다. 모델 라우팅은 FR-011의 정책 기반 자동 라우팅으로 별도 정의한다.

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

### FR-011. 정책 기반 자동 모델 라우팅

Cost Optimizer는 LLM 노드가 배포 후 운영 실행에서 모델을 자동 선택할 수 있도록 정책 기반 모델 라우팅을 제공해야 한다.

모델 라우팅은 매 실행마다 LLM judge를 호출해 판단하는 기능이 아니다. 실행 시점에는 이미 저장된 active policy를 읽고, 그 정책의 rule에 따라 사용할 기본 모델과 fallback 모델을 선택한다. Judge LLM은 정책 생성 또는 정책 갱신 시점에만 호출한다.

정책 갱신은 모델 변경과 같은 의미가 아니다. 배포 후 운영 실행이 20회 쌓이면 시스템은 기존 active policy를 재평가하지만, 충분한 운영 샘플과 품질 gate를 통과한 저비용 후보가 없으면 기존 active policy를 유지한다. 검증 샘플을 만들기 위해 자동으로 더 싼 모델로 하향하는 동작은 하지 않는다. 저비용 모델 탐색은 A/B 테스트나 별도 실험 기능에서 수행한다.

사용자 시나리오는 다음 흐름을 따른다.

1. 빌더가 LLM 노드 상세 화면에서 `자동 모델 라우팅`을 켠다.
2. ON 상태에서는 기본 모델과 fallback 모델 직접 선택 UI를 숨기고 현재 정책 상태를 보여준다.
3. 배포 후 실행 시 LLM 노드는 active policy를 읽어 모델을 선택한다.
4. 실행 시점에는 judge LLM을 호출하지 않는다.
5. 배포 후 운영 실행이 20회 쌓이면 정책 갱신 job이 실행된다.
6. 사용자는 `자동 정책 갱신하기` 버튼으로 즉시 갱신을 요청할 수 있다.
7. judge가 새 정책을 만들면 품질 gate 통과 시 active policy로 반영한다.
8. 품질 근거가 부족하거나 검증된 저비용 후보가 없으면 기존 active policy를 유지하고 갱신 결과를 `kept_current`로 기록한다.
9. 새 정책안이 만들어졌지만 불확실성이 높으면 `pending_review` 상태로 저장하고 기존 active policy를 유지한다.
10. credential 또는 model이 사용할 수 없게 되면 해당 모델은 후보에서 제외하고 fallback 정책을 사용한다.

정책 상태는 다음 값만 사용한다. `cold_start`, `warming_up`, `optimized` 같은 데이터 성숙도 단계는 사용자-facing 상태와 API 계약에서 사용하지 않는다.

| 상태 | 의미 |
| --- | --- |
| `off` | 자동 라우팅 꺼짐 |
| `collecting` | 자동 라우팅은 켜졌지만 정책 갱신에 필요한 운영 로그를 모으는 중 |
| `active` | active policy로 실행 중 |
| `refreshing` | judge가 운영 로그를 분석해 정책을 갱신 중 |
| `pending_review` | 새 정책안이 만들어졌지만 품질 gate 미통과 또는 불확실성 때문에 반영 보류 |
| `failed` | 정책 갱신 실패 |

정책 저장은 LLM 노드 data JSON이 아니라 별도 정책 테이블을 source of truth로 둔다. 노드 data에는 자동 라우팅 ON/OFF와 현재 정책 참조에 필요한 최소 식별자만 둘 수 있다. 정책 본문, 정책 버전, judge 갱신 이력, 갱신 실패 사유, 보류 정책은 별도 테이블에 저장한다.

자동 라우팅 ON 상태에서 운영 실행은 다음 순서로 동작한다.

1. target LLM node의 active policy를 조회한다.
2. active policy가 있고 사용할 수 있는 모델이면 policy rule로 모델을 선택한다.
3. 선택된 모델과 fallback 모델이 현재 organization credential/model relation에서 실행 가능한지 검증한다.
4. 선택된 모델을 사용할 수 없으면 policy fallback을 사용한다.
5. fallback도 사용할 수 없으면 저장된 안정 모델 또는 상위 안정 모델로 보수적으로 실행한다.
6. 실행 metadata에 policy id, policy version, selected model, fallback model, reason code를 남긴다.

런타임 rule evaluator는 도메인 키워드 목록을 코드 상수로 가지지 않는다. 실행 시점에는 입력 길이 bucket, prompt 길이 bucket, 출력 형식, schema 필요 여부, RAG 사용 여부, 파일 입력 여부, 명시적 `customer_facing`, 명시적 `node_task` 같은 일반 feature만 계산한다. SLA, 보상, 장애, 다운로드 같은 도메인 키워드가 필요하면 judge policy refresh가 active policy rule의 `when.keyword_any`에 저장해야 한다.

rule 평가는 구체적인 도메인 rule이 일반 fallback rule에 가려지지 않도록 수행한다. `keyword_any` 같은 judge 생성 도메인 rule은 동일 입력에서 generic `short-json` rule과 함께 매칭될 수 있으므로 우선 평가한다. 그 외 generic rule은 policy의 `priority` 순서를 따른다. 기본 bootstrap policy는 customer-facing 입력을 short JSON 비용 절감 rule보다 보수적으로 우선한다.

허용되지 않은 `when` condition key가 들어온 rule은 저장하거나 평가하지 않는다. 런타임이 모르는 key를 무시하면 judge가 잘못 만든 rule이 너무 넓게 매칭될 수 있기 때문이다. 예를 들어 `customer_support_ticket_triage: true` 같은 임의 key는 사용할 수 없고, 노드 작업 분류는 `node_task: "customer_support_ticket_triage"`로 표현해야 한다.

정책 갱신 샘플은 workflow 전체가 아니라 target LLM node 기준으로 계산한다. 자동 갱신 기준은 배포 후 운영 실행 20회다.

정책 갱신 샘플에 포함하는 데이터:

- `workflow_runs.deployment_id IS NOT NULL`인 배포 후 실행
- `trigger_mode`가 API, webhook, scheduler, app 같은 운영 실행인 run
- target LLM node의 `workflow_node_runs`
- 모델, 비용, token, latency 원천인 `llm_usage_logs`
- schema/downstream/fallback/retry safe metadata

정책 갱신 샘플에서 제외하는 데이터:

- 배포 전 테스트 실행
- `deployment_id IS NULL`인 수동 테스트 실행
- Cost Optimizer A/B 후보 실행
- usage 또는 output을 복원할 수 없는 실행
- retention/redaction 정책 때문에 safe summary를 만들 수 없는 실행

Judge LLM 호출은 정책 갱신 작업에서만 발생한다. 자동 라우팅 ON 상태의 일반 workflow 실행마다 judge를 호출해서는 안 된다.

정책 갱신 trigger는 다음 두 가지다.

| Trigger | 설명 |
| --- | --- |
| `auto_20_runs` | active policy 기준 마지막 갱신 이후 배포 후 운영 실행 20회가 누적되면 자동 실행. 이 trigger는 정책 재평가를 뜻하며 모델 변경을 보장하지 않는다. |
| `manual_refresh` | 사용자가 `자동 정책 갱신하기` 버튼을 눌러 즉시 실행 |

Judge LLM에 전달하는 입력은 safe summary만 허용한다. raw prompt, raw output, raw input, credential 원문, API key, encrypted config, raw trace payload, raw RAG chunk content는 전달하거나 저장하지 않는다.

Judge 입력 safe summary는 다음 정보를 포함할 수 있다.

- eligible run count
- excluded run count와 제외 사유 count
- 모델별 평균 비용, 평균 token, 평균 latency
- schema pass rate
- downstream success rate
- fallback rate
- retry count
- output format/schema summary
- RAG 사용 여부와 retrieval safe summary
- 현재 active policy version
- candidate model 목록과 가격/credential 사용 가능 여부 summary

Judge 결과는 바로 운영 정책에 반영하지 않는다. 다음 gate를 통과한 경우에만 active policy로 조건부 자동 반영한다. gate를 통과한 변경안이 없으면 정책 갱신은 성공했더라도 active policy는 유지하며 결과를 `kept_current`로 남긴다.

- 사용할 수 있는 credential/model만 포함한다.
- 비용 또는 latency 개선 근거가 있다.
- schema/downstream 품질 지표가 기준 이하로 떨어지지 않는다.
- fallback/retry 증가가 허용 범위 이내다.
- judge 결과 confidence가 정책 기준 이상이다.
- raw payload 또는 secret을 포함하지 않는다.

gate를 통과하지 못하면 새 정책안은 `pending_review`로 저장하고 기존 active policy를 유지한다. 검증된 변경안 자체가 없으면 `kept_current`로 기록하고 보류 정책을 만들지 않는다. `pending_review` 정책은 운영 실행에 영향을 주지 않는다.

정책 갱신 metadata는 추적 가능해야 한다. 최소한 다음 정보를 저장한다.

```json
{
  "trigger": "auto_20_runs",
  "judge_model": "gpt-4.1-mini",
  "prompt_version": "model-routing-policy-judge-v1",
  "eligible_run_count": 20,
  "excluded_run_count": 7,
  "judge_usage_log_id": "uuid",
  "result": "applied",
  "new_policy_version": "router-policy-v4"
}
```

실행 시점 trace metadata는 모델 선택 결과만 safe summary로 남긴다.

```json
{
  "llm": {
    "model_routing": {
      "enabled": true,
      "policy_id": "uuid",
      "policy_version": "router-policy-v4",
      "selected_model": "gpt-4.1-mini",
      "fallback_model": "gpt-4.1",
      "decision_source": "active_policy",
      "matched_rule_id": "low-risk-json-triage",
      "reason_code": "quality_gate_passed_cost_reduction",
      "judge_called": false
    }
  }
}
```

작업 유형은 사용자가 직접 고르는 입력값으로 두지 않는다. 정책 갱신은 node 설정, output format/schema, prompt safe summary, RAG 사용 여부, downstream 계약, 과거 node run profile을 보고 내부적으로 판단한다.

정책 기반 자동 모델 라우팅의 기본 원칙은 `품질 유지 후 비용 절감`이다. 비용이 더 싼 모델이라도 품질 gate를 통과하지 못하면 active policy로 반영하지 않는다.

최적화 에이전트는 실행 로그와 A/B 비교 결과를 바탕으로 모델, 프롬프트, `max_tokens`, 출력 형식 같은 최적화 후보를 제안하는 별도 후속 기능이다. 에이전트는 자동 정책 갱신 judge와 역할이 다르며, 후속 기능으로 추가한다.

### FR-012. LLM 파라미터 추천 룰셋

Cost Optimizer는 모델 교체뿐 아니라 LLM 노드의 파라미터 조정 후보도 추천할 수 있어야 한다.

파라미터 추천의 기본 원칙은 `룰셋 + 운영 로그 통계`다. LLM이 직접 추천 결정을 내리지 않는다. LLM은 프롬프트 축소 후보 생성, 변경안 설명 문장 생성, 샘플 품질 judge 같은 보조 역할로만 사용할 수 있다.

추천 대상은 다음 범위로 제한한다.

| 추천 대상 | 추천 근거 | 1차 추천 방식 | 적용 방식 |
| --- | --- | --- | --- |
| `max_tokens` | 최근 `completion_tokens` p95/p99, 응답 잘림 여부, schema/downstream 성공률 | 통계 기반 룰셋 | A/B 후보 생성 후 적용 |
| `temperature` | 출력 형식, JSON schema 사용 여부, schema 실패율, retry/fallback 추세 | 작업 성격 기반 룰셋 | A/B 후보 생성 후 적용 |
| `top_p` | provider 지원 여부, `temperature`와의 조합, 현재 값이 극단값인지 여부 | 보수적 룰셋 | A/B 후보 생성 후 적용 |
| `frequency_penalty` | 출력 반복 패턴, 동일 문장/토큰 반복률, 사용자-facing 답변 품질 이슈 | 로그/출력 패턴 기반 룰셋 | A/B 후보 생성 후 적용 |
| RAG context 사용량 | `prompt_tokens` 중 retrieval context 비중, `context_token_estimate`, `retrieved_chunk_count`, evidence 충분성 | trace summary 기반 룰셋 | A/B 후보 생성 후 적용 |

다음 항목은 1차 자동 추천에서 제외한다.

- `presence_penalty`: 비용 절감과 직접 연결되는 근거가 약하다.
- `stop`: 출력 패턴 분석과 provider별 finish reason 수집이 더 필요하다.
- 프롬프트 축소 자동 적용: 품질 저하 위험이 커서 LLM이 후보를 만들더라도 반드시 A/B 실험을 거쳐야 한다.

`max_tokens` 추천은 다음 조건을 만족할 때만 생성한다.

- target LLM node의 배포 후 운영 성공 sample이 충분하다.
- 최근 sample의 `completion_tokens` p95가 현재 `max_tokens`보다 충분히 낮다.
- schema 실패율과 downstream 실패율이 허용 기준 이하이다.
- 응답이 길이 제한 때문에 잘린 근거가 없다.

추천값은 `completion_tokens` p95 또는 p99에 안전 여유를 더해 계산한다. 예를 들어 현재 `max_tokens=4096`, 최근 p95가 820이고 길이 잘림이 없다면 `1200~1500` 범위를 추천할 수 있다.

현재 코드에는 provider `finish_reason` 저장이 충분하지 않다. 따라서 `max_tokens` 추천은 응답 잘림 여부를 확실히 알 수 없는 경우 confidence를 `medium` 이하로 낮추고, 후속으로 `finish_reason == length` 계열 정보를 usage summary 또는 trace metadata에 저장해야 한다.

`temperature` 추천은 다음 정책을 따른다.

- JSON 출력, schema 필수, 분류, 추출, routing 판단처럼 일관성이 중요한 노드는 낮은 값을 추천한다.
- `temperature > 0.3`이고 schema 실패 또는 출력 변동성 문제가 있으면 `0.1~0.3` 범위를 추천한다.
- 사용자-facing 답변이나 창의적 생성 노드는 낮추더라도 품질 영향이 있을 수 있으므로 반드시 A/B 후보로만 제안한다.
- `temperature` 추천은 직접 비용 절감보다 실패, 재시도, fallback 비용 감소를 목표로 한다.

`top_p` 추천은 provider 호환성과 조합 안정성을 우선한다.

- Anthropic 계열처럼 현재 UI/실행 경로에서 `top_p` 동시 사용을 제한하는 모델은 추천 대상에서 제외하거나 제거 후보로만 표시한다.
- `temperature`와 `top_p`가 동시에 극단값이면 한쪽만 조정하도록 추천한다.
- 단독 비용 절감 근거가 약하므로 `temperature` 안정화 추천의 보조 항목으로 다룬다.

`frequency_penalty` 추천은 반복 출력이 확인되는 경우에만 생성한다.

- 최근 성공 output에서 동일 문장 반복, 같은 bullet 반복, 동일 n-gram 반복률이 높다.
- 반복 때문에 completion token이 증가하고 있다.
- JSON/schema 노드에는 기본적으로 추천하지 않는다.

RAG context 추천은 다음 데이터를 사용한다.

- `LLMUsageLog.prompt_tokens`
- `workflow_node_runs.trace_metadata` 또는 RAG trace payload의 `context_token_estimate`
- `retrieved_chunk_count`
- `evidence_sufficient`
- `answer_grounding` 또는 downstream 성공 여부

RAG context가 prompt token의 대부분을 차지하고, evidence 충분성이 유지되며, 실제 검색 chunk가 과도하게 많으면 `topK`, `retrievedContextMaxChars`, `retrievedContextCompression` 조정을 추천한다. 이때 author가 작성한 system/user/assistant prompt는 임의로 자르지 않는다. 제한 대상은 Knowledge/RAG context뿐이다.

추천 결과는 다음 판단 정보를 가져야 한다.

| Field | 의미 |
| --- | --- |
| `recommendation_type` | `llm_parameter` |
| `parameter_key` | 추천 대상 파라미터 또는 RAG 옵션 |
| `current_value` | 현재 LLM 노드 설정값 |
| `suggested_value` | 추천 후보값 |
| `confidence` | `high`, `medium`, `low` |
| `risk` | `low`, `medium`, `high` |
| `reason` | 사용자에게 보여줄 근거 |
| `evidence` | sample 수, p95 token, 실패율, context token 비중 같은 safe summary |
| `apply_mode` | `experiment_required` 또는 `direct_policy_update` |

파라미터 추천의 기본 `apply_mode`는 `experiment_required`다. 추천 모달에서 `바로 적용`을 누르더라도 `max_tokens`, `temperature`, RAG context 변경은 직접 draft를 수정하지 않고 Cost Optimizer B candidate를 생성해 A/B 비교 화면으로 넘긴다.

자동 모델 라우팅 정책 갱신처럼 운영 정책만 바꾸는 항목은 후속 구현에서 `direct_policy_update`를 허용할 수 있다. 그러나 현재 LLM node의 prompt, parameter, Knowledge/RAG 설정값을 바꾸는 추천은 A/B 비교와 사용자 확인 없이 적용하지 않는다.

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
- 일반 A/B 결과에 대한 LLM judge 기반 자동 품질 점수 산정
- 사용자 클릭 기반 단발 모델 추천 화면
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
- 모든 RAG 검색 모드는 권한 검사를 통과한 문서만 검색 후보로 사용한다. A/B의 차이는 권한 적용 여부가 아니라 권한 범위 안에서 근거를 얼마나 정밀하게 선택하느냐다.
- 가격 정보가 없는 모델은 자동 추천 후보에서 제외하고, 수동 비교 시에는 비용 비교 불가 상태를 명시한다.
- 한쪽 variant 실행이 실패하면 성공한 variant의 부분 결과와 실패 원인을 구분해 표시하고, 절감률은 계산하지 않는다.
- 더 저렴한 후보가 없으면 빈 리포트 대신 "절감 가능 없음"을 명시한다.

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
| Priority 3 | 자동 추천 | 가격표 기반 단발 추천 화면을 별도로 둘지 | 정책 기반 자동 라우팅과 겹치면 사용자가 실행 정책과 단발 추천을 혼동할 수 있다 | FR-011은 정책 기반 자동 라우팅으로 결정하고, 단발 추천 화면은 후속으로 분리한다 |
| Priority 3 | 모델 라우팅 정책 세부 gate | 정책 자동 반영의 정확한 schema/downstream/fallback/confidence 기준값을 어디까지 고정할지 | gate가 느슨하면 품질이 흔들리고, 너무 엄격하면 비용 절감 효과가 낮다 | 기본 원칙은 품질 gate 통과 시 조건부 자동 반영, 미통과 시 `pending_review`로 둔다 |
| Priority 3 | 최적화 에이전트 | 에이전트가 어떤 근거로 모델/프롬프트/파라미터 최적화 후보를 제안할지 | 추천 자체도 비용이 들고 잘못된 추천은 workflow 품질을 해칠 수 있다 | 후속 기능으로 분리하고 자동 적용은 금지한다 |
| Priority 3 | cache/budget | LLM cache와 budget guardrail을 1차 구현에 넣을지 | 실제 비용 절감 효과는 크지만 범위가 커진다 | 별도 follow-up 이슈로 분리한다 |
