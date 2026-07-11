# Mail Credentials Test Cases

Status: Draft

## Model And Encryption

- MAIL-CRED-TC-001: Migration upgrade/downgrade가 Mail credential과 user/team permission table을 정확히 반영한다.
- MAIL-CRED-TC-002: 저장된 ciphertext는 입력 secret과 다르고 올바른 key version으로만 복호화된다.
- MAIL-CRED-TC-003: Unknown key version과 손상된 ciphertext는 safe 오류로 실패한다.
- MAIL-CRED-TC-004: 구키·신키 keyring은 기존 `v1` ciphertext를 복호화하면서 신규 secret을 active `v2`로 암호화한다.
- MAIL-CRED-TC-005: Disposable PostgreSQL에서 migration head upgrade, Mail credential/user/team permission CRUD, one-step downgrade와 re-upgrade가 통과한다.

## API And Permission

- MAIL-CRED-TC-010: Organization manager만 credential을 등록할 수 있다.
- MAIL-CRED-TC-011: `viewer`는 safe detail만 조회하고 `use` 권한자는 picker option과 runtime 사용이 가능하지만 누구도 secret을 조회할 수 없다.
- MAIL-CRED-TC-012: `manage` 권한자는 secret을 교체하고 revoke할 수 있다.
- MAIL-CRED-TC-013: Cross-organization 접근은 `404`, in-scope denial은 `403`이다.
- MAIL-CRED-TC-014: Unknown field와 빈 PATCH는 validation error다.
- MAIL-CRED-TC-015: Revoked credential은 option 목록에서 제외된다.
- MAIL-CRED-TC-016: Revoked credential의 수정과 신규 permission grant는 `409 mail.credential_revoked`로 거부되고 기존 permission 회수는 허용된다.
- MAIL-CRED-TC-017: Lifecycle 또는 permission audit row 저장 실패 시 credential mutation도 rollback된다.

## Runtime

- MAIL-CRED-TC-020: Runtime resolver는 scope, active, `use`, decrypt를 통과한 credential만 반환한다.
- MAIL-CRED-TC-021: 권한 회수와 revoke는 다음 실행부터 즉시 반영된다.
- MAIL-CRED-TC-022: 인증 test/deployment run은 같은 resolver와 명시 execution subject를 사용한다. Public/schedule run은 owner fallback 없이 차단된다.
- MAIL-CRED-TC-023: Provider 연결 전에 permission denial과 decrypt failure가 발생한다.
- MAIL-CRED-TC-024: `993`은 implicit TLS, `143`은 로그인 전 STARTTLS를 수행하고 다른 mode/port 조합과 private target을 거부한다.
- MAIL-CRED-TC-025: 검색 입력의 quote/backslash는 IMAP quoted-string으로 escape하고 CR/LF/NUL은 provider 호출 전에 거부한다.
- MAIL-CRED-TC-026: Select/search/fetch/logout의 provider raw exception은 safe reason code로 변환되거나 cleanup에서 흡수되어 log에 남지 않는다.
- MAIL-CRED-TC-027: Revoked credential permission row가 남아 있어도 direct permission count, team source count, team inherited resource count와 team mutation 영향 count에는 포함되지 않는다.

## Graph And Client

- MAIL-CRED-TC-030: Mail node save payload에는 `credential_id`만 있고 password/token이 없다.
- MAIL-CRED-TC-031: Legacy inline secret graph는 `mail.credential_reference_required`로 실패한다.
- MAIL-CRED-TC-032: Mail panel은 safe option만 표시하고 password input을 렌더링하지 않는다.
- MAIL-CRED-TC-033: Agent Builder는 unresolved `credential_id`를 만들고 자동 선택하지 않는다.
- MAIL-CRED-TC-034: 관리자 콘솔과 actor access drawer는 Mail credential user/team 권한을 조회·부여·회수한다.
- MAIL-CRED-TC-035: Unknown Mail data field와 비어 있지 않은 `parameters`는 workflow 저장, Agent Builder apply/save, 비활성 포함 deployment 생성과 기존 deployment 활성화에서 모두 거부된다.

## Non-Exposure

- MAIL-CRED-TC-040: API response, graph, audit, trace, log와 fixture에 secret/ciphertext가 없다.
- MAIL-CRED-TC-041: 로그인 및 로그인 이후 작업/cleanup의 provider raw exception과 mailbox email 원문이 audit/trace/log에 없다.
- MAIL-CRED-TC-042: DB 예외 문자열에 mailbox identity나 ciphertext가 포함되어도 audit metadata와 API 오류에는 안전한 error code만 남는다.
