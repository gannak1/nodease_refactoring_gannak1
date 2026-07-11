# Workflow Test Cases

Status: Draft

## Test File Mapping

- Top-aligned workflow ranks, boundary-centered BaseNode handles, Default/input alignment, and downward Condition branches: `apps/client/app/features/workflow/utils/nodeHandleLayout.test.ts`, `apps/client/app/features/workflow/utils/arrangeConditionNodes.test.ts`, `apps/shared/tests/test_workflow_layout.py`

- 실행 편의성: `apps/client/app/features/workflow/tests/execution-convenience.test.ts`
- 노드 조작 편의성: `apps/client/app/features/workflow/tests/node-panel-resize.test.ts`
- 워크플로우 조작 편의성: `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx`
- 노드 실행 기록 패널 추가: `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts`
- 공통 그래프 검증: `apps/client/app/features/workflow/tests/utils/validateWorkflowGraph.test.ts`
- 공통 catalog/Backend 연결 정책: `apps/shared/tests/test_workflow_node_catalog.py`, `apps/gateway/tests/services/test_agent_builder_service.py`
- 인증 배포 실행/RAG 경계: `apps/gateway/tests/services/test_chatbot_deployment_run.py`, `apps/gateway/tests/api/test_deployment_permissions.py`, `apps/client/app/features/app/tests/moduleRunNavigation.test.ts`, `apps/client/app/features/workflow/tests/deploymentRunResult.test.ts`
- 동시성 처리: TBD. 구현/API 경계 확정 후 `apps/client/app/features/workflow/tests/workflow-concurrency.test.ts` 또는 Gateway integration test로 분리한다.

`*.todo.test.ts`의 `it.todo` 항목은 아직 대응 구현 또는 API 계약이 없는 테스트 케이스다. 구현 시 같은 파일에서 실제 assertion 테스트로 전환한다.

Frontend 공통 그래프 검증은 catalog v2의 incoming/outgoing 금지 정책과 parity를 유지해야 한다. Start/Webhook/Schedule incoming, Answer outgoing, 잘못된 Condition source handle을 거부하고, Agent Builder apply/save도 같은 graph를 다시 거부하는지 검증한다.

## Spec Document Mapping

`Demo Test Priority` 표의 `영역` 컬럼은 아래 spec 문서 섹션과 대응된다. 테스트를 구현하거나 우선순위를 바꿀 때는 대응하는 `requirements.md`, `api_spec.md`, `component_spec.md`를 함께 확인한다.

| 테스트 영역 | requirements.md | api_spec.md | component_spec.md | 문서 상태 |
| --- | --- | --- | --- | --- |
| 실행 편의성 | `docs/features/workflow/requirements.md`의 `### 1. 실행 편의성` | `docs/features/workflow/api_spec.md`의 `### 1. 실행 편의성` | `docs/features/workflow/component_spec.md`의 `### 1. 실행 편의성` | 매핑됨 |
| 노드 조작 편의성 | `docs/features/workflow/requirements.md`의 `### 2. 노드 조작 편의성` | `docs/features/workflow/api_spec.md`의 `### 2. 노드 조작 편의성` | `docs/features/workflow/component_spec.md`의 `### 2. 노드 조작 편의성` | 매핑됨 |
| 워크플로우 조작 편의성 | `docs/features/workflow/requirements.md`의 `### 3. 워크플로우 조작 편의성` | `docs/features/workflow/api_spec.md`의 `### 3. 워크플로우 조작 편의성` | `docs/features/workflow/component_spec.md`의 `### 3. 워크플로우 조작 편의성` | 매핑됨 |
| 노드 실행 기록 패널 추가 | `docs/features/workflow/requirements.md`의 `### 4. 노드 실행 기록 패널 추가` | `docs/features/workflow/api_spec.md`의 `### 4. 노드 실행 기록 패널 추가` | `docs/features/workflow/component_spec.md`의 `### 4. 노드 실행 기록 패널 추가` | 매핑됨 |
| 동시성 처리 | 문서 보완 필요. 현재 `requirements.md`에 독립 요구사항 섹션이 없다. | 문서 보완 필요. 현재 `api_spec.md`에 draft revision, stream session, cursor 동시성 계약이 없다. | 문서 보완 필요. 현재 `component_spec.md`에 stale response, conflict UI, 중복 실행 방지 상태가 없다. | 미매핑 |
| 정책 확정 필요 | `docs/features/workflow/requirements.md`의 `## Open Questions`와 연결 | `docs/features/workflow/api_spec.md`의 `## Errors` 또는 `## Permissions` 보완 필요 | 정책 확정 후 관련 interaction/accessibility 섹션 보완 필요 | 부분 매핑 |

## Demo Test Priority

데모 전까지 모든 테스트를 같은 비중으로 구현하지 않는다. 안정적으로 시연되는 workflow 생성/편집/테스트 실행 경로를 우선하며, 테스트 케이스는 다음 3등급으로 나눈다.

- `Priority 1`: 데모 전에 반드시 구현하고 통과시킨다. 실패하면 핵심 시연 흐름이 깨지거나 사용자에게 오류로 보인다.
- `Priority 2`: 데모 안정성을 높이는 항목이다. 시간이 남으면 구현하고, 데모 전에는 수동 QA 또는 todo로 추적한다.
- `Priority 3`: 운영 품질, 대규모 사용, 장기 안정성 항목이다. 데모 이후 별도 이슈로 구현한다.

| Priority | 영역 | 테스트/요구 항목 | 현재 상태 | 미구현/미통과 사유 | 대응 파일 |
| --- | --- | --- | --- | --- | --- |
| 1 | 실행 편의성 | 노드 output token/cost 읽기와 `-` fallback 표시 | 통과 | 구현 및 unit test 완료 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 1 | 실행 편의성 | 노드별 실행 상태, 시간, 비용, 토큰 표시 | 통과 | node summary parser와 `TestSidebar` 표시 경로 구현 완료 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts`, `apps/client/app/features/workflow/components/editor/TestSidebar.tsx` |
| 1 | 실행 편의성 | `node_finish` 표준 필드 `latency_ms`, `total_tokens`, `total_cost` 우선 표시 | 통과 | 프론트 summary parser unit test 완료. Gateway/engine API contract test는 별도 API test infra에서 다룬다. | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 1 | 실행 편의성 | 최종 서버 실행 시간, 화면 완료 시간, 비용, 토큰 요약 표시 | 통과 | workflow-level summary 우선 사용과 node 합산 fallback unit test 완료 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 1 | 실행 편의성 | 테스트 성공 후 최종 사용자가 받는 `최종 응답` 카드 표시 | 통과 | workflow output, answer/response node, LLM output fallback helper와 카드 render test 완료 | `apps/client/app/features/workflow/tests/testExecutionFinalResponse.test.ts`, `apps/client/app/features/workflow/tests/test-sidebar-final-response-card.test.tsx`, `apps/client/app/features/workflow/components/editor/TestSidebar.tsx` |
| 1 | 실행 편의성 | JSON/긴/빈/정책 차단성 최종 응답 preview 처리 | 통과 | JSON key/value preview, empty state, 긴 응답 보존, 민감 key redaction unit test 완료 | `apps/client/app/features/workflow/tests/testExecutionFinalResponse.test.ts`, `apps/client/app/features/workflow/tests/test-sidebar-final-response-card.test.tsx` |
| 1 | 실행 편의성 | 서버 실행 시간과 화면 완료 시간을 서로 다른 라벨로 표시 | 통과 | `TestSidebar`가 `서버 실행`/`화면 완료` 라벨을 분리하고 summary unit test 완료 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts`, `apps/client/app/features/workflow/components/editor/TestSidebar.tsx` |
| 1 | 실행 편의성 | 테스트 실행 중복 클릭 방지 또는 기존 stream 정리 | 통과 | 실행 중/업로드/저장 중/권한 없음 disabled 조건 unit test 완료 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 1 | 실행 편의성 | stream 실패 시 사용자에게 실패 상태 표시 | 통과 | 실패 상태 store transition unit test와 `TestSidebar` 실패 UI 구현 완료 | `apps/client/app/features/workflow/store/useWorkflowStore.test.ts`, `apps/client/app/features/workflow/components/editor/TestSidebar.tsx` |
| 1 | 노드 조작 편의성 | 3패널 기본 표시 | 통과 | 기본 3패널 폭 산출 unit test와 `NodeFullscreenEditor` grid 구현 완료 | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts`, `apps/client/app/features/workflow/components/editor/NodeFullscreenEditor.tsx` |
| 1 | 노드 조작 편의성 | 3패널 resize 계산의 min/max clamp | 통과 | layout 계산 unit test 완료 | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 1 | 노드 조작 편의성 | viewport width 90% 안에서 편집 화면 표시 | 통과 | layout 계산 unit test 완료. 실제 DOM 폭은 수동 QA 필요 | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 1 | 노드 조작 편의성 | 기본 패널 폭을 부모 영역 기준 28/52/20 비율로 계산 | 통과 | layout 계산 unit test 완료 | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 1 | 워크플로우 조작 편의성 | Delete/Backspace로 선택 노드 삭제 | 통과 | shortcut hook test 완료 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 1 | 워크플로우 조작 편의성 | A -> B -> C 구조에서 B 삭제 시 A -> C 자동 재연결 | 통과 | store unit test 완료 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 1 | 워크플로우 조작 편의성 | 입력 필드 focus 중 Backspace/Delete가 노드 삭제로 동작하지 않음 | 통과 | shortcut hook test 완료 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 1 | 워크플로우 조작 편의성 | 삭제 후 undo 복구 | 통과 | store unit test 완료 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 1 | 워크플로우 조작 편의성 | 왼쪽 노드 패널의 `뒤에 추가`가 선택 노드 오른쪽에 새 노드와 edge를 생성 | 통과 | 선택 노드 우선, 미선택 시 단일 terminal만 허용, note 제외, undo 단위, validation 실패 rollback unit test 완료 | `apps/client/app/features/workflow/tests/workflow-add-after-selected-node.test.ts` |
| 1 | 동시성 처리 | 자동 저장 응답이 늦게 도착해도 최신 화면 상태를 이전 상태로 되돌리지 않음 | 통과 | active workflow가 아닌 data 적용 시 현재 화면 nodes/edges를 덮지 않는 store test 완료 | `apps/client/app/features/workflow/store/useWorkflowStore.test.ts` |
| 1 | 동시성 처리 | 테스트 실행 중 graph를 수정해도 실행 결과가 현재 편집 중인 설정값을 덮어쓰지 않음 | 통과 | 실행 결과 observability merge가 기존 node 설정값을 유지하는 store test 완료 | `apps/client/app/features/workflow/store/useWorkflowStore.test.ts` |
| 2 | 실행 편의성 | 권한 없는 테스트 실행의 403 처리 | 미구현 테스트 | Gateway/API contract test infra가 필요하다 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 2 | 실행 편의성 | scope 밖 workflow 테스트 실행의 404 처리 | 미구현 테스트 | Gateway/API contract test infra가 필요하다 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 2 | 실행 편의성 | 캔버스에 별도 테스트 실행 요약 패널이 표시되지 않는지 UI test로 고정 | 미구현 테스트 | BottomPanel/Canvas render test가 아직 없다 | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 2 | 노드 조작 편의성 | 실제 pointer drag interaction test | 미구현 테스트 | DOM pointer event test가 아직 없다 | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 2 | 노드 조작 편의성 | 닫았다가 다시 열었을 때 세션 내 패널 비율 유지 정책 고정 | 미구현 테스트 | 세션 유지 범위에 대한 UI test가 필요하다 | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 2 | 노드 조작 편의성 | read-only 사용자의 리사이즈 가능/수정 불가 구분 | 미구현 테스트 | read-only render fixture가 아직 없다 | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 2 | 워크플로우 조작 편의성 | incoming only/outgoing only 삭제 edge 정리 | 부분 구현 | 구현은 포함되어 있으나 별도 명시 테스트가 없다 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 2 | 워크플로우 조작 편의성 | 여러 incoming/outgoing 조합 재연결 중복 방지 | 통과 | store unit test 완료 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 2 | 워크플로우 조작 편의성 | 여러 노드 동시 삭제 재연결 후보 제외 | 부분 구현 | 구현은 남는 노드 기준으로 동작하나 다중 삭제 fixture test가 없다 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 2 | 노드 실행 기록 패널 추가 | 실행 기록 탭 기본 상태 | 미구현 | UI가 아직 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 2 | 노드 실행 기록 패널 추가 | 빈 상태 안내 | 미구현 | UI가 아직 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 2 | 노드 실행 기록 패널 추가 | 최신 기록 불러오기 | 미구현 | UI/API가 아직 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 2 | 노드 실행 기록 패널 추가 | JSON/plain text input/output 읽기 표시 | 미구현 | detail renderer가 아직 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 2 | 동시성 처리 | 같은 workflow를 두 브라우저 세션에서 열고 수정할 때 충돌 또는 최신 상태 갱신 안내 | 미구현 | 충돌 감지 정책/API가 없다 | TBD |
| 2 | 동시성 처리 | 권한 회수 후 열린 탭에서 저장/배포/실행 시 최신 권한 기준으로 거부 | 미구현 테스트 | Gateway 권한 재검증 test와 UI error handling test가 필요하다 | TBD |
| 3 | 노드 실행 기록 패널 추가 | node execution log 목록/상세 API 전체 | 미구현 | API가 아직 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 3 | 노드 실행 기록 패널 추가 | `limit`, `cursor`, `status`, `q`, `from`, `to` query 처리 | 미구현 | API가 아직 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 3 | 노드 실행 기록 패널 추가 | preview/full payload redaction 정책 | 미구현 | API response/redaction 정책 구현이 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 3 | 노드 실행 기록 패널 추가 | 120개 이상 실행 로그 pagination | 미구현 | API/UI pagination 구현이 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 3 | 노드 실행 기록 패널 추가 | 실행 로그 목록 실패 retry UI | 미구현 | error/retry UI가 아직 없다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 3 | 동시성 처리 | draft revision/ETag 기반 충돌 API | 미구현 | draft revision contract가 없다 | TBD |
| 3 | 동시성 처리 | 배포 snapshot revision 고정 | 미구현 | 배포 API snapshot/revision contract가 없다 | TBD |
| 3 | 동시성 처리 | cursor pagination 중 동시 insert 중복/누락 방지 | 미구현 | cursor 정렬 기준과 API test가 없다 | TBD |
| 3 | 동시성 처리 | 오프라인 편집 후 온라인 복귀 충돌 확인 | 미구현 | offline edit flow가 없다 | TBD |
| 3 | 동시성 처리 | 실행 stream 재연결 시 이전 이벤트와 새 실행 결과 격리 | 미구현 | stream session id 또는 cleanup 정책이 없다 | TBD |
| 3 | 정책 확정 필요 | 시작 트리거/삭제 제한 노드 삭제 정책 | 정책 필요 | 현재 legacy `deletable:false` 제거 정책과 삭제 제한 요구가 충돌한다 | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 3 | 정책 확정 필요 | run은 존재하지만 현재 node_id 기록이 없는 상세 조회 오류 형식 | 문서 보완 필요 | 404와 `node_execution_log.not_found` 중 하나로 확정해야 테스트를 고정할 수 있다 | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |

## Todo Test Coverage Register

다음 항목은 테스트 케이스에는 존재하지만 아직 실행 가능한 assertion 테스트로 전환되지 않았다. 각 항목은 미완료 단계가 해소되면 대응 테스트 파일에서 `it.todo`를 실제 `it(...)`로 바꾼다.

### 실행 편의성

| Todo | 미완료 단계 | 이유 | 대응 파일 |
| --- | --- | --- | --- |
| 테스트 실행 스트리밍 API가 `node_start`, `node_finish`, `workflow_finish` 이벤트를 반환한다 | API test infra | 현재 client Vitest에서 Gateway streaming contract를 직접 검증하지 않는다. API integration/e2e 테스트 경계가 필요하다. | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| `node_finish` 이벤트는 `latency_ms`, `total_tokens`, `total_cost`를 표준 필드로 반환한다 | API test infra | Gateway/engine streaming contract test가 필요하다. | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 권한 없는 사용자의 테스트 실행 요청은 403으로 거부된다 | API test infra | Gateway 권한 응답 검증이 client unit test 범위 밖이다. API test 또는 MSW 기반 contract test가 필요하다. | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| scope 밖 workflow 테스트 실행 요청은 404로 처리된다 | API test infra | active organization scope 검증은 Gateway/API 통합 테스트가 필요하다. | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 캔버스에는 별도 테스트 실행 요약 패널이 표시되지 않는다 | UI test | 캔버스/BottomPanel render test가 아직 없다. | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |
| 프론트 버튼 disabled여도 API 직접 호출 권한 검증은 Gateway에서 유지된다 | API test infra | Gateway authorization contract test가 필요하다. | `apps/client/app/features/workflow/tests/execution-convenience.test.ts` |

### 노드 조작 편의성

| Todo | 미완료 단계 | 이유 | 대응 파일 |
| --- | --- | --- | --- |
| 패널을 최대/최소 폭까지 드래그해도 UI가 겹치거나 화면 밖으로 밀려나지 않는다 | UI test | pointer drag 기반 DOM interaction test가 아직 없다. | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 노드 상세 편집 화면을 닫았다가 같은 세션에서 다시 열었을 때 세션 내 비율 유지 정책이 의도대로 동작한다 | UI behavior | 현재 구현은 컴포넌트 생명주기 안의 state 유지 기준이다. 닫기/재열기 정책을 UI test로 고정해야 한다. | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| read-only 사용자는 패널 리사이즈는 할 수 있지만 node data 수정/저장은 할 수 없다 | UI/permission test | read-only 상태에서 리사이즈와 수정 차단을 함께 검증하는 render test가 없다. | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 드래그 중 마우스가 편집 영역 밖으로 나가도 pointer capture 또는 window event 처리로 리사이즈가 끊기지 않는다 | UI test | window pointer event 기반 interaction test가 필요하다. | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |
| 드래그 종료 후 텍스트 선택 상태나 캔버스 pan 상태가 남지 않는다 | UI test | `document.body.style` cleanup과 canvas pan 상태를 검증하는 DOM test가 없다. | `apps/client/app/features/workflow/tests/node-panel-resize.test.ts` |

### 워크플로우 조작 편의성

| Todo | 미완료 단계 | 이유 | 대응 파일 |
| --- | --- | --- | --- |
| read-only 사용자는 Backspace/Delete로 노드 삭제 또는 자동 재연결을 수행할 수 없다 | UI permission test | `NodeCanvas`의 `isReadOnly` 조건과 shortcut hook 연결을 render test로 검증해야 한다. | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 삭제 대상 노드에 incoming edge만 있거나 outgoing edge만 있으면 재연결 없이 해당 노드와 연결 edge만 제거한다 | Unit test | 구현은 이 동작을 포함하지만 별도 명시 테스트가 아직 없다. | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 삭제 대상이 시작 트리거 노드 또는 삭제 제한 노드라면 기존 삭제 제한 정책을 따른다 | Policy/implementation | 현재 legacy `deletable:false` 제거 정책과 삭제 제한 정책이 충돌한다. 제품 정책 확정 후 테스트가 필요하다. | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |
| 여러 노드를 동시에 삭제할 때 삭제되는 노드끼리의 edge는 재연결 후보에서 제외한다 | Unit test | 구현은 삭제 후 남는 노드 기준으로 계산하지만 다중 삭제 fixture 테스트가 아직 없다. | `apps/client/app/features/workflow/tests/workflow-delete-reconnect.test.tsx` |

### 노드 실행 기록 패널 추가

| Todo | 미완료 단계 | 이유 | 대응 파일 |
| --- | --- | --- | --- |
| 실행 기록 탭 기본 상태는 실행 목록 검색과 가장 최신 로그 기록 불러오기 버튼을 표시한다 | UI implementation | 노드 실행 기록 패널 UI가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 선택된 실행 기록이 없으면 빈 상태 안내를 표시한다 | UI implementation | 빈 상태 UI가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 실행 목록 검색 버튼을 누르면 오른쪽 패널이 picker view로 전환된다 | UI implementation | picker view 전환 UI가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| picker view는 workflow run 목록을 최신순으로 표시한다 | UI/API implementation | 목록 API와 picker UI가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| picker row는 workflow run 요약과 현재 node_id의 node run/trace preview를 함께 표시한다 | UI/API implementation | summary response와 row UI가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| picker row를 선택하면 detail view로 전환되고 선택한 run 안의 현재 노드 input/output을 표시한다 | UI/API implementation | detail API와 detail view가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 가장 최신 로그 기록 불러오기 버튼은 현재 node_id 기록이 포함된 가장 최신 run을 선택한다 | UI/API implementation | latest selection API/query 동작이 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 현재 node_id 기록이 없는 run은 row에서 제외되거나 현재 노드 기록 없음으로 표시된다 | UI/API implementation | node_id 기반 목록 필터링 정책은 문서화됐지만 구현이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| input/output JSON 값은 읽기 가능한 형태로 렌더링된다 | UI implementation | detail renderer가 아직 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| plain text input/output 값은 줄바꿈이 보존되어 렌더링된다 | UI implementation | detail renderer가 아직 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| workflow read 권한 사용자는 node execution log 목록 API로 현재 node_id 기록 포함 run 목록을 조회할 수 있다 | API implementation | node execution log 목록 API가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| node execution log 목록 API는 `limit`, `cursor`, `status`, `q`, `from`, `to` query를 처리한다 | API implementation | query contract는 문서에 있으나 Gateway 구현이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| node execution log 목록 API는 full input/output이 아니라 preview 문자열만 반환한다 | API implementation | response redaction/preview contract 구현이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| node execution log 상세 API는 선택한 run 안의 현재 node_id input/output/trace/usage 상세를 반환한다 | API implementation | detail API가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| workflow read 권한이 없는 사용자의 실행 로그 조회 요청은 403으로 거부된다 | API implementation | node execution log API 권한 검증 구현이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| active organization scope 밖 workflow의 실행 로그 조회 요청은 404로 처리된다 | API implementation | node execution log API scope masking 구현이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 현재 node_id 기록이 없는 workflow는 목록 API에서 빈 목록을 반환한다 | API implementation | node_id filter 구현이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| run은 존재하지만 현재 node_id 기록이 없는 상세 조회는 404 또는 `node_execution_log.not_found`로 처리한다 | API/document gap | 문서가 404 또는 error code 둘 다 허용한다. 하나로 확정해야 테스트를 고정할 수 있다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 상태 필터를 실패로 바꾸면 실패 run 또는 실패 node 기록만 목록에 남는다 | UI/API implementation | status filter API와 UI 연결이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 검색어를 입력하면 input/output/error preview에 해당 검색어가 포함된 실행 기록을 찾을 수 있다 | UI/API implementation | `q` 검색 API와 UI 연결이 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| workflow read 권한만 있는 사용자는 실행 기록을 조회할 수 있지만 노드 설정을 수정할 수 없다 | UI/permission implementation | read-only detail view와 edit control 차단 UI가 아직 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 실행 기록 조회는 workflow write 권한을 요구하지 않는다 | API implementation | read-only 권한으로 조회 가능한 API contract test가 필요하다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 현재 node_id 기록이 있는 실행 로그가 없으면 이 노드의 실행 기록이 없습니다 안내를 표시한다 | UI/API implementation | empty API response와 empty UI가 아직 구현되지 않았다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| run detail에는 있으나 input/output payload가 retention 또는 redaction으로 비어 있으면 표시 가능한 기록 없음으로 표시한다 | UI/API implementation | redaction-aware detail response와 UI가 아직 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 실행 로그가 120개 이상 있어도 초기 목록은 제한된 개수만 렌더링하고 더 보기로 확장한다 | UI/API implementation | pagination API와 더 보기 UI가 아직 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |
| 실행 로그 목록 조회 실패 시 오류 안내와 다시 시도 액션을 표시한다 | UI implementation | 목록 error state와 retry UI가 아직 없다. | `apps/client/app/features/workflow/tests/node-execution-log-panel.todo.test.ts` |

### 동시성 처리

| Todo | 미완료 단계 | 이유 | 대응 파일 |
| --- | --- | --- | --- |
| 같은 workflow draft를 두 탭에서 동시에 편집하면 뒤늦은 저장이 최신 변경을 조용히 덮어쓰지 않는다 | API/UX policy | draft version, updated_at, ETag 등 충돌 감지 기준이 문서/API에 확정되어 있지 않다. | TBD |
| 자동 저장 요청이 연속 발생할 때 오래된 응답이 최신 로컬 상태를 되돌리지 않는다 | UI implementation/test | auto-sync request ordering 또는 stale response guard 정책을 테스트로 고정해야 한다. | TBD |
| 테스트 실행 중 사용자가 workflow graph를 수정해도 실행 요청은 시작 시점 draft snapshot 기준으로 처리된다 | UI/API contract | 실행 snapshot 생성 시점과 이후 편집 상태의 분리 기준을 API/UI 테스트로 고정해야 한다. | TBD |
| 동시에 두 번 테스트 실행을 눌러도 중복 stream이 열리거나 결과가 섞이지 않는다 | UI implementation/test | 실행 버튼 disable, in-flight guard, stream cleanup 테스트가 필요하다. | TBD |
| 배포 요청과 draft 저장 요청이 겹쳐도 배포 snapshot은 의도한 버전의 graph를 사용한다 | API/UX policy | 배포 시 draft revision 고정 정책이 문서/API에 확정되어 있지 않다. | TBD |
| workflow run 목록/노드 실행 기록 조회 중 새 run이 생성되어도 pagination cursor가 중복/누락 없이 동작한다 | API implementation | cursor 정렬 기준과 동시 insert 처리 정책이 필요하다. | TBD |
| 같은 노드를 여러 사용자가 동시에 수정하면 충돌 안내 또는 최신 상태 재조회 경로를 제공한다 | UX/API policy | 협업 편집을 허용할지, last-write-wins를 허용할지 정책 결정이 필요하다. | TBD |

## Unit Tests

### 1. 실행 편의성

- `node_finish.total_tokens`가 있으면 테스트 실행 사이드바에 해당 토큰 수를 표시한다.
- `node_finish.total_cost`가 있으면 테스트 실행 사이드바에 해당 비용을 표시한다.
- `node_finish.latency_ms`가 있으면 노드 소요 시간은 해당 값을 우선 표시한다.
- 토큰 정보가 없으면 `-`를 표시한다.
- 비용 정보가 없으면 `-`를 표시한다.
- `node_start` 후 `node_finish`를 받으면 소요 시간이 ms 단위로 표시 가능한 값으로 계산된다.
- 전체 테스트 실행 완료 시 화면 완료 시간, 전체 비용, 전체 토큰 사용량이 계산된다.
- `workflow_finish`가 서버 실행 시간 summary를 제공하면 최종 요약은 서버 실행 시간을 주 지표로 표시한다.
- `workflow_finish`가 서버 실행 시간 summary를 제공하지 않으면 최종 요약은 서버 실행 시간 fallback과 화면 완료 시간을 함께 표시한다.
- 최종 응답 helper는 `workflow_finish.output`, answer/response node output, LLM node text 계열 output 순서로 preview 후보를 선택한다.
- JSON 최종 응답은 raw dump 대신 key/value preview로 요약한다.
- 권한/정책 차단성 최종 응답은 사용자 메시지를 표시하되 hidden KB id, source path/url/title, credential, raw trace payload를 preview에서 제외한다.
- 빈 최종 응답은 empty state로 표시할 수 있는 값을 반환한다.

### 2. 노드 조작 편의성

- 3패널 layout 계산에서 각 패널 폭은 최소/최대 폭 제약을 넘지 않는다.
- 사용자가 아직 직접 조정하지 않은 기본 패널 폭은 부모 영역 기준 왼쪽 28%, 가운데 52%, 오른쪽 20% 비율로 계산된다.
- 왼쪽 패널 폭을 늘리면 가운데와 오른쪽 패널 폭이 비슷한 비율로 줄어든다.
- 전체 편집 영역은 viewport width의 90%를 초과하지 않는다.
- 패널 폭 계산은 실제 렌더된 부모 영역 폭이 바뀌면 그 폭을 기준으로 다시 clamp된다.
- reset 동작이 있다면 패널 폭이 기본 비율로 복구된다.

### 3. 워크플로우 조작 편의성

- 선택 노드가 있는 상태에서 왼쪽 노드 패널의 `뒤에 추가`를 실행하면 선택 노드 오른쪽에 새 노드가 생성되고 선택 노드에서 새 노드로 edge가 생성된다.
- 일반 노드 클릭/추가는 기존 자유 배치 흐름을 유지하고, `뒤에 추가` 액션과 동작이 섞이지 않는다.
- 선택 노드가 없고 terminal node가 하나뿐이면 `뒤에 추가`는 terminal node 뒤에 연결할 수 있다.
- 선택 노드가 없고 terminal node가 여러 개이면 `뒤에 추가`는 임의 연결하지 않고 실행하지 않는다.
- sticky note처럼 workflow 실행 graph에 포함되지 않는 보조 노드는 terminal node 계산에서 제외한다.
- 선택 노드가 여러 개이면 `뒤에 추가`는 임의 연결하지 않고 실행하지 않는다.
- condition/switch/loop처럼 handle이 모호한 노드는 연결 handle이 명확할 때만 자동 edge를 생성한다.
- `뒤에 추가`는 전체 graph 정렬을 실행하지 않고 새 노드 주변 local placement만 수행한다.
- `뒤에 추가`는 노드 생성과 edge 생성을 undo 한 번으로 되돌릴 수 있어야 한다.
- `뒤에 추가` edge 생성이 일반 연결 validation을 통과하지 못하면 새 노드도 남기지 않는다.
- 단일 중간 노드를 삭제하면 incoming source와 outgoing target 사이에 새 edge가 생성된다.
- 자동 재연결은 기존 연결 검증 규칙을 통과하는 경우에만 edge를 생성한다.
- 여러 incoming/outgoing edge가 있는 노드를 삭제하면 가능한 유효 조합만 생성하고 중복 edge는 만들지 않는다.
- 입력 필드에 focus가 있을 때 Backspace/Delete를 눌러도 노드 삭제 함수가 호출되지 않는다.

### 4. 노드 실행 기록 패널 추가

- 실행 기록 탭 기본 상태는 `실행 목록 검색`과 `가장 최신 로그 기록 불러오기` 버튼을 표시한다.
- 선택된 실행 기록이 없으면 빈 상태 안내를 표시한다.
- 실행 목록 검색 버튼을 누르면 오른쪽 패널이 picker view로 전환된다.
- picker view는 workflow run 목록을 최신순으로 표시한다.
- picker row는 workflow run 요약과 현재 node_id의 node run/trace preview를 함께 표시한다.
- picker row를 선택하면 detail view로 전환되고 선택한 run 안의 현재 노드 input/output을 표시한다.
- 가장 최신 로그 기록 불러오기 버튼은 현재 node_id 기록이 포함된 가장 최신 run을 선택한다.
- 현재 node_id 기록이 없는 run은 row에서 제외되거나 `현재 노드 기록 없음`으로 표시된다.
- input/output JSON 값은 읽기 가능한 형태로 렌더링된다.
- plain text input/output 값은 줄바꿈이 보존되어 렌더링된다.

### 5. 동시성 처리

- 자동 저장 요청이 빠르게 여러 번 발생하면 마지막 요청 결과만 현재 편집 상태에 반영된다.
- 테스트 실행 중 graph를 수정해도 실행 결과는 실행 시작 시점의 draft snapshot에 대응된다.
- 테스트 실행 stream이 이미 진행 중이면 중복 실행 요청을 막거나 이전 stream을 명확히 정리한다.
- undo/redo 중 자동 저장이 발생해도 로컬 graph와 저장된 draft가 서로 다른 revision으로 조용히 엇갈리지 않는다.

## API Tests

### 1. 실행 편의성

- 기존 테스트 실행 스트리밍 API가 `node_start`, `node_finish`, `workflow_finish` 이벤트를 반환한다.
- `node_finish` 이벤트는 node-level summary 표준 필드 `latency_ms`, `total_tokens`, `total_cost`를 포함한다.
- `workflow_finish` 이벤트가 workflow run summary를 제공하는 경우 `run_id`, `duration`, `total_tokens`, `total_cost`를 포함한다.
- `workflow_finish.duration`은 `workflow_runs.duration`과 같은 서버 실행 시간 기준이다.
- 권한 없는 사용자의 테스트 실행 요청은 403으로 거부된다.
- scope 밖 workflow 테스트 실행 요청은 404로 처리된다.

### 4. 노드 실행 기록 패널 추가

- workflow read 권한이 있는 사용자는 node execution log 목록 API로 현재 node_id 기록이 포함된 run 목록을 조회할 수 있다.
- node execution log 목록 API는 `limit`, `cursor`, `status`, `q`, `from`, `to` query를 처리한다.
- node execution log 목록 API는 full input/output이 아니라 preview 문자열만 반환한다.
- node execution log 상세 API는 선택한 run 안의 현재 node_id input/output/trace/usage 상세를 반환한다.
- workflow read 권한이 없는 사용자의 실행 로그 조회 요청은 403으로 거부된다.
- active organization scope 밖 workflow의 실행 로그 조회 요청은 404로 처리된다.
- 현재 node_id 기록이 없는 workflow는 목록 API에서 빈 목록을 반환한다.
- run은 존재하지만 현재 node_id 기록이 없는 상세 조회는 404 또는 `node_execution_log.not_found`로 처리한다.

### 5. 동시성 처리

- draft 저장 API는 클라이언트가 보낸 revision 또는 updated_at이 서버 최신 값보다 오래되면 충돌 응답을 반환한다.
- 동일 workflow에 대해 동시 저장 요청 2개가 도착하면 서버는 최신 revision 기준으로 하나만 성공시키거나 명시적 충돌을 반환한다.
- 배포 API는 요청 시점에 지정한 draft revision 또는 snapshot id를 기준으로 배포한다.
- 실행 로그 목록 API는 새 run이 조회 중 생성되어도 cursor pagination에서 중복 row를 반환하지 않는다.

## E2E Tests

### 1. 실행 편의성

- 빌더가 워크플로우 테스트를 실행하면 테스트 실행 사이드바에 노드별 상태가 표시된다.
- 실행 중인 노드는 `실행 중`, 완료된 노드는 `성공`, 실패한 노드는 `실패`로 표시된다.
- `node_finish` 이벤트에 토큰/비용 표준 필드가 있으면 테스트 실행 사이드바에 토큰 수와 비용이 표시된다.
- 테스트 성공 후 테스트 실행 사이드바 상단에 최종 사용자가 받는 `최종 응답` 카드가 표시된다.
- JSON 최종 응답은 카드에서 읽기 쉬운 preview로 표시되고, 원본 JSON은 노드별 실행 결과 상세 영역에 유지된다.
- 테스트 완료 후 테스트 실행 사이드바 마지막 영역에 서버 실행 시간, 화면 완료 시간, 전체 비용, 전체 토큰 사용량이 표시된다.
- 서버 실행 시간과 화면 완료 시간은 `서버 실행`, `화면 완료`처럼 서로 다른 라벨로 구분된다.
- 캔버스에는 별도 테스트 실행 요약 패널이 표시되지 않는다.
- 다시 테스트하기를 누르면 이전 실행 요약이 초기화되고 새 실행 결과로 갱신된다.

### 2. 노드 조작 편의성

- 노드 상세 편집 화면을 열면 3패널이 기본 비율로 표시된다.
- 노드 상세 편집 화면은 넓은 화면에서도 viewport width의 90% 안에서 표시된다.
- 노드 상세 편집 화면은 넓은 화면에서 고정 px 기본값에 갇히지 않고 부모 영역 기준 최대 90% 폭을 사용한다.
- 사용자가 왼쪽 패널 resizer를 드래그하면 왼쪽 패널은 넓어지고 가운데/오른쪽 패널은 같이 줄어든다.
- 패널을 최대/최소 폭까지 드래그해도 UI가 겹치거나 화면 밖으로 밀려나지 않는다.
- 노드 상세 편집 화면을 닫았다가 같은 세션에서 다시 열었을 때 세션 내 비율 유지 정책이 의도대로 동작한다.

### 3. 워크플로우 조작 편의성

- 캔버스에서 노드를 클릭한 뒤 Backspace를 누르면 해당 노드가 삭제된다.
- 캔버스에서 노드를 클릭한 뒤 Delete를 누르면 해당 노드가 삭제된다.
- A → B → C 구조에서 B를 삭제하면 A → C edge가 생성된다.
- A → B → C 구조에서 B 삭제 후 undo를 실행하면 B와 기존 edge가 복구된다.
- LLM prompt textarea에 focus가 있는 상태에서 Backspace를 눌러도 선택 노드는 삭제되지 않는다.

### 4. 노드 실행 기록 패널 추가

- 노드 상세 패널에서 실행 기록 탭을 열면 기본 view가 표시된다.
- 실행 목록 검색을 클릭하면 오른쪽 패널 전체가 검색/필터/선택 화면으로 바뀐다.
- 상태 필터를 `실패`로 바꾸면 실패 run 또는 실패 node 기록만 목록에 남는다.
- 검색어를 입력하면 input/output/error preview에 해당 검색어가 포함된 실행 기록을 찾을 수 있다.
- 실행 로그 row를 선택하면 선택 화면이 닫히고 상세 view에 input/output/error/metadata가 표시된다.
- 가장 최신 로그 기록 불러오기를 클릭하면 목록 검색 없이 최신 노드 기록 상세가 표시된다.
- 실행 기록 상세를 보는 동안 현재 노드 설정값은 변경되지 않는다.

### 5. 동시성 처리

- 같은 workflow를 두 브라우저 세션에서 열고 각각 수정하면 충돌 또는 최신 상태 갱신 안내가 표시된다.
- 테스트 실행 버튼을 연속 클릭해도 실행 사이드바에는 하나의 실행 흐름만 표시된다.
- 테스트 실행 중 노드 설정을 수정한 뒤 결과가 도착해도 현재 편집 중인 설정값이 실행 결과 payload로 덮어써지지 않는다.
- 저장 중 네트워크 지연이 발생한 뒤 이전 저장 응답이 늦게 도착해도 최신 화면 상태가 이전 상태로 되돌아가지 않는다.

## Permission Tests

### 1. 실행 편의성

- `can_execute=false`인 사용자는 테스트 버튼을 실행할 수 없다.
- 프론트에서 테스트 버튼이 disabled여도 API 직접 호출 권한 검증은 Gateway에서 유지된다.

### 2. 노드 조작 편의성

- read-only 사용자는 패널 리사이즈는 할 수 있지만 node data 수정/저장은 할 수 없다.

### 3. 워크플로우 조작 편의성

- read-only 사용자는 Backspace/Delete로 노드 삭제 또는 자동 재연결을 수행할 수 없다.

### 4. 노드 실행 기록 패널 추가

- workflow read 권한만 있는 사용자는 실행 기록을 조회할 수 있지만 노드 설정을 수정할 수 없다.
- workflow read 권한이 없는 사용자는 실행 기록 탭에서 목록/상세를 조회할 수 없다.
- 실행 기록 조회는 workflow write 권한을 요구하지 않는다.

### 5. 동시성 처리

- write 권한이 없는 사용자의 stale draft 저장 재시도는 충돌 처리 이전에 권한 오류로 거부된다.
- manager가 권한을 회수한 뒤 열린 탭에서 저장/배포/실행을 시도하면 최신 권한 기준으로 거부된다.

## Edge Cases

### 1. 실행 편의성

- 토큰 사용량이 없는 non-LLM 노드는 토큰 칸에 `-`를 표시한다.
- 서버 실행 시간 summary가 없는 테스트 실행 결과는 서버 실행 시간 칸에 `-` 또는 `기록 없음`을 표시하고 화면 완료 시간은 유지한다.
- 화면 완료 시간이 서버 실행 시간보다 길어도 그 차이를 순수 UI 처리 시간으로 표시하지 않는다.
- 노드 실행 중 스트리밍이 실패하면 전체 실패 상태와 식별 가능한 노드 실패 상태를 함께 표시한다.
- 실행 결과가 매우 많은 경우 테스트 실행 사이드바 내부에서 스크롤되며 캔버스에는 별도 요약 패널을 만들지 않는다.

### 2. 노드 조작 편의성

- 화면 폭이 3패널 최소 폭 합보다 좁으면 resizer를 비활성화하거나 responsive fallback을 사용한다.
- 드래그 중 마우스가 편집 영역 밖으로 나가도 pointer capture 또는 window event 처리로 리사이즈가 끊기지 않는다.
- 드래그 종료 후 텍스트 선택 상태나 캔버스 pan 상태가 남지 않는다.

### 3. 워크플로우 조작 편의성

- 삭제 대상 노드에 incoming edge만 있거나 outgoing edge만 있으면 재연결 없이 해당 노드와 연결 edge만 제거한다.
- 삭제 대상이 시작 트리거 노드 또는 삭제 제한 노드라면 기존 삭제 제한 정책을 따른다.
- 여러 노드를 동시에 삭제할 때 삭제되는 노드끼리의 edge는 재연결 후보에서 제외한다.

### 4. 노드 실행 기록 패널 추가

- 현재 node_id 기록이 있는 실행 로그가 없으면 `이 노드의 실행 기록이 없습니다` 안내를 표시한다.
- run detail에는 있으나 input/output payload가 retention 또는 redaction으로 비어 있으면 `표시 가능한 기록 없음`으로 표시한다.
- 실행 로그가 120개 이상 있어도 초기 목록은 제한된 개수만 렌더링하고 `더 보기`로 확장한다.
- 긴 input/output은 패널을 깨지 않고 스크롤 또는 줄바꿈으로 표시된다.
- 실행 로그 목록 조회 실패 시 오류 안내와 다시 시도 액션을 표시한다.

### 5. 동시성 처리

- 저장 요청이 취소되거나 timeout된 뒤 재시도할 때 같은 draft revision을 중복 생성하지 않는다.
- 사용자가 오프라인 상태에서 편집한 뒤 온라인으로 돌아오면 서버 최신 revision과 충돌 여부를 확인한다.
- 실행 stream 연결이 끊긴 뒤 재연결하거나 재실행할 때 이전 stream 이벤트가 새 실행 결과에 섞이지 않는다.
- 배포 중 draft가 추가로 수정되면 배포 완료 알림은 배포된 snapshot과 현재 draft가 다를 수 있음을 구분한다.


## Runtime RAG Boundary Tests

- Workflow run context resolver는 interactive user를 `execution_subject`로 만들고, approved service account 또는 assigned operator는 후속 private RAG 기능으로 구분한다.
- Missing execution subject는 anonymous public-only 결과를 반환하고 workflow owner fallback을 만들지 않는다. Ambiguous execution subject는 private retrieval fail-closed로 처리한다.
- LLM node의 RAG 옵션은 Builder-time skill selection과 runtime data access 권한을 분리한다.

## API Tests

- 로그인 LLM node의 RAG 옵션 실행 요청은 Knowledge service에 `execution_subject=current_user`를 전달한다.
- LLM node RAG 선택 UI는 legacy owner-filtered `/knowledge` 목록이 아니라 active organization, KB `use` 권한, completed retrieval-visible document chunk 기준을 통과한 LLM-selectable 후보만 표시한다. 빈 KB 또는 `pending`/`failed` 문서만 있는 KB는 경고 없이 선택 가능한 후보로 노출하지 않는다. 후보가 없으면 "완료된 문서가 있는 지식 베이스가 없습니다." 같은 safe 안내를 표시한다.
- 인증 배포 실행 화면은 `GET /deployments/{deployment_id}/run-info` safe metadata만 사용하고, `auth_secret` 또는 `graph_snapshot`을 받지 않는다.
- 로그인 사용자의 배포 실행 요청(`/deployments/{deployment_id}/run`)은 workflow `execute` 권한을 재검증하고, active deployment snapshot을 `execution_subject=current_user`로 실행한다.
- 인증 배포 실행의 `conversation_id`는 서버에서 deployment와 execution subject 기준으로 namespace 처리되어 다른 사용자 memory context와 섞이지 않는다.
- `/run-public/{url_slug}` 공개 실행은 `execution_subject`를 주입하지 않으며 workflow owner 권한으로 private RAG를 fallback하지 않는다.
- Execution subject가 없으면 public collection 소속 active KB는 검색 가능하고 private collection 소속 KB는 검색되지 않는다. Source-managed KB는 valid source/connector public exposure approval이 없으면 public collection에 연결되어도 검색되지 않는다.
- Execution context에 `user_id`만 있고 `execution_subject`가 없으면 `user_id` 권한으로 private KB access를 fallback하지 않는다.
- Schedule/webhook/API trigger 실행은 배포 시 승인된 service account 또는 정책상 지정된 execution subject가 없으면 anonymous public-only로 Knowledge retrieval을 실행한다.
- 배포 preflight는 LLM node RAG 옵션의 KB/collection 후보가 deployment type에서 파생한 runtime audience에게 사용 가능한지 검증하고, unavailable/unknown/private 후보가 있으면 hidden id/count 없이 safe reason과 required action만 반환한다.
- Public/API/webhook/schedule/chatbot/MCP surface는 subject가 없으므로 private KB 후보가 있으면 활성 배포 create/toggle에서 `409 deployment.preflight.blocked`를 반환한다.
- Workflow-node runtime은 parent execution context를 상속한다. Parent subject가 있으면 해당 subject 기준 KB permission/source ACL을 사용하고, subject가 없으면 anonymous public-only로 낮춘다.
- Workflow-node preflight는 `workflowNode.data.appId`로 target app active deployment를 찾는다. `workflowId`로 target을 잘못 해석하면 테스트 실패다.

## E2E Tests

- 배포된 workflow의 LLM node의 RAG 옵션은 execution subject가 있으면 해당 subject 기준으로 KB permission/source ACL gate를 다시 평가하고, subject가 없으면 anonymous public-only gate를 사용한다. Builder actor 권한으로 fallback하지 않는다.
- Evidence sufficiency가 insufficient인 경우 workflow는 추측 답변을 생성하지 않고 safe no-result 응답 또는 명시된 분기 결과를 반환한다.
- Query rewrite가 켜진 LLM node의 RAG 옵션도 권한 없는 KB 또는 requester source authorization denied 문서를 prompt, citation, trace에 포함하지 않는다.
- 배포 시점에 available이던 KB가 실행 시점 source ACL stale/revoked 상태가 되면 workflow는 설정된 failure policy에 따라 safe no-result, fallback branch, 또는 node/workflow failure로 닫고 세부 source ACL reason을 사용자에게 노출하지 않는다.

## Permission Tests

- Workflow owner가 KB `use` 권한을 갖고 있어도 execution subject가 권한을 갖지 않으면 RAG retrieval은 실패하거나 resource-hidden/no-result matrix를 따른다. Execution subject가 없으면 owner 권한 대신 public-only 후보만 사용한다.
- Skill visibility 또는 workflow 작성 권한만으로 runtime KB permission/source ACL gate가 충족되지 않는다.
- RAG를 포함한 workflow compare/A-B 실행도 로그인 실행에서는 일반 workflow 실행과 같은 execution subject를 사용하고, subject가 없으면 public-only gate를 사용한다.

## Edge Cases

- `llm_assisted` query rewrite는 별도 승인 전까지 실행 가능한 variant가 아니다. 승인 후 실패하면 승인된 fallback 정책에 따라 원 query 사용 또는 terminal error로 처리하고, raw rewritten query를 durable metadata에 저장하지 않는다.
- 일부 authorized KB retrieval만 operational failure가 발생하면 Knowledge partial-result 정책에 맞춘 safe summary만 반환한다.
- Workflow runtime outbound egress guard는 Knowledge source collection egress boundary와 별도 gate이므로, Knowledge source connector guard가 workflow HTTP node 전체를 보호한다고 가정하지 않는다.
