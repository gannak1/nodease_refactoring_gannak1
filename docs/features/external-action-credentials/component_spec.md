# External Action Credentials Component Spec

Status: Draft

## Gateway And Shared

- `ExternalActionCredentialService`는 lifecycle, safe response mapping, organization manager registration, resource hiding과 canonical audit를 소유한다.
- `ExternalActionCredentialService`는 실행용 active/`use` picker와 active·revoked/`manage` 관리 목록을 분리한다. 공통 auth-state resolver의 lifecycle 옵션을 사용하며 endpoint나 UI에서 권한 조합을 재구현하지 않는다.
- `ExternalActionCredentialSecretService`만 encryption envelope encrypt/decrypt와 provider secret shape 검증을 수행한다.
- `ExternalActionCredentialUseResolver`는 organization, active lifecycle, provider, effective auth state와 `use`를 단일 해석한다. Graph 저장과 runtime은 이 resolver를 재사용한다.
- `external_action_credentials`, user/team permission tables는 기존 organization-scoped additive resource permission pattern을 따른다.
- Secret keyring은 `EXTERNAL_ACTION_CREDENTIAL_ENCRYPTION_KEYS`와 `EXTERNAL_ACTION_CREDENTIAL_ACTIVE_KEY_VERSION`으로 주입한다. Gateway와 Workflow Worker가 같은 keyring을 startup에서 검증한다.

## Graph, Builder And Client

- Shared graph boundary는 최상위 및 모든 `subGraph.nodes`에서 Slack direct token/Webhook URL과 GitHub direct token field를 거부한다. GitHub data는 UI/runtime 계약의 explicit allowlist 밖 field와 비어 있지 않은 generic `parameters`를 거부한다.
- Legacy persisted graph response/copy 경계는 direct field와 GitHub allowlist 밖 field를 제거한 deep copy만 반환하고, `credential_id`가 없으면 unresolved로 표시한다.
- Workflow Editor의 Slack/GitHub panel은 safe option picker만 렌더링한다. 선택 결과는 `credential_id`만 저장하고 기존 direct setting이 남아 있으면 제거 action과 validation state를 표시한다.
- Admin permission 화면은 safe 관리 option으로 revoked 상태를 표시하고 기존 grant 회수 경로를 유지한다. 신규 grant 모달과 행위자 접근 관리의 grant catalog는 active credential만 선택할 수 있다.
- Agent Builder는 typed GraphMutation에 unresolved `credential_id`를 남기고 credential 선택은 parameter task/editor에서 명시적으로 수행한다.

## Deployment And Runtime

- Deployment preflight repository는 credential secret을 읽지 않고 provider, active state, principal effective auth state만 `ExternalActionCredentialSnapshot`으로 반환한다.
- Active deployment와 authenticated execution enforcement는 unresolved/invalid/unavailable credential을 task publish 전에 차단한다. Preview는 safe blocker/warning만 반환한다.
- Workflow Engine Slack/GitHub node는 execution context의 canonical organization과 explicit user execution subject를 사용한다. app/workflow owner fallback은 허용하지 않는다.
- Runtime은 resolver로 secret을 메모리에 투영한 뒤 provider request 바로 전에 fresh DB session에서 동일 credential id/provider/revision의 `use`를 재검증한다.
- Provider adapter는 secret material의 `repr`/copy를 막고 trace에는 delivery outcome, status bucket, latency 같은 allowlisted metadata만 남긴다.

## Audit And Redaction

- Lifecycle action은 `external_action_credential.create`, `external_action_credential.update`, `external_action_credential.revoke`를 사용한다.
- Lifecycle mutation과 해당 canonical audit row는 같은 transaction에서 한 번만 저장한다.
- Permission denial은 common `permission.denied` audit을 사용하며 resource id, organization id, effective auth state와 safe correlation id만 허용한다.
- Credential secret, raw Webhook URL, GitHub authorization header, channel, comment/message body와 raw provider exception은 audit/trace에 포함하지 않는다.
