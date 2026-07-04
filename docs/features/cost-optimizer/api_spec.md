# Cost Optimizer API Spec

Status: Draft
Verified Against: TBD

## Purpose

이 문서는 `requirements.md`의 FR-001부터 FR-010까지를 API 계약 관점에서 정리한다.

Cost Optimizer API는 특정 workflow의 특정 LLM node를 기준으로 baseline 실행 로그를 선택하고, 같은 입력으로 B 후보 설정을 실행한 뒤, 선택한 후보를 현재 draft에 적용하는 흐름을 지원한다.

## FR Mapping

| FR | API 책임 |
| --- | --- |
| FR-001 | LLM node인지 확인하고 A/B 테스트 진입 가능 여부를 판단한다. |
| FR-002 | target LLM node의 baseline 실행 로그 목록과 최신 baseline을 제공한다. |
| FR-003 | B 후보 설정 request schema를 정의한다. |
| FR-004 | baseline input을 B 후보 실행 입력으로 고정한다. |
| FR-005 | A는 재실행하지 않고 B 후보만 실행하는 compare API를 제공한다. |
| FR-006 | A/B 결과와 trace/Inspector에 필요한 데이터를 반환한다. |
| FR-007 | baseline graph와 current graph의 downstream 호환성 상태를 반환한다. |
| FR-008 | 선택한 B 후보 설정을 current draft target LLM node에 적용한다. |
| FR-009 | 비교 실행에서 발생한 LLM usage/cost를 기록한다. |
| FR-010 | builder 이상 권한을 API에서 강제한다. |

## Endpoints

| Method | Path | Description | Related FR | Auth |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/availability` | A/B 테스트 진입 가능 여부 조회 | FR-001, FR-010 | builder 이상 |
| GET | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines/latest` | 최신 baseline 실행 로그 조회 | FR-002, FR-004, FR-007 | builder 이상 |
| GET | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines` | baseline 실행 로그 목록 검색/필터/정렬 | FR-002, FR-004, FR-007 | builder 이상 |
| POST | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/compare` | 선택 baseline input으로 B 후보 실행 | FR-003, FR-004, FR-005, FR-006, FR-009, FR-010 | builder 이상 |
| PATCH | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/apply` | 선택한 B 후보 설정을 current draft에 적용 | FR-008, FR-010 | builder 이상 |

## Implementation Tracking

현재 문서는 Cost Optimizer API 계약과 구현 추적 상태를 함께 기록한다. 실제 router/service/schema 파일명은 Gateway의 기존 workflow/app API 구조에 맞춰 확정한다.

| FR | API/계약 단위 | 예상 코드 위치 | 구현 상태 | API 테스트 코드 | 테스트 통과 여부 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | `GET availability` | `apps/gateway/api/v1/endpoints/workflow.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-002 | `GET baselines/latest`, `GET baselines` | `apps/gateway/routes/`, `apps/gateway/services/`, `apps/shared/schemas/` | 구현 전 | 작성 전 | 미실행 |
| FR-003 | compare candidate request schema | `apps/shared/schemas/`, `apps/gateway/services/` | 구현 전 | 작성 전 | 미실행 |
| FR-004 | baseline input restore/lock | `apps/gateway/services/`, `apps/workflow_engine/` trace/log 조회 경계 | 구현 전 | 작성 전 | 미실행 |
| FR-005 | hybrid compare execution | `apps/gateway/services/`, `apps/workflow_engine/` | 구현 전 | 작성 전 | 미실행 |
| FR-006 | compare response trace/diff | `apps/shared/schemas/`, `apps/gateway/services/` | 구현 전 | 작성 전 | 미실행 |
| FR-007 | downstream compatibility response | `apps/gateway/services/`, workflow graph helper | 구현 전 | 작성 전 | 미실행 |
| FR-008 | `PATCH apply` | `apps/gateway/routes/`, `apps/gateway/services/` | 구현 전 | 작성 전 | 미실행 |
| FR-009 | LLM usage/cost logging | `apps/shared/services/`, `apps/gateway/services/`, `apps/workflow_engine/` | 구현 전 | 작성 전 | 미실행 |
| FR-010 | builder permission enforcement | `apps/gateway/services/`, permission helper | 구현 전 | 작성 전 | 미실행 |

## Common Path Parameters

| Name | Type | Description |
| --- | --- | --- |
| `workflow_id` | UUID string | Cost Optimizer를 실행할 workflow id |
| `node_id` | string | target LLM node id |

## Baseline Data Sources

관련 FR: FR-002, FR-004

Baseline의 canonical id는 `workflow_node_runs.id`다.

Baseline API는 다음 저장소를 조합해 row와 detail을 만든다.

| Source | Usage |
| --- | --- |
| `workflow_node_runs` | baseline id, target node id/type, node status, node-level latency, node trace metadata |
| `workflow_runs` | workflow run id, 전체 run 상태, 실행 시각, workflow/app/deployment context |
| `llm_usage_logs` | model, prompt tokens, completion tokens, total tokens, cost, LLM latency |
| `trace_payloads` | redaction-safe input/output preview, input 복원 가능 여부, trace 존재 여부 |

`workflow_runs.id`는 baseline의 전체 실행 컨텍스트이고, `workflow_node_runs.id`가 사용자가 선택하는 baseline 식별자다.

Baseline API는 target LLM node의 `workflow_node_runs.status=success`이고 `output_available=true`, `usage_available=true`인 기록만 반환한다. 실패한 node run, output preview가 없는 node run, usage summary가 없는 node run은 baseline 후보에서 제외하고, 실패 원인 분석이나 불완전한 실행 기록 확인은 workflow 실행 로그/trace API에서 다룬다.

`trace_payloads` retention, redaction, 저장 누락으로 target LLM node input을 복원할 수 없는 경우에도 baseline row는 목록에 포함한다. 다만 response는 `input_available=false`, `compare_available=false`를 반환하고, compare API는 해당 baseline으로 B 후보 실행을 시작하지 않는다.

## Common Response Fragments

### DownstreamCompatibility

관련 FR: FR-007

```json
{
  "state": "compatible",
  "label": "검증 가능",
  "message": "baseline 실행 시점의 downstream과 현재 downstream이 호환됩니다.",
  "baseline_downstream_hash": "string",
  "current_downstream_hash": "string",
  "first_consumer_status": "same",
  "contract_check": {
    "status": "pass",
    "checked_node_ids": ["extract-result"],
    "warnings": []
  }
}
```

`state` 값:

- `compatible`: 검증 가능
- `warning`: 주의 필요
- `incompatible`: 검증 불가
- `unknown`: 판정 불가

### LLMNodeUsageSummary

관련 FR: FR-006, FR-009

```json
{
  "model": "gpt-4.1-mini",
  "prompt_tokens": 1200,
  "completion_tokens": 240,
  "total_tokens": 1440,
  "cost": 0.00123,
  "latency_ms": 1840,
  "status": "success"
}
```

### LLMNodeTraceSummary

관련 FR: FR-006

```json
{
  "input_preview": "string",
  "output_preview": "string",
  "messages_preview": [
    {
      "role": "system",
      "content_preview": "string"
    }
  ],
  "rag_summary": {
    "retrieved_chunk_count": 3,
    "knowledge_base_count": 1,
    "source_summary": ["HR 정책 문서"]
  },
  "error_message": null
}
```

Trace summary는 credential 원문, API key, encrypted config, raw secret payload를 포함하지 않는다.

## Endpoint Details

### GET availability

관련 FR: FR-001, FR-010

`GET /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/availability`

대상 node가 Cost Optimizer를 사용할 수 있는지 반환한다.

Response:

```json
{
  "available": true,
  "reason": null,
  "workflow_id": "uuid",
  "node_id": "llm-triage",
  "node_type": "llmNode",
  "permission": {
    "can_compare": true,
    "can_apply": true,
    "required_auth_state": "builder"
  }
}
```

`available=false` 사유 예:

- target node가 존재하지 않음
- target node가 `llmNode`가 아님
- builder 이상 권한 없음
- draft를 조회할 수 없음

### GET latest baseline

관련 FR: FR-002, FR-004, FR-007

`GET /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines/latest`

target LLM node의 가장 최근 비교 가능 실행 로그를 baseline으로 반환한다.
반환 대상은 `node_status=success`, `input_available=true`, `output_available=true`, `usage_available=true`인 기록으로 제한한다.

Response:

```json
{
  "baseline": {
    "baseline_id": "workflow-node-run-id",
    "baseline_source": "workflow_node_run",
    "source_workflow_node_run_id": "workflow-node-run-id",
    "workflow_run_id": "workflow-run-id",
    "workflow_id": "workflow-id",
    "node_id": "llm-triage",
    "run_started_at": "2026-07-04T00:00:00Z",
    "node_status": "success",
    "model": "gpt-4.1",
    "input_available": true,
    "output_available": true,
    "usage_available": true,
    "trace_available": true,
    "compare_available": true,
    "unavailable_reason": null,
    "input": {},
    "output": {},
    "usage": {
      "model": "gpt-4.1",
      "prompt_tokens": 1200,
      "completion_tokens": 240,
      "total_tokens": 1440,
      "cost": 0.0123,
      "latency_ms": 2100,
      "status": "success"
    },
    "trace": {
      "input_preview": "string",
      "output_preview": "string",
      "messages_preview": [],
      "rag_summary": null,
      "error_message": null
    },
    "downstream_compatibility": {
      "state": "compatible",
      "label": "검증 가능",
      "message": "string"
    }
  }
}
```

### GET baseline list

관련 FR: FR-002, FR-004, FR-007

`GET /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines`

target LLM node가 포함된 실행 로그 목록을 검색/필터/정렬한다.
반환 대상은 `node_status=success`, `output_available=true`, `usage_available=true`인 기록으로 제한한다. `input_available=false`인 row는 목록에 포함하되 `compare_available=false`로 반환한다.

Query:

| Name | Type | Default | Description |
| --- | --- | --- | --- |
| `model` | string | optional | 모델 필터 |
| `q` | string | optional | input/output preview 검색어 |
| `date_from` | ISO datetime | optional | 시작 시각 |
| `date_to` | ISO datetime | optional | 종료 시각 |
| `sort` | string | `started_at_desc` | `started_at_desc`, `cost_desc`, `cost_asc`, `tokens_desc`, `latency_desc` |
| `compare_available` | boolean | optional | input 복원 가능 여부 기준 비교 가능 row 필터 |
| `limit` | integer | 20 | page size |
| `offset` | integer | 0 | offset |

Response:

```json
{
  "items": [
    {
      "baseline_id": "workflow-node-run-id",
      "baseline_source": "workflow_node_run",
      "source_workflow_node_run_id": "workflow-node-run-id",
      "workflow_run_id": "workflow-run-id",
      "run_started_at": "2026-07-04T00:00:00Z",
      "workflow_run_status": "success",
      "node_status": "success",
      "model": "gpt-4.1",
      "cost": 0.0123,
      "total_tokens": 1440,
      "latency_ms": 2100,
      "input_available": true,
      "output_available": true,
      "usage_available": true,
      "trace_available": true,
      "compare_available": true,
      "unavailable_reason": null,
      "input_preview": "string",
      "output_preview": "string",
      "has_trace": true,
      "downstream_compatibility": {
        "state": "compatible",
        "label": "검증 가능",
        "message": "string"
      }
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### POST compare

관련 FR: FR-003, FR-004, FR-005, FR-006, FR-009, FR-010

`POST /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/compare`

A baseline input을 사용해 B 후보 설정을 실행한다. A baseline은 재실행하지 않는다.

`baseline_id`는 `workflow_node_runs.id`다. 해당 baseline의 target LLM node input을 복원할 수 없으면 API는 B 후보 실행을 시작하지 않고 `400 cost_optimizer.baseline_input_unavailable`을 반환한다.

Compare request의 후보 설정 필드명은 `candidate`다. Apply request의 후보 설정 필드명은 `candidate_settings`다.

Request:

```json
{
  "baseline_id": "workflow-node-run-id",
  "candidate": {
    "label": "B",
    "model_id": "gpt-4.1-mini",
    "fallback_model_id": "gpt-4.1",
    "task_type": "generate",
    "system_prompt": "string",
    "user_prompt": "string",
    "assistant_prompt": "string",
    "parameters": {
      "max_tokens": 800,
      "temperature": 0.2,
      "top_p": 1,
      "presence_penalty": 0,
      "frequency_penalty": 0,
      "stop": []
    },
    "output_format": {
      "type": "json",
      "schema": {
        "type": "object",
        "properties": {
          "severity": { "type": "string" },
          "approvalRequired": { "type": "boolean" },
          "replyDraft": { "type": "string" }
        },
        "required": ["severity", "approvalRequired", "replyDraft"]
      }
    },
    "knowledge": {
      "knowledge_base_ids": ["knowledge-base-id"],
      "top_k": 5,
      "score_threshold": 0.7
    }
  }
}
```

Candidate request schema:

| Field | Type | Required | Validation |
| --- | --- | --- | --- |
| `baseline_id` | string | yes | target workflow/node scope의 `workflow_node_runs.id`여야 한다. |
| `candidate.label` | string | no | UI 표시용 라벨이다. 기본값은 `B`다. |
| `candidate.model_id` | string | yes | 현재 사용자와 organization scope에서 사용 가능한 model이어야 한다. |
| `candidate.fallback_model_id` | string or null | no | 지정하면 사용 가능한 model이어야 하며 `model_id`와 같으면 invalid candidate다. |
| `candidate.task_type` | string | no | 기본값은 현재 node 설정 또는 `generate`다. |
| `candidate.system_prompt` | string | no | 세 prompt 중 하나 이상은 비어 있지 않아야 한다. |
| `candidate.user_prompt` | string | no | 변수 참조는 baseline input/upstream output 기준으로 resolve 가능해야 한다. |
| `candidate.assistant_prompt` | string | no | 변수 참조는 baseline input/upstream output 기준으로 resolve 가능해야 한다. |
| `candidate.parameters.max_tokens` | number | yes | 1~8192 |
| `candidate.parameters.temperature` | number | yes | 0~2 |
| `candidate.parameters.top_p` | number | no | 0~1 |
| `candidate.parameters.presence_penalty` | number | no | -2~2 |
| `candidate.parameters.frequency_penalty` | number | no | -2~2 |
| `candidate.parameters.stop` | string[] | no | 최대 4개 |
| `candidate.output_format.type` | `text` or `json` | yes | `json`이면 schema 검증을 수행한다. |
| `candidate.output_format.schema` | object | no | 1차 UI는 flat key-type schema를 만든다. API는 valid JSON schema object만 허용한다. |
| `candidate.knowledge.knowledge_base_ids` | string[] | no | 모두 현재 사용자/organization/workflow scope에서 사용 가능해야 한다. |
| `candidate.knowledge.top_k` | number | no | Knowledge/RAG 사용 시 retrieval 개수다. |
| `candidate.knowledge.score_threshold` | number | no | Knowledge/RAG 사용 시 retrieval score threshold다. |

B candidate가 Knowledge/RAG를 사용하면 compare API는 baseline의 과거 retrieval 결과를 재사용하지 않고, request의 `candidate.knowledge` 설정으로 retrieval을 새로 수행한다. Response는 baseline retrieval summary와 candidate retrieval summary를 구분해 반환해야 한다.

Response:

```json
{
  "comparison_id": "uuid",
  "workflow_id": "uuid",
  "node_id": "llm-triage",
  "baseline": {
    "baseline_id": "workflow-node-run-id",
    "label": "A",
    "settings": {},
    "input": {},
    "output": {},
    "usage": {},
    "trace": {}
  },
  "candidate": {
    "label": "B",
    "settings": {},
    "output": {},
    "usage": {
      "model": "gpt-4.1-mini",
      "prompt_tokens": 900,
      "completion_tokens": 180,
      "total_tokens": 1080,
      "cost": 0.0011,
      "latency_ms": 1600,
      "status": "success"
    },
    "schema_validation": {
      "status": "valid",
      "errors": []
    },
    "trace": {},
    "error_message": null
  },
  "diff": {
    "cost_delta": -0.0112,
    "cost_delta_percent": -91.0,
    "token_delta": -360,
    "latency_delta_ms": -500
  },
  "downstream_compatibility": {
    "state": "compatible",
    "label": "검증 가능",
    "message": "string"
  }
}
```

비교 실행에서 발생한 LLM call은 `llm_usage_logs`에 기록되어야 한다. 또한 비교 실행 자체도 `comparison_id`로 재조회하거나 추적할 수 있도록 저장한다.

JSON schema 검증에 실패한 경우에도 HTTP response는 200으로 반환할 수 있다. 이 경우 후보 LLM call은 성공한 것이므로 비용/토큰/시간을 반환하고, `candidate.usage.status` 또는 `candidate.schema_validation.status`를 `schema_failed`로 표시한다. schema 실패 후보는 apply API에서 거부한다.

### PATCH apply

관련 FR: FR-008, FR-010

`PATCH /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/apply`

선택한 B 후보 설정을 current draft의 target LLM node에 적용한다.

적용은 부분 적용이 아니라 B 후보 설정 전체 일괄 적용이다.

Apply request의 후보 설정 필드명은 `candidate_settings`다. 이 schema는 compare request의 `candidate`와 같은 설정 구조를 사용하되, 이미 생성된 비교 결과를 적용하는 API이므로 `comparison_id`를 함께 받는다.

Request:

```json
{
  "comparison_id": "comparison-id",
  "candidate_settings": {
    "model_id": "gpt-4.1-mini",
    "fallback_model_id": "gpt-4.1",
    "task_type": "generate",
    "system_prompt": "string",
    "user_prompt": "string",
    "assistant_prompt": "string",
    "parameters": {
      "max_tokens": 800,
      "temperature": 0.2,
      "top_p": 1,
      "presence_penalty": 0,
      "frequency_penalty": 0,
      "stop": []
    },
    "output_format": {
      "type": "json",
      "schema": {}
    },
    "knowledge": {
      "knowledge_base_ids": ["knowledge-base-id"],
      "top_k": 5,
      "score_threshold": 0.7
    }
  },
  "acknowledge_downstream_warning": false
}
```

Response:

```json
{
  "workflow_id": "uuid",
  "node_id": "llm-triage",
  "applied": true,
  "downstream_compatibility": {
    "state": "compatible",
    "label": "검증 가능",
    "message": "string"
  },
  "updated_draft_revision": "string-or-number"
}
```

`downstream_compatibility.state`가 `warning` 또는 `incompatible`인 경우, API는 `acknowledge_downstream_warning=true` 없이는 적용을 거부할 수 있다.

## Errors

| Status | Code | Description | Related FR |
| --- | --- | --- | --- |
| 400 | `cost_optimizer.not_llm_node` | target node가 `llmNode`가 아님 | FR-001 |
| 400 | `cost_optimizer.no_baseline` | baseline으로 사용할 로그가 없음 | FR-002 |
| 400 | `cost_optimizer.invalid_candidate` | B 후보 설정이 유효하지 않음 | FR-003 |
| 400 | `cost_optimizer.schema_failed_candidate` | schema 검증 실패 후보를 적용하려고 함 | FR-003, FR-008 |
| 400 | `cost_optimizer.baseline_input_unavailable` | baseline input을 복원할 수 없음 | FR-004 |
| 400 | `cost_optimizer.downstream_ack_required` | downstream warning 확인 없이 적용 요청 | FR-007, FR-008 |
| 403 | `permission.denied` | builder 이상 권한 없음 | FR-010 |
| 404 | `resource.not_found` | workflow, node, baseline이 없거나 scope 밖임 | FR-001, FR-002 |
| 409 | `cost_optimizer.draft_conflict` | 현재 draft가 baseline 비교 이후 충돌됨 | FR-008 |
| 422 | `cost_optimizer.model_unavailable` | 사용할 수 없는 credential/model 후보 | FR-003, FR-010 |
| 422 | `cost_optimizer.knowledge_unavailable` | 사용할 수 없거나 접근 권한이 없는 Knowledge Base 후보 | FR-003, FR-010 |
| 500 | `cost_optimizer.compare_failed` | B 후보 실행 중 예기치 않은 실패 | FR-006 |

## Permissions

관련 FR: FR-010

Cost Optimizer API는 builder 이상 권한을 요구한다.

- A/B 테스트 진입 가능 여부 조회: builder 이상
- baseline 조회: builder 이상
- B 후보 실행: builder 이상
- 후보 적용: builder 이상

API는 프론트의 UI 차단과 별개로 서버에서 권한을 강제해야 한다.

workflow 실행 권한만 있는 사용자는 Cost Optimizer를 사용할 수 없다.

## Security And Redaction

관련 FR: FR-006, FR-009, FR-010

- credential 원문, API key, encrypted config는 응답에 포함하지 않는다.
- raw prompt 전체는 정책에 따라 preview 또는 redacted summary로 제한할 수 있다.
- RAG retrieval summary는 권한이 허용된 safe summary만 반환한다.
- 권한 없는 문서명, raw chunk content, raw source metadata는 반환하지 않는다.
- 비교 실행에서 발생한 LLM usage는 비용 추적에서 누락되지 않아야 한다.
