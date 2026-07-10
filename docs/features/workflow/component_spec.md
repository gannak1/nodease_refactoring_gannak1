# Workflow Component Spec

Status: Draft
Verified Against: feature/mba-162 @ 419df74

## Condition Exit Layout

- Standard BaseNode input and output handles use the fixed vertical offset calculated from `WORKFLOW_NODE_SIZE.height / 2`, with their centers placed directly on the left and right node boundaries.
- Canonical automatic layout top-aligns every rank instead of centering shorter ranks against the tallest rank.
- A Condition node renders its Default exit first, aligns the Default target with the Condition node, and expands configured branch targets downward.
- The Condition Default output handle uses the same fixed vertical coordinate as the standard input handle. Explicit branch handles are added below it at a stable `40px` interval, and the node shape grows to contain the final handle.

## Screens

- Workflow Builder 화면: 캔버스, 노드 라이브러리, 상단 액션, 테스트 실행 사이드바, 하단 캔버스 도구를 포함한다.

## Components

### 1. 실행 편의성

- `TestSidebar`
  - 테스트 입력값을 받고 기존 workflow stream 실행을 시작한다.
  - 실행 중/완료된 노드별 상태, 소요 시간, 비용, 토큰 사용량을 표시한다.
  - 완료된 노드의 소요 시간, 비용, 토큰 사용량은 `node_finish` 이벤트의 `latency_ms`, `total_cost`, `total_tokens` 표준 필드를 우선 사용한다.
  - 표준 필드가 없으면 소요 시간은 프론트 수신 시각 기준 fallback을 사용할 수 있고, 비용/토큰은 `-`로 표시한다.
  - 노드별 상세 output은 필요할 때 JSON 형태로 확인할 수 있다.
  - 성공 결과 상단에는 `최종 응답` 카드를 표시한다.
  - `최종 응답` 카드는 최종 사용자가 받는 응답 preview를 표시하며, workflow output, answer/response node output, LLM node text output 순서로 fallback한다.
  - JSON 최종 응답은 raw JSON dump 대신 key/value preview로 표시하고, 원본 JSON은 노드별 실행 결과 상세 output에 유지한다.
  - 최종 응답 preview 추출은 `TestSidebar` 렌더링과 분리된 helper에서 수행한다.
  - 워크플로우 테스트가 완료되면 마지막 영역에 서버 실행 시간, 화면 완료 시간, 전체 비용, 전체 토큰 사용량을 최종 요약으로 표시한다.
  - 서버 실행 시간은 주 지표로 표시한다.
  - 화면 완료 시간은 보조 지표로 표시하며, 네트워크/stream/UI 처리 시간이 포함될 수 있음을 tooltip 또는 보조 문구로 설명한다.
- `BottomPanel`
  - 기본 캔버스 조작 도구만 유지한다.
  - 테스트 실행 요약을 표시하지 않는다.
- Node card observability
  - 기존 노드 카드의 running/success/failure 상태와 `observability` 표시를 유지한다.

### 2. 노드 조작 편의성

- `NodeFullscreenEditor`
  - 노드 상세 편집 화면을 구성한다.
  - 화면은 왼쪽 편집 패널, 가운데 작업/미리보기 패널, 오른쪽 보조 설정/참조 패널의 3패널 구조를 가진다.
  - 각 패널 사이에는 드래그 가능한 resizer handle을 둔다.
- Resizable three-panel layout
  - 기본 비율은 왼쪽 28%, 가운데 52%, 오른쪽 20%로 시작한다.
  - 기본 레이아웃은 부모 영역 기준 최대 90% 폭을 사용한다.
  - 왼쪽 패널을 넓힐 때 가운데와 오른쪽 패널은 남은 공간 감소분을 비슷한 비율로 나눠 부담한다.
  - 모든 패널은 `min-width`와 `max-width`를 가진다.
  - 전체 편집 영역은 viewport width의 최대 90%까지 사용하며, 초과 공간은 중앙 정렬 또는 기존 레이아웃 규칙을 따른다.
  - 패널 폭 계산은 고정된 전체 px 값이나 grid 자기 자신의 현재 폭이 아니라, 실제 렌더된 부모 영역의 가로 폭을 기준으로 한다.
  - 사용자가 아직 직접 조정하지 않았다면 화면 크기 변경에 따라 기본 비율을 다시 계산한다.
  - 사용자가 resizer를 조정한 뒤에는 같은 편집 세션에서 사용자 조정 폭을 유지한다.

### 3. 워크플로우 조작 편의성

- Canvas keyboard delete
  - 캔버스에서 선택된 노드를 Backspace/Delete 키로 삭제한다.
  - 삭제 전 선택된 노드의 incoming edge와 outgoing edge를 수집한다.
  - 삭제 후 남는 upstream/downstream 노드 사이에 유효한 edge를 자동 생성한다.
- Auto reconnect helper
  - 삭제된 노드 집합을 기준으로 upstream candidate와 downstream candidate를 계산한다.
  - 기존 연결 검증 로직을 사용해 허용되는 연결만 생성한다.
  - 이미 같은 source/sourceHandle/target/targetHandle edge가 있으면 중복 생성하지 않는다.

### 4. 노드 실행 기록 패널 추가

- `NodeDetailsPanel` 또는 노드 상세 오른쪽 보조 패널
  - `설정`과 분리된 `실행 기록` 탭을 제공한다.
  - 실행 기록 탭은 현재 선택된 노드의 과거 input/output trace를 읽기 전용으로 표시한다.
- Node execution log default view
  - 기본 상태에는 `실행 목록 검색` 버튼과 `가장 최신 로그 기록 불러오기` 버튼을 표시한다.
  - 선택된 실행 기록이 없으면 빈 상태 안내를 표시한다.
  - 선택된 실행 기록이 있으면 같은 화면에서 상세 내용을 표시한다.
- Node execution log picker view
  - `실행 목록 검색` 클릭 시 오른쪽 패널 전체가 실행 로그 선택 화면으로 전환된다.
  - 상단에는 뒤로가기, 검색 input, 상태 필터, 정렬/기간 필터를 둔다.
  - 본문에는 최신 workflow run 목록을 표시하되, 각 row는 현재 node_id에 해당하는 node run/trace preview를 포함한다.
  - row 선택 시 picker view를 닫고 default view의 상세 상태로 돌아간다.
- Node execution log detail view
  - 선택된 workflow run 요약과 현재 노드 기록을 분리해 표시한다.
  - 현재 노드 기록에는 상태, 소요 시간, 토큰, 비용, 모델/프로바이더, input, output, error, metadata를 표시한다.
  - input/output은 JSON이면 code block 형태로, plain text면 줄바꿈이 보존되는 text block으로 표시한다.

## States

### 1. 실행 편의성

- `idle`: 테스트 실행 전 상태. 테스트 실행 사이드바는 입력 폼과 실행 버튼을 표시한다.
- `running`: 실행 중 상태. 테스트 실행 사이드바에 실행 중/완료된 노드를 표시한다.
- `success`: 전체 실행 성공 상태. 테스트 실행 사이드바는 마지막 실행 결과와 전체 요약을 유지한다.
- `failure`: 전체 실행 실패 상태. 실패한 노드가 식별되면 해당 노드를 실패로 표시하고, 전체 실패 상태를 함께 표시한다.
- `uploading/preflight`: 파일 업로드, 그래프 검증, 드래프트 저장 중에는 테스트 실행 준비 상태로 본다.

### 2. 노드 조작 편의성

- `panel-resizing`: 사용자가 노드 상세 편집 화면의 resizer를 드래그하는 상태다. 이 상태에서는 패널 폭만 갱신하고 node data는 변경하지 않는다.
- `panel-default`: 사용자가 아직 폭을 조정하지 않은 기본 3패널 비율 상태다.
- `panel-constrained`: 사용자의 드래그 값이 최소/최대 폭 제약에 걸려 clamp된 상태다.
- `panel-custom`: 사용자가 resizer 또는 키보드 조작으로 기본 비율을 벗어난 상태다.

### 3. 워크플로우 조작 편의성

- `node-selected`: 하나 이상의 노드가 캔버스에서 선택된 상태다. Backspace/Delete 삭제 대상이 된다.
- `node-add-after-available`: 캔버스에 선택 노드가 있거나 단일 terminal node가 있어 왼쪽 패널에서 `뒤에 추가`를 실행할 수 있는 상태다.
- `node-add-after-pending-target`: 선택 노드가 여러 개이거나 분기 handle이 모호해 연결 대상을 더 선택해야 하는 상태다.
- `node-delete-reconnecting`: 선택 노드 삭제와 자동 재연결 edge 계산이 한 번의 graph update로 처리되는 상태다.

### 4. 노드 실행 기록 패널 추가

- `log-empty`: 실행 기록 탭에 진입했지만 선택된 로그가 없는 상태다.
- `log-loading-latest`: `가장 최신 로그 기록 불러오기` 요청이 진행 중인 상태다.
- `log-picker`: 실행 목록 검색/필터/선택 화면이 오른쪽 패널 전체를 차지한 상태다.
- `log-picker-loading`: 실행 로그 목록을 불러오는 상태다.
- `log-detail`: 선택된 workflow run과 현재 노드 기록 상세를 표시하는 상태다.
- `log-error`: 실행 로그 목록 또는 상세를 불러오지 못한 상태다.

## Interactions

### 1. 실행 편의성

- 테스트 버튼 클릭 시 기존 TestSidebar가 열리고 실행 입력을 받을 수 있다.
- 실행이 시작되면 테스트 실행 사이드바가 노드별 실행 카드를 순차적으로 표시한다.
- 실행 중인 노드는 캔버스에서 기존처럼 중심 이동/상태 강조를 유지한다.
- 테스트 실행 사이드바의 노드별 실행 카드는 상태, 소요 시간, 비용, 토큰 사용량을 compact 형태로 표시한다.
- 노드별 실행 카드의 숫자 지표는 노드 output 내부 구조를 직접 추측하지 않고, stream 이벤트의 node-level summary 표준 필드를 기준으로 표시한다.
- 워크플로우 테스트가 성공하면 테스트 실행 사이드바는 성공 안내 다음에 `최종 응답` 카드를 먼저 표시하고, 그 아래에 서버 실행 시간, 화면 완료 시간, 전체 비용, 전체 토큰 사용량과 노드별 상세 결과를 표시한다.
- workflow-level 서버 실행 시간이 없으면 노드별 `latency_ms` 합산값을 `서버 실행` fallback으로 표시한다. 노드 latency도 없을 때만 `서버 실행 -` 또는 `서버 실행 기록 없음`으로 표시하고, 화면 완료 시간은 계속 표시한다.
- 사용자가 다시 테스트하기를 누르면 이전 실행 요약은 초기화된다.

### 2. 노드 조작 편의성

- 사용자는 노드 상세 편집 화면에서 패널 경계선을 드래그해 패널 폭을 조정한다.
- 왼쪽 패널 resizer를 오른쪽으로 드래그하면 왼쪽 패널이 넓어지고, 가운데/오른쪽 패널은 비슷한 비율로 좁아진다.
- resizer 드래그 중에는 커서와 handle 상태가 resize 중임을 보여준다.
- 최소/최대 폭에 도달하면 더 이상 같은 방향으로 폭이 변하지 않는다.
- 더블 클릭 또는 별도 reset affordance가 있다면 기본 3패널 비율로 되돌릴 수 있다.

### 3. 워크플로우 조작 편의성

- 왼쪽 노드 패널의 각 노드 항목은 일반 추가와 `뒤에 추가` 액션을 구분해 제공한다.
- 일반 추가는 기존 자유 배치 또는 캔버스 추가 흐름을 유지한다.
- `뒤에 추가`는 현재 선택된 노드를 기준으로 오른쪽에 새 노드를 local placement하고, 선택 노드에서 새 노드로 edge를 생성한다.
- 선택된 노드가 없고 terminal node가 하나뿐이면 `뒤에 추가`는 해당 terminal node를 기준으로 동작할 수 있다.
- sticky note처럼 workflow 실행 graph에 포함되지 않는 보조 노드는 terminal node 개수 계산에서 제외한다.
- 선택 노드가 여러 개이거나 terminal node가 여러 개이거나 condition/switch/loop처럼 연결 handle이 모호한 경우에는 임의 연결하지 않는다. 연결 대상 또는 handle 선택 UI를 표시하거나 액션을 비활성화한다.
- `뒤에 추가`의 edge 생성은 일반 연결 validation을 통과한 경우에만 적용한다. validation이 실패하면 새 노드도 남기지 않는다.
- `뒤에 추가` 실행 후 전체 graph 자동 정렬을 수행하지 않는다. 새 노드와 기준 노드 주변만 겹치지 않게 배치한다.
- `뒤에 추가`는 undo 한 번으로 노드 생성과 edge 생성을 함께 되돌릴 수 있어야 한다.
- 사용자가 캔버스에서 노드를 선택하고 Backspace/Delete를 누르면 선택 노드를 삭제한다.
- 삭제되는 노드의 앞단과 뒷단이 모두 존재하면 삭제 후 앞단 노드에서 뒷단 노드로 자동 edge를 생성한다.
- 입력 요소에 focus가 있는 상태에서는 Backspace/Delete가 텍스트 삭제로 동작하고 노드 삭제를 실행하지 않는다.
- 자동 재연결이 불가능한 경우에는 삭제만 수행하고 새 edge를 만들지 않는다.
- 삭제와 자동 재연결은 undo 한 번으로 되돌릴 수 있는 단일 편집 동작이어야 한다.

### 4. 노드 실행 기록 패널 추가

- 사용자가 `실행 기록` 탭에 진입하면 기본 view를 표시한다.
- 사용자가 `실행 목록 검색`을 클릭하면 오른쪽 패널 전체가 picker view로 전환된다.
- picker view에서 검색어/상태/기간 필터를 변경하면 목록을 갱신한다.
- picker view의 실행 로그 row를 클릭하면 해당 run 안의 현재 노드 기록을 선택하고 detail view로 전환한다.
- 사용자가 `가장 최신 로그 기록 불러오기`를 클릭하면 현재 node_id 기록이 존재하는 가장 최신 workflow run을 찾아 detail view에 표시한다.
- 선택한 run에 현재 node_id 기록이 없으면 상세 대신 `이 실행에서 현재 노드 기록 없음` 안내를 표시한다.
- 실행 기록 탭에서 표시되는 input/output은 현재 노드 설정값을 변경하지 않는다.

## Accessibility

### 1. 실행 편의성

- 테스트 실행 요약의 상태는 색상뿐 아니라 텍스트(`실행 중`, `성공`, `실패`)로도 표시한다.
- 숫자 정보는 `ms`, `tok` 단위를 함께 표시한다.
- 비용 정보는 통화 단위 또는 소수점 자리수를 일관되게 표시한다.
- 서버 실행 시간과 화면 완료 시간은 서로 다른 라벨로 표시한다. `전체 실행 시간`처럼 둘 중 어느 기준인지 모호한 라벨을 사용하지 않는다.
- 테스트 실행 사이드바가 좁아도 노드명, 상태, 시간, 비용, 토큰 정보가 겹치지 않아야 한다.
- `최종 응답` 카드의 긴 응답은 카드 내부에서 줄바꿈과 스크롤로 처리하며, 다음 실행 요약 또는 노드별 상세 결과를 가리지 않아야 한다.

### 2. 노드 조작 편의성

- resizer handle은 키보드 focus가 가능해야 한다.
- 키보드 사용자는 좌우 방향키로 패널 폭을 일정 step 단위로 조정할 수 있어야 한다.
- resizer handle에는 현재 조정 대상과 조작 방법을 설명하는 accessible label을 제공한다.
- 패널 폭이 바뀌어도 각 패널의 주요 버튼/입력/라벨 텍스트가 겹치지 않아야 한다.

### 3. 워크플로우 조작 편의성

- 키보드 삭제 shortcut은 focus context를 구분해야 하며, 입력 필드 사용자의 기본 Backspace/Delete 조작을 방해하지 않아야 한다.
- 레이아웃 최적화는 하단 툴바의 버튼 액션으로 제공한다.
- 레이아웃 최적화 버튼이나 tooltip에는 아직 shortcut 표기를 노출하지 않는다.
- 노드 삭제 전 별도 확인 모달을 띄우지 않는다면, undo 경로가 명확해야 한다.

### 4. 노드 실행 기록 패널 추가

- picker view의 검색 input과 필터는 label 또는 accessible name을 가져야 한다.
- 실행 로그 row는 상태를 색상뿐 아니라 텍스트(`성공`, `실패`, `실행 중`)로 표시한다.
- input/output block은 긴 텍스트가 패널 밖으로 넘치지 않고 스크롤 또는 줄바꿈으로 읽을 수 있어야 한다.
- 패널 전환 시 focus가 예측 가능해야 한다. picker view 진입 시 검색 input 또는 뒤로가기 버튼에 focus를 둘 수 있다.
