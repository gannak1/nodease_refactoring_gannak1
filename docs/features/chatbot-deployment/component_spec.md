# Chatbot Deployment Component Spec

Status: Draft

## Screens

- 워크플로우 에디터 상단 "게시하기" 드롭다운 (`components/editor/NodeCanvas.tsx`)
- 배포 플로우 모달 (`components/deployment/DeploymentFlowModal.tsx` → `SuccessStep.tsx`)
- 공개 챗봇 페이지 (`app/embed/chat/[urlSlug]/page.tsx`) — 기존 임베드 챗 UI 재사용
- 인증 내부 실행 페이지 (`app/modules/[id]/run/page.tsx`) — 로그인 사용자 권한으로 배포 snapshot 실행

## Components

- "게시하기" 드롭다운: 시작 노드가 `startNode`일 때 "공개 웹페이지 생성"과 "사이트에 임베드" 사이에 **"챗봇 배포"** 항목을 노출한다. 클릭 시 `handlePublishAsChatbot`(`hooks/useDeployment.ts`)이 `deploymentType='chatbot'`으로 모달을 연다.
- `useDeployment.handleDeploy`: `deploymentType === 'chatbot'`이면 결과의 `webAppUrl`을 `${origin}/embed/chat/{url_slug}`로 설정하고, `internalRunUrl`을 `${origin}/modules/{workflow_id}/run?deploymentId={deployment_id}`로 설정한다.
- `DeploymentFlowModal.getDeploymentTypeName`: `chatbot` → `"챗봇"`.
- `SuccessStep`: `deploymentType === 'chatbot'`이면 공개 챗봇 공유 링크와 사내 인증 실행 링크를 별도 카드로 표시한다. 공개 링크 설명은 anonymous public-only RAG 경계를 명시하고, 사내 인증 실행 링크 설명은 로그인 사용자 권한 실행임을 명시한다.
- 챗봇 페이지(`app/embed/chat/[urlSlug]/page.tsx`): 메시지 버블/입력창/환영 메시지/입력 중 표시(기존). 전송 시 `POST /api/v1/run-public/{urlSlug}`를 사용하며, private Knowledge/RAG 후보를 workflow owner 권한으로 넓히지 않는다.
- 인증 내부 실행 페이지(`app/modules/[id]/run/page.tsx`): `GET /api/v1/deployments/{deployment_id}/run-info`와 `POST /api/v1/deployments/{deployment_id}/run`을 사용한다. LLM node RAG는 로그인 사용자를 execution subject로 전달받는다.

## States

- `conversationId`: 방문자별 대화 격리 키. 마운트 시 `localStorage['nodease_chat_conv_' + urlSlug]`에서 읽고 없으면 `crypto.randomUUID()`로 생성/저장한다. `localStorage` 접근 불가(프라이빗 모드 등) 시 세션 한정 임시 id를 사용한다.
- `messages`: 현재 브라우저 세션의 대화 표시용(React state). 서버 기억은 `conversation_id` 기반 실행 이력 요약으로 별도 유지된다.

## Interactions

- 메시지 전송: 사용자 입력을 첫 입력 변수에 매핑하고, `inputs.memory_mode = true`, `inputs.conversation_id = conversationId`를 추가하여 전송한다. 두 값은 서버에서 pop된다.
- 응답 추출: `results`에서 `answer` 필드를 가진 노드 결과를 찾아 assistant 메시지로 표시한다(기존 로직 유지).

## Accessibility

- 입력창은 `input[type=text]`, 전송은 `button[type=submit]`. 전송 중에는 입력/버튼을 비활성화한다(기존 동작 유지).
