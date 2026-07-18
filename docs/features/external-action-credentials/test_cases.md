# External Action Credentials Test Cases

Status: Draft

## Model And Encryption

- EAC-TC-001: Migration upgrade/downgrade가 credential 및 user/team permission table과 foreign key/index를 정확히 반영한다.
- EAC-TC-002: Secret은 versioned envelope로만 저장되고 response/ORM projection/`repr`에 평문이 없다.
- EAC-TC-003: Slack Webhook은 canonical commercial URL만 허용하며 invalid provider, control character, blank/oversized secret은 저장 전에 거부한다.
- EAC-TC-004: 구키·신키 keyring은 기존 ciphertext 복호화와 active version 신규 암호화를 모두 지원한다.

## API And Permission

- EAC-TC-010: organization manager만 create를 수행하고 `read/use/manage`는 user/team strongest auth state로 판정한다.
- EAC-TC-011: credential option/detail/mutation은 safe field만 반환하며 secret/ciphertext/key metadata가 없다.
- EAC-TC-012: Cross-organization 및 same-organization unauthorized resource access는 existence를 노출하지 않는다.
- EAC-TC-013: 빈 PATCH, unknown field, stale revision, revoked credential update/new grant는 safe validation/conflict로 거부한다.
- EAC-TC-014: revoked credential은 실행용 option 및 `use` 집계에서 제외된다. 관리 option에는 `manage` 가능한 revoked 항목이 safe 상태와 함께 포함되고, 기존 grant 조회·회수만 허용하며 신규 grant UI/API는 차단한다.
- EAC-TC-015: lifecycle mutation은 상태 변경과 같은 transaction에 canonical audit를 정확히 한 번 추가하고 allowlist 밖 request metadata와 secret material을 저장하지 않는다.

## Graph, Builder And Client

- EAC-TC-020: Slack/GitHub node 저장 payload와 Agent Builder GraphMutation은 `credential_id`만 포함한다.
- EAC-TC-021: Slack `authConfig.token`, raw Webhook URL과 GitHub `api_token`/`token`/`authConfig`는 최상위와 nested subgraph 모두에서 거부된다. GitHub의 `authorization`, `headers`, `secret`처럼 allowlist 밖의 durable data도 같은 저장 경계에서 거부된다.
- EAC-TC-022: legacy persisted graph는 response/copy/migration에서 direct field와 GitHub allowlist 밖 field를 제거하고 unresolved로 표시한다. `displayNumber`와 `visibleProperties` 같은 검증된 편집기 metadata는 migration에서도 보존한다. Slack의 legacy HTTP `headers`/`body`/auth configuration도 보존하지 않는다. rollback은 secret을 복원하지 않는다.
- EAC-TC-023: picker는 active organization에서 `use` 가능한 safe option만 표시하고 direct token input을 렌더링하지 않는다.
- EAC-TC-024: Slack catalog는 safe delivery output만 광고하며 raw headers/body selector는 migration error로 차단한다.

## Preflight And Runtime

- EAC-TC-030: preflight는 active state, expected provider, principal `use`를 safe snapshot으로 검사하되 decrypt/network I/O를 수행하지 않는다.
- EAC-TC-031: missing, revoked, cross-organization, wrong provider와 permission denial은 동일 safe unavailable reason으로 projection한다.
- EAC-TC-032: preview는 permission-denied audit을 만들지 않고 active create/toggle/authenticated enforcement는 resource별 한 번만 기록한다.
- EAC-TC-033: runtime resolver는 explicit user execution subject, organization, active state, provider, `use`를 통과한 credential만 decrypt한다.
- EAC-TC-034: 권한 회수, revoke 또는 revision rotation이 resolver 이후 발생해도 provider call 직전 revalidation이 외부 adapter를 호출하지 않고 fail-closed한다.
- EAC-TC-035: Gateway와 Workflow Worker는 invalid keyring/active key version에서 startup fail-fast한다.

## Non-Exposure

- EAC-TC-040: API, graph, deployment snapshot, audit, trace, structured log, exception, test fixture에 secret/ciphertext/raw provider response가 없다.
- EAC-TC-041: permission denial audit은 safe correlation metadata만 가지며 raw URL, header, repository, channel/message/comment을 포함하지 않는다.
