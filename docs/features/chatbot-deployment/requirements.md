# Chatbot Deployment Requirements

Status: Draft
Related Features: deployment, workflow, llm-credentials, audit-tracing

## Purpose

`시작 입력 노드`(코드 타입 `startNode`)로 시작하는 워크플로우를, 공개 웹페이지 생성과 동일한 방식으로 **공개 채팅 웹페이지(챗봇)** 로 배포하는 기능을 제공한다. 챗봇은 방문자와 여러 턴에 걸쳐 대화하며, **이전 대화 맥락을 기억**한다.

이 feature는 [deployment](../deployment/requirements.md)의 배포 타입/공개 실행 표면 위에 챗봇 전용 배포 타입과 방문자별 대화 격리 기억을 additive로 추가한다. 채팅 UI는 기존 임베드 챗 페이지(`app/embed/chat/[urlSlug]`)를 재사용한다.

## User Stories

- 빌더로서, `startNode`로 시작하는 워크플로우를 클릭 한 번으로 공개 챗봇 링크로 배포하고 싶다.
- 챗봇 방문자로서, 새로고침이나 여러 턴에 걸쳐 이전에 나눈 대화 맥락을 챗봇이 기억한 채로 대화하고 싶다.
- 챗봇 방문자로서, 다른 방문자의 대화 내용이 내 대화에 섞이지 않기를 원한다.

## Functional Requirements

- CBOT-REQ-001: 배포 진입점("게시하기" 드롭다운)의 "챗봇 배포" 항목은 시작 노드가 `startNode`인 워크플로우에서만 노출한다(공개 웹페이지 생성과 동일 조건). `webhookTrigger`/`scheduleTrigger` 시작 노드에는 노출하지 않는다.
- CBOT-REQ-002: 챗봇 배포는 `DeploymentType.chatbot` 타입의 배포를 생성한다. 배포 생성 경로(그래프 스냅샷, url_slug/auth_secret 지연 생성, 단일 활성 배포, input/output 스키마 추출)는 기존 배포와 동일하다.
- CBOT-REQ-003: 배포 성공 시 `${origin}/embed/chat/{url_slug}` 형태의 공개 챗봇 공유 링크를 제공한다. 이 링크는 무인증 공개 실행 표면(`POST /run-public/{url_slug}`)을 사용한다.
- CBOT-REQ-004: 챗봇 배포의 실행은 **기억모드(memory_mode)를 항상 ON** 으로 강제한다. 이 강제는 서버(`run_deployment`)가 `deployment.type == chatbot`을 근거로 수행하며, 클라이언트가 보낸 `memory_mode` 값과 무관하다.
- CBOT-REQ-005: 챗봇 페이지는 방문자별 `conversation_id`를 브라우저 `localStorage`(`nodease_chat_conv_{url_slug}`)에 생성/유지하고, 매 실행 요청의 `inputs`에 `conversation_id`와 `memory_mode: true`를 담아 보낸다. 서버는 이 두 값을 dispatch 전에 `inputs`에서 제거(pop)하여 워크플로우 입력을 오염시키지 않고 `execution_context`로만 전달한다.
- CBOT-REQ-006: 기억 조회는 방문자별로 격리한다. `execution_context.conversation_id`가 있으면 기억 요약은 `workflow_id + conversation_id + status=SUCCESS` 실행 이력으로 스코프하고 `user_id` 필터를 사용하지 않는다. `conversation_id`가 없으면 기존 `workflow_id + user_id` 스코프를 유지한다(하위호환).
- CBOT-REQ-007: 실행 이력(`workflow_runs`)에는 방문자별 격리 키로 `conversation_id`(nullable, indexed)를 저장한다. 저장 경로는 기존 `correlation_id`와 동일하게 `execution_context → workflow_logger → log_system`을 따른다.

## Policies And Edge Cases

- 공개 실행은 `user_id`가 앱 소유자로 고정되므로(과금/크레덴셜은 소유자 기준, deployment 정책), 방문자 격리 기준으로 `user_id`를 쓸 수 없다. 격리는 반드시 `conversation_id` 기준으로 한다.
- `conversation_id`는 비인증 클라이언트 값이다. 공개 챗봇은 사용자 인증이 없으므로 이는 인증 격리가 아니며, UUIDv4의 추정 곤란성에만 의존한다.
- 기억은 성공(`SUCCESS`)한 `llmNode` 실행 이력만 반영하며, 최근 `MEMORY_RUN_LIMIT`(5)턴으로 제한한다. 기억모드는 매 턴 요약용 LLM 호출을 1회 추가한다.
- `conversation_id`/`memory_mode`는 `inputs` 내부 키로 전달되어 dispatch 전에 pop되므로, 시작 노드에 동일 이름의 입력 변수가 있으면 삼켜진다(가능성 낮음).

## Open Questions

- 요약 기반 기억을 최근 대화 원문 주입으로 전환할지(비용/지연 절감, 충실도 향상) 여부. 현재는 기존 기억모드(요약) 재사용으로 확정.
- 다중 입력 변수 챗봇 지원(현재는 사용자 메시지를 첫 입력 변수에 매핑).
