# ADR-0032: Mail 처리 claim과 Gmail 답장 초안 멱등성 경계

Status: Accepted
Related ADRs: ADR-0022, ADR-0031

## 배경

ADR-0031은 organization-scoped Mail credential과 workflow graph의 opaque `credential_id` 경계를 확정했다. 현재 Mail node는 IMAP 검색 후 선택적으로 메시지를 즉시 읽음 처리한다. 이 구조에는 다음 공백이 있다.

- IMAP sequence id는 durable message identity가 아니다.
- schedule 재실행이나 Celery 재전달이 같은 메일을 반복 처리할 수 있다.
- Gmail 답장 초안과 후속 알림이 끝나기 전에 원본 메일이 읽음 처리될 수 있다.
- Gmail `users.drafts.create`는 provider idempotency key를 지원하지 않아 요청 결과 유실 뒤 무조건 retry하면 중복 draft가 생길 수 있다.
- `gmail.compose` OAuth scope는 draft뿐 아니라 send도 허용하므로 scope만으로 no-send를 보장할 수 없다.

## 결정

1. Durable Mail 자동화는 `(organization_id, workflow_id, source_node_id, credential_id, provider, message_identity_hash)`로 message processing을 식별한다. Deployment version이 바뀌어도 같은 workflow와 stable source node id는 같은 logical consumer다.
2. Mail 검색 node는 `search_only`와 `durable` processing mode를 지원한다. 기존 graph의 기본값은 `search_only`다. Durable mode는 최소 provider source reference를 암호화한 processing row를 생성하고 후속 node에는 opaque `processing_ref`만 전달한다.
3. IMAP sequence id 단독 사용을 금지한다. RFC Message-ID와 IMAP UID/UIDVALIDITY를 우선 사용하고 Gmail REST 호출 직전에 Gmail API에서 canonical message/thread identity를 다시 확인한다. Gmail IMAP extension id를 REST API id로 직접 가정하지 않는다.
4. Gmail 답장 초안은 별도 `gmailDraftNode`가 담당한다. 수신 검색과 provider mutation을 하나의 node operation으로 합치지 않는다.
5. Gmail OAuth는 로그인 OAuth와 분리된 ADR-0031 Mail credential resource로 저장한다. Refresh token은 기존 versioned encryption envelope를 사용하고 workflow graph, API response, audit, trace, log에 저장하지 않는다.
6. Gmail draft adapter port는 `create_reply_draft`만 노출한다. `users.drafts.send`, `users.messages.send`와 arbitrary Gmail method/URL 호출을 구현하지 않는다. `gmail.compose` scope가 send를 허용하므로 이 application capability allowlist가 no-send의 실제 경계다.
7. Draft effect는 `(processing_id, node_id, operation_key_hash)`로 하나만 admission한다. Provider 호출 전에 durable claim을 commit한다.
8. Effect outcome은 `succeeded`, `failed_before_effect`, `outcome_unknown`을 구분한다. 요청 전달 뒤 timeout이나 응답 유실처럼 생성 여부를 확정할 수 없는 경우 `outcome_unknown`으로 격리하고 자동 replay하지 않는다.
9. Terminal acknowledgement는 명시적 `mailAcknowledgeNode`가 processing row와 required effect reference를 서버에서 검증한 뒤 수행한다. Client가 제출한 성공 boolean은 신뢰하지 않는다.
10. Durable mode에서는 `mailNode.mark_as_read=true`를 거부한다. Search-only mode는 모든 선택 메시지 fetch가 성공한 뒤에만 일괄 읽음 처리할 수 있다. 일부 fetch가 실패하면 어느 메시지도 읽음 처리하지 않는다.
11. Draft 성공 뒤 acknowledgement가 실패하면 draft를 다시 생성하지 않고 acknowledgement만 재시도한다. `outcome_unknown`과 terminal success 상태는 일반 실행 경로에서 pending으로 되돌리지 않는다.
12. Gmail 답장 MVP는 원본 sender 한 명, `text/plain` UTF-8, 무첨부로 제한한다. Reply-all, CC, BCC, HTML, attachment와 자동 발송은 지원하지 않는다.
13. Processing/effect row와 telemetry에는 body, snippet, subject, recipient, MIME, token, raw provider identifier/response/error를 저장하지 않는다. Provider 재조회에 필요한 최소 identifier는 versioned encryption envelope로 보호하고 client에는 processing/effect resource를 가리키는 opaque reference만 반환한다.
14. MBA-190의 범용 외부 effect 계약을 선행 조건으로 두지 않는다. 이 ADR은 Mail/Gmail 전용 port와 outcome 의미를 작게 구현하고, 이후 공통 계약이 확정되면 adapter로 정렬한다.

## 검토한 대안

### Gmail draft를 기존 Mail node operation으로 추가

검색과 외부 mutation은 권한, retry, output과 실패 의미가 다르다. 기존 IMAP workflow 호환성과 effect admission 경계를 흐리므로 채택하지 않았다.

### Provider timeout을 동일 요청으로 자동 retry

Gmail Draft API에는 idempotency key가 없어 응답 유실 뒤 중복 draft를 만들 수 있다. 요청 전 실패가 확정된 경우만 bounded retry하고 결과 불명 상태는 격리한다.

### Workflow 실행 종료 hook에서 자동 acknowledgement

공통 Workflow Engine lifecycle을 Mail 전용 정책으로 변경하고 병렬 effect의 required/optional 의미를 암묵적으로 추론하게 된다. Graph에 명시적 acknowledgement node를 두는 방식을 채택한다.

### Organization/mailbox 단위 전역 message deduplication

서로 다른 workflow가 같은 메일을 합법적으로 처리할 수 없게 된다. Workflow와 stable source node를 logical consumer scope에 포함한다.

### Gmail IMAP extension id를 REST id로 변환

두 protocol의 identifier 표현에 구현이 결합되고 canonical 확인을 생략하게 된다. REST 호출 직전에 Gmail API source lookup으로 message/thread identity를 검증한다.

## 결과

- Mail processing과 Gmail draft effect용 additive table 및 migration이 필요하다.
- Mail credential은 OAuth secret payload를 지원하도록 확장되지만 ADR-0031의 organization scope, permission, encryption, revoke 경계를 유지한다.
- Workflow node catalog, Editor, Agent Builder, save/deploy/runtime validation에 두 신규 node와 processing mode가 추가된다.
- Gmail OAuth restricted scope 운영에는 Google verification 및 필요 시 security assessment가 별도로 요구될 수 있다.
- 외부 provider까지 포함한 exactly-once 또는 자동 발송을 보장하지 않는다.

