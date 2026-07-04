# Cost Optimizer Component Spec

Status: Draft
Verified Against: feature/mba-112 @ c82a14a

## Purpose

이 문서는 `requirements.md`의 FR-001부터 FR-010까지를 화면과 컴포넌트 관점에서 구현 가능한 형태로 정리한다.

Cost Optimizer UI는 workflow 전체 비교 화면이 아니라, LLM 노드 상세 화면에서 시작하는 LLM 노드 단위 A/B 테스트 흐름이다.

## FR Mapping

| FR | 화면/컴포넌트 | UI 책임 |
| --- | --- | --- |
| FR-001 | LLM node detail action | LLM 노드에서만 A/B 테스트 진입 액션을 제공한다. |
| FR-002 | Baseline log picker | 최신 실행 로그 또는 이전 실행 로그를 A baseline으로 선택한다. |
| FR-003 | Candidate editor | B 후보의 모델, prompt, parameter, 출력 형식을 편집한다. |
| FR-004 | Baseline input lock display | A baseline 입력이 B 후보 실행 입력으로 고정됨을 보여준다. |
| FR-005 | Hybrid compare flow | A는 재실행하지 않고 B만 실행하는 비교 흐름을 안내한다. |
| FR-006 | A/B compare workspace | A, B, Inspector 3영역으로 결과와 trace를 비교한다. |
| FR-007 | Downstream compatibility badge | downstream 호환성을 3상태로 표시하고 의미를 설명한다. |
| FR-008 | Apply candidate action | 선택한 B 후보 설정을 현재 LLM 노드 draft에 적용한다. |
| FR-009 | Cost/usage display | 비교 실행 비용이 기록된다는 사실과 후보별 비용을 표시한다. |
| FR-010 | Permission-gated UI | builder 이상이 아니면 A/B 테스트와 적용 액션을 막는다. |

## Implementation Tracking

현재 문서는 Cost Optimizer UI 설계 기준과 구현 추적 상태를 함께 기록한다. 실제 파일 경로는 기존 workflow editor 구조에 맞춰 조정할 수 있다.

| FR | 주요 컴포넌트 | 예상 코드 위치 | 구현 상태 | 테스트 코드 | 테스트 통과 여부 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | LLM node detail action | `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerEntryAction.tsx` | 구현 완료 | `apps/client/app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx` | 통과 |
| FR-002 | Baseline selection, baseline log picker | `apps/client/app/features/workflow/components/costOptimizer/CostOptimizerBaselineSelection.tsx` | 진행중 | `apps/client/app/features/workflow/tests/costOptimizer/fr2-baseline-selection.test.tsx` | 통과 |
| FR-003 | Candidate editor | `apps/client/app/features/workflow/components/costOptimizer/NodeSettingsComparisonPanel.tsx` | 진행중 | `apps/client/app/features/workflow/tests/costOptimizer/fr3-candidate-editor.test.tsx` | 통과 |
| FR-004 | Baseline input lock display | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-005 | Hybrid compare flow state | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-006 | A/B compare workspace, Inspector | `apps/client/app/modules/[id]/cost-optimizer/[nodeId]/page.tsx` | 진행중 | `apps/client/app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | 통과 |
| FR-007 | Downstream compatibility badge | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-008 | Apply candidate action, confirmation modal | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-009 | Cost/usage metric display | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-010 | Permission-gated UI | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |

## Screens

### LLM Node Detail

관련 FR: FR-001, FR-010

LLM 노드 상세 화면에는 `A/B 테스트하기` 액션을 제공한다.

- 이 액션은 `llmNode`에서만 표시한다.
- builder 이상 권한이 없는 사용자는 액션을 비활성화한다.
- 비활성화 상태에는 권한 부족 사유를 표시한다.
- LLM 노드 설정이 저장되지 않았거나 draft가 오래된 경우, 비교 시작 전에 현재 draft 저장 또는 저장 필요 안내를 표시한다.

#### A/B Test Button Placement

`A/B 테스트` 버튼은 LLM 노드 상세 패널의 상단 헤더 우측 보조 액션 영역에 배치한다.

- 위치: 노드 제목, 노드 타입, 상태 badge가 표시되는 헤더 영역의 우측
- 라벨: `A/B 테스트`
- 아이콘: `GitCompare` 또는 기존 icon set에서 비교 의미가 명확한 아이콘
- Tooltip: `이 LLM 노드의 실행 로그를 기준으로 후보 설정을 비교합니다.`
- 액션 위계: 저장, 삭제 같은 기본 편집 액션보다 낮은 보조 액션으로 표시한다.

버튼 상태는 다음과 같이 처리한다.

| 상태 | 표시 | 동작 |
| --- | --- | --- |
| target node가 `llmNode`가 아님 | 미노출 | Cost Optimizer 진입 불가 |
| builder 이상 권한 있음 | 활성화 | baseline 선택 단계로 이동 |
| builder 이상 권한 없음 | disabled | `Builder 권한이 필요합니다.` 안내 |
| baseline 실행 로그 없음 | 활성화 또는 disabled | 클릭 시 `비교할 실행 로그가 없습니다. 먼저 테스트 실행을 완료해 주세요.` 안내 |
| 저장되지 않은 draft 있음 | 활성화 | 클릭 시 `현재 노드 설정을 저장한 뒤 비교를 시작할 수 있습니다.` 안내 |

버튼 클릭 후에는 바로 비교 화면을 열지 않고 baseline 선택 단계를 먼저 연다. baseline 선택이 완료된 뒤 A/B compare workspace로 이동한다.

### Baseline Selection

관련 FR: FR-002, FR-004, FR-005

`A/B 테스트하기`를 누르면 A baseline 선택 화면을 먼저 연다.

화면은 두 가지 선택지를 제공한다.

- `최신 실행 로그로 비교하기`
- `이전 실행 로그 선택해서 비교하기`

`최신 실행 로그로 비교하기`는 target LLM node의 성공한 실행 기록 중 `input_available=true`, `output_available=true`, `usage_available=true`를 모두 만족하는 가장 최근 baseline을 자동 선택한다.

baseline 선택 화면은 진입 시 최신 baseline을 미리 조회하고, `최신 실행 로그로 비교하기` CTA 안에 최신 로그 요약을 표시한다. 사용자는 CTA를 누르기 전에 어떤 실행 로그가 A 기준으로 고정될지 확인할 수 있어야 한다.

최신 로그 요약은 다음 정보를 표시한다.

- 실행 시각
- 모델
- 토큰
- 비용
- 실행 시간
- 입력 preview
- 출력 preview

최신 비교 가능 baseline이 없으면 최신 CTA 영역에 로그 없음 안내를 표시하고, `이전 실행 로그 선택해서 비교하기` 경로를 사용할 수 있게 한다.

`이전 실행 로그 선택해서 비교하기`는 baseline log picker를 연다.

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

A/B compare workspace는 특정 workflow의 특정 LLM node에 종속된 전용 작업 화면이다. 사용자는 workflow 편집 화면에서 target LLM node의 `A/B 테스트하기` 액션으로 이 workspace에 진입한다.

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

기본 workspace mode는 `실험 설정`이다. 사용자가 B 후보를 실행해 리포트가 생성되면 `결과 분석` mode로 이동할 수 있어야 한다. B 실행 API가 아직 연결되지 않은 상태에서는 `결과 분석` mode가 비어 있는 리포트 상태와 실행 대기 안내를 표시한다.

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

왼쪽 A 실행 시점 옵션 영역은 읽기 전용이다.

- baseline 실행 시점의 기본 설정
- baseline 실행 시점의 고급 설정
- baseline 실행 시점의 지식 베이스 설정

오른쪽 기준 실행 정보 영역은 baseline이 어떤 입력과 출력으로 고정되었는지 보여준다.

- 선택된 기준 실행 모델
- baseline 비용/토큰/latency
- 기준 입력 preview
- 기준 출력 preview
- B 후보 비교 컨텍스트

기준 입력/출력 preview는 화면에서 임의로 truncate하지 않는다. 긴 값은 줄바꿈과 패널 스크롤로 처리하고, 값 자체를 `...`로 잘라내지 않는다.

B candidate 영역은 편집 가능하다.

B candidate는 현재 LLM 노드 설정 복사본으로 초기화한다.

B candidate 상단에는 사용자가 이번 실험을 구분할 수 있는 `테스트명` 입력을 둔다. `테스트명`은 설정 패널 제목을 대체하는 화면 메타 정보이며, `후보 옵션` 같은 중복 제목은 표시하지 않는다. 현재 프론트 구현에서는 local state로 관리하고, compare result 저장 API가 연결되면 `test_name` 또는 `experiment_name`으로 전달한다.

A baseline과 B candidate는 서로 다른 JSX 구조를 가지면 안 된다. 두 영역은 동일한 설정 패널 컴포넌트를 사용하고, `readOnly` 여부만 다르게 동작해야 한다.

- A baseline: `NodeSettingsComparisonPanel(readOnly=true)`
- B candidate: `NodeSettingsComparisonPanel(readOnly=false)`

공통 설정 패널은 다음 탭을 제공한다.

- `기본 설정`
- `고급 설정`
- `지식 베이스`

`기본 설정` 탭은 LLM 노드 상세 편집에서 사용자가 기본적으로 조작하던 핵심 옵션을 같은 구조로 보여준다.

- 모델 선택
- fallback 모델 선택
- task type 선택
- system prompt 편집
- user prompt 편집
- assistant prompt 편집
- 출력 형식 선택: text 또는 JSON
- JSON schema 편집

모델 선택 UI는 기존 LLM 노드 상세 편집의 모델 조회/선택 기준을 따른다.

- 모델 목록 API: `GET /api/v1/llm/my-models`
- 모델 선택 컴포넌트: 기존 `ModelSelectDropdown` 계열을 우선 재사용한다.
- 사용할 수 없는 credential/model은 목록에서 제외하는 것을 우선한다.
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
- task type
- system/user/assistant prompt
- output format
- JSON schema
- LLM parameters
- Knowledge Base selection
- `topK`
- `scoreThreshold`

화면은 A baseline과 B candidate가 같은 입력 기준이라는 점을 명확히 표시한다.

`결과 분석` mode는 편집 UI보다 비교 리포트 가독성을 우선한다.

- 상단: 비용, 토큰, 모델, 실행 상태 요약
- 왼쪽: A baseline 결과
- 가운데: B candidate 결과
- 오른쪽: Diff, RAG, downstream 분석 요약
- 액션: `실험 설정으로 돌아가기`, `현재 노드에 적용`

B 실행 결과가 없으면 B 결과 영역에는 `B 실행 후 결과 분석이 표시됩니다.` empty state를 표시한다.

### Candidate Settings Mapping

관련 FR: FR-003, FR-008

프론트 local draft, LLM node data, compare request, apply request는 다음 기준으로 매핑한다.

| UI/Local field | LLM node data | `POST /compare` field | `PATCH /apply` field | 비고 |
| --- | --- | --- | --- | --- |
| `model_id` | `data.model_id` | `candidate.model_id` | `candidate_settings.model_id` | 기존 모델 선택 목록을 재사용한다. |
| `fallback_model_id` | `data.fallback_model_id` | `candidate.fallback_model_id` | `candidate_settings.fallback_model_id` | 기본 모델과 같으면 validation 대상이다. |
| `task_type` | `data.task_type` 또는 node option | `candidate.task_type` | `candidate_settings.task_type` | 비용/품질 분석 라벨과 후속 라우팅 기준으로 사용한다. |
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

### Inspector

관련 FR: FR-006, FR-007, FR-009

Inspector는 A/B 비교를 이해하기 위한 상세 정보 영역이다.

Inspector는 탭 구조를 사용한다.

- `A Trace`
- `B Trace`
- `Diff`
- `Downstream`
- `Settings`

`A Trace`는 baseline 실행의 상세 정보를 보여준다.

- input
- output
- prompt/messages 요약
- token/cost/latency breakdown
- LLM usage trace
- RAG retrieval summary
- error

`B Trace`는 B 후보 실행 후 활성화된다.

`Diff`는 A와 B의 차이를 보여준다.

- 모델 차이
- prompt 차이
- parameter 차이
- 출력 형식 차이
- 비용 차이
- 토큰 차이
- latency 차이

`Downstream`은 downstream 호환성 상태와 계약 검증 결과를 보여준다.

`Settings`는 비교 화면 안에서 필요한 고급 설정과 지식 베이스 관련 설정을 확인하거나 편집하는 탭이다. 별도 패널을 중첩해서 열지 않는다.

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

1. 사용자가 LLM 노드 상세 화면에서 `A/B 테스트하기`를 누른다.
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
