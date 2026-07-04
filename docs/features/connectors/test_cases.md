# Connectors Test Cases

Status: Draft
Verified Against: TBD

이 문서는 현재 workflow DB connector와 목표 Knowledge source connector가 공유해야 하는 보안 경계를 검증한다. Knowledge source connector target case는 [ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)의 egress/adapter gate가 닫힌 뒤 구현 blocker가 된다.

## 단위 테스트

- URL canonicalization은 IDNA/punycode, CNAME, IPv4 obfuscation, redirect target을 정규화한 뒤 private/link-local/metadata IP를 차단한다.
- HTTP adapter는 `verify=false`, HTTPS downgrade, unsupported scheme, oversized response, compression bomb, sensitive header redirect forwarding을 거부한다.
- DB adapter는 connector test/preview/sync 경로에서 arbitrary SQL을 허용하지 않고 read-only probe와 schema introspection cap만 수행한다.
- SSH adapter는 connector test/preview/sync 경로에서 임의 command 실행을 허용하지 않는다.
- Object-storage adapter는 과도한 listing 범위를 cap으로 제한하고 object key 원문을 audit/log에 남기지 않는다.

## API 테스트

- Knowledge source connector test/preview/fetch/sync 요청은 중앙 `OutboundEgressGuard` 또는 승인된 client/dialer factory를 통과하지 않으면 실패한다.
- `/api/v1/rag/proxy/preview`, URL 기반 upload/preview(`s3FileUrl`, `apiUrl`) target 이관 후에는 private network, metadata IP, redirect 우회, unsupported scheme을 거부한다.
- Connector 실패 응답은 raw host, secret, token, raw source path, raw exception stack을 노출하지 않는다.
- 현재 `/api/v1/connectors/test`와 schema endpoint가 target guard로 이관되기 전에는 current behavior와 target requirement를 문서상 구분한다.

## E2E 테스트

- Organization-scoped Knowledge source connector는 active organization 밖 resource 또는 user-owned `connections`를 자동 사용하지 않는다.
- Source sync가 실패해도 secret 원문, raw source id/url/path/title, raw connector exception이 UI, audit, trace, log에 표시되지 않는다.
- Connector health/remediation 화면은 safe reason code, retryability, coarse source type만 표시한다.

## 권한 테스트

- Connection owner 또는 organization manager가 아닌 사용자는 secret manage/read endpoint를 사용할 수 없다.
- Workflow/KB 권한만 있는 사용자는 current user-owned `connections` 사용 권한을 자동으로 얻지 않는다.
- Knowledge source connector의 use/manage/sync 권한은 KB content retrieval 권한이나 raw/compliance access 권한을 대체하지 않는다.

## Edge Case

- SSH tunnel, proxy, approved private network segment는 별도 connector/egress ADR이 승인되기 전까지 Knowledge source collection에서 기본 거부된다.
- DNS rebinding과 redirect chain 중간에 안전한 host가 포함돼도 최종 target이 금지 IP면 거부한다.
- Source connector가 public ACL을 보고하더라도 organization-wide read/use로 자동 materialize하지 않는다.
