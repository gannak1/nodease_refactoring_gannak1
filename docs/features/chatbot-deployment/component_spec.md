# Chatbot Deployment Component Spec

Status: Draft

## Screens

- 워크플로우 에디터 상단 "게시하기" 드롭다운 (`components/editor/NodeCanvas.tsx`)
- 배포 플로우 모달 (`components/deployment/DeploymentFlowModal.tsx` → `SuccessStep.tsx`)
- 공개 챗봇 페이지 (`app/embed/chat/[urlSlug]/page.tsx`) — 기존 임베드 챗 UI 재사용
- 인증 내부 챗봇 실행 페이지 (`app/modules/[id]/run/page.tsx`) — 로그인 사용자 권한으로 `internal_chatbot` 배포 snapshot을 실행한다. Target access grant/session surface는 별도 후속 계약이다.

## Components

- "게시하기" 드롭다운: 시작 노드가 `startNode`일 때 **"공개 챗봇 배포"**와 **"내부 챗봇 배포"**를 별도 항목으로 노출한다. 각각 `handlePublishAsChatbot`과 `handlePublishAsInternalChatbot` 호출로 `deploymentType='chatbot'` 또는 `'internal_chatbot'`인 모달을 연다.
- `useDeployment.handleDeploy`: `chatbot`은 `${origin}/embed/chat/{url_slug}` 공개 링크만 결과에 넣고, `internal_chatbot`은 `${origin}/modules/{workflow_id}/run?deploymentId={deployment_id}` 인증 실행 링크만 넣는다.
- `DeploymentFlowModal.getDeploymentTypeName`: `chatbot` → `"공개 챗봇"`, `internal_chatbot` → `"내부 챗봇"`.
- `SuccessStep`: `chatbot`은 공개 챗봇 공유 카드만, `internal_chatbot`은 사내 인증 실행 카드만 표시해 두 보안 경계를 한 배포 결과에서 섞지 않는다.
- 챗봇 페이지(`app/embed/chat/[urlSlug]/page.tsx`): 메시지 버블/입력창/환영 메시지/입력 중 표시(기존). 전송 시 `POST /api/v1/run-public/{urlSlug}`를 사용하며, private Knowledge/RAG 후보를 workflow owner 권한으로 넓히지 않는다.
- 인증 내부 실행 페이지(`app/modules/[id]/run/page.tsx`): `GET /api/v1/deployments/{deployment_id}/run-info`와 `POST /api/v1/deployments/{deployment_id}/run`을 사용한다. `internal_chatbot`은 page-session UUID를 top-level `conversation.client_id`로 보내고 업무 `inputs`에는 `memory_mode`/`conversation_id` control을 추가하지 않는다. LLM node RAG는 로그인 사용자를 execution subject로 전달받는다.
- 인증 내부 실행 오류: 문서화된 HTTP status를 fixed 사용자 메시지로 mapping하고, 알 수 없는 `response.data.detail` 원문을 화면에 표시하지 않는다.
- 인증 복귀: run-info가 `401`을 반환하면 원래 path/query/hash를 인코딩한 `/auth/login?next=...`로 이동한다. 공통 redirect helper가 API interceptor와 page handler의 중복 이동을 조정한다. 이메일/비밀번호 로그인 성공 후 `LoginPage`는 safe same-origin `next`로 복귀하고 외부 URL은 `/dashboard`로 닫는다.

## States

- 공개 `conversationId`: 방문자별 대화 격리 키. 마운트 시 `localStorage['nodease_chat_conv_' + urlSlug]`에서 읽고 없으면 `crypto.randomUUID()`로 생성/저장한다. `localStorage` 접근 불가(프라이빗 모드 등) 시 세션 한정 임시 id를 사용한다.
- 내부 `conversationId`: 내부 실행 페이지 마운트 시 생성하는 canonical UUID다. `localStorage`에 저장하지 않고 top-level `conversation.client_id`로만 전송한다. 서버가 deployment/current user에 결박한 `auth:v1` namespace로 바꾼다.
- `messages`: 현재 브라우저 세션의 대화 표시용(React state). 서버 기억은 `conversation_id` 기반 실행 이력 요약으로 별도 유지된다.

두 state 설명은 Legacy Current Implementation이다. Target Client는 [Conversation Memory component spec](../conversation-memory/component_spec.md)의 server-issued Access Grant/session 및 transcript projection을 사용한다. 같은 채팅 시각 컴포넌트는 재사용하되 public/authenticated backend surface, API/auth adapter, CORS/Origin, deployment access policy, session namespace와 secret storage는 분리한다.

## Interactions

- 공개 메시지 전송: 사용자 입력을 첫 입력 변수에 매핑하고, `inputs.memory_mode = true`, `inputs.conversation_id = conversationId`를 추가한다. 두 값은 공개 legacy 서버 경로에서 pop된다.
- 내부 메시지 전송: 업무 입력은 `inputs`에 그대로 두고 `{ conversation: { client_id } }` control을 sibling field로 전송한다. 서버가 Chatbot memory mode를 강제하므로 Client가 `inputs.memory_mode`를 보내지 않는다.
- 내부 링크 인증 복귀: 인증이 없거나 만료하면 현재 실행 링크를 `next`로 보존한다. 이메일/비밀번호 로그인은 안전한 내부 `next`로 복귀하며 Google OAuth는 기존처럼 대시보드로 이동한다.
- 응답 추출: `results`에서 `answer` 필드를 가진 노드 결과를 찾아 assistant 메시지로 표시한다(기존 로직 유지).

Target interaction은 conversation envelope과 idempotency key를 사용하고 node별 Memory config를 deployment snapshot에서 읽는다. UI가 모든 node Memory를 강제하거나 client state를 transcript source of truth로 사용하지 않는다.

Public Client는 deployment-owned exact Origin/embed/CSP policy가 확인된 surface만 사용한다. Login 상태를 감지해 public adapter를 authenticated mode로 바꾸지 않으며, 내부 Chatbot link/component는 별도 access bootstrap 성공 후에만 렌더링한다.

## Accessibility

- 입력창은 `input[type=text]`, 전송은 `button[type=submit]`. 전송 중에는 입력/버튼을 비활성화한다(기존 동작 유지).
