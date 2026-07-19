# Agent Builder Protected Resource Completion Matrix

Status: Verification Blocked

Verified Against: feature/mba-277 @ 9341ed3d

이 문서는 MBA-331의 보호 리소스 기능 완결성 기준을 Agent Builder direct-edit 변경에 적용한 PR-visible 증거다. 상세 실행 이력은 로컬 작업 기록과 분리하며, 아래 행은 현재 계약·구현·검증 증거만 유지한다.

`122 passed`와 `121 passed` 증거는 위 commit에 고정한다. 이후 working tree correction은 별도 RED/GREEN 결과로 기록하며 commit 전에는 위 검증 SHA에 포함하지 않는다. 아래에서 역사적이라고 표시한 수치는 현재 완료 증거로 사용하지 않는다.

## 대상

| 항목 | 내용 |
| --- | --- |
| 기능/이슈 | MBA-277 Agent Builder direct-edit bug correction |
| 보호 리소스 | Knowledge Base, Knowledge Collection, Mail/Gmail credential reference, Slack/GitHub node-owned secret configuration |
| durable reference 위치 | Workflow graph node data, Agent Builder safe operation envelope, ParameterTask safe metadata |
| 실행 진입점 | Agent Builder message/Knowledge/parameter endpoints, workflow draft CAS save, deployment/test preflight, Workflow Engine runtime |
| 외부 I/O | Agent Builder 생성 중 없음. 저장된 workflow 실행 시 Knowledge retrieval과 provider adapter가 수행함 |
| 권위 문서 | ADR-0045, ADR-0046, ADR-0061, `docs/features/agent-builder/{requirements,api_spec,component_spec,test_cases}.md` |

## 경계 상태

| 경계 | 상태 | 계약 증거 | 구현 위치 | 검증 증거 | 해당 없음 사유 또는 남은 검증 |
| --- | --- | --- | --- | --- | --- |
| 정책·식별자·organization scope | 완료 | ADR-0045 Knowledge/credential/secret 경계, ADR-0061 opaque handle 계약 | `KnowledgeSelectionService`, `KnowledgeCandidateResolver`, workflow permission helpers | `test_agent_builder_knowledge_selection.py`, `test_knowledge_permission_phase2.py` |  |
| 관리 API command/query | 해당 없음 | Agent Builder는 Knowledge/credential을 생성·수정·삭제하지 않고 기존 use-permitted resource만 선택함 | 기존 Knowledge/Mail credential 관리 API를 재사용 | Agent Builder service tests에서 후보 권한과 lifecycle 재검증 | 관리 API 정책 자체는 이 변경의 소유 범위가 아님 |
| 관리 UI·catalog·picker | 완료 | ADR-0045 typed ParameterTask와 ADR-0061 hierarchy-only Knowledge card | `KnowledgeSelectionControl`, `ParameterInputRenderer`, `NodeParameterCard`, `AgentBuilderPanel` | Current working tree frontend 3 files / 122 passed; TypeScript와 targeted lint 통과 | 인증된 실제 browser smoke는 미실행 |
| 저장 schema·GraphMutation·redaction | 완료 | ADR-0045/0046 safe envelope, secret 비복제, typed mutation | `workflow_node_catalog.py`, `parameter_task_service.py`, `ParameterInputRenderer.tsx` | `test_workflow_node_catalog.py`, `test_agent_builder_parameter_tasks.py`, focused frontend tests | Slack/GitHub secret은 `agent_builder_task=false`이며 Agent Builder API/task/card/save 경계를 통과하지 않음 |
| Deployment/test preflight | 완료 | Catalog 전체 required configuration과 selector validity를 같은 의미로 검사 | `workflow_configuration_preflight.py`, `workflow_node_catalog.py` | 이번 correction은 preflight 계약을 변경하지 않음; 517 passed는 이전 변경의 역사적 결과로만 유지 |  |
| Runtime/background 재검증 또는 capability validity | 완료 | Catalog/runtime parameter parity와 unresolved 실행 차단 | `test_agent_builder_parameter_runtime_contract.py`, Workflow Engine node schemas | 이번 correction은 runtime 계약을 변경하지 않음; 517 passed는 이전 변경의 역사적 결과로만 유지 | Agent Builder 생성 단계는 runtime/provider를 호출하지 않음 |
| Transaction·session·TOCTOU | Verification Blocked | ADR-0046 graph hash와 `updated_at` CAS, Knowledge handle 제출 시 권한·lifecycle 재검증 | workflow draft save service, `KnowledgeSelectionService` | Handle cap unit/service 회귀 통과; 이전 revision의 disposable PostgreSQL 증거는 현재 revision 완료 근거로 재사용하지 않음 | Current revision disposable PostgreSQL 미실행 |
| Retry·idempotency·terminal acknowledgement | Verification Blocked | ADR-0046 operation id, task version, canonical acknowledgement/reconciliation | parameter decision service, mutation lifecycle, frontend save coordinator | ParameterTask reconciliation/service 회귀 통과 | Current revision acknowledgement 재계획 PostgreSQL 미실행 |
| Background lease·claim·fencing | 해당 없음 | Agent Builder direct-edit 요청은 background lease/claim을 도입하지 않음 | 해당 없음 | 해당 없음 | Workflow runtime worker lease 정책은 변경하지 않음 |
| Revoke/delete/expire/rotation lifecycle | 완료 | 선택 적용과 runtime 전에 resource visibility/lifecycle 재검증 | Knowledge resolvers, credential candidate resolver | Knowledge permission/lifecycle tests | Slack/GitHub node-owned secret에는 별도 managed credential lifecycle을 추가하지 않음 |
| 오류·resource hiding·reason code | 완료 | safe 403/404/409/422와 stale selection 계약 | Agent Builder endpoints/services | API/service negative tests |  |
| Audit event 생성·action/status·중복 방지 | 완료 | GraphMutation/decision idempotency와 safe audit metadata | parameter task service, mutation lifecycle | duplicate decision/audit regression tests | Agent Builder secret 원문은 audit 대상 payload가 아님 |
| Audit·trace·secret/PII redaction | 완료 | planner/chat/task/session/audit/trace에 raw secret 금지 | secret decision early rejection, safe summary/redaction helpers | secret rejection and response/session regression tests | Workflow graph의 기존 node-owned secret 저장 방식 자체는 이 변경에서 재설계하지 않음 |
| Legacy migration·scrub·호환성 종료 | 완료 | legacy Preview는 `stale_protocol`, direct secret decision은 `secret_forbidden` | session recovery, parameter decision service | stale protocol and secret rejection tests | 별도 schema migration 없음 |
| 공식 문서 정합성 | 완료 | ADR-0045/0046/0061과 Agent Builder feature 문서 | 이 매트릭스와 권위 문서 | 문서 정적 확인 및 관련 실행 테스트 |  |

## 현재 변경의 소비 경계 추적

| 계약 단위 | Schema/Catalog | 저장 정규화 | UI/ParameterTask | GraphMutation/CAS | Preflight/runtime | 검증 |
| --- | --- | --- | --- | --- | --- | --- |
| Optional selector list | `variable_selector_list` | 신규 empty는 skip, 기존 값 전체 해제는 clear | checkbox selection과 clear action 분리 | clear만 parameter mutation/CAS 수행 | stored selector 정규화 후 source/output 검증 | frontend focused suite, backend/shared focused suite |
| File Extraction selector | Catalog `variable_selector` | stored `referenced_variables`를 canonical selector로 변환 | server-issued selector만 제출 | canonical graph mapping 유지 | 같은 normalized value로 preflight 검증 | `test_agent_builder_unresolved_preflight.py` |
| Collection/KB 선택 | opaque handle과 editor resource ID 경로 분리 | 추천 탐색은 5,000개 상한을 유지하고, 발급 resolution은 server-only handle-to-resource binding을 보존해 제출된 최대 20개 resource만 재검증 | Collection/child 선택 상태와 payload 의미 분리 | `knowledge_binding` CAS/acknowledgement | runtime KB union/dedup과 stale resource 차단 | Current revision Knowledge service tests; PostgreSQL cap test blocked |
| Slack/GitHub secret | Catalog `secret` + `agent_builder_task=false` | Agent Builder 저장 정규화 대상에서 제외 | task/card/input/save bridge 미제공 | Agent Builder decision/GraphMutation에는 raw value 없음 | 미설정 node를 preflight/runtime에서 fail-closed | frontend legacy-task fail-closed test, planner omission과 backend `secret_forbidden` tests |
| Workflow save coordination | canonical hash와 `updated_at` | 모든 save owner를 workflow별 직렬화 | pending/confirming 상태 보존 | CAS/acknowledgement 후에만 완료 | test 실행은 저장 완료 전 차단 | Frontend focused test 통과; current revision PostgreSQL CAS blocked |
| Server-derived readiness와 version Note | `configuration_state`는 Catalog 파생 상태 | Client save/compare projection에서 제거하고 Server가 재계산 | version restore의 modern/legacy Note 출처를 구분 | 복원 payload와 editor Note 집합을 동일하게 유지 | canonical comparison에서 파생 상태 차이를 제외 | Mail Acknowledge materialize/runtime contract와 frontend focused test 통과 |
| Scoped deferred projection | `node_path[] + parameter_keys[]` | Gateway가 root 기준 path projection을 저장 응답에 계산 | active Workflow와 path가 일치하는 node에만 marker 반영 | 일반/Agent Builder save가 같은 projection 사용 | ParameterTask/audit 상태는 변경하지 않음 | store 88 tests와 CAS service tests 통과 |
| 늦은 저장 응답 격리 | 응답 `workflow_id` | 비활성 Workflow metadata/cache만 갱신 | 현재 live graph, marker, dirty/history 보존 | 응답 도착 뒤 active identity 재검사 | 다른 Workflow의 autosync를 유발하지 않음 | deferred-promise autosync race regression 통과 |
| Knowledge hierarchy-only UI | `collections + ungrouped_kbs` | flat candidate는 읽기 호환 데이터로만 유지 | flat-only direct 응답은 오류와 제출 차단 | 전용 Knowledge endpoint만 유지 | planner/runtime 변경 없음 | component 회귀와 Knowledge service 회귀 통과 |
| Knowledge 후보 공유 예산 | ADR-0061 고유 KB 5,000 상한 | 적격 direct 결과 최대 20개를 bounded pagination으로 채운 뒤 실제 평가 수를 제외한 예산만 linked 후보에 사용 | 표시 상한 20은 scoring 뒤 적용 | 발급 handle 적용 계약은 변경 없음 | 권한·lifecycle·readiness 실패도 평가 예산에 포함하고 합계가 상한 이내 | permission/recommendation/selection service tests와 denied-20/allowed-21 회귀 |

## 실행 결과

| 범위 | 명령 | 결과 |
| --- | --- | --- |
| Historical frontend focused | `npm run test -- app/features/workflow/components/agentBuilder/AgentBuilderPanel.test.tsx` | 이전 변경 1 file / 59 passed; 현재 working tree 증거로 사용하지 않음 |
| Historical backend/shared/runtime related | `.ignore/codex-py311-venv/Scripts/python.exe -m pytest <previous 13-file suite> -q` | 이전 변경 517 passed; 현재 working tree 증거로 사용하지 않음 |
| Current frontend focused | `npm test -- --run app/features/workflow/store/useWorkflowStore.test.ts app/features/workflow/hooks/useAutoSync.test.ts app/features/workflow/components/agentBuilder/KnowledgeSelectionControl.test.tsx` | 3 files / 122 passed |
| Current backend Knowledge/CAS related | `.ignore/codex-py311-venv/Scripts/python.exe -m pytest apps/gateway/tests/services/test_agent_builder_workflow_cas.py apps/gateway/tests/services/test_knowledge_permission_phase2.py apps/gateway/tests/services/test_knowledge_rag_recommendation_service.py apps/gateway/tests/services/test_agent_builder_knowledge_selection.py -q -p no:cacheprovider` | 121 passed; 3 existing Pydantic deprecation warnings only |
| Working tree direct candidate pagination | `.ignore/codex-py311-venv/Scripts/python.exe -m pytest apps/gateway/tests/services/test_knowledge_permission_phase2.py::test_builder_hierarchy_pages_past_denied_direct_kbs_within_shared_budget -q -p no:cacheprovider`; related four-file suite | RED 1 failed at 20 evaluated; GREEN single test passed; related suite 122 passed with 3 existing Pydantic warnings |
| Working tree Client CI reproduction | `npm run lint`; `npm run typecheck`; `npm run test -- --changed=cebb34178c82830e02e3f5b3d2124821c3c1fd1f --passWithNoTests` | Initial test run 1 failed / 1137 passed; hierarchy empty-handle expectation correction 뒤 138 files / 1138 passed / 1 skipped; lint 0 errors / 248 warnings; typecheck passed |
| Collection cap PostgreSQL | current revision disposable DB | 미실행; explicit disposable DB environment가 없음 |
| Workflow CAS PostgreSQL | current revision disposable DB | 미실행; explicit disposable DB environment가 없음 |
| Python lint | `uvx --from ruff==0.15.20 ruff check apps/gateway/application/agent_builder/graph_mutation_builder.py apps/gateway/services/knowledge_candidate_resolver.py apps/gateway/tests/services/test_agent_builder_workflow_cas.py apps/gateway/tests/services/test_knowledge_permission_phase2.py` | passed |
| Python/import and schema | `.ignore/codex-py311-venv/Scripts/python.exe -c <projection-and-resolver-import-check>` | passed; path projection empty graph and 5,000 cap assertions passed |
| Client static | `npm run typecheck`; `npm run lint`; targeted ESLint | typecheck passed; full lint 0 errors / 248 existing warnings; changed test lint passed; production build는 실행 중 dev server와 `.next`를 공유하지 않기 위해 미실행 |
| Git static | `git diff --check`; `git diff --name-status --diff-filter=D` | passed; whitespace errors 0, deleted files 0 |
| Authenticated browser | Agent Builder secret set/delete, Knowledge selection, save/acknowledgement recovery | 미실행; 인증 organization fixture 필요 |

## 완료 Gate

- Current revision unit/component/service, TypeScript, lint와 static diff 검증은 통과했다.
- Current revision disposable PostgreSQL acknowledgement/Collection cap과 인증된 browser smoke를 실행하기 전까지 상태를 `Verification Blocked`로 유지한다.
- 인증된 browser smoke는 미실행 사실과 남은 위험을 PR에 기록한다. 이를 실행하지 않은 상태를 browser 검증 완료로 표시하지 않는다.
