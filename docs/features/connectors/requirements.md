# Connectors Requirements

Status: Draft
Related Features: workflow, organization, audit-tracing, knowledge

## Purpose

외부 DB를 workflow의 data source로 연결하는 기능을 제공한다. 연결 테스트/등록/스키마 조회 API(`/api/v1/connectors`)와 `connections` 테이블(암호화 비밀번호, SSH 터널 설정 포함)이 구현돼 있으며, workflow의 DB 노드가 이 연결을 사용한다. 이 feature의 범위는 연결 관리와 그 보안 경계다.

Knowledge source connector는 [Knowledge](../knowledge/requirements.md) feature의 목표 범위지만, outbound egress, credential, adapter safety는 connectors feature의 공통 보안 경계와 정합해야 한다.

## User Stories

- 빌더로서, 외부 DB 연결을 등록하기 전에 접속 정보가 유효한지 테스트하고 싶다.
- 빌더로서, 등록한 연결의 스키마(테이블/컬럼)를 조회해 workflow DB 노드 설정에 사용하고 싶다.
- 빌더로서, workflow에서 등록된 연결을 참조해 쿼리를 실행하고 싶다.

## Functional Requirements

- 외부 DB 연결의 테스트/등록/상세/스키마 조회를 제공한다. 지원 DB 종류는 `SupportedDBType` 기준을 따른다.
- DB 비밀번호와 SSH 비밀번호/개인키는 암호화 저장(`encrypted_password`, `encrypted_ssh_*`)하고 응답으로 반환하지 않는다.
- workflow DB 노드는 connection id 참조로 연결을 사용한다.
- 목표 Knowledge source connector와 KB source collection으로 승격되는 server-side test/preview/fetch/probe는 중앙 `OutboundEgressGuard` 또는 승인된 client/dialer factory를 통과해야 한다 ([ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)). 기존 workflow DB connector API 전체가 이미 이 보호를 받는다는 뜻은 아니다.

## Policies And Edge Cases

- connection `use`는 별도 permission table 없이 소비하는 workflow/knowledge base 권한으로 허용하는 방향을 검토하되, 현재 user-owned `connections`에서는 connection owner/organization scope 확인이 선행돼야 한다. Secret 조회/관리(manage)는 connection owner 또는 organization owner/manager로 제한한다 ([data_model.md](../../data_model.md) "만들지 않는 테이블" 참조).
- 현재 `connections` 테이블은 user 소유이며 `organization_id`가 없다. 조직 경계 판정이 다른 리소스와 다르므로, target Knowledge source connector에서 workflow/KB 권한만으로 connection use가 자동 허용된다고 해석하지 않는다.
- 연결 실패/타임아웃은 원문 접속 정보를 노출하지 않는 오류 메시지로 처리한다.
- HTTP/URL 계열 connector는 DNS resolve 후 IP 재검증, IDNA/punycode/CNAME/IPv4 obfuscation canonicalization, redirect마다 재검증, private/link-local/metadata IP 차단, scheme allowlist, HTTPS downgrade 금지, `verify=false` 금지, sensitive header redirect stripping, timeout/size/content-type cap, compression bomb 방지, rate limit을 적용한다.
- DB/SSH connector는 arbitrary SQL/command를 connector test/preview/sync 경로에서 허용하지 않는다. 필요한 경우 read-only probe, schema introspection cap, credential scope 제한, tunnel/proxy 정책을 adapter별로 문서화한다.
- Internal DB/API/private-network targets are denied by default for Knowledge source collection unless a future connector/egress ADR defines an explicit organization policy, approved network segment, audit-safe reason code, and operational owner.

## Open Questions

- `connections`에 organization scope를 도입할지 (현재 user 소유 → 조직 리소스로 전환 여부).
- SSH 터널 경유 연결의 아웃바운드 통제(Squid proxy/NetworkPolicy)와의 관계 정리.
- 기존 `/api/v1/connectors/test`와 schema endpoint를 central egress guard로 이관할 시점과 운영 compatibility 범위.
- 공식 API errors 문서에서 `egress.*`, `adapter.sql_not_allowed`, `adapter.ssh_command_not_allowed`, `adapter.object_listing_too_broad` 같은 sanitized reason code 계열을 확정할 시점.
