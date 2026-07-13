# Workflow Requirements

Status: Draft
Related Features: auth, organization, agent-builder, audit-tracing, knowledge, mail-credentials, conversation-memory

## Purpose

Workflow feature는 사용자가 업무 절차를 노드 그래프로 구성하고, 수동 실행·스케줄·웹훅·API trigger로 실행할 수 있게 한다. 이 문서는 전체 workflow runtime 요구사항 중 다른 도메인과 충돌하기 쉬운 권한·실행 주체·감사 경계를 우선 기록한다.
워크플로우 생성, 편집, 테스트 실행, 배포의 기본 사용자 흐름을 제공한다. 빌더는 캔버스에서 노드를 조합하고, 테스트 실행으로 각 노드가 정상 동작하는지 확인한 뒤 배포로 이어간다.
MBA-104 범위에서는 비용 최적화와 A/B 비교 실행을 준비하기 위해 테스트 실행 UX를 먼저 정리한다. 테스트 버튼을 눌렀을 때 테스트 실행 사이드바에서 각 노드의 실행 상태, 소요 시간, 비용, 토큰 사용량을 한눈에 확인할 수 있어야 한다.


## User Stories

### 1. 실행 편의성
- 빌더로서, 테스트 실행 중 어떤 노드가 실행 중이고 어떤 노드가 완료/실패했는지 테스트 실행 사이드바에서 확인하고 싶다.
- 빌더로서, 각 노드별 소요 시간, 비용, 토큰 사용량을 빠르게 비교해 병목 또는 비용이 큰 노드를 찾고 싶다.
- 빌더로서, 워크플로우 테스트가 모두 끝난 뒤 서버에서 실제 워크플로우가 실행된 시간과 브라우저 화면에서 완료까지 체감한 시간을 함께 확인하고 싶다.
- 빌더로서, 워크플로우 테스트가 끝난 뒤 최종 사용자가 실제로 받게 되는 응답 메시지를 노드별 JSON 상세를 열기 전에도 한눈에 확인하고 싶다.
- 빌더로서, 전체 비용과 전체 토큰 사용량은 서버 실행 결과 기준으로 확인하고 싶다.
- 빌더로서, 향후 모델/프롬프트 A/B 비교를 붙이기 전에 기본 단일 실행 결과부터 명확하게 보고 싶다.


- 빌더로서, 배포 전에 필요한 credential과 권한 누락을 확인하고 싶다.
- 운영자로서, schedule/webhook/API trigger로 실행된 workflow가 명시 실행 주체 권한 또는 anonymous public-only 경계 중 무엇으로 RAG retrieval을 수행했는지 추적하고 싶다.
- 감사자로서, workflow owner와 실제 execution subject를 구분해 audit/trace에서 확인하고 싶다.

### 2. 노드 조작 편의성
- 빌더로서, 노드 상세 편집 화면에서 왼쪽/가운데/오른쪽 3패널의 가로 비율을 작업 맥락에 맞게 조정하고 싶다.
- 빌더로서, 프롬프트나 코드처럼 긴 내용을 편집할 때 왼쪽 편집 패널을 넓히되, 가운데 미리보기/캔버스와 오른쪽 보조 패널이 완전히 사라지지 않기를 원한다.

### 3. 워크플로우 조작 편의성
- 빌더로서, 선택한 노드를 Backspace 또는 Delete 키로 빠르게 삭제하고 싶다.
- 빌더로서, 중간 노드를 삭제했을 때 앞단과 뒷단 노드가 자연스럽게 다시 연결되어 워크플로우 흐름이 끊기지 않기를 원한다.

### 4. 노드 실행 기록 패널 추가
- 빌더로서, 노드 상세 패널에서 현재 노드의 과거 실행 input/output을 바로 참고하고 싶다.
- 빌더로서, 전체 워크플로우 실행 로그 중 현재 노드 기록이 포함된 실행을 검색/필터해 선택하고 싶다.
- 빌더로서, 가장 최신 실행 기록을 빠르게 불러와 현재 노드가 실제로 어떤 입력을 받고 어떤 출력을 냈는지 확인하고 싶다.
- 빌더로서, 과거 실행 기록을 참고하되 현재 노드 설정값과 과거 input/output을 혼동하지 않기를 원한다.

## Functional Requirements
- FR-001: Workflow run context는 organization, workflow, workflow version, run id, node id, trigger mode, actor 또는 service account 정보를 전달한다.
- FR-002: Interactive 실행은 요청 사용자를 execution subject로 사용할 수 있다.
- FR-003: Schedule, webhook, API trigger처럼 요청 사용자가 명확하지 않은 실행은 MVP에서 `execution_subject` 없이 anonymous public-only RAG로 실행한다. Private KB access가 필요한 자동 실행은 후속 service account, assigned operator, 또는 별도 정책으로 확정된 execution subject 기능이 필요하다.
- FR-004: RAG 옵션이 켜진 LLM node가 Knowledge retrieval을 호출할 때 workflow runtime은 로그인 interactive 실행에서는 `execution_subject=current_user`를 전달한다. 비로그인/자동 실행처럼 `execution_subject`가 없으면 anonymous public-only로 처리한다.
- FR-005: `execution_subject`가 없을 때 Workflow owner, deployment owner, app creator, builder, `user_id` 권한으로 조용히 fallback하지 않는다. Subject 부재는 private retrieval 실패가 아니라 anonymous public-only gate를 통과한 public collection/KB 후보만 허용하는 실행이다. Source-managed KB는 collection public visibility와 별도 source/connector public exposure approval을 모두 통과해야 한다. 모호하거나 지원하지 않는 subject는 private retrieval fail-closed로 처리한다.
- FR-006: Workflow owner, deployment owner, execution subject는 audit/trace에서 구분할 수 있어야 한다. Owner는 소유권과 관리 표시에는 사용할 수 있지만, 명시 정책 없이 실행 시점 data access 권한으로 사용하지 않는다.
- FR-007: Workflow runtime이 Knowledge Skill을 사용할 경우, execution subject 기준으로 skill visibility, freshness/eval, collection route, KB permission/source ACL gate를 통과해야 한다. 빌더 단계 skill 선택이나 workflow 작성자 권한은 실행 시점 data access 권한으로 전파되지 않는다.
- FR-008: LLM node의 RAG 옵션을 포함한 workflow 배포는 deployment type에서 파생한 runtime audience 기준 preflight를 수행해야 한다. 사용자 subject가 없는 public/API/webhook/schedule/chatbot/MCP surface는 private KB 후보를 활성 배포로 올릴 수 없고 anonymous public-only 후보만 허용한다.
- FR-009: Workflow-node 실행은 parent workflow의 execution context를 상속한다. Parent execution subject가 있으면 해당 subject 기준 KB permission/source ACL gate를 사용하고, subject가 없으면 anonymous public-only로 낮춘다. Deployment preflight에서 workflow-node target은 node 설정의 `workflowNode.data.appId`를 기준으로 target app active deployment를 찾는다.
- FR-010: System schedule execution은 App/deployment creator나 workflow owner를 executor로 기록하지 않아야 한다. Canonical schedule claim과 연결된 `WorkflowRun.user_id`는 null이고 audit actor는 system이어야 하며, 기존 manual/API/webhook interactive run의 사용자 attribution은 유지해야 한다.
- FR-011: Schedule Worker admission winner는 claim을 `running`으로 전이하는 같은 원자적 write에서 stable workflow run id를 생성·저장하고 duplicate delivery에서 같은 id를 재사용해야 한다. Admission 이후 실패나 timeout으로 outcome이 불명확하면 engine을 자동 재실행하지 않아야 한다.
- FR-012: Schedule execution context의 idempotency key는 node adapter까지 opaque correlation으로 전달할 수 있지만 prompt, user-visible output, durable raw trace에 복제하지 않아야 한다. 이 전달은 외부 provider의 exactly-once를 보장하지 않는다.
- FR-013: 요청 사용자가 없는 system schedule이 LLM provider credential을 사용해야 할 때 runtime은 locked canonical deployment의 `created_by`를 user형 credential principal로만 사용할 수 있다. 이 principal은 queue 입력에서 받지 않으며 executor, audit actor 또는 Knowledge execution subject로 승격하지 않는다. Legacy `LLMUsageLog.user_id`에는 비용/credential 귀속을 위해 이 principal을 기록하되 WorkflowRun actor 의미로 해석하지 않는다. 별도 service account principal은 lifecycle과 권한 모델이 승인되기 전까지 합성하지 않는다.
- FR-014: Code node는 sandbox tenant/fairness context에 canonical `execution_context.organization_id`를 전달해야 한다. `user_id`를 organization tenant로 해석하거나 system schedule의 null executor 때문에 canonical organization을 누락해서는 안 된다.
- FR-015: RAG retrieval 및 evidence policy block audit의 user actor는 실제 user형 `execution_subject`에서만 가져온다. System schedule은 `actor_id=NULL`, `actor_type=system`으로 기록하며, credential principal은 query embedding/LLM credential 선택에 사용할 수 있지만 RAG audit actor로 승격하지 않는다.
- FR-016: 실행 전 Knowledge sync는 best-effort 전처리다. Connector 또는 DB 동기화가 일시적으로 실패해도 이미 색인된 evidence로 Workflow Engine 실행을 계속하며, task 결과와 로그에는 raw 예외 없이 safe sync failure reason만 남긴다.
- FR-017 (Conversation Memory Target Integration): Memory-enabled task envelope은 memory contract/storage generation과 minimum Worker capability를 포함해야 한다. Worker는 외부 node side effect 전에 이를 검증하고 rolling migration에서는 capability 전용/versioned queue를 사용해야 한다. Preflight는 runtime task 검증을 대체하지 않는다.
- FR-018 (Conversation Memory Target Integration): Duplicate Memory dispatch는 Memory-owned write를 idempotent하게 처리해야 한다. Tool/connector/custom node의 외부 side effect 재시도·중복 방지는 Workflow node별 idempotency 계약이 소유하며 Memory dispatcher가 arbitrary workflow execution을 무조건 재실행해서는 안 된다.
- FR-019 (Conversation Memory Target Integration): Workflow application은 `AdmitExecution(dispatch_id)`을 durable/idempotent하게 수행해 같은 dispatch의 execution admission을 최대 하나만 생성하고 existing admission reference를 재반환해야 한다.
- FR-020 (Conversation Memory Target Integration): Workflow application은 Memory reconciler가 acknowledgement 유실을 복구할 수 있는 `GetExecutionAdmission(dispatch_id)` port를 제공해야 한다. Workflow execution lease/heartbeat와 retry policy는 Workflow가 소유하고 Memory turn state는 safe projection만 받아야 한다.
- FR-021 (Conversation Memory Target Integration): 모든 content-bearing node result는 server-derived `RuntimeDataDependencyEnvelope`와 completeness marker를 함께 전달해야 한다. Knowledge/connector/tool/system policy adapter는 자기 source dependency를 발급하고, subworkflow는 target deployment version과 child envelope 합집합을 반환해야 한다. Condition/Switch/Loop runtime은 predicate, selected route, iterable, bound와 termination에 사용한 dependency를 active control context로 전파하고 최종 envelope은 값 dependency와 활성 control dependency의 합집합을 가져야 한다. Producer가 값·제어 source 영향이 없음을 확인한 explicit complete empty envelope만 허용하고 missing/unknown envelope을 empty로 간주해서는 안 된다.
- FR-022 (Conversation Memory Target Integration): Transform/code/LLM/final output은 내용에 영향을 준 모든 input dependency의 합집합을 보존해야 한다. LLM output은 prompt input뿐 아니라 Memory Context, retrieval과 tool dependency도 상속해야 한다. V1은 optional dependency를 지원하지 않으며 node/client가 canonical dependency를 삭제·발급하거나 required 의미를 낮출 수 없어야 한다.
- FR-023 (Conversation Memory Target Integration): Provenance를 보존하지 못한 code/custom output은 public-only/non-sensitive라는 server-side 증명이 없으면 private/sensitive Memory write에서 fail-closed해야 한다.
- FR-024 (Conversation Memory Target Integration): Memory task/admission은 deployment ID와 immutable version 또는 snapshot hash, conversation mapping/Memory policy version, contract/storage generation을 고정해야 한다. Worker가 current active deployment pointer로 기존 session task를 자동 rebind해서는 안 된다.
- FR-025 (Conversation Memory Target Integration): Main/summary provider adapter는 LLM Credentials domain이 발급한 opaque `ProviderExecutionCapability` identity/revision과 자기 operation의 deployment version, node invocation, execution admission, provider attempt와 purpose binding을 검증해야 한다. Workflow는 credential principal, permission decision revision 또는 capability scope를 자체 구성하지 않아야 한다.
- FR-026 (Conversation Memory Target Integration): Execution subject, credential principal, billing principal, audit actor와 Conversation Access Grant는 runtime context에서 명시적으로 구분해야 한다. Public grant나 app/deployment owner를 Knowledge subject 또는 audit actor로 승격하지 않아야 한다.


### 1. 실행 편의성

- 테스트 실행은 기존 workflow 실행 경로와 스트리밍 이벤트를 사용한다.
- `node_start` 수신 시 해당 노드는 실행 중 상태로 표시된다.
- `node_finish` 수신 시 해당 노드는 성공 상태, 소요 시간, 토큰 사용량을 표시한다.
- 실행 오류가 노드에 연결된 경우 해당 노드는 실패 상태와 소요 시간을 표시한다.
- 노드별 실행 요약은 테스트 실행 사이드바 안에서 확인할 수 있어야 한다.
- 노드별 실행 요약은 노드명, 실행 상태, 소요 시간, 비용, 토큰 사용량을 포함해야 한다.
- 백엔드 스트리밍 `node_finish` 이벤트는 노드별 `latency_ms`, `total_tokens`, `total_cost` 표준 필드를 제공해야 한다.
- 프론트는 노드별 소요 시간, 비용, 토큰 사용량을 표시할 때 `node_finish`의 표준 필드를 우선 사용해야 한다.
- 워크플로우 테스트가 완료되면 테스트 실행 사이드바의 마지막 영역에 서버 실행 시간, 화면 완료 시간, 전체 비용, 전체 토큰 사용량을 최종 요약으로 표시해야 한다.
- 워크플로우 테스트가 성공하면 테스트 실행 사이드바의 성공 결과 상단에 `최종 응답` 카드를 표시해야 한다.
- 최종 응답 카드는 `workflow_finish.output` 또는 response/answer node 최종 output을 우선 사용하고, 없으면 LLM node output의 `text`, `message`, `answer`, `content` 계열 값을 fallback으로 사용한다.
- 최종 응답이 JSON object이면 raw JSON dump만 노출하지 않고 읽기 쉬운 field preview를 표시해야 한다. 원본 노드별 JSON output은 기존 노드별 실행 결과 상세 영역에 유지한다.
- 서버 실행 시간은 백엔드/엔진이 기록한 workflow run의 실행 시간이다. 가능한 경우 `workflow_runs.duration` 또는 stream 완료 이벤트가 제공하는 workflow-level duration을 사용한다.
- 화면 완료 시간은 프론트가 테스트 실행 시작 상태로 전환된 시각부터 성공/실패 완료 상태로 전환된 시각까지 계산한 시간이다. 이 값에는 네트워크, stream 처리, UI 상태 갱신, 시각적 지연이 포함될 수 있다.
- 최종 요약에서는 서버 실행 시간을 주 지표로, 화면 완료 시간을 보조 지표로 표시해야 한다.
- 테스트 실행 사이드바 요약은 A/B 테스트 구현을 대체하지 않는다. 단일 테스트 실행 결과를 명확히 확인하는 UI이며, 이후 variant 비교 UI의 기반 정보로 사용할 수 있어야 한다.

### 2. 노드 조작 편의성

- 노드 상세 편집 화면은 3패널 구조를 유지한다.
- 사용자는 패널 사이의 resizer를 드래그해 좌우 가로 비율을 조정할 수 있어야 한다.
- 각 패널에는 최소/최대 가로 폭이 있어야 하며, 전체 화면을 벗어나거나 특정 패널이 사용 불가능할 정도로 줄어들면 안 된다.
- 맨 왼쪽 패널을 넓히면 가운데와 오른쪽 패널이 비슷한 비율로 공간을 내주어야 한다.
- 가운데 또는 오른쪽 패널을 넓히는 경우에도 나머지 패널의 최소 폭과 전체 최대 폭 제약을 지켜야 한다.
- 노드 상세 편집 영역은 화면 가로 폭의 최대 90%까지 사용할 수 있어야 하며, 고정 픽셀 최대 폭에 묶이지 않아야 한다.
- 사용자가 패널 폭을 직접 조정하기 전의 기본 레이아웃은 부모 영역 기준 최대 90% 폭을 사용하고, 왼쪽/가운데/오른쪽 패널을 비율 기반으로 배치해야 한다.
- 기본 패널 비율은 왼쪽 28%, 가운데 52%, 오른쪽 20%를 기준으로 한다. 단, 각 패널의 최소/최대 폭 제약이 이 비율보다 우선한다.
- 패널 가로 비율은 현재 편집 세션 안에서 유지되어야 한다. 영구 저장은 이번 범위가 아니다.

### 3. 워크플로우 조작 편의성

- 사용자가 캔버스에서 노드를 선택한 상태로 왼쪽 노드 패널의 노드 항목을 클릭하면, 기본 후보 동작은 선택된 노드 뒤에 새 노드를 추가하는 것이다.
- 왼쪽 노드 패널의 노드 항목은 일반 추가와 `뒤에 추가` 액션을 구분해서 제공해야 한다. 일반 추가는 기존 자유 배치 또는 캔버스 추가 흐름을 유지하고, `뒤에 추가`는 선택된 노드 오른쪽에 새 노드를 배치한 뒤 edge를 자동 생성한다.
- 선택된 노드가 없고 graph에 terminal node가 하나뿐이면 `뒤에 추가`는 해당 terminal node 뒤에 새 노드를 연결할 수 있다. terminal node가 여러 개면 임의로 마지막 노드를 고르지 않고 액션을 비활성화하거나 연결 대상 선택 UI를 요구한다.
- terminal node 개수 계산에서는 sticky note처럼 workflow 실행 graph에 포함되지 않는 보조 노드를 제외한다.
- 새 노드 자동 배치는 전체 graph를 재정렬하지 않고, 기준 노드 오른쪽의 local placement만 수행해야 한다. 사용자가 이미 만든 배치를 망가뜨리면 안 된다.
- condition, switch, loop처럼 여러 handle 또는 분기 의미가 있는 노드 뒤에 추가할 때는 연결할 handle이 명확한 경우에만 자동 연결한다. 애매하면 handle 선택 UI를 요구하거나 `뒤에 추가`를 제한한다.
- 사용자는 캔버스에서 노드를 선택한 뒤 Backspace 또는 Delete 키로 해당 노드를 삭제할 수 있어야 한다.
- 삭제 대상 노드에 들어오는 edge와 나가는 edge가 모두 있으면, 삭제 후 가능한 경우 upstream 노드와 downstream 노드를 자동으로 다시 연결해야 한다.
- 자동 재연결은 기존 edge 방향을 보존한다. 삭제된 노드의 upstream source는 downstream target으로 연결된다.
- 자동 재연결은 유효한 연결 규칙을 통과하는 경우에만 수행한다. 노드 타입, handle, 그래프 검증 규칙상 연결할 수 없으면 재연결하지 않고 삭제만 수행한다.
- 삭제 대상 노드가 여러 upstream 또는 여러 downstream edge를 가진 경우에는 가능한 모든 유효한 upstream/downstream 조합을 재연결하되, 중복 edge는 만들지 않는다.
- 여러 노드를 동시에 삭제하는 경우에는 삭제 후 남는 노드들 사이에서만 유효한 자동 재연결을 계산해야 한다.

### 4. 노드 실행 기록 패널 추가

- 노드 상세 패널에는 `실행 기록` 탭을 제공한다.
- `실행 기록` 탭의 기본 상태에는 `실행 목록 검색`과 `가장 최신 로그 기록 불러오기` 액션을 제공한다.
- `실행 목록 검색`을 누르면 오른쪽 패널 전체가 실행 로그 선택 화면으로 전환되어야 한다.
- 실행 로그 선택 화면은 워크플로우 실행 로그를 최신순으로 표시하고, 상태/검색어 기반 필터를 제공해야 한다.
- 실행 로그 row는 전체 workflow run 요약과 현재 선택된 node_id의 노드 실행 기록 preview를 함께 표시해야 한다.
- 사용자가 실행 로그 row를 선택하면 패널은 다시 `실행 기록` 탭 상세 상태로 돌아와 선택한 실행 로그 안의 현재 노드 input/output, 상태, 소요 시간, 토큰, 비용, 오류 정보를 표시해야 한다.
- `가장 최신 로그 기록 불러오기`는 현재 workflow의 실행 로그 중 현재 node_id 기록이 존재하는 가장 최신 실행 기록을 불러와야 한다.
- 선택된 실행 상세는 workflow run 전체 요약과 현재 노드 기록을 구분해서 표시해야 한다.
- 노드 실행 기록 패널은 현재 노드 설정을 변경하지 않는 read-only 참고 UI다.

## Policies And Edge Cases

### 1. 실행 편의성

- 노드별 토큰 사용량은 `node_finish.total_tokens` 표준 필드를 우선 사용한다. 값이 없으면 `-`로 표시한다.
- 노드별 비용은 `node_finish.total_cost` 표준 필드를 우선 사용한다. 값이 없으면 `-`로 표시한다.
- 노드별 소요 시간은 `node_finish.latency_ms` 표준 필드를 우선 사용한다. 값이 없으면 프론트가 `node_start`와 `node_finish` 이벤트 수신 시각 기준으로 계산한 값을 fallback으로 사용할 수 있다.
- 프론트의 fallback 소요 시간은 백엔드의 영구 실행 로그와 완전히 같은 값이라고 보장하지 않는다.
- 서버 실행 시간과 화면 완료 시간은 서로 다른 지표다. 화면 완료 시간에서 서버 실행 시간을 뺀 값을 순수 UI 처리 시간으로 표현하지 않는다.
- workflow-level 서버 실행 시간이 응답에 없으면 노드별 `latency_ms` 합산값을 서버 실행 시간 fallback으로 표시한다. 노드 latency도 없을 때만 서버 실행 시간은 `-` 또는 `기록 없음`으로 표시한다.
- 실행 권한이 없는 사용자는 테스트 버튼을 실행할 수 없어야 하며, 테스트 실행 사이드바는 이전 결과를 조작 가능한 상태로 보여주지 않는다.
- secret, credential 원문, raw prompt 전체를 테스트 실행 요약에 노출하지 않는다.
- 최종 응답 카드의 preview는 hidden KB id, source title/path/url, credential, raw trace payload 같은 내부 식별자와 민감 payload를 표시하지 않는다.
- 최종 응답이 비어 있으면 빈 상태를 명확히 표시하고, 실패 상태에서는 성공 결과용 최종 응답 카드 대신 실패 메시지를 유지한다.

### 2. 노드 조작 편의성

- 패널 리사이즈는 프론트 UI 상태이며 API나 저장된 workflow graph를 변경하지 않는다.
- 패널 폭 계산은 grid 자체의 현재 폭이 아니라, 노드 상세 편집 영역을 감싸는 부모 영역의 실제 가로 폭을 기준으로 한다.
- 사용자가 아직 직접 드래그하지 않았다면 화면 크기 변경 시 기본 비율을 다시 적용한다. 사용자가 드래그한 뒤에는 현재 편집 세션의 사용자 조정 폭을 유지한다.
- 작은 화면에서는 3패널 리사이즈보다 기존 responsive layout을 우선한다. 최소 폭을 만족할 수 없는 경우 resizer를 숨기거나 기본 비율로 고정한다.
- 드래그 중 텍스트 선택, 캔버스 pan/zoom, 노드 편집 입력이 의도치 않게 발생하지 않아야 한다.

### 3. 워크플로우 조작 편의성

- `뒤에 추가`는 노드 생성, local placement, edge 생성이 하나의 graph edit 동작으로 처리되어야 하며 undo 한 번으로 되돌릴 수 있어야 한다.
- `뒤에 추가` edge 생성은 일반 edge 연결과 같은 validation 경로를 사용해야 한다. 검증에 실패하면 노드와 edge를 모두 만들지 않는다.
- 자동 배치 위치는 선택된 노드 오른쪽을 기본으로 하되, 기존 노드와 겹치면 같은 흐름을 해치지 않는 범위에서 아래 또는 오른쪽으로 밀어 배치한다.
- `뒤에 추가`는 사용자 편의를 위한 graph edit 동작이며 API를 호출하지 않는다. 저장은 기존 workflow draft sync 경로를 따른다.
- 키보드 삭제는 캔버스가 shortcut scope일 때만 동작한다. 입력창, textarea, select, contenteditable 내부에서는 Backspace/Delete가 노드 삭제로 해석되면 안 된다.
- 레이아웃 최적화는 하단 툴바의 레이아웃 최적화 버튼으로 실행할 수 있어야 한다.
- 시작 트리거 노드처럼 삭제가 제한된 노드가 있다면 기존 삭제 가능 정책을 우선한다.
- 자동 재연결은 사용자 편의를 위한 graph edit 동작이며 API를 호출하지 않는다. 저장은 기존 workflow draft sync 경로를 따른다.

### 4. 노드 실행 기록 패널 추가

- 노드 실행 기록은 workflow run, node run, trace payload, LLM usage log에 저장된 기존 실행 데이터를 읽어 표시한다.
- secret, credential 원문, raw prompt 전체, raw payload 중 정책상 비공개 값은 패널에 노출하지 않는다.
- 실행 목록은 기본적으로 최신순으로 표시한다. 많은 실행 로그가 있는 경우 초기 로드는 제한된 개수만 수행하고 `더 보기`로 확장한다.
- 현재 node_id 기록이 없는 workflow run은 목록에서 제외하거나, 표시하더라도 `이 실행에서 현재 노드 기록 없음`으로 명확히 구분한다.
- 최신 기록 불러오기는 workflow의 최신 run 1개가 아니라, 현재 node_id 기록이 존재하는 최신 run을 대상으로 한다.

### 5. 교차 도메인 실행 경계

- 생성된 workflow나 Agent Builder가 만든 workflow도 일반 workflow와 동일한 organization scope, RBAC, audit, trace 정책을 따른다.
- Workflow 실행 권한, LLM credential `use`, connector/connection 사용 권한, Knowledge KB/source ACL 권한은 서로를 대체하지 않는다.
- Workflow-node 순환 참조, nesting depth 초과, target app/deployment unavailable 같은 복구 불가능한 graph 설정 오류는 retry 가능한 일시 장애가 아니다. Celery task는 이러한 non-retryable runtime error를 즉시 실패로 보존해야 한다.
- Workflow runtime HTTP/GitHub node의 전체 outbound egress policy는 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)의 Knowledge source collection egress boundary와 별도 gate다. Mail IMAP 연결은 [ADR-0031](../../decisions/ADR-0031-mail-credential-reference-boundary.md)의 제한된 egress gate를 적용한다.

### Mail Credential Reference

- Mail node graph는 organization-scoped Mail credential의 opaque `credential_id`만 저장한다. Email, password, token, ciphertext, provider endpoint를 graph에 직접 저장하지 않는다.
- Workflow 저장 경계는 최상위 graph와 모든 중첩 `subGraph.nodes`의 inline Mail secret field를 거부하고, reference가 있으면 active organization, active 상태와 저장 요청자의 `use` 권한을 검증한다. `displayNumber`와 `visibleProperties`는 제한된 UI metadata만 허용한다.
- Agent Builder가 만든 Mail node는 `credential_id=null`, `configuration_state=unresolved`로 preview와 draft 저장이 가능하지만 실행 준비 상태로 간주하지 않는다. Deployment snapshot 생성과 기존 deployment 활성화는 최상위와 중첩 Mail node 모두 유효한 credential reference가 있어야 한다.
- 인증 test/deployment run은 명시 user execution subject와 canonical organization을 runtime resolver에 전달한다. Resolver는 provider 연결 직전에 scope, active 상태, `use` 권한, egress target을 재검증한다. Public/schedule run은 App/workflow owner를 대체 주체로 사용하지 않으며, service account 또는 assigned operator 정책이 없으면 Mail 실행을 차단한다.
- Credential이 없거나 revoke됐거나 권한이 회수된 경우 Mail provider 연결 전에 safe error로 fail-closed한다. Legacy inline password graph는 호환 fallback 없이 거부한다.
- Mail node의 `processing_mode` 기본값은 기존 호환을 위한 `search_only`다. `durable` mode는 workflow/source node scoped processing row를 생성하고 opaque `processing_ref`를 출력한다.
- 단일 Gmail Draft node에 직접 연결하는 durable Mail node는 `max_results=1`이어야 하며 최상위 `processing_ref`를 제공한다. 여러 메일 결과는 명시적인 반복 처리 계약 없이 단일 Draft selector에 연결하지 않는다.
- Durable mode에서는 Mail node의 `mark_as_read=true`를 금지한다. `mailAcknowledgeNode`가 required effect의 durable success를 검증한 뒤에만 원본 메시지를 처리 완료한다.
- Gmail 답장 초안은 별도 `gmailDraftNode`가 수행한다. Node는 `credential_id`, `processing_ref` selector, reply body selector만 저장하고 provider id, token, MIME 또는 recipient override를 graph에 저장하지 않는다.
- Gmail Draft effect가 `outcome_unknown`이면 Workflow/Celery generic retry가 provider create를 자동 재호출하지 않아야 한다.
- `mailAcknowledgeNode`는 graph dependency로 연결된 processing/effect reference를 서버에서 검증하며 client 제공 success boolean을 신뢰하지 않는다.
- Gmail Draft 또는 Mail Acknowledge가 포함된 graph는 source Mail node가 durable mode인지와 required selector 연결을 save/deploy 경계에서 검증한다.
- 편집 중 unresolved Draft/Acknowledge node의 빈 selector는 저장할 수 있지만 save/deploy 경계에서는 source/effect node 유형, 출력 key, 선행 graph path, source/Draft credential 일치와 Gmail OAuth auth type을 검증한다. Workflow Engine은 legacy snapshot 실행 시 selector schema와 DB processing/deployment/credential provenance를 다시 검증하여 fail-closed한다.
- 기존 활성 Draft claim을 발견한 중복 실행은 claim을 획득한 것으로 간주하지 않으며 Gmail provider를 다시 호출하지 않는다.
- OAuth Gmail Mail node와 terminal acknowledgement는 `gmail.modify` 기반 고정 Gmail REST adapter를 사용한다. OAuth credential을 IMAP XOAUTH2로 연결하지 않으며 app password/password credential만 제한된 IMAP 경로를 사용한다.
- Gmail REST provider message id는 암호화된 processing source reference에만 저장하고 node output, API, audit, trace, log에는 노출하지 않는다.
- Mail body/subject/recipient와 생성 답장 본문은 runtime graph 데이터로만 전달한다. Durable node trace는 Mail result와 Gmail effect input을 node-aware safe summary로 치환한 뒤 일반 trace redaction/retention 정책을 적용한다.
- RAG를 포함한 workflow 비교 실행이나 A/B 실행도 로그인 interactive 실행이면 동일한 execution subject와 Knowledge permission/source ACL gate를 사용하고, subject가 없으면 anonymous public-only gate를 사용한다.
- 배포 preflight에서 client-supplied audience hint는 preview UI용이며, create/activation 경로는 deployment type과 실행 endpoint에서 audience를 서버가 다시 파생한다.
- Private KB를 자동 실행에서 사용하려면 별도 service account 또는 assigned operator 정책이 필요하다. 이 정책이 없으면 workflow owner, deployment owner, app creator 권한으로 fallback하지 않는다.
- Anonymous public-only gate에서 source-managed KB는 collection public visibility와 별도 source/connector public exposure approval을 모두 통과해야 한다 ([ADR-0020](../../decisions/ADR-0020-knowledge-mcp-incremental-sync-boundary.md)).
- 별도 RAG node를 만들지 않는다. Knowledge retrieval은 LLM node의 RAG option/runtime path로 연결한다 ([ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)).
- Skill이 workflow generation이나 실행 시점 RAG procedure를 안내하더라도, skill은 data access 권한을 부여하지 않는다. 실제 evidence retrieval은 Knowledge permission helper 결과로만 수행한다.
- Code-bearing skill은 별도 sandbox/approval/egress/resource-cap gate 전까지 workflow runtime에서 실행하지 않는다.
- Workflow Playground가 별도 실험 공간인지 canvas와 통합되는지, draft/unpublished skill을 테스트 실행에 사용할 수 있는지는 아직 확정하지 않는다.
- Missing execution subject는 anonymous public-only로 처리한다. Ambiguous execution subject, suspended/removed membership, inactive service account는 private retrieval fail-closed로 처리한다.


## Open Questions

Open Question 중요도는 다음 3단계로 나눈다.

- `Priority 1`: 현재 기능 구현 또는 데모 핵심 흐름을 막는 결정이다. 구현 전에 먼저 정해야 한다.
- `Priority 2`: 데모 안정성과 후속 구현 품질에 영향을 준다. 현재 구현은 fallback으로 진행할 수 있지만 PR 전후로 정리해야 한다.
- `Priority 3`: 장기 사용성, 성능, 확장성 결정이다. 현재 구현을 막지는 않으며 후속 이슈로 분리할 수 있다.

| Priority | 영역 | Question | 왜 중요한가 | 결정 전 임시 처리 |
| --- | --- | --- | --- | --- |
| 1 | 실행 편의성 | 백엔드 스트리밍 완료 이벤트에 workflow-level `run_id`, `duration`, `total_tokens`, `total_cost`를 표준 필드로 포함할지 여부 | 서버 실행 시간과 비용/토큰을 테스트 실행 사이드바에서 정확히 표시하려면 완료 이벤트 또는 후속 조회 기준이 필요하다. | 완료 이벤트에 값이 없으면 서버 실행 시간은 노드별 `latency_ms` 합산으로 fallback하고, 비용/토큰도 노드별 합산으로 fallback한다. |
| 1 | 워크플로우 조작 편의성 | branching/condition/loop 같은 특수 노드 삭제 시 자동 재연결을 어디까지 허용할지 여부 | 잘못 재연결하면 workflow 의미가 바뀔 수 있다. 삭제 shortcut의 안전성에 직접 영향이 있다. | 기존 연결 검증을 통과하는 단순 upstream/downstream 조합만 재연결하고, 애매한 특수 노드는 삭제만 수행한다. |
| 2 | 노드 실행 기록 패널 추가 | input/output full payload 표시 범위와 redaction 기준을 어디까지 프론트에서 보완할지 여부 | 실행 기록 패널은 trace payload와 LLM usage를 보여줄 수 있어 secret/raw prompt 노출 위험이 있다. | Gateway/API 응답 정책을 우선하고, 프론트는 allowlist 기반 preview/detail 렌더링만 허용한다. |
| 2 | 노드 실행 기록 패널 추가 | node_id 기반 실행 기록 API의 cursor 기준을 `started_at + run_id`로 둘지, 별도 node_run id 기준으로 둘지 여부 | 실행 로그가 많아질 때 중복/누락 없는 pagination과 최신 기록 선택에 영향을 준다. | 초기 구현은 제한된 최신 page와 명확한 정렬 기준을 사용하고, 대량 조회는 후속 API에서 cursor를 확정한다. |
| 2 | 노드 실행 기록 패널 추가 | input/output 검색을 preview 문자열 기준으로 제한할지, redaction-safe full payload 검색까지 허용할지 여부 | 검색 품질과 보안 경계가 충돌할 수 있다. | 우선 preview 문자열 검색으로 제한한다. |
| 3 | 실행 편의성 | A/B 비교 실행 결과를 테스트 실행 사이드바 안에서 확장할지, 별도 비교 패널로 분리할지 여부 | 현재 단일 테스트 실행 UX를 막지는 않지만, 이후 비용/품질 비교 UI 구조에 영향을 준다. | 현재 TestSidebar는 단일 실행 결과만 다루고 A/B 비교 UI는 별도 후속 설계로 둔다. |
| 3 | 노드 조작 편의성 | 패널 비율을 사용자별 preference로 영구 저장할지 여부 | 반복 작업 편의성에는 도움이 되지만 현재 리사이즈 기능 구현을 막지는 않는다. | 현재 편집 세션 안에서만 유지하고 저장하지 않는다. |

후속 확장 open question:
- Service account의 데이터 접근 범위와 승인 절차를 Auth/RBAC에서 어떤 table과 helper로 표현할지.
- Schedule/webhook/API trigger에서 private KB access가 필요할 때 service account/assigned operator `execution_subject` resolution reason enum과 audit action 이름을 어떻게 둘지. Conversation Access Grant나 credential principal은 후보가 아니다.
- Workflow runtime outbound egress guard를 Knowledge source egress guard와 통합할지 별도 runtime ADR로 둘지.
- Skill execution을 runtime node로 허용할지, 허용한다면 sandbox와 approval 경계를 어디에 둘지.
- Workflow Playground, canvas 작업 공간/사용 공간, 배포 승인 요청에서 skill binding을 어떻게 표현하고 검토할지.
