# Deployment Requirements

Status: Draft
Related Features: workflow, llm-credentials, audit-tracing, knowledge, chatbot-deployment

## Purpose

Deployment feature는 App의 workflow snapshot을 API, webapp, widget, chatbot, MCP, workflow-node, schedule, webhook 같은 실행 표면으로 게시하고 실행 가능한 상태를 관리한다.

이 feature의 범위에는 배포된 앱의 공개 실행 표면 — 임베드 챗 UI(`app/embed/chat`), public run/webhook endpoint(app secret Bearer 인증) — 을 포함한다.

배포 타입 `chatbot`(공개 채팅 웹페이지, 기억모드 항상 ON, 방문자별 대화 격리)의 상세는 [chatbot-deployment](../chatbot-deployment/requirements.md)를 참조한다.

Webhook capture helper는 public webhook 실행 표면이 아니라 로그인한 배포 권한자의 디버그 도구다. Capture start/status/cancel은 user session과 대상 workflow `deploy` 권한을 요구하며, app secret 인증만으로는 사용할 수 없다. Capture session은 short TTL과 server-issued `capture_id` nonce를 사용하고, status 응답은 raw webhook payload 원문이 아니라 known secret patterns와 sensitive keys가 redacted/capped 처리된 preview만 반환한다. 사용자가 capture를 취소하면 서버 session도 삭제되어 이후 webhook은 normal execution path를 따른다.

## User Stories

- 빌더로서, 배포를 활성화하기 전에 현재 workflow snapshot이 실제 실행 표면에서 사용할 수 없는 private KB를 참조하는지 알고 싶다.
- 운영자로서, public/API/webhook/schedule/chatbot 실행에서 사용자 주체가 없을 때 private KB가 owner 권한으로 조용히 사용되지 않기를 원한다.
- 감사자로서, 배포 실행 표면별로 RAG 접근 경계가 명시되어 있고 실패 시 hidden KB id/name/count가 노출되지 않기를 원한다.

## Functional Requirements

- DEP-REQ-001: 배포 생성과 활성화는 workflow graph snapshot, input/output schema, deployment type, active 상태를 기준으로 실행 가능 surface를 만든다.
- DEP-REQ-002: `DeploymentType`은 `api`, `webapp`, `widget`, `chatbot`, `mcp`, `workflow_node`, `schedule`, `webhook`를 지원한다.
- DEP-REQ-003: LLM node RAG 옵션이 private KB 후보를 참조하고 실행 표면에 authenticated execution subject가 없으면 해당 활성 배포는 preflight에서 차단해야 한다.
- DEP-REQ-004: Preflight preview endpoint는 UI가 결과를 렌더링할 수 있도록 blocked 상태도 `200 OK` 응답으로 반환한다. `is_active=false` preview는 inactive 저장 가능성을 반영해 활성화 blocker를 warning으로 낮출 수 있지만, create(`is_active=true`)와 enable/toggle activation의 blocking preflight는 완화하지 않는다.
- DEP-REQ-005: 실제 배포를 활성 surface에 올리는 create(`is_active=true`), enable/toggle activation은 blocking preflight 실패 시 `409 deployment.preflight.blocked`로 실패해야 한다.
- DEP-REQ-006: `is_active=false` 배포 생성은 저장을 허용할 수 있다. 단, inactive 생성은 active deployment 교체, public URL 활성화, schedule job 생성 같은 실행 부작용을 만들지 않아야 하며, 이후 활성화 시 blocking preflight를 다시 통과해야 한다.
- DEP-REQ-007: Active deployment 삭제 시 다른 deployment를 자동 승격하지 않는다. 자동 승격을 도입하려면 승격 직전 같은 blocking preflight를 통과해야 한다.
- DEP-REQ-008: Preflight는 graph snapshot의 LLM node RAG 옵션을 검사하고, explicit KB mode와 materialized recommendation 결과의 KB 후보를 서버 side resolver/helper로 다시 평가해야 한다. Client-supplied KB id나 audience hint만으로 차단을 완화하지 않는다.
- DEP-REQ-009: Source-managed KB를 anonymous public-only 후보로 포함하려면 collection public visibility와 별도 source/connector public exposure approval이 모두 필요하다. Public exposure approval primitive가 구현되기 전에는 source-managed public 후보를 blocked로 처리한다.
- DEP-REQ-010: Preflight response는 hidden KB id/name/path, exact denied count, raw source metadata, raw exception을 반환하지 않고 safe reason code, bucketed count, required action만 반환한다.
- DEP-REQ-011: Schedule record와 scheduler job은 active `type=schedule` deployment에서만 생성/로드/실행한다. `scheduleTrigger` node가 `workflow_node`, `chatbot`, `api` 등 다른 deployment type graph에 포함되어도 schedule 실행 surface를 만들지 않는다.
- DEP-REQ-012: Webhook 수신 endpoint는 active deployment가 target app 소유이고 active 상태이며 `type=webhook`일 때만 background execution을 예약한다. 같은 slug의 active deployment가 `api`, `chatbot`, `workflow_node`, `schedule` 등 다른 type이면 `accepted`를 반환하지 않고 dispatch 전에 safe 404로 거부한다.
- DEP-REQ-013: Deployment 실행 surface와 `DeploymentType` allowlist는 Gateway endpoint, scheduler, Workflow Engine task의 개별 문자열 분기가 아니라 중앙 runtime policy matrix에서 판정해야 한다. Unknown surface 또는 unknown deployment type은 fail-closed로 거부한다.
- DEP-REQ-014: 인증 없는 public deployment info는 기본 runtime policy에서 `webapp`, `widget`, `chatbot` metadata만 노출한다. API, MCP, schedule, webhook, workflow-node와 unknown type은 safe 404로 닫는다. Allowlist는 endpoint 문자열 분기나 환경변수가 아니라 불변 `DeploymentRuntimePolicy` dependency로 주입하며, 확장은 명시적 composition 변경과 계약 테스트를 요구한다.
- DEP-REQ-015: Scheduler는 Celery dispatch 전에 `Schedule.id`와 `deployment_id`가 일치하는 canonical DB row를 확인해야 한다. Row가 삭제되었거나 불일치하면 stale local job을 제거하고 budget check, queue dispatch, `last_run_at`/`next_run_at` update를 수행하지 않아야 한다.
- DEP-REQ-016: Deployment ID 기반 Worker는 queue 입력의 tenant/resource 식별자를 권한 source of truth로 사용하지 않아야 한다. `workflow_id`, `organization_id`, `app_id`, deployment id/version, runtime credential owner는 DB의 current active Deployment/App에서 재구성하고, queue에서는 검증된 trigger와 제한된 correlation metadata만 전달받아야 한다. Subject 없는 webhook/schedule 실행에 queue 입력으로 `execution_subject`를 주입할 수 없다.

## Runtime Audience Matrix

| DeploymentType | 실행 주체 정책 | RAG 경계 |
| --- | --- | --- |
| `api` | Public/app secret 호출에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `webapp` | Public web app surface에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `widget` | Embedded widget surface에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `chatbot` | `/run-public` 공개 실행에는 사용자 subject가 없다. 인증 내부 실행 endpoint만 로그인 사용자를 subject로 사용한다 | 공개 실행은 anonymous public-only. 인증 내부 실행은 current user 권한 |
| `mcp` | 별도 authenticated operator/service account가 없으면 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `workflow_node` | Public/API/webhook 및 authenticated run/run-info 같은 direct execution surface는 지원하지 않는다. Subworkflow 실행은 parent workflow의 execution context를 상속한다 | Parent subject 기준 KB permission/source ACL. Parent subject가 없으면 anonymous public-only로 평가되어 private KB blocked |
| `schedule` | 예약 실행에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |
| `webhook` | Webhook/app secret 호출에는 사용자 subject가 없다 | Anonymous public-only. Private KB blocked |

## Policies And Edge Cases

- Organization membership은 KB 사용 권한이 아니다. Public/automatic deployment surface에서 private KB를 사용하려면 후속 service account 또는 assigned operator 정책이 필요하다.
- Preview endpoint의 `audience` 필드는 UI 검증용 힌트일 뿐이다. Create/enable/toggle 경로는 서버가 실제 deployment type과 실행 경로에서 audience를 파생해야 하며, client-supplied audience가 보안 차단을 완화할 수 없다.
- Workflow-node preflight는 node 설정의 `workflowNode.data.appId`를 target app으로 해석하고, target app의 active deployment snapshot을 검사한다. `workflowId`와 혼동하지 않는다. Target active deployment는 target app 소유이고, active 상태이며, `type=workflow_node`여야 한다. Pending active candidate graph도 pending deployment type이 `workflow_node`일 때만 workflow-node target으로 인정한다.
- `workflow_node` 배포를 단독 reusable module로 활성화할 때는 parent subject가 아직 없으므로 private KB 참조를 warning으로 보고할 수 있다. 단, public/API/webhook/authenticated run 같은 모든 direct execution surface는 거부하며, public/non-interactive parent deployment가 해당 module을 참조하면 parent audience 기준 preflight에서 private KB를 blocked로 처리한다.
- Workflow-node runtime은 parent `execution_context.organization_id`가 있어야 하며, target app organization이 없거나 target app organization과 다르거나 parent organization context가 없으면 실행하지 않는다. Target active deployment도 target app 소유, active 상태, `type=workflow_node`를 만족해야 한다. Runtime은 `workflow_node_depth`와 `workflow_node_visited_app_ids` context guard로 순환 참조와 depth 초과를 fail-closed로 차단한다.
- Workflow-node nesting은 우선 한 단계 active target 검사를 baseline으로 삼는다. 순환 참조, 과도한 depth, target active deployment 부재는 subject 상속 여부와 무관한 구조적 오류이므로 active publish와 inactive preview 모두에서 safe blocked reason으로 유지한다.
- Workflow-node runtime의 순환 참조, depth 초과, target unavailable 같은 복구 불가능한 설정 오류는 Celery retry 대상이 아니다. Runtime은 non-retryable error로 즉시 실패시켜 같은 잘못된 subworkflow 실행을 반복 예약하지 않는다.
- `run.py`/`webhook.py`와 authenticated deployment run/run-info 같은 runtime endpoint는 실행 주체와 direct surface contract verification 대상이다. Preflight의 핵심 차단은 deployment create/toggle service boundary에서 수행하며, delete는 다른 deployment를 자동 승격하지 않아 우회 activation surface를 만들지 않는다.
- Schedule dispatch는 graph snapshot을 queue payload에 직접 넣지 않고 deployment id를 worker에 전달한다. Worker는 실행 직전에 deployment active/type, app ownership과 current active pointer를 다시 확인하며, 삭제/비활성/stale/mismatched target은 retry하지 않는 permanent policy failure로 종료한다. Gateway replica 간 동일 예정 실행의 단일 claim과 end-to-end idempotency는 MBA-187에서 구현하며, 이 요구사항을 단일 process stale-job 방어와 혼동하지 않는다.
- Preflight 예외는 broad catch에서 일반 `400`으로 감싸지 않고 `409 deployment.preflight.blocked` 또는 문서화된 error envelope을 보존해야 한다.
- Public info, authenticated run/run-info, webhook dispatch, schedule dispatch, workflow-node child dispatch는 같은 불변 runtime policy dependency를 사용해야 한다. Metadata 조회 가능 여부와 실제 execution 허용 여부는 별도 surface로 표현하며, public info 허용이 public execution 허용을 뜻하지 않는다. Production 기본 policy는 composition provider가 주입하고 임의 runtime mutation이나 환경변수 기반 allowlist 확장을 허용하지 않는다.

## Open Questions

- Private KB를 자동 실행에서 사용할 service account 또는 assigned operator 모델은 MBA-176 범위 밖이다.
