# Cost Optimizer Component Spec

Status: Draft
Verified Against: TBD

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

현재 문서는 구현 전 설계 기준이다. 실제 파일 경로는 구현 시점에 기존 workflow editor 구조에 맞춰 조정할 수 있다.

| FR | 주요 컴포넌트 | 예상 코드 위치 | 구현 상태 | 테스트 코드 | 테스트 통과 여부 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | LLM node detail action | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-002 | Baseline selection, baseline log picker | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-003 | Candidate editor | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-004 | Baseline input lock display | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-005 | Hybrid compare flow state | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
| FR-006 | A/B compare workspace, Inspector | `apps/client/app/features/workflow/components/editor/` | 구현 전 | 작성 전 | 미실행 |
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

`최신 실행 로그로 비교하기`는 target LLM node의 가장 마지막 실행 로그를 자동 선택한다.

`이전 실행 로그 선택해서 비교하기`는 baseline log picker를 연다.

### Baseline Log Picker

관련 FR: FR-002, FR-004, FR-007

Baseline log picker는 target LLM node가 실제로 실행된 로그만 보여준다.

각 row는 다음 정보를 표시한다.

- 실행 시각
- workflow run 상태
- target LLM node 상태
- 사용 모델
- target LLM node 비용
- target LLM node 토큰
- target LLM node 실행 시간
- 입력 preview
- 출력 preview
- trace 존재 여부
- downstream 호환성 상태

필터와 정렬은 다음을 지원한다.

- 상태 필터: success, failed, all
- 모델 필터
- 날짜 범위 필터
- 검색어: 입력/출력 preview 기준
- 정렬: 최신순, 비용 높은순, 비용 낮은순, 토큰 높은순, 실행 시간 긴순

Baseline을 선택하면 A baseline input은 잠금 상태로 표시한다. 사용자는 A 입력을 직접 수정하지 않는다.

### A/B Compare Workspace

관련 FR: FR-003, FR-004, FR-005, FR-006, FR-009

A/B compare workspace는 3영역 레이아웃이다.

- 왼쪽: A baseline
- 가운데: B candidate
- 오른쪽: Inspector

A baseline 영역은 읽기 전용이다.

- baseline 실행 로그 정보
- baseline 입력
- baseline 출력
- baseline 모델
- baseline 비용/토큰/latency
- baseline trace 요약

B candidate 영역은 편집 가능하다.

- 모델 선택
- system prompt 편집
- user prompt 편집
- assistant prompt 편집
- `max_tokens` 편집
- `temperature` 편집
- 출력 형식 선택: text 또는 JSON
- B 후보 실행

B 후보 실행 결과에는 다음을 표시한다.

- 실행 상태
- 출력 결과 preview
- prompt tokens
- completion tokens
- total tokens
- estimated cost
- latency
- error message

화면은 A baseline과 B candidate가 같은 입력 기준이라는 점을 명확히 표시한다.

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
- downstream 호환성 상태
- 추가 검증 필요 여부

`검증 가능`이 아닌 경우, 모달에서 현재 workflow 테스트 실행으로 최종 확인해야 함을 표시한다.

적용이 완료되면 현재 LLM node draft가 B 후보 설정으로 갱신된다.

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
- `baseline_error`: baseline 조회 실패

### Candidate States

관련 FR: FR-003, FR-006

- `editing`: B 후보 편집 중
- `running`: B 후보 실행 중
- `success`: B 후보 실행 성공
- `failed`: B 후보 실행 실패
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
5. baseline이 선택되면 A/B compare workspace로 이동한다.

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
