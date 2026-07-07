# Connectors Requirements

Status: Draft
Verified Against: feature/mba-120 @ 7a7032e
Related Features: workflow, organization, audit-tracing, knowledge

## Purpose

Connectors 기능은 외부 데이터 소스에 접속하기 위한 연결 정보를 관리한다. 현재 구현 범위는 PostgreSQL DB 연결 테스트, 연결 저장, 연결 상세 조회, 스키마 조회 API(`/api/v1/connectors`)와 `connections` 테이블이다. DB 비밀번호와 SSH 비밀번호/개인키는 서버에서 암호화 저장하고, 응답에는 secret 원문을 반환하지 않는다.

이 feature의 책임은 연결 등록과 조회, owner 기반 접근 제한, secret 저장/비노출, DB probe/schema 조회의 보안 경계다. 사용자 인증 생명주기, organization/team RBAC 부여, workflow 실행 권한, Knowledge Base 권한, Knowledge sync scheduler/worker는 connectors 자체의 책임이 아니다.

## User Stories

- 빌더는 외부 DB 연결 정보를 저장하기 전에 접속 가능 여부를 테스트할 수 있다.
- 빌더는 외부 DB 연결 정보를 저장하고, 이후 workflow 또는 Knowledge DB source 설정에서 connection id를 참조할 수 있다.
- 빌더는 저장한 연결의 테이블, 컬럼, FK 정보를 조회해 DB source의 테이블/컬럼 선택에 사용할 수 있다.
- 빌더는 저장한 연결 상세를 다시 열 때 비밀번호나 SSH secret 원문이 노출되지 않은 host/port/database/username/SSH metadata만 볼 수 있다.
- 플랫폼 운영자는 connector가 workflow 권한과 KB 권한의 책임을 대체하지 않는다는 점을 기준으로 운영 위험을 판단할 수 있다.

## Functional Requirements

### Current DB Connection Requirements

- CONN-REQ-001: 시스템은 `/api/v1/connectors` 하위 API로 외부 DB 연결 테스트, 저장, 상세 조회, 스키마 조회를 제공해야 한다.
- CONN-REQ-002: 현재 지원 DB 타입은 Gateway `SupportedDBType` 기준 `postgres`여야 한다.
- CONN-REQ-003: 클라이언트는 PostgreSQL을 활성 선택지로 제공하고, MySQL은 disabled/Coming Soon 선택지로 표시해야 한다.
- CONN-REQ-004: DB 연결 요청은 `connection_name`, `type`, `host`, `port`, `database`, `username`, `password`, 선택적 `ssh` 설정을 받아야 한다.
- CONN-REQ-005: SSH 설정은 `enabled`, `host`, `port`, `username`, `auth_type`, `password`, `private_key`를 포함할 수 있어야 한다.
- CONN-REQ-006: `ssh.enabled`가 false이면 Gateway는 adapter에 전달하는 설정에서 SSH 구성을 비활성화해야 한다.
- CONN-REQ-007: `POST /connectors/test`는 요청 연결 정보로 실제 DB 접속을 확인하고 `success`와 `message`를 반환해야 한다.
- CONN-REQ-008: `POST /connectors/test`는 현재 저장소에 connection row를 만들지 않아야 한다.
- CONN-REQ-009: `POST /connectors/test`에서 지원하지 않는 DB 타입은 `success=false`와 지원하지 않는 타입 메시지로 반환되어야 한다.
- CONN-REQ-010: `POST /connectors`는 인증된 현재 사용자를 요구해야 한다.
- CONN-REQ-011: `POST /connectors`는 저장 전 같은 연결 정보로 DB 접속 테스트를 수행해야 한다.
- CONN-REQ-012: `POST /connectors`는 저장 전 접속 테스트에 10초 timeout을 적용해야 한다.
- CONN-REQ-013: 저장 전 접속 테스트가 실패하면 시스템은 connection row를 만들지 않아야 한다.
- CONN-REQ-014: 저장 성공 시 시스템은 `connections.user_id`를 현재 사용자 ID로 설정해야 한다.
- CONN-REQ-015: 저장 성공 시 시스템은 DB 비밀번호를 `encrypted_password`에 암호화 저장해야 한다.
- CONN-REQ-016: SSH password 인증을 사용하는 저장 성공 시 시스템은 SSH 비밀번호를 `encrypted_ssh_password`에 암호화 저장해야 한다.
- CONN-REQ-017: SSH key 인증을 사용하는 저장 성공 시 시스템은 SSH private key를 `encrypted_ssh_private_key`에 암호화 저장해야 한다.
- CONN-REQ-018: 저장 성공 응답은 생성된 connection id, success flag, 사용자 표시용 message만 반환해야 한다.
- CONN-REQ-019: 저장 성공은 `connection.create` audit action으로 기록되어야 한다.
- CONN-REQ-020: `GET /connectors/{connection_id}`는 인증된 현재 사용자를 요구해야 한다.
- CONN-REQ-021: `GET /connectors/{connection_id}`는 connection owner가 아니면 `403`으로 거부해야 한다.
- CONN-REQ-022: `GET /connectors/{connection_id}`는 비밀번호, SSH 비밀번호, SSH private key, encrypted secret 값을 반환하지 않아야 한다.
- CONN-REQ-023: `GET /connectors/{connection_id}/schema`는 인증된 현재 사용자를 요구해야 한다.
- CONN-REQ-024: `GET /connectors/{connection_id}/schema`는 connection owner가 아니면 `403`으로 거부해야 한다.
- CONN-REQ-025: `GET /connectors/{connection_id}/schema`는 저장된 encrypted secret을 서버에서만 복호화해 adapter 접속 설정을 구성해야 한다.
- CONN-REQ-026: PostgreSQL schema 조회는 table name, column name/type, FK의 column/referenced table/referenced column 정보를 반환해야 한다.
- CONN-REQ-027: DB schema 조회는 secret 원문을 응답 body에 포함하지 않아야 한다.
- CONN-REQ-028: 현재 `connections` 테이블은 user-owned resource이며 `organization_id`를 갖지 않는다.
- CONN-REQ-029: 현재 connection owner 판정은 organization/team permission helper가 아니라 `connections.user_id == current_user.id` 기준이어야 한다.
- CONN-REQ-030: connector test, create, schema 조회 실패 응답은 raw host, database name, secret, driver detail, stack trace를 포함하지 않고 safe message 또는 safe `reason_code`로 닫아야 한다.
- CONN-REQ-031: PostgreSQL 직접 연결 경로는 DB host/port를 사전 검증해 private, loopback, link-local, metadata, reserved target을 거부하고, 검증된 public IP로 실제 연결 대상을 고정해야 한다.
- CONN-REQ-032: 기존 workflow DB connector compatibility 경로는 문서화된 SSH tunnel 설정을 사용할 수 있다. 이 허용은 workflow connector API 경계에서 명시적으로 선택해야 하며, arbitrary SSH command execution 허용을 의미하지 않는다.
- CONN-REQ-033: Knowledge DB source ingestion이 공유 PostgreSQL adapter를 사용할 때는 기본 정책으로 SSH tunnel, proxy, private-network target을 거부해야 한다. 이 경로에서 tunnel을 열려면 별도 connector/egress ADR 또는 승인된 organization policy가 필요하다.
- CONN-REQ-034: PostgreSQL schema introspection은 table, column, foreign key 개수 상한을 적용하고, 잘린 결과는 safe truncation marker로 표시해야 한다.
- CONN-REQ-035: DB row fetch 경로는 SELECT-only guard, dangerous function/keyword blocklist, read-only transaction, statement timeout, batch size cap, total row cap을 적용해야 한다.

## Policies And Edge Cases

- 현재 `POST /connectors/test`는 Gateway 코드상 `get_current_user`를 요구하지 않는다.
- 현재 `POST /connectors`는 `get_current_user`를 요구하지만 resource permission table을 사용하지 않는다.
- 현재 `GET /connectors/{connection_id}`와 `GET /connectors/{connection_id}/schema`는 없는 connection에 `404`, owner mismatch에 `403`을 반환한다.
- create/test/schema 실패 메시지는 raw host, database, secret, driver detail을 응답에 포함하지 않아야 한다.
- 현재 schema 조회는 SQLAlchemy inspector를 사용해 schema metadata를 읽는다.
- schema 조회 cap은 UX용 metadata preview 범위를 제한하기 위한 것이며, connector가 전체 DB inventory를 durable storage, audit, trace, log에 저장해도 된다는 의미가 아니다.
- SSH tunnel compatibility는 기존 workflow DB connector 기능을 보존하기 위한 경계다. Knowledge source ingestion의 기본 경계와 다르며, SSH tunnel 허용은 remote shell command 실행 허용으로 해석하지 않는다.
- 현재 `DbProcessor`는 Knowledge DB source ingestion에서 저장된 `connection_id`를 조회하고 선택된 테이블/컬럼 기반 SQL을 생성한다. 이 ingestion lifecycle은 Knowledge feature 책임이다.
- `connections`에는 `created_at/updated_at`과 `organization_id`가 없다.

### Knowledge Source Connector Target Requirements

- CONN-KNOW-REQ-001: 목표 Knowledge source connector와 KB source collection으로 승격되는 server-side test, preview, fetch, probe는 중앙 `OutboundEgressGuard` 또는 승인된 client/dialer factory를 통과해야 한다 ([ADR-0014](../../decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md), [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md), [ADR-0020](../../decisions/ADR-0020-knowledge-mcp-incremental-sync-boundary.md)). 이 요구사항은 기존 workflow DB connector API 전체가 이미 같은 보호를 받는다는 뜻이 아니다.
- CONN-KNOW-REQ-002: HTTP/URL 계열 Knowledge connector는 DNS resolve 후 IP 재검증, IDNA/punycode/CNAME/IPv4 obfuscation canonicalization, redirect마다 재검증, private/link-local/metadata IP 차단, scheme allowlist, HTTPS downgrade 금지, `verify=false` 금지, sensitive header redirect stripping, timeout/size/content-type cap, compression bomb 방지, rate limit을 적용해야 한다.
- CONN-KNOW-REQ-003: DB/SSH connector는 arbitrary SQL/command를 connector test, preview, sync 경로에서 허용하지 않아야 한다. 필요한 경우 read-only probe, schema introspection cap, credential scope 제한, tunnel/proxy 정책을 adapter별로 문서화해야 한다.
- CONN-KNOW-REQ-004: Knowledge Slack/meeting connector의 초기 baseline은 channel을 Knowledge Collection으로, thread/huddle recap/canvas/bot-generated meeting summary/pinned-message group을 document-level KB로 매핑한다.
- CONN-KNOW-REQ-005: Slack/meeting artifact-level ACL이 있으면 artifact ACL과 containing channel/workspace ACL의 교집합을 requester authorization으로 사용하고, artifact ACL을 확인할 수 없으면 fail-closed 또는 remediation 상태로 둔다. Channel membership만으로 huddle recap, canvas, meeting summary를 자동 공개하지 않는다.
- CONN-KNOW-REQ-006: Slack/meeting DM, raw audio, raw transcript는 별도 opt-in policy 없이 수집하지 않는다.
- CONN-KNOW-REQ-007: Source ACL sync는 source authorization provenance와 freshness evidence를 만든다. Source ACL fact만으로 mbased KB `use`를 부여하지 않으며, auto-ingested KB retrieval에는 admin/team/user grant 또는 organization-approved connector/source policy가 provision한 explicit KB `use`가 필요하다.
- CONN-KNOW-REQ-008: MCP/API 기반 Knowledge source connector는 LLM 자유 tool-use surface가 아니라 server-side adapter allowlist로 동작해야 한다. Allowlist 밖 operation, raw source data direct fetch, LLM prompt/completion을 source query parameter로 사용하는 flow는 허용하지 않는다.
- CONN-KNOW-REQ-009: Knowledge source connector는 runtime authorization primitive로 `check_access_batch(subject_ref, source_item_refs[])`를 우선 제공해야 한다. Batch 미지원 source는 bounded single `check_access(subject_ref, source_item_ref)` fallback을 제공할 수 있지만, 둘 다 없으면 private source-managed KB retrieval은 fail-closed 대상이다.
- CONN-KNOW-REQ-010: Connector는 source별 raw payload를 Knowledge가 소비할 safe normalized shape로 변환해야 하며, 변환 전 raw payload는 connector debug/error log, retry/dead-letter payload, audit, trace에 남기지 않아야 한다.
- CONN-KNOW-REQ-011: Connector가 source-side search를 Live-linked mode에 제공하려면 requester-scoped search이거나 opaque source ref-only result여야 한다. Broad service-account search가 authorization 전 title, snippet, count, score를 반환하는 flow는 기본 구현으로 허용하지 않는다.
- CONN-KNOW-REQ-012: File/page artifact를 가져오는 Knowledge source connector는 egress guard 이후에도 content를 untrusted로 취급해야 한다. Connector 또는 ingestion boundary는 지원 file type/content type allowlist, archive depth/expanded-size/file-count cap, macro/script/embedded object/executable 차단, parser sandbox/least-privilege 실행, malware/content scan hook을 redacted canonical text 생성 전에 적용해야 한다. Scan failure, timeout, unsupported type, active content detection은 indexing-visible artifact를 만들지 않고 fail-closed 또는 remediation으로 처리한다.

## Knowledge Source Connector Policies

- 현재 `connections` 테이블은 user 소유이며 `organization_id`가 없다. 조직 경계 판정이 다른 리소스와 다르므로, target Knowledge source connector에서 workflow/KB 권한만으로 connection use가 자동 허용된다고 해석하지 않는다.
- connection `use`는 별도 permission table 없이 소비하는 workflow/knowledge base 권한으로 허용하는 방향을 검토하되, 현재 user-owned `connections`에서는 connection owner/organization scope 확인이 선행돼야 한다. Secret 조회/관리(manage)는 connection owner 또는 organization owner/manager로 제한한다 ([data_model.md](../../data_model.md) "만들지 않는 테이블" 참조).
- Internal DB/API/private-network targets are denied by default for Knowledge source collection unless a future connector/egress ADR defines an explicit organization policy, approved network segment, audit-safe reason code, and operational owner.
- Bot/webhook/app installation visibility는 capture signal 또는 event detection에 사용할 수 있지만 requester authorization으로 취급하지 않는다. Private source-managed retrieval은 delegated OAuth, source subject mapping, or runtime authorization primitive를 통해 별도 확인해야 한다.

## Open Questions

- `connections`를 organization-scoped resource로 전환할지, user-owned resource로 유지할지 결정해야 한다.
