# Cost Optimizer Test Cases

Status: Draft
Verified Against: TBD

## Purpose

이 문서는 `requirements.md`의 FR-001부터 FR-010까지를 테스트 관점에서 검증 가능한 형태로 정리한다.

테스트는 LLM 노드 단위 Cost Optimizer 흐름을 기준으로 한다. workflow 전체 A/B 테스트, 자동 모델 라우팅, 최적화 에이전트는 이 문서의 1차 검증 범위가 아니다.

## Test Matrix

| FR | Component Spec | API Spec | Test Focus | 테스트 코드 상태 | 테스트 통과 여부 |
| --- | --- | --- | --- | --- | --- |
| FR-001 | LLM node detail action | GET availability | LLM 노드에서만 A/B 테스트 진입 가능 | 작성 완료 | 통과 |
| FR-002 | Baseline selection, baseline log picker | GET latest baseline, GET baselines | 최신/이전 baseline 로그 선택 | 작성 전 | 미실행 |
| FR-003 | Candidate editor | POST compare request candidate schema | B 후보 설정 입력과 검증 | 작성 전 | 미실행 |
| FR-004 | Baseline input lock display | baseline input 고정 | B 실행 입력이 A baseline 입력으로 고정됨 | 작성 전 | 미실행 |
| FR-005 | Hybrid compare flow | POST compare | A는 재실행하지 않고 B만 실행 | 작성 전 | 미실행 |
| FR-006 | A/B compare workspace, Inspector | compare response trace/diff | A/B 결과와 Inspector 데이터 표시 | 작성 전 | 미실행 |
| FR-007 | Downstream compatibility badge | downstream compatibility fragment | downstream 호환성 3상태 표시와 차단/경고 | 작성 전 | 미실행 |
| FR-008 | Apply candidate action | PATCH apply | B 후보 설정을 current draft에 적용 | 작성 전 | 미실행 |
| FR-009 | Cost/usage display | llm usage logging | 비교 실행 비용/토큰/latency 기록과 표시 | 작성 전 | 미실행 |
| FR-010 | Permission-gated UI | builder permission enforcement | builder 이상 권한 강제 | 작성 전 | 미실행 |

## Test Implementation Tracking

테스트 파일명은 구현 시점에 실제 컴포넌트/API 파일명에 맞춰 조정할 수 있다. 단, FR과 테스트 파일의 역참조는 유지해야 한다.

| FR | 테스트 레이어 | 예상 테스트 파일 | 검증 대상 | 작성 상태 | 실행 명령 | 통과 여부 |
| --- | --- | --- | --- | --- | --- | --- |
| FR-001 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx` | LLM 노드 전용 진입 액션, non-LLM 차단, availability 기반 비활성화 | 작성 완료 | `cd apps/client && npm run test -- --run app/features/workflow/tests/costOptimizer/fr1-entry-action.test.tsx` | 통과 |
| FR-001 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | availability, not-LLM, not-found, builder 권한 강제 | 작성 완료 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 통과 |
| FR-002 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerBaselinePicker.test.tsx` | 최신/이전 baseline 선택, 필터/정렬 UI | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-002 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | latest/list baseline query | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-003 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerCandidateEditor.test.tsx` | 후보 설정 입력/validation | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-003 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | candidate schema validation, unavailable model | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-004 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerBaselineLock.test.tsx` | baseline input lock 표시 | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-004 | Gateway service/API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | baseline input restore, wrong baseline scope | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-005 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerHybridCompare.test.tsx` | A 고정, B running 상태 | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-005 | Gateway service/API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | A 미재실행, B만 실행 | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-006 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerWorkspace.test.tsx` | 3패널, Inspector 탭, diff 표시 | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-006 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | compare response shape, safe trace | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-007 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerDownstream.test.tsx` | downstream 3상태 badge/warning | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-007 | Gateway service/API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | compatible/warning/incompatible 판정 | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-008 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerApply.test.tsx` | 적용 모달, draft 갱신 UI | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-008 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | apply, draft conflict, downstream ack | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-009 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerUsage.test.tsx` | 비용/토큰/latency 표시 | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-009 | Gateway/service | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | `llm_usage_logs` 기록, secret redaction | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |
| FR-010 | Frontend component | `apps/client/app/features/workflow/tests/costOptimizerPermission.test.tsx` | builder 미만 UI 차단 | 작성 전 | `cd apps/client && npm run test` | 미실행 |
| FR-010 | Gateway API | `apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | builder 권한 강제, scope 밖 404 | 작성 전 | `PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/Scripts/python.exe -m pytest apps/gateway/tests/api/cost_optimizer/test_cost_optimizer_api.py` | 미실행 |

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
- 최신 실행 로그가 없으면 최신 선택 CTA는 사용할 수 없고 로그 없음 안내가 표시된다.
- 이전 실행 로그 picker는 실행 시각, 상태, 모델, 비용, 토큰, 실행 시간, 입력 preview, 출력 preview, trace 존재 여부, downstream 상태를 표시한다.
- 이전 실행 로그 picker는 성공한 LLM node run만 표시하고 실패한 node run은 표시하지 않는다.
- 이전 실행 로그 picker는 input 복원 불가 baseline row도 목록에 표시하되 `비교 불가` 상태로 표시한다.
- picker 검색은 입력/출력 preview 기준으로 동작한다.
- picker 필터는 모델, 날짜 범위, 비교 가능 여부를 지원한다.
- picker 정렬은 최신순, 비용 높은순, 비용 낮은순, 토큰 높은순, 실행 시간 긴순을 지원한다.

### API Tests

- `GET /baselines/latest`는 target LLM node의 가장 최근 성공 로그를 반환한다.
- `GET /baselines/latest`는 실패한 node run을 baseline 후보로 반환하지 않는다.
- `GET /baselines`는 pagination metadata와 baseline row 목록을 반환한다.
- `GET /baselines`의 `q`, `model`, `date_from`, `date_to`, `sort`, `compare_available` query가 API 계약대로 적용된다.
- `GET /baselines`는 실패한 node run을 목록에 포함하지 않는다.
- `GET /baselines`는 `workflow_node_runs.id`를 `baseline_id`로 반환한다.
- input을 복원할 수 없는 baseline row는 `input_available=false`, `compare_available=false`, `unavailable_reason=input_payload_unavailable`을 반환한다.
- baseline row는 credential 원문, API key, encrypted config를 포함하지 않는다.

### Scenario Tests

- 사용자가 최신 실행 로그를 선택하면 A baseline이 자동으로 고정되고 A/B compare workspace로 이동한다.
- 사용자가 이전 로그 picker에서 특정 row를 선택하면 해당 로그가 A baseline으로 고정된다.
- 사용자가 `비교 불가` baseline row를 선택하면 A/B compare workspace로 이동하지 않고 input 복원 불가 안내를 본다.

## FR-003 B 후보 설정 입력

### Component Tests

- B candidate 영역은 모델, system prompt, user prompt, assistant prompt, `max_tokens`, `temperature`, 출력 형식을 편집할 수 있다.
- 출력 형식은 text와 JSON을 선택할 수 있다.
- 필수 후보 설정이 누락되면 `B 실행` 버튼이 disabled 상태가 되거나 validation message를 표시한다.
- 사용할 수 없는 credential/model 후보는 선택할 수 없거나 실패 후보로 명확히 표시된다.

### API Tests

- `POST /compare`는 `candidate_settings.model_id`, prompt, parameters, output_format을 request로 받는다.
- 잘못된 `max_tokens`, `temperature`, output_format schema는 `400 cost_optimizer.invalid_candidate`를 반환한다.
- 사용할 수 없는 model 또는 credential은 `422 cost_optimizer.model_unavailable`을 반환한다.

### Scenario Tests

- 사용자가 모델만 바꾸고 B를 실행하면 A baseline과 같은 입력으로 후보 실행 결과가 생성된다.
- 사용자가 prompt와 parameter를 함께 바꿔도 compare request는 하나의 B 후보 설정으로 전송된다.

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
- B 실행 중에는 B 영역만 running 상태가 되고 A baseline 영역은 변경되지 않는다.
- A baseline 영역에는 재실행 spinner나 새 run id가 표시되지 않는다.

### API Tests

- `POST /compare`는 A baseline을 재실행하지 않는다.
- `POST /compare`는 B candidate 실행 결과와 A baseline summary를 함께 반환한다.
- B candidate 실행으로 생성된 run/trace는 compare 실행으로 구분할 수 있어야 한다.

### Scenario Tests

- A baseline 로그의 비용/토큰/latency는 B 실행 전후로 변하지 않는다.
- B 실행 실패 시에도 A baseline 정보는 유지되고 실패 원인은 B candidate에만 표시된다.

## FR-006 A/B 비교 화면과 Inspector

### Component Tests

- A/B compare workspace는 A baseline, B candidate, Inspector 3영역으로 구성된다.
- A baseline 영역은 읽기 전용이고 baseline 실행 로그, 입력, 출력, 모델, 비용, 토큰, latency, trace 요약을 표시한다.
- B candidate 영역은 후보 설정, 실행 상태, 출력 preview, 토큰, 비용, latency, error를 표시한다.
- Inspector는 `A Trace`, `B Trace`, `Diff`, `Downstream`, `Settings` 탭을 제공한다.
- `B Trace` 탭은 B 실행 전에는 disabled 또는 empty state이고 B 실행 후 활성화된다.
- `Diff` 탭은 모델, prompt, parameter, 출력 형식, 비용, 토큰, latency 차이를 표시한다.

### API Tests

- `POST /compare` response는 `baseline`, `candidate`, `diff`, `downstream_compatibility`를 포함한다.
- `baseline.trace`와 `candidate.trace`는 safe summary만 포함한다.
- candidate 실행 실패 시 response는 부분 결과와 `error_message`를 구분해 반환한다.

### Scenario Tests

- B 실행 성공 후 사용자는 A와 B의 출력, 비용, 토큰, latency를 한 화면에서 비교할 수 있다.
- B 실행 실패 후에도 사용자는 A baseline과 실패 사유를 볼 수 있다.

## FR-007 Downstream 호환성 검증

### Component Tests

- downstream 상태는 `검증 가능`, `주의 필요`, `검증 불가` 중 하나의 명확한 라벨로 표시된다.
- 상태는 색상만으로 구분하지 않고 텍스트 설명을 함께 제공한다.
- `주의 필요` 또는 `검증 불가` 상태에서는 후보 적용 전 추가 확인이 필요하다는 안내를 표시한다.
- side-effect node는 자동으로 downstream 실행하지 않는다는 안내를 표시한다.

### API Tests

- baseline downstream과 current downstream이 같으면 `compatible`을 반환한다.
- downstream 구조가 일부 달라졌지만 첫 consumer 계약 검증이 가능하면 `warning`을 반환한다.
- target LLM node의 출력 소비자가 사라졌거나 계약 검증이 불가능하면 `incompatible` 또는 `unknown`을 반환한다.
- `PATCH /apply`는 downstream warning 확인 없이 적용하는 요청을 `400 cost_optimizer.downstream_ack_required`로 거부할 수 있다.

### Scenario Tests

- baseline 이후 현재 workflow에서 다음 노드 입력 계약이 바뀐 경우 UI는 `주의 필요`를 표시한다.
- downstream이 크게 바뀐 경우 UI는 `검증 불가`를 표시하고 workflow 전체 테스트 실행을 안내한다.

## FR-008 B 후보 적용

### Component Tests

- B 후보가 성공 상태일 때만 `현재 노드에 적용` 액션이 활성화된다.
- 적용 전 확인 모달은 변경되는 모델, prompt, parameter, 출력 형식, downstream 상태를 보여준다.
- 적용 성공 후 현재 LLM node draft는 B 후보 설정으로 갱신된다.
- 적용 후 기존 workflow 저장/테스트 실행 흐름은 유지된다.

### API Tests

- `PATCH /apply`는 B 후보 설정을 current draft target LLM node에 적용한다.
- draft revision이 충돌하면 `409 cost_optimizer.draft_conflict`를 반환한다.
- downstream warning 상태에서 `acknowledge_downstream_warning=false`이면 적용을 거부할 수 있다.
- 적용 response는 `updated_draft_revision`을 반환한다.

### Scenario Tests

- 사용자가 B 후보 적용 후 노드 상세 화면으로 돌아오면 변경된 모델과 prompt가 표시된다.
- 적용 후 사용자가 workflow 저장을 수행하면 기존 저장 API 흐름을 그대로 사용한다.

## FR-009 비용 기록과 표시

### Component Tests

- A baseline과 B candidate는 각각 비용, prompt tokens, completion tokens, total tokens, latency를 표시한다.
- 비교 실행 비용은 일반 workflow 실행 비용과 분리되지 않고 추적 대상이라는 안내를 제공한다.
- 가격 정보가 없는 모델은 비용 비교 불가 상태로 표시한다.

### API Tests

- B candidate 실행에서 발생한 LLM call은 `llm_usage_logs`에 기록된다.
- usage log에는 workflow id, node id, model, prompt tokens, completion tokens, total tokens, cost, latency, status가 포함된다.
- 비용 계산이 불가능한 모델은 response에 비용 불가 상태를 명확히 반환한다.
- usage response에는 credential 원문, API key, encrypted config가 포함되지 않는다.

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
- baseline log picker와 compare response는 권한 없는 RAG source의 raw content나 숨겨진 문서명을 노출하지 않는다.
