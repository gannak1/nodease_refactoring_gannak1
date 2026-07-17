# Agent Builder Test Cases

Status: Draft

## 1. Verification Policy

MBA-228 direct-edit와 MBA-293 generation-mode target은 문서 작성만으로 구현 완료하지 않는다. 각 요구사항은 static, unit, integration, component, E2E 또는 manual smoke 중 하나 이상의 실행 가능한 검증에 연결한다. MBA-293 시점에 아직 구현되지 않은 quick mode case는 후속 구현 gate이며 현재 코드 통과로 표시하지 않는다.

DB를 사용하는 integration/E2E는 순차 실행한다. pure unit과 frontend component test는 병렬 실행할 수 있다. 필수 검증이 환경 문제로 실행되지 않으면 완료로 처리하지 않는다.

과거 revision이나 다른 worktree의 결과는 현재 변경의 통과 근거로 재사용하지 않는다. Test Matrix의 `Passed`에는 검증한 commit, 정확한 command, test count와 environment를 함께 기록한다.

## 2. Static Tests

### DBP-TC-S001 Catalog Schema

- MBA-228 direct-edit catalog version은 3이다.
- v3 parameter/input/output schema와 parser를 같은 변경에서 도입한다.
- 새 GraphMutation API 응답은 full typed operations를 포함하지만 기존 request `response_payload` JSON에는 operations 없이 `catalog_version=3`, canonical/requested/effective `generation_mode`, mode transition/proposal safe state, safe operation envelope와 task version/defer policy/resolution source를 기록하고 전체 JSON 객체를 재할당해 저장한다.
- Ddditive migration의 nullable `AgentBuilderSession.protocol_version`은 구현 시점의 단일 Alembic head 뒤에 연결한다. 신규 direct-edit session에 `direct_edit_v1`을 기록하고 기존 null session을 request 유무와 무관하게 legacy로 분류한다.
- 버전이 없거나 `2`인 미적용 legacy operation은 stale 처리하고 재생성을 요구한다.
- `catalog_version=3`인 operation만 current catalog validation과 apply/CDS save/acknowledgement 후보가 된다.
- 기존 Preview session은 direct-edit 전환 이후 `stale_protocol`이며 legacy draft를 GraphMutation으로 변환하지 않는다.
- Catalog version 또는 operation replay를 위해 별도 column, encrypted payload나 legacy backfill을 만들지 않는다. Session protocol column 외 신규 Agent Builder table은 만들지 않는다.
- catalog의 모든 supported node는 parameter schema, connection policy, input/output contract를 가진다.
- parameter key는 node 안에서 유일하다.
- input type과 validation rule reference는 허용 enum에 포함된다.
- `credential_ref` parameter는 sensitive policy를 가진다.
- command: shared catalog schema pytest

### DBP-TC-S002 Runtime Contract Parity

- webhook root payload, condition selected handle, file extraction output, variable extraction mapping output이 runtime 구현과 catalog에 동일하게 정의된다.
- runtime에 없는 output을 catalog가 노출하면 실패한다.

### DBP-TC-S003 API Schema

- raw graph keys와 raw secret payload를 request schema가 거부한다.
- GraphMutation kind와 discriminated operation은 extra field를 거부한다.
- `initial_graph`, `graph_edit`, `replace_workflow`, `parameter_update`, `knowledge_binding`이 같은 envelope를 사용하고 `structure_only`는 mutation kind로 거부한다.
- `reverted`는 operation status이며 GraphMutation kind로 허용하지 않는다.
- 지원 operation은 `add_node`, `remove_node`, `add_edge`, `remove_edge`, `replace_node_data`뿐이다.
- Workflow draft `mutation_context`와 canonical save response가 frontend/backend type에 동일하게 정의된다.
- GraphMutation API schema에는 `expected_result_graph_hash`와 typed operations가 있지만 persisted safe envelope schema에는 operations가 없다.
- canonical generation mode `guided_generate|quick_generate|structure_only`, legacy transport alias `configure_and_generate`, `mode_transition_required`, terminal `configuration_required`와 `skipped`를 포함한 status enum이 frontend/backend type에서 의도대로 일치한다. RequestStatus에는 `pending_apply`가 없고 GraphMutationStatus에만 존재한다.
- Typed Knowledge placement의 timing/effect/step/bridge discriminator와 required field가 frontend/backend type에 일치한다.

### DBP-TC-S004 Documentation

- ADR-0045/ADR-0046/ADR-0054, requirements, API, component, test 문서의 endpoint, mode, status 이름이 일치한다.
- PRD, architecture, data model, glossary가 direct-edit, GraphMutation, CDS save와 acknowledgement 계약을 동일하게 설명한다.
- ADR-0045는 direct-edit UX/history authority, ADR-0046은 supporting 저장 contract, ADR-0054는 generation mode/transition authority, ADR-0019는 Superseded legacy로 표시한다. Preview를 활성 fallback으로 유지한다는 표현은 허용하지 않는다.

## 3. Unit Tests

### DBP-TC-U001 Planner Call Count

- 정상 request는 planner를 한 번 호출한다.
- strict JSON Schema를 지원하는 OpenDI model은 Pydantic output schema를 provider response format으로 전달하고, 지원하지 않는 model/provider는 JSON object mode를 유지한다.
- 복합 Knowledge placement 응답이 reasoning/output 한도 부족으로 잘리지 않도록 Planner 호출의 `max_tokens=4000` 계약을 검증한다.
- 최초 응답은 모든 parameter guidance hint를 `step_id`, `parameter_key`, `reason`, `input_guidance`로 함께 반환한다.
- Planner는 명시적인 "한 번에", "단계별로", "구조만" 요청만 canonical `generation_mode_intent`로 반환하고 일반 생성 요청은 null을 반환한다. 이 값만으로 quick eligibility나 권한을 통과시키지 않는다.
- 최초 schema-valid 결과가 semantic invariant를 위반한 request만 repair를 한 번 호출해 총 두 번이다. Pydantic 구조 schema 오류는 attempt 1 뒤 repair 없이 fail-closed한다.
- provider 호출, JSON 파싱 또는 JSON 객체 형태 오류는 repair 없이 fail-closed한다.
- repair 결과의 재실패는 세 번째 호출 없이 fail-closed한다.
- 실제 extractor 경로에서 `입력 응답 노드를 만들어줘`, `입력 출력 노드를 생성해줘`, `Start Answer 노드를 만들어줘`를 완결된 신규 node 흐름으로 안내한다. `깃허브 노드 만들어줘`처럼 배치 없는 단일 지원 node 생성 요청은 `github_pr_read`와 read action을 포함한 신규 flow로 안내한다.
- 최초 schema-valid 응답이 reason과 structured unsupported action 없이 `unsupported`이면 `UNSUPPORTED_REASON_REQUIRED`로 한 번 repair하고, 두 번째 유효 응답을 사용한다.
- 완결된 지원 `입력/Start -> 응답/Output` 생성 요청이 임의의 자연어 unsupported 사유와 함께 `unsupported`로 반환되면 `UNSUPPORTED_SUPPORTED_FLOW_CONTRADICTION`으로 한 번 repair한다. 이 검증은 capability를 직접 생성하거나 LLM 결과를 덮어쓰지 않는다.
- 배치 없는 단일 지원 node 생성 요청이 임의의 자연어 unsupported 사유와 함께 `unsupported`로 반환되면 `UNSUPPORTED_SUPPORTED_NODE_CREATION_CONTRADICTION`으로 한 번 repair한다. 이 검증은 capability를 직접 생성하거나 LLM 결과를 덮어쓰지 않는다.
- 서버가 인식하는 `github/pull_request/create` structured unsupported action은 별도 자연어 reason이 없어도 repair 없이 unsupported로 닫는다.
- `웹훅으로 받는 사내 문서 챗봇 워크플로우를 만들어줘`의 최초 응답이 Knowledge placement를 누락하면 typed `after_graph`/`binding_only` placement 계약을 포함해 한 번 repair한다.
- 같은 사내 문서 챗봇 요청의 유효 응답은 `webhook_trigger -> knowledge_backed_llm -> answer`와 LLM step 대상 `after_graph + binding_only` placement를 사용하고, 명시적인 topology 변경 요청에만 `before_graph + insert_step`을 허용한다.
- Semantic code는 allowlist 형식만 진단에 남긴다. Provider 호출 예외는 `provider_call_failed`, Pydantic schema 오류는 `schema_validation_failed`로 구분하되 raw provider exception, credential-like value와 사용자 message 원문은 반사하지 않는다.
- parameter task 이동과 값 제출은 planner를 호출하지 않는다.

### DBP-TC-U002 Planner Authority Boundary

- planner가 catalog에 없는 parameter를 반환해도 task에 포함되지 않는다.
- planner가 unsupported node를 요구하면 mutation generation이 차단된다.
- 현재 step capability의 Catalog에 존재하는 parameter guidance hint만 task description에 사용된다.
- Unknown/mismatched/secret-like hint는 폐기되고 Catalog description으로 fallback한다.

### DBP-TC-U003 Target Resolution

- selected node, selected edge, 자연어 단일 target을 resolve한다.
- 0개 또는 2개 이상 target은 clarification을 반환한다.
- 기존 graph 수정에 detached Start/Answer wrapper를 만들지 않는다.

### DBP-TC-U004 GraphMutation Validation

- 다섯 mutation kind와 다섯 operation의 valid 조합을 생성한다.
- `replace_workflow`는 기존 edge/node 전체 제거와 새 node/edge 추가의 typed operation만 허용하고 raw workflow 교체 payload를 거부한다.
- invalid handle, duplicate id, unsupported node, detached node와 임의 JSON Patch path를 차단한다.
- 일부 operation만 유효한 경우 전체 mutation을 반환하지 않는다.
- 같은 입력, catalog version과 base graph는 같은 operation order를 만든다.
- complete candidate를 발급 전에 검증하고 같은 canonical `expected_result_graph_hash`를 만든다.
- Condition의 default와 각 case target decision은 typed ParameterTask로 생성된다. 생성기의 단일 선형 downstream edge는 node를 보존한 explicit default edge와 초기 선택값으로 변환되고, 여러 handle 없는 edge는 validation failure가 된다. 확인 전 Condition은 unresolved이고, 기존 node를 선택한 branch edge에는 해당 case id 또는 `default` `sourceHandle`이 명시되며 `연결 안 함`을 확인한 branch에는 edge가 없다. `cases` acknowledgement 뒤 새 handle task가 한 번만 추가되고 제거된 task는 canceled이며 중복 acknowledgement가 task를 중복 생성하지 않는다.
- Validator와 Workflow runtime integration에서 handle 없는 Condition edge를 암묵적 default로 처리하지 않고, 명시적 default/case handle만 실제 선택 결과를 따라간다.
- Condition target picker는 node id와 내부 sentinel 대신 `option_labels`를 표시하고 canonical id를 제출하며, 기존 target과 `연결 안 함`을 node data에서 hydrate한다. 자기 자신, 발급되지 않은 option, incoming forbidden node와 cycle target은 거부한다.

### DBP-TC-U005 Auto Layout

- measured width/height를 우선하고 없을 때 안정적인 기본 크기를 사용한다.
- 여러 case가 있는 condition node와 인접 layer node가 겹치지 않는다.
- 저장 또는 direct mutation operation의 node position에 실제 layout 결과가 포함된다.

### DBP-TC-U006 Parameter Task Ordering

- graph dependency 순서로 node group을 정렬한다.
- node 내부에서는 catalog order를 유지한다.
- required와 optional 상태를 보존한다.
- `structure_only`에서는 task를 만들지 않는다.
- 사용자 명시값, 기존 node 값, 단일 upstream 값, 안전한 기본값 순서로 materialize한다.
- `agent_builder_task=true`인 configurable parameter에 task record를 만들고 자동 추천 parameter는 올바른 resolution source와 graph 값을 가지되 사용자 확인 전 `pending|active`다. Start의 빈 `variables`와 Answer의 빈 `outputs`는 `agent_builder_task=false`여서 task를 만들지 않는다.
- 자동 확정 task의 실제 값은 request payload에 복제하지 않고 workflow graph에만 존재한다.
- 후보가 여러 개면 선택 task를 만들고 자동 확정하지 않는다.
- Catalog에 defer policy가 없으면 `forbidden`이며 `allow_unresolved`만 defer할 수 있다.
- Optional skip은 graph mutation 없이 task를 `skipped`로 전환하고 required skip은 거부한다. Skipped task set은 일반 parameter mutation으로 completed가 된다.
- Required configuration 전체를 검사해 missing/deferred/invalid 중 하나라도 있으면 unresolved이고 모두 유효할 때만 resolved다. Optional skipped task는 required가 아닌 한 상태를 막지 않는다.

### DBP-TC-U007 Suggestion Resolver

- reachable upstream output 중 input type이 맞는 항목만 추천한다.
- 다른 condition branch의 output을 추천하지 않는다.
- webhook root payload에서 유효한 selector를 만든다.
- variable/file extraction의 실제 runtime output key를 사용한다.
- suggestion은 opaque id, source node, output key, nested path를 포함한 canonical selector 배열, 표시용 JSON path, value type과 safe description을 반환한다.
- client가 selector 배열 또는 JSON path를 변조하면 current graph/catalog contract 검증에서 거부한다.
- 동점 ranking이 결정적이다.

### DBP-TC-U008 Knowledge Timing

- RDG node 유무가 바뀌면 `before_graph`다.
- 기존 LLM node binding만 바뀌면 `after_graph`다.
- empty `before_graph` selection은 가짜 candidate나 재질문 없이 KB-free base topology를 선택하고 planner를 다시 호출하지 않는다.
- Planner는 requirement id, timing, target/effect와 insert step의 upstream/downstream/bridge로 구성된 typed placement만 반환하고 선택별 완성 graph나 raw edge를 반환하지 않는다.
- Unknown step, invalid capability, `before_graph+binding_only`/`after_graph+insert_step` timing-effect mismatch 또는 invalid bridge placement를 거부한다.
- selected/empty selection이 만드는 node/data/edge 결과를 각각 고정하고 invalid KB-free candidate는 부분 mutation 없이 실패한다.
- 다중 selection을 dedupe하고 cap을 적용한다.
- Candidate가 0개인 direct resolution도 상위 `resolution_id`와 KB-free CTD를 렌더링하고 빈 배열을 전용 endpoint로 제출한다.
- direct-edit parameter group은 `llmNode.knowledgeBases` generic `resource_ref` task를 만들지 않고 KB 후보를 전용 Knowledge card에만 표시한다. 이전 session에 남은 generic task는 복구 시 제거하고 다음 task 또는 완료 상태로 정리한다.

### DBP-TC-U009 Existing Model Compatibility

- active organization credential/model relation과 사용자 use 권한을 통과한 후보만 반환한다.
- generated LLM node 추천과 intent planner 선택을 서로 혼용하지 않는다.
- MBA-228 변경으로 기존 후보가 숨은 fixed-model fallback을 사용하거나 credential을 graph에 저장하지 않는다.
- 같은 model/credential의 verified relation이 중복이면 가장 낮은 relation priority 하나만 후보로 사용한다.
- Header와 새 generated LLM node가 같은 후보 집합에서 동일한 첫 model을 추천한다. Header 사용자 선택은 generated node에 복사하지 않고 기존 node model도 덮어쓰지 않는다.
- Provider 순서, 최신 세대, 같은 세대 `general -> mini -> nano -> pro`, 같은 tier 기본형 -> 날짜/release -> preview -> latest 순서를 검증한다.
- 특수 목적 model은 완전한 token 또는 명시된 연속 token/전체 ID 규칙으로 제외하고 단순 부분 문자열 일치로 정상 verified chat model을 제외하지 않는다. 세대/tier 미분류 모델은 provider 후순위에서 안정적으로 유지한다.
- LlamaParse는 `chat_model_not_supported` disabled group으로 반환한다.
- 최신 dev catalog의 Mail 검색, Gmail Draft와 Mail terminal acknowledgement capability가 direct-edit allowlist와 template에 유지된다.
- Gmail 답장 초안 capability는 durable Mail 검색, LLM, Gmail Draft, Mail terminal acknowledgement 순서로 정규화되고 acknowledgement 단독 요청은 거부된다.
- Mail send/reply-all/attachment 요청은 unsupported이며 HTTP node로 대체되지 않는다.

### DBP-TC-U010 Secret Boundary

- 알려진 token prefix, private key, connection string, bearer value를 planner 입력에서 차단 또는 redaction한다.
- parameter task description/example/audit에 원문이 남지 않는다.
- credential id는 safe reference로 처리하고 credential config는 거부한다.

## 4. Backend Integration Tests

### DBP-TC-I001 Session Permission

- active organization member와 workflow write 권한 사용자는 session을 시작한다.
- workflow id가 없으면 `workflow_context_required`로 거부하고 Agent Builder가 workflow row를 만들지 않는다.
- 신규 workflow flow는 기존 Editor가 만든 빈 workflow shell을 사용한다.
- removed/suspended member, 다른 organization, read-only 사용자는 거부된다.
- 403/404 숨김 정책을 유지한다.

### DBP-TC-I002 Guided Generate

- `canonical-v2`의 `guided_generate` message submit이 validated GraphMutation과 parameter group을 반환한다. Mode가 없거나 legacy `configure_and_generate` 입력도 내부 guided로 정규화되며 외부 응답 mode는 negotiated contract 표현을 따른다.
- 검증된 planner `reason`/`input_guidance`가 해당 parameter task description으로 전달되고 API 복구 뒤에도 같은 safe 설명을 반환한다.
- Planner hint가 없거나 폐기되면 Catalog description으로 생성된 task를 반환한다.
- GraphMutation 발급 과정에서 workflow run, retrieval, 외부 HTTP action을 호출하지 않는다.
- GraphMutation 발급 audit를 기록한다.

### DBP-TC-I003 Structure Only

- 동일 `generation_mode=structure_only` request가 빈 workflow의 새 graph에서는 `initial_graph`, 기존 workflow 부분 변경에서는 `graph_edit`, 전체 교체에서는 `replace_workflow` GraphMutation을 반환하고 parameter group은 만들지 않는다.
- parameter group은 null이다.
- unresolved configuration warning을 반환한다.
- local graph 적용만으로 operation을 완료하지 않는다.
- CDS workflow draft 저장과 canonical graph hash/`updated_at` acknowledgement 뒤 operation을 완료한다.
- 저장 실패와 acknowledgement 유실 후 operation id와 canonical 값으로 재시도·복구한다.
- workflow 실행·배포 preflight는 unresolved external node를 차단한다.
- 비어 있지 않은 editor에서 완결된 신규 workflow 요청을 보내면 기존 graph 전체를 typed remove/add operation의 `replace_workflow`로 교체한다. 같은 요청은 빈 workflow shell에서는 `initial_graph`를 반환한다.
- `Diff 노드와 LLM 노드 사이에 Code 노드 삽입`처럼 자연어 source/destination pair를 받은 `between` request는 직접 edge가 정확히 하나일 때만 `graph_edit`를 반환한다. 0개 또는 복수 direct edge는 edge 선택 clarification이며 multi-hop path는 지원하지 않는다.
- `입력`과 `응답` 사이에 LLM node 삽입 요청은 저장 graph 제목이 `Start node`와 `Answer node`여도 예약 구조 node 별칭으로 직접 edge를 resolve한다.

### DBP-TC-I004 GraphMutation CDS Save And Acknowledgement

- GraphMutation 응답은 `pending_apply`이고 parameter group은 `pending_save`다.
- local mutation 적용만으로 parameter group을 활성화하지 않는다.
- workflow draft CDS save 성공 후 acknowledgement 전 local 상태는 `pending_ack`이고 모든 task는 canonical `pending`이며 frontend와 decision API 모두 입력을 받지 않는다.
- canonical graph hash/`updated_at`이 확인된 acknowledgement만 parameter group을 `active`로 전환한다.
- 저장 실패, stale 또는 validation failure는 group을 `blocked`로 유지한다.
- Full operations 응답이 CDS 저장 전에 유실되면 server가 이를 재생하거나 active mutation으로 반환하지 않고 기존 envelope를 `blocked/operation_payload_unavailable`로 닫는다. Initial/graph-edit/replace는 parent request의 terminal cancel 확인 후 request 재생성, parameter decision은 같은 parent request와 task/version의 새 operation id 재입력을 요구한다.
- Session recovery와 CDS save가 경합하면 request row lock 뒤 최신 상태를 다시 읽고 `pending_ack|acknowledged`를 차단 상태로 덮어쓰지 않는다.
- 차단된 parameter operation은 pending decision을 제거하고 같은 task/version을 다시 active로 열며, 새 입력은 새 operation id로 발급할 수 있다.
- 저장 성공 후 acknowledgement 응답 유실은 같은 operation id, expected/saved graph hash와 canonical `updated_at`으로 안전하게 복구한다. 원래 mutation 제출 흐름은 동일 payload acknowledgement를 정확히 한 번 재시도할 수 있고, 두 번째 결과까지 유실되면 session recovery가 acknowledgement를 다시 보내지 않고 acknowledged operation과 canonical hash/timestamp를 확인해 client boundary를 완료 상태로 reconcile한다.
- Client는 acknowledgement 응답이 한 번 유실되면 동일 payload로 한 번만 재시도하고, server는 이미 완료된 task/resolution과 audit를 다시 변경하지 않는다.
- mismatched graph hash 또는 `updated_at`은 stale 또는 validation failure다.
- 같은 operation id acknowledgement와 재전송이 graph나 task 중복 변경을 유발하지 않는다.
- 중복 acknowledgement는 같은 completed task/next task 응답을 반환하고 task version과 audit count를 증가시키지 않는다.
- acknowledgement endpoint는 graph를 다시 저장하지 않는다.

### DBP-TC-I005 Stale Graph

- request base 이후 graph hash 또는 workflow `updated_at`이 바뀌면 mutation을 stale로 반환한다.
- 같은 base에서 두 사용자가 저장하면 첫 CDS 저장만 성공하고 두 번째는 409이며 첫 graph를 덮어쓰지 않는다.
- stale mutation을 parameter task로 진행하지 않는다.
- latest failed request가 과거 ready mutation을 복구하지 않는다.

### DBP-TC-I006 Parameter Decision

- typed text/resource/credential/selector decision을 검증한다.
- decision discriminator와 task input type이 다르면 거부한다.
- `variable_selector` decision의 suggestion id와 canonical selector 배열이 server-issued candidate와 모두 일치해야 한다.
- required task skip을 거부한다.
- optional task skip과 Catalog `defer_policy`를 구분한다. Optional skip은 GraphMutation 없이 task를 `skipped`로 만들고 next task를 한 번만 활성화한다. Policy 누락/`forbidden` defer는 거부하고 `allow_unresolved` defer만 parameter mutation을 만든다.
- `allow_unresolved` defer는 CDS 저장/acknowledgement 뒤 task를 deferred로 전환하고 실행·배포 preflight가 해당 node를 차단한다.
- 유효한 decision은 현재 task를 유지한 `parameter_update` GraphMutation을 반환한다.
- mutation local 적용만으로 task를 완료하거나 next task를 활성화하지 않는다.
- CDS 저장과 canonical graph hash/`updated_at` acknowledgement 뒤 현재 task가 완료되고 next task가 안정적으로 이동한다.
- parameter mutation은 base hash, expected workflow `updated_at`, affected node, completion context와 catalog version을 포함한다.
- 저장 실패, acknowledgement 응답 유실, 새로고침 후에도 저장되지 않은 task를 완료로 복구하지 않는다.
- parameter decision은 LLM usage row를 추가하지 않는다.
- 자동 추천 task의 값이 canonical graph와 같고 관련 structural operation이 acknowledged일 때만 `confirm`하면 GraphMutation/workflow save 없이 completed가 되고 next task를 한 번만 활성화한다. Structural operation이 `pending_save|pending_ack`이면 confirm을 거부한다. 같은 operation 재시도는 version, next task와 audit를 반복 변경하지 않는다.
- mutation이 추가한 node의 template/default value는 `catalog_default`, server-issued upstream selector는 `upstream_selector`, base graph node에서 읽은 값만 `existing_graph` source로 표시한다. 세 경우 모두 사용자 confirm 전 terminal task가 되지 않는다.
- 자동 추천 task 값을 `set`으로 수정하면 동일 task id의 새 `parameter_update`를 거쳐 acknowledgement 뒤 completed가 되고 이미 활성화된 next task를 다시 생성·활성화하지 않는다.
- `previous`는 current presentation task의 canonical 상태가 `active|completed|skipped|deferred`여도 persisted 상태/version을 바꾸지 않고 이전 재편집 가능 task id를 반환한다.
- skipped task를 다시 열어 `set`하면 CDS acknowledgement 뒤 completed가 되며 skip 당시 graph에는 값이 저장되지 않는다.
- 여러 required configuration 중 일부만 set하거나 하나를 defer하면 unresolved이고, 마지막 required 값을 유효하게 set하면 resolved가 된다. Undo와 reload에서도 같은 파생 상태를 계산한다.

### DBP-TC-I007 Knowledge Selection

- before-graph 선택 전에는 GraphMutation을 만들지 않는다.
- before-graph empty selection은 KB-free graph를 한 번만 만들고, prompt에 Knowledge가 언급돼도 선택을 다시 요구하거나 planner를 다시 호출하지 않는다.
- Structured plan의 typed placement step/effect/bridge를 검증하고 selected/empty graph는 Catalog template에서 생성한다. Planner가 별도 완성 graph를 제공하지 않는다.
- after-graph selection은 `knowledge_binding` GraphMutation만 만든다.
- after-graph binding은 CDS 저장과 canonical graph hash/`updated_at` acknowledgement 뒤에만 선택 완료로 기록한다.
- binding mutation의 completion context와 acknowledgement는 완료된 resolution id를 반환한다.
- binding 저장 실패와 acknowledgement 재시도에서 같은 operation을 중복 적용하지 않는다.
- 0개, 1개, 다중 KB 선택을 지원한다.
- before/after Knowledge 선택은 하나의 workflow 설정 결과에서 순차 표시하며 같은 requirement의 legacy selector와 direct-edit card가 동시에 존재하지 않는다.
- 각 KB의 use 권한, lifecycle, ready version을 검증한다.
- safe metadata 외 raw title/path/content를 planner에 보내지 않는다.

### DBP-TC-I008 Session Recovery

- pending planning, graph mutation ready, parameter active 상태를 복구한다.
- Request 없는 신규 direct-edit session도 session row의 `protocol_version=direct_edit_v1`로 복구한다.
- Request가 없는 기존 null-protocol session도 legacy로 분류해 `stale_protocol`로 반환한다.
- applied operation은 자동 재적용하지 않는다.
- raw parameter value와 secret은 response에 포함되지 않는다.
- task 상태는 request `response_payload`에서, 실제 parameter 값은 저장된 workflow graph에서 복구한다.
- 자동 추천 task와 resolution source를 복구하고 실제 값은 graph에서만 읽는다. 사용자 confirm 전에는 completed로 앞당기지 않는다.
- parameter/Knowledge operation이 CDS 저장 또는 acknowledgement 전에 종료되면 task/selection 완료 상태를 앞당겨 복구하지 않는다.
- stale session은 명확한 stale status를 반환한다.
- 기존 Preview session은 `stale_protocol`이며 safe 대화 외 legacy preview/draft를 복구·적용하지 않는다.
- session GET 또는 pending polling이 transport/5xx로 세 번 연속 실패하면 `1초 -> 2초 -> 4초` 자동 확인 뒤 `결과 확인 필요`와 `다시 확인` control을 표시하고 local session key, 대화, 입력 draft, Knowledge 선택과 history boundary를 유지한다.
- `다시 확인`은 같은 session GET만 새로 세 번 시도하며 natural-language request, planner, GraphMutation 또는 acknowledgement를 새로 발급하지 않는다.
- `stale_protocol`, 명시적 session not found 또는 invalid session만 local session key를 제거한다. Gateway 5xx와 network failure는 key를 제거하거나 새 session을 만들지 않는다.
- `reverted` history boundary와 연결된 모든 ParameterTask/Knowledge resolution은 `canceled`로 복구한다. Parameter/Knowledge operation별 `reverted` 상태를 만들지 않고 Redo로 canceled 흐름을 completed로 바꾸지 않는다.

### DBP-TC-I009 Audit Durability

- mutation 발급, CDS save, acknowledgement, task complete/defer, permission/stale 차단 event를 구분한다.
- Graph CDS save 또는 persisted revert와 같은 SQLDlchemy session에서 `add_action_audit` insert가 실패하면 graph와 operation 상태를 모두 rollback하고 성공을 반환하지 않는다.
- safe ids/reason만 기록한다.
- parameter value, raw URL/path, raw Knowledge metadata와 secret-like span이 audit/trace에 없다.

### DBP-TC-I010 Workflow Draft CDS Contract

- Agent Builder operation의 `mutation_context` 누락을 거부한다.
- workflow row lock 안에서 expected base graph hash와 expected workflow `updated_at`을 함께 비교한다.
- 저장 request graph hash가 persisted safe envelope의 `expected_result_graph_hash`와 다르면 저장하지 않는다. DB에 full typed operations가 없으며 이를 재생하지 않는다.
- 저장 성공 응답은 canonical graph hash, `updated_at`, workflow id와 operation id를 반환한다.
- 존재하지 않는 workflow version/revision을 schema나 응답에 만들지 않는다.
- 일반 editor save 호환 요청은 유지하되 그 결과로 Agent Builder acknowledgement할 수 없다.
- graph 저장과 기존 transaction-bound audit insert 중 하나가 실패하면 성공 응답을 반환하지 않는다.

### DBP-TC-I011 Unresolved Execution And Deployment Preflight

- unresolved 외부 action node가 있는 graph의 편집과 저장은 허용한다.
- 같은 graph의 workflow run과 deployment 생성은 server-side preflight에서 차단한다.
- resolved required configuration이면 기존 권한 검증 뒤 실행·배포할 수 있다.
- 생성, set/defer/skip, persisted Undo, recovery와 preflight가 같은 Catalog 기반 aggregate state를 계산하며 client가 보낸 `configuration_state` 변조를 신뢰하지 않는다.
- preflight는 Slack/GitHub/HTTP/Mail 또는 credential provider를 호출하지 않는다.

### DBP-TC-I012 Legacy Clarification Parity And Removal

- 현재 Condition/Variable node-specific clarification 결과를 characterization fixture로 고정한다.
- Catalog + ParameterTask + GraphMutation 경로가 같은 graph data와 validation 결과를 만든다.
- Characterization fixture 외 Preview 경로를 수정·확장하거나 활성 fallback으로 사용하지 않는다.
- parity와 필수 integration/E2E 뒤 backend와 frontend legacy 분기를 함께 제거한다.
- 신규 session과 message 응답에는 `draft_preview` 또는 legacy apply action이 포함되지 않는다.
- Preview-opened/apply 전용 endpoint는 direct-edit 제품 route에서 제거되고 호출할 수 없다.
- Agent Builder UI에는 Preview 진입과 `적용 및 저장` control이 렌더링되지 않는다.
- 기존 null session은 `stale_protocol` 안내만 표시하고 legacy draft 적용 action을 제공하지 않는다.
- Static removal test는 backend의 node별 legacy clarification 분기와 frontend Preview component/import가 남아 있으면 실패한다.

### DBP-TC-I013 Persisted Undo

- ParameterTask가 있는 completed boundary의 첫 Undo는 server graph, parameter 값과 persisted task 상태/version을 바꾸지 않고 `completed|skipped|deferred` 중 재편집 가능하며 `stable_order`가 가장 큰 task를 client presentation에서 표시한다.
- Parameter 재진입 상태의 다음 Undo는 boundary final hash가 current graph와 일치할 때 `action=revert`로 시작 전 base graph를 저장한다. Task가 없으면 completed 상태 첫 Undo가 즉시 이 revert를 수행한다.
- Revert는 generated node/edge, parameter 값, KB binding을 포함한 전체 결과를 제거하고 모든 ParameterTask/Knowledge resolution을 같은 transaction에서 `canceled`로 닫는다.
- `replace_workflow` boundary는 교체 전 graph 전체를 복구한다.
- `parameter_update`/`knowledge_binding` operation별 revert 요청은 거부한다.
- Audit insert 실패는 graph, boundary와 task/Knowledge 상태를 모두 rollback한다.
- Revert 전 다른 저장이 있으면 stale conflict로 닫고 기존 변경을 덮어쓰지 않는다. 수동 editor history가 있으면 해당 history를 먼저 Undo해야 boundary에 도달한다.
- 같은 revert 재시도는 idempotent하다. Reload 전 `action=redo`는 final graph를 CDS 저장하지만 canceled task/Knowledge 흐름을 재실행하지 않으며 reload 뒤에는 Redo stack이 없다.

### DBP-TC-I014 Protocol Migration Compatibility

- MBA-228 단일 기능 PR은 nullable `AgentBuilderSession.protocol_version` migration, null/`direct_edit_v1` mixed read와 direct-edit parity 뒤 Preview 제거를 함께 제공한다.
- 신규 migration을 적용해도 Alembic code head는 하나다.
- 기존 Agent Builder 데이터가 있는 disposable PostgreSQL에서 `upgrade head`가 성공하고 기존 null `protocol_version` row를 backfill하지 않는다.
- Gateway는 request가 없는 null session과 `direct_edit_v1` session을 모두 안전하게 읽는다.
- 신규 session은 `direct_edit_v1`을 기록하고 기존 null Preview session은 `stale_protocol`로 복구한다.
- Legacy session을 backfill하거나 direct-edit operation으로 자동 변환하지 않으며 additive schema downgrade를 요구하지 않는다.
- Frontend/Gateway mixed-revision 무중단 배포와 rollback은 별도 배포 검증 범위다.
- 기존 null session은 `stale_protocol`이며 legacy preview/draft를 적용하거나 변환하지 않는다.
- Frontend/Gateway 무중단 rollout은 별도 배포 계획과 후속 이슈가 소유하며 MBA-228 test 또는 완료 조건에 포함하지 않는다.

### DBP-TC-I015 Parameter Task Persistence And Concurrency

- Parameter task 변경은 parent request row를 write lock으로 조회하고 target task id, expected task version과 action별 허용 상태를 비교한다. 일반 진행은 active task만 변경하고 `set`은 `active|completed|skipped|deferred|invalid`에 허용하며 `pending|canceled`에는 허용하지 않는다.
- 같은 operation id 재시도는 GraphMutation 또는 next task를 중복 생성하지 않는다. `confirm|skip|cancel|previous`와 Catalog validation으로 invalid가 된 set은 같은 safe 결과를 반환하고 task version/commit/audit를 반복하지 않는다. Full operations가 유실된 `set|defer` replay는 `operation_payload_unavailable`을 반환하고 recovery 뒤 새 operation id로 재입력한다.
- 같은 task/version에 서로 다른 두 decision을 동시에 제출하면 첫 commit만 성공하고 두 번째는 `409 task_conflict`다.
- `response_payload` nested dict를 제자리 변경하지 않고 새 전체 객체를 재할당하며 commit 후 새 DB session에서 task version/status/operation을 다시 읽을 수 있다.
- 완료 task 수정, policy-allowed defer, optional skip과 group cancel 각각에서 task version이 단조 증가하고 남은 task 중복 활성화가 없다.
- Optional skip은 commit/reload 뒤 `skipped`로 남고 GraphMutation이나 workflow save를 만들지 않으며, skipped task set은 일반 CDS 흐름을 거친다.

## 5. Frontend Unit And Component Tests

### DBP-TC-F001 Generation Mode Control

- 기본값은 `단계별 생성`이다.
- `단계별 생성`, `빠른 생성`, 고급 `구조만 생성` label과 selected state를 표시한다.
- request 진행 중 control이 disabled다.
- 제출 request에 선택 mode와 `default|explicit_control` source가 포함된다.

### DBP-TC-F002 Atomic Graph Transaction

- nodes와 edges를 한 store update로 적용한다.
- undo stack에 기존 graph가 한 번만 추가된다.
- 최초 구조 mutation은 시작 전 snapshot과 final graph를 가진 boundary entry 하나만 만든다. 후속 parameter/Knowledge mutation은 history entry를 추가하지 않고 final snapshot을 갱신한다.
- 저장 또는 acknowledgement 전에는 completed boundary Undo로 처리하지 않는다.
- ParameterTask가 있으면 completed 상태 첫 Ctrl+Z가 graph/value와 persisted task 상태를 유지하고 최대 stable order task UI를 연다. 닫히거나 최소화된 panel도 열며 재진입 상태의 다음 canvas Ctrl+Z가 persisted boundary revert를 수행한다.
- ParameterTask가 없으면 completed 상태 첫 Ctrl+Z가 시작 전 graph를 persisted revert한다.
- `이전 항목`은 backend의 `next_task_id`를 presentation cursor로 소비해 card/node focus를 이동하지만 persisted task 상태와 Workflow undo stack을 변경하지 않는다.
- 생성 완료 뒤 수동 editor 변경이 있으면 그 변경을 먼저 Undo한 다음 Agent Builder boundary 동작이 실행된다.
- Reload 뒤에는 Redo stack을 복구하지 않는다.
- Parameter 재진입 상태에서 Ctrl+Y/Ctrl+Shift+Z는 UI를 닫고 completed 표시로 돌아간다. 전체 revert 뒤 Redo는 final graph를 CDS 저장하며 canceled Agent Builder task/Knowledge 흐름을 재개하지 않는다. 전체 Redo 뒤 다시 Ctrl+Z하면 parameter 재진입 없이 같은 boundary를 즉시 revert한다.
- Parameter input 안의 Ctrl+Z는 입력 문자만 되돌리고 Workflow Undo를 실행하지 않는다. Agent Builder card/button focus에서도 canvas Undo/Redo를 실행하지 않는다.
- partial apply exception 시 graph와 history가 바뀌지 않는다.
- Agent Builder transaction 중 autosync가 별도 save를 시작하지 않는다.
- CDS save가 stale이면 local graph를 silent overwrite하지 않고 blocked 상태를 표시한다.

### DBP-TC-F003 Workflow Result Group

- 현재 Agent Builder 결과에 포함된 라우팅 미설정 LLM은 하나의 자동 라우팅 안내에만 표시한다. routing이 이미 활성화됐거나 현재 결과에 포함되지 않은 LLM은 표시하지 않는다. 각 `설정 열기` 버튼은 해당 node focus만 요청하고 GraphMutation, workflow save, policy API 또는 planner 호출을 만들지 않는다.
- 구조만 생성 결과를 새로고침한 뒤에도 canonical safe envelope의 `affected_node_ids`로 동일한 routing 안내를 복구한다. full typed operation을 복구하거나 재생하지 않는다.
- 여러 node를 하나의 result group 아래 표시한다.
- Knowledge 선택, 자동 추천 확인과 수동 parameter 입력을 같은 result group 안에서 순차 표시한다.
- 같은 Knowledge requirement의 legacy clarification과 direct-edit Knowledge card를 동시에 표시하지 않는다.
- `direct_edit_v1` 응답이 `knowledge_resolution` 없이 legacy `clarification_options`만 포함하면 Knowledge 설정 card를 렌더링하지 않는다.
- active card만 확장하고 completed card는 요약한다.
- 자동 추천 parameter는 active card에 resolution source, 안전한 이유, 현재 값을 표시하고 확인 또는 수정할 수 있다.
- 진행률과 deferred/unresolved 상태를 표시한다.
- skipped task를 완료와 구분해 표시하고 다시 열어 설정할 수 있다.
- 모든 필수 Knowledge/parameter 확인과 graph 저장/acknowledgement 전에는 생성 완료를 표시하지 않고, 충족 뒤 명시적인 생성 완료 메시지를 표시한다.
- 긴 node/parameter label이 container를 넘지 않는다.

### DBP-TC-F004 Parameter Renderer

- 각 input type에 맞는 control을 렌더링한다.
- node type별 switch 없이 input type을 사용한다.
- LLM model graph의 provider API id가 candidate DB UUID와 달라도 `reference_value`로 기존 값을 hydrate하고 typed decision에는 candidate id를 제출한다.
- label, description, example, validation error를 연결한다.
- selector suggestion에 source node/output key/JSON path/value type을 표시하고 선택 시 suggestion id와 canonical selector를 제출한다.
- optional task에는 skip control을 표시하고 required task에서는 skip을 숨기거나 disabled로 표시한다.
- `defer_policy=allow_unresolved` task에만 defer를 표시하고 누락/`forbidden` task에는 표시하지 않는다.
- confirm/set/defer/skip/previous interaction, operation id/task version과 pending/invalid/completed/deferred/skipped 상태를 검증한다.
- active task id가 바뀌면 text/boolean/selector/candidate/search/error local draft가 초기화된다.
- secret input type은 렌더링하지 않는다.
- Mail/Gmail managed credential task는 Undo reentry와 구분되어 권한 검증된 후보만 표시하고, deferred presentation reentry는 기존 값과 상태를 안전하게 보여준다. Slack/GitHub credential task는 direct-edit response에 포함하지 않으며, 해당 node의 결과 안내는 기존 Editor 연결 설정으로 이동한다.

### DBP-TC-F005 Node Focus

- active 또는 presentation task id 변경 시 해당 node를 선택하고 panel을 제외한 가시 canvas 영역에서 가능한 가장 큰 비중첩 zoom으로 한 번 focus한다.
- 같은 task의 candidate/validation 갱신과 사용자 viewport 이동 뒤에는 반복 focus하지 않는다.
- 닫힘/최소화 panel 재진입, card scroll, mobile 동적 zoom과 node/handle/panel control 비중첩을 component 및 browser viewport에서 검증한다.

### DBP-TC-F006 Chat Scroll

- user message 제출 직후 pending message가 보이도록 scroll한다.
- assistant result와 active task가 추가되면 최신 content로 이동한다.
- 사용자가 과거 message를 읽는 중에는 불필요한 강제 scroll을 하지 않는다.
- panel은 mobile viewport에서 좌우 여백 안의 전체 너비를 유지하고 desktop viewport에서 화면 너비의 50%를 사용한다. 높이는 고정 최대값 없이 viewport에 맞춰 editor 상단 영역까지 확장하고 launcher는 하단 Flow 설정 island와 같은 control row에 정렬한다.

### DBP-TC-F007 Knowledge Selection

- 후보 3개 높이를 기본으로 하고 최대 20개까지 scroll한다.
- 0개 이상 선택할 수 있다.
- 미선택이 다른 후보를 자동 선택하거나 후보 목록을 숨기지 않는다.
- 다중 selection을 request에 모두 전달한다.

### DBP-TC-F008 Recovery

- latest request와 관계없는 과거 mutation을 표시하지 않는다.
- active parameter group을 올바른 card/task에서 복구한다.
- 새 요청이 terminal failed, unsupported 또는 validation failure로 끝나면 이전 request의 ParameterTask, Knowledge card와 완료 상태를 현재 결과 container에 표시하지 않는다.
- already-applied operation을 다시 workflow store에 적용하지 않는다.
- CDS 저장 전 operations 응답 유실은 재생성/재입력 안내를 표시하고 자동 적용하지 않는다. 저장 뒤 acknowledgement 유실은 canonical hash로 복구한다.
- legacy Preview session은 `stale_protocol` 안내만 표시하고 적용 action을 제공하지 않는다.
- `reverted` boundary의 대화는 읽기 전용 이력으로 표시하고 연결된 ParameterTask/Knowledge resolution은 모두 `canceled`로 복구한다. Parameter/Knowledge operation별 `reverted` 상태나 task 재활성화는 만들지 않는다.
- Knowledge selection 응답 유실 뒤 canonical `session.messages`와 `knowledge_resolution`을 upsert한다. `unapplied`는 같은 card와 선택값으로 재시도하고, `pending_ack`는 중복 제출을 막으며, `completed`는 stale card를 닫고 다음 설정으로 진행한다. Planner, 원래 message와 typed operations 호출 횟수는 늘지 않는다.

- legacy session 복구 또는 message 전송에서 `stale_protocol`을 받으면 저장된 session key를 제거하고 새 `direct_edit_v1` session으로 정확히 한 번 재시도한다.
- 새 session도 `stale_protocol`이면 추가 session 생성이나 무한 재시도 없이 세션 전환 실패 안내를 표시한다.
- Gateway `502/503/504`, network failure, permission/validation/CDS/task conflict는 서로 구분된 안전한 사용자 메시지로 표시한다. Raw response detail과 allowlist 형식이 아닌 error text는 사용자 메시지에 반영하지 않는다.

## 6. E2E And Manual Smoke

### DBP-TC-E001 Authoritative Knowledge Workflow Configure Flow

1. 실제 dev server에서 Agent Builder를 연다.
2. `단계별 생성`으로 Input -> KB-backed LLM -> Answer workflow를 요청한다.
3. 통합 workflow 설정 결과에서 `before_graph` Knowledge 후보가 먼저 표시되고 0개, 1개, 다중 선택을 각각 독립 run에서 제출한다. 같은 requirement의 legacy selector는 보이지 않아야 한다.
4. 선택 결과에 맞는 graph가 editor에 한 번 적용되는지 확인한다. Empty selection은 KB-free, 선택이 있으면 Knowledge-backed topology여야 한다.
5. CDS workflow 저장과 acknowledgement 뒤 node별 parameter card와 설명이 활성화되는지 확인한다.
6. 자동 추천 active card의 기존 값을 확인하거나 수정하고 unresolved required task는 값을 완료한다. Optional task 하나는 skip해 `skipped`로 남기고 다시 열어 설정한다. Catalog가 `allow_unresolved`로 허용한 task만 defer한다.
7. 각 parameter mutation도 CDS 저장/acknowledgement 뒤에만 완료되는지 확인한다.
8. 모든 필수 확인과 acknowledgement 뒤 같은 result group에 명시적인 생성 완료가 표시되는지 확인하고 저장된 workflow graph와 대화/task 상태를 확인한다.
9. Knowledge를 선택한 run의 별도 test 실행에서 Answer와 citation/retrieval 근거를 확인한다.

### DBP-TC-E002 Structure Only And Undo

1. `구조만 생성`을 선택한다.
2. 다중 node workflow를 요청한다.
3. parameter 질문 없이 graph가 생성되고 CDS 저장/acknowledgement되는지 확인한다.
4. Ctrl+Z 한 번으로 전체 graph 변경이 local과 server 저장 graph에서 모두 되돌아가는지 확인한다.
5. 새로고침 후 operation이 `reverted`이고 관련 task/Knowledge 흐름이 활성화되지 않는지 확인한다.
6. 새로고침 후 Redo history가 복구되지 않는지 확인한다.

### DBP-TC-E003 Existing Workflow Insert

1. 저장된 workflow와 target node를 선택한다.
2. target 뒤에 node를 삽입하도록 요청한다.
3. 새 Start/Answer wrapper나 detached graph가 생기지 않는지 확인한다.
4. 기존 edge가 올바르게 재연결되는지 확인한다.

### DBP-TC-E004 Knowledge Timing

1. topology-changing Knowledge request가 graph 생성 전에 후보를 표시하는지 확인한다.
2. binding-only request가 graph 생성 후 후보를 표시하는지 확인한다.
3. 아무 KB도 선택하지 않고 KB-free graph로 진행한다.
4. 두 KB를 선택하고 동일 RDG node binding에 반영되는지 확인한다.
5. Empty selection에서 planner 추가 호출이나 KB 재선택 질문이 없고 selected/empty graph의 node·edge 결과가 각각 기대값과 일치하는지 확인한다.

### DBP-TC-E005 Permission And Security

1. workflow write 권한이 없는 사용자로 수정 요청을 시도한다.
2. KB use 권한이 없는 후보를 선택한다.
3. credential config/secret-like 값을 parameter API에 제출한다.
4. API, audit, trace, browser console에 원문이 노출되지 않는지 확인한다.

### DBP-TC-E006 External Node Regression

1. Webhook -> LLM -> Slack graph를 구조만 생성한다.
2. 기존 intent model 권한 검증, generated model 추천과 KB 후보 표시가 유지되는지 확인한다. 모델 표시 순서 변경은 이 검증의 합격 조건이 아니다.
3. 생성과 parameter 설정 중 Slack 외부 요청이 발생하지 않는지 확인한다.
4. unresolved credential/channel 상태가 실행·배포 preflight에서 차단되는지 확인한다.
5. durable Mail 검색 -> LLM -> Gmail Draft -> Mail terminal acknowledgement graph를 생성하고 credential reference가 unresolved인지 확인한다.
6. 생성과 설정 과정에서 OAuth refresh, mailbox 조회, Gmail draft 생성, 읽음 처리 또는 전송 호출이 없는지 확인한다.
7. Mail send 요청이 unsupported로 닫히고 HTTP fallback을 만들지 않는지 확인한다.

### DBP-TC-E007 Boundary Redo Before Reload

1. 별도 structure-only 다중 node workflow를 생성하고 CDS 저장/acknowledgement한다.
2. Task가 없으므로 첫 Ctrl+Z가 persisted boundary Undo를 완료해 graph와 task/Knowledge 상태를 취소하는지 확인한다.
3. Reload 전에 Ctrl+Shift+Z로 final graph를 복구한다.
4. `action=redo` CDS save가 완료되는지 확인한다.
5. 새로고침 후 Redo graph가 server 저장 graph로 유지되는지 확인한다.
6. 취소된 Agent Builder 질문, parameter task, Knowledge 흐름과 진행 상태가 자동 복구되지 않는지 확인한다.

### DBP-TC-E008 Selector Recommendation And Task Actions

1. Webhook output을 downstream LLM 또는 Slack parameter에 연결하는 `단계별 생성` workflow를 요청한다.
2. Parameter card가 source node, output key, JSON path와 value type을 포함한 selector suggestion을 표시하는지 확인한다.
3. Suggestion을 선택하고 canonical selector가 `parameter_update` GraphMutation, CDS save와 acknowledgement 뒤 workflow graph에 저장되는지 확인한다.
4. Optional task의 skip/previous와 policy-allowed defer를 수행한다. Skip은 workflow save 없이 `skipped`가 되고 reload 뒤 유지되며, 다시 set하면 CDS acknowledgement 뒤 completed가 되는지 확인한다.
5. Required task의 skip control이 disabled/hidden이며 직접 API 제출도 거부되는지 확인한다.
6. Selector 값을 변조하면 graph와 task 상태가 변경되지 않는지 확인한다.

### DBP-TC-E009 Agent Builder Boundary Undo Sequence

1. `단계별 생성`으로 여러 node가 있는 graph를 생성하고 최초 `initial_graph`를 저장·acknowledgement한다.
2. 두 parameter를 차례로 설정하고 Knowledge binding 하나를 저장하되 Workflow history entry는 최초 boundary 하나뿐이고 final snapshot/hash만 갱신되는지 확인한다.
3. 완료 상태 첫 Ctrl+Z가 graph, 기존 값과 persisted task 상태를 유지한 채 `completed|skipped|deferred` 중 최대 stable order ParameterTask를 표시하고 닫힌/최소화 panel을 여는지 확인한다.
4. `이전 항목`이 backend `next_task_id`의 이전 parameter card와 node focus로 이동하면서도 Workflow history와 persisted task 상태를 변경하지 않는지 확인한다.
5. 재진입 상태의 다음 Ctrl+Z가 최초 생성 전 snapshot으로 서버 graph까지 CDS 복구하고 생성 node/edge, parameter 값과 KB binding을 제거하는지 확인한다.
6. 모든 ParameterTask/Knowledge resolution이 `canceled`인지, Redo가 final graph만 복구하고 canceled 흐름을 재실행하지 않으며 그 뒤 Undo가 parameter 재진입 없이 즉시 boundary를 revert하는지 확인한다.
7. Parameter input과 card/button focus에서는 canvas Undo가 실행되지 않고 첫 Undo 직후 canvas focus에서는 다음 Undo가 전체 복구로 이어지며, 완료 뒤 수동 편집 history가 boundary보다 먼저 Undo되는지 확인한다.
8. Reopened text/number/boolean/select/JSON/selector control이 canonical graph의 safe value로 초기화되고 task/session payload에는 값이 없으며 secret과 권한 없는 reference ID/label이 표시되지 않는지 확인한다.
9. Desktop/mobile에서 panel을 제외한 가시 canvas 영역에 node와 주요 handle이 표시되고 card/control이 겹치거나 잘리지 않는지 확인한다.
10. Revert/redo commit 뒤 response loss를 각각 발생시켜 동일 context 재시도와 canonical 판정이 중복 write/audit 없이 성공하는지 확인한다.

### DBP-TC-E010 Direct-Edit Consistency Hardening

1. Agent Builder가 발급한 managed `credential_ref` task가 자동 deferred가 아니라 active/pending인지 확인하고, policy-allowed explicit defer가 CDS save/acknowledgement 뒤에만 deferred가 되는지 확인한다. Mail처럼 resolver가 있는 provider는 권한과 node runtime compatibility를 통과한 후보만 반환하고 Gmail Draft 후보와 제출은 Gmail OAuth2만 허용하는지 확인한다. Slack/GitHub credential task, 후보, token 입력과 defer control은 direct-edit response에 없고, 결과 UI의 기존 Editor 연결 설정 이동만 제공하는지 확인한다.
2. Direct response의 Knowledge 후보가 `knowledge_resolution.candidates`에만 있고 legacy clarification field 제출과 legacy/direct 교차 중복 제출이 거부되는지 확인한다.
3. KB save 실패와 response loss에서 같은 card/selection을 유지하고 canonical recovery 뒤 중복 mutation이나 사용자 메시지가 없는지 확인한다.
4. 같은 `confirm|set|defer|skip|cancel` operation/payload 재시도가 GraphMutation, task 전환, commit과 audit를 한 번만 만들고 같은 id의 다른 payload는 conflict인지 확인한다.
5. Draft save/read 실제 응답이 canonical `graph_hash`와 DB `updated_at`을 반환하고 Agent Builder save, autosync와 Undo/Redo fixture가 같은 metadata를 사용하는지 확인한다.
6. 일반 autosync와 Agent Builder save가 같은 base에서 경쟁할 때 row lock/CDS로 하나만 성공하고 다른 요청은 `409 stale_graph`인지 확인한다.
7. 저장 결과가 불명확하면 pending history를 유지하고, acknowledgement 성공 뒤 session read 실패는 `완료 확인 중`으로 복구되며 terminal 확인 전 완료/Undo가 활성화되지 않는지 확인한다.
8. 첫 Undo가 secret/credential/deferred task도 최대 stable order 기준으로 재진입하되 raw secret과 권한 없는 reference를 표시하지 않는지 확인한다.
9. Completed task 편집 중 완료 표시가 숨겨지고 취소/닫기, 입력 보존과 acknowledgement 뒤 완료 복귀가 동작하는지 확인한다.
10. 추천 출처 4개와 before/after Knowledge CTD 4개를 exact component copy로 확인한다.
11. Reload와 `stale_protocol`에서 만료되지 않은 복수 request의 safe conversation을 시간순으로 유지하고, stale session에서는 이를 읽기 전용으로 표시하며 legacy Preview 정보를 복원하지 않고 신규 direct session 전환이 한 번만 일어나는지 확인한다.
12. Preview/apply E2E가 제품 경로에 남지 않고 `KB 선택 -> 자동 추천 confirm -> 필수 parameter 입력 또는 명시적 defer -> save/acknowledgement -> completion -> Undo/Redo`와 response-loss E2E로 대체됐는지 확인한다. KB 선택 직후 완료를 기대하지 않는다.
13. Direct candidate가 비어 있을 때 legacy clarification fallback을 frontend와 backend가 모두 거부하고, allowlisted KB reason만 사용자 문구로 표시하는지 확인한다.
14. `before_graph` structural Knowledge response loss가 resolution을 `unapplied`로 복구하고 같은 card에서 새 operation으로 재시도되는지 확인한다.
15. Acknowledgement 성공 뒤 session read 실패가 `완료 확인 중`으로 남았다가 terminal read 뒤 completion과 첫 Undo를 활성화하는지 확인한다.
16. 제3 canonical graph가 반환되는 ambiguous save에서 Workflow history boundary, redo memory와 pending context가 보존되는지 확인한다.
17. direct-edit response와 legacy session 정규화 뒤 Slack/GitHub credential task, 빈 picker, token 입력, defer control이 없고 결과 UI의 `연결 설정으로 이동`만 기존 Editor 설정을 여는지 확인한다.

## 7. Non-Functional Verification

### DBP-TC-N001 Module Cohesion

- endpoint가 graph operation, task order 또는 permission query를 직접 구현하지 않는다.
- application, domain service, DB adapter와 composition dependency 방향을 import/static test로 검증한다.
- application import 검증은 shared Pydantic contract를 허용하되 FastAPI, SQLAlchemy, DB model과 concrete Gateway service/adapter를 차단한다.
- Agent Builder DB integration과 CAS 경쟁 테스트는 disposable PostgreSQL 전용 CI에서 실행하고 DB가 없는 일반 Gateway test selector에서는 제외한다.

### DBP-TC-N002 Coupling

- frontend parameter renderer에 node type별 form switch가 없다.
- backend GraphMutation builder가 React Flow component 또는 browser API를 import하지 않는다.
- runtime output 변경이 catalog contract test 실패로 전파된다.

### DBP-TC-N003 Determinism

- 같은 structured plan, catalog v3와 base graph를 반복 입력하면 operation order와 parameter task 순서가 같다.
- suggestion score 동점에서 고정된 tie-break 결과를 반환한다.

### DBP-TC-N004 Accessibility And Responsive Layout

- 모든 typed control은 label, error association과 keyboard focus를 제공한다.
- desktop/mobile viewport에서 parameter card, validation message와 focused node가 서로 가리지 않는다.
- 긴 label과 validation message가 container를 벗어나지 않는다.

## 8. Test Matrix

| Requirement | Primary tests | Level |
|---|---|---|
| DBP-FR-001 | F001, I003, E002 | component/integration/e2e |
| DBP-FR-002 | U001, U002, I002, F004, E001 | unit/integration/component/e2e |
| DBP-FR-003 | S001, S002, S003, U002 | static/unit |
| DBP-FR-004 | S003, U003, U004, U005, I005, I010, E003 | static/unit/integration/e2e |
| DBP-FR-005 | S003, F002, I004, I010, I013, E002, E003, E007, E009 | static/unit/integration/e2e |
| DBP-FR-006 | U006, I002, I015, F003, F004, E001 | unit/integration/component/e2e |
| DBP-FR-007 | S003, I006, I015, F004, E008 | static/integration/component/e2e |
| DBP-FR-008 | U007, I006, F004, E008 | unit/integration/component/e2e |
| DBP-FR-009 | F003, F005, F006 | component |
| DBP-FR-010 | S003, U008, I007, F007, E004 | static/unit/integration/component/e2e |
| DBP-FR-011 | U005, U009, F007, E006 | unit/component/e2e regression |
| DBP-FR-012 | S001, I004, I008, I012, I014, F008 | static/migration/integration/component |
| DBP-FR-013 | I001, I003, I011, E005 | integration/e2e |
| DBP-FR-014 | U010, I009, I010, E005 | unit/integration/e2e |
| Direct-edit consistency hardening | E010 | unit/integration/component/e2e |
| DBP-NFR-001 | N001 | static/architecture |
| DBP-NFR-002 | N002, S002, F004 | static/unit/component |
| DBP-NFR-003 | N003, U004, U006, U007 | unit |
| DBP-NFR-004 | N004, F004, F005, E001 | component/e2e |
| Cross-document release gate | S004 | static/docs |

## 9. Completion Gate

- static/type/lint가 통과한다.
- backend unit/integration과 frontend component test가 통과한다.
- DB integration은 순차 실행한다.
- E001~E009의 핵심 demo와 regression flow를 실제 dev server에서 확인한다.
- permission, audit, secret boundary, Knowledge status, graph apply와 persisted Undo 검증을 실행한다.
- local apply/CDS save/acknowledgement 순서, safe envelope의 expected result hash, full operations 비영속화, 저장 전 응답 유실의 재생성·재입력, 저장 뒤 acknowledgement 복구, 동시 저장 stale와 parameter task row-lock/version/idempotency 검증을 실행한다.
- legacy clarification characterization/parity, Alembic single head, disposable 기존 DB upgrade, request 없는 null/direct mixed read, `stale_protocol` 복구와 additive schema 유지 검증을 실행한다.
- Structure-only browser E2E D에서 save/acknowledgement, persisted Undo, reload와 Redo history 미복구를 확인한다.
- 독립된 browser E2E B에서 전체 Undo, reload 전 final-graph CDS Redo, reload와 Agent Builder task 미복구를 확인한다.
- typed Knowledge placement의 selected/empty topology, 명시적 skipped 상태, client-only ParameterTask 재진입과 서버 계산형 `configuration_state`를 검증한다.
- 통합 Knowledge/Parameter UI, legacy Knowledge 중복 방지, 자동 추천 confirm 멱등성, 명시적 생성 완료 gate와 canonical completed task의 previous navigation을 검증한다.
- unresolved 실행·배포 preflight와 mutation audit/redaction 검증을 실행한다.
- DBP-NFR-001~004가 Test Matrix에 매핑되어야 한다.
- 실행하지 못한 필수 검증은 사유와 남은 위험을 기록하며 완료로 처리하지 않는다.
## 2026-07-15 Connection Navigation And Recovery Cases

- Canonical graph recovery after acknowledgement loss, persisted Undo, persisted Redo, and ambiguous save assigns editor-only edge display numbers without changing the serialized workflow graph or graph hash.
- A Slack/GitHub direct-edit plan exposes configuration guidance but no `credential_ref` task, credential candidate, empty picker, or Agent Builder token field. Mail/Gmail still expose only permitted managed credential candidates.
- A `연결 설정으로 이동` action selects/focuses the unresolved Slack/GitHub node and opens the existing Editor connection control without mutation, save, planner call, or external request.
- A `Routing 설정으로 이동` action opens the selected LLM Routing control rather than only changing the viewport; an already enabled routing node has no guidance.
- A recommended parameter is preselected with alternate choices, stays active until explicit confirmation, and sends no GraphMutation/save when confirmed unchanged.
- Failed KB selection retains selected candidates and classifies permission, stale, validation, pending acknowledgement, and retryable unapplied outcomes without resubmitting natural language or rerunning the planner.
- A reference task hydrates canonical graph values by `candidate_id` or `reference_value`. A deleted or unauthorized reference is unavailable and cannot be treated as complete.
- The result container renders explicit workflow completion only after terminal acknowledgement and reopens a completed task through its edit action.

## 2026-07-14 Regression Cases

- Knowledge 후보가 둘 이상인 clarification/selection card는 상단부터 추천 점수 내림차순이라는 설명과 `1순위`부터의 순위를 표시한다. 후보가 하나면 순위 설명과 순위를 표시하지 않는다.

- Dn after-graph Knowledge selection mutation includes both the UUID `id` and safe `name` for every `knowledgeBases` reference, and the resulting graph passes workflow graph validation before CDS draft save.
- D recommended parameter renders its recommended candidate as selected and displays an alternate candidate. Applying the unchanged recommendation sends `confirm`; applying the alternate sends `set`; neither path completes before the explicit apply action.
- The routing guidance settings button opens the target LLM node's editor settings view and does not issue a GraphMutation, save, or planner request.

- 일반 LLM 생성의 canonical `guided_generate` 요청과 legacy `configure_and_generate` 호환 입력은 `after_graph + binding_only` Knowledge resolution과 target LLM step을 만든다.
- use 권한은 있으나 active ready version이 없는 KB도 candidate/selection에서 선택할 수 있고, run/deployment preflight에서만 unresolved로 차단한다.
- Agent Builder `knowledge_binding` CAS 저장은 권한/lifecycle을 계속 검증하면서 retrieval readiness가 없는 선택 KB도 저장할 수 있고, 일반 Editor 저장은 같은 KB를 계속 거부한다.
- `safe_query_topics`가 하나 이상의 KB safe label/description/topics와 매칭되면 intent/node-purpose fallback을 사용하지 않는다. 모든 후보가 무매칭일 때만 fallback하며, 최종 `kb_relevance=0` 후보의 score는 source tier, availability, freshness와 관계없이 `0`이다.
- Knowledge 또는 ParameterTask 카드가 active일 때 새 자연어 composer와 Send control이 disabled되지 않는다.
- graph edit auto-layout은 새 node뿐 아니라 이동한 기존 node에 `replace_node_position` operation을 발급하고, CDS 저장 graph에 해당 위치가 남는다.
- stale canvas에 같은 node ID가 남아도 Agent Builder mutation은 canonical draft graph를 base로 적용하고 저장한다.
- 화면 전용 `displayNumber`는 Agent Builder CDS 저장 request와 canonical graph hash에 포함하지 않는다.
- Agent Builder GraphMutation으로 추가된 node와 canonical base graph의 기존 node는 local editor 반영 시 모두 유효한 `displayNumber`를 가진다. 이 번호는 BaseNode의 source/target 연결 handle에 표시되며 저장 request에는 포함하지 않는다.
- 빈 Start/Answer workflow는 ParameterTask 없이 저장·acknowledgement 후 완료 상태로 진행한다.
- schema-invalid planner 응답은 provider 호출 한 번 뒤 repair 없이 fail-closed한다. 완결된 Start-to-Answer 흐름을 unsupported로 반환한 schema-valid semantic 모순만 safe repair prompt를 한 번 보내며, 수정된 `start_input -> answer` structured response를 정상 처리한다.

### MBA-275 Direct-Edit Consistency Cases

- direct `set`의 secret-like 값과 detector 오류는 fail-closed하며 `400 invalid_decision`만 반환하고 graph/session/task/audit/trace/log에 원문이 남지 않는다. 일반 Catalog validation issue는 HTTP 오류가 아니라 `status=invalid`, `reason=catalog_validation_failed` task 결과로 저장·반환된다.
- `credential_ref`/`resource_ref`의 raw config와 미검증 id는 거부하고, 서버가 검증한 canonical reference만 저장한다.
- WorkflowNode는 유효한 `appId`만으로 실행 admission을 통과하고 빈 `workflowId`는 오탐 차단하지 않는다. `appId`를 직접 교체할 때 stale 또는 legacy `workflowId`는 선택된 App의 canonical Workflow로 정규화된다. `workflowId`를 직접 교체한 mismatch와 숨김 resource·권한 부족은 safe 4xx로 끝나며 부분 mutation을 남기지 않는다.
- PostgreSQL 두 session 경쟁에서 stale identity-map을 가진 CAS 요청은 locked 최신 row를 기준으로 `409 stale_graph`가 되고, 선행 commit의 graph/hash/updated_at을 보존한다.

## MBA-293 Generation Mode Target Cases

### Static And Schema

- Shared/Gateway/Client canonical enum은 `guided_generate|quick_generate|structure_only`이고 신규 default는 `guided_generate`다.
- Legacy `configure_and_generate`는 transport parsing, 기존 JSON read와 `legacy-v1` 외부 응답에서만 허용되고 application result, 저장 metadata와 `canonical-v2` 응답에는 나타나지 않는다.
- Request가 없을 때 header가 없거나 `legacy-v1`이면 legacy 표현, `canonical-v2`이면 canonical 표현을 반환하고 지원하지 않는 contract는 `unsupported_mode_contract`로 거부한다. Raw header는 저장하지 않지만 message request에는 normalized `mode_contract_version`을 고정하며 contract가 없는 기존 row는 legacy로 읽는다.
- `legacy-v1` schema에는 quick mode가 없고 canonical quick 직접 입력은 request row 생성 전 `unsupported_generation_mode`로 거부된다. Legacy default 요청의 자연어 quick intent는 requested mode를 바꾸거나 transition metadata를 만들지 않는다.
- `generation_mode_source=default|explicit_control`, `mode_transition_required`, requested/effective mode, transition/proposal id와 monotonic request/proposal version schema가 frontend/backend에서 일치한다.
- ParameterTask의 `reconfirmation_required` boolean이 Shared/Gateway/Client schema에서 일치하고 true일 때 `resolution_source`와 graph value가 비어 있으며 `confirm` action이 허용되지 않는다.
- Quick review와 proposal의 persisted safe schema에는 full typed operations, raw graph, parameter 값, 값 의존 graph fragment, hidden resource id, credential 또는 raw prompt가 없다. Quick-to-guided 전환에는 Catalog 검증된 재입력 대상 `step_id`/`parameter_key`만 저장할 수 있다.
- ADR-0054와 PRD, architecture, data model, glossary, Agent Builder 4종 문서의 mode 이름, 기본값, endpoint와 Legacy Preview 금지가 일치한다.
- ADR-0054의 contract-before-planning, durable-state-only, every-nonterminal-cancelable, authorize-final-graph-at-save와 Request aggregate 불변조건이 API 상태표, data model 허용/금지 데이터와 Backend/Frontend 테스트 항목에 각각 연결되어 있다. Terminal parent 아래 pending child 금지, idempotency-result-first 조회, proposal task fencing과 retained canonical history rollback gate를 포함한다.

### Unit Policy

- Mode 생략, explicit guided, explicit quick, structure-only와 legacy alias를 canonical mode로 결정론적으로 정규화한다.
- `explicit_control` mode와 자연어 intent가 충돌하면 UI 선택을 requested mode로 사용하고 planner가 이를 덮어쓰지 않는다. `canonical-v2` default guided 상태에서 명시적인 "한 번에" 자연어 intent가 있으면 requested quick으로 진행하고 intent가 없으면 guided다. 같은 문장의 `legacy-v1` 요청은 guided를 유지하고 quick eligibility/transition을 실행하지 않는다.
- Legacy client가 mode를 보내고 source를 생략하면 explicit control로 해석해 기존 동작을 보존한다.
- 모든 capability/parameter/resource/revision이 안전한 fixture만 quick eligible이다.
- Credential, 권한 KB/Collection, 일반 required parameter에 사용자 요청·기존 graph·selector·안전한 default 값이 없는 경우, 외부 target, Condition branch, HTTP/code/egress, unresolved external action, 의미 있는 복수 후보와 stale/hidden resource fixture는 각각 fail-closed reason code를 반환한다. 일반 값 부재는 `configuration_value_required`다.
- Eligibility result는 resource id/name, 정확한 후보 수, raw URL/path와 secret을 포함하지 않는다.
- Initial quick과 `remaining_configuration` scope가 같은 primitive를 사용하되, remaining scope는 completed/skipped/deferred task를 입력 대상에서 제외한다.
- Mode transition과 remaining quick completion은 planner를 호출하지 않는다.
- Quick 판정에서 읽은 사용자 parameter 값은 transition metadata에 저장되지 않고 safe reconfirmation descriptor만 남는다. Continue-guided 결과는 해당 값을 materialize하지 않으며 `resolution_source=null`, `reconfirmation_required=true` task를 생성한다.

### Backend Integration

- Eligible quick message는 `graph_mutation_ready`, effective quick mode, `pending_apply` GraphMutation과 safe summary를 반환하고 parameter group을 만들지 않는다. Quick GraphMutation도 `workflow_id`, base/result graph hash, expected workflow `updated_at`, Catalog version, full operations, affected node ids와 completion context를 모두 포함한다.
- Ineligible quick message는 `mode_transition_required`와 null GraphMutation을 반환하며 workflow graph, request task와 audit의 mutation state를 변경하지 않는다.
- `continue_guided`는 보존된 값 독립 structured plan으로 guided GraphMutation/task를 만들고 planner call count를 늘리지 않는다. 최초 요청이 일반 parameter 값을 포함했어도 reload 또는 다른 Gateway replica에서 전환하면 그 값이 graph/response metadata에서 복구되지 않고 typed reconfirmation task로 열린다.
- Transition은 client operation id와 expected request version으로 멱등하며 stale/competing 요청은 `mode_transition_conflict`다.
- `continue_guided`가 GraphMutation을 발급한 뒤 응답이 유실되면 같은 operation 재시도는 mutation을 다시 만들거나 planner를 호출하지 않고 `operation_payload_unavailable`과 safe 상태를 반환한다. Client는 기존 request의 contract-neutral cancel 결과가 terminal `canceled`임을 확인한 뒤 새 message request를 명시적으로 제출한다.
- Transition 취소는 별도 mode-transition action을 만들지 않고 기존 request cancel endpoint만 호출한다.
- Request cancel parameterized test는 `planning|clarification_required|mode_transition_required|graph_mutation_ready|parameter_configuration`를 모두 terminal `canceled`로 전환한다. 같은 transaction에서 남은 task와 미완료 Knowledge resolution, pending quick-completion proposal, 저장 전 operation envelope를 각각 `canceled|blocked`로 닫고 변경되는 task/proposal version을 정확히 한 번 증가시킨다. Terminal request 아래 pending child가 남지 않고 늦게 도착한 planner/transition/task/proposal 결과는 commit되지 않으며 persisted graph와 완료 task 값은 유지된다. 이미 canceled 재시도는 멱등이고 그 밖의 terminal 상태는 `request_not_cancelable`이다.
- `configuration_required`는 terminal 상태로 schema/API/Client가 처리하고 cancel 대상에 포함하지 않는다. Intent model/credential route 선택 뒤에는 기존 request를 재개하지 않고 새 message request를 제출한다.
- Message submit은 provider 호출 전에 session lock으로 단일 `planning` row와 mode contract/source를 commit한다. 명시적 control과 `legacy-v1` default는 canonical requested/effective mode를 즉시 저장하고, `canonical-v2` default는 두 mode를 미확정으로 유지한 뒤 schema-valid planner의 명시적 intent 또는 guided fallback으로 정확히 한 번 확정한다. Planner 실패·취소 시 미확정 mode를 추측해 채우지 않는다.
- 동기식 message provider를 barrier로 지연시킨 상태에서 별도 HTTP client가 session-scoped active-request cancel을 호출하면 아직 response에 노출되지 않은 유일한 `planning` request가 terminal `canceled`가 된다. 응답 유실 후 새 request를 만든 fixture에서 같은 cancel operation을 재시도하면 backend가 active row보다 terminal request의 persisted operation result를 먼저 조회해 최초 request id/status를 반환하고 새 request는 유지한다. Persisted 결과가 없을 때만 active row 0건은 `active_request_not_found`, legacy fixture의 2건은 `active_request_ambiguous`, competing message submit은 `request_in_progress`다.
- Cancel 전에 시작된 provider attempt의 검증 가능한 usage는 정확히 한 번 완료되지만 늦은 planner 결과는 저장되지 않고 semantic repair attempt 2도 예약·호출되지 않는다. Schema-invalid attempt도 usage 기록 여부와 무관하게 repair하지 않는다. Usage 저장 실패는 terminal `failed`와 safe issue code를 사용하고 별도 RequestStatus를 만들지 않는다.
- Cancel과 CDS save가 경쟁하는 PostgreSQL test는 request/workflow lock 뒤 저장 전 operation이면 graph를 쓰지 않고 blocked/canceled로, 저장이 먼저 확정됐으면 persisted graph를 유지한 canceled request로 결정론적으로 수렴한다.
- Quick GraphMutation도 기존 CDS row lock, permission, graph hash, `updated_at`, Catalog validation과 acknowledgement를 통과한 뒤에만 completed가 된다. 발급 뒤 저장 전에 workflow write, Catalog `resource_ref`, managed `credential_ref`, Knowledge/Collection 또는 WorkflowNode App/Workflow 권한·lifecycle·relation을 회수/삭제/변경하는 fixture는 final candidate graph에서 reference를 다시 추출해 전체 save/audit를 rollback한다. Unknown field와 managed resolver 누락도 fail-closed한다.
- Resolver 미구현 기존 Slack/GitHub Editor connection이 base graph와 candidate에서 canonical field 값 및 connection-relevant node data가 같으면 다른 node의 Agent Builder mutation 저장을 허용한다. 같은 legacy field의 추가·교체·삭제, 새 node 복제 또는 connection-relevant data 변경은 전체 save/audit를 rollback한다. Carry-forward 뒤에도 test/run/deployment/runtime의 기존 연결 검증을 통과하지 않으면 외부 호출은 차단된다.
- Quick response가 save 전에 유실되면 safe envelope에서 operations를 복원하지 않고 `operation_payload_unavailable`로 닫는다. 기존 request가 여전히 `graph_mutation_ready`일 때 새 message는 `request_in_progress`로 거부되며, Client가 request cancel의 terminal 결과를 확인한 뒤에만 새 operation id로 재제출할 수 있다. Save 뒤 acknowledgement 유실은 기존 canonical reconciliation만 사용한다.
- Remaining quick proposal은 acknowledged graph와 completed task를 보존하고, canonical graph 값과 fingerprint가 일치하는 no-change confirm만 포함한다. 값이 없거나 graph 변경이 필요한 task는 guided 상태로 남긴다.
- Remaining proposal 생성은 parent request row lock에서 expected request/task version을 비교하고 request와 각 confirm 대상 task version을 정확히 한 번 증가시켜 fenced id/version/fingerprint를 저장한다. 같은 operation 재시도는 어떤 version도 다시 증가시키지 않는다. Proposal 이전 version의 늦은 `set`과 pending proposal target에 대한 최신-version decision도 `task_conflict`이며 remaining guided task는 계속 진행할 수 있다.
- Remaining proposal acknowledgement는 fenced task version, permission, Catalog, canonical graph 값과 recommendation fingerprint를 다시 검증하고 GraphMutation/workflow save를 만들지 않는다. 성공은 request/proposal과 각 completed task version을 다시 한 번 증가시키고 응답에 task id/version/status를 포함한다.
- Remaining proposal cancel은 request/proposal version을 각각 한 번 증가시켜 target 예약을 해제하고 proposal만 canceled로 전환하며 guided request, graph와 task 값을 유지한다. 생성 시 증가한 task version은 되돌리지 않는다. 같은 cancel 재시도는 같은 version을 반환하고 acknowledged/stale proposal은 conflict다.
- Remaining proposal 일부가 stale이면 request/proposal version을 증가시키고 proposal 전체를 terminal `stale`로 전환해 예약을 해제한 뒤 `quick_completion_conflict`를 반환한다. 기존 guided graph/task 값은 유지한다.
- `structure_only` unresolved graph는 저장할 수 있지만 test, run과 deployment preflight를 계속 차단한다.
- PostgreSQL 경쟁 테스트에서 같은 transition/proposal operation 재시도는 한 상태 전이만 commit하고 다른 version 요청은 기존 row를 덮어쓰지 않는다. Full operations가 비영속화된 transition replay는 동일 payload 대신 `operation_payload_unavailable`을 반환한다.
- Mixed-version 계약 테스트는 구형 Client/신형 Gateway에서 legacy 응답, dual-read Client/legacy Gateway에서 legacy fallback, canonical-v2 Client/준비된 Gateway에서 canonical 응답, 지원하지 않는 contract 거부를 각각 검증한다. Canonical-v2 quick request를 만든 뒤 header 누락/legacy session GET은 active payload 대신 `mode_contract_mismatch`를 반환하고, canonical 재조회와 mode-free cancel은 성공해야 한다.
- Rollback 테스트는 canonical/quick creation gate를 닫고 active canonical-v2 request를 완료·취소해 0건이 되면 legacy-write로 전환할 수 있음을 검증한다. 그러나 완료된 quick request가 session 보존 기간에 남은 동안 legacy-only Client/Gateway 단계는 차단되고 dual-read timeline이 stored canonical contract를 그대로 표시해야 한다. Terminal history까지 포함한 retained canonical aggregate가 0건이 된 뒤에만 legacy-only cutback이 가능하며 completed quick을 guided로 projection하거나 숨기지 않는다.

### Frontend Component

- 같은 guided UI 상태가 legacy `configure_and_generate`와 canonical `guided_generate` 응답을 모두 정상 선택 상태로 표시한다. 알 수 없는 mode를 무선택 상태로 대입하지 않는다.
- Legacy contract에서는 빠른 생성 control과 자연어 quick 전환 prompt를 노출하지 않는다.
- Client는 Gateway canonical-v2 gate가 확인되기 전 legacy-write를 유지하고, 협상 성공 뒤에만 canonical mode를 전송한다. Active request의 `mode_contract_version`을 보존해 후속 호출에 재사용하고 mismatch가 지원 contract를 가리키면 같은 GET을 한 번만 재시도한다. 오래 열린 request 없는 legacy session은 legacy 응답을 계속 처리할 수 있다.
- Mode control은 기본 단계별 생성, 빠른 생성, 고급 구조만 생성 값을 표시하고 pending request 중 새 request mode 변경을 막는다.
- Quick ineligible 상태는 allowlisted 설명과 `단계별 생성으로 계속`/`취소`를 표시하며 자동 전환 요청을 보내지 않는다.
- Transition response의 reconfirmation task는 최초 parameter 값을 prefill하거나 Client memory에서 자동 제출하지 않고 빈 typed control과 안전한 재입력 안내를 표시한다.
- `configuration_value_required`는 hidden resource나 후보 수 없이 `필수 설정값을 확인해야 합니다`로 표시하고 unknown reason은 raw enum을 노출하지 않는다.
- Quick review는 actual workflow store와 분리된 cloned graph에서 dry-run하고 `생성 적용` 전 nodes, edges, unsaved flag와 history를 변경하지 않는다.
- `생성 적용` 한 번이 기존 atomic GraphMutation dispatcher와 한 history boundary를 사용한다. Double click과 response retry가 중복 node/edge/history를 만들지 않는다.
- Quick review UI는 Legacy Preview component/import/route를 사용하지 않고 `Preview Mode` 또는 legacy `적용 및 저장` control을 렌더링하지 않는다.
- Guided result의 `남은 설정 빠르게 완료`는 현재 result에만 표시하고 proposal review 중에도 완료된 card/value를 유지한다.
- Pending remaining proposal의 confirm 대상 task card는 편집을 잠그고 cancel/stale/acknowledge 뒤 canonical task version을 다시 읽는다. 다른 tab의 `task_conflict` 결과를 자동 재적용하지 않는다.
- Remaining quick conflict는 기존 active task와 input draft를 유지하고 자동 재요청·자동 apply하지 않는다.
- Remaining quick review 취소는 guided result를 닫지 않고 proposal만 제거하며, initial quick review와 mode-transition 대기 취소는 기존 request cancel을 사용한다.

### Browser E2E

- 기본 mode로 workflow를 생성하면 guided structural save/acknowledgement 뒤 첫 Knowledge/Parameter card가 활성화된다. Canonical graph에 required 값이 모두 유효하게 materialize된 fixture는 card가 `pending|active`여도 run/deploy preflight를 통과하고, missing/deferred/invalid graph fixture만 차단된다.
- 안전한 Start-to-Answer 요청을 quick으로 생성하면 변경 요약 전 graph가 그대로이고, `생성 적용` 뒤에만 graph가 CAS 저장되며 한 번의 Undo로 시작 전 graph를 복구한다.
- Credential 또는 Knowledge 선택이 필요한 quick 요청은 graph를 바꾸지 않고 guided 전환 확인을 표시하며, 확인 뒤 기존 prompt/planner를 재실행하지 않고 단계별 card를 연다.
- 일반 parameter 값과 credential/resource 확인이 함께 필요한 quick 요청은 reload 뒤 guided 전환해도 원래 parameter 값을 복원하지 않고 해당 typed card에서 재입력을 요구하며, 입력 전 graph에는 그 값과 값 의존 edge/data가 없다.
- Guided 중 일부 task 완료 뒤 남은 설정 quick completion을 적용하면 기존 완료 값과 history boundary가 유지되고 이미 materialize된 안전한 추천만 batch confirm된다. 값 변경이 필요한 나머지는 guided card에 남는다.
- Quick review에서 reload하면 full operations를 복구하거나 자동 적용하지 않는다. 재생성 control은 기존 request cancel의 terminal 결과를 확인한 뒤에만 새 message를 제출하며 cancel 확인 중에는 비활성이다.
- Canonical-v2 quick review 중 header가 누락된 reload는 legacy projection을 렌더링하지 않고 contract mismatch 뒤 canonical GET으로 복구하며, rollback 시 mode-free cancel 뒤 legacy Client로 전환한다.
- Structure-only unresolved 결과는 저장 후에도 test, run과 deploy command가 server preflight에서 차단된다.

### Security And Observability

- Quick/guided/remaining transition은 동일한 active organization, workflow write, resource permission과 secret detector를 통과한다.
- Quick review 발급과 CAS apply 사이에 참조 resource 권한이 회수되거나 resource/relation이 바뀌면 server가 final graph에서 reference inventory를 다시 만들고 resource hiding을 적용한 4xx로 전체 transaction을 거부한다. 발급 시점 allow 결과나 Client inventory만으로 저장하지 않는다.
- Planner가 quick eligible이라고 주장하거나 malicious reason/resource payload를 반환해도 server policy가 이를 무시하고 fail-closed한다.
- API, audit, trace와 UI reason에는 full operations, secret, credential config, hidden KB/Collection, raw URL/path, raw prompt와 정확한 차단 후보 수가 남지 않는다.
- Audit은 requested/effective mode, allowlisted reason, transition/proposal outcome과 operation/hash만 구분하며 graph/parameter 원문을 저장하지 않는다.
