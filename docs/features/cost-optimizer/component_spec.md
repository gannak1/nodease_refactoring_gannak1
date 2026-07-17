# Cost Optimizer Component Spec

Status: Draft
Verified Against: feature/mba-198 @ 40c45fcc

## Purpose

이 문서는 `requirements.md`의 FR-001부터 FR-014까지를 화면과 컴포넌트 관점에서 구현 가능한 형태로 정리한다.
FR-011은 LLM 노드 상세 화면의 자동 라우팅 컨트롤과 Workflow-Aware 분석 상태로 다룬다. 사용자는 단순 ON/OFF가 아니라 `이 node가 라우팅에 적합한지`, `어떤 evidence가 부족한지`, `어떤 cohort에서 어떤 모델을 쓰는지`, `예상 순절감과 품질 근거가 무엇인지`를 확인할 수 있어야 한다.

Cost Optimizer UI는 workflow 전체 비교 화면이 아니라, LLM 노드 상세 화면에서 시작하는 LLM 노드 단위 A/B 테스트 흐름이다.

현재 구현 기준으로 `최적화`와 `비교 분석 테스트`는 LLM 노드 상세 상단의 별도 액션이다. `비교 분석 테스트`는 사용자가 baseline 목록에서 기준 실행을 직접 선택하는 전용 workspace로 이동한다. FR-013의 `최적화` 추천 모달 `테스트하기`는 별도 workspace로 즉시 이동하지 않고, 최신 비교 가능한 성공 실행을 자동 baseline으로 사용해 모달 안에서 빠른 검증 결과를 보여준다.

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
| FR-011 | Workflow-Aware routing controls / analysis / decision trace | 자동 라우팅 ON/OFF, 라우팅 적합성, evidence gap, semantic cohort별 policy, 예상 순절감, 실제 선택 모델과 Route 점수/fallback 근거를 보여준다. |
| FR-012 | Optimization recommendation modal | LLM 노드 상세 화면의 `최적화` 버튼으로 추천 모달을 열고, 추천 근거와 위험도를 확인한 뒤 직접 정책 적용 또는 A/B 후보 실험으로 연결한다. |
| FR-013 | Recommendation verification / compare quality row | 추천 모달과 일반 결과 분석 화면에서 baseline 대비 candidate 비용·속도·token·품질 점수·schema·downstream 결과를 보여주고 적용 또는 이력 재조회로 연결한다. |
| FR-014 | 배포별 자동 파라미터 최적화 | 배포 모달에서 운영 로그 수집·점검 주기·월간 검증 예산을 설정하고, 내 모듈 운영 현황에서는 비용 위험과 분리된 자동 최적화 상태를 관리한다. |

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
| FR-009 | Cost/usage metric display, experiment history | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx`, `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerHistoryPanel.tsx`, `apps/client/app/features/workflow/hooks/useCostOptimizerHistory.ts` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr9-usage-display.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr9-experiment-history-api-client.test.ts`, `apps/client/app/features/workflow/tests/costOptimizer/fr9-history-model.test.ts` | 통과 |
| FR-010 | Permission-gated UI | `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerEntryAction.tsx`, `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | 통과 |
| FR-011 | 기존 policy controls와 model-routing route | `apps/client/app/features/workflow/components/nodes/llm/components/LLMNodePanel.tsx`, `apps/client/app/modules/[id]/model-routing/[nodeId]/page.tsx` | 기반 구현 완료 | 기존 Cost Optimizer frontend tests | 토글, 주기, policy 상태, 추천 route 통과 |
| FR-011 | Runtime decision trace UI | `apps/client/app/features/workflow/components/modelRouting/ModelRoutingDecisionDetails.tsx`, `apps/client/app/features/workflow/components/editor/TestSidebar.tsx`, `apps/client/app/features/workflow/components/logs/LogDetail.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr11-semantic-routing-trace.test.tsx`, `apps/client/app/features/workflow/components/logs/LogDetail.test.tsx` | 통과 |
| FR-011 | Test Sidebar 실행 노드 상세 | `apps/client/app/features/workflow/components/editor/TestSidebar.tsx`, `apps/client/app/features/workflow/components/modelRouting/ModelRoutingDecisionDetails.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/test-sidebar-node-detail.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr11-semantic-routing-trace.test.tsx` | 이번 변경 targeted test |
| FR-011 | 적합성/evidence/policy diff UI | 기존 model-routing route 확장 | 구현 필요 | Workflow-Aware routing component tests | 미작성 |
| FR-012 | Optimization recommendation modal | `apps/client/app/features/workflow/components/costOptimizer/OptimizationRecommendationModal.tsx`, `apps/client/app/features/workflow/components/nodes/llm/components/LLMNodePanel.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr8-apply-api-client.test.ts`, `apps/client/app/features/workflow/tests/costOptimizer/fr2-entry-to-baseline-connection.test.tsx` | 통과 기록 있음 |
| FR-013 | Recommendation verification, compare quality row, history restore | `apps/client/app/features/workflow/components/costOptimizer/OptimizationRecommendationModal.tsx`, `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerHistoryPanel.tsx`, `apps/client/app/features/workflow/hooks/useCostOptimizerHistory.ts`, `apps/client/app/features/workflow/api/workflowApi.ts`, `apps/client/app/features/workflow/types/Api.ts`, `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr13-recommendation-inline-verification.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr13-recommendation-verification-api-client.test.ts`, `apps/client/app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | modal 검증, 일반 compare 품질 행, 평가 불가, 단건 비교 이력 복원 통과 |
| FR-014 | Deployment optimization step / management | `apps/client/app/features/workflow/components/deployment/ParameterOptimizationStep.tsx`, `apps/client/app/features/workflow/components/deployment/AutomaticOptimizationManagementModal.tsx`, `apps/client/app/dashboard/mymodule/page.tsx` | 구현 완료 | `apps/client/app/features/workflow/components/deployment/DeploymentFlowModal.test.tsx`, `apps/client/app/features/workflow/components/deployment/AutomaticOptimizationManagementModal.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr14-dashboard-automatic-optimization-management.test.tsx` | 통과 |

## FR-014 배포별 자동 파라미터 최적화 UI

### 배포 모달

배포 흐름은 `배포 설명 → 운영 비용 자동 최적화 → 결과` 세 단계다. 두 번째 단계는 선택형이며, 사용자가 끄면 배포 설정과 실행 동작은 기존과 동일하다.

- `운영 비용 자동 최적화 사용`: 체크 스위치. 대상 LLM node가 없으면 비활성화한다.
- `최적화 대상 LLM 노드`: 현재 graph의 LLM node만 나열한다. 전체 선택/해제와 개별 선택을 제공한다.
- `자동 점검 주기`: `20~200회`, 10회 단위 slider. 성공한 배포 후 운영 실행 수를 기준으로 한다.
- `월간 검증 예산`: `$0.5~$10`, $0.5 단위 slider. 일반 workflow 운영 비용과 분리해 설명한다.
- 안내 문구는 응답 길이/RAG context만 다루며 모델 라우팅, 모델 선택, prompt는 바꾸지 않는다는 점을 분명히 표시한다.

### 내 모듈 운영 현황

기존 비용·추세·예산 사용률·비용 위험 신호는 변경하지 않는다. 기존 `최적화` 컬럼은 `자동 최적화` 컬럼으로 교체한다.

- 수집 상태: `수집 중 14 / 50회`처럼 현재 수집 수와 점검 주기를 보여준다.
- 검증 예산: `월 검증 $0.18 / $3.00`처럼 별도 지출과 한도를 보여준다. 이 값은 대상 node의 추천 `테스트하기`에서 실제 후보 실행과 품질 judge에 든 새 비용만 반영하며, 운영 실행 비용·기준 로그 조회 비용은 포함하지 않는다.
- `관리`: 배포 권한이 있는 사용자만 표시하며, modal에서 사용 여부·점검 주기·월간 검증 예산을 수정한다.
- 관리 modal은 대상 node 수와 현재 수집 상태를 읽기 전용으로 표시한다. 대상 node 변경은 재배포 snapshot의 책임이다.
- 배포가 없으면 `배포 후 설정`, 사용하지 않으면 `미사용`을 표시한다.

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

`비교 분석 테스트`를 누르면 A baseline 선택 화면을 먼저 연다. 추천 모달의 `테스트하기`는 FR-013 빠른 검증 경로로 분리되어 최신 성공 baseline을 서버에서 자동 확정한다.

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

### Workflow-Aware Adaptive Routing Controls

관련 FR: FR-011

#### 목표 사용자 흐름

1. 사용자가 LLM node에서 `자동 모델 라우팅`을 켠다.
2. 시스템은 먼저 라우팅 적합성을 분석한다.
3. 후보가 있지만 증거가 부족하면 `Replay로 검증하기`를 안내한다.
4. Cost Optimizer Replay에서 후보가 품질/효율 gate를 통과하면 policy proposal을
   만든다.
5. 사용자는 의미 입력군, 대표 문장 수, 기준 점수와 입력군별 검증 모델을 확인한다.
6. 사용자는 예상 순절감, 품질 근거, cohort별 선택 모델과 fallback을 확인한다.
7. 검증된 policy가 active가 되면 일반 실행은 저장 policy로 모델을 선택한다.
8. 실행 로그에서 실제 선택 모델, matched cohort/rule, fallback과 policy version을
   확인한다.

후보 검증 결과에서 provider가 요청 후보와 다른 모델을 실제 실행한 경우, 후보 모델명만 성공으로 표시하면 안 된다. 분석 화면은 `요청 모델 -> 실제 실행 모델`과 `fallback 발생`을 함께 표시하고, 해당 후보를 `검증 제외` 상태로 표시한다. 이 경우 schema, downstream, 품질 점수가 있어도 policy 적용 후보로 선택할 수 없다.

#### Routing analysis panel

기존 model-routing route의 첫 화면은 모델 추천 한 건보다 라우팅 가능 여부를 먼저
보여준다.

| 분석 상태 | 주 표시 | 기본 액션 |
| --- | --- | --- |
| `eligible` | 검증 후보 수, 예상 순절감, 적용 가능한 cohort | policy proposal 확인 |
| `needs_evidence` | 부족한 모델/cohort/sample과 필요한 품질 검증 | Replay로 검증하기 |
| `fixed_model_recommended` | 현재 모델 유지 이유와 라우팅 예상 실익 부족 | 현재 모델 유지 |
| `blocked` | 권한, credential, capability, schema 계약 문제의 safe reason | 설정/권한 확인 |

`fixed_model_recommended`를 실패처럼 빨간 오류로 표시하지 않는다. 이 결과는 한
모델을 유지하는 것이 더 안전하고 경제적이라는 정상 최적화 판단이다.

#### Evidence summary

Evidence는 `운영`과 `Replay`를 별도 행 또는 segmented view로 표시한다.

- 운영: 실제 traffic sample, 입력군 비중, 현재 모델 비용/latency/품질
- Replay: 후보별 paired sample, schema/downstream/quality gate, 비교 비용
- 후속 Shadow/Canary는 계약만 예약하고 현재 화면에는 미구현 badge로 노출하지 않는다.

Sample 수를 하나로 합쳐 `총 28회`처럼 표시하지 않는다. `운영 20회`,
`Replay 8쌍`처럼 출처와 단위를 함께 표시한다.

#### Policy proposal

Policy proposal은 다음을 보여준다.

- 기본 모델과 fallback
- cohort 조건과 선택 모델
- 현재 policy 대비 변경점
- evidence version과 gate profile version
- cohort별 예상 비용/latency/품질 변화
- traffic share를 반영한 전체 예상 순절감
- 근거 부족으로 현재 모델을 유지하는 cohort
- semantic Route label, 대표 문장 수, threshold와 catalog version

Judge 설명은 보조 문구로 표시한다. UI는 Judge 추천을 최종 결정처럼 표현하지 않고,
Hard Gate와 deterministic optimizer가 검증했다는 상태를 별도로 보여준다.

#### Runtime decision trace

실행 로그의 LLM node 상세에는 다음을 표시한다.

- 실제 선택 모델
- fallback 모델과 fallback 사용 여부
- 사용자 친화적인 입력 유형 이름과 matched cohort/rule
- 의미 유사도, 통과 기준, 2위와의 점수 차이
- 현재 policy에 등록된 모든 입력군의 유사도 순위와 각 입력군의 통과 기준
- 입력군 선택에 필요한 1위·2위 최소 점수 차이 기준
- 의미 유사도 판정인지 policy 안전 override인지 구분하는 선택 근거
- 안전 override가 적용된 경우 signal 원문 대신 매칭 개수와 안전 우선 적용 상태
- 선택 reason code의 사용자 친화 문구
- policy/evidence/gate profile/Route catalog version
- `실행 중 Judge 호출 안 함`

기술 식별자를 그대로 나열하지 않고 다음 순서로 설명한다.

```text
입력 유형: 단순 사용·안내 문의
판정: 유사도 88% (선택 기준 75%, 2위와 차이 37%p)
선택 모델: gpt-4o-mini
선택 이유: 이 입력 유형에서 품질 기준을 통과한 모델 중 예상 비용이 가장 낮습니다.
안전 장치: 호출 실패 시 검증된 gpt-4.1-mini로 한 번 전환합니다.
```

분류가 불확실하면 비용 절감 성공처럼 표시하지 않는다.

```text
입력 유형: 명확히 분류하지 못함
판정: 1위와 2위 의미 점수 차이가 안전 기준보다 작습니다.
선택 모델: 현재 기본 모델 유지
선택 이유: 애매한 입력을 저비용 모델로 보내지 않는 보수적 정책입니다.
```

Frontend는 raw query, embedding vector, 대표 문장 원문을 trace 화면에 노출하지
않는다. `semantic_similarity`, `semantic_threshold`, `semantic_margin`,
`semantic_min_margin`, `semantic_cohort_scores[]`의 safe number와 입력군 이름만
표시한다. 입력군 목록은 유사도 내림차순으로 표시하고, 선택된 행 또는 가장 가까운 행을
구분한다.
`semantic_decision_source=safety_override`이면 전문 점수 대신
`정책의 안전 조건과 일치해 고성능 모델을 선택함`으로 설명한다. Catalog의 signal
원문도 화면에 노출하지 않는다.

이 정보가 없으면 `자동 라우팅 ON` badge만으로 모델이 실제 바뀌었는지 증명할 수
없으므로 시연 완료로 보지 않는다.

공통 `ModelRoutingDecisionDetails`는 테스트 실행 결과의
`output.metadata.model_routing`과 배포 로그의 canonical `trace_metadata.llm`을 같은
표시 계약으로 해석한다. 배포 실행 로그에서는 사용자가 LLM node를 선택했을 때 노드
설정 다음에 이 설명을 표시한다. 두 화면이 서로 다른 reason 해석을 갖지 않도록 별도
복사본을 만들지 않는다.

#### Test Sidebar 실행 노드 상세

테스트 실행 결과 목록의 각 완료 노드는 icon-only `상세 보기` 버튼을 제공한다. 버튼은
페이지를 이동하지 않고 같은 Test Sidebar를 노드 실행 상세 상태로 전환한다.

- 상세 header에는 `테스트 결과로 돌아가기` 버튼과 `{노드명} 실행 상세` 제목을 표시한다.
- 모든 node 상세에는 상태, 실행 시간, 비용, 출력 데이터를 표시한다. 긴 출력은 줄임표로
  자르지 않고 scrollable code block으로 보여준다. 자동 라우팅 상세가 있으면 출력 데이터를
  먼저, 그 다음 `배포 정책 기준 테스트`와 판정 근거를 표시한다.
- LLM node output에 `metadata.model_routing`이 있으면 `ModelRoutingDecisionDetails`를
  재사용해 입력 유형, 가장 가까운 입력 유형, 모든 입력군의 유사도·선택 기준·최소 점수 차이,
  매칭 결과, 최초 선택 모델, 판단/선택 이유, policy version을 보여준다.
- `semantic_match_status=no_match|ambiguous|unavailable`이면 `기준 미달로 기본 모델 사용`
  라벨과 유사도/기준 미달 또는 판정 불가 사유를 보여준다.
- `fallback_used=true`이면 계획된 fallback 설명과 별도로 `실제 대체 실행` block에서
  `fallback_from_model`, `fallback_reason_code`, 실제 output model을 표시한다.
- 자동 라우팅 trace가 있는 테스트 실행에는 `이 테스트 실행은 자동 라우팅 정책의 학습 및
  갱신 횟수에 포함되지 않습니다.`를 표시한다.
- trace의 `policy_source=active_deployment`와 `included_in_policy_learning=false`이면 공통
  상세 컴포넌트 header를 `배포 정책 기준 테스트`로 표시한다. 활성 배포 policy를 읽었지만
  테스트 결과는 운영 학습에 포함하지 않았다는 뜻이다.
- 현재 draft와 활성 deployment의 node 설정이 다르면 배포 policy를 적용하지 않는다. 이 경우
  기존 `자동 라우팅` 상세에서 저장 모델 사용 사유를 표시한다.

#### Backend core와 UI 연결 경계

Backend core 구현에서는 기존 policy panel이 새 analysis/policy response를
깨지지 않게 받을 타입과 최소 상태 표시를 보장한다. 이후 적합성 panel,
evidence summary, policy diff, activation/rollback, runtime decision trace를 연결한다.

#### 현재 구현 호환 controls

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

- `기본 모델 (규칙 미일치 시)` 선택 UI를 표시한다. 이 값은 입력군 rule과 매칭되지 않은 요청의 기본 모델이며, policy table의 `active_policy.default_model_id`와 node draft의 `model_id`를 함께 갱신한다.
- `기본 대체 모델` 선택 UI를 표시한다. 이 값은 기본 모델 호출 실패 시에만 사용하며, `active_policy.fallback_model_id`와 node draft의 `fallback_model_id`를 함께 갱신한다.
- active policy 상태 panel을 표시한다. panel은 `GET /model-routing/policy` 응답을 우선 사용한다.
- runtime은 active policy를 사용해 모델을 선택한다.
- active policy가 없으면 `collecting` 상태로 표시하고, runtime은 node에 저장된 `model_id`/`fallback_model_id`를 그대로 사용한다. bootstrap은 새 모델이나 rule을 만들지 않는다.
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
- active policy의 default/rule/fallback 중 현재 사용자의 credential `use` 권한으로 실행 가능한 모델이 없으면 provider 호출 전에 실행이 차단된다는 안내를 표시한다.

정책 갱신 결과의 judge 호출 비용은 숨기지 않는다. UI는 policy update summary에서 judge 모델, token/cost, 갱신 trigger를 확인할 수 있어야 한다. 단 raw prompt, raw output, credential 원문, API key, raw trace payload는 표시하지 않는다.

현재 구현은 policy 조회 응답의 `last_update` safe summary를 사용해 `최근 정책 점검`, 자동/수동 갱신 여부, `반영됨`/보류/실패 상태, judge 모델과 judge 비용을 표시한다. 사용자는 judge usage log id를 원문 로그로 열람하지 않고 추적 식별자로만 확인한다.

자동 라우팅 토글과 점검 주기 slider는 local draft만 바꾸지 않는다. 사용자가 토글을 바꾸거나 slider 조작을 마치면 `PATCH /model-routing/policy`로 `enabled`, `refresh_every_runs`, `validation_budget_usd`, `max_cohorts`를 저장한다. 현재 배포가 없거나 현재 deployment snapshot에 자동 라우팅 ON 설정이 포함되지 않은 경우에는 draft 설정은 저장되지만 policy panel은 `collecting`으로 남고, 해당 설정을 포함해 다시 배포한 뒤 target LLM node가 성공한 terminal 운영 workflow 완료가 policy row를 생성한다.

자동 라우팅이 켜진 노드를 다시 배포하면, 화면은 새 deployment snapshot의 LLM 설정 지문과 이전 cohort/evidence 지문이 모두 같을 때만 복제된 policy와 입력군을 조회한다. 따라서 같은 설정을 재배포한 직후에는 `입력군 관리` 목록, 검증된 기본 모델, `직접 입력군 추가` 액션이 이전 version 상태를 이어서 표시한다. 모델·prompt·RAG 등 실행 설정이 달라지면 이전 근거를 이어서 표시하지 않고 새 deployment에서 다시 수집한다. 어느 경우든 `정책 갱신 기준`의 누적 실행 수는 새 배포의 운영 로그만 세므로 `0/{refresh_every_runs}회`부터 다시 표시한다.

자동 라우팅 ON panel에는 입력군 제어 영역을 추가한다.

- `입력군 관리`은 자동 정책 점검 주기와 월간 검증 한도보다 위에 표시한다.
- `입력군 최대 개수` slider: `1~12`, 기본값 `6`, 권장 범위 `3~6`을 표시한다.
- count badge: `proposed`, `validating`, `validated_waiting`, `active` 상태의 개수만 `현재/최대`로 표시한다. 휴면/종료 입력군은 이력 목록에는 남지만 자리를 차지하지 않는다.
- 입력군 목록: 한국어 이름, 변수명, source(`직접 등록`/`자동 발견`), 합성 `대표 문의`, 관찰 수, lifecycle, 고정 여부, 검증된 기본 모델 또는 `검증 대기`를 표시한다. 대표 문의가 없는 자동 발견 입력군은 `대표 문의를 준비 중입니다.`라고 표시한다. 검증된 기본 모델은 읽기 전용이며 사용자가 직접 고르지 않는다.
- 직접 등록: 대표 문의를 입력하고 `입력군 마법사`를 누르면 한국어 이름과 영문 변수명 초안을 채운다. 사용자는 두 값을 수정하고 `입력군 고정` 여부를 정한 뒤 `입력군 추가`를 누른다.
- 직접 등록 입력군: `수정` 액션으로 대표 문의, 한국어 이름, 변수명, 고정 여부를 다시 편집할 수 있다. 저장 전 화면은 대표 문의 변경이 기존 검증을 무효화하고 재검증 대기로 바꾼다는 경고를 보여준다.
- 자동 발견 입력군: 원본을 직접 수정하지 않는다. `사용자 입력군으로 전환` 액션은 같은 cohort row를 `manual`로 전환하고 현재 이름/key/대표 문의를 수정 form에 채운다. 저장 시 기존 route, observation, evidence를 재검증 대상으로 초기화한다. 자동 입력군의 대표 문의가 아직 없으면 사용자가 대표 문의를 입력한 뒤 전환해야 한다.
- 입력군 고정: 고정된 입력군은 traffic이 줄어도 자동 휴면/종료 처리하지 않는다. 고정하지 않은 직접 등록 입력군은 lifecycle 정책을 따른다.
- 삭제: safety-protected 입력군을 제외한 입력군은 `삭제`할 수 있다. 삭제는 DB 이력을 물리적으로 지우지 않고 `retired`로 전환하며, 이후 요청은 전체 기본 정책으로 처리한다.
- 직접 등록은 policy row가 생성된 뒤에만 활성화한다. 첫 배포 운영 실행 전에는 대표 문장 embedding과 policy 연결을 할 수 없으므로 disabled 안내를 표시한다.
- 대표 문의는 설정 데이터로 DB에 저장된다. UI는 secret, 실제 고객 원문, credential 정보를 넣지 말아야 한다는 안내를 제공해야 한다.
- 직접/자동 입력군 모두 등록 직후 실행 모델을 바꾸지 않는다. 운영 관찰과 candidate Replay/Judge gate가 통과해 `active` rule이 된 뒤에만 runtime 선택에 참여한다.

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
- 답변·검색 문서 어휘 일치도

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

B 후보 실행 버튼을 누르면 비교 리포트가 생성된다. 리포트는 A baseline과 B candidate의 출력, 비용, 토큰, latency, 출력 품질 점수와 confidence, schema 검증 상태, retrieval summary, downstream 호환성 상태를 함께 보여준다. 사용자는 리포트를 본 뒤 B 후보 설정을 현재 노드에 적용할지 선택한다.

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
- 답변·검색 문서 어휘 일치도

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
- `comparisonId/candidateId` deep link는 이력 목록에서 검색하지 않고 단건 상세 API로 복원한다. 필터 목록이 다시 조회되거나 선택 후보가 첫 20개 밖에 있어도 상세 선택은 유지한다.
- workflow, node 또는 deep link query가 바뀌면 이전 baseline, compare result, 선택 이력을 재사용하지 않고 새 화면 세션으로 초기화한다.

상단 판단 요약은 B 후보를 현재 노드에 적용해도 되는지 먼저 말해준다. 상태는 다음 3개 라벨을 사용한다.

- `적용 후보로 적합`
- `주의 필요`
- `적용 비추천`

판단 요약은 다음 근거를 함께 표시한다.

- 비용 변화율
- prompt/completion/total token 변화율
- latency 변화
- 출력 품질 점수 변화와 confidence
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
| 출력 품질 점수 | baseline quality score 또는 `평가 불가` | candidate quality score 또는 `평가 불가` | 점수 상승/하락과 confidence |
| 실행 상태 | baseline status | candidate status | 성공/실패 변화 |
| Schema | baseline 기준 또는 `-` | candidate schema status | 통과/실패/미사용 |
| Downstream | baseline downstream | current compatibility | 검증 가능/주의 필요/검증 불가 |

출력 품질 비교는 A 출력과 B 출력을 나란히 보여준다.

`출력 품질 점수`는 `핵심 지표 비교` 안에서 schema와 downstream보다 먼저 표시한다. completed 평가에서는 `86점`, `82점`, `4점 하락 · 신뢰도 보통`처럼 실제 값과 방향을 함께 표시하고 변화값 tooltip에는 safe summary와 별도 품질 평가 비용을 노출한다. judge를 실행할 수 없으면 행을 숨기지 않고 A/B 값을 `평가 불가`, 변화값을 safe summary로 표시한다. 품질 점수 하락 또는 낮은 confidence는 `주의 필요` 판단 근거지만 단독으로 후보 적용을 차단하지 않는다.

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

필터 입력값은 즉시 서버 query로 사용하지 않는다. 사용자가 `필터 적용`을 실행할 때 입력값을 한 번에 적용하며, `초기화`는 기본값인 성공 후보 조건으로 돌아간다. 이 방식은 실행자나 모델을 입력하는 매 keystroke마다 목록 API가 호출되는 것을 막는다.

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
| 액션 | `테스트하기`, `정책 갱신`, `보류` |

파라미터 추천 row의 기본 액션은 `테스트하기`다.

- `max_tokens`, `temperature`, `top_p`, `frequency_penalty`, RAG context 설정은 직접 draft에 적용하지 않는다.
- 사용자가 row를 선택하고 `테스트하기`를 누르면 현재 LLM node 설정 복사본에 `candidate_patch`를 merge한 B candidate를 만들고 모달 안에서 빠른 검증을 실행한다.
- 빠른 검증이 끝난 뒤에만 `적용하기`와 `상세 비교 분석하기`를 사용할 수 있다.

검증 전 모달 하단 버튼은 다음을 사용한다.

| 버튼 | 동작 |
| --- | --- |
| `테스트하기` | 최신 비교 가능한 성공 실행을 A로 고정하고 선택한 추천 patch가 적용된 B를 한 번 실행한다. 실제 LLM 비용 안내 후 실행한다. |
| `닫기` | 변경 없이 모달을 닫는다. |

검증 완료 후 모달 하단 버튼은 다음을 사용한다.

| 버튼 | 동작 |
| --- | --- |
| `적용하기` | 빠른 검증에서 실행한 exact B candidate settings를 current draft에 적용한다. schema/downstream hard gate를 통과해야 한다. |
| `상세 비교 분석하기` | 같은 experiment/candidate를 기존 Cost Optimizer 결과 분석 화면에서 열며 후보를 다시 실행하지 않는다. |
| `닫기` | draft를 바꾸지 않고 모달만 닫는다. 검증 결과는 experiment history에 남는다. |

`바로 적용`이라는 단일 버튼은 사용하지 않는다. 파라미터 추천은 품질 저하 가능성이 있으므로 빠른 검증 전 상태와 검증 완료 후 적용을 UI에서 분리해야 한다.

추천 근거는 raw prompt, raw completion, raw Knowledge chunk content, credential 원문을 표시하지 않는다. 빠른 검증은 output 전체를 기본 화면에 펼치지 않고 품질 점수와 deterministic gate 요약을 우선 표시하며, 전체 output은 `상세 비교 분석하기`에서 확인한다.

추천 상태는 다음과 같이 표시한다.

| 상태 | 조건 | UI |
| --- | --- | --- |
| `추천 가능` | sample 수와 usage/trace summary가 충분하다 | 추천 row와 `테스트하기` 활성화 |
| `근거 부족` | 운영 로그 또는 usage/trace가 부족하다 | 필요한 추가 실행 조건 표시 |
| `실험 필요` | 추천 근거는 있으나 품질 gate를 확인해야 한다 | 빠른 검증 CTA |
| `적용 비추천` | schema/downstream 실패, 비용 악화, RAG evidence 부족이 확인된다 | CTA 비활성화 또는 경고 |

### Recommendation Inline Verification

관련 FR: FR-013

`테스트하기`를 누르면 추천 목록 아래 또는 같은 modal body 안에 빠른 검증 panel을 연다. 모달 전체를 새 페이지처럼 교체하지 않고, 선택 추천과 기준 실행 정보를 위에서 다시 확인할 수 있어야 한다.

패널은 다음 순서로 구성한다.

1. `A 기준 실행`: `최신 비교 가능한 성공 기록` 라벨, 실행 시각, 실행 모델, deployment, baseline cost/latency/token을 표시한다.
2. `추천 설정`: 선택한 recommendation label과 current → suggested 변경 요약을 표시한다.
3. `핵심 지표 비교`: 비용, 실행 시간, token, 출력 품질 점수를 각각 독립된 A/B horizontal bar로 표시한다.
4. `안전성 검사`: JSON schema 상태와 downstream 호환성 상태를 표시한다.
5. `이번 테스트 비용`: candidate 실행 비용, quality judge 비용, 신규 발생 합계를 표시한다.
6. `판단 요약`: 비용 절감 여부와 품질·schema·downstream 위험을 분리해 표시한다.

막대그래프는 다음 규칙을 따른다.

- A baseline은 중립색, B candidate는 강조색을 사용한다.
- 비용·latency·token 감소는 긍정, 증가는 주의 색상으로 표시한다.
- 품질 점수는 증가가 긍정이지만, confidence가 낮으면 색상만으로 추천하지 않고 `신뢰도 낮음`을 함께 표시한다.
- 서로 다른 단위는 하나의 공통 chart axis에 놓지 않는다.
- 실제 값과 delta를 항상 텍스트로 표시해 막대 길이만으로 판단하지 않게 한다.

품질 점수 card는 baseline score, candidate score, delta, confidence와 짧은 safe rationale을 표시한다. 평가가 불가능하면 card를 숨기지 않고 `품질 평가 불가`와 사유를 표시한다.

JSON schema card는 output format이 JSON인 경우에만 활성화한다.

- schema 있음: `통과` 또는 `실패`, 실패 field/type 요약
- JSON이지만 schema 없음: `스키마 미설정`
- text output: `검사 대상 아님`

downstream card는 `사용 가능`, `주의 필요`, `사용 불가`, `확인 불가`와 직접 검사한 후속 node 수를 표시한다. 상세 field/selector 차이는 기존 결과 분석 Inspector에서 확인한다.

모달 container는 `max-height`를 유지하고 body만 `overflow-y-auto`로 스크롤한다. footer는 body scroll 밖에 두어 `적용하기`, `상세 비교 분석하기`, `닫기`가 항상 보이게 한다.

상태 전이는 다음과 같다.

| 상태 | UI |
| --- | --- |
| `idle` | 추천 목록과 `테스트하기` 표시 |
| `resolving_baseline` | 최신 성공 baseline을 찾는 중, 중복 실행 차단 |
| `running_candidate` | B candidate 실행 중, 실제 비용 발생 안내 |
| `evaluating_quality` | candidate 결과는 유지하고 품질 judge 진행 상태 표시 |
| `completed` | chart, gate, 비용, 하단 3개 버튼 표시 |
| `partial` | candidate는 성공했지만 judge 평가 불가 등 일부 결과만 표시 |
| `failed` | 실패 단계와 safe error를 표시하고 다시 테스트 허용 |
| `stale` | 추천 선택 또는 node draft가 바뀌어 적용 비활성화, 재실행 요구 |

### Candidate Settings Mapping

관련 FR: FR-003, FR-008

프론트 local draft, LLM node data, compare request, apply request는 다음 기준으로 매핑한다.

| UI/Local field | LLM node data | `POST /compare` field | `PATCH /apply` field | 비고 |
| --- | --- | --- | --- | --- |
| `model_id` | `data.model_id` | `candidate.model_id` | `candidate_settings.model_id` | 기존 모델 선택 목록을 재사용한다. |
| `fallback_model_id` | `data.fallback_model_id` | `candidate.fallback_model_id` | `candidate_settings.fallback_model_id` | 기본 모델과 같으면 validation 대상이다. |
| `auto_model_routing` | `data.auto_model_routing` | `candidate.auto_model_routing` | `candidate_settings.auto_model_routing` | LLM 노드 자동 모델 라우팅 ON/OFF 저장값이다. ON인 후보에 active policy가 없으면 Gateway는 후보가 명시한 모델을 보존한 rule 없는 cold-start policy를 materialize한다. |
| `model_routing_context` | `data.model_routing_context` | 사용하지 않음 | 사용하지 않음 | 런타임 policy rule 평가에 쓰는 명시적 일반 힌트다. 예: `customer_facing`, `node_task`. 현재 자동 refresh는 raw 입력을 받지 않으므로 도메인 키워드 rule을 추정 생성하지 않고 이 일반 feature의 segment 근거만 사용한다. |
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
| `answerGroundingCheck` | `data.answerGroundingCheck` | `candidate.knowledge.answer_grounding_check` | `candidate_settings.knowledge.answer_grounding_check` | `off`, `basic`, `strict`. 답변·검색 문서 lexical overlap metadata만 의미하며 새 노드와 값이 없는 기존 노드의 기본값은 `basic`. |

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

### Verify Recommended Settings In Modal

관련 FR: FR-012, FR-013

1. 사용자가 `최적화`를 눌러 추천 모달을 연다.
2. 검증할 추천 row를 선택하고 `테스트하기`를 누른다.
3. 실제 candidate와 품질 judge 호출 비용이 발생한다는 안내를 확인한다.
4. 서버가 최신 비교 가능한 성공 baseline을 고정한다.
5. 같은 input으로 B candidate만 실행하고 semantic quality judge를 수행한다.
6. 모달은 A 기준 안내, metric bar, 품질 점수, JSON schema, downstream, 이번 테스트 비용을 표시한다.
7. 사용자는 `적용하기`, `상세 비교 분석하기`, `닫기` 중 하나를 선택한다.
8. 상세 분석은 같은 comparison/candidate를 열며 candidate를 다시 실행하지 않는다.

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

## Grounding And Citation Labels

- 후보 설정의 `answerGroundingCheck`는 `답변·검색 문서 어휘 일치도`로 표시한다.
- `citationDisplayMode`의 `출처 표시` UI는 LLM node reference panel이 소유한다. Cost Optimizer 후보 화면은 이를 직접 편집하지 않는다.
- A/B 후보 patch는 `citationDisplayMode`를 변경하거나 제거하지 않고 기존 graph 값을 그대로 보존한다.

## Accessibility

- 모든 주요 액션은 버튼으로 제공하고 키보드 포커스가 가능해야 한다.
- downstream 호환성 상태는 색상만으로 구분하지 않고 텍스트 라벨을 함께 표시한다.
- 비용, 토큰, latency는 숫자만 나열하지 않고 단위를 포함한다.
- Inspector 탭은 키보드로 전환 가능해야 한다.
- 실행 중 상태는 spinner와 텍스트를 함께 표시한다.
