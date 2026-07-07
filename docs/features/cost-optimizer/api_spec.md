# Cost Optimizer API Spec

Status: Draft
Verified Against: feature/mba-112 @ df9ed6df92c2c8177cc9ef0fe2f2c50967e423f6

## Purpose

이 문서는 `requirements.md`의 FR-001부터 FR-011까지를 API 계약 관점에서 정리한다.
FR-011 모델 라우팅 최적화는 실행 시점 자동 라우팅이 아니라 사용자 클릭 기반 추천 분석으로 다룬다. 추천 분석 endpoint는 후속 API이며, 현재 workflow runtime은 저장된 `model_id`와 `fallback_model_id`만 사용한다.

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
| FR-011 | 현재 Cost Optimizer API는 모델 라우팅 추천 endpoint를 제공하지 않는다. 후속 API는 배포 후 운영 로그를 분석해 추천 모델, 예상 절감, 품질 근거를 반환하고, 적용은 기존 apply 흐름처럼 사용자의 명시 액션으로만 수행한다. |

## Endpoints

| Method | Path | Description | Related FR | Auth |
| --- | --- | --- | --- | --- |
| GET | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/availability` | A/B 테스트 진입 가능 여부 조회 | FR-001, FR-010 | builder 이상 |
| GET | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines/latest` | 최신 baseline 실행 로그 조회 | FR-002, FR-004, FR-007 | builder 이상 |
| GET | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/baselines` | baseline 실행 로그 목록 검색/필터/정렬 | FR-002, FR-004, FR-007 | builder 이상 |
| GET | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/experiments` | 과거 experiment/candidate 결과 목록 조회 | FR-006, FR-009, FR-010 | builder 이상 |
| POST | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/compare` | 선택 baseline input으로 B 후보 실행 | FR-003, FR-004, FR-005, FR-006, FR-009, FR-010 | builder 이상 |
| PATCH | `/api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/apply` | 선택한 B 후보 설정을 current draft에 적용 | FR-008, FR-010 | builder 이상 |

## Implementation Tracking

현재 문서는 Cost Optimizer API 계약과 구현 추적 상태를 함께 기록한다. 실제 router/service/schema 파일명은 Gateway의 기존 workflow/app API 구조에 맞춰 확정한다.

| FR | API/계약 단위 | 예상 코드 위치 | 구현 상태 | API 테스트 코드 | 테스트 통과 여부 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | `GET availability` | `apps/gateway/api/v1/endpoints/workflow.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-002 | `GET baselines/latest`, `GET baselines` | `apps/gateway/api/v1/endpoints/workflow.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-003 | compare candidate request schema | `apps/gateway/api/v1/endpoints/workflow.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-004 | baseline input restore/lock | `apps/gateway/api/v1/endpoints/workflow.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-005 | hybrid compare execution | `apps/gateway/api/v1/endpoints/workflow.py`, `apps/workflow_engine/` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-006 | compare response trace/diff | `apps/gateway/api/v1/endpoints/workflow.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-007 | downstream compatibility response | `apps/gateway/api/v1/endpoints/workflow.py`, workflow graph helper | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-008 | `PATCH apply` | `apps/gateway/api/v1/endpoints/workflow.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-009 | LLM usage/cost logging/history | `apps/gateway/api/v1/endpoints/workflow.py`, `apps/workflow_engine/`, `apps/shared/db/models/cost_optimizer.py`, `apps/shared/services/cost_optimizer_retention.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py`, `apps/workflow_engine/tests/nodes/test_llm_node_runtime.py`, `apps/shared/tests/services/test_cost_optimizer_retention.py` | 통과 |
| FR-010 | builder permission enforcement | `apps/gateway/api/v1/endpoints/workflow.py`, `apps/gateway/auth/permissions.py` | 구현 완료 | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |

## Model Routing Recommendation Contract

이 섹션은 FR-011 사용자 클릭 기반 모델 라우팅 최적화의 후속 API 계약이다. 이 계약은 LLM 노드 실행 중 자동으로 호출되지 않는다. 사용자가 LLM 노드 상세 화면에서 `모델 라우팅 최적화`를 눌렀을 때만 최근 배포 후 운영 로그를 분석하고 추천 결과를 반환한다.

예상 service/API entrypoint:

```python
ModelRouter.recommend(context: ModelRoutingRecommendationContext) -> ModelRoutingRecommendation
```

`ModelRoutingRecommendationContext`는 다음 정보를 포함한다.

| Field | Type | Required | Description |
| --- | --- | --- | --- |
| `organization_id` | UUID string | yes | credential/model 사용 가능성 검증 scope |
| `user_id` | UUID string nullable | yes | 실행 주체. private Knowledge Base와 credential 사용 가능성 판단에 필요하다. |
| `workflow_id` | UUID string | yes | 대상 workflow |
| `node_id` | string | yes | 대상 LLM node |
| `current_model_id` | string nullable | yes | 현재 target LLM node에 저장된 기본 모델 |
| `current_fallback_model_id` | string nullable | no | 현재 target LLM node에 저장된 fallback 모델 |
| `candidate_models` | array | yes | 현재 organization credential로 실제 실행 가능하고 workflow LLM node 후보 필터를 통과한 chat model 후보 |
| `input_summary` | object nullable | no | 입력 길이, 변수 수, RAG query 여부 같은 safe summary |
| `output_contract` | object nullable | no | text/json/schema, downstream variable contract, required key summary |
| `knowledge_summary` | object nullable | no | Knowledge/RAG 사용 여부, 선택 KB 수, context budget 같은 safe summary |
| `node_profile` | object nullable | no | 최근 target node run 기반 성공률, 비용, latency, fallback/retry 지표 |

`ModelRoutingRecommendation`은 다음 정보를 반환한다.

| Field | Type | Description |
| --- | --- | --- |
| `analysis_stage` | `insufficient_logs` \| `reviewable` \| `high_confidence` | 운영 로그 축적 정도로 결정한 추천 신뢰 단계 |
| `recommended_model_id` | string nullable | 사용자가 적용할 수 있는 추천 모델. 품질 gate를 통과하지 못하면 null일 수 있다. |
| `recommended_fallback_model_id` | string nullable | 추천 fallback 모델 |
| `estimated_cost_reduction_rate` | number nullable | judge 비용과 예상 fallback 비용을 반영한 순절감률 |
| `quality_basis` | object | schema pass, downstream success, fallback/retry, latency, token 변화 같은 safe metric summary |
| `judge_policy` | `not_required` \| `sampled_async` \| `required_before_apply` | judge 호출 필요 여부 |
| `warnings` | array | 추천 보류 또는 적용 주의 사유 |
| `reason` | string | 사용자가 이해할 수 있는 추천 사유 |
| `policy_version` | string | 추천 정책 버전 |

추천 분석은 다음 순서로 동작한다.

1. 현재 organization에서 실행 가능한 chat model 중 workflow LLM node 후보 필터를 통과한 모델만 남긴다. 날짜 suffix 모델, embedding/image/audio/realtime/moderation/tts/transcribe/sora/search 전용 모델은 제외한다.
2. 후보가 없으면 provider 호출 없이 명확한 error를 반환한다.
3. target LLM node의 배포 후 운영 node-level profile을 조회한다.
4. `deployment_id IS NULL`인 테스트 실행, 배포 전 수동 실행, `cost_optimizer_compare` 실행은 추천 프로파일에서 제외한다.
5. 사용 가능한 운영 로그가 부족하면 추천 모델을 null로 두고 `insufficient_logs`와 필요한 추가 로그 조건을 반환한다.
6. 품질 gate를 통과한 후보만 추천한다. 비용 절감만으로 더 약한 모델을 추천하지 않는다.
7. confidence가 낮거나 schema/downstream 근거가 부족하면 judge를 즉시 모든 run에 붙이지 않고 `sampled_async` 또는 `required_before_apply`로 표시한다.
8. 사용자가 추천을 적용하면 기존 `PATCH /cost-optimizer/apply`와 동일하게 current draft의 target LLM node 설정을 명시적으로 갱신한다.

라우터가 사용하는 node-level profile은 workflow 전체 run이 아니라 target LLM node 기준으로 계산한다. `workflow_runs.deployment_id IS NOT NULL`인 배포 후 운영 실행만 stage count와 품질 gate에 포함한다. 배포 전 테스트 실행과 Cost Optimizer 비교 실행은 profile sample에서 제외한다. usage/output이 없는 run은 profile sample에서 제외한다. 명시적인 downstream summary가 없으면 배포 후 workflow run 성공 여부를 downstream 통과 근거로 사용할 수 있다. 실패 run은 sample count에는 제외할 수 있지만 fallback rate, retry rate, failure trend 계산에는 포함할 수 있다.

workflow runtime은 이 추천 결과를 자동으로 사용하지 않는다. 추천 적용 전까지 기존 `model_id`와 `fallback_model_id`가 그대로 실행된다. 과거 `auto_model_routing` 저장 필드가 남아 있더라도 런타임 모델 선택에는 영향을 주지 않는다.

### Actual Provider Verification Contract

`scripts/verify_model_router_actual.py`는 제품 HTTP API가 아니라 FR-011 라우터 정책을 실제 provider 호출로 검증하는 운영/개발용 스크립트다. 이 스크립트는 다음 계약을 따른다.

| Option | Description |
| --- | --- |
| `--provider auto` | 현재 organization/user가 실행 가능한 provider preset을 OpenAI, Anthropic, Google 순서로 탐색한다. |
| `--provider openai\|anthropic\|google` | 지정 provider preset만 사용한다. 해당 credential/model relation/use 권한이 없으면 provider 호출 전에 실패한다. |
| `--cheap-model`, `--mid-model`, `--high-model` | preset의 실행 대상 모델을 명시적으로 덮어쓴다. 세 모델은 같은 provider여야 한다. |
| `--judge-model` | LLM judge에 사용할 모델을 덮어쓴다. 실행 가능하면 실행 대상 provider와 달라도 허용한다. |
| `--dry-run` | provider 호출 없이 credential/model relation/use 권한과 모델 해석만 검증한다. |

기본 provider preset은 다음 의미를 가진다.

| Provider | Cheap | Mid | High | Judge |
| --- | --- | --- | --- | --- |
| OpenAI | `gpt-4o-mini` | `gpt-4.1-mini` | `gpt-4.1` | `gpt-4.1-mini` |
| Anthropic | `claude-haiku-4-5-20251001` | `claude-sonnet-4-5-20250929` | `claude-opus-4-5-20251101` | `claude-sonnet-4-5-20250929` |
| Google | `gemini-2.5-flash-lite` | `gemini-2.5-flash` | `gemini-2.5-pro` | `gemini-2.5-flash` |

Judge 호출은 OpenAI `response_format`에 의존하지 않는다. provider 공통 prompt로 compact JSON을 요청하고, 응답 text에서 JSON object를 파싱한다. 이 방식은 Anthropic/Google만 쓰는 organization에서도 API key와 model relation이 있으면 같은 품질 gate 검증을 수행하기 위한 최소 공통 계약이다.

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

Cost Optimizer의 B 후보 실행은 일반 workflow 실행 로그와 같은 `workflow_runs`/`workflow_node_runs`에 저장되지만, A baseline 후보로 다시 선택되면 안 된다. 따라서 baseline API는 `llm_usage_logs.cost_optimizer_candidate_id`가 있거나 `cost_optimizer_candidates.candidate_workflow_run_id`로 연결된 run을 제외한다.

`trace_payloads` retention, redaction, 저장 누락으로 target LLM node input을 복원할 수 없는 경우에도 baseline row는 목록에 포함한다. 다만 response는 `input_available=false`, `compare_available=false`를 반환하고, compare API는 해당 baseline으로 B 후보 실행을 시작하지 않는다.

## Persistence Model

관련 FR: FR-005, FR-006, FR-008, FR-009

Cost Optimizer 비교 실행은 기존 run/usage/trace 테이블을 원천으로 사용하되, A/B 테스트 세션과 후보 실행을 묶기 위해 전용 테이블을 추가한다.

### `cost_optimizer_experiments`

하나의 A/B 테스트 세션을 나타낸다. 사용자가 특정 workflow의 특정 LLM node에서 baseline을 선택해 A/B 테스트 workspace를 시작하면 생성된다. 같은 baseline을 사용하더라도 사용자가 나중에 다시 A/B 테스트를 시작하면 기존 experiment를 재사용하지 않고 새 experiment를 생성한다.

주요 필드:

| Field | Type | Description |
| --- | --- | --- |
| `id` | UUID | experiment id. compare/apply response의 상위 식별자다. |
| `organization_id` | UUID | organization scope |
| `workflow_id` | UUID | target workflow |
| `app_id` | UUID | workflow가 속한 app |
| `node_id` | string | target LLM node id |
| `baseline_node_run_id` | UUID | A baseline의 `workflow_node_runs.id` |
| `baseline_workflow_run_id` | UUID | A baseline이 속한 `workflow_runs.id` |
| `baseline_node_options` | JSONB | baseline 실행 시점의 LLM node 설정 snapshot |
| `baseline_usage_summary` | JSONB | baseline 비용/토큰/latency safe summary. 비용/토큰 원천은 `llm_usage_logs`이고, latency는 `llm_usage_logs.latency_ms`가 0 또는 누락이면 `workflow_node_runs.duration`을 ms로 환산해 사용한다. |
| `baseline_trace_summary` | JSONB | baseline input/output/retrieval safe summary. raw payload와 secret은 포함하지 않는다. |
| `baseline_downstream_snapshot` | JSONB | baseline 생성/조회 시점의 downstream safe snapshot. compare의 contract check 기준이며 raw payload와 secret은 포함하지 않는다. |
| `usage_summary` | JSONB | 이 experiment에 속한 candidate 실행 비용/토큰/latency 합계 |
| `status` | string | `draft`, `running`, `completed`, `applied`, `failed`, `archived` |
| `created_by` | UUID | experiment 생성 사용자 |
| `created_at`, `updated_at` | datetime | 생성/수정 시각 |
| `retention_expires_at` | datetime nullable | trace metadata retention 정책 기준 experiment/candidate summary 만료 시각 |

### `cost_optimizer_candidates`

하나의 experiment 안에서 실행한 B 후보 하나를 나타낸다. 같은 workspace 안에서 후보 설정을 바꿔 여러 번 실행할 수 있으므로 experiment와 candidate는 1:N 관계다.

주요 필드:

| Field | Type | Description |
| --- | --- | --- |
| `id` | UUID | candidate id |
| `experiment_id` | UUID | `cost_optimizer_experiments.id` |
| `name` | string | UI의 테스트명 |
| `model_id` | string | 결과분석 필터용 후보 기본 모델 id |
| `fallback_model_id` | string nullable | 결과분석 필터용 후보 fallback 모델 id |
| `task_type` | string nullable | 결과분석 필터용 후보 작업 유형 |
| `candidate_settings` | JSONB | B 후보 LLM node 설정 safe snapshot. prompt 본문은 redacted summary로 저장하고, apply 검증용 `_settings_fingerprint`를 포함한다. |
| `candidate_workflow_run_id` | UUID nullable | B 후보 실행으로 생성된 `workflow_runs.id` |
| `candidate_node_run_id` | UUID nullable | B 후보 target node의 `workflow_node_runs.id` |
| `total_cost` | Numeric nullable | 후보 실행 비용 합계. 조회 편의를 위한 summary이며 원천은 `llm_usage_logs`다. |
| `total_tokens` | Integer nullable | 후보 실행 토큰 합계 |
| `latency_ms` | Integer nullable | 후보 target LLM node latency |
| `schema_status` | string nullable | `not_checked`, `pass`, `failed` |
| `downstream_state` | string nullable | `compatible`, `warning`, `incompatible`, `unknown` |
| `usage_summary` | JSONB | model, token, cost, latency summary. 원천은 `llm_usage_logs`다. |
| `schema_validation` | JSONB | output format/schema 검증 결과 |
| `retrieval_summary` | JSONB | B 후보 Knowledge/RAG safe retrieval summary. raw chunk content와 raw source metadata는 포함하지 않는다. |
| `downstream_compatibility` | JSONB | downstream 호환성 판정 결과 |
| `diff_summary` | JSONB | A/B 비용, 토큰, latency, 출력 차이 요약 |
| `status` | string | `draft`, `running`, `success`, `failed`, `schema_failed` |
| `is_applied` | boolean | 현재 draft에 적용된 후보 여부 |
| `applied_at` | datetime nullable | 적용 시각 |
| `applied_by` | UUID nullable | 후보를 현재 draft에 적용한 사용자 |
| `applied_llm_node_version_id` | UUID nullable | 적용으로 생성된 `llm_node_versions.id` |
| `created_at`, `updated_at` | datetime | 생성/수정 시각 |

원천 데이터 관계:

- A baseline의 실행/입출력/비용 원천은 `workflow_node_runs`, `workflow_runs`, `llm_usage_logs`, `trace_payloads`다. Baseline 실행 시간은 LLM usage latency가 없을 수 있으므로 `workflow_node_runs.duration` fallback을 허용한다.
- B candidate의 실제 실행/입출력/비용 원천도 동일한 기존 테이블이다.
- B candidate 실행에서 생성되는 `workflow_runs.id`는 `cost_optimizer_candidates.candidate_workflow_run_id`로 저장한다. 이 값은 candidate 실행 로그가 최신 baseline 후보로 다시 잡히지 않게 하는 1차 식별자다.
- B candidate 실행에서 생성되는 `llm_usage_logs` row는 `cost_optimizer_candidate_id`로 `cost_optimizer_candidates.id`를 직접 참조한다. worker 전파가 지연되거나 누락되어도 Gateway는 `candidate_workflow_run_id` 기준으로 usage row를 candidate에 다시 연결한다.
- `cost_optimizer_experiments`와 `cost_optimizer_candidates`는 원천 로그를 복제하기 위한 테이블이 아니라, baseline과 여러 candidate 실행을 하나의 비교 흐름으로 묶는 메타 저장소다.
- experiment의 `usage_summary`는 해당 experiment에 속한 candidate 비용만 합산한다. 같은 baseline을 기준으로 여러 experiment가 있으면 baseline 누적 비용은 `baseline_node_run_id`가 같은 experiments를 별도로 합산해 계산한다.
- raw prompt, credential 원문, API key, encrypted config, secret payload는 두 테이블에 저장하지 않는다.
- `cost_optimizer_candidates.candidate_settings`의 `system_prompt`, `user_prompt`, `assistant_prompt`는 `{ redacted, present, length }` 형태의 요약만 저장한다. compare/apply 동일 후보 검증은 원문 prompt가 아니라 비가역 `_settings_fingerprint`로 수행한다.
- `baseline_trace_summary`와 `retrieval_summary`에는 `retrieved_chunk_count`, `knowledge_base_count`, `source_summary`, `score_summary`, `hierarchy_fallback` 같은 safe summary만 저장한다. `raw_chunk_content`, `source_metadata`, raw document name/file name 계열 값은 저장하거나 반환하지 않는다. safe summary의 list 값은 최대 20개, string 값은 최대 200자로 제한한다.
- `baseline_downstream_snapshot`에는 target node 이후 직접/간접 소비 노드의 id, type, edge, selector/path 계약, side-effect 여부, topology hash만 저장한다. 노드 실행 raw output, prompt 원문, credential, 외부 전송 payload는 저장하지 않는다.

조회/제약 권장 사항:

| 대상 | 권장 사항 | 목적 |
| --- | --- | --- |
| `cost_optimizer_experiments` | index `(workflow_id, node_id, baseline_node_run_id, created_at DESC)` | 결과분석에서 같은 workflow/node/baseline 기준 최신 실험 재조회 |
| `cost_optimizer_experiments` | index `(organization_id, created_by, created_at DESC)` | 사용자별 실험 이력 조회 |
| `cost_optimizer_candidates` | index `(experiment_id, status, is_applied)` | experiment 상세에서 후보 상태/적용 여부 조회 |
| `cost_optimizer_candidates` | index `(model_id, created_at DESC)` | 모델 기준 결과 분석 필터 |
| `cost_optimizer_candidates` | partial unique `(experiment_id) WHERE is_applied = true` | 하나의 experiment 안에서 적용 후보를 최대 1개로 제한 |

`DESC`는 최신 항목을 먼저 조회하기 위한 내림차순 정렬이다.

저장/보관 정책:

- Cost Optimizer experiment/candidate summary는 trace metadata retention 정책의 `metadata_retention_days`를 따른다.
- 만료 기준은 `cost_optimizer_experiments.retention_expires_at`이다. candidate는 experiment 삭제 cascade로 함께 정리된다.
- `llm_usage_logs.cost_optimizer_candidate_id`는 candidate 삭제 시 `SET NULL`이 되며, usage log 자체 보관은 기존 usage/trace 보관 경계를 따른다.
- candidate 하나가 retry/fallback 등으로 여러 `llm_usage_logs`를 만들 때는 `llm_usage_logs.cost_optimizer_candidate_id` 기준으로 합산한다.
- `baseline_trace_summary`와 `retrieval_summary`의 redaction 기준은 위 safe summary 규칙을 따른다. list 값은 최대 20개, string 값은 최대 200자로 제한한다.

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

`contract_check`는 B candidate output이 현재 target LLM node의 직접 소비 노드가 요구하는 입력 selector를 만족하는지 검사한 결과다. 현재 1차 구현은 다음 직접 소비 노드 계약을 검사한다.

contract check의 기준은 baseline 생성/조회 시점에 만든 downstream snapshot이다. Compare API는 `baseline_id`로 baseline row를 복원하고, 해당 row의 `baseline_downstream_snapshot`과 B candidate output을 사용해 계약을 검사한다. 현재 workflow graph는 snapshot과의 topology/hash 비교 및 적용 위험 안내에 사용한다.

신규 baseline 생성/조회 경로는 `baseline_downstream_snapshot`을 만들 수 있어야 한다. 기존 데이터, retention 만료, 또는 graph 복원 불가로 snapshot이 없을 때만 `state=unknown`, `contract_check.status=skipped`, `warnings=["baseline_downstream_snapshot_unavailable"]` 형태의 fallback을 허용한다.

| Node type | 검사 기준 |
| --- | --- |
| `variableExtractionNode` | `source_selector`가 target LLM node를 가리키면 `mappings[].json_path`가 candidate output JSON에 존재해야 한다. |
| `conditionNode` | `cases[].conditions[].variable_selector`가 target LLM node를 가리키면 selector key가 candidate output에 존재해야 한다. |
| `answerNode` | `outputs[].value_selector`가 target LLM node를 가리키면 selector key가 candidate output에 존재해야 한다. |
| `slackPostNode` | `referenced_variables[].value_selector`가 target LLM node를 가리키면 selector key가 candidate output에 존재해야 한다. |

후보 출력의 `text`가 JSON 문자열이면 JSON으로 파싱해 selector/path 존재 여부를 확인한다. 필수 path가 없으면 topology가 같아도 `state=incompatible`, `contract_check.status=failed`로 반환한다.

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

응답 생성 시 Gateway는 baseline row 내부에 `baseline_downstream_snapshot`을 생성해야 한다. API response에는 snapshot 원문을 노출하지 않고 `downstream_compatibility` summary만 반환한다. snapshot은 이후 `POST /compare`에서 B candidate output contract check의 기준으로 사용된다.

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

목록 row도 baseline 후보로 선택될 수 있으므로 각 row를 만들 때 downstream snapshot을 생성하거나, 사용자가 해당 row를 baseline으로 선택하는 시점에 동일한 규칙으로 snapshot을 생성해야 한다. 신규 compare 가능 row에서 snapshot 생성 실패가 발생하면 `compare_available=false` 또는 `downstream_compatibility.state=unknown`과 명확한 unavailable reason을 반환한다.

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

### GET experiments

관련 FR: FR-006, FR-009, FR-010

`GET /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/experiments`

같은 workflow, target LLM node 기준으로 저장된 Cost Optimizer experiment와 B candidate 요약을 조회한다. 결과 분석 화면에서 과거 비교 결과를 다시 열거나, 같은 baseline 기준 후보 실행 이력을 확인할 때 사용한다.

Query:

| Name | Type | Description |
| --- | --- | --- |
| `baseline_id` | UUID optional | 특정 A baseline `workflow_node_runs.id` 기준으로 좁힌다. |
| `date_from`, `date_to` | datetime optional | experiment 생성 시각 범위 |
| `created_by` | UUID optional | experiment 생성 사용자 |
| `candidate_status` | string optional | `success`, `failed`, `schema_failed`, `running` |
| `model` | string optional | 후보 기본 모델 id |
| `is_applied` | boolean optional | 현재 draft에 적용된 후보 포함 여부 |
| `schema_status` | string optional | `not_checked`, `pass`, `failed` |
| `downstream_state` | string optional | `compatible`, `warning`, `incompatible`, `unknown` |
| `limit`, `offset` | integer | pagination |

Response:

```json
{
  "total": 1,
  "limit": 20,
  "offset": 0,
  "items": [
    {
      "experiment_id": "uuid",
      "workflow_id": "uuid",
      "app_id": "uuid",
      "node_id": "llm-triage",
      "baseline_node_run_id": "uuid",
      "baseline_workflow_run_id": "uuid",
      "status": "completed",
      "created_by": "uuid",
      "created_at": "2026-07-05T01:30:00+00:00",
      "usage_summary": {
        "total_tokens": 240,
        "cost": 0.0006
      },
      "candidates": [
        {
          "candidate_id": "uuid",
          "name": "비용 절감 후보",
          "status": "success",
          "model_id": "gpt-4.1-mini",
          "fallback_model_id": null,
          "task_type": "generate",
          "total_cost": 0.0006,
          "total_tokens": 240,
          "latency_ms": 1200,
          "schema_status": "pass",
          "downstream_state": "compatible",
          "is_applied": false,
          "created_at": "2026-07-05T01:30:00+00:00"
        }
      ]
    }
  ]
}
```

이 응답은 summary 조회용이다. raw prompt, credential 원문, secret payload는 포함하지 않는다. 상세 trace 원천은 기존 trace/usage 조회 경계에서 권한과 redaction 정책을 거쳐 조회한다.

### POST compare

관련 FR: FR-003, FR-004, FR-005, FR-006, FR-009, FR-010

`POST /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/cost-optimizer/compare`

A baseline input을 사용해 B 후보 설정을 실행한다. A baseline은 재실행하지 않는다.

`baseline_id`는 `workflow_node_runs.id`다. 해당 baseline의 target LLM node input을 복원할 수 없으면 API는 B 후보 실행을 시작하지 않고 `400 cost_optimizer.baseline_input_unavailable`을 반환한다.

Compare는 `baseline_id`에 연결된 downstream snapshot을 복원한 뒤 B candidate output에 대해 contract check를 수행한다. snapshot이 있으면 downstream 상태는 snapshot 기반 검사 결과를 우선한다. snapshot이 없으면 신규 데이터 누락으로 보고 서버 로그에 남기며, response는 `state=unknown`, `contract_check.status=skipped`, `warnings=["baseline_downstream_snapshot_unavailable"]`를 반환한다.

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
      "score_threshold": 0.7,
      "dedupe_retrieved_context": true,
      "retrieved_context_max_chars": 6000,
      "retrieved_context_compression": "off",
      "answer_grounding_check": "basic"
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
| `candidate.task_type` | `classify`, `extract`, `summarize`, `generate`, `reason` | no | 기본값은 현재 node 설정 또는 `generate`다. 원본 LLM 노드 상세 편집과 같은 값 체계를 사용한다. |
| `candidate.system_prompt` | string | no | 생략하면 현재 node 설정을 보존한다. 세 prompt를 모두 명시하면서 전부 비우면 invalid candidate다. |
| `candidate.user_prompt` | string | no | 변수 참조는 baseline input/upstream output 기준으로 resolve 가능해야 한다. |
| `candidate.assistant_prompt` | string | no | 변수 참조는 baseline input/upstream output 기준으로 resolve 가능해야 한다. |
| `candidate.referenced_variables` | array | no | prompt token을 upstream output selector로 렌더링하기 위한 `{ name, value_selector }` 목록이다. 각 `value_selector`는 최소 `[node_id, output_key]` 형태여야 한다. |
| `candidate.parameters.max_tokens` | number | yes | 1~8192 |
| `candidate.parameters.temperature` | number | yes | 0~2 |
| `candidate.parameters.top_p` | number | no | 0~1 |
| `candidate.parameters.presence_penalty` | number | no | -2~2 |
| `candidate.parameters.frequency_penalty` | number | no | -2~2 |
| `candidate.parameters.stop` | string[] | no | 최대 4개 |
| `candidate.output_format.type` | `text` or `json` | yes | `json`이면 schema 검증을 수행한다. |
| `candidate.output_format.schema` | object | no | 1차 UI는 flat key-type schema를 만든다. API는 valid JSON schema object만 허용하며, `required`에 들어간 field는 `properties`에 정의돼 있어야 한다. |
| `candidate.knowledge.knowledge_base_ids` | string[] | no | 모두 현재 사용자/organization/workflow scope에서 사용 가능해야 한다. |
| `candidate.knowledge.top_k` | number | no | Knowledge/RAG 사용 시 retrieval 개수다. |
| `candidate.knowledge.score_threshold` | number | no | Knowledge/RAG 사용 시 retrieval score threshold다. |
| `candidate.knowledge.dedupe_retrieved_context` | boolean | no | `true`이면 검색된 문서 조각 중 중복 근거를 제거한다. |
| `candidate.knowledge.retrieved_context_max_chars` | number or null | no | 검색으로 주입되는 Knowledge/RAG context의 최대 글자 수다. `null`이면 제한 없음이며 author prompt는 제한 대상이 아니다. |
| `candidate.knowledge.retrieved_context_compression` | `off`, `light`, `strong` | no | 검색 문서 압축 강도다. |
| `candidate.knowledge.answer_grounding_check` | `off`, `basic`, `strict` | no | 답변이 검색 근거로 뒷받침되는지 확인하는 수준이다. |

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
    "candidate_workflow_run_id": "uuid",
    "settings": {},
    "output": {},
    "usage": {
      "model": "gpt-4.1-mini",
      "prompt_tokens": 900,
      "completion_tokens": 180,
      "total_tokens": 1080,
      "cost": 0.0011,
      "cost_unavailable": false,
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

모델 가격 정보가 없어 비용을 계산할 수 없으면 `candidate.usage.cost`는 `null`, `candidate.usage.cost_unavailable`은 `true`로 반환한다. 이 경우 토큰과 latency를 계산할 수 있다면 그대로 반환한다.

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

`downstream_compatibility.state`가 `warning` 또는 `incompatible`인 저장 후보를 적용하는 경우, API는 `acknowledge_downstream_warning=true` 없이는 `400 cost_optimizer.downstream_ack_required`로 적용을 거부한다.

`comparison_id`에 해당하는 저장 후보 중 request의 `candidate_settings`와 일치하는 후보가 있으면, 적용 성공 시 해당 `cost_optimizer_candidates` row의 `is_applied`를 `true`로 바꾸고 `applied_at`, `applied_by`를 기록한다. 같은 experiment 안의 다른 후보는 `is_applied=false`로 정리해 experiment history에서 적용된 후보를 하나만 표시한다.

`comparison_id`가 없거나 UUID로 해석할 수 없거나, 해당 `comparison_id`에 저장된 후보가 없거나, request의 `candidate_settings`와 일치하는 저장 후보가 없으면, API는 검증되지 않은 후보 적용으로 보고 `400 cost_optimizer.candidate_not_found`를 반환한다.

현재 apply request에는 기대 draft revision을 전달하는 필드가 없다. 따라서 현재 계약은 적용 성공 후 `updated_draft_revision`을 반환하는 데까지를 보장한다. baseline 비교 이후 current draft가 바뀌었는지 감지해 `409 cost_optimizer.draft_conflict`로 막는 동작은 expected draft revision 계약을 추가하는 후속 보강 범위다.

## Errors

| Status | Code | Description | Related FR |
| --- | --- | --- | --- |
| 400 | `cost_optimizer.not_llm_node` | target node가 `llmNode`가 아님 | FR-001 |
| 400 | `cost_optimizer.no_baseline` | baseline으로 사용할 로그가 없음 | FR-002 |
| 400 | `cost_optimizer.invalid_candidate` | B 후보 설정이 유효하지 않음 | FR-003 |
| 400 | `cost_optimizer.schema_failed_candidate` | schema 검증 실패 후보를 적용하려고 함 | FR-003, FR-008 |
| 400 | `cost_optimizer.candidate_not_found` | apply 요청의 `comparison_id`가 없거나, 해당 comparison 안에서 request 후보 설정과 일치하는 저장 후보를 찾을 수 없음 | FR-008, FR-009 |
| 400 | `cost_optimizer.baseline_input_unavailable` | baseline input을 복원할 수 없음 | FR-004 |
| 400 | `cost_optimizer.downstream_ack_required` | downstream warning 확인 없이 적용 요청 | FR-007, FR-008 |
| 403 | `permission.denied` | builder 이상 권한 없음 | FR-010 |
| 404 | `resource.not_found` | workflow, node, baseline이 없거나 scope 밖임 | FR-001, FR-002 |
| 422 | `cost_optimizer.model_unavailable` | 사용할 수 없는 credential/model 후보 | FR-003, FR-010 |
| 422 | `cost_optimizer.knowledge_unavailable` | 사용할 수 없거나 접근 권한이 없는 Knowledge Base 후보 | FR-003, FR-010 |
| 500 | `cost_optimizer.compare_failed` | B 후보 실행 결과를 failed candidate로 기록할 수 없는 예기치 않은 서버 오류 | FR-006 |

후속 보강 오류:

| Status | Code | Description | Related FR |
| --- | --- | --- | --- |
| 409 | `cost_optimizer.draft_conflict` | expected draft revision 계약 추가 후 현재 draft가 baseline 비교 이후 충돌됨 | FR-008 |

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
