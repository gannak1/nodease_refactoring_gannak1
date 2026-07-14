# Cost Optimizer Requirements

Status: Draft
Related Features: workflow, llm-credentials, observability
Verified Against: feature/mba-198 @ 92669f3

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
- 빌더로서, 추천 모달을 벗어나지 않고 최신 성공 실행을 기준으로 추천 설정의 비용, 속도, 출력 품질, schema/downstream 안전성을 빠르게 검증하고 싶다.
- 운영자로서, 비용 최적화 비교 실행에서 발생한 LLM 비용도 일반 실행 비용처럼 기록되기를 원한다.

## Current Implementation Snapshot

현재 구현은 Cost Optimizer를 두 흐름으로 나눈다.

1. `비교 분석 테스트`: 특정 LLM 노드의 과거 `workflow_node_runs.id`를 baseline으로 직접 선택하고, 같은 입력으로 B candidate를 실행해 결과를 비교한다.
2. `모델 라우팅 최적화`: 최신 baseline과 과거 Cost Optimizer experiment/candidate 이력을 읽어, 사용자가 선택한 전략(`자동 균형`, `비용 우선`, `속도 우선`)에 맞는 검증된 후보가 있는지 보여준다.

baseline 선택 UI는 현재 최신 로그를 자동으로 고정하지 않는다. 사용자는 baseline 목록에서 비교 기준 실행 로그를 직접 선택해야 한다. `GET /baselines/latest` API는 모델 라우팅 추천 화면과 API 호환을 위해 남아 있지만, A/B workspace 진입의 기본 UX는 “선택 없이 최신 baseline 자동 사용”이 아니다.

정책 기반 자동 모델 라우팅의 실행 기준은 별도 policy 저장소다. 현재 코드는 active policy 저장, runtime rule 평가, 실행 주체 기준 credential Hard Gate, 운영 run 집계, 자동 입력군 발견, 후보 Replay/Judge 검증, 검증 통과 rule 활성화를 제공한다. 입력군과 검증 증거는 전용 DB table에 저장한다. 다만 Cost Optimizer의 기존 비교 이력을 정책 증거로 자동 흡수하는 통합과, 운영자가 evidence gap을 상세히 보는 분석 화면은 남아 있다. FR-011은 이 범위를 [ADR-0038](../../decisions/ADR-0038-workflow-aware-adaptive-routing.md)의 Workflow-Aware Adaptive Routing으로 다루는 진행중 요구사항이다.

파라미터 추천은 미구현이 아니다. `GET /cost-optimizer/parameter-recommendations`는 배포 후 운영 로그 기반 추천을 반환하고, `PATCH /cost-optimizer/apply-recommendations`는 현재 `direct_policy_update` 성격의 추천만 즉시 draft에 반영한다. 일반 파라미터 변경 추천은 A/B 후보 실험을 거쳐 검증하는 흐름으로 다룬다.

추천 모달 내부의 빠른 검증은 Gateway orchestration API, output quality judge, 프론트 modal panel까지 구현됐다. `테스트하기`는 별도 workspace로 즉시 이동하지 않고, 최신 비교 가능한 성공 실행을 A baseline으로 자동 선택해 모달 안에서 B 후보를 한 번 실행하고 결과를 시각화한다.

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
| FR-002 | A baseline 실행 로그 선택 | P1 | `구현 완료` | `테스트 통과` | baseline 목록에서 사용자가 직접 A 기준 실행 로그를 선택한다. 최신 baseline API는 존재하지만 현재 기본 UX는 자동 선택하지 않는다. |
| FR-003 | 비교 가능한 옵션 | P1 | `구현 완료` | `테스트 통과` | 모델, fallback 모델, prompt, Knowledge/RAG, 고급 파라미터, 출력 형식을 바꿔 비교한다. 작업 유형은 사용자 선택값으로 노출하지 않는다. |
| FR-004 | 동일 입력 기준 비교 | P1 | `구현 완료` | `테스트 통과` | A baseline의 target LLM node 입력을 B 후보 실행 입력으로 고정한다. |
| FR-005 | 하이브리드 비교 | P1 | `구현 완료` | `테스트 통과` | A는 과거 로그로 고정하고 B만 새 설정으로 실행해 비교한다. |
| FR-006 | A/B 비교 화면 | P1 | `구현 완료` | `테스트 통과` | A baseline, B candidate, Inspector 3영역으로 비용/토큰/trace를 비교하고, 결과 분석 화면에서 B 후보를 현재 노드에 적용해도 되는지 판단 요약을 제공한다. |
| FR-007 | Downstream 호환성 검증 | P1 | `구현 완료` | `테스트 통과` | baseline graph와 현재 graph의 downstream 호환성을 3상태로 판정하고 결과 분석 화면에 표시한다. warning/incompatible 후보는 적용 전 사용자 확인이 필요하다. |
| FR-008 | 후보 적용 | P1 | `구현 완료` | `테스트 통과` | 사용자가 성공한 B 후보 설정 전체를 현재 target LLM node draft에 적용한다. downstream warning 확인과 schema 실패 후보 차단을 제공한다. draft conflict 처리는 후속 보강 대상이다. |
| FR-009 | 비용 기록 | P1 | `구현 완료` | `테스트 통과` | 결과 분석 화면은 A/B 비용, prompt/completion/total token, latency를 표시한다. 비교 실행은 전용 experiment/candidate row로 저장되고 usage row가 candidate를 직접 참조한다. 과거 결과 재조회 API와 trace metadata retention 기준 정리를 제공한다. |
| FR-010 | 권한 | P1 | `구현 완료` | `UI/API 권한 기반 구현, 테스트 통과` | A/B 테스트와 후보 적용은 builder 이상 권한이 있는 사용자만 수행한다. compare/apply/history API와 모델/Knowledge 후보 사용 가능성 검증이 적용됐다. |
| FR-011 | Workflow-Aware Adaptive Routing | P1 | `진행중` | `전용 cohort/evidence DB, 자동·직접 입력군, 실제 Replay/Judge gate, runtime trace, 실제 Provider 50건 holdout 검증 완료. 기존 비교 이력 자동 흡수와 분석 UI 보강이 남음` | 운영 로그와 Cost Optimizer Replay를 출처가 구분된 evidence로 사용한다. Hard Gate와 품질 gate를 통과한 후보만 versioned input cohort rule에 연결하며, runtime은 저장 policy만 평가한다. Judge는 검증 단계에서만 출력 품질 평가와 설명을 돕고, 요청마다 정책을 직접 결정하지 않는다. |
| FR-012 | LLM 파라미터 추천 룰셋 | P2 | `진행중` | `서비스/API/UI 일부 구현` | 운영 로그 기반 추천 API와 추천 모달이 있다. 모델 라우팅 enable/refresh 같은 `direct_policy_update`는 즉시 적용 가능하고, 일반 파라미터/RAG 조정은 A/B 후보 실험으로 검증한다. |
| FR-013 | Cost Optimizer 후보 검증 및 출력 품질 평가 | P1 | `구현 완료` | `추천 빠른 검증·일반 compare quality judge·이력 저장·결과 분석 UI 및 targeted test 통과` | 추천 모달과 일반 비교 분석 테스트에서 동일 입력의 A/B 출력을 평가해 비용·속도·token·품질 점수·JSON schema·downstream 호환성을 보여주고, 같은 결과를 적용하거나 다시 조회한다. |
| FR-014 | 배포별 자동 파라미터 최적화 | P2 | `진행중` | `배포 설정·운영 수집·상태/예산 UI 구현` | 배포 시 선택한 LLM 노드의 운영 실행을 수집하고, 점검 주기와 월간 검증 예산을 분리해 관리한다. 모델 라우팅·모델 선택·프롬프트 변경은 포함하지 않는다. |

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

사용자는 baseline 목록에서 특정 실행 로그를 직접 골라 A baseline을 정한다.

현재 UI는 `최신 실행 로그로 비교하기` CTA로 baseline을 자동 고정하지 않는다. target LLM node의 성공한 실행 기록 중 가장 최근 비교 가능 baseline을 조회하는 API는 존재하지만, Cost Optimizer workspace는 사용자가 기준 실행을 확인하고 선택한 뒤에만 B candidate 편집 영역을 연다.

baseline 선택 화면은 로그 선택 화면을 열고, 사용자가 특정 실행 로그를 직접 고르게 한다.

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
- 정책 갱신은 새 validated Replay evidence, 운영 evidence threshold, model availability/drift, 사용자의 수동 요청으로 수행한다. `refresh_every_runs` 기본 20회는 호환용 주기 재평가 trigger이며 모델 변경을 보장하지 않는다.
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

결과 분석 화면은 같은 workflow, 같은 target LLM node, 같은 baseline 기준으로 과거 experiments와 candidates를 다시 조회할 수 있어야 한다. 사용자는 기간, 실행자, 후보 상태, 모델, 적용 여부, schema 검증 상태, downstream 상태 같은 조건으로 이전 실험 결과를 좁혀 볼 수 있어야 한다. 후보 조건을 사용하면 조건에 맞는 experiment 안에서도 일치하는 candidate만 결과에 포함해야 한다.

기존 `workflow_runs`, `workflow_node_runs`, `llm_usage_logs`, `trace_payloads`는 실행/trace/비용의 원천으로 유지한다. Cost Optimizer 전용 테이블은 이 원천 데이터를 대체하지 않고, A baseline과 여러 B 후보 실행을 하나의 비교 흐름으로 묶기 위한 메타데이터를 저장한다.

현재 코드에는 일반 workflow LLM 호출의 token, cost, latency를 `llm_usage_logs`와 workflow run 집계에 기록하는 기반이 있다. Cost Optimizer compare는 `comparison_id`가 되는 `cost_optimizer_experiments` row와 B 후보의 `cost_optimizer_candidates` row를 저장한다. B 후보 실행에서 생성되는 usage row는 `llm_usage_logs.cost_optimizer_candidate_id`로 후보 row를 직접 참조한다. 과거 experiment/candidate summary 재조회 API도 제공한다. experiment/candidate summary는 trace metadata retention 정책의 `metadata_retention_days`를 따르고, 만료된 experiment는 candidate와 함께 정리한다.

### FR-010. 권한

비용 비교와 후보 적용은 workflow를 수정할 수 있는 builder 이상 권한이 있는 사용자만 수행할 수 있다.

Cost Optimizer의 A/B 테스트는 단순 실행 기능이 아니라, LLM 노드 설정 후보를 만들고 현재 draft에 적용할 수 있는 편집 도구다. 따라서 실행 권한만 가진 사용자가 비용 비교를 수행할 수 있게 하지 않는다.

- builder 이상 권한이 없으면 A/B 테스트를 실행할 수 없다.
- builder 이상 권한이 없으면 후보를 현재 노드에 적용할 수 없다.
- 사용할 수 없는 credential/model 후보는 실행하지 않거나 실패 후보로 표시한다.

현재 Gateway의 Cost Optimizer availability, baseline 조회, experiment history, compare, apply API는 workflow `write` 권한을 요구한다. 프론트 진입 액션은 builder 미만 사용자에게 비활성화 상태와 권한 부족 안내를 제공한다. compare/apply API는 선택한 모델 후보가 현재 사용자의 사용 가능 모델 목록에 있는지 확인하고, Knowledge Base 후보가 현재 organization/workflow scope에서 `use` 가능한지 다시 검증한다.

### FR-011. Workflow-Aware Adaptive Routing

Cost Optimizer는 LLM 노드의 workflow 맥락과 검증된 실행 증거를 사용해 모델을
선택하는 Workflow-Aware Adaptive Routing을 제공해야 한다.

여기서 `workflow 맥락`은 다음을 뜻한다.

- target LLM node의 출력 형식과 schema 계약
- Knowledge/RAG 사용 여부
- 파일 입력 여부와 입력/prompt 길이 구간
- downstream node가 기대하는 출력 계약
- 명시적으로 저장된 `customer_facing`과 `node_task`
- 과거 운영 traffic에서 각 입력군이 차지한 비중

`Adaptive`는 매 실행마다 Judge LLM이 모델을 고른다는 뜻이 아니다. 새로운 운영
증거나 Cost Optimizer Replay 결과가 생기면 policy를 재평가하고, 일반 실행은 이미
검증되어 저장된 active policy만 평가한다.

#### 테스트 실행 후 실제 라우팅 상세

Test Sidebar는 실행 전 모델을 예상하는 UI를 제공하지 않는다. 자동 라우팅이 켜진 LLM
node는 현재 draft 설정이 활성 deployment snapshot과 같을 때에만 그 deployment의 active
policy를 **테스트 실행에도 읽어** 모델을 고른다. 사용자는 실제 테스트를 실행한 뒤 각
node의 `상세 보기`를 눌러, **이번 실행에서 실제로 어떤 모델이 선택·호출됐는지** 같은
사이드바 안에서 확인한다. 상세 보기에서 `테스트 결과로 돌아가기`를 누르면 노드별 실행
결과 목록으로 복귀한다.

- 실행 상세에는 상태, 실행 시간, 비용, 전체 출력 데이터를 표시한다. 출력은 임의로 자르지
  않고 내부 스크롤 영역에서 전체 값을 확인할 수 있어야 한다.
- 자동 모델 라우팅이 적용된 LLM node는 입력 유형, 가장 가까운 입력 유형, **현재 policy에
  등록된 모든 입력군의 유사도와 각 입력군의 선택 기준**, 처음 선택한 모델, 선택 이유,
  policy version을 표시한다. 목록은 유사도 내림차순으로 보여 주며, 선택된 입력군 또는
  기준 미달 상태를 함께 표시한다. 매칭 점수는 해당 입력이 특정 입력군과 얼마나 가까운지를
  뜻하며, 입력군의 운영 traffic 비중이나 성공 확률을 뜻하지 않는다.
- 입력군 선택에는 개별 입력군의 통과 기준과 1위·2위 최소 점수 차이 기준을 모두 적용한다.
  화면은 두 기준을 수치로 보여 주되, 입력 원문이나 embedding vector는 표시하지 않는다.
- 입력군 매칭이 기준에 미달하거나 애매하면 `기준 미달로 기본 모델 사용`과 그 이유를
  표시한다. 저비용 모델을 불확실한 입력에 임의로 적용하지 않는 안전 장치다.
- 실제 provider 호출에서 fallback이 발생했으면 최초 선택 모델, 안전한 실패 사유 코드,
  실제 대체 실행 모델을 함께 표시한다. 계획된 fallback 모델만 있는 것과 실제 fallback이
  발생한 것은 구분한다.
- 테스트 실행은 배포 후 운영 실행이 아니므로 policy 학습, 입력군 traffic 집계, 정책 갱신
  카운터에 포함하지 않는다는 안내를 표시한다.
- draft와 활성 deployment의 같은 LLM node 설정 fingerprint가 다르면 해당 node는 배포
  policy를 읽지 않고 현재 저장 모델로 실행한다. 오래된 policy로 새 draft를 테스트하지 않기
  위한 경계다.
- trace에는 raw credential, API key, embedding vector, 입력 원문을 새로 복사해 노출하지
  않는다. 출력 데이터는 기존 테스트 실행 권한 범위에서만 제공한다.

#### 해결해야 하는 현재 공백

현재 구현은 다음 기반을 제공한다.

- policy table과 update/run event 이력
- 배포 runtime의 active policy 조회와 rule evaluator
- 실행 주체 기준 credential/model Hard Gate
- 운영 run 중복 집계와 비동기 refresh task
- 선택 모델, fallback, rule, policy version safe trace

그러나 bootstrap policy는 저장 모델만 유지하고, 운영 profile은 Cost Optimizer
candidate를 제외한다. 새 모델을 policy에 넣으려면 그 모델의 품질 표본이 필요한데
runtime은 검증되지 않은 모델을 임의로 탐색하지 않는다. 따라서 Replay에서 이미
검증한 후보를 policy evidence로 연결하지 않으면 새 모델이 승격될 수 없는 순환이
생긴다.

기존 synthetic E2E는 여러 모델의 profile을 테스트 안에서 미리 주입한다. 이는
rule evaluator와 refresh gate가 주어진 profile에서 동작함을 검증하지만, 실제 DB의
Replay candidate가 policy와 runtime 모델 변경으로 이어짐을 증명하지 않는다.

#### 목표 처리 순서

```text
운영 로그 + Cost Optimizer Replay
  -> Evidence Adapter
  -> Hard Gate
  -> Routing Eligibility Analyzer
  -> Candidate Quality/Efficiency Gate
  -> Deterministic Policy Optimizer
  -> Policy Proposal 또는 Fixed Model 권고
  -> Active Policy
  -> Runtime Semantic Cohort Matcher + Rule Evaluator
  -> Decision Trace
```

#### Evidence source

Evidence는 출처를 구분해야 한다.

| Source | 의미 | FR-011 적용 |
| --- | --- | --- |
| `operational` | 배포 후 실제 운영 run | 현재 구현과 연결 |
| `replay` | 같은 baseline input으로 실행한 Cost Optimizer candidate | 현재 FR-011 구현 범위 |
| `shadow` | 운영 응답에 영향 없이 후보를 병렬 실행 | 후속 |
| `canary` | 제한된 실제 traffic에 후보를 적용 | 후속 |

Replay는 실제 운영 traffic 비중을 증명하지 않는다. 따라서 `replay`와
`operational` sample count를 하나의 숫자로 합치지 않는다. Replay는 후보 품질을
검증하고, 운영 로그는 현재 정책 성능과 입력군 비중을 계산하는 데 사용한다.

현재 구현은 정책 단위로 전용 학습 저장소를 둔다. 일반 운영 입력 원문은 이 저장소에
복사하지 않으며 hash와 embedding vector만 관찰값으로 보관한다.

| 저장소 | 용도 | 원문 보관 여부 |
| --- | --- | --- |
| `workflow_runs`, `workflow_node_runs`, `llm_usage_logs` | 배포 후 운영 실행과 비용의 원천 | 기존 trace 정책을 따른다. |
| `cost_optimizer_experiments`, `cost_optimizer_candidates` | 사용자가 만든 비교/Replay 이력 | 기존 Cost Optimizer 보존 정책을 따른다. |
| `llm_node_model_routing_policies`, `llm_node_model_routing_policy_updates` | active policy와 갱신 이력 | 원문 없음 |
| `llm_node_model_routing_cohorts`, `..._observations`, `..._model_evidence`, `..._validation_*` | 입력군 lifecycle, 비가역 관찰값, 후보 검증 결과, 월간 예산 | 운영 입력 원문 없음 |
| `llm_node_model_routing_cohort_examples` | 입력군의 합성 대표 문장 | 사용자가 직접 등록한 대표 문의 또는 별도 안전 요약 과정이 만든 합성 문장만 보관한다. 운영 원문, secret, 실제 고객 식별 정보는 보관하지 않는다. |

입력군은 자동 발견과 직접 등록을 함께 지원한다.

- 자동 발견: 최근 40개 관찰에서 서로 다른 입력 5개 이상이 두 점검 구간에 반복되면 제안한다.
- 직접 등록: 사용자가 대표 한국어 문의를 쓰고 마법사로 이름/영문 key 초안을 받은 뒤 수정해 저장한다. 직접 등록만으로는 즉시 저비용 모델을 사용하지 않으며, 운영 관찰과 Replay 검증을 통과해야 active rule이 된다.
- 입력군이 0개여도 자동 라우팅을 막지 않는다. 이때 모든 요청은 `기본 모델 (규칙 미일치 시)`로 실행하고, 자동 발견 또는 직접 등록 후 검증된 rule만 별도 모델을 선택한다.
- 대표 문의: policy 조회는 cohort별 `representative_query`를 반환한다. 자동 발견 입력군은 운영 원문을 저장하지 않으므로 안전한 합성 대표 문장이 아직 없으면 `null`을 반환하며, 화면은 준비 중 상태와 `사용자 입력군으로 전환` 액션을 표시한다.
- 수정 경계: `source=manual` 입력군만 이름, 영문 key, 대표 문의, 고정 여부를 수정할 수 있다. 대표 문의를 바꾸면 centroid와 기존 품질 증거의 의미가 달라지므로 기존 route/evidence를 비활성화하고 `proposed` 상태에서 다시 검증한다. `source=auto`는 원본을 수정하지 않고 같은 값을 새 manual cohort 초안으로 복사해 사용자가 별도 입력군으로 등록한다.
- 최대 개수: policy별 `1~12`, 기본 `6`, 권장 `3~6`이다. `proposed`, `validating`, `validated_waiting`, `active` 상태만 자리를 차지한다. `dormant`와 `retired`는 과거 trend 이력이므로 새 입력군 자리를 막지 않는다.
- lifecycle: 자동 입력군은 최근 traffic share가 3개 점검 구간 연속 5% 이하이면 `dormant`, 휴면 뒤 10% 이상으로 회복하면 `active`, 90일이 지나면 `retired`가 된다. 직접 등록/필수/안전 보호 입력군은 자동 휴면 처리하지 않는다.

#### Hard Gate

다음 조건을 통과하지 못한 모델은 점수 계산 전에 후보에서 제외한다.

- 현재 organization과 execution subject가 credential `use` 권한을 가진다.
- credential-model relation이 verified이고 active chat model이다.
- context/output limit, JSON/schema, tool/file/image 기능이 node 요구사항과 호환된다.
- RAG/provider 기능과 organization 정책을 만족한다.
- 삭제, 비활성, 만료 또는 scope 밖 resource를 참조하지 않는다.

권한이나 capability를 통과하지 못한 모델은 fallback으로도 저장하지 않는다.

#### Routing Eligibility Analyzer

모든 LLM node에 adaptive routing을 강제하지 않는다. 분석 결과는 다음 값 중
하나다.

| 결과 | 의미 |
| --- | --- |
| `eligible` | 둘 이상의 실행 가능한 후보와 검증 가능한 품질 계약이 있다. |
| `needs_evidence` | 후보는 있지만 Replay/운영 표본이 부족하다. |
| `fixed_model_recommended` | 모델을 나눠 쓸 예상 이익이 작거나 안전한 품질 검증이 어렵다. |
| `blocked` | 권한, credential, capability 또는 데이터 계약 문제로 분석할 수 없다. |

Analyzer는 후보 수, 품질 계약, cohort 구분 가능성, 표본 수, 예상 순절감액을 본다.
예상 순절감액은 모델 비용 차이에서 Replay/Judge/fallback 비용을 뺀 값이다.
`fixed_model_recommended`이면 억지로 조건 rule을 만들지 않고 현재 모델을 유지한다.

#### Candidate lifecycle과 품질 gate

Candidate 상태는 최소한 다음 의미를 구분한다.

| 상태 | 의미 |
| --- | --- |
| `discovered` | credential/capability 목록에서 발견됨 |
| `eligible` | Hard Gate 통과 |
| `evaluating` | Replay 또는 후속 Shadow/Canary 검증 중 |
| `validated` | 품질/효율 gate 통과 |
| `rejected` | 품질, 호환성 또는 효율 gate 실패 |
| `active` | active policy의 default 또는 rule model로 사용 중 |

`CostOptimizerCandidate` row가 존재한다는 사실만으로 `validated`가 되지 않는다.
다음 조건을 만족해야 한다.

- candidate 실행 성공
- schema가 필요한 경우 schema 통과
- downstream contract가 compatible 또는 승인 가능한 warning
- 자유형 출력은 quality judge score/confidence 통과
- baseline 대비 비용 또는 latency 개선
- fallback/retry 증가가 허용 범위 이내
- candidate와 현재 배포 node fingerprint 비교 가능

임계값은 service 여러 곳에 숫자로 하드코딩하지 않고 versioned
`gate_profile`에서 관리한다. Policy와 trace에는 `gate_profile_version`을 남긴다.

#### Judge 역할

Judge LLM은 다음만 담당한다.

- 자유형 A/B 출력 품질 점수와 safe 근거 생성
- evidence 설명 문구 생성
- policy proposal을 위한 보조 신호 생성

Judge 결과를 active policy에 직접 저장하면 안 된다. Hard Gate, sample gate,
schema/downstream gate, 비용/latency 비교와 허용 condition 검사는 결정론적 코드가
다시 수행해야 한다. Runtime 요청마다 Judge를 호출해서도 안 된다.

#### Semantic cohort catalog

입력의 의미가 다른데도 길이와 JSON 여부가 같으면 일반 feature만으로는 서로 다른
모델을 선택할 수 없다. 따라서 FR-011은 Aurelio Semantic Router의 정적 Route 방식을
참고한 semantic cohort matcher를 포함한다.

Semantic cohort는 runtime에서 즉석으로 군집을 만드는 기능이 아니다. Policy를
활성화하기 전에 다음을 준비한다.

- node별 versioned Route catalog
- Route별 사용자 친화 label과 대표 문장
- 대표 문장의 사전 계산 embedding vector
- Route별 사전 계산 centroid vector
- embedding model/version
- 의미 분류에 사용할 runtime input의 명시적인 `input_paths`
- Route별 threshold, `centroid` aggregation, `min_margin`

대표 문장은 실제 운영 raw input을 그대로 저장하지 않는다. 첫 구현은 node에
명시적으로 등록했거나 검토된 synthetic 문장만 허용한다. Runtime은 `input_paths`에
지정된 업무 본문 값만 순서대로 추출해 한 번 embedding한다. 객체 key, customer tier,
실행 식별자처럼 의미 분류 대상이 아닌 주변 metadata는 포함하지 않는다. 원문과
vector는 trace/API에 저장하지 않는다. 지정 경로에 값이 없으면 임의로 전체 payload를
사용하지 않고 semantic match를 `unavailable`로 닫아 default model을 유지한다.

Route 대표 문장과 threshold/min-margin은 label이 있는 calibration 입력으로만
조정한다. Aurelio의 `fit/evaluate` 분리를 참고해 calibration에 사용한 문장은 최종
정확도 보고용 holdout에서 제외한다. Holdout 결과를 보고 같은 holdout 문장을 그대로
대표 문장에 추가한 뒤 그 데이터로 정확도를 다시 주장해서는 안 된다.

Policy 활성화 시 각 Route 대표 vector의 평균으로 centroid를 미리 계산한다. Runtime은
입력 vector와 각 Route centroid의 cosine similarity를 계산한다. 이 방식은 대표 문장
하나와 우연히 비슷해서 잘못 분류되는 `max` 방식의 위험을 줄이고 Route 전체 의미를
반영한다. 최고 Route가 threshold를 넘고 2위와의 차이가 `min_margin` 이상일 때만
semantic cohort를 확정한다. 불확실하면 `no_match` 또는 `ambiguous`로 표시하고 현재
default model을 유지한다. 기존 policy의 `mean`, `max`, `sum`은 호환을 위해 유지한다.

분류가 확정되지 않아도 운영자가 기준을 조정할 수 있도록 가장 점수가 높았던 Route의
`candidate_cohort_id`, 사용자 친화 label, similarity, threshold와 margin은 safe
진단 정보로 남긴다. 이 후보 Route는 확정 cohort가 아니며 모델 선택 rule에 전달하지
않는다. Runtime input 원문, 대표 문장 원문과 embedding vector는 계속 trace/API에
노출하지 않는다.

Semantic cohort는 입력 의미를 판정할 뿐 모델을 직접 결정하지 않는다. 해당
cohort에서 품질 gate를 통과한 모델만 active policy rule에 연결할 수 있다. Embedding
호출 비용과 latency도 예상 순절감 계산에 포함한다.

#### Hybrid safety override

결제·계정처럼 같은 주제 안에서도 일반 문의와 보안 사고가 함께 발생할 수 있으므로,
서로 배타적인 centroid Route 하나만으로 위험도를 판정하지 않는다. FR-011 runtime은
다음 순서의 하이브리드 matcher를 사용한다.

1. active policy catalog에 `safety_override=true`인 Route가 있으면 해당 Route의
   versioned `lexical_signals`를 먼저 평가한다.
2. signal 점수가 Route의 `lexical_override_threshold` 이상이면 dense similarity보다
   안전 Route를 우선 확정한다.
3. 안전 override가 없으면 기존 embedding centroid, Route threshold와 `min_margin`으로
   semantic cohort를 판정한다.
4. 두 단계 모두 확정하지 못하면 default model을 유지한다.

도메인 신호는 runtime Python 상수에 하드코딩하지 않고 Route catalog/policy 데이터에만
저장한다. 따라서 다른 workflow는 자기 catalog에 맞는 신호를 가질 수 있고, catalog
version 변경으로 검증·배포 이력을 추적할 수 있다. Runtime matcher는 문자열 정규화,
가중치 합산과 threshold 비교만 담당하며 `보안`, `결제`, `SLA` 같은 업무 단어의 의미를
알지 못한다.

Trace에는 `hybrid` matcher 여부, safety override 적용 여부, 매칭 signal 수와 합산
점수만 남긴다. 입력 원문과 매칭된 signal 원문은 저장하지 않는다. 일반 결제 단어만
있다는 이유로 안전 Route를 선택해서는 안 되며, catalog에 명시된 사고 신호가 실제로
threshold를 넘어야 한다.

#### Deterministic Policy Optimizer

Optimizer는 다음 순서로 policy를 만든다.

1. Hard Gate와 quality gate를 통과한 `validated` 후보만 남긴다.
2. 성공/schema/downstream 같은 이진 품질은 Wilson lower bound로 작은 표본의
   불확실성을 반영한다.
3. 자유형 quality score는 표본 수와 분산을 반영한 보수적 lower bound를 사용한다.
4. 후보의 품질 하한이 `baseline 품질 하한 - 허용 품질 저하` 이상인 경우에만 품질
   floor를 통과한다.
5. 품질 floor 안에서 expected cost 또는 latency를 최소화한다. 동률이면 현재 모델을
   유지한다.
6. 운영 traffic share로 전체 예상 비용을 계산한다.
7. fallback, Replay/Judge, semantic embedding 비용을 포함한 예상 순절감액이 양수일
   때만 변경한다.
8. 증거가 부족한 cohort는 현재 모델을 유지한다.

이 알고리즘은 RouteLLM의 `강한 모델이 필요한 확률을 threshold와 비교한 뒤 약한
모델을 사용한다`는 보수적 경계를 참고하되, Nodease의 여러 모델/provider와
schema/downstream 계약에 맞게 constrained optimization으로 확장한다.

초기 cohort condition은 runtime과 optimizer가 공통으로 이해하는 일반 feature만
사용한다.

- `output_format`
- `schema_required`
- `knowledge_enabled`
- `has_file_input`
- `input_length_bucket`
- `prompt_length_bucket`
- 명시적 `customer_facing`
- 명시적 `node_task`

런타임 코드에 SLA, 법무, 고객지원 같은 도메인 키워드를 하드코딩하지 않는다.
초기 자동 policy 생성은 `keyword_any`를 사용하지 않는다.

Policy rule은 `cohort_id`, `when`, `selected_model_id`, `fallback_model_id`,
`reason_code`, `evidence_version`, `gate_profile_version`을 가져야 한다.

#### Runtime과 trace

Runtime은 active policy만 읽고 일반 feature를 계산해 rule을 평가한다. Judge와
optimizer는 runtime request path에서 호출하지 않는다. 사용할 수 없는 rule model은
건너뛰고 검증된 fallback을 사용하며, 사용할 수 있는 policy model이 없으면 provider
호출 전에 fail-closed한다.

Semantic Route catalog가 있으면 runtime은 일반 feature와 semantic cohort를 함께
평가한다. Encoder 사용 실패, threshold 미달, margin 미달에서는 임의로 저비용
모델을 선택하지 않고 default model을 사용한다.

Trace에는 최소한 다음 safe metadata를 남긴다.

- `strategy=workflow_aware_adaptive`
- policy id/version
- evidence version과 gate profile version
- selected/fallback model
- matched cohort/rule id
- semantic Route label, similarity, threshold, margin, match status
- route catalog와 encoder version
- decision source와 reason code
- fallback/escalation 여부와 사유
- `judge_called=false`

#### Policy refresh

고정 N회는 policy 변경의 충분조건이 아니다. `refresh_every_runs`는 호환용
재평가 trigger로 유지할 수 있지만 다음 evidence trigger도 지원해야 한다.

- 새 validated Replay candidate 생성
- 새 운영 evidence가 gate 최소 표본 충족
- model/credential availability 변경
- 품질, 비용 또는 latency drift
- 사용자 수동 갱신
- 호환용 `auto_n_runs`

새 evidence가 없으면 `kept_current`로 끝내고 policy version을 불필요하게 올리지
않는다.

#### 구현 및 실험 완료 조건

FR-011 구현 완료는 문서나 synthetic profile 테스트만으로 판정하지 않는다. 한
workflow의 한 LLM node에서 다음 흐름이 실제 DB 데이터를 통해 연결되어야 한다.

1. 현재 모델과 저비용 후보를 같은 대표 입력군으로 Replay한다.
2. 후보가 schema/downstream/quality gate를 통과한다.
3. refresh가 Replay evidence를 읽어 policy proposal을 만든다.
4. active policy가 versioned Semantic Route catalog를 포함한다.
5. runtime은 입력을 embedding하고 threshold/margin을 통과한 semantic cohort에서
   검증된 후보 모델을 선택한다.
6. 다른 cohort, 애매한 입력 또는 근거 부족 입력은 현재 모델을 유지한다.
7. trace에서 모델, Route label/score/threshold, rule, policy/evidence/catalog version과
   사유를 확인한다.
8. gate 실패 후보는 active policy에 들어가지 않는다.
9. 배포된 workflow에 학습 대표 문장과 겹치지 않는 50개 이상의 다양한 입력을 보내
   예상 cohort/model과 실제 선택 결과를 비교한다.
10. 전체 semantic cohort 정확도 90% 이상, 고위험 입력 recall 95% 이상, trace 필수
    필드 기록률 100%, 권한 없는 모델 선택 0건을 만족해야 한다.
11. 기준을 만족하지 못하면 threshold, 대표 문장 또는 policy mapping의 원인을
    분석하고 수정한 뒤 같은 검증을 반복한다.

실제 Provider 검증은
`reports/model-routing/adaptive-routing-run-b46d0c6d30924f1bbde73c9857fe1969.md`와
보정 기록에 남겼다. 실제 배포 discovery 40건으로 자동 입력군 2개를 만들고,
각 입력군에서 후보별 실제 Replay 5회와 LLM Judge gate를 수행했다. 실제 모델이
요청 모델과 달라 fallback이 발생한 `gpt-5-nano` 후보는 제외했고,
`gpt-5.4-nano`만 검증 통과 rule로 활성화했다. discovery/Replay에 쓰지 않은
holdout 50건은 50/50 성공, trace 선택 근거 50/50 기록, 자동 입력군 2개는 각각
20/20으로 `gpt-5.4-nano`, 고위험 입력군 10/10은 `gpt-4.1`로 실행됐다.
이 결과는 해당 seed/deployment의 재현 결과이지, 모든 업무 입력에서 같은 품질을
보장한다는 일반 성능 수치는 아니다.

Replay 품질 증거를 만드는 입력군은 Route 대표 문장, threshold 보정용 calibration,
최종 정확도 평가용 holdout과 분리한다. 증거 수집 입력은 실제 배포 baseline을 먼저
만들고, 그 baseline의 동일 입력으로 후보 모델만 실행한다. 이 과정에서 생성된 실제
`cost_optimizer_experiments`와 `cost_optimizer_candidates`만 policy optimizer의
후보 증거로 사용하며, 임의로 만든 DB 행이나 최종 holdout 결과를 증거로 사용하지
않는다.

#### 후속 제품 범위

후속 제품 작업에서는 라우팅 적합성/evidence gap/예상 절감/policy diff UI,
activation/rollback UI, traffic share 기반 예상 절감 보강과 시연 QA를 진행한다.
실행 로그의 실제 선택 모델·입력 유형·fallback·policy version과 사용자 친화적 선택
근거 표시는 현재 구현 범위에 포함된다.

Shadow, Canary, Selective Cascade, provider SLO, drift 기반 adaptive refresh와
Contextual Bandit은 후속 범위다. Semantic cohort matcher는 현재 FR-011 범위에
포함한다.

#### 현재 구현 호환 동작

아래 내용은 Workflow-Aware evidence pipeline이 연결되기 전 현재 policy 저장,
runtime, 운영 run 집계와 Judge refresh의 호환 동작이다. 고정 20회와 Judge policy
초안은 최종 policy 결정 규칙이 아니라 기존 trigger/입력 경로로만 유지한다.

Cost Optimizer는 LLM 노드가 배포 후 운영 실행에서 모델을 자동 선택할 수 있도록 정책 기반 모델 라우팅을 제공해야 한다.

모델 라우팅은 매 실행마다 LLM judge를 호출해 판단하는 기능이 아니다. 실행 시점에는 이미 저장된 active policy를 읽고, 그 정책의 rule에 따라 사용할 기본 모델과 fallback 모델을 선택한다. Judge LLM은 정책 생성 또는 정책 갱신 시점에만 호출한다.

정책 갱신은 모델 변경과 같은 의미가 아니다. 배포 후 운영 실행이 20회 쌓이면 시스템은 기존 active policy를 재평가하지만, 충분한 운영 샘플과 품질 gate를 통과한 저비용 후보가 없으면 기존 active policy를 유지한다. 검증 샘플을 만들기 위해 자동으로 더 싼 모델로 하향하는 동작은 하지 않는다. 저비용 모델 탐색은 A/B 테스트나 별도 실험 기능에서 수행한다.

사용자 시나리오는 다음 흐름을 따른다.

1. 빌더가 LLM 노드 상세 화면에서 `자동 모델 라우팅`을 켠다.
2. ON 상태에서는 사용자가 `기본 모델 (규칙 미일치 시)`과 `기본 대체 모델`을 설정하고 현재 정책 상태를 확인한다. 입력군 rule에 매칭되지 않은 요청만 이 기본 모델을 사용하며, 검증된 입력군 rule은 별도 모델을 선택할 수 있다.
3. 변경한 node 설정을 포함해 workflow를 배포한다. draft에서 토글만 켠 상태는 운영 표본 집계 대상이 아니다.
4. 배포 후 첫 성공 운영 실행은 저장 `model_id`/`fallback_model_id`로 보수적으로 실행하고, 같은 두 모델만 담은 policy row를 만든다. bootstrap은 모델을 하향하거나 조건 rule을 만들지 않는다.
5. 그 다음 배포 후 실행부터 LLM 노드는 policy table의 active policy를 읽어 모델을 선택한다.
6. 실행 시점에는 judge LLM을 호출하지 않는다.
7. 배포 후 운영 실행이 20회 쌓이면 정책 갱신 job이 실행된다.
8. 사용자는 policy row가 만들어진 뒤 `자동 정책 갱신하기` 버튼으로 즉시 갱신을 요청할 수 있다.
9. judge가 새 정책을 만들면 품질 gate 통과 시 active policy로 반영한다.
10. 품질 근거가 부족하거나 검증된 저비용 후보가 없으면 기존 active policy를 유지하고 갱신 결과를 `kept_current`로 기록한다.
11. 새 정책안이 만들어졌지만 불확실성이 높으면 `pending_review` 상태로 저장하고 기존 active policy를 유지한다.
12. credential 또는 model이 사용할 수 없게 되면 해당 모델은 후보에서 제외하고 policy fallback을 찾는다. 현재 실행 주체가 쓸 수 있는 모델이 하나도 없으면 provider 호출 전에 명시적으로 실패한다.

정책 상태는 다음 값만 사용한다. `cold_start`, `warming_up`, `optimized` 같은 데이터 성숙도 단계는 사용자-facing 상태와 API 계약에서 사용하지 않는다.

| 상태 | 의미 |
| --- | --- |
| `off` | 자동 라우팅 꺼짐 |
| `collecting` | 자동 라우팅은 켜졌지만 정책 갱신에 필요한 운영 로그를 모으는 중 |
| `active` | active policy로 실행 중 |
| `refreshing` | judge가 운영 로그를 분석해 정책을 갱신 중 |
| `pending_review` | 새 정책안이 만들어졌지만 품질 gate 미통과 또는 불확실성 때문에 반영 보류 |
| `failed` | 정책 갱신 실패 |

정책 저장 source of truth는 `llm_node_model_routing_policies`다. 이 row는 active policy, pending policy, 정책 버전, 설정된 갱신 횟수, 마지막 갱신 시각과 누적 운영 실행 수를 가진다. LLM node data의 `model_routing_policy` JSON은 이전 draft/Cost Optimizer candidate 호환용 snapshot일 뿐, 일반 배포 실행의 정책 기준이 아니다.

자동 모델 라우팅이 켜진 동일 LLM node를 새 deployment version으로 다시 배포하면, 새 배포는 이전 활성 배포의 active policy, 입력군, 대표 예문, 검증 완료 모델 evidence를 이어받아야 한다. 이때 policy 안의 semantic cohort ID 참조도 새 입력군 row ID로 다시 연결해야 한다. 반면 이전 배포에서 누적한 운영 실행 수, refresh 진행 상태, run event, 운영 관찰값, 월간 Replay/Judge 검증 비용은 새 배포의 운영 이력이 아니므로 복사하지 않고 새 버전에서 0부터 다시 기록한다. 이 규칙은 새 배포 직후 입력군 목록과 직접 입력군 추가 기능이 비어 보이지 않게 하면서, 예전 버전의 실행 수로 새 버전의 정책 갱신이 조기에 예약되는 문제를 막는다.

배포된 graph snapshot에서 `auto_model_routing=true`인 LLM node에 아직 policy row가 없다면 첫 실행은 node에 저장된 `model_id`와 `fallback_model_id`를 보수적으로 사용한다. graph snapshot 안의 legacy `model_routing_policy` JSON은 이 시점에 평가하지 않는다. 첫 terminal 운영 workflow 완료 후 생성되는 bootstrap policy도 저장 `model_id`/`fallback_model_id`만 보존하고 rule은 빈 배열로 둔다. bootstrap 생성은 judge refresh가 아니며, `auto_n_runs` 또는 `manual_refresh`가 policy update row를 남기는 실제 정책 갱신이다.

각 배포 후 workflow run은 `llm_node_model_routing_policy_run_events`에 한 번만 기록한다. 이 event의 `(policy_id, workflow_run_id)` 고유 제약으로 Celery 재시도나 중복 완료 훅이 같은 run을 두 번 카운트하지 못하게 한다. 누적 수가 `refresh_every_runs`에 처음 도달한 event만 refresh task를 예약한다.

자동 라우팅 ON 상태에서 운영 실행은 다음 순서로 동작한다.

1. target LLM node의 policy table에서 active policy를 조회한다.
2. active policy가 있고 사용할 수 있는 모델이면 policy rule로 모델을 선택한다.
3. policy의 default/rule/fallback 모델을 현재 execution subject의 credential `use` 권한과 verified credential-model relation으로 제한한다.
4. 선택된 rule 모델을 사용할 수 없으면 policy default/fallback 중 현재 사용 가능한 모델을 선택한다.
5. 현재 사용 가능한 policy 모델이 하나도 없으면 provider 호출 전에 `model_routing_no_available_model`로 실패한다. 저장 모델이나 임의 상위 모델을 추정해 호출하지 않는다.
6. 실행 metadata에 policy id, policy version, selected model, fallback model, reason code, `judge_called=false`를 남긴다.

런타임 rule evaluator는 도메인 키워드 목록을 코드 상수로 가지지 않는다. 실행 시점에는 입력 길이 bucket, prompt 길이 bucket, 출력 형식, schema 필요 여부, RAG 사용 여부, 파일 입력 여부, 명시적 `customer_facing`, 명시적 `node_task` 같은 일반 feature만 계산한다. 현재 judge refresh에는 raw 입력이 전달되지 않으므로 `keyword_any`를 추정 생성하지 않고, 위 일반 feature와 동일한 segment 성능 근거가 있는 rule만 자동 반영한다. 기존에 검토·저장된 `keyword_any` rule은 runtime이 저장 policy로만 평가할 수 있지만, 자동 refresh의 생성 대상은 아니다.

generic rule은 policy의 `priority` 순서를 따른다. 기본 bootstrap policy는 rule 없이 저장 모델을 유지한다.

허용되지 않은 `when` condition key가 들어온 rule은 저장하거나 평가하지 않는다. 런타임이 모르는 key를 무시하면 judge가 잘못 만든 rule이 너무 넓게 매칭될 수 있기 때문이다. 예를 들어 `customer_support_ticket_triage: true` 같은 임의 key는 사용할 수 없고, 노드 작업 분류는 `node_task: "customer_support_ticket_triage"`로 표현해야 한다.

정책 갱신 샘플은 workflow 전체가 아니라 target LLM node 기준으로 계산한다. 자동 갱신 기준은 배포 후 운영 실행 20회다.

정책 갱신 샘플에 포함하는 데이터:

- `workflow_runs.deployment_id IS NOT NULL`인 배포 후 terminal (`success` 또는 `failed`) 실행
- `trigger_mode`가 API, webhook, scheduler, app 같은 운영 실행인 run
- target LLM node의 `workflow_node_runs`
- 모델, 비용, token, latency 원천인 `llm_usage_logs`
- schema/downstream/fallback/retry safe metadata

정책 갱신 샘플에서 제외하는 데이터:

- 배포 전 테스트 실행
- `deployment_id IS NULL`인 수동 테스트 실행
- Cost Optimizer A/B 후보 실행
- 모델을 식별할 수 없거나 safe summary를 만들 수 없는 실행
- retention/redaction 정책 때문에 safe summary를 만들 수 없는 실행

Judge LLM 호출은 정책 갱신 작업에서만 발생한다. 자동 라우팅 ON 상태의 일반 workflow 실행마다 judge를 호출해서는 안 된다.

정책 갱신 trigger는 다음 두 가지다. 자동 trigger는 배포 후 운영 실행이 완료된 뒤에만 생성한다. 테스트 실행, Cost Optimizer candidate 실행, `deployment_id`가 없는 수동 실행은 카운트와 judge 입력에서 제외한다.

| Trigger | 설명 |
| --- | --- |
| `auto_n_runs` | active policy 기준 마지막 갱신 이후 배포 후 운영 실행이 node 설정의 `refresh_every_runs`만큼 누적되면 자동 실행. 기본값은 20회이며 이 trigger는 정책 재평가를 뜻할 뿐 모델 변경을 보장하지 않는다. |
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
- 입력/프롬프트 길이 bucket, output format, schema 필요 여부, RAG 사용 여부, 파일 입력 여부, `customer_facing`, `node_task`별 segment 성능 summary
- output format/schema summary
- RAG 사용 여부와 retrieval safe summary
- 현재 active policy version
- candidate model 목록과 가격/credential 사용 가능 여부 summary

Judge 결과는 바로 운영 정책에 반영하지 않는다. 다음 gate를 통과한 경우에만 active policy로 조건부 자동 반영한다. gate를 통과한 변경안이 없으면 정책 갱신은 성공했더라도 active policy는 유지하며 결과를 `kept_current`로 남긴다.

- 사용할 수 있는 credential/model만 포함한다.
- 비용 또는 latency 개선 근거가 있다.
- schema/downstream 품질 지표가 기준 이하로 떨어지지 않는다.
- fallback/retry 증가가 허용 범위 이내다.
- 후보 Replay의 `requested_model_id`와 provider가 실제로 응답한 `actual_model_id`가 같고 fallback이 발생하지 않는다. 요청 모델과 실제 실행 모델이 다르면 해당 표본은 후보 모델의 품질 증거가 아니므로, schema와 judge 점수가 통과했더라도 candidate 승격에 사용하지 않는다.
- judge 결과 confidence가 정책 기준 이상이다.
- 조건 rule은 같은 `when` 조건의 segment에서 해당 모델이 품질 gate를 통과한 근거가 있다.
- raw payload 또는 secret을 포함하지 않는다.

새 default model 또는 새/변경된 rule의 `selected_model_id`는 기존 bootstrap policy의 rule이나 fallback에 이미 등장했더라도 별도의 운영 품질 표본을 가져야 한다. 단순히 후보 목록에 있었던 사실은 검증 근거가 아니다. 변경 모델과 현재 primary model 모두 관측 평균 비용 또는 평균 latency가 있으면 변경 모델은 둘 중 하나에서 개선되어야 한다. 관측값을 비교할 수 없는 경우에만 verified candidate의 정적 price 정보를 보조 비용 근거로 사용한다.

gate를 통과하지 못하면 새 정책안은 `pending_review`로 저장하고 기존 active policy를 유지한다. 검증된 변경안 자체가 없으면 `kept_current`로 기록하고 보류 정책을 만들지 않는다. `pending_review` 정책은 운영 실행에 영향을 주지 않는다.

정책 갱신 metadata는 추적 가능해야 한다. 최소한 다음 정보를 저장한다.

```json
{
  "trigger": "auto_n_runs",
  "judge_model": "gpt-4.1-mini",
  "prompt_version": "model-routing-policy-judge-v1",
  "eligible_run_count": 20,
  "excluded_run_count": 7,
  "judge_usage_log_id": "uuid",
  "result": "applied",
  "new_policy_version": "router-policy-v4"
}
```

실행 시점 trace metadata는 모델 선택 결과와 파라미터 추천 품질 신호를 canonical `trace_metadata.llm`/`.rag`에 safe summary로 남긴다.

```json
{
  "llm": {
    "policy_id": "uuid",
    "policy_version": "router-policy-v4",
    "selected_model": "gpt-4.1-mini",
    "fallback_model": "gpt-4.1",
    "decision_source": "active_policy",
    "matched_rule_id": "low-risk-json-triage",
    "reason_code": "quality_gate_passed_cost_reduction",
    "judge_called": false,
    "finish_reason": "stop",
    "schema_status": "passed",
    "downstream_status": "passed",
    "fallback_used": false,
    "repetition_rate": 0.02
  },
  "rag": {
    "context_token_estimate": 420,
    "retrieved_chunk_count": 3,
    "evidence_sufficient": true
  }
}
```

작업 유형은 사용자가 직접 고르는 입력값으로 두지 않는다. 정책 갱신은 node 설정, output format/schema, prompt safe summary, RAG 사용 여부, downstream 계약, 과거 node run profile을 보고 내부적으로 판단한다.

정책 기반 자동 모델 라우팅의 기본 원칙은 `품질 유지 후 비용 절감`이다. 비용이 더 싼 모델이라도 품질 gate를 통과하지 못하면 active policy로 반영하지 않는다.

최적화 에이전트는 실행 로그와 A/B 비교 결과를 바탕으로 모델, 프롬프트, `max_tokens`, 출력 형식 같은 최적화 후보를 제안하는 별도 후속 기능이다. 에이전트는 자동 정책 갱신 judge와 역할이 다르며, 후속 기능으로 추가한다.

### FR-012. LLM 파라미터 추천 룰셋

Cost Optimizer는 모델 교체뿐 아니라 LLM 노드의 파라미터 조정 후보도 추천한다.

현재 구현은 `CostOptimizerParameterRecommendationService`와 Gateway의 `GET /cost-optimizer/parameter-recommendations`, `PATCH /cost-optimizer/apply-recommendations`를 통해 일부 추천을 제공한다. 운영 로그가 부족하면 모델 라우팅 enable/refresh 계열 추천만 반환할 수 있고, 충분한 운영 sample이 있으면 `max_tokens`, `temperature`, `top_p`, `frequency_penalty`, RAG context 관련 추천을 만든다.

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

일반 실행은 `finish_reason`, JSON schema 결과, fallback 사용 여부, output 반복률을 `workflow_node_runs.trace_metadata.llm`의 safe summary로 남긴다. `finish_reason` 또는 schema signal이 누락된 표본은 max_tokens 하향 추천의 신뢰도를 낮추거나 추천 자체를 막는다.

파라미터 추천은 현재 draft와 활성 deployment snapshot의 target node 설정 fingerprint가 같은 경우에만 운영 표본을 사용한다. 서로 다른 deployment/version 또는 현재 draft 설정을 섞지 않으며, terminal 실패 run은 schema/downstream/RAG 품질 실패율에 포함한다. 비용·token p95는 성공 usage가 있는 표본에서만 계산한다.

`temperature` 추천은 다음 정책을 따른다.

- JSON 출력, schema 필수, 분류, 추출, routing 판단처럼 일관성이 중요한 노드는 낮은 값을 추천한다.
- `temperature > 0.3`이고 schema 실패 또는 출력 변동성 문제가 있으면 `0.1~0.3` 범위를 추천한다.
- 사용자-facing 답변이나 창의적 생성 노드는 낮추더라도 품질 영향이 있을 수 있으므로 반드시 A/B 후보로만 제안한다.
- `temperature` 추천은 직접 비용 절감보다 실패, 재시도, fallback 비용 감소를 목표로 한다.

`top_p` 추천은 provider/model 호환성과 조합 안정성을 우선한다.

- Anthropic 계열처럼 현재 UI/실행 경로에서 `top_p` 동시 사용을 제한하는 모델과 OpenAI GPT-5/o Responses 계열처럼 중앙 runtime 보정이 `top_p`를 제외하는 모델은 새 값 추천 대상에서 제외하거나 제거 후보로만 표시한다.
- 중앙 runtime 보정은 저장된 node parameter와 호출자가 전달한 message/parameter object를 바꾸지 않고 별도 effective request를 만든다. GPT-5/o Responses 요청에서는 지원하지 않는 `top_p`, `presence_penalty`, `frequency_penalty`, `stop`을 제거하며, `response_format`을 `text.format`으로 합칠 때도 기존 nested `text` object를 변경하지 않는다.
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

### FR-013. Cost Optimizer 후보 검증 및 출력 품질 평가

추천 모달의 `테스트하기`는 더 이상 Cost Optimizer workspace로 즉시 이동하지 않는다. 사용자가 선택한 추천 설정을 현재 LLM node 설정 복사본에 적용한 B candidate를 만들고, 최신 비교 가능한 성공 실행을 A baseline으로 자동 선택해 모달 안에서 B를 한 번 실행한다.

일반 `비교 분석 테스트`에서 사용자가 baseline을 직접 선택해 B candidate를 실행하는 경로도 같은 출력 품질 평가 계약을 사용한다. B candidate 실행이 끝나면 동일 입력의 A/B 출력을 blind pairwise judge로 평가하고, 결과 분석 화면의 `핵심 지표 비교`에 `출력 품질 점수` 행을 추가한다. 점수와 confidence는 compare 응답과 experiment/candidate 이력에 함께 저장해, 방금 실행한 후보와 이전 실험을 같은 기준으로 다시 확인할 수 있어야 한다.

빠른 검증 baseline은 요청 시점의 target LLM node 실행 중 다음 조건을 모두 만족하는 가장 최근 실행이다.

- 성공한 `workflow_node_runs`다.
- input, output, usage를 복원할 수 있다.
- Cost Optimizer candidate 실행이 아니다.
- 현재 draft와 node 설정 fingerprint가 같은 활성 deployment의 exact `deployment_id`를 가진 운영 실행이다. 실행 로그의 `process_data`는 보안 마스킹될 수 있으므로 baseline cohort를 다시 판정하는 원천으로 사용하지 않는다.

baseline을 찾지 못하면 LLM 호출을 시작하지 않고 `비교 가능한 최신 성공 기록이 없습니다.`를 표시한다. 빠른 검증이 시작된 뒤에는 exact `baseline_node_run_id`를 결과에 고정하며, 실행 도중 더 최신 로그가 생겨도 baseline을 바꾸지 않는다.

빠른 검증은 A를 다시 실행하지 않고, A의 복원된 입력을 B candidate에 고정해 B만 새로 실행한다. 선택한 추천 row 또는 target node draft가 바뀌면 기존 결과를 `stale`로 표시하고 적용을 막으며, 다시 테스트해야 한다.

모달은 각 지표를 서로 다른 단위의 독립된 A/B 막대그래프로 표시한다.

| 지표 | A baseline | B candidate | 변화 표시 |
| --- | --- | --- | --- |
| 비용 | 과거 baseline LLM 비용 | 이번 candidate LLM 비용 | 금액 차이와 절감률 |
| 실행 시간 | baseline node latency | candidate node latency | ms/s 차이와 증감률 |
| 입력/출력/전체 token | baseline usage | candidate usage | token 수와 증감률 |
| 출력 품질 점수 | 같은 rubric으로 평가한 baseline 점수 | 같은 rubric으로 평가한 candidate 점수 | 0~100 점수 차이와 confidence |

비용, latency, token, 품질 점수는 단위와 값 범위가 다르므로 하나의 공통 축에 섞지 않는다. 막대 길이는 각 metric 카드 안에서 A/B 상대 비교에만 사용하고 실제 숫자를 항상 함께 표시한다.

`이번 테스트에서 새로 발생한 비용`은 다음 항목을 분리해 보여준다.

- B candidate 실행 LLM 비용
- 출력 품질 평가 judge 비용
- 두 비용의 합계

A baseline 비용은 과거 실행에서 이미 발생한 참고 비용이므로 이번 테스트 신규 비용 합계에 다시 더하지 않는다. candidate 또는 judge 가격 정보를 계산할 수 없으면 `계산 불가`를 표시하고 임의의 0원으로 보이지 않게 한다.

출력 품질 평가는 Cost Optimizer 전용 LLM judge 기능으로 새로 구현한다.

- baseline output을 정답으로 간주하지 않는다.
- baseline과 candidate를 같은 input, target node prompt 목적, output contract에서 독립적으로 평가한다.
- judge에는 A/B 순서를 무작위로 가린 pairwise payload를 전달해 위치 편향을 줄인다.
- `instruction_fulfillment`, `relevance_completeness`, `clarity_consistency`, RAG 사용 시 `groundedness`를 평가해 0~100 점수와 confidence를 반환한다.
- JSON schema 통과 여부와 downstream 호환성은 semantic 품질 점수에 섞지 않고 별도 deterministic gate로 표시한다.
- judge가 실패하거나 실행 가능한 credential/model이 없으면 품질 점수만 `평가 불가`로 표시하고 비용·속도·schema·downstream 결과는 유지한다.
- 품질 점수는 추천 근거이며 단독 hard block으로 사용하지 않는다. 낮은 점수 또는 낮은 confidence에서는 적용 전 경고와 명시적 확인을 요구한다.

일반 compare 경로의 품질 judge 호출은 B candidate 실행과 같은 비교 결과에 귀속한다. candidate 실행이 실패하면 judge를 호출하지 않고 `unavailable` 품질 평가를 저장한다. candidate 실행이 성공했지만 judge가 실패해도 compare HTTP 응답은 성공한 candidate 실행 결과를 유지하며, 품질 평가 상태와 safe summary만 `unavailable`로 반환한다.

judge provider 호출이 완료됐지만 응답 JSON 파싱, 필수 dimension 또는 confidence 검증에 실패한 경우에도 실제 발생한 judge usage와 비용은 기록한다. 이 경우 점수는 임의로 보정하지 않고 `unavailable`로 반환하며, 계약에 없는 추가 dimension은 총점 계산에서 제외한다.

출력 schema 검증은 candidate의 `output_format.type=json`일 때만 수행한다.

- JSON schema가 있으면 `passed` 또는 `failed`와 누락 field/type mismatch를 safe summary로 보여준다.
- JSON 출력이지만 schema가 없으면 `not_configured`로 표시한다.
- text 출력이면 `not_applicable`로 표시하고 schema 실패처럼 보이지 않게 한다.

downstream 호환성은 기존 FR-007 contract validator를 재사용한다. `compatible`, `warning`, `incompatible`, `unknown` 상태와 검사한 직접 소비 노드를 표시한다. `incompatible`은 적용을 막고, `warning`은 사용자 확인 후 적용할 수 있다.

빠른 검증 결과는 기존 Cost Optimizer experiment/candidate 이력으로 저장한다. 모달의 `상세 비교 분석하기`는 같은 `comparison_id`와 `candidate_id`를 기존 결과 분석 workspace에 전달하며 B를 다시 실행하거나 비용을 중복 발생시키지 않는다.

결과 분석 workspace는 전달받은 experiment/candidate를 목록 pagination이나 현재 이력 필터에서 검색하지 않고 단건 safe summary API로 복원한다. 선택한 후보가 오래됐거나 실패 상태여도 URL이 유효하고 권한 범위 안이면 같은 결과를 유지해야 한다. workflow, target node 또는 deep link 식별자가 바뀌면 이전 화면 세션의 baseline과 compare result를 초기화한다.

검증 완료 후 모달 하단에는 다음 액션을 제공한다.

| 버튼 | 동작 |
| --- | --- |
| `적용하기` | 성공한 exact candidate settings를 현재 target LLM node draft에 적용한다. schema failed 또는 downstream incompatible이면 비활성화한다. |
| `상세 비교 분석하기` | 같은 experiment/candidate를 기존 Cost Optimizer 결과 분석 화면에서 연다. |
| `닫기` | 결과를 이력에 남기고 모달만 닫는다. draft는 바꾸지 않는다. |

모달 본문은 결과가 길어지면 내부 세로 스크롤을 제공하고, 하단 버튼 영역은 항상 접근할 수 있도록 고정한다. loading 중 중복 실행을 막고, 비용이 발생하는 실제 LLM 호출임을 실행 전에 안내한다.

### FR-014. 배포별 자동 파라미터 최적화

배포 전에 사용자는 LLM 노드별 비용 최적화와 별도로, 배포된 workflow의 운영 로그를 수집할지 결정할 수 있어야 한다.

- 배포 모달은 설명 입력 다음 단계에서 `운영 비용 자동 최적화`를 설정한다.
- 사용자는 대상 LLM 노드, 자동 점검 주기(`20~200회`, 기본 `50회`), 월간 검증 예산(`$0.5~$10`, 기본 `$3`)을 정한다.
- 수집 대상은 배포 후 `api`, `webhook`, `scheduler`, `app` 실행에서 성공한 LLM node run이다. Test Sidebar와 수동 편집 테스트 실행은 포함하지 않는다.
- 여러 LLM 노드를 선택하면 각 노드의 수집 수가 모두 점검 주기에 도달했을 때만 `점검 준비 완료`가 된다. 어느 한 노드의 운영 표본이 부족하면 계속 수집 상태다.
- 자동 최적화가 수집하는 후보는 응답 길이(`max_tokens`)와 RAG context 설정이다. 모델 선택, 자동 모델 라우팅, fallback 모델, 작성자 prompt는 이 기능이 변경하지 않는다.
- 운영 현황의 비용·예산 사용률·비용 위험 신호는 기존 비용 관측 기능이다. 자동 최적화의 수집 횟수와 월간 검증 예산은 별도 컬럼과 별도 상태로 표시한다.
- 현재 단계에서 주기 도달은 추천/검증을 실행할 수 있는 조건을 뜻한다. 후보 LLM 재실행은 기존 Cost Optimizer의 명시적 `테스트하기` 흐름으로만 발생하며, 수집 자체는 비용을 발생시키지 않는다. 자동 최적화가 켜진 배포의 대상 LLM node를 기준으로 검증하면 후보 실행 비용과 품질 judge 비용만 월간 검증 사용액에 누적한다. 기준 로그 조회와 평소 배포 운영 실행 비용은 이 사용액에 포함하지 않는다.
- 월간 사용액이 한도에 도달한 배포는 새 추천 검증을 시작하지 못한다. 이미 시작한 검증의 실제 비용은 실행 완료 뒤에 기록되므로, 마지막 검증 한 건으로 한도를 조금 넘을 수는 있다.

자동 최적화 상태는 다음과 같다.

| 상태 | 의미 |
| --- | --- |
| `미사용` | 해당 배포에서 자동 최적화 수집을 켜지 않았다. |
| `수집 중` | 대상 LLM 노드의 성공 운영 로그가 점검 주기보다 적다. |
| `점검 준비 완료` | 대상 노드마다 필요한 운영 로그가 모였다. 추천 후보를 검토/검증할 수 있다. |
| `월 예산 도달` | 실제 검증 비용 누적이 월 한도에 도달해 새 검증을 시작할 수 없다. |
| `일시 중지`/`점검 실패` | 운영자가 중지했거나 안전한 점검 상태를 만들 수 없었다. |

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
| Priority 1 | 품질 점수 rubric/가중치 | instruction fulfillment, relevance/completeness, clarity/consistency, RAG groundedness를 어떤 비율로 100점에 합산할지 | 가중치가 제품의 품질 정의가 되며 node 유형마다 적합도가 다르다 | 1차는 node output contract 기반 공통 rubric을 사용하되 정확한 가중치는 구현 전 확정한다 |
| Priority 1 | 품질 점수 경고 기준 | baseline 대비 몇 점 하락 또는 어느 confidence부터 적용 확인을 요구할지 | 너무 느슨하면 품질 저하를 놓치고 너무 엄격하면 비용 절감 후보를 적용하지 못한다 | 품질 점수 단독 hard block은 금지하고, threshold 미확정 동안 하락 또는 low confidence이면 항상 확인을 요구한다 |
| Priority 2 | 품질 judge 모델 선택 | organization에 여러 provider/model credential이 있을 때 어떤 모델을 judge로 사용할지 | judge 품질과 빠른 검증 비용이 달라진다 | 현재 사용자가 실행 가능한 모델 중 별도 evaluator allowlist를 두고, 없으면 품질 평가만 `unavailable`로 처리한다 |
| Priority 2 | 빠른 검증 baseline 범위 | 최신 성공 기록을 현재 active deployment/config cohort로 제한할지 전체 성공 기록에서 찾을지 | 과거 설정의 로그를 기준으로 추천 후보를 비교하면 결과 해석이 어긋난다 | active deployment와 node setting fingerprint가 같은 최신 성공 운영 로그로 제한한다 |
| Priority 3 | 자동 추천 | 가격표 기반 단발 추천 화면을 별도로 둘지 | 정책 기반 자동 라우팅과 겹치면 사용자가 실행 정책과 단발 추천을 혼동할 수 있다 | FR-011은 정책 기반 자동 라우팅으로 결정하고, 단발 추천 화면은 후속으로 분리한다 |
| Priority 3 | 모델 라우팅 정책 세부 gate | 정책 자동 반영의 정확한 schema/downstream/fallback/confidence 기준값을 어디까지 고정할지 | gate가 느슨하면 품질이 흔들리고, 너무 엄격하면 비용 절감 효과가 낮다 | 기본 원칙은 품질 gate 통과 시 조건부 자동 반영, 미통과 시 `pending_review`로 둔다 |
| Priority 3 | 최적화 에이전트 | 에이전트가 어떤 근거로 모델/프롬프트/파라미터 최적화 후보를 제안할지 | 추천 자체도 비용이 들고 잘못된 추천은 workflow 품질을 해칠 수 있다 | 후속 기능으로 분리하고 자동 적용은 금지한다 |
| Priority 3 | cache/budget | LLM cache와 budget guardrail을 1차 구현에 넣을지 | 실제 비용 절감 효과는 크지만 범위가 커진다 | 별도 follow-up 이슈로 분리한다 |
