# Workflow API Spec

Status: Draft
Verified Against: TBD

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| POST | `/api/v1/workflows/{workflow_id}/execute/stream` | 테스트 실행 스트리밍 이벤트를 반환한다. 기존 구현을 사용한다. | workflow execute 권한 |
| GET | 기존 workflow run 목록 API | 실행 로그 선택 화면의 workflow run 목록을 조회한다. 신규 API가 아니라 기존 실행 로그 조회 경로를 우선 사용한다. | workflow read 권한 |
| GET | 기존 workflow run detail API | 선택한 workflow run의 node run, trace payload, LLM usage 정보를 조회한다. 신규 API가 아니라 기존 실행 로그 상세 경로를 우선 사용한다. | workflow read 권한 |

## Request And Response Models

### 1. 실행 편의성

- 이번 UI 변경은 신규 API를 추가하지 않는다.
- 프론트는 기존 스트리밍 이벤트를 사용한다.
  - `node_start`: `{ node_id }`
  - `node_finish`: `{ node_id, node_type, output }`
  - `workflow_finish`: 최종 workflow output
  - `error`: `{ message, node_id? }`
- 노드별 토큰 사용량은 `node_finish.output.usage.total_tokens` 또는 `prompt_tokens + completion_tokens`에서 계산한다.
- 노드별 비용은 `node_finish.output.cost`, `node_finish.output.usage.total_cost`, 또는 백엔드가 제공하는 node-level cost 값에서 계산한다.
- 노드별 소요 시간은 프론트가 `node_start` 수신 시각과 `node_finish`/`error` 수신 시각의 차이로 계산한다.
- 전체 실행 시간은 테스트 실행 시작 시각과 `workflow_finish` 또는 최종 오류 수신 시각의 차이로 계산한다.
- 전체 비용과 전체 토큰은 노드별 값의 합산 또는 `workflow_finish`가 제공하는 workflow-level summary 값으로 계산한다.

### 2. 노드 조작 편의성

- 노드 상세 편집 화면의 3패널 리사이즈는 API request/response를 변경하지 않는다.
- 패널 폭과 비율은 workflow graph, node data, deployment snapshot에 저장하지 않는다.
- 패널 비율 영구 저장이 필요해지면 사용자 preference API를 별도 이슈로 정의한다.

### 3. 워크플로우 조작 편의성

- Backspace/Delete 키 노드 삭제와 자동 재연결은 클라이언트 graph 편집 동작이다.
- 삭제 결과 graph는 기존 workflow draft 저장 API를 통해 저장된다. 별도 삭제 API나 재연결 API를 추가하지 않는다.
- 자동 생성 edge는 기존 edge schema를 사용한다.

### 4. 노드 실행 기록 패널 추가

- 이번 UI는 우선 신규 API를 추가하지 않고 기존 실행 로그 목록/상세 데이터를 사용한다.
- 프론트는 workflow run 목록을 최신순으로 조회한 뒤, 각 run의 node run/trace/usage 데이터 중 현재 선택된 `node_id`와 일치하는 기록을 찾아 표시한다.
- 실행 로그 선택 row의 preview는 다음 값을 사용한다.
  - workflow run id/status/started_at/finished_at
  - workflow run 전체 latency 또는 시작/종료 시각 기반 소요 시간
  - workflow run 전체 token/cost summary가 있으면 표시
  - 현재 node_id의 node run status/latency/input/output/error preview
  - 현재 node_id의 LLM usage total_tokens/total_cost/model/provider가 있으면 표시
- 실행 로그 상세는 선택한 run detail에서 현재 node_id에 해당하는 다음 값을 추출한다.
  - node run input/output/error/status
  - trace payload의 redaction-safe metadata
  - llm usage log의 model/provider/token/cost/latency
- `가장 최신 로그 기록 불러오기`는 현재 node_id 기록이 포함된 가장 최신 workflow run을 선택한다.
- 기존 API만으로 node_id 필터가 불가능하면 프론트는 제한된 최신 page를 순회해 현재 node_id 기록이 있는 run을 찾는다. 대량 조회가 필요해지면 후속 API를 정의한다.
- 후속 API 후보:
  - `GET /api/v1/workflows/{workflow_id}/runs?node_id={node_id}&limit=20&cursor=...`
  - `GET /api/v1/workflows/{workflow_id}/nodes/{node_id}/run-traces?limit=20&cursor=...`

## Errors

### 1. 실행 편의성

- workflow execute 권한이 없으면 403으로 거부한다.
- workflow가 active organization scope 밖이면 404로 숨긴다.
- 스트리밍 중 노드 오류가 발생하면 `error` 이벤트에 `node_id`가 포함될 수 있으며, 프론트는 해당 노드를 실패로 표시한다.

### 4. 노드 실행 기록 패널 추가

- workflow read 권한이 없으면 실행 로그 목록/상세 조회는 403으로 거부한다.
- workflow가 active organization scope 밖이면 실행 로그 목록/상세 조회는 404로 숨긴다.
- 선택한 run 안에 현재 node_id 기록이 없으면 API 오류로 보지 않고 UI에서 빈 상태로 처리한다.
- trace/input/output payload가 redaction 또는 retention 정책으로 누락된 경우 UI는 `표시 가능한 기록 없음`으로 처리한다.

## Permissions

### 1. 실행 편의성

- 테스트 실행은 workflow `operator` 이상 또는 `can_execute=true`인 effective permission이 필요하다.
- 프론트는 권한 없는 사용자에게 테스트 버튼을 disabled 처리하지만, 최종 권한 판정은 Gateway/API가 수행한다.

### 2. 노드 조작 편의성

- 패널 리사이즈 자체는 서버 권한을 요구하지 않는 로컬 UI 조작이다.
- 단, 노드 상세 편집 화면의 입력 수정과 저장은 기존 workflow write 권한 정책을 그대로 따른다.

### 3. 워크플로우 조작 편의성

- 노드 삭제와 자동 재연결은 workflow write 권한이 있는 사용자에게만 허용한다.
- read-only 사용자는 노드 선택은 가능하지만 Backspace/Delete로 graph를 변경할 수 없다.

### 4. 노드 실행 기록 패널 추가

- 노드 실행 기록 조회는 workflow read 권한을 따른다.
- 실행 기록 조회는 현재 workflow graph를 변경하지 않으므로 workflow write 권한을 요구하지 않는다.
- secret, credential 원문, raw prompt 전체 등 민감 정보는 Gateway/API의 응답 정책을 우선하며, 프론트는 표시 단계에서 추가로 allowlist 기반 렌더링을 적용한다.
