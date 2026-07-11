# Workflow API Spec

Status: Draft
Verified Against: feature/mba-163 @ 056673e

## Endpoints

| Method | Path | Description | Auth |
| --- | --- | --- | --- |
| POST | `/api/v1/workflows/{workflow_id}/stream` | 테스트 실행 스트리밍 이벤트를 반환한다. 기존 구현을 사용한다. | workflow execute 권한 |
| GET | `/api/v1/workflows/{workflow_id}/nodes/{node_id}/execution-logs` | 현재 노드가 실행된 workflow run 목록을 최신순으로 조회한다. 목록 row에 필요한 node-level preview를 포함한다. | workflow read 권한 |
| GET | `/api/v1/workflows/{workflow_id}/nodes/{node_id}/execution-logs/{run_id}` | 선택한 workflow run 안의 현재 노드 input/output/trace/usage 상세를 조회한다. | workflow read 권한 |

Client 내부 route:

| Method | Path | Description |
| --- | --- | --- |
| POST | `/stream-api/workflows/{workflow_id}` | Next.js route handler가 Gateway `/api/v1/workflows/{workflow_id}/stream`으로 SSE를 proxy한다. Backend URL은 `API_URL`, `NEXT_PUBLIC_API_URL`, `http://127.0.0.1:8000` 순서로 결정하며 trailing `/api/v1`은 제거한다. Cookie와 `X-Organization-Id`, `X-Request-Id`, `X-Correlation-Id` 같은 safe context header만 전달한다. 서버/컨테이너 runtime에서는 `API_URL` 명시를 우선한다. `API_URL`이 없고 `NEXT_PUBLIC_API_URL`이 공개 Gateway URL이면 production에서도 fallback으로 사용할 수 있지만, `localhost`, `127.0.0.1`, `::1`, `0.0.0.0` 같은 loopback public URL은 production server fallback으로 사용하지 않는다. |

## Request And Response Models

### Workflow run actor compatibility

Workflow run list/detail 또는 node execution log가 run actor를 포함하는 경우 `user_id`는 `UUID | null`이다. Null은 canonical schedule claim에서 내부 입력 `schedule`이 저장 계약 `trigger_mode="scheduler"`로 정규화된 system execution에서만 허용한다. Client는 null을 App creator로 대체하지 않고 actor를 표시하는 화면에서는 `System`으로 표현한다. Manual/API/webhook 등 기존 user-attributed run의 non-null 계약은 유지한다.

Schedule claim id, idempotency key와 outcome review state는 public workflow API response에 추가하지 않는다. Internal Worker correlation은 user-visible output이나 raw durable trace에 포함하지 않는다.

### 1. 실행 편의성

- 이번 UI 변경은 신규 API를 추가하지 않는다.
- 프론트는 기존 스트리밍 이벤트를 사용한다.
  - `node_start`: `{ node_id }`
  - `node_finish`: `{ node_id, node_type, output, latency_ms, total_tokens, total_cost }`
  - `workflow_finish`: 최종 workflow output
  - `error`: `{ message, node_id? }`
- Gateway는 `X-Organization-Id`가 전달된 테스트 실행 요청에서 active organization membership을 검증하고, 해당 organization이 workflow의 organization과 다르면 scope 밖 resource로 보고 `404`로 숨긴다. Header가 없는 legacy 호출은 기존 workflow row organization 기준 permission check를 유지한다.
- `node_finish` 이벤트의 node-level summary 표준 필드:
  - `latency_ms`: 노드 실행 소요 시간. 서버/엔진 기준 millisecond 단위 값.
  - `total_tokens`: 노드 실행에서 사용한 전체 토큰 수. 토큰 사용이 없는 노드는 null 또는 0을 반환할 수 있다.
  - `total_cost`: 노드 실행에서 발생한 비용. 비용 집계가 없는 노드는 null 또는 0을 반환할 수 있다.
- 프론트는 노드별 토큰/비용/소요 시간을 `node_finish` 표준 필드에서 우선 읽는다.
- `node_finish.latency_ms`가 없으면 프론트는 `node_start` 수신 시각과 `node_finish`/`error` 수신 시각의 차이를 fallback으로 계산할 수 있다.
- `node_finish.total_tokens` 또는 `node_finish.total_cost`가 없으면 해당 값은 `-`로 표시한다. `output.usage`나 `output.cost`를 표준 경로로 간주하지 않는다.
- 화면 완료 시간은 프론트가 테스트 실행 시작 상태로 전환된 시각과 `workflow_finish` 또는 최종 오류 처리 시각의 차이로 계산한다. 이 값은 API response 필드가 아니며 DB에 저장하지 않는다.
- 서버 실행 시간은 백엔드/엔진이 기록한 workflow-level duration을 사용한다. 현재 저장 기준은 `workflow_runs.duration`이며, 단위는 초다.
- `workflow_finish` 이벤트가 workflow-level summary를 제공하는 경우 프론트는 다음 필드를 우선 사용한다.
  - `run_id`: 연결된 workflow run id.
  - `duration`: 서버 실행 시간. `workflow_runs.duration`과 같은 초 단위 값.
  - `total_tokens`: 서버가 집계한 전체 토큰 사용량.
  - `total_cost`: 서버가 집계한 전체 비용.
- `workflow_finish` 이벤트에 workflow-level summary가 없으면 프론트는 `node_finish.latency_ms` 합산값을 서버 실행 시간 fallback으로 표시한다. 노드 latency도 없을 때만 `-` 또는 `기록 없음`으로 표시한다. 화면 완료 시간은 계속 프론트에서 계산한다.
- 전체 비용과 전체 토큰은 `workflow_finish`가 제공하는 workflow-level summary 값을 우선 사용하고, 없으면 노드별 값의 합산으로 fallback한다.

Example `workflow_finish` event data with server summary:

```json
{
  "run_id": "run-123",
  "output": {
    "answer": "처리 완료"
  },
  "duration": 3.4,
  "total_tokens": 8420,
  "total_cost": 0.0842
}
```

Client-only screen completion summary example:

```json
{
  "screen_completion_duration_ms": 8600
}
```

`screen_completion_duration_ms`는 API response가 아니라 프론트 UI 상태에서 계산되는 값이다.

Example `node_finish` event data with node-level summary:

```json
{
  "node_id": "llm-triage",
  "node_type": "llmNode",
  "output": {
    "text": "{\"approvalRequired\": true}"
  },
  "latency_ms": 3571,
  "total_tokens": 361,
  "total_cost": 0.001964
}
```

### 2. 노드 조작 편의성

- 노드 상세 편집 화면의 3패널 리사이즈는 API request/response를 변경하지 않는다.
- 패널 폭과 비율은 workflow graph, node data, deployment snapshot에 저장하지 않는다.
- 패널 비율 영구 저장이 필요해지면 사용자 preference API를 별도 이슈로 정의한다.

### 3. 워크플로우 조작 편의성

- 왼쪽 노드 패널의 `뒤에 추가` 액션은 클라이언트 graph 편집 동작이다.
- `뒤에 추가` 결과 graph는 기존 workflow draft 저장 API를 통해 저장된다. 별도 노드 추가 API, edge 연결 API, 자동 정렬 API를 추가하지 않는다.
- 자동 생성 node와 edge는 기존 workflow graph node/edge schema를 사용한다.
- Backspace/Delete 키 노드 삭제와 자동 재연결은 클라이언트 graph 편집 동작이다.
- 삭제 결과 graph는 기존 workflow draft 저장 API를 통해 저장된다. 별도 삭제 API나 재연결 API를 추가하지 않는다.
- 자동 생성 edge는 기존 edge schema를 사용한다.

### 4. 노드 실행 기록 패널 추가

- 이번 UI는 node_id 기준 실행 기록 목록/상세 API를 추가해 사용한다.
- 목록 API는 workflow run 전체 목록이 아니라, 현재 `node_id` 실행 기록이 포함된 run만 최신순으로 반환한다.
- 목록 API query parameter:
  - `limit`: 한 번에 가져올 최대 row 수. 기본 20, 최대 100.
  - `cursor`: 다음 페이지 조회용 cursor. offset pagination보다 cursor pagination을 우선한다.
  - `status`: optional. `success`, `failed`, `running` 등 node run 상태 필터.
  - `q`: optional. input/output/error preview 검색어.
  - `from`, `to`: optional. 실행 시각 범위 필터.
- 목록 API 응답은 다음 shape를 따른다.
  - `items`: node execution log summary array
  - `next_cursor`: 다음 페이지 cursor. 더 이상 없으면 null 또는 생략.
- node execution log summary는 다음 값을 포함한다.
  - workflow run id/status/started_at/finished_at
  - workflow run 전체 latency 또는 시작/종료 시각 기반 소요 시간
  - workflow run 전체 token/cost summary가 있으면 표시
  - 현재 node_id의 node run status/latency/input/output/error preview
  - 현재 node_id의 LLM usage total_tokens/total_cost/model/provider가 있으면 표시
- preview 필드는 목록에서 빠른 식별을 위해 사용하는 짧은 문자열이다. full input/output은 상세 API에서만 반환한다.
- 상세 API는 선택한 run 안의 현재 node_id에 해당하는 다음 값을 반환한다.
  - node run input/output/error/status
  - trace payload의 redaction-safe metadata
  - llm usage log의 model/provider/token/cost/latency
- `가장 최신 로그 기록 불러오기`는 현재 node_id 기록이 포함된 가장 최신 workflow run을 선택한다.

Example summary response:

```json
{
  "items": [
    {
      "run_id": "run-123",
      "node_run_id": "node-run-456",
      "workflow_status": "success",
      "node_status": "success",
      "started_at": "2026-07-03T09:00:00Z",
      "finished_at": "2026-07-03T09:00:03Z",
      "latency_ms": 842,
      "total_tokens": 1240,
      "total_cost": 0.0123,
      "model_name": "gpt-4o-mini",
      "provider": "openai",
      "input_preview": "휴가 정책 알려줘...",
      "output_preview": "연차는 입사일 기준...",
      "error_preview": null
    }
  ],
  "next_cursor": null
}
```

Example detail response:

```json
{
  "run_id": "run-123",
  "node_run_id": "node-run-456",
  "workflow_summary": {
    "status": "success",
    "started_at": "2026-07-03T09:00:00Z",
    "finished_at": "2026-07-03T09:00:03Z",
    "latency_ms": 3000,
    "total_tokens": 8420,
    "total_cost": 0.0842
  },
  "node_summary": {
    "status": "success",
    "latency_ms": 842,
    "total_tokens": 1240,
    "total_cost": 0.0123,
    "model_name": "gpt-4o-mini",
    "provider": "openai"
  },
  "input": {
    "query": "휴가 정책 알려줘"
  },
  "output": {
    "answer": "연차는 입사일 기준..."
  },
  "error": null,
  "metadata": {
    "trace_id": "trace-789"
  }
}
```

## Errors

### 1. 실행 편의성

- workflow execute 권한이 없으면 403으로 거부한다.
- workflow가 active organization scope 밖이면 404로 숨긴다.
- 스트리밍 중 노드 오류가 발생하면 `error` 이벤트에 `node_id`가 포함될 수 있으며, 프론트는 해당 노드를 실패로 표시한다.

### 4. 노드 실행 기록 패널 추가

- workflow read 권한이 없으면 node execution log 목록/상세 조회는 403으로 거부한다.
- workflow가 active organization scope 밖이면 node execution log 목록/상세 조회는 404로 숨긴다.
- `node_id`가 workflow graph 또는 해당 run 기록에 없으면 목록 API는 빈 목록을 반환한다.
- 상세 API에서 `run_id`는 존재하지만 현재 node_id 기록이 없으면 404 또는 `node_execution_log.not_found`로 처리한다.
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

## Mail Node 저장 계약

- Mail node data는 `credential_id: UUID | null`과 `configuration_state: resolved | unresolved`만 credential 설정으로 허용한다.
- `displayNumber`와 `visibleProperties`는 정해진 형식과 값만 갖는 UI metadata로 허용한다.
- `password`, `token`, `email`, `encrypted_secret` 같은 inline Mail identity/secret field가 최상위 또는 중첩 `subGraph`에 있으면 workflow 저장은 `422 mail.credential_reference_required`로 실패한다.
- Non-null `credential_id`는 active organization의 active Mail credential이어야 하며 저장 요청자에게 `use` 권한이 있어야 한다. Organization 밖 reference는 `404`, 같은 organization의 권한 부족은 `403`으로 처리한다.
- `credential_id=null`인 unresolved draft는 preview/apply-save를 위해 저장할 수 있지만 deployment snapshot 생성과 기존 deployment 활성화는 `422 mail.credential_reference_required`로 차단한다. Legacy snapshot runtime도 provider 연결 전에 같은 reason으로 차단한다.
