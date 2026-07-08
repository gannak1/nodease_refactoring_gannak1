# Agent Builder Component Spec

Status: Draft

## 화면 구성

Agent Builder는 Workflow Editor 안에서 동작한다.

- 기본 상태: 우측 하단 고정 launcher button
- 열림 상태: chatbot panel
- canvas: 기존 Workflow Editor canvas를 유지
- preview summary: chatbot panel 안에서 draft summary와 `도안 생성 미리보기` action 표시
- Preview Mode: Workflow Editor canvas에서 agent draft graph를 읽기 전용 preview graph로 렌더링
- Node Detail Panel: Preview Mode에서 선택한 node의 내부 설정을 읽기 전용으로 표시

Agent Builder panel은 workflow를 직접 실행하지 않는다. 사용자가 Preview Mode에서 `적용 및 저장`을 선택하면 [ADR-0019](../../decisions/ADR-0019-agent-builder-preview-apply-save-boundary.md)의 경계에 따라 backend 재검사를 통과한 경우에만 workflow graph 저장으로 이어진다.

## Frontend Components

| Component | Responsibility |
| --- | --- |
| `AgentBuilderLauncher` | 우측 하단 고정 entry point |
| `AgentBuilderChatPanel` | 대화 목록, 입력창, pending 상태, cancel control |
| `AgentBuilderMessageList` | 사용자 메시지, agent response, clarification, warning 표시 |
| `DraftPreviewSummary` | chatbot panel 안에서 생성/변경될 workflow 요약과 `도안 생성 미리보기` action 표시 |
| `PreviewModeController` | actual editor graph와 preview graph를 분리하고 Preview Mode 진입/종료 제어 |
| `PreviewCanvasRenderer` | agent draft graph를 실제 editor graph와 분리된 읽기 전용 canvas로 렌더링. Answer/Output 계열 node card는 output variable 목록을 카드 본문에 직접 렌더링하지 않고 구조 요약만 표시 |
| `PreviewNodeDetailPanel` | preview node의 type, 주요 설정, KB/Slack binding, credential 참조 상태, input/output mapping, validation 상태를 읽기 전용으로 표시. Preview Mode에서는 canvas 왼쪽 영역에 배치해 우측 Agent Builder chat panel과 겹치지 않게 함 |
| `DraftApplyActionBar` | Preview Mode 안내, `적용 및 저장`, `취소`, 저장 전 safety notice 표시. MVP에서는 별도 canvas action bar 또는 Preview Mode 동안 닫을 수 없는 Agent Builder panel 안의 action 영역으로 구현할 수 있다 |
| `DraftApplyStateGuard` | unsaved editor change, stale warning, apply/save processing 중 중복 action 방지 |
| `DraftApplyResultPresenter` | 저장 성공, 저장 차단, 저장 실패, 취소 결과를 한국어로 표시하고 Preview Mode 유지/종료를 제어 |
| `KnowledgeBaseSelectionSurface` | LLM node Knowledge Base picker와 Agent Builder KB 후보 표시에서 권한 확인된 ready 후보, legacy retrieval-visible 후보, indexing/not-ready 후보를 구분해 표시. indexing/not-ready 후보는 selectable ready KB로 취급하지 않지만 조용히 숨기지 않고 safe warning 또는 disabled option으로 표시 |

Preview Mode component는 preview graph를 actual editor graph에 merge하지 않는다. `취소`는 server-side apply/save audit에 canceled event를 기록한 뒤 preview graph를 닫고 Preview Mode를 종료한다. 이 동작은 draft metadata를 terminal 폐기하지 않으며, 원복 로직에 의존하지 않아야 한다.

`PreviewNodeDetailPanel`은 편집 가능한 input, credential picker, KB picker, node delete, edge edit action을 제공하지 않는다. 설정 변경은 채팅 후속 요청으로 새 draft를 생성하거나 기존 draft를 수정하는 방식으로 수행한다.

Preview Mode의 `PreviewNodeDetailPanel`은 우측 Agent Builder chat panel, `적용 및 저장`, `취소` action과 겹치지 않아야 한다. 기본 배치는 canvas 왼쪽 drawer 또는 왼쪽 side panel이며, 좁은 viewport에서는 responsive layout으로 node detail과 chat panel 둘 중 하나가 다른 하나를 가리지 않게 해야 한다.

Answer/Output 계열 node의 output variable 목록, value selector, input/output mapping은 canvas card 본문이 아니라 `PreviewNodeDetailPanel` 또는 기존 node 설정 패널의 상세 표면에서 확인한다. Canvas card에 긴 목록을 직접 렌더링해 node border 밖으로 넘치게 하거나 preview graph 구조 파악을 방해해서는 안 된다.

## Backend Components

| Component | Responsibility |
| --- | --- |
| `RequestContextResolver` | 인증 사용자, active organization, workflow/app scope, 권한 context 확정 |
| `ConversationSessionService` | server-issued chat session, redaction된 사용자 message summary와 assistant response로 구성된 최근 메시지, pending request, cancel state 관리. Session은 인증 사용자, active organization, workflow/app scope, agent panel lifecycle에 묶인다 |
| `StructuredRequestBuilder` | 자연어 의미 후보를 안전한 `StructuredRequest`로 정규화 |
| `WorkflowContextSnapshotBuilder` | graph, selected node, selected edge, existing node/edge summary 생성 |
| `TargetResolver` | 기존 workflow 수정 target 해석 |
| `CapabilityCatalogProvider` | Agent Builder가 사용할 수 있는 capability allowlist 제공 |
| `KnowledgeRecommendationAdapterClient` | KB pending resolution을 Knowledge adapter request로 변환 |
| `WorkflowDraftBuilder` | `StructuredRequest`와 resolver 결과를 workflow draft로 변환 |
| `WorkflowDraftValidator` | schema, permission, side effect, missing config 검증 |
| `DraftLayoutOptimizer` | 기존 Workflow Editor 레이아웃 최적화 UI 버튼과 동등한 deterministic layout 로직을 apply/save 직전 draft graph에 적용하고, 저장될 node position을 확정 |
| `WorkflowDraftApplyService` | draft metadata 조회, 권한 재확인, stale check, validation 재확인, workflow graph 저장, apply/save audit 기록. 저장 성공은 audit 기록 성공을 전제로 한다. |

`WorkflowDraftApplyService`는 `base_graph_hash`와 workflow `version` 또는 `updated_at`을 최신 graph/context와 비교한다. Graph hash는 workflow 의미에 영향을 주는 node id, node type, node data/config, edge source/target/handle을 기준으로 계산하고 viewport, selection, panel state, preview state, timestamp, UI-only metadata, note/memo node와 해당 note/memo node에만 연결된 non-runtime edge는 제외한다.

Apply/save가 성공하면 backend는 저장된 workflow id와 최신 workflow version 또는 updated_at을 반환한다. 이 성공 응답은 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 상태는 허용하지 않는다. Frontend는 이 결과를 받은 뒤 Preview Mode를 종료하고 저장된 최신 workflow graph를 표시한다. 새 workflow draft 생성이 성공하면 새 workflow editor로 이동하거나 현재 editor context를 새 workflow로 전환한다.

Apply/save 저장 경계는 draft graph를 저장하기 전에 `DraftLayoutOptimizer`를 실행해야 한다. 이 로직은 사용자가 기존 Workflow Editor에서 누르는 레이아웃 최적화 UI 버튼과 동등한 배치 결과를 만들어야 하며, 저장된 graph의 node position과 저장 성공 후 editor에 표시되는 node position이 이 결과와 일치해야 한다. 자동 레이아웃은 UI-only viewport, selection, panel state를 저장 의미로 만들지 않고, workflow 실행이나 외부 side effect를 발생시키지 않는다.

Frontend는 저장 성공 응답만으로 local `previewGraph`를 actual editor graph에 직접 승격하지 않는다. 저장된 workflow id를 기준으로 서버의 최신 workflow graph를 다시 조회하거나, 서버가 반환한 동등한 최신 저장 graph로 reconcile한 뒤 editor state를 갱신한다.

Apply/save가 차단되거나 실패하면 Preview Mode를 유지하고 `actualEditorGraph`를 변경하지 않는다. Backend response는 `blocked`에 `block_reason`, `failed`에 `failure_reason`을 사용해 차단과 저장 시도 실패 또는 apply/save audit 기록 실패를 구분한다. Frontend는 block reason 또는 failure reason을 표시하고, 사용자가 재시도, 취소, 또는 채팅 후속 요청으로 draft 수정을 선택할 수 있게 한다.

## Knowledge Adapter Integration

Agent Builder는 Knowledge DB를 직접 조회하지 않는다.

1. `StructuredRequestBuilder`가 KB 후보 목록 없이 `knowledge_requirements`와 `pending_resolution`을 만든다.
2. `KnowledgeRecommendationAdapterClient`가 KB pending resolution 단위로 adapter request를 만든다.
3. Knowledge side의 `KnowledgeCandidateResolver`가 Builder actor와 server-resolved context 기준으로 authorized safe candidate set을 만든다.
4. Adapter는 structured knowledge requirement, safe workflow context summary, HTTP boundary의 server-issued reference 또는 같은 backend 내부 service call의 authorized safe candidate set을 매칭하고, MVP에서 keyword/metadata deterministic ranking을 수행한다.
5. Agent Builder는 결과를 resolved pending slot, clarification, validation failure 중 하나로 반영한다.

Adapter result는 recommendation item마다 score, confidence, reason category, threshold result를 포함해야 한다. Agent Builder는 이 값을 기준으로 후보 1개 high confidence는 resolved 처리하고, 점수 근접 또는 후보 다중 상황은 clarification으로 전환한다.

KB clarification UI는 safe candidate handle과 safe label/confidence/score/reason category만 표시한다. 사용자가 후보를 선택하면 frontend는 raw KB id나 safe metadata 전체를 다시 보내지 않고 candidate safe handle과 선택적 resolution/requirement reference만 제출한다. Backend는 원 clarification option과 같은 session/context에서 온 선택인지 검증하고, apply/save 직전 runtime KB reference materialization을 다시 수행한다.

MBA-145 MVP에서는 Knowledge Skill body/checklist를 prompt context로 직접 로드하지 않는다. Agent Builder가 제안하는 RAG option은 ADR-0017 기본값과 safe candidate 설명 범위로 제한하고, Knowledge Skill 직접 사용과 고급 RAG option tuning은 후속 기능으로 둔다.

## UI States

| State | Behavior |
| --- | --- |
| `idle` | launcher 표시, panel 닫힘 가능 |
| `open` | panel 열림, 입력 가능 |
| `pending` | 요청 처리 중, submit 중복 방지, cancel 가능 |
| `clarification_required` | 질문 표시, 사용자가 후속 답변 가능 |
| `draft_ready` | chatbot panel에 draft summary와 `도안 생성 미리보기` action 표시 |
| `preview_mode` | actual graph와 분리된 preview graph를 읽기 전용으로 표시 |
| `validation_failed` | 실패 사유와 필요한 조치 표시 |
| `apply_save_processing` | `적용 및 저장` 처리 중, 중복 action 방지 |
| `apply_saved` | workflow graph 저장과 apply/save audit 기록 완료, 실행은 별도 action 필요 |
| `apply_blocked` | metadata/permission/stale/validation 문제로 저장 차단 |
| `apply_failed` | 저장 시도 실패, preview 유지, 재시도 또는 취소 가능 |
| `canceled` | late result가 preview/apply로 이어지지 않음 |

## Interaction Rules

- Refresh 후에는 redaction된 사용자 message summary와 assistant response를 포함한 최근 대화, pending request 상태를 복구한다.
- Pending request가 있으면 새 submit은 막고 cancel은 허용한다.
- Cancel 이후 도착한 결과는 draft preview, Preview Mode, apply/save로 이어질 수 없다.
- 선택된 edge는 "이 연결 사이에" 같은 자연어 edge 문맥에서만 target hint로 사용하고, 권한/scope 판단에는 사용하지 않는다.
- Validation을 통과하지 않은 draft에는 `도안 생성 미리보기` 또는 `적용 및 저장` action을 표시하지 않는다.
- Preview Mode 안내는 "미리보기 모드이며 아직 저장되지 않았다"는 상태를 명확히 표시한다. `적용 및 저장`과 `취소` action이 Agent Builder panel 안에 있다면 Preview Mode 동안 panel close를 차단해 action 경로가 사라지지 않게 한다.
- `도안 생성 미리보기` audit 기록이 실패하면 Preview Mode에 진입하지 않고 재시도 안내를 표시한다.
- Preview Mode에서 actual editor graph와 preview graph는 별도 state로 유지한다.
- MVP에서는 editor에 저장되지 않은 변경이 있으면 Agent Builder draft 생성, Preview Mode 진입, 또는 `적용 및 저장`을 차단하고 먼저 저장 또는 폐기를 요구한다.
- MVP message request는 raw client graph snapshot을 보내지 않는다. Client는 selected node/edge hint만 보내며, apply/save 단계의 preview 확인과 stale guard에는 semantic graph hash만 사용한다. Hash 계산이 불가능하면 raw graph payload fallback을 보내지 않고 apply/save를 차단한다.
- 후속 확장에서는 검증 가능한 client graph snapshot을 draft base로 삼는 정책을 도입할 수 있으나, 그 전까지 unsaved editor graph를 agent draft base로 자동 포함하지 않는다.
- `적용 및 저장`은 workflow graph 저장까지 수행하지만 workflow 실행, Knowledge Base retrieval, Slack 전송, credential 사용/변경, 외부 시스템 변경을 수행하지 않는다.
- `적용 및 저장` 성공 시 Preview Mode를 종료하고 editor는 저장된 최신 workflow graph를 표시한다. 이 성공 상태는 backend 저장과 apply/save audit 기록 성공을 모두 통과한 경우에만 사용한다.
- `적용 및 저장` 차단 또는 실패 시 Preview Mode를 유지하고 actual editor graph를 변경하지 않는다.
- Stale check는 backend가 base graph hash와 workflow version/updated_at을 최신 값과 비교해 수행한다. Frontend의 stale warning은 사용자 안내일 뿐 최종 판정이 아니다.
- Apply/save audit은 draft preview 생성, Preview Mode 진입, 적용 및 저장 요청, 저장 차단, 저장 성공, 저장 실패, 취소 event를 구분한다. Audit payload는 safe metadata만 포함한다.

## Accessibility

- Launcher와 panel은 keyboard focus 이동이 가능해야 한다.
- Pending, warning, validation failure는 screen reader가 읽을 수 있는 status text를 제공한다.
- `적용 및 저장`과 `취소`는 명확한 button label을 사용한다.
