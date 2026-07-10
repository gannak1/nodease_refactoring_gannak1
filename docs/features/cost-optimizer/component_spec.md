# Cost Optimizer Component Spec

Status: Draft
Verified Against: feature/mba-166 @ d9eeed80c47dcd9988c5453c2332b0e8c17cf921

## Purpose

이 문서는 `requirements.md`의 FR-001부터 FR-012까지를 화면과 컴포넌트 관점에서 구현 가능한 형태로 정리한다.
FR-011 모델 라우팅은 LLM 노드 상세 화면의 `자동 모델 라우팅` 토글과 policy status panel로 다룬다. 자동 라우팅 ON 상태에서는 실행 시점에 active policy로 모델을 선택하고, judge LLM은 정책 갱신 시점에만 호출한다.

Cost Optimizer UI는 workflow 전체 비교 화면이 아니라, LLM 노드 상세 화면에서 시작하는 LLM 노드 단위 A/B 테스트 흐름이다.

현재 구현 기준으로 `최적화`와 `비교 분석 테스트`는 LLM 노드 상세 상단의 별도 액션이다. `최적화`는 추천 모달을 열고, 추천 모달의 `테스트하기`는 baseline을 자동 선택하지 않은 채 Cost Optimizer workspace로 이동한다. `비교 분석 테스트`는 사용자가 baseline 목록에서 기준 실행을 직접 선택하는 전용 workspace로 이동한다.

## FR Mapping

| FR | 화면/컴포넌트 | UI 책임 |
| --- | --- | --- |
| FR-001 | LLM node detail action | LLM 노드에서만 A/B 테스트 진입 액션을 제공한다. |
| FR-002 | Baseline log picker | baseline 목록에서 사용자가 A 기준 실행 로그를 직접 선택한다. |
| FR-003 | Candidate editor | B 후보의 모델, prompt, parameter, 출력 형식을 편집한다. |
| FR-004 | Baseline input lock display | A baseline 입력이 B 후보 실행 입력으로 고정됨을 보여준다. |
| FR-005 | Hybrid compare flow | A는 재실행하지 않고 B만 실행하는 비교 흐름을 안내한다. |
| FR-006 | A/B compare workspace | A, B, Inspector 3영역으로 결과와 trace를 비교한다. |
| FR-007 | Downstream compatibility badge | downstream 호환성을 3상태로 표시하고 의미를 설명한다. |
| FR-008 | Apply candidate action | 선택한 B 후보 설정을 현재 LLM 노드 draft에 적용한다. |
| FR-009 | Cost/usage display | 비교 실행 비용이 기록된다는 사실과 후보별 비용을 표시한다. |
| FR-010 | Permission-gated UI | builder 이상이 아니면 A/B 테스트와 적용 액션을 막는다. |
| FR-011 | Model routing policy controls / model-routing route | LLM 노드 상세 화면에서 자동 모델 라우팅 ON/OFF와 정책 상태를 표시하고, 전용 model-routing 화면에서 검증된 후보 실험 이력 기반 추천을 보여준다. |
| FR-012 | Optimization recommendation modal | LLM 노드 상세 화면의 `최적화` 버튼으로 추천 모달을 열고, 추천 근거와 위험도를 확인한 뒤 직접 정책 적용 또는 A/B 후보 실험으로 연결한다. |

## Implementation Tracking

현재 문서는 Cost Optimizer UI 설계 기준과 구현 추적 상태를 함께 기록한다. 실제 파일 경로는 기존 workflow editor 구조에 맞춰 조정할 수 있다.

| FR | 주요 컴포넌트 | 예상 코드 위치 | 구현 상태 | 테스트 코드 | 테스트 통과 여부 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | LLM node detail action | `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerEntryAction.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx` | 통과 |
| FR-002 | Baseline selection, baseline log picker | `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerBaselineSelection.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr2-baseline-selection.test.tsx` | 통과 |
| FR-003 | Candidate editor, LLM node setting | `apps/client/app/features/workflow/components/costOptimizer/NodeSettingsComparisonPanel.tsx`, `apps/client/app/features/workflow/components/nodes/llm/components/LLMNodePanel.tsx`, `apps/client/app/features/workflow/components/nodes/llm/components/LLMReferenceSidePanel.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr3-candidate-editor.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr3-llm-node-routing.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr3-rag-cost-options.test.tsx` | 통과 |
| FR-004 | Baseline input lock display | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr4-fr5-hybrid-compare-flow.test.tsx` | 통과 |
| FR-005 | Hybrid compare flow state | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr4-fr5-hybrid-compare-flow.test.tsx` | 통과 |
| FR-006 | A/B compare workspace, Inspector | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | 통과 |
| FR-007 | Downstream compatibility badge | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr7-downstream-compatibility.test.tsx` | 통과 |
| FR-008 | Apply candidate action | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr8-apply-flow.test.tsx` | 통과 |
| FR-009 | Cost/usage metric display | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr9-usage-display.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr9-experiment-history-api-client.test.ts` | 통과 |
| FR-010 | Permission-gated UI | `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerEntryAction.tsx`, `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | 통과 |
| FR-011 | Model routing policy controls, model-routing recommendation route, refresh result summary | `apps/client/app/features/workflow/components/nodes/llm/components/LLMNodePanel.tsx`, `apps/client/app/features/workflow/api/workflowApi.ts`, `apps/client/app/features/workflow/types/Api.ts`, `apps/client/app/modules/[id]/model-routing/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr3-llm-node-routing.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr2-entry-to-baseline-connection.test.tsx` | policy toggle/주기 저장, manual refresh 요청, 마지막 judge 결과·비용 표시 검증 |
| FR-012 | Optimization recommendation modal | `apps/client/app/features/workflow/components/costOptimizer/OptimizationRecommendationModal.tsx`, `apps/client/app/features/workflow/components/nodes/llm/components/LLMNodePanel.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr8-apply-api-client.test.ts`, `apps/client/app/features/workflow/tests/costOptimizer/fr2-entry-to-baseline-connection.test.tsx` | 통과 기록 있음 |

## Screens

### LLM Node Detail

관련 FR: FR-001, FR-010

LLM 노드 상세 화면에는 A/B 테스트 진입 액션과 자동 모델 라우팅 정책 컨트롤을 제공한다.

- A/B 테스트 진입 액션과 자동 모델 라우팅 컨트롤은 `llmNode`에서만 표시한다.
- builder 이상 권한이 없는 사용자는 액션과 정책 수정 컨트롤을 비활성화한다.
- 비활성화 상태에는 권한 부족 사유를 표시한다.
- LLM 노드 설정이 저장되지 않았거나 draft가 오래된 경우, 비교 시작 전에 현재 draft 저장 또는 저장 필요 안내를 표시한다.

#### Cost Optimizer Entry And Model Routing Placement

A/B 테스트 진입 액션은 LLM 노드 상세 패널의 상단 헤더 우측 보조 액션 영역에 배치한다. 자동 모델 라우팅 토글과 정책 상태 panel은 모델 선택 영역 상단에 배치한다.

- 위치: 노드 제목, 노드 타입, 상태 badge가 표시되는 헤더 영역의 우측
- 라벨: `A/B 테스트`
- 아이콘: 비용/분석 의미가 명확한 기존 icon set 아이콘
- Tooltip: `이 LLM 노드의 비용과 품질을 같은 입력 기준으로 비교합니다.`
- 액션 위계: 저장, 삭제 같은 기본 편집 액션보다 낮은 보조 액션으로 표시한다.

버튼 상태는 다음과 같이 처리한다.

| 상태 | 표시 | 동작 |
| --- | --- | --- |
| target node가 `llmNode`가 아님 | 미노출 | Cost Optimizer 진입 불가 |
| builder 이상 권한 있음 | 활성화 | baseline 선택 단계로 이동 |
| builder 이상 권한 없음 | disabled | `Builder 권한이 필요합니다.` 안내 |
| baseline 실행 로그 없음 | 활성화 또는 disabled | 클릭 시 `비교할 실행 로그가 없습니다. 먼저 테스트 실행을 완료해 주세요.` 안내 |
| 저장되지 않은 draft 있음 | 활성화 | 클릭 시 `현재 노드 설정을 저장한 뒤 비교를 시작할 수 있습니다.` 안내 |

버튼 클릭 후에는 바로 적용하지 않는다. baseline 선택과 B 후보 비교 단계를 거쳐 결과를 확인한 뒤에만 현재 노드 설정에 적용할 수 있다.

### Baseline Selection

관련 FR: FR-002, FR-004, FR-005

`비교 분석 테스트` 또는 추천 모달의 `테스트하기`를 누르면 A baseline 선택 화면을 먼저 연다.

현재 baseline 선택 화면은 최신 로그 CTA로 baseline을 자동 고정하지 않는다. 화면은 검색/필터/정렬 가능한 baseline log picker를 바로 보여주고, 사용자가 특정 row를 직접 선택해야 A/B workspace가 열린다.

baseline row는 다음 정보를 표시한다.

- 실행 시각
- 모델
- 토큰
- 비용
- 실행 시간
- 입력 preview
- 출력 preview
- trace 존재 여부
- downstream 호환성 상태
- 비교 가능 여부

### Baseline Log Picker

관련 FR: FR-002, FR-004, FR-007

Baseline log picker는 target LLM node가 성공적으로 완료되고 output preview와 usage summary를 모두 제공할 수 있는 실행 로그만 보여준다. 실패한 node run, output preview가 없는 node run, usage summary가 없는 node run은 baseline 후보로 표시하지 않는다.

baseline row의 기준 식별자는 `workflow_node_runs.id`다. UI는 이를 사용자에게 직접 노출하지 않지만, 같은 workflow run 안에 여러 node 기록이 있을 수 있으므로 내부 선택 값은 workflow run id가 아니라 node run id를 사용한다.

각 row는 다음 정보를 표시한다.

- 실행 시각
- workflow run 상태
- target LLM node 상태: 항상 success
- 사용 모델
- target LLM node 비용
- target LLM node 토큰
- target LLM node 실행 시간
- 입력 preview
- 출력 preview
- trace 존재 여부
- downstream 호환성 상태
- input 복원 가능 여부
- 비교 가능 여부

필터와 정렬은 다음을 지원한다.

- 모델 필터
- 날짜 범위 필터
- 검색어: 입력/출력 preview 기준
- 정렬: 최신순, 비용 높은순, 비용 낮은순, 토큰 높은순, 실행 시간 긴순
- 비교 가능 여부 필터: 전체, 비교 가능, 비교 불가

Baseline을 선택하면 A baseline input은 잠금 상태로 표시한다. 사용자는 A 입력을 직접 수정하지 않는다.

input을 복원할 수 없는 baseline row는 목록에 표시하되 `비교 불가` badge를 붙인다. 해당 row는 상세 확인은 가능하지만 A/B compare workspace 진입 또는 B 후보 실행에 사용할 수 없다.

output preview 또는 usage summary가 없는 baseline row는 목록에 표시하지 않는다.

비교 불가 row의 안내 문구:

```text
입력 기록이 보관 기간 만료 또는 보안 정책으로 인해 복원되지 않아 이 실행 로그로는 A/B 테스트를 시작할 수 없습니다.
```

### A/B Compare Workspace

관련 FR: FR-003, FR-004, FR-005, FR-006, FR-009

A/B compare workspace는 특정 workflow의 특정 LLM node에 종속된 전용 작업 화면이다. 사용자는 LLM 노드 상세 화면의 A/B 테스트 진입 액션으로 이 workspace에 진입한다.

현재 프론트 구현은 A/B compare workspace를 workflow editor 안의 중첩 패널이 아니라 전용 route로 둔다.

- Route: `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx`
- 진입 액션: `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerEntryAction.tsx`
- baseline 선택: `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerBaselineSelection.tsx`
- A/B 공통 설정 패널: `apps/client/app/features/workflow/components/costOptimizer/NodeSettingsComparisonPanel.tsx`
- 고급 설정 재사용 패널: `apps/client/app/features/workflow/components/nodes/llm/components/LLMParameterSidePanel.tsx`
- 지식 베이스 재사용 패널: `apps/client/app/features/workflow/components/nodes/llm/components/LLMReferenceSidePanel.tsx`
- 설정 변환 모델: `apps/client/app/features/workflow/components/costOptimizer/costOptimizerPlaygroundModel.ts`

workspace 상단에는 context bar를 둔다.

- workflow 이름
- target LLM node 이름
- workspace mode switch: `실험 설정`, `결과 분석`
- 선택된 baseline 실행 시각
- 같은 입력 기준 badge
- downstream 호환성 badge
- B 후보 실행 액션
- 현재 노드에 적용 액션

workspace의 `워크플로우로 돌아가기`와 baseline 선택 단계의 `닫기`는 단순 workflow 화면이 아니라 A/B 테스트를 시작한 target LLM node 상세 화면으로 돌아간다. 프론트 route는 `/modules/{workflowId}?node={nodeId}` 형식을 사용한다.

A/B compare workspace는 같은 route 안에서 두 가지 mode를 제공한다.

- `실험 설정`: A baseline을 고정하고 B candidate 설정을 편집하는 mode다.
- `결과 분석`: B 실행 결과와 비교 리포트를 확인하고 적용 여부를 판단하는 mode다.

기준 baseline을 선택하기 전에는 `실험 설정`/`결과 분석` mode switch, B candidate, 기준 실행 정보 패널을 열지 않는다. 첫 화면은 A/B 테스트 기준 선택에 집중한다. 사용자가 baseline을 선택하면 workspace가 `실험 설정` mode로 열리고, 그때부터 B candidate와 기준 실행 정보 패널이 표시된다.

기본 workspace mode는 `실험 설정`이다. 사용자가 B 후보를 실행해 리포트가 생성되면 `결과 분석` mode로 이동할 수 있어야 한다. 아직 실행한 B 후보가 없는 상태에서 `결과 분석` mode로 이동하면 실행 대기 안내를 표시한다.

`실험 설정` mode 본문은 3영역 레이아웃이다.

- 왼쪽: A 실행 시점 옵션
- 가운데: B candidate
- 오른쪽: 기준 실행 정보

workspace는 B 후보 실험 루프를 같은 화면 안에서 지원한다.

1. A baseline을 고정한다.
2. B 후보 설정을 편집한다.
3. B 후보를 실행한다.
4. A/B 결과를 비교한다.
5. B 후보 설정을 다시 편집한다.
6. 같은 baseline으로 B 후보를 다시 실행한다.
7. 만족스러운 후보를 현재 노드에 일괄 적용한다.

B 후보 재실행을 위해 baseline picker를 다시 열거나 workspace를 닫게 해서는 안 된다.

### Model Routing Policy Controls

관련 FR: FR-011

LLM 노드 상세 화면은 자동 모델 라우팅을 별도 route가 아니라 노드 설정 안의 정책 컨트롤로 제공한다.

- 위치: LLM 노드 상세 패널의 모델 설정 영역 상단
- 라벨: `자동 모델 라우팅`
- 보조 설명: `저장된 정책으로 실행 시점 모델을 선택합니다. Judge는 정책 갱신 시에만 호출됩니다.`
- 권한: builder 이상에서만 수정 가능

자동 라우팅 OFF 상태:

- 기존 기본 모델 선택 UI를 표시한다.
- 기존 fallback 모델 선택 UI를 표시한다.
- runtime은 저장된 `model_id`와 `fallback_model_id`를 사용한다.
- 정책 상태 panel은 숨기거나 `자동 라우팅 꺼짐` summary만 표시한다.
- task type 선택 UI는 표시하지 않는다.

자동 라우팅 ON 상태:

- 기본 모델 선택 UI를 숨긴다.
- fallback 모델 선택 UI를 숨긴다.
- active policy 상태 panel을 표시한다. panel은 `GET /model-routing/policy` 응답을 우선 사용하고, 배포 policy가 아직 없을 때만 draft의 legacy JSON summary를 보조 표시한다.
- runtime은 active policy를 사용해 모델을 선택한다.
- active policy가 없으면 `collecting` 상태로 표시하고, runtime은 보수적으로 저장된 안정 모델을 사용한다.
- judge LLM은 일반 실행 중 호출하지 않는다.

정책 상태 panel은 다음 정보를 보여준다.

- 정책 상태: `collecting`, `active`, `refreshing`, `pending_review`, `failed`
- active policy version
- 현재 active policy의 기본 선택 모델과 fallback 모델
- 선택 사유 또는 reason code
- 마지막 정책 갱신 결과
- 마지막 정책 갱신 시각
- 다음 자동 갱신까지 남은 운영 실행 수: 예) `13/20회 수집됨`
- `자동 정책 갱신하기` 버튼

정책 상태별 UI:

| 상태 | 표시 | 사용자 액션 |
| --- | --- | --- |
| `off` | 자동 라우팅 꺼짐 | 토글 ON |
| `collecting` + policy id 없음 | 첫 배포 운영 실행 대기 | `자동 정책 갱신하기` disabled, `첫 배포 운영 실행이 완료된 뒤 정책을 갱신할 수 있습니다.` 안내 |
| `collecting` + policy id 있음 | 운영 로그 수집 중, `n/20회` | 수동 갱신 가능. 로그/후보 근거가 부족하면 최종 결과에서 실패 또는 기존 policy 유지 안내 |
| `active` | active policy로 실행 중 | 수동 갱신 가능 |
| `refreshing` | 정책 갱신 중 | 중복 갱신 버튼 disabled |
| `pending_review` | 새 정책 보류, 기존 정책 유지 | 보류 사유 확인 |
| `failed` | 마지막 갱신 실패 | 실패 사유 확인 후 재시도 |

`자동 정책 갱신하기` 버튼을 누르면 `POST /model-routing/policy/refresh`로 즉시 정책 갱신 작업을 예약한다.

- 요청 중에는 버튼을 disabled 처리한다. policy id가 없는 초기 `collecting` 상태에서도 disabled 처리한다.
- 요청 성공은 judge 완료가 아니라 `refreshing` 상태 전환을 뜻한다. UI는 policy 조회를 다시 수행해 새 policy version과 최종 적용 결과를 표시한다.
- `kept_current`이면 정책 재평가는 끝났지만 검증된 변경 후보가 없어 기존 active policy를 유지했다는 문구를 표시한다.
- `pending_review`이면 새 정책이 운영에 반영되지 않았고 기존 active policy가 유지된다는 문구를 표시한다.
- 실패하면 로그 부족, credential/model 사용 불가, judge 호출 실패 같은 safe reason을 표시한다.

정책 갱신 결과의 judge 호출 비용은 숨기지 않는다. UI는 policy update summary에서 judge 모델, token/cost, 갱신 trigger를 확인할 수 있어야 한다. 단 raw prompt, raw output, credential 원문, API key, raw trace payload는 표시하지 않는다.

현재 구현은 policy 조회 응답의 `last_update` safe summary를 사용해 `최근 정책 점검`, 자동/수동 갱신 여부, `반영됨`/보류/실패 상태, judge 모델과 judge 비용을 표시한다. 사용자는 judge usage log id를 원문 로그로 열람하지 않고 추적 식별자로만 확인한다.

자동 라우팅 토글과 점검 주기 slider는 local draft만 바꾸지 않는다. 사용자가 토글을 바꾸거나 slider 조작을 마치면 `PATCH /model-routing/policy`로 `enabled`, `refresh_every_runs`를 저장한다. 현재 배포가 없거나 현재 deployment snapshot에 자동 라우팅 ON 설정이 포함되지 않은 경우에는 draft 설정은 저장되지만 policy panel은 `collecting`으로 남고, 해당 설정을 포함해 다시 배포한 뒤 첫 LLM node 성공 실행이 policy row를 생성한다.

- 모델 목록 API: `GET /api/v1/llm/my-models`
- 모델 선택 컴포넌트: 기존 `ModelSelectDropdown` 계열을 우선 재사용한다.
- 사용할 수 없는 credential/model은 목록에서 제외하는 것을 우선한다.
- 일반 LLM 노드 상세 화면과 Cost Optimizer B 후보 화면은 같은 workflow LLM 모델 필터를 사용한다.
- alias 계열 모델만 기본 노출하고 날짜 suffix 모델은 숨긴다.
- embedding, image, audio, realtime, moderation, tts, whisper, transcribe, sora, search-only 계열은 숨긴다.
- 목록에 보였더라도 compare API에서 최종 검증에 실패하면 실패 후보 또는 validation error로 표시한다.

prompt 입력 영역은 기존 노드 상세 편집과 같이 변수 삽입을 지원한다.

- upstream output variable을 system/user/assistant prompt에 삽입할 수 있어야 한다.
- 변수 삽입 UI는 기존 `VariableTokenEditor` 계열 재사용을 우선한다.
- 등록되지 않은 변수는 실행 전 validation message로 표시한다.
- B candidate에서 프롬프트 마법사를 사용할 수 있다.

`고급 설정` 탭은 기존 LLM 노드 상세 편집의 LLM parameter 패널과 같은 구조를 사용한다. 기존 `LLMParameterSidePanel`을 재사용하되, A/B workspace에서는 실제 workflow node store를 직접 수정하지 않도록 controlled 경로를 사용한다.

- A baseline은 read-only로 실행 시점 parameter 설정을 보여준다.
- B candidate는 local candidate 상태만 수정한다.
- 기존 LLM node detail에서는 기존처럼 workflow store를 갱신한다.

`고급 설정` 탭에서 다루는 항목은 다음과 같다.

- `max_tokens` 편집
- `temperature` 편집
- `top_p` 편집
- `presence_penalty` 편집
- `frequency_penalty` 편집
- `stop` 편집

`지식 베이스` 탭은 기존 LLM 노드의 지식 베이스 설정 UI와 같은 구조를 사용한다. 기존 `LLMReferenceSidePanel`을 재사용하되, A/B workspace에서는 실제 workflow node store를 직접 수정하지 않도록 controlled 경로를 사용한다.

- A baseline은 read-only로 실행 시점 Knowledge/RAG 설정을 보여준다.
- B candidate는 local candidate 상태만 수정한다.
- 기존 LLM node detail에서는 기존처럼 workflow store를 갱신한다.

지식 베이스 탭에서 다루는 항목은 다음과 같다.

- Knowledge Base 선택
- `topK` 편집
- `scoreThreshold` 편집
- 중복 근거 제거
- 참조 문서 길이 제한
- 검색 문서 압축
- 답변 근거 확인

B candidate 영역은 다음 액션을 포함한다.

- B 후보 실행

고급 파라미터는 기본 설정 화면에 모두 펼쳐두지 않고 `고급 설정` 탭으로 분리한다. 사용자는 기본 옵션만으로 빠르게 비교할 수 있고, 필요한 경우 고급 설정 탭에서 세밀하게 조정한다.

JSON schema 편집 영역은 출력 형식이 JSON일 때 활성화한다. text 출력 형식에서는 schema 입력을 비활성화하거나 숨긴다.

JSON schema는 key-type 행 추가 UI로 편집한다. 사용자는 필드명, 타입, 필수 여부를 행 단위로 추가/수정/삭제한다. raw JSON schema 직접 편집은 1차 필수 UI가 아니다.

JSON schema type 후보는 다음만 제공한다.

- `string`
- `number`
- `boolean`
- `object`
- `array`

각 schema row는 다음 컨트롤을 가진다.

- field key input
- type select
- required checkbox
- delete row button

Nested schema는 `object` 또는 `array` 내부의 하위 field까지 편집하는 구조다. 1차 UI는 flat key-type row까지만 제공한다. `object`와 `array` 타입은 선택할 수 있지만 하위 field editor는 제공하지 않는다.

Knowledge Base 선택은 복수 선택을 허용한다.

고급 파라미터 validation은 기존 LLM node 고급 설정의 범위를 따른다.

- `temperature`: 0~2
- `top_p`: 0~1
- `max_tokens`: 1~8192
- `presence_penalty`: -2~2
- `frequency_penalty`: -2~2
- `stop`: 문자열 배열, 최대 4개

B 후보 실행 결과에는 다음을 표시한다.

- 실행 상태
- 출력 결과 preview
- prompt tokens
- completion tokens
- total tokens
- estimated cost
- latency
- error message
- JSON schema 검증 상태

B 후보 설정이 마지막 실행 이후 변경되면 기존 실행 결과는 stale 상태로 표시한다. 이때 결과는 참고용으로 남기되, 현재 설정에 대한 결과가 아니므로 `B 후보 실행`을 다시 유도한다.

B 후보 실행 버튼을 누르면 비교 리포트가 생성된다. 리포트는 A baseline과 B candidate의 출력, 비용, 토큰, latency, schema 검증 상태, retrieval summary, downstream 호환성 상태를 함께 보여준다. 사용자는 리포트를 본 뒤 B 후보 설정을 현재 노드에 적용할지 선택한다.

stale 상태는 다음 필드 중 하나라도 마지막 B 실행 이후 변경되면 발생한다.

- model
- fallback model
- auto routing state
- system/user/assistant prompt
- output format
- JSON schema
- LLM parameters
- Knowledge Base selection
- `topK`
- `scoreThreshold`
- 중복 근거 제거
- 참조 문서 길이 제한
- 검색 문서 압축
- 답변 근거 확인

화면은 A baseline과 B candidate가 같은 입력 기준이라는 점을 명확히 표시한다.

`결과 분석` mode는 편집 UI보다 비교 리포트 가독성과 적용 판단을 우선한다.

결과 분석 화면의 정보 구조는 다음 순서를 따른다.

1. 상단 이전 실험 이력 패널
2. 판단 요약
3. 핵심 지표 비교
4. A/B 출력 품질 비교
5. 상세 Inspector
6. 액션: `B 설정 다시 수정`, `현재 노드에 적용`

상단 이전 실험 이력 패널은 같은 baseline 기준으로 저장된 B 후보 실행 이력을 다시 확인하고, 분석 대상을 선택하는 영역이다. 결과 분석 화면의 주 콘텐츠는 아래의 선택된 실험 분석이므로, 이력 패널은 세로 공간을 과도하게 차지하면 안 된다.

상단 이전 실험 이력 패널은 다음 구조를 사용한다.

```text
[이전 실험 이력]                         [접기]
같은 baseline 기준으로 저장된 B 후보 실행 이력을 다시 확인합니다.

[시작일] [종료일] [실행자] [적용 여부] [후보 상태] [모델] [Schema] [Downstream]

┌──────────────┬──────────────┬───────┬──────┬──────┬────────┬────────┬────────────┐
│ 실행 시각     │ 테스트명      │ 모델  │ 비용 │ 토큰 │ 시간   │ Schema │ Downstream │
├──────────────┼──────────────┼───────┼──────┼──────┼────────┼────────┼────────────┤
│ 07.06 14:22  │ 비용 절감 v2  │ mini  │ ...  │ ...  │ ...    │ 통과   │ 검증 가능  │
│ 07.06 14:19  │ prompt 축약   │ mini  │ ...  │ ...  │ ...    │ 실패   │ 주의 필요  │
└──────────────┴──────────────┴───────┴──────┴──────┴────────┴────────┴────────────┘
```

이전 실험 이력은 card list가 아니라 dense table로 표시한다. 이력은 상세 콘텐츠가 아니라 선택/비교용 목록이므로, 같은 metric이 열 기준으로 정렬되어야 한다. 사용자는 비용, 토큰, latency, schema, downstream 상태를 row 간 빠르게 비교하고 하나의 후보를 선택할 수 있어야 한다.

이력 패널의 높이 정책은 다음을 따른다.

- 기본 상태는 화면 상단의 compact 영역으로 유지한다.
- 필터와 table을 포함하되, table body는 내부 스크롤을 사용한다.
- row height는 조밀하게 유지한다.
- 선택된 row는 배경색 또는 좌측 accent border로 표시한다.
- 방금 실행한 후보는 자동 선택하고 `방금 실행` 또는 `최신` badge를 표시한다.
- 이력 패널을 접으면 제목, 선택된 실험 요약, `펼치기` 액션만 남긴다.
- 이력 조회 실패 시 패널 안에 실패 안내를 표시하되, 이미 보유한 compare result가 있으면 아래 결과 분석은 유지한다.

상단 판단 요약은 B 후보를 현재 노드에 적용해도 되는지 먼저 말해준다. 상태는 다음 3개 라벨을 사용한다.

- `적용 후보로 적합`
- `주의 필요`
- `적용 비추천`

판단 요약은 다음 근거를 함께 표시한다.

- 비용 변화율
- prompt/completion/total token 변화율
- latency 변화
- B 실행 상태
- JSON schema 검증 상태
- downstream 호환성 상태

핵심 지표 비교는 A/B/변화값을 표 형태로 보여준다.

| 항목 | A baseline | B candidate | 변화 |
| --- | --- | --- | --- |
| 비용 | baseline cost | candidate cost | 절감/증가 금액과 비율 |
| prompt tokens | baseline prompt tokens | candidate prompt tokens | 증감 |
| completion tokens | baseline completion tokens | candidate completion tokens | 증감 |
| total tokens | baseline total tokens | candidate total tokens | 증감 |
| latency | baseline latency | candidate latency | 증감 |
| 실행 상태 | baseline status | candidate status | 성공/실패 변화 |
| Schema | baseline 기준 또는 `-` | candidate schema status | 통과/실패/미사용 |
| Downstream | baseline downstream | current compatibility | 검증 가능/주의 필요/검증 불가 |

출력 품질 비교는 A 출력과 B 출력을 나란히 보여준다.

- text 출력이면 전체 텍스트를 줄바꿈과 내부 스크롤로 표시한다.
- JSON 출력이면 field 단위로 펼쳐서 볼 수 있어야 한다.
- JSON field 표시명은 해당 node 실행 시점 JSON Schema의 `properties.{key}.title`이 있을 때만 사용한다. title이 없으면 원본 key를 그대로 표시하며, 공통 preview 컴포넌트에 workflow 도메인별 key-label mapping을 두지 않는다.
- JSON schema가 있으면 필수 field 충족 여부, 누락 field, type mismatch를 표시한다.
- 긴 값은 화면에서 임의로 `...` 처리하지 않는다. 패널 내부 스크롤을 사용한다.

상세 Inspector는 결과를 이해하기 위한 보조 영역이다. 사용자 기준 탭 라벨은 다음을 우선한다.

- `설정 차이`
- `근거/Trace`
- `후속 노드 영향`

현재 구현이 내부적으로 `A Trace`, `B Trace`, `Diff`, `Downstream`, `Settings` 같은 탭을 사용하더라도, 사용자에게 노출되는 라벨은 위 의미를 기준으로 정리한다.

B 실행 결과가 없으면 B 결과 영역에는 `B 실행 후 결과 분석이 표시됩니다.` empty state를 표시한다.

상단 이전 실험 이력 패널은 다음 필터를 제공한다.

- 시작일
- 종료일
- 실행자
- 적용 여부
- 후보 상태
- 모델
- Schema 상태
- Downstream 상태

### Parameter Recommendation Modal

관련 FR: FR-012

배포된 workflow 목록 또는 Cost Optimizer 추천 화면에서 `워크플로우 최적화 권장` 항목을 누르면 최적화 추천 모달을 열 수 있다.

모달은 workflow 전체 요약과 target LLM node별 추천안을 구분해서 보여준다.

첫 화면에는 다음 정보를 표시한다.

- workflow 이름
- 예상 월 비용
- 예상 절감 가능 범위
- 추천 대상 LLM node 수
- 추천안이 `정책 갱신 가능`인지 `A/B 실험 필요`인지

추천안 row는 다음 정보를 제공한다.

| UI 항목 | 설명 |
| --- | --- |
| 추천 유형 | `max_tokens 조정`, `temperature 안정화`, `RAG context 사용량 조정`, `프롬프트 축소 후보`, `모델 라우팅 정책 갱신` |
| 현재값 | 현재 LLM node 설정값 |
| 추천값 | 추천 후보값 |
| 예상 효과 | 비용, token, latency 중 설명 가능한 효과 |
| 근거 | sample 수, p95 token, context token 비중, schema/downstream 성공률 같은 safe summary |
| 위험도 | `낮음`, `중간`, `높음` |
| 액션 | `후보 실험 만들기`, `정책 갱신`, `보류` |

파라미터 추천 row의 기본 액션은 `후보 실험 만들기`다.

- `max_tokens`, `temperature`, `top_p`, `frequency_penalty`, RAG context 설정은 직접 draft에 적용하지 않는다.
- 사용자가 row를 선택하고 `후보 실험 만들기`를 누르면 현재 LLM node 설정 복사본에 `candidate_patch`를 merge한 B candidate를 만들고 기존 A/B workspace로 이동한다.
- A/B workspace에서 B 후보를 실행하고 결과 분석을 확인한 뒤에만 `현재 노드에 적용`을 사용할 수 있다.

모달 하단 버튼은 다음을 사용한다.

| 버튼 | 동작 |
| --- | --- |
| `선택 항목으로 실험 만들기` | 선택된 파라미터 추천 row를 B candidate patch로 변환하고 Cost Optimizer A/B workspace로 이동한다. |
| `정책 갱신 적용` | 자동 모델 라우팅 정책처럼 draft node parameter를 직접 바꾸지 않는 항목에만 활성화한다. |
| `나가기` | 변경 없이 모달을 닫는다. |

`바로 적용`이라는 단일 버튼은 사용하지 않는다. 파라미터 추천은 품질 저하 가능성이 있으므로 직접 적용과 후보 실험 생성을 UI에서 분리해야 한다.

추천 근거는 raw prompt, raw completion, raw Knowledge chunk content, credential 원문을 표시하지 않는다. 긴 output 예시는 기존 A/B 결과 화면에서만 확인한다.

추천 상태는 다음과 같이 표시한다.

| 상태 | 조건 | UI |
| --- | --- | --- |
| `추천 가능` | sample 수와 usage/trace summary가 충분하다 | 추천 row와 `후보 실험 만들기` 활성화 |
| `근거 부족` | 운영 로그 또는 usage/trace가 부족하다 | 필요한 추가 실행 조건 표시 |
| `실험 필요` | 추천 근거는 있으나 품질 gate를 확인해야 한다 | A/B 후보 생성 CTA |
| `적용 비추천` | schema/downstream 실패, 비용 악화, RAG evidence 부족이 확인된다 | CTA 비활성화 또는 경고 |

### Candidate Settings Mapping

관련 FR: FR-003, FR-008

프론트 local draft, LLM node data, compare request, apply request는 다음 기준으로 매핑한다.

| UI/Local field | LLM node data | `POST /compare` field | `PATCH /apply` field | 비고 |
| --- | --- | --- | --- | --- |
| `model_id` | `data.model_id` | `candidate.model_id` | `candidate_settings.model_id` | 기존 모델 선택 목록을 재사용한다. |
| `fallback_model_id` | `data.fallback_model_id` | `candidate.fallback_model_id` | `candidate_settings.fallback_model_id` | 기본 모델과 같으면 validation 대상이다. |
| `auto_model_routing` | `data.auto_model_routing` | 사용하지 않음 | 사용하지 않음 | LLM 노드 자동 모델 라우팅 ON/OFF 저장값이다. ON이면 런타임은 active policy를 우선 평가한다. Cost Optimizer A/B 후보 설정에는 포함하지 않는다. |
| `model_routing_context` | `data.model_routing_context` | 사용하지 않음 | 사용하지 않음 | 런타임 policy rule 평가에 쓰는 명시적 일반 힌트다. 예: `customer_facing`, `node_task`. 도메인 키워드 목록은 여기에 넣지 않고 policy rule의 `when.keyword_any`에 저장한다. |
| `task_type` | 내부 기본값 | 내부 기본값 | `candidate_settings.task_type` | 사용자 입력으로 노출하지 않는다. 후속 라우터/분석 내부 판단값으로만 사용한다. |
| `system_prompt` | `data.system_prompt` | `candidate.system_prompt` | `candidate_settings.system_prompt` | 변수 삽입 지원. |
| `user_prompt` | `data.user_prompt` | `candidate.user_prompt` | `candidate_settings.user_prompt` | 변수 삽입 지원. |
| `assistant_prompt` | `data.assistant_prompt` | `candidate.assistant_prompt` | `candidate_settings.assistant_prompt` | 변수 삽입 지원. |
| `max_tokens` | `data.parameters.max_tokens` | `candidate.parameters.max_tokens` | `candidate_settings.parameters.max_tokens` | 1~8192. |
| `temperature` | `data.parameters.temperature` | `candidate.parameters.temperature` | `candidate_settings.parameters.temperature` | 0~2. |
| `top_p` | `data.parameters.top_p` | `candidate.parameters.top_p` | `candidate_settings.parameters.top_p` | 0~1. |
| `presence_penalty` | `data.parameters.presence_penalty` | `candidate.parameters.presence_penalty` | `candidate_settings.parameters.presence_penalty` | -2~2. |
| `frequency_penalty` | `data.parameters.frequency_penalty` | `candidate.parameters.frequency_penalty` | `candidate_settings.parameters.frequency_penalty` | -2~2. |
| `stop` | `data.parameters.stop` | `candidate.parameters.stop` | `candidate_settings.parameters.stop` | 최대 4개 문자열. |
| `output_format` | node output option | `candidate.output_format.type` | `candidate_settings.output_format.type` | `text` 또는 `json`. |
| `json_schema` | node output option | `candidate.output_format.schema` | `candidate_settings.output_format.schema` | JSON output일 때만 사용. |
| `knowledgeBases` | `data.knowledgeBases` | `candidate.knowledge.knowledge_base_ids` | `candidate_settings.knowledge.knowledge_base_ids` | id 배열로 변환한다. |
| `topK` | `data.topK` | `candidate.knowledge.top_k` | `candidate_settings.knowledge.top_k` | B 실행 시 새 retrieval에 사용한다. |
| `scoreThreshold` | `data.scoreThreshold` | `candidate.knowledge.score_threshold` | `candidate_settings.knowledge.score_threshold` | B 실행 시 새 retrieval에 사용한다. |
| `dedupeRetrievedContext` | `data.dedupeRetrievedContext` | `candidate.knowledge.dedupe_retrieved_context` | `candidate_settings.knowledge.dedupe_retrieved_context` | 중복 검색 근거를 제거한다. |
| `retrievedContextMaxChars` | `data.retrievedContextMaxChars` | `candidate.knowledge.retrieved_context_max_chars` | `candidate_settings.knowledge.retrieved_context_max_chars` | author prompt가 아니라 Knowledge/RAG context만 제한한다. |
| `retrievedContextCompression` | `data.retrievedContextCompression` | `candidate.knowledge.retrieved_context_compression` | `candidate_settings.knowledge.retrieved_context_compression` | `off`, `light`, `strong`. |
| `answerGroundingCheck` | `data.answerGroundingCheck` | `candidate.knowledge.answer_grounding_check` | `candidate_settings.knowledge.answer_grounding_check` | `off`, `basic`, `strict`. |

### Inspector

관련 FR: FR-006, FR-007, FR-009

Inspector는 A/B 비교를 이해하기 위한 상세 정보 영역이다. 결과 분석 화면에서 Inspector는 판단 요약의 근거를 확인하는 보조 영역이어야 하며, 판단 요약보다 먼저 읽혀서는 안 된다.

Inspector는 탭 구조를 사용한다.

- `설정 차이`
- `근거/Trace`
- `후속 노드 영향`

`설정 차이`는 A 실행 시점 옵션과 B candidate 설정의 차이를 보여준다.

- 모델 차이
- fallback 모델 차이
- prompt 차이
- parameter 차이
- 출력 형식 차이
- JSON schema 차이
- Knowledge/RAG 설정 차이

`근거/Trace`는 A와 B의 실행 근거를 함께 보여준다.

- input
- output
- prompt/messages 요약
- token/cost/latency breakdown
- A/B LLM usage trace
- A/B RAG retrieval summary
- error

`후속 노드 영향`은 downstream 호환성 상태와 계약 검증 결과를 보여준다.

- 검증 가능
- 주의 필요
- 검증 불가
- 검사한 downstream node
- 계약 검증 warning
- side-effect node 자동 실행 제외 안내

이 패널의 상태는 현재 graph만으로 계산한 값이 아니라, A baseline 생성/조회 시점에 만든 downstream snapshot과 B candidate output의 contract check 결과를 표시한다. snapshot이 없는 legacy/retention 데이터는 `판정 불가`로 표시하고, 사용자가 현재 workflow 전체 테스트 실행으로 확인해야 함을 안내한다.

### Candidate Apply Flow

관련 FR: FR-008, FR-010

사용자는 B 후보 실행 결과를 확인한 뒤 `현재 노드에 적용`을 누를 수 있다.

적용 전 확인 모달은 다음을 보여준다.

- 변경되는 모델
- 변경되는 prompt
- 변경되는 parameter
- 변경되는 출력 형식
- 변경되는 JSON schema
- 변경되는 Knowledge/RAG 설정
- downstream 호환성 상태
- 추가 검증 필요 여부

`검증 가능`이 아닌 경우, 모달에서 현재 workflow 테스트 실행으로 최종 확인해야 함을 표시한다.

적용은 B 후보 설정 전체를 일괄 적용한다. 적용이 완료되면 현재 LLM node draft가 B 후보 설정으로 갱신된다.

## States

### Permission States

관련 FR: FR-010

- `builder_or_higher`: A/B 테스트 진입, B 후보 실행, 후보 적용 가능
- `not_builder`: A/B 테스트 진입과 후보 적용 불가

### Baseline States

관련 FR: FR-002

- `no_logs`: target LLM node 실행 로그 없음
- `loading_latest`: 최신 baseline 조회 중
- `latest_loaded`: 최신 baseline 선택 완료
- `picker_open`: 이전 로그 선택 화면 열림
- `baseline_selected`: baseline 선택 완료
- `baseline_input_unavailable`: baseline 기록은 있으나 target LLM node input 복원 불가
- `baseline_error`: baseline 조회 실패

### Candidate States

관련 FR: FR-003, FR-006

- `editing`: B 후보 편집 중
- `running`: B 후보 실행 중
- `success`: B 후보 실행 성공
- `schema_failed`: B 후보 LLM 호출은 성공했지만 JSON schema 검증 실패
- `failed`: B 후보 실행 실패
- `stale`: 마지막 B 실행 이후 후보 설정이 변경되어 결과가 현재 설정과 일치하지 않음
- `applied`: B 후보가 현재 node draft에 적용됨

### Downstream Compatibility States

관련 FR: FR-007

- `compatible`: 검증 가능
- `warning`: 주의 필요
- `incompatible`: 검증 불가
- `unknown`: 아직 판정 불가

## Interactions

### Start A/B Test

관련 FR: FR-001, FR-002, FR-010

1. 사용자가 LLM 노드 상세 화면에서 `A/B 테스트`를 누른다.
2. builder 이상 권한이 아니면 진입을 막는다.
3. baseline 선택 화면을 연다.
4. 사용자가 최신 로그 또는 이전 로그를 선택한다.
5. baseline input을 복원할 수 없으면 비교 불가 안내를 표시하고 A/B compare workspace로 이동하지 않는다.
6. baseline이 선택되면 A/B compare workspace로 이동한다.

### Run Candidate B

관련 FR: FR-003, FR-004, FR-005, FR-009

1. 사용자가 B 후보 설정을 편집한다.
2. 사용자가 `B 실행`을 누른다.
3. 화면은 A baseline input이 고정 입력으로 사용된다는 점을 표시한다.
4. B 후보 실행 상태를 `running`으로 표시한다.
5. 실행 완료 후 비용, 토큰, latency, output, error를 표시한다.
6. B trace가 있으면 Inspector의 `B Trace` 탭을 활성화한다.

### Apply Candidate

관련 FR: FR-008, FR-010

1. B 후보가 성공 상태일 때 `현재 노드에 적용`을 활성화한다.
2. builder 이상 권한이 아니면 적용할 수 없다.
3. 적용 전 확인 모달을 표시한다.
4. 사용자가 확인하면 current draft의 target LLM node 설정을 갱신한다.
5. 적용 후 기존 workflow 저장/테스트 실행 흐름을 유지한다.

## Accessibility

- 모든 주요 액션은 버튼으로 제공하고 키보드 포커스가 가능해야 한다.
- downstream 호환성 상태는 색상만으로 구분하지 않고 텍스트 라벨을 함께 표시한다.
- 비용, 토큰, latency는 숫자만 나열하지 않고 단위를 포함한다.
- Inspector 탭은 키보드로 전환 가능해야 한다.
- 실행 중 상태는 spinner와 텍스트를 함께 표시한다.
