# Cost Optimizer Test Cases

Status: Draft
Verified Against: feature/mba-112 @ df9ed6df92c2c8177cc9ef0fe2f2c50967e423f6

## Purpose

이 문서는 `requirements.md`의 FR-001부터 FR-010까지를 테스트 관점에서 검증 가능한 형태로 정리한다.
FR-011 모델 라우팅과 최적화 에이전트는 후속 기능이므로 현재 구현 테스트 대상이 아니다.

테스트는 LLM 노드 단위 Cost Optimizer 흐름을 기준으로 한다. workflow 전체 A/B 테스트, 자동 모델 라우팅, 최적화 에이전트는 이 문서의 1차 검증 범위가 아니다.

## Test Matrix

| FR | Component Spec | API Spec | Test Focus | 테스트 코드 상태 | 테스트 통과 여부 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | LLM node detail action | GET availability | LLM 노드에서만 A/B 테스트 진입 가능 | 작성 완료 | 통과 |
| FR-002 | Baseline selection, baseline log picker | GET latest baseline, GET baselines | 최신/이전 baseline 로그 선택 | 작성 완료 | 통과 |
| FR-003 | Candidate editor | POST compare request candidate schema | B 후보 설정 입력과 검증 | 작성 완료 | 통과 |
| FR-004 | Baseline input lock display | baseline input 고정 | B 실행 입력이 A baseline 입력으로 고정됨 | 작성 완료 | 통과 |
| FR-005 | Hybrid compare flow | POST compare | A는 재실행하지 않고 B만 실행 | 작성 완료 | 통과 |
| FR-006 | A/B compare workspace, result analysis, Inspector | compare response trace/diff | A/B 결과, 적용 판단 요약, 핵심 지표 비교, Inspector 데이터 표시 | 작성 완료 | 통과 |
| FR-007 | Downstream compatibility badge | downstream compatibility fragment | downstream 호환성 3상태 표시와 차단/경고 | 작성 완료 | 통과 |
| FR-008 | Apply candidate action | PATCH apply | B 후보 설정을 current draft에 적용 | 작성 완료 | 통과 |
| FR-009 | Cost/usage display | llm usage logging | 비교 실행 비용/토큰/latency 기록과 표시 | 작성 완료 | 통과 |
| FR-010 | Permission-gated UI | builder permission enforcement | builder 이상 권한 강제 | 작성 완료 | 통과 |
| FR-011 | Deferred model routing/optimizer agent | 없음 | 후속 기능으로 분리되어 현재 테스트하지 않음 | 범위 제외 | 해당 없음 |

## Test Implementation Tracking

테스트 파일명은 구현 시점에 실제 컴포넌트/API 파일명에 맞춰 조정할 수 있다. 단, FR과 테스트 파일의 역참조는 유지해야 한다.

| FR | 테스트 레이어 | 예상 테스트 파일 | 검증 대상 | 작성 상태 | 실행 명령 | 통과 여부 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-001 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx` | LLM 노드 전용 진입 액션, non-LLM 차단, availability 기반 비활성화, 저장되지 않은 draft 안내 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx` | 통과 |
| FR-001 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | availability, not-LLM, not-found, builder 권한 강제 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-002 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr2-baseline-selection.test.tsx` | 최신/이전 baseline 선택, 최신 로그 요약, preview 전체 표시, 최신 비교 가능 로그 없음 CTA 차단, 필터/정렬 UI | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr2-baseline-selection.test.tsx` | 통과 |
| FR-002 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | latest/list baseline query, 필터/정렬/pagination, secret redaction, trace payload availability | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-003 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr3-candidate-editor.test.tsx` | 후보 모델/대체 모델 선택 UI, JSON schema key-type row 추가, prompt variable token editor 재사용, compare request schema 변환 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr3-candidate-editor.test.tsx` | 통과 |
| FR-003 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr3-llm-node-task-type.test.tsx` | 원본 LLM 노드 상세 설정의 task type 선택과 node data 저장 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr3-llm-node-task-type.test.tsx` | 통과 |
| FR-003 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr3-rag-cost-options.test.tsx` | RAG 비용 최적화 옵션 노출/변경 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr3-rag-cost-options.test.tsx` | 통과 |
| FR-003 | Workflow runtime | `apps/workflow_engine/tests/nodes/test_llm_node_runtime.py` | 중복 근거 제거, 참조 문서 길이 제한, 검색 문서 압축, 답변 근거 확인 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/workflow_engine/.venv/Scripts/python.exe -m pytest apps/workflow_engine/tests/nodes/test_llm_node_runtime.py` | 통과 |
| FR-003 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | candidate schema validation, Knowledge Base/model 사용 가능성 검증, schema_failed response/apply 차단 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-004 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr4-fr5-hybrid-compare-flow.test.tsx` | baseline input lock 표시, compare request에 임의 input을 넣지 않음 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr4-fr5-hybrid-compare-flow.test.tsx` | 통과 |
| FR-004 | Gateway service/API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | baseline input restore, wrong baseline scope | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-005 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr4-fr5-hybrid-compare-flow.test.tsx` | A 고정, B running/result 상태 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr4-fr5-hybrid-compare-flow.test.tsx` | 통과 |
| FR-005 | Frontend API client | `apps/client/app/features/workflow/tests/costOptimizer/fr4-fr5-compare-api-client.test.ts` | compare API path와 request body 계약 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr4-fr5-compare-api-client.test.ts` | 통과 |
| FR-005 | Gateway service/API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | A 미재실행, B만 실행 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-006 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | 실험 설정/결과 분석 mode switch, stale 안내, 적용 판단 요약, 핵심 지표 비교, Inspector 탭, schema 검증 결과, A/B retrieval summary 표시, 직접 URL 진입 권한 차단 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | 통과 |
| FR-006 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | compare response shape, safe trace, RAG raw content/source metadata redaction, 비용/토큰/latency diff, 실패 후보 response | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-007 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr7-downstream-compatibility.test.tsx` | compare 응답의 downstream 3상태 라벨, 설명, 검사 노드 표시 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr7-downstream-compatibility.test.tsx` | 통과 |
| FR-007 | Gateway service/API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | compatible/warning/incompatible 판정, `variableExtractionNode`/`conditionNode`/`answerNode`/`slackPostNode` 직접 소비 노드 contract 검사, compare response 연결 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-008 | Frontend API client | `apps/client/app/features/workflow/tests/costOptimizer/fr8-apply-api-client.test.ts` | apply API path와 `candidate_settings` request body 계약 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr8-apply-api-client.test.ts` | 통과 |
| FR-008 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr8-apply-flow.test.tsx` | 성공한 B 후보 적용 버튼 활성화, 적용 전 변경 요약 모달, downstream warning 확인, apply 호출, 적용 성공 안내 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr8-apply-flow.test.tsx` | 통과 |
| FR-008 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | apply가 current draft target LLM node data를 B candidate의 모델, prompt, 고급 파라미터, 출력 형식, Knowledge/RAG 비용 최적화 설정으로 갱신 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-009 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr9-usage-display.test.tsx` | A/B prompt/completion/total token, 비용, latency, experiment history 필터 UI 표시 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr9-usage-display.test.tsx` | 통과 |
| FR-009 | Frontend API client | `apps/client/app/features/workflow/tests/costOptimizer/fr9-experiment-history-api-client.test.ts` | experiment history API path와 baseline/date/creator/status/model/applied/schema/downstream filter query 계약 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr9-experiment-history-api-client.test.ts` | 통과 |
| FR-009 | Gateway/service | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | compare response usage/diff, 비용 계산 불가 상태, `cost_optimizer_compare` trigger context, comparison_id experiment/candidate 저장, candidate id context 전달, raw candidate prompt 저장 방지, RAG summary redaction/size cap, 실패 후보 저장, experiment/candidate history 조회 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-009 | Workflow runtime | `apps/workflow_engine/tests/nodes/test_llm_node_runtime.py` | Cost Optimizer candidate id를 LLM usage log 호출로 전달 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/workflow_engine/.venv/Scripts/python.exe -m pytest apps/workflow_engine/tests/nodes/test_llm_node_runtime.py` | 통과 |
| FR-009 | Shared service | `apps/shared/tests/services/test_cost_optimizer_retention.py` | trace metadata retention 기준 만료일 계산, expired experiment purge, dry run, limit validation | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/shared/tests/services/test_cost_optimizer_retention.py` | 통과 |
| FR-010 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx`, `apps/client/app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | builder 미만 진입 액션 disabled, availability 기반 차단, 직접 URL 진입 시 draft 로드 차단 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx app/features/workflow/tests/costOptimizer/fr6-playground-mode-switch.test.tsx` | 통과 |
| FR-010 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | availability, baseline latest/list, experiment history, compare, apply가 builder/write 권한 경계를 사용하고 모델/Knowledge 후보 사용 가능성을 검증 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |

## FR-001 LLM 노드 단위 A/B 테스트 진입

### Component Tests

- LLM 노드 상세 화면에는 `A/B 테스트하기` 액션이 표시된다.
- `A/B 테스트` 액션은 LLM 노드 상세 패널의 상단 헤더 우측 보조 액션 영역에 표시된다.
- LLM 노드가 아닌 노드 상세 화면에는 `A/B 테스트하기` 액션이 표시되지 않는다.
- builder 이상 권한이 없는 사용자는 액션이 disabled 상태로 보이고 권한 부족 안내를 확인할 수 있다.
- baseline 실행 로그가 없으면 사용자는 `비교할 실행 로그가 없습니다. 먼저 테스트 실행을 완료해 주세요.` 안내를 확인할 수 있다.
- 저장되지 않은 draft가 있으면 사용자는 저장 후 비교를 시작해야 한다는 안내를 확인할 수 있다.

### API Tests

- `GET /cost-optimizer/availability`는 target node가 `llmNode`이면 `available=true`를 반환한다.
- target node가 `llmNode`가 아니면 `available=false` 또는 `cost_optimizer.not_llm_node` 오류를 반환한다.
- 존재하지 않는 node id는 scope 밖 resource와 구분되지 않도록 `404 resource.not_found`로 처리한다.

### Scenario Tests

- 사용자가 LLM 노드에서 `A/B 테스트하기`를 누르면 baseline 선택 화면으로 이동한다.
- 사용자가 일반 노드, webhook 노드, variable extraction 노드를 선택하면 Cost Optimizer 흐름이 시작되지 않는다.
- 사용자가 baseline 선택 전에는 A/B compare workspace로 바로 진입하지 않는다.

## FR-002 A Baseline 실행 로그 선택

### Component Tests

- baseline 선택 화면은 `최신 실행 로그로 비교하기`와 `이전 실행 로그 선택해서 비교하기`를 제공한다.
- baseline 선택 화면은 최신 비교 가능 baseline을 미리 조회하고 실행 시각, 모델, 토큰, 비용, 실행 시간, 입력 preview, 출력 preview를 표시한다.
- `input_available=true`, `output_available=true`, `usage_available=true`를 모두 만족하는 최신 성공 실행 로그가 없으면 최신 선택 CTA는 사용할 수 없고 로그 없음 안내가 표시된다.
- 이전 실행 로그 picker는 실행 시각, 상태, 모델, 비용, 토큰, 실행 시간, 입력 preview, 출력 preview, trace 존재 여부, downstream 상태를 표시한다.
- 이전 실행 로그 picker는 성공한 LLM node run만 표시하고 실패한 node run은 표시하지 않는다.
- 이전 실행 로그 picker는 output preview 또는 usage summary가 없는 node run을 표시하지 않는다.
- 이전 실행 로그 picker는 input 복원 불가 baseline row도 목록에 표시하되 `비교 불가` 상태로 표시한다.
- picker 검색은 입력/출력 preview 기준으로 동작한다.
- picker 필터는 모델, 날짜 범위, 비교 가능 여부를 지원한다.
- picker 정렬은 최신순, 비용 높은순, 비용 낮은순, 토큰 높은순, 실행 시간 긴순을 지원한다.

### API Tests

- `GET /baselines/latest`는 target LLM node의 성공 로그 중 `input_available=true`, `output_available=true`, `usage_available=true`를 모두 만족하는 가장 최근 로그를 반환한다.
- `GET /baselines/latest`는 실패한 node run을 baseline 후보로 반환하지 않는다.
- `GET /baselines/latest`는 output preview 또는 usage summary가 없는 node run을 baseline 후보로 반환하지 않는다.
- `GET /baselines`는 pagination metadata와 baseline row 목록을 반환한다.
- `GET /baselines`의 `q`, `model`, `date_from`, `date_to`, `sort`, `compare_available` query가 API 계약대로 적용된다.
- `GET /baselines`는 실패한 node run을 목록에 포함하지 않는다.
- `GET /baselines`는 output preview 또는 usage summary가 없는 node run을 목록에 포함하지 않는다.
- baseline query는 `workflow_node_runs.outputs`만으로 DB boundary에서 후보를 제외하지 않는다. trace payload에 redaction-safe output이 있으면 row 생성 단계에서 output availability를 판정한다.
- `GET /baselines`는 `workflow_node_runs.id`를 `baseline_id`로 반환한다.
- input을 복원할 수 없는 baseline row는 `input_available=false`, `compare_available=false`, `unavailable_reason=input_payload_unavailable`을 반환한다.
- baseline row는 credential 원문, API key, encrypted config를 포함하지 않는다.
- baseline row의 `llm_usage_logs.latency_ms`가 0 또는 누락된 경우 `workflow_node_runs.duration`을 ms로 환산해 실행 시간으로 반환한다.

### Scenario Tests

- 사용자가 최신 실행 로그를 선택하면 가장 최근 비교 가능 baseline이 자동으로 고정되고 A/B compare workspace로 이동한다.
- 사용자가 이전 로그 picker에서 특정 row를 선택하면 해당 로그가 A baseline으로 고정된다.
- 사용자가 `비교 불가` baseline row를 선택하면 A/B compare workspace로 이동하지 않고 input 복원 불가 안내를 본다.

## FR-003 B 후보 설정 입력

### Component Tests

- B candidate 영역은 현재 LLM 노드 설정 복사본으로 초기화된다.
- B candidate 영역은 `후보 옵션` 같은 중복 제목 대신 `테스트명` 입력을 제공한다.
- 원본 LLM 노드 상세 설정은 task type 선택을 제공하고, 선택 값은 node data에 저장된다.
- B candidate 영역은 모델, fallback 모델, task type, system prompt, user prompt, assistant prompt, `max_tokens`, `temperature`, 출력 형식을 편집할 수 있다.
- 일반 LLM 노드 상세 화면과 B candidate 영역은 같은 workflow LLM 모델 필터를 사용한다.
- 모델 후보 목록은 alias 계열 모델을 노출하고 날짜 suffix 모델은 숨긴다.
- 모델 후보 목록은 embedding, image, audio, realtime, moderation, tts, whisper, transcribe, sora, search-only 계열을 숨긴다.
- B candidate의 task type은 Cost Optimizer local draft에서 원본 LLM node data 변환까지 보존된다.
- B candidate prompt 입력은 upstream output 변수 삽입을 지원한다.
- prompt 변수 삽입은 candidate `referenced_variables`를 함께 갱신하고 compare/apply request에 포함한다.
- 출력 형식은 text와 JSON을 선택할 수 있다.
- 출력 형식이 JSON이면 JSON schema 편집 영역이 활성화된다.
- 출력 형식이 text이면 JSON schema 편집 영역은 비활성화되거나 숨겨진다.
- JSON schema는 key-type 행 추가 UI로 필드명, 타입, 필수 여부를 편집할 수 있다.
- JSON schema type 후보는 `string`, `number`, `boolean`, `object`, `array`다.
- 1차 UI는 nested field editor를 제공하지 않고 flat key-type row만 편집한다.
- B candidate 영역은 여러 Knowledge Base, `topK`, `scoreThreshold`를 편집할 수 있다.
- B candidate 영역은 중복 근거 제거, 참조 문서 길이 제한, 검색 문서 압축, 답변 근거 확인을 편집할 수 있다.
- 새 LLM 노드는 중복 근거 제거, 참조 문서 길이 제한, 검색 문서 압축, 답변 근거 확인 기본값을 명시적으로 가진다.
- 참조 문서 길이 제한은 Knowledge/RAG context에만 적용되며 system/user/assistant prompt를 임의로 자르지 않는다.
- 참조 문서 길이 제한이 비어 있으면 compare request는 `retrieved_context_max_chars: null`을 보낼 수 있고, API는 이를 제한 없음으로 허용한다.
- 중복 근거 제거가 켜지면 동일한 retrieved chunk content는 한 번만 LLM context에 들어간다.
- 검색 문서 압축이 켜지면 검색 query와 관련된 문장을 우선 남겨 Knowledge/RAG context를 줄인다.
- 답변 근거 확인이 켜지면 LLM 응답과 Knowledge/RAG context의 기본 overlap 결과를 safe metadata로 남긴다.
- B candidate 영역은 고급 파라미터 섹션에서 `top_p`, `presence_penalty`, `frequency_penalty`, `stop`을 편집할 수 있다.
- 고급 파라미터 validation은 기존 LLM node 고급 설정 범위를 따른다.
- 필수 후보 설정이 누락되면 `B 실행` 버튼이 disabled 상태가 되거나 validation message를 표시한다.
- 사용할 수 없는 credential/model 후보는 선택할 수 없거나 실패 후보로 명확히 표시된다.

### API Tests

- `POST /compare`는 `candidate.model_id`, task type, prompt, parameters, output_format, knowledge를 request로 받는다.
- `POST /compare`는 `top_p`, `presence_penalty`, `frequency_penalty`, `stop`을 후보 파라미터로 받을 수 있다.
- 잘못된 task type, `max_tokens`, `temperature`, 고급 파라미터, output_format schema, `properties`에 없는 field를 `required`로 지정한 schema, 세 prompt를 모두 명시적으로 비운 후보는 `400 cost_optimizer.invalid_candidate`를 반환한다.
- `candidate.knowledge.retrieved_context_max_chars=null`은 제한 없음으로 허용하고, `0` 이하 값은 `400 cost_optimizer.invalid_candidate`를 반환한다.
- 사용할 수 없는 Knowledge Base 또는 접근 권한이 없는 Knowledge Base는 `422 cost_optimizer.knowledge_unavailable`을 반환한다.
- 현재 Gateway 테스트는 `invalid_candidate`, `knowledge_unavailable`, `model_unavailable`을 검증한다.
- 사용할 수 없는 model 또는 credential은 `422 cost_optimizer.model_unavailable`을 반환한다.
- schema 검증에 실패한 B 후보는 LLM 비용/토큰/시간을 반환하되 `schema_failed` 상태와 `schema_validation.errors`를 포함한다.
- schema 검증에 실패한 B 후보를 apply하려고 하면 `400 cost_optimizer.schema_failed_candidate`를 반환한다.
- 비교 실행은 `comparison_id`로 식별 가능한 `cost_optimizer_experiments` 기록과 `cost_optimizer_candidates` 후보 기록으로 저장된다.
- 현재 Gateway 테스트는 compare 응답의 `schema_failed` 상태, 사용량 보존, comparison_id 저장, schema 실패 후보 apply 차단을 검증한다.

### Scenario Tests

- 사용자가 모델만 바꾸고 B를 실행하면 A baseline과 같은 입력으로 후보 실행 결과가 생성된다.
- 사용자가 prompt와 parameter를 함께 바꿔도 compare request는 하나의 B 후보 설정으로 전송된다.
- 사용자가 Knowledge Base 또는 검색 설정을 바꾸고 B를 실행하면 baseline retrieval을 재사용하지 않고 B 후보 설정 기준으로 retrieval을 새로 수행한다.
- 비교 리포트는 A baseline retrieval summary와 B candidate retrieval summary를 구분해 표시한다.
- 사용자가 JSON schema를 지정하고 B를 실행하면 후보 출력은 schema 검증 결과와 함께 표시된다.
- schema 검증에 실패한 후보는 비용과 출력 preview를 확인할 수 있지만 `현재 노드에 적용`은 사용할 수 없다.
- 사용자가 B 후보를 적용하면 모델, prompt, parameters, output_format, schema, Knowledge/RAG 설정이 일괄 적용된다.

## FR-004 동일 입력 기준 비교

### Component Tests

- A baseline input은 읽기 전용 잠금 상태로 표시된다.
- B candidate 영역은 현재 입력 필드를 직접 수정하지 않고 A baseline input을 사용한다는 안내를 표시한다.
- baseline을 바꾸면 B 실행 전 비교 입력 기준도 함께 바뀐다.

### API Tests

- `POST /compare`는 request의 임의 입력값이 아니라 `baseline_id`에 연결된 target node input을 사용한다.
- baseline input을 복원할 수 없으면 `400 cost_optimizer.baseline_input_unavailable`을 반환한다.
- baseline이 다른 workflow나 node에 속하면 `404 resource.not_found`를 반환한다.

### Scenario Tests

- 사용자가 현재 workflow draft의 앞단 노드 값을 수정해도 이미 선택된 baseline input은 바뀌지 않는다.
- 동일 baseline으로 모델만 바꿔 여러 번 B를 실행하면 입력 preview는 동일하게 유지된다.

## FR-005 하이브리드 비교 실행

### Component Tests

- 화면은 A baseline이 과거 로그이고 B candidate만 새로 실행된다는 점을 표시한다.
- B 실행 중에는 B 영역만 running 상태가 되고, 실행 버튼은 spinner와 `B 실행 중` 텍스트를 함께 표시한다.
- A baseline 영역에는 재실행 spinner나 새 run id가 표시되지 않는다.

### API Tests

- `POST /compare`는 A baseline을 재실행하지 않는다.
- `POST /compare`는 B candidate 실행 결과와 A baseline summary를 함께 반환한다.
- B candidate 실행으로 생성된 run/trace는 `candidate_workflow_run_id`와 `cost_optimizer_candidate_id`로 compare 실행임을 구분할 수 있어야 하며, baseline 후보 조회에는 다시 포함되지 않아야 한다.

### Scenario Tests

- A baseline 로그의 비용/토큰/latency는 B 실행 전후로 변하지 않는다.
- B 실행 실패 시에도 A baseline 정보는 유지되고 실패 원인은 B candidate에만 표시된다.

## FR-006 A/B 비교 화면과 Inspector

### Component Tests

- A/B compare workspace의 실험 설정 mode는 A 실행 시점 옵션, B candidate, 기준 실행 정보 3영역으로 구성된다.
- A/B compare workspace는 `실험 설정`과 `결과 분석` mode switch를 제공한다.
- baseline 선택 전에는 B candidate, 기준 실행 정보, mode switch를 표시하지 않는다.
- baseline 선택 전 첫 화면은 A/B 테스트 기준 선택에 집중한다.
- baseline 선택 단계의 `닫기`와 workspace의 `워크플로우로 돌아가기`는 `/modules/{workflowId}?node={nodeId}`로 이동해 target LLM node 상세 화면을 다시 연다.
- baseline 선택 후 기본 mode는 `실험 설정`이다.
- 사용자는 `결과 분석` mode로 전환할 수 있다.
- B 실행 결과가 없으면 `결과 분석` mode는 B 실행 후 결과 분석이 표시된다는 empty state를 보여준다.
- A/B compare workspace는 특정 workflow와 특정 LLM node의 context를 상단 context bar에 표시한다.
- context bar는 workflow 이름, target LLM node 이름, baseline 실행 시각, 같은 입력 기준 badge, downstream 상태 badge를 표시한다.
- A 실행 시점 옵션 영역은 읽기 전용이고 baseline 실행 당시의 기본 설정, 고급 설정, 지식 베이스 설정을 표시한다.
- 기준 실행 정보 영역은 baseline 모델, 비용, 토큰, latency, 기준 입력 preview, 기준 출력 preview를 표시한다.
- 기준 입력/출력 preview의 긴 값과 여러 JSON field는 `...` 또는 row 개수 제한으로 임의 truncation하지 않고 전체 값을 표시한다.
- B candidate 영역은 `테스트명` 입력을 제공하고 설정 패널의 중복 제목은 표시하지 않는다.
- B candidate 영역은 후보 설정, 실행 상태, 출력 preview, 토큰, 비용, latency, error를 표시한다.
- B 후보 실행 후에도 사용자는 같은 workspace 안에서 B 후보 설정을 수정하고 같은 baseline으로 다시 실행할 수 있다.
- B 후보 설정이 마지막 실행 이후 변경되면 기존 B 결과는 stale 상태로 표시된다.
- B 후보의 RAG 비용 최적화 옵션이 마지막 실행 이후 변경되면 기존 B 결과는 stale 상태로 표시된다.
- 결과 분석 mode 상단에는 접기 가능한 `이전 실험 이력` 패널이 표시된다.
- 이전 실험 이력 패널은 시작일, 종료일, 실행자, 적용 여부, 후보 상태, 모델, Schema 상태, Downstream 상태 필터를 제공한다.
- 이전 실험 이력은 card list가 아니라 실행 시각, 테스트명, 모델, 비용, 토큰, 시간, Schema, Downstream을 열로 갖는 dense table로 표시된다.
- 이전 실험 이력 table body는 내부 스크롤을 사용하고 결과 분석 본문을 과도하게 아래로 밀지 않는다.
- B 후보 실행 후 결과 분석 mode로 이동하면 방금 실행한 후보가 이전 실험 이력 table에서 자동 선택된다.
- 이전 실험 이력에서 다른 row를 선택하면 아래 결과 분석 본문은 해당 후보 기준으로 갱신된다.
- 이전 실험 이력 조회에 실패해도 이미 보유한 compare result가 있으면 결과 분석 본문은 유지된다.
- 결과 분석 mode는 상단에 `적용 후보로 적합`, `주의 필요`, `적용 비추천` 중 하나의 판단 요약을 표시한다.
- 판단 요약은 비용 변화율, token 변화율, latency 변화, B 실행 상태, schema 검증 상태, downstream 호환성 상태를 근거로 표시한다.
- 결과 분석 mode는 비용, prompt tokens, completion tokens, total tokens, latency, 실행 상태, schema, downstream을 A/B/변화값 형태로 비교한다.
- 결과 분석 mode는 A 출력과 B 출력을 나란히 표시하고 긴 값을 임의 truncation하지 않는다.
- JSON 출력과 schema가 있으면 결과 분석 mode는 필수 field 충족 여부, 누락 field, type mismatch를 표시한다.
- 결과 분석 mode의 Inspector는 `설정 차이`, `근거/Trace`, `후속 노드 영향` 탭을 제공한다.
- `설정 차이` 탭은 모델, fallback 모델, task type, prompt, parameter, 출력 형식, JSON schema, Knowledge/RAG 설정 차이를 표시한다.
- `근거/Trace` 탭은 A/B usage trace와 A/B retrieval summary를 구분해 표시한다.
- `후속 노드 영향` 탭은 downstream 호환성 상태, 검사 노드, 계약 검증 warning, side-effect node 자동 실행 제외 안내를 표시한다.

### API Tests

- `POST /compare` response는 `baseline`, `candidate`, `diff`, `downstream_compatibility`를 포함한다.
- `baseline.trace`와 `candidate.trace`는 safe summary만 포함한다.
- candidate 실행 실패 시 response는 부분 결과와 `error_message`를 구분해 반환한다.
- candidate task 제출 또는 대기 중 예외가 발생해도 response는 `candidate.status=failed`와 `error_message`를 반환하고 experiment/candidate row를 failed 상태로 저장한다.

### Scenario Tests

- B 실행 성공 후 사용자는 A와 B의 출력, 비용, 토큰, latency를 한 화면에서 비교하고 적용 판단 요약을 확인할 수 있다.
- 비용은 줄었지만 downstream warning이 있으면 결과 분석 화면은 `주의 필요`로 표시한다.
- B 실행 실패, schema 실패, downstream incompatible 중 하나가 있으면 결과 분석 화면은 `적용 비추천` 또는 그에 준하는 강한 경고를 표시한다.
- B 실행 실패 후에도 사용자는 A baseline과 실패 사유를 볼 수 있다.
- 사용자가 B 실행 결과를 본 뒤 prompt 또는 model을 수정하면 workspace를 닫지 않고 같은 baseline으로 재실행할 수 있다.
- stale 상태의 B 결과는 참고용으로 남지만 현재 후보 설정의 결과가 아니라는 안내를 표시한다.

## FR-007 Downstream 호환성 검증

### Component Tests

- downstream 상태는 `검증 가능`, `주의 필요`, `검증 불가` 중 하나의 명확한 라벨로 표시된다.
- 상태는 색상만으로 구분하지 않고 텍스트 설명을 함께 제공한다.
- `주의 필요` 또는 `검증 불가` 상태에서는 후보 적용 전 추가 확인이 필요하다는 안내를 표시한다.
- side-effect node는 자동으로 downstream 실행하지 않는다는 안내를 표시한다. UI 문구는 `외부 전송이나 쓰기 작업이 있는 downstream 노드는 자동 실행하지 않습니다.`를 포함한다.

### API Tests

- `GET /baselines/latest`는 compare 가능한 baseline을 반환할 때 downstream snapshot을 생성하고, response에는 snapshot 원문이 아니라 `downstream_compatibility` summary만 반환한다.
- `GET /baselines`는 목록 row 생성 또는 baseline 선택 시점에 downstream snapshot을 만들 수 있어야 하며, snapshot 생성 실패 시 compare 가능 여부와 unavailable reason을 명확히 반환한다.
- baseline downstream과 current downstream이 같으면 `compatible`을 반환한다.
- downstream 구조가 일부 달라졌지만 첫 consumer 계약 검증이 가능하면 `warning`을 반환한다.
- target LLM node의 출력 소비자가 사라졌거나 계약 검증이 불가능하면 `incompatible` 또는 `unknown`을 반환한다.
- `POST /compare`는 현재 graph만 보지 않고 baseline downstream snapshot과 B candidate output을 기준으로 `contract_check`를 수행한다.
- current downstream topology가 같더라도 B candidate output이 직접 소비 노드의 필수 selector/path를 만족하지 못하면 `incompatible`과 `contract_check.status=failed`를 반환한다.
- baseline downstream snapshot이 없는 legacy/retention row는 `unknown`과 `contract_check.status=skipped`, `baseline_downstream_snapshot_unavailable` warning을 반환한다.
- `variableExtractionNode`의 `source_selector`가 target LLM node를 가리키면 `mappings[].json_path`가 B candidate output JSON에 존재하는지 검사한다.
- `conditionNode`, `answerNode`, `slackPostNode`는 target LLM node를 참조하는 selector key가 B candidate output에 존재하는지 검사한다.
- `PATCH /apply`는 downstream warning 확인 없이 적용하는 요청을 `400 cost_optimizer.downstream_ack_required`로 거부한다.

### Scenario Tests

- baseline 이후 현재 workflow에서 다음 노드 입력 계약이 바뀐 경우 UI는 `주의 필요`를 표시한다.
- downstream이 크게 바뀐 경우 UI는 `검증 불가`를 표시하고 `workflow 전체 테스트 실행으로 downstream 성공 여부를 별도 확인하세요.` fallback 안내를 제공한다.

## FR-008 B 후보 적용

### Component Tests

- B 후보가 성공 상태일 때만 `현재 노드에 적용` 액션이 활성화된다.
- 적용 전 확인 모달은 변경되는 모델, prompt, 고급 parameter(`max_tokens`, `temperature`, `top_p`, penalty, `stop`), 출력 형식, JSON schema, Knowledge/RAG 설정, downstream 상태를 보여준다.
- 적용 성공 후 현재 LLM node draft는 B 후보 설정으로 갱신된다.
- 적용 후 기존 workflow 저장/테스트 실행 흐름은 유지된다.

### API Tests

- `PATCH /apply`는 B 후보 설정을 current draft target LLM node에 적용한다.
- downstream warning 상태에서 `acknowledge_downstream_warning=false`이면 적용을 거부한다.
- 적용 response는 `updated_draft_revision`을 반환한다.
- `PATCH /apply`는 request의 `candidate_settings`와 일치하는 저장 후보를 `is_applied=true`로 표시하고 `applied_at`, `applied_by`를 기록한다. 같은 experiment의 다른 후보는 적용 표시를 해제한다.
- `PATCH /apply`는 `comparison_id`가 없거나, `comparison_id` 안에서 request의 `candidate_settings`와 일치하는 저장 후보가 없으면 `400 cost_optimizer.candidate_not_found`로 적용을 거부한다.
- draft revision 충돌 감지는 현재 request 계약에 expected draft revision 필드가 없어 후속 보강 범위다.

### Scenario Tests

- 사용자가 B 후보 적용 후 노드 상세 화면으로 돌아오면 변경된 모델과 prompt가 표시된다.
- 적용 후 사용자가 workflow 저장을 수행하면 기존 저장 API 흐름을 그대로 사용한다.

## FR-009 비용 기록과 표시

### Component Tests

- A baseline과 B candidate는 각각 비용, prompt tokens, completion tokens, total tokens, latency를 표시한다.
- 비교 실행 비용은 일반 workflow 실행 비용과 분리되지 않고 추적 대상이라는 안내를 제공한다.
- 가격 정보가 없는 모델은 비용 비교 불가 상태로 표시한다.
- 결과 분석 화면은 이전 experiment 이력을 기간, 실행자, 후보 상태, 모델, 적용 여부, schema 상태, downstream 상태로 필터링할 수 있다.

### API Tests

- B candidate 실행에서 발생한 LLM call은 `llm_usage_logs`에 기록된다.
- usage log에는 workflow id, node id, model, prompt tokens, completion tokens, total tokens, cost, latency, status가 포함된다.
- Cost Optimizer 비교 실행에서 생성되는 usage log는 `cost_optimizer_candidate_id`로 B candidate row를 직접 참조한다.
- `GET /cost-optimizer/experiments`는 같은 workflow/node 기준으로 저장된 experiment와 candidate summary를 조회한다.
- Cost Optimizer experiment/candidate summary는 trace metadata retention 기준으로 만료일을 계산하고, 만료된 experiment를 정리하면 candidate도 함께 정리된다.
- RAG safe summary는 raw chunk content/source metadata/document filename 계열 값을 제거하고, list 값은 20개, string 값은 200자로 제한한다.
- 비용 계산이 불가능한 모델은 response에 비용 불가 상태를 명확히 반환한다.
- usage response에는 credential 원문, API key, encrypted config가 포함되지 않는다.
- 저장된 candidate summary에는 raw system/user/assistant prompt가 포함되지 않고 redacted summary와 apply 검증용 fingerprint만 남는다.

### Scenario Tests

- 사용자가 B 후보를 여러 번 실행하면 각 실행 비용이 누락 없이 기록된다.
- B 후보 실행 실패 시에도 실패 상태와 측정 가능한 latency/usage가 있으면 기록된다.

## FR-010 권한

### Component Tests

- builder 이상 권한 사용자는 A/B 테스트 진입, B 후보 실행, 후보 적용을 사용할 수 있다.
- viewer/operator 또는 builder 미만 사용자는 Cost Optimizer 액션을 사용할 수 없다.
- 권한 부족 상태는 숨김 또는 disabled 처리와 함께 사유를 표시한다.

### API Tests

- builder 이상 권한이 없는 사용자의 availability, baseline 조회, compare, apply 요청은 `403 permission.denied`를 반환한다.
- 프론트가 버튼을 숨기더라도 API는 서버에서 builder 이상 권한을 다시 검증한다.
- 다른 organization의 workflow/node/baseline 접근은 `404 resource.not_found`로 숨김 처리한다.
- 사용할 수 없는 credential/model 후보는 실행하지 않거나 실패 후보로 반환한다.

### Scenario Tests

- builder 사용자는 baseline 선택부터 B 후보 적용까지 전체 흐름을 완료할 수 있다.
- member/viewer 사용자는 직접 URL 접근을 시도해도 Cost Optimizer API를 사용할 수 없다.

## Regression Tests

- 기존 workflow 생성, 편집, 저장, 테스트 실행, 배포 흐름은 Cost Optimizer 문서 계약 추가 이후에도 변경되지 않는다.
- Cost Optimizer response에는 secret value, credential 원문, API key, token, encrypted config가 노출되지 않는다.
- Cost Optimizer experiment/candidate 저장 summary에는 raw prompt, credential 원문, API key, token, encrypted config가 남지 않는다.
- baseline log picker와 compare response는 권한 없는 RAG source의 raw content, raw source metadata, 숨겨진 문서명을 노출하지 않는다.
