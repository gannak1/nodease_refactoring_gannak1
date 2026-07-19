# External Action Credentials Requirements

Status: Draft
Related Features: workflow, deployment, agent-builder, organization, audit-tracing

## Purpose

External Action Credential은 GitHub PR 조회·댓글과 Slack API/Webhook 전송에 필요한 secret을 workflow graph와 분리해 organization-scoped resource로 관리한다. Graph에는 provider-neutral opaque `credential_id`만 저장하며, 실제 secret은 runtime resolver가 권한을 확인한 뒤 메모리에서만 사용한다.

## Functional Requirements

- EAC-REQ-001: Credential은 하나의 organization에 속하고 provider는 `github`, `slack_api`, `slack_webhook`만 허용한다.
- EAC-REQ-002: 등록은 active organization manager만 수행한다. `read`, `use`, `manage`는 기존 user/team auth state 계층으로 분리하고 organization manager는 override를 가진다.
- EAC-REQ-003: Secret은 versioned encryption envelope로만 저장한다. API, graph, deployment snapshot, Agent Builder preview, audit, trace, log와 test fixture에는 secret, ciphertext, encryption key 원문, raw provider response를 남기지 않는다.
- EAC-REQ-004: API response와 picker option은 credential id, safe name, provider, revision, lifecycle 상태만 반환한다. Credential 존재를 알 권한이 없는 동일 organization 사용자의 상세 접근은 resource hiding으로 처리한다.
- EAC-REQ-005: Workflow의 `slackPostNode`와 `githubNode`는 secret 대신 opaque `credential_id`만 durable graph에 저장한다. Slack `authConfig.token`/Webhook URL과 GitHub `api_token`/`token`/`authConfig`는 새 저장, Agent Builder apply, deployment snapshot과 실행 경계에서 허용하지 않는다. GitHub node의 durable data는 현재 UI/runtime 계약의 allowlist로 제한하며, 계약 밖 field는 credential-like 여부와 무관하게 저장하지 않는다.
- EAC-REQ-006: 기존 direct-secret graph는 자동으로 새 credential에 매핑하지 않는다. migration은 secret-shaped field를 제거하고 해당 node를 `configuration_state=unresolved`로 남긴다. downgrade는 제거된 secret을 복구하지 않는다.
- EAC-REQ-007: Draft와 Agent Builder 결과는 unresolved `credential_id`를 보존할 수 있지만, active deployment, authenticated execution, schedule dispatch와 provider call은 유효한 reference와 명시 user execution subject를 요구한다.
- EAC-REQ-008: Graph 저장 시 Gateway는 active organization, credential active 상태, provider 일치와 저장 요청자의 `use` 권한을 `ExternalActionCredentialUseResolver`로 확인한다. endpoint, Workflow service, runtime은 권한 조합 규칙을 중복 구현하지 않는다.
- EAC-REQ-009: Workflow Engine은 provider call 직전에 같은 resolver로 organization, execution subject, lifecycle, provider, `use` 권한과 credential revision을 다시 확인한다. 저장 후 revoke, 권한 회수, provider 변경 또는 secret rotation은 외부 request 전에 fail-closed한다.
- EAC-REQ-010: Slack API credential은 `slack_api`, Slack incoming webhook credential은 `slack_webhook`, GitHub node는 `github` provider와 정확히 일치해야 한다. 불일치, missing, revoked, cross-organization, 권한 거부와 복호화 실패는 같은 safe unavailable reason으로 projection한다.
- EAC-REQ-011: Deployment preflight는 secret을 복호화하거나 provider network call을 하지 않는다. safe snapshot의 provider, active lifecycle, principal `use` 결과만 사용하며 runtime authorization capability로 재사용하지 않는다.
- EAC-REQ-012: Preflight preview는 permission-denied audit을 만들지 않는다. active create/toggle 또는 authenticated execution enforcement에서 확인된 same-organization `use` 거부는 credential별 한 번의 safe `permission.denied` audit으로 기록한다.
- EAC-REQ-013: Gateway와 Workflow Worker는 startup에서 동일한 external-action credential keyring과 active key version을 검증한다. keyring이 잘못되면 secret을 읽거나 외부 효과를 시작하기 전에 fail-fast한다.
- EAC-REQ-014: Slack node output은 safe delivery 상태와 optional message reference만 제공한다. raw response headers/body selector는 legacy migration error로 차단한다.
- EAC-REQ-015: Agent Builder는 credential을 자동 선택하거나 secret을 생성 결과에 넣지 않는다. Slack/GitHub node는 unresolved reference와 parameter task만 생성한다.
- EAC-REQ-016: 실행용 picker는 active이고 `use` 가능한 credential만 반환한다. 권한 관리 화면은 active 또는 revoked 중 `manage` 가능한 safe option을 별도 조회하며, revoked credential은 기존 permission 조회·회수에만 사용하고 신규 grant 대상으로 노출하지 않는다.
- EAC-REQ-017: Organization manager 화면은 외부 연동 Credential 등록, 이름·secret 교체와 revoke 경로를 제공한다. 기존 secret은 다시 표시하지 않고 mutation은 현재 revision을 사용하며, 서버 mutation 성공 뒤 목록 갱신 실패를 같은 mutation의 실패로 오인해 재제출하지 않는다.

## Out Of Scope

- Organization-scoped Connection schema 또는 generic connector RBAC 재설계
- Generic HTTP node의 outbound egress, proxy, NetworkPolicy 변경
- GitHub/Slack provider capability 확장이나 arbitrary URL/method 실행
- LLM/Mail credential storage 모델 변경

## Policies And Edge Cases

- `use` 권한은 secret 조회 권한이 아니다. 어떤 role도 secret을 API로 읽을 수 없다.
- `viewer`는 safe metadata를 읽을 수 있지만 workflow 실행에는 사용할 수 없다.
- PATCH secret 교체와 revoke는 optimistic `expected_revision`을 요구한다.
- Revoked credential은 수정·신규 grant 대상이 될 수 없고, 관리용 목록을 통한 기존 permission 조회·회수만 가능하다.
- Resource hiding reason은 provider, credential name, target URL, channel, repository, raw exception을 포함하지 않는다.
- Runtime revalidation은 provider I/O 직전에 짧은 DB session으로 수행하며 DB transaction 또는 row lock을 provider network call 동안 유지하지 않는다.
- Slack Webhook mode는 Credential에 목적지가 포함되므로 별도 channel 설정을 요구하지 않는다. Slack API mode만 channel을 필수로 사용한다.
