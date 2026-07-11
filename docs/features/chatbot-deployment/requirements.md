# Chatbot Deployment Requirements

Status: Draft
Related Features: deployment, workflow, conversation-memory, llm-credentials, audit-tracing

## Purpose

`시작 입력 노드`(코드 타입 `startNode`)로 시작하는 워크플로우를, 공개 웹페이지 생성과 동일한 방식으로 **공개 채팅 웹페이지(챗봇)** 로 배포하는 기능을 제공한다. 챗봇은 방문자와 여러 턴에 걸쳐 대화하며, **이전 대화 맥락을 기억**한다.

이 feature는 [deployment](../deployment/requirements.md)의 배포 타입/공개 실행 표면 위에 챗봇 전용 배포 타입과 방문자별 대화 격리 기억을 additive로 추가한다. 채팅 UI는 기존 임베드 챗 페이지(`app/embed/chat/[urlSlug]`)를 재사용한다.

## Contract Status

CBOT-REQ-004~007의 global `memory_mode`, client UUID와 execution-log memory는 현재 구현을 설명하는 **Legacy Current Implementation**이다. [ADR-0030](../../decisions/ADR-0030-memory-bounded-context.md)와 [Conversation Memory](../conversation-memory/requirements.md)가 목표 계약이며, 해당 migration이 완료되면 CBOT-REQ-008 이후가 이를 대체한다. Legacy 동작을 신규 배포나 확장 기능의 설계 기준으로 복제하지 않는다. 현재 generic authenticated deployment run은 로그인 사용자를 execution subject로 전달할 수 있지만, 별도 내부 Chatbot 이용 권한·배포 surface와 Target Conversation Session을 제공하는 완성된 내부 Chatbot 계약은 아니다.

## User Stories

- 빌더로서, `startNode`로 시작하는 워크플로우를 클릭 한 번으로 공개 챗봇 링크로 배포하고 싶다.
- 챗봇 방문자로서, 새로고침이나 여러 턴에 걸쳐 이전에 나눈 대화 맥락을 챗봇이 기억한 채로 대화하고 싶다.
- 챗봇 방문자로서, 다른 방문자의 대화 내용이 내 대화에 섞이지 않기를 원한다.

## Functional Requirements

- CBOT-REQ-001: 배포 진입점("게시하기" 드롭다운)의 "챗봇 배포" 항목은 시작 노드가 `startNode`인 워크플로우에서만 노출한다(공개 웹페이지 생성과 동일 조건). `webhookTrigger`/`scheduleTrigger` 시작 노드에는 노출하지 않는다.
- CBOT-REQ-002: 챗봇 배포는 `DeploymentType.chatbot` 타입의 배포를 생성한다. 배포 생성 경로(그래프 스냅샷, url_slug/auth_secret 지연 생성, 단일 활성 배포, input/output 스키마 추출)는 기존 배포와 동일하다.
- CBOT-REQ-003: 배포 성공 시 `${origin}/embed/chat/{url_slug}` 형태의 공개 챗봇 공유 링크를 제공한다. 이 링크는 무인증 공개 실행 표면(`POST /run-public/{url_slug}`)을 사용한다.
- CBOT-REQ-003a: 공개 챗봇 활성 배포 생성/전환은 deployment preflight를 통과해야 한다. `/run-public`은 사용자 execution subject를 주입하지 않으므로 private KB 후보가 있으면 `409 deployment.preflight.blocked`로 활성화를 차단한다.
- CBOT-REQ-004 (Legacy Current Implementation): 챗봇 배포의 실행은 **기억모드(memory_mode)를 항상 ON** 으로 강제한다. 이 강제는 서버(`run_deployment`)가 `deployment.type == chatbot`을 근거로 수행하며, 클라이언트가 보낸 `memory_mode` 값과 무관하다.
- CBOT-REQ-005 (Legacy Current Implementation): 챗봇 페이지는 방문자별 `conversation_id`를 브라우저 `localStorage`(`nodease_chat_conv_{url_slug}`)에 생성/유지하고, 매 실행 요청의 `inputs`에 `conversation_id`와 `memory_mode: true`를 담아 보낸다. 서버는 이 두 값을 dispatch 전에 `inputs`에서 제거(pop)하여 워크플로우 입력을 오염시키지 않고 `execution_context`로만 전달한다.
- CBOT-REQ-006 (Legacy Current Implementation): 기억 조회는 방문자별로 격리한다. `execution_context.conversation_id`가 있으면 기억 요약은 `workflow_id + conversation_id + status=SUCCESS` 실행 이력으로 스코프하고 `user_id` 필터를 사용하지 않는다. `conversation_id`가 없으면 기존 `workflow_id + user_id` 스코프를 유지한다(하위호환).
- CBOT-REQ-007 (Legacy Current Implementation): 실행 이력(`workflow_runs`)에는 방문자별 격리 키로 `conversation_id`(nullable, indexed)를 저장한다. 저장 경로는 기존 `correlation_id`와 동일하게 `execution_context → workflow_logger → log_system`을 따른다.
- CBOT-REQ-008 (Target): Chatbot deployment는 Conversation Session surface를 제공할 수 있지만 모든 LLM node의 Memory를 강제하지 않는다. Node별 versioned Memory config의 기본값은 OFF다.
- CBOT-REQ-009 (Target): Public chatbot은 server-issued Conversation Access Grant를 사용하고 client-generated UUID를 접근 capability로 사용하지 않는다.
- CBOT-REQ-010 (Target): Conversation metadata는 업무 `inputs`와 분리된 envelope로 전달하며 dedicated Memory store가 source of truth다. Workflow execution log는 conversation reader가 아니다.
- CBOT-REQ-011 (Target): 공개·인증 챗봇은 시각 컴포넌트를 재사용할 수 있지만 public grant API와 cookie-authenticated API/CSRF 경계를 분리한다.
- CBOT-REQ-012 (Target): `public_chatbot`과 `authenticated_internal_chatbot`은 backend runtime policy, route, authentication/CORS/Origin, deployment access permission과 session namespace를 분리해야 한다. Public route의 optional login으로 내부 권한을 허용해서는 안 된다.
- CBOT-REQ-013 (Target): Public Chatbot은 login cookie 존재 여부와 무관하게 anonymous public-only RAG를 사용하고 private KB 후보가 있으면 activation preflight를 차단해야 한다.
- CBOT-REQ-014 (Target): Authenticated internal Chatbot은 별도 내부 Chatbot 이용 권한과 current user의 KB permission/source ACL을 모두 통과해야 한다. Workflow `execute` 또는 public Access Grant만으로 권한을 대체해서는 안 된다.
- CBOT-REQ-015 (Target): Authenticated internal Chatbot은 별도 기능 이슈에서 deployment access mode와 permission/default grant 정책이 구현된 뒤에만 제공한다. Conversation Memory 설계만으로 해당 기능이 현재 동작한다고 간주하지 않는다.
- CBOT-REQ-016 (Target): Public browser Chatbot은 deployment-owned versioned exact Origin/embed/CSP allowlist를 가져야 하며 missing/null/unlisted Origin, wildcard, client hint와 environment fallback을 거부해야 한다.
- CBOT-REQ-017 (Target): Conversation Session은 deployment ID와 immutable version 또는 snapshot hash, conversation mapping/Memory policy version에 고정하며 active deployment 변경에 자동 rebind하지 않아야 한다.
- CBOT-REQ-018 (Target): Public Access Grant는 session 접근 capability일 뿐 execution subject, credential/billing principal 또는 audit actor가 아니다. Public request lifecycle audit은 `actor_id=null`, `actor_type='public'`을 사용하고 비동기 purge completion은 `system` actor를 사용해야 한다.

## Policies And Edge Cases

- Legacy 공개 실행에서 앱 소유자를 사용하더라도 이는 deployment policy가 정한 credential/billing principal일 뿐 execution subject나 audit actor가 아니다. 방문자 격리 기준으로 `user_id`를 사용할 수 없고 legacy는 `conversation_id`, target은 server-issued session/grant를 사용한다.
- 공개 챗봇 실행은 anonymous public-only RAG 경계다. 현재 generic authenticated deployment run은 로그인 사용자의 KB 권한을 평가할 수 있지만, target private-KB 내부 Chatbot은 별도 내부 Chatbot 이용 권한과 backend surface가 구현된 뒤에만 제공한다.
- Legacy `conversation_id`는 비인증 클라이언트 값이며 UUIDv4의 추정 곤란성에만 의존한다. Target contract에서는 public Access Grant가 session 접근 capability다.
- Legacy 기억은 성공(`SUCCESS`)한 `llmNode` 실행 이력과 `MEMORY_RUN_LIMIT`(5)을 사용한다. Target contract에서는 dedicated store, node별 window/summary policy와 current authorization을 사용한다.
- Legacy `conversation_id`/`memory_mode` business input collision은 target conversation envelope migration으로 제거한다.

## Open Questions

- 다중 입력 변수 챗봇 지원(현재는 사용자 메시지를 첫 입력 변수에 매핑).
