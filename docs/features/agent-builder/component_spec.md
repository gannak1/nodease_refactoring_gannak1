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
| `AgentBuilderIntentModelSelector` | Header에서 active organization의 권한 확인 model/credential 조합을 provider별로 표시하고 통합 추천 정책의 첫 option을 내부 intent planner 초기값으로 사용. 사용자가 다른 option으로 변경할 수 있으며 선택 ID는 message request에만 포함하고 저장하거나 generated LLM node로 복사하지 않음. 선택 메뉴는 chat panel 가로 폭의 약 절반을 사용하고 모델 행 약 5개 높이 이후에는 내부 스크롤로 나머지 option을 표시 |
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
| `LLMIntentExtractor` | redaction된 사용자 요청, safe workflow context, `PreIntentKnowledgeContextProvider`의 bounded safe KB 후보를 명시적으로 선택되고 요청마다 재검증된 permission-aware LLM runtime에 전달하고 schema-validated 의미 후보를 반환. Raw graph, node/edge id, credential, raw provider response를 구조화 결과에 포함하지 않음 |
| `PreIntentKnowledgeContextProvider` | 기존 Knowledge candidate resolver와 metadata ranker로 권한/readiness를 통과한 후보를 조회하고 상위 20개의 opaque handle, safe label/topics/description, runtime availability, bounded relevance만 Intent LLM에 투영 |
| `LLMService.get_agent_answer_options()` | Active organization의 유효한 credential, active chat model, model과 credential의 같은 provider, verified relation, 사용자 credential `use` permission을 결합해 DB 자격 후보를 조회 |
| `LLMService._order_agent_builder_options()` | 같은 model/credential의 중복 관계에서 가장 낮은 relation priority 하나만 남기고 safe 정책 입력으로 변환한 뒤 공통 추천 정책으로 정렬 |
| `model_recommendation_policy.sort_model_candidates()` | DB와 framework에 의존하지 않고 provider별 명시적 정책표로 세대와 `general/mini/nano/pro` tier를 해석해 `openai`, `anthropic`, `google` provider 순서, provider별 최신 세대, 같은 세대 tier, 같은 tier의 기본형/날짜·release snapshot/`preview`/`latest` 순서와 안정적 tie-break를 계산. 특수 목적은 정규화한 model ID의 완전한 token·명시된 연속 token 또는 provider별 전체 일치 규칙으로만 판정하고 단순 부분 문자열 일치는 사용하지 않음. 특수 목적 모델은 제외하고 이름을 해석하지 못한 verified chat 모델은 provider의 해석 가능한 모델 뒤에 안정적으로 유지하며 원래 model ID는 변경하지 않음 |
| `AgentBuilderService._recommended_draft_model_id()` | `LLMService.get_agent_builder_draft_model_recommendation()`이 같은 권한 후보를 공통 정책으로 정렬해 반환한 첫 model id를 generated LLM node 기본값으로 적용. Header의 사용자 선택은 복사하지 않으며 credential은 graph에 저장하지 않고 후보가 없으면 unresolved 설정 issue 반환. 기존 node와 적용 및 저장 후 사용자가 바꾼 model은 덮어쓰지 않음 |
| `StructuredRequestBuilder` | 자연어 의미 후보를 안전한 `StructuredRequest`로 정규화 |
| `WorkflowContextSnapshotBuilder` | graph, selected node, selected edge, existing node/edge summary 생성 |
| `TargetResolver` | 기존 workflow 수정 target 해석 |
| `CapabilityCatalogProvider` | ADR-0024/0026의 공통 Workflow Node Capability Catalog v2를 읽고 `implemented=true`, `agent_builder_supported=true`인 node/capability allowlist, 제품 가용성, side effect/필수 설정, 연결 정책 제공 |
| `IntentSemanticValidator` | Schema-valid LLM 의미 후보의 request/draft mode, workflow context, 신규 capability, target/placement와 KB candidate handle allowlist invariant를 검증하고 safe-code 1회 repair 경계를 제공 |
| `KnowledgeRecommendationAdapterClient` | KB pending resolution을 Knowledge adapter request로 변환 |
| `WorkflowDraftBuilder` | `StructuredRequest`와 resolver 결과를 workflow draft로 변환하고, LLM node에는 `DraftLLMModelRecommender`의 safe model id만 적용 |
| `WorkflowDraftValidator` | schema, permission, side effect, missing config와 catalog 기반 complete-graph 연결 정책을 preview/apply-save에서 동일하게 검증 |
| `DraftLayoutOptimizer` | 기존 Workflow Editor 레이아웃 최적화 UI 버튼과 동등한 deterministic layout 로직을 apply/save 직전 draft graph에 적용하고, 저장될 node position을 확정 |
| `WorkflowDraftApplyService` | draft metadata 조회, 권한 재확인, stale check, validation 재확인, workflow graph 저장, apply/save audit 기록. 저장 성공은 audit 기록 성공을 전제로 한다. |

`WorkflowDraftApplyService`는 `base_graph_hash`와 workflow `version` 또는 `updated_at`을 최신 graph/context와 비교한다. Graph hash는 workflow 의미에 영향을 주는 node id, node type, node data/config, edge source/target/handle을 기준으로 계산하고 viewport, selection, panel state, preview state, timestamp, UI-only metadata, note/memo node와 해당 note/memo node에만 연결된 non-runtime edge는 제외한다.

`StructuredRequestBuilder`는 수정 문장에서 기존 target과 신규 step을 분리해
`edit_operations`를 만든다. `TargetResolver`는 server가 읽은 현재 저장 graph에서 자연어
node type/role 후보를 찾고, 자연어 target을 우선한 뒤 selected node/edge를 후보 제한 또는
tie-break hint로만 사용한다. `WorkflowDraftBuilder`는 신규 workflow용 full-chain 생성과
기존 workflow용 edit operation 적용 경로를 분리하며, 후자는 신규 entry/answer wrapper를
만들지 않고 resolved edge에 요청된 신규 step만 splice한다.

운영 message 처리 경로의 자연어 해석은 `LLMIntentExtractor`가 담당한다. Extractor는
발화 의도, 새 workflow와 기존 workflow 수정, 절 순서, 신규 capability, 기존 target,
before/after/between placement, GitHub read/write 의도를 JSON 구조로 분리한다. Capability
이름과 설명은 공통 catalog 기준 bounded guide를 사용하지만 자연어 활용형을 정규식 목록으로
계속 추가하지 않는다.

`StructuredRequestBuilder`는 LLM 결과를 그대로 graph로 만들지 않는다. Catalog 밖 capability,
request type과 draft mode 불일치, 잘못된 target reference는 fail-closed 처리하고, step id,
dependency, Knowledge pending slot, external configuration warning과 risk flag를 결정론적으로 다시
계산한다. `TargetResolver`는 safe target query와 capability role을 server-loaded graph에 적용하며,
동일한 `githubNode`가 여러 개이면 `get_pr`와 `comment_pr` role을 node type보다 우선한다.
LLM 호출 또는 schema validation 실패 시 deterministic 자연어 parser로 silent fallback하지 않는다.

Apply/save가 성공하면 backend는 저장된 workflow id와 최신 workflow version 또는 updated_at을 반환한다. 이 성공 응답은 apply/save audit 기록 성공을 전제로 하며, `audit_recorded=false`인 저장 성공 상태는 허용하지 않는다. Frontend는 이 결과를 받은 뒤 Preview Mode를 종료하고 저장된 최신 workflow graph를 표시한다. 새 workflow draft 생성이 성공하면 새 workflow editor로 이동하거나 현재 editor context를 새 workflow로 전환한다.

Apply/save 저장 경계는 draft graph를 저장하기 전에 `DraftLayoutOptimizer`를 실행해야 한다. 이 로직은 사용자가 기존 Workflow Editor에서 누르는 레이아웃 최적화 UI 버튼과 동등한 배치 결과를 만들어야 하며, 저장된 graph의 node position과 저장 성공 후 editor에 표시되는 node position이 이 결과와 일치해야 한다. 자동 레이아웃은 UI-only viewport, selection, panel state를 저장 의미로 만들지 않고, workflow 실행이나 외부 side effect를 발생시키지 않는다.

Frontend는 저장 성공 응답만으로 local `previewGraph`를 actual editor graph에 직접 승격하지 않는다. 저장된 workflow id를 기준으로 서버의 최신 workflow graph를 다시 조회하거나, 서버가 반환한 동등한 최신 저장 graph로 reconcile한 뒤 editor state를 갱신한다.

Apply/save가 차단되거나 실패하면 Preview Mode를 유지하고 `actualEditorGraph`를 변경하지 않는다. Backend response는 `blocked`에 `block_reason`, `failed`에 `failure_reason`을 사용해 차단과 저장 시도 실패 또는 apply/save audit 기록 실패를 구분한다. Frontend는 block reason 또는 failure reason을 표시하고, 사용자가 재시도, 취소, 또는 채팅 후속 요청으로 draft 수정을 선택할 수 있게 한다.

`new_workflow` apply/save에서 Agent Builder application service는 draft에 저장된 expected App primary를 사용해 optimistic concurrency를 확인한다. Apply 시 App row를 잠그고 현재 primary가 달라졌거나 active deployment pointer가 있으면 새 Workflow를 생성하기 전에 차단한다. 전환 가능한 경우 기존 primary의 organization-scoped user/team Workflow permission을 새 Workflow로 승계하고 actor manager 권한, App primary pointer, session rebind, audit를 같은 transaction에서 확정한다. 이 guard는 apply 시점의 active pointer 충돌을 막는 즉시 안전장치이며, inactive 과거 Deployment의 원본 Workflow provenance와 재활성화 compatibility를 추론하지 않는다. Immutable Deployment-to-Workflow provenance, Deployment 생성·활성화와 primary 전환의 공통 lifecycle 직렬화, App 전용 ACL 구조는 별도 lifecycle 컴포넌트 책임이다.

## Knowledge Adapter Integration

Agent Builder는 Knowledge DB를 직접 조회하지 않는다.

1. `StructuredRequestBuilder`가 KB 후보 목록 없이 `knowledge_requirements`와 `pending_resolution`을 만든다.
2. `KnowledgeRecommendationAdapterClient`가 KB pending resolution 단위로 adapter request를 만든다.
3. Knowledge side의 `KnowledgeCandidateResolver`가 Builder actor와 server-resolved context 기준으로 authorized safe candidate set을 만든다.
4. Adapter는 structured knowledge requirement, safe workflow context summary, HTTP boundary의 server-issued reference 또는 같은 backend 내부 service call의 authorized safe candidate set을 매칭하고, MVP에서 keyword/metadata deterministic ranking을 수행한다.
5. Agent Builder는 결과를 resolved pending slot, clarification, validation failure 중 하나로 반영한다.

Adapter result는 recommendation item마다 score, confidence, reason category, threshold result를 포함해야 한다. Agent Builder는 KB 추천 후보가 1개여도 자동 resolved 처리하지 않고 clarification으로 전환해 사용자가 직접 후보 선택 상태를 확정하게 한다.

KB clarification UI는 safe candidate handle과 safe label/confidence/score/reason category만 표시한다. 후보 목록은 한 번에 3개 카드 높이로 표시하고, 최대 20개 후보를 스크롤로 확인할 수 있어야 한다. 후보 카드는 토글 방식이며 사용자는 0개, 1개, 여러 개 후보를 선택할 수 있다. 사용자가 후보를 선택하면 frontend는 raw KB id나 safe metadata 전체를 다시 보내지 않고 candidate safe handle과 선택적 resolution/requirement reference만 제출한다. 사용자가 아무 후보도 선택하지 않고 제출하면 Knowledge Base binding 없이 draft 생성을 계속한다. 후보 선택 제출이 `draft_ready` 또는 다른 후속 assistant 응답으로 완료되면 해당 clarification은 해결된 상태가 되어 빈 입력 전송의 재사용 대상이 아니며, 과거 후보 카드는 채팅 기록으로 남아도 다시 선택할 수 없다. Backend는 직전 미해결 clarification과 같은 session/context에서 온 선택인지 검증하고, apply/save 직전 runtime KB reference materialization을 다시 수행한다.

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

- Refresh 후에는 redaction된 사용자 message summary와 assistant response를 포함한 최근 대화, pending request 상태를 복구한다. Top-level preview는 최신 assistant response가 `draft_ready`이거나 최근 메시지가 없는 legacy session일 때만 보조 복구하며, 최신 응답이 `failed`, `unsupported`, `validation_failed`이면 과거 preview를 별도 draft 메시지로 추가하지 않는다.
- 같은 workflow의 apply/save reconcile로 `app_id` metadata가 채워져도 panel을 remount하거나 대화를 초기화하지 않는다. Workflow scope 변경 또는 workflow가 없는 app-only scope 변경에서만 이전 session state를 분리한다.
- 새 workflow apply/save 성공에서는 backend가 재결합한 동일 server session id를 새 workflow key로 이전하고 one-shot reopen marker로 panel을 다시 열어 safe conversation을 복구한다.
- 사용자 요청, pending 상태, assistant 응답이 대화 목록에 추가되면 Agent Builder chat panel은 최신 메시지가 보이도록 대화 영역을 맨 아래로 자동 스크롤한다. KB 후보 목록 내부 스크롤은 대화 영역 스크롤과 별도로 유지한다.
- Pending request가 있으면 새 submit은 막고 cancel은 허용한다.
- Cancel 이후 도착한 결과는 draft preview, Preview Mode, apply/save로 이어질 수 없다.
- 선택된 edge는 "이 연결 사이에" 같은 자연어 edge 문맥에서만 target hint로 사용하고, 권한/scope 판단에는 사용하지 않는다.
- TargetResolver가 여러 workflow node 후보를 반환하면 client는 이를 Knowledge Base 후보와 구분된 node target option으로 표시한다. 사용자가 node option을 선택하면 원래 자연어 요청과 선택한 `selected_node_id`를 다시 보내며, KB candidate field로 변환하지 않는다.
- Validation을 통과하지 않은 draft에는 `도안 생성 미리보기` 또는 `적용 및 저장` action을 표시하지 않는다.
- Preview Mode 안내는 "미리보기 모드이며 아직 저장되지 않았다"는 상태를 명확히 표시한다. `적용 및 저장`과 `취소` action이 Agent Builder panel 안에 있다면 Preview Mode 동안 panel close를 차단해 action 경로가 사라지지 않게 한다.
- `도안 생성 미리보기` audit 기록이 실패하면 Preview Mode에 진입하지 않고 재시도 안내를 표시한다.
- Preview Mode에서 actual editor graph와 preview graph는 별도 state로 유지한다.
- MVP에서는 editor에 저장되지 않은 변경이 있으면 Agent Builder draft 생성, Preview Mode 진입, 또는 `적용 및 저장`을 차단하고 먼저 저장 또는 폐기를 요구한다.
- MVP message request는 raw client graph snapshot을 보내지 않는다. Client는 selected node/edge hint만 보내며, apply/save 단계의 preview 확인과 stale guard에는 semantic graph hash만 사용한다. Hash 계산이 불가능하면 raw graph payload fallback을 보내지 않고 apply/save를 차단한다.
- 후속 확장에서는 검증 가능한 client graph snapshot을 draft base로 삼는 정책을 도입할 수 있으나, 그 전까지 unsaved editor graph를 agent draft base로 자동 포함하지 않는다.
- `적용 및 저장`은 workflow graph 저장까지 수행하지만 workflow 실행, Knowledge Base retrieval, Slack 전송, workflow node credential 사용/변경, 외부 시스템 변경을 수행하지 않는다.
- GitHub, Slack, HTTP, Mail, Workflow 같은 외부 연동 node는 draft에 포함할 수 있지만 credential과 target 설정을 자동 주입하지 않는다. Mail node는 `credential_id=null`만 생성하며 email/password/provider endpoint를 graph에 넣지 않는다. 미해결 설정은 `configuration_state=unresolved`로 표시하고 Preview/Node Detail에서 읽기 전용으로 확인한다.
- Gmail 답장 자동화 preview는 `max_results=1`인 durable Mail 검색, LLM, Gmail Draft, Mail Acknowledge node를 구분해 표시한다. Draft node에는 발송 action이 없으며 Acknowledge node는 processing/effect output 연결만 표시한다.
- 공통 외부 호출 차단 안내는 draft `safety_notices`에 한 번만 유지한다. 외부 연동 node의 미해결 설정은 `configuration_issues`에서 node별 표시명과 필요한 파라미터 목록으로 구분하며, 같은 type의 node가 여러 개여도 합치지 않는다. Session restore는 저장된 preview graph에서 이 목록을 다시 파생한다.
- `적용 및 저장` 성공 시 Preview Mode를 종료하고 editor는 저장된 최신 workflow graph를 표시한다. 이 성공 상태는 backend 저장과 apply/save audit 기록 성공을 모두 통과한 경우에만 사용한다.
- `적용 및 저장` 차단 또는 실패 시 Preview Mode를 유지하고 actual editor graph를 변경하지 않는다.
- `APP_ACTIVE_DEPLOYMENT_CONFLICT`와 `APP_WORKFLOW_BUDGET_CONFLICT`는 `apply_blocked`로 표시하고, 기존 배포 해제 또는 예산 lifecycle 확인이라는 안전한 다음 조치만 안내한다. 예산 금액, 당월 비용, 권한 subject 목록은 표시하지 않는다.
- Stale check는 backend가 base graph hash와 workflow version/updated_at을 최신 값과 비교해 수행한다. Frontend의 stale warning은 사용자 안내일 뿐 최종 판정이 아니다.
- Apply/save audit은 draft preview 생성, Preview Mode 진입, 적용 및 저장 요청, 저장 차단, 저장 성공, 저장 실패, 취소 event를 구분한다. Audit payload는 safe metadata만 포함한다.

## Accessibility

- Launcher와 panel은 keyboard focus 이동이 가능해야 한다.
- Pending, warning, validation failure는 screen reader가 읽을 수 있는 status text를 제공한다.
- `적용 및 저장`과 `취소`는 명확한 button label을 사용한다.
