# Knowledge Test Cases

Status: Draft
Verified Against: `feature/mba-264 @ 8832d23b`
이 문서는 현재 RAG 동작과 목표 KB 통합 모델에 필요한 테스트 범위를 함께 기록한다. MBA-105 목표 모델 테스트는 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)과 [implementation_baseline.md](implementation_baseline.md)의 임시 baseline을 기준으로 구현 blocker가 된다.

## Unit Tests

- Metadata filter는 allowlist된 key/operator만 허용하고 free-form dict, JSONPath, raw SQL fragment, secret/header/prompt/completion/raw response field를 거부한다.
- Classification metadata가 없으면 [ADR-0007](../../decisions/ADR-0007-mvp2-classification-metadata-storage.md)에 따라 `internal`로 처리한다.
- 목표 cutover 전 `document_chunks.metadata`와 현재 `documents.meta_info`가 충돌하면 document metadata를 우선한다.
- 목표 metadata sanitizer는 protected source identity field를 public metadata/filter path에서 거부한다.
- Redaction은 기본적으로 chunk content, embedding input, retrieval-visible artifact에 사용되는 canonical text를 만든다.
- Raw source content를 저장하더라도 protected raw artifact store 또는 encrypted object storage metadata table에만 저장하고 `document_chunks.content`에는 저장하지 않는다.
- Raw artifact storage path는 organization/source opt-in, raw/compliance gate, encryption, retention, legal hold, purge, audit policy가 명시적으로 활성화되지 않으면 비활성 상태다.
- Privacy/Redaction baseline은 admin policy가 비활성화할 수 없고, organization/collection/source/KB policy는 더 엄격하게 조정하거나 승인된 display mode만 선택할 수 있다.
- Knowledge Skill body/resource는 raw source content, raw source title/path/url, raw principal, raw ACL fact, restricted document list, hidden KB id, raw prompt/completion/provider response를 포함하지 않는다.
- Skill metadata sanitizer는 skill name/description/tag/source tier/owner/freshness도 민감 metadata로 보고 display-policy-approved safe field만 허용한다.
- Stale/review-required/deprecated skill은 운영 workflow 생성 자동 후보나 실행 시점 RAG procedure에서 fail-closed 또는 remediation surface로 제한된다.
- Golden question/eval fixture는 raw restricted content를 포함하지 않고 safe reference와 expected behavior만 사용한다.
- Source public ACL은 기본적으로 organization-wide KB read/use로 materialize되지 않는다.
- Source ACL provenance storage는 raw source permission, source permission action/provenance, source authorization state, KB permission `auth_state`를 섞어 저장하지 않는다.
- Source ACL authorization만으로 KB `use`가 충족됐다고 판정하지 않는다.
- Auto-ingested KB는 admin/team/user grant 또는 organization-approved connector/source policy가 명시 KB `use`를 provision하지 않으면 retrieval 후보가 되지 않는다.
- Runtime access cache key는 source item 또는 document version 단위를 포함한다. Subject-level `allowed` cache가 다른 source item에 재사용되면 테스트 실패다.
- Redaction 전 ephemeral content handle은 process/run scope와 short TTL을 가지며 durable DB, retry/dead-letter payload, audit, trace, log, user-facing response에 handle value나 raw content가 남으면 테스트 실패다.
- Ingestion lock release는 owner token을 비교한다. TTL 만료 뒤 다른 worker가 lock을 획득한 경우 stale worker는 새 worker의 lock을 삭제하지 못한다.
- Fencing token 또는 동등한 guard가 없는 stale worker는 active version, `content_hash`, chunking fingerprint, external index namespace를 finalize하지 못한다.

## Permission And RBAC Tests

- Team onboarding demo seed는 회사 공통 PDF용 빈 KB를 플랫폼개발·영업·재무·People 팀에 부여하고, 각 팀 전용 빈 KB는 해당 팀과 People 팀에만 부여한다. 플랫폼개발팀 사용자의 runtime 후보에 영업·재무 KB가 포함되거나 영업팀 사용자의 후보에 플랫폼개발·재무 KB가 포함되면 실패한다.
- Team onboarding demo의 네 KB는 `demodata/` PDF를 Document로 등록한다. runtime OpenAI credential 옵션만 사용해도 기존 precomputed fixture가 법령·사내문서를 채우고, PDF를 실제 파싱한 `text-embedding-3-small` embedding을 생성해 reset 직후 검색 가능해야 한다. 이 경로는 로컬 법령 PDF 원본을 요구하지 않는다. 플랫폼 PDF의 manager-only 마지막 페이지는 chunk ACL을 가장하지 않고 일반 플랫폼 KB 복사본에서 제외한다.
- Demo reset은 demo Knowledge Base 또는 demo 사용자와 연결된 `user_knowledge_permissions`를 Knowledge Base보다 먼저 삭제해야 한다. migration backfill이나 시연 중 생성된 직접 권한이 남아 있어도 외래키 오류 없이 reset 후 같은 demo 상태를 재생성해야 한다.
- Demo reset은 demo Knowledge Base와 연결된 `knowledge_ingestion_outbox`만 Knowledge Base보다 먼저 삭제하고, 곧바로 upsert할 demo 조직 row 자체는 삭제하지 않는다. 같은 조직의 사용자 생성 Knowledge Base에 연결된 outbox 작업은 보존해야 하며, demo KB의 오래된 outbox 작업은 남지 않아야 한다.
- 현재 demo seed는 document-level KB 권한만 보장한다. 같은 PDF 안의 chunk별 동적 `role_acl`을 권한 경계로 주장하지 않으며 manager-only 내용은 별도 KB로 분리해야 한다.

- Document progress SSE는 stream을 열기 전에 active organization과 KB `read`를 검증한다. 권한 없는 actor나 다른 organization context는 document status, safe error, Redis progress를 한 건도 수신하지 못한다.
- KB hard delete는 Organization manager와 acknowledgement가 있어도 approved retention/legal-hold checker가 없으면 storage/DB mutation 전에 fail-closed한다. 삭제 mechanics transaction 테스트는 explicit allow checker를 주입하며 production eligibility 증거로 취급하지 않는다.
- Collection `read`, `route`, `manage`, `sync`만으로는 하위 KB content retrieval 권한이 생기지 않는다.
- Auto collection mode는 route 권한이 없는 collection scope에서 유래한 KB를 제외한다.
- Explicit KB mode는 collection route permission을 생략할 수 있지만 KB helper allow, source ACL gate, final evidence policy는 계속 요구한다.
- 현재 retrieval/search-test content access에는 KB `use`가 필요하며 read/listing permission만으로는 content retrieval이 되지 않는다.
- Source-managed KB는 mbased KB `use`와 fresh requester source ACL authorization을 모두 요구한다.
- 빌더 단계 skill visibility만으로 실행 시점 collection route, KB `use`, source ACL gate가 충족되지 않는다.
- Skill이 특정 KB/collection을 routing hint로 제안하더라도 실행 시점 permission helper가 거부한 KB는 workflow 실행 후보에서 제외된다.
- Manual KB grant는 stale/unmapped/ambiguous/unverified source ACL freshness gate를 우회하지 못한다.
- Source ACL revocation은 이후 retrieval을 막고 freshness epoch/cache invalidation signal을 갱신한다.
- Organization manager는 operations policy에 따라 remediation을 수행할 수 있지만 기본적으로 source ACL retrieval filtering을 우회하지 못한다.
- 다른 organization KB id의 response shape, audit behavior, answer-run 생성 여부는 ADR-0017 resource-hiding baseline에 따라 hidden identity를 만들지 않는다.
- Visible resource 확인 이후 same-scope KB use denial은 승인된 resource-hiding/API matrix를 따른다. Matrix가 resource visible 상태를 유지한다고 결정한 경우에만 `403 permission.denied`를 허용한다.
- Active organization member라는 사실만으로 KB `use`가 허용되지 않는다. Team 또는 user direct KB grant가 없고 organization manager override도 없으면 retrieval은 fail-closed다.
- `user_knowledge_permissions` direct grant는 같은 active organization member에게만 생성된다. invited/suspended/removed/non-member 대상은 safe validation 또는 hidden/not-found response로 닫는다.
- User direct KB grant와 team KB grant가 함께 있으면 가장 강한 additive allow가 effective permission이 된다. User direct grant가 team grant를 낮추거나 deny할 수 없다.
- User direct KB grant request에서 `none`은 거부한다. 권한 회수는 DELETE endpoint로만 표현한다.
- User direct KB grant가 있어도 source-managed KB retrieval은 fresh source ACL/requester authorization gate를 다시 통과해야 한다.
- MBA-231의 모든 KB-bearing API는 `read/use/write/content_read/manage` 중 하나로 분류되고 active organization scope를 먼저 고정한다. Owner attribution만으로 action이 허용되거나 Team/User grant가 owner predicate 때문에 거부되면 테스트 실패다.
- `content_read`는 builder 이상에 매핑되지만 source-managed original content는 requester source authorization과 approved display/raw policy가 없으면 Organization manager에게도 fail-closed된다.
- Active member manual KB create는 KB, creator user-direct `manager`, canonical audit를 한 transaction에서 생성한다. Grant 또는 audit flush/commit 실패는 세 row를 모두 rollback한다.
- Legacy owner backfill은 같은 organization active member만 grant하고 stronger grant를 낮추지 않으며 반복 실행해도 중복 row/audit을 만들지 않는다. Cross-org/inactive/non-member/ambiguous owner는 identity나 KB label 없이 safe finding bucket으로 남긴다.
- Team/User Knowledge domain grant는 Organization manager만 변경할 수 있고, action allowlist, same-org active subject, optional expiry와 non-negative flags constraint를 강제한다.
- Knowledge domain grant는 inactive Team, deactivated/removed User, non-member 또는 cross-organization subject를 계속 거부한다. Revoke는 같은 대상의 기존 permission row가 있으면 subject active check 없이 row를 lock/delete하고 audit와 함께 commit한다. Existing row가 없는 revoke는 idempotent하며 audit를 만들지 않는다.
- Inactive/removed subject의 domain permission revoke에서 audit 저장 또는 commit이 실패하면 permission delete도 rollback된다. 다른 organization의 동일 subject/action row는 조회·삭제·audit되지 않는다.
- Domain revoke repository test는 filter를 무시하는 query fake를 사용하지 않는다. PostgreSQL dialect로 organization/subject/action bind predicate와 `FOR UPDATE`를 compile 검증하고, opt-in disposable PostgreSQL test는 cross-org row 보존, audit failure rollback, 두 session의 concurrent revoke가 `deleted` 1회와 `unchanged` 1회 및 delete audit 1개만 만드는지 검증한다.
- Expired domain grant는 cleanup worker 실행 여부와 무관하게 effective action에서 제외된다. Team과 user direct domain grant는 additive allow이며 explicit deny를 만들지 않는다.
- Domain action은 KB read/use/content, Collection route를 상속하지 않는다. `catalog_manage`만 가진 actor의 RAG 검색과 원문 조회가 허용되면 테스트 실패다.
- `permission_delegate` actor가 자신 또는 자신이 active member인 Team에 content-plane grant를 시도하면 mutation 없이 safe policy block audit만 정확히 한 번 기록한다. Organization manager와 resource manager의 기존 recovery path는 별도 positive case로 검증한다.
- Collection role bundle은 Viewer=`read`, Workflow Router=`read+route`, Maintainer=`read+manage`, Sync Operator=`read+sync` explicit row를 한 transaction에서 적용한다. 일부 row 또는 audit 저장 실패 시 bundle 전체를 rollback하고 KB `use` row를 만들지 않는다.
- Domain `catalog_manage` actor는 private manual Collection과 membership을 관리할 수 있지만 public membership 변경은 Organization manager acknowledgement 없이는 차단된다. Source public exposure primitive가 없으면 source-managed KB의 public link/visibility 전환은 `source_public_exposure_required`로 fail-closed된다.

## MBA-232 Workflow Runtime Candidate Resolver Tests

- Shared runtime contract는 `AuthenticatedAudience(organization_id, user_id)`와 `AnonymousPublicAudience(organization_id)`만 허용하고 optional subject, owner, builder, deployment owner, credential principal, service account fallback을 표현하지 않는다.
- Runtime `collection_ids` missing/empty는 Collection stream 0개다. Gateway Builder resolver의 route-safe subset/direct-KB fallback을 호출하거나 organization 전체 Collection을 query하면 테스트 실패다.
- Direct KB는 Collection route 없이 KB `use`와 applicable materialized source gate를 통과할 수 있다. Collection child는 selected active Collection `route`와 독립적인 child KB `use`/source gate를 모두 통과해야 한다.
- Collection `read/manage/sync`와 Knowledge domain `catalog_manage`, `permission_delegate`, `lifecycle_manage`, `sync_manage`만 가진 actor는 runtime candidate를 얻지 못한다.
- Direct candidates는 configured order를 유지하고 남은 budget은 selected Collection configured order의 round-robin으로 채운다. Collection 내부 tie-break는 item rank, item created time, KB UUID다.
- Direct와 여러 Collection에 중복된 KB는 canonical KB UUID로 한 번만 반환하고 처음 허용된 provenance를 유지한다. Duplicate를 건너뛴 뒤 뒤쪽 unique KB로 budget을 계속 채운다.
- Candidate budget 19/20 boundary는 deterministic success이고 21 이상의 direct/Collection reference 또는 budget 20 초과 request는 configuration validation에서 silent truncation 없이 차단한다. Dynamic membership overflow는 fixed `candidate_budget_limited` safe warning을 반환한다.
- `KnowledgeCollectionItem`에는 lifecycle을 가정하지 않는다. Present row는 linked, unlink/missing은 후보 없음이며 Collection과 child KB lifecycle을 따로 검증한다.
- Active ready version 또는 documented completed-document unversioned legacy chunk fallback만 ready다. Archived/deleted/source_deleted/non-ready/pre-finalized 후보는 identity 없이 제외한다.
- Authenticated source-managed KB는 active/fresh/unexpired/matching materialized `SourceAuthorizationProvenance`가 필요하다. Missing/inactive/stale/unmapped/ambiguous/unverified/revoked/denied/unknown/expired/organization-requester-KB-source mismatch는 fail-closed다.
- MBA-232 adapter는 connector client, HTTP client, `check_access_batch`, single `check_access`, runtime source authorization cache를 0회 호출한다.
- Anonymous selected Collection child는 active public manual Collection의 active/ready manual KB만 허용한다. Direct manual KB도 하나 이상의 active public manual Collection membership이 필요하다. Source public exposure primitive가 없는 동안 source-managed Collection은 manual child만 포함해도 membership scan 전에 제외하고, source-managed KB는 public membership과 authenticated provenance가 있어도 모두 제외한다. Collection source identity field가 projection에서 누락되거나 malformed이면 anonymous path는 fail-closed다.
- PostgreSQL adapter는 fresh transaction의 첫 query 전에 `REPEATABLE READ, READ ONLY`를 적용한다. Path-scoped PostgreSQL CI의 two-transaction test에서 resolver 시작 뒤 membership/Collection route/KB use/organization membership/source provenance/Collection lifecycle/KB lifecycle 변경이 commit되어도 current invocation은 한 snapshot만 보고 다음 invocation이 변경을 본다.
- Source-policy/provenance expiry는 timezone-aware PostgreSQL transaction timestamp 하나로 전체 invocation을 평가한다. KB 순회 중 wall clock이 만료 경계를 지나도 같은 invocation에서 서로 다른 evaluation time을 사용하면 테스트 실패다.
- Snapshot/repository/authorization infrastructure exception은 fixed safe retryable whole-resolution failure다. 이미 평가한 candidate partial set, raw SQL/exception, identifier, source metadata, exact count를 반환하거나 retrieval/provider mock을 호출하면 테스트 실패다.
- Candidate 0개는 `safe_no_result`, budget 제한은 successful warning이며 downstream partial retrieval failure와 구분한다.
- Query count는 candidate/Collection 수에 비례하는 N+1이 아니고 selected 20 Collections/5,000 membership fixture에서도 scan/memory/result가 bounded하고 fair해야 한다. Membership SQL은 Collection별 LATERAL cap을 global window보다 먼저 적용하고 outer `LIMIT`만으로 boundedness를 주장하지 않는다.
- Shared pure policy는 SQLAlchemy/FastAPI/Celery/Gateway/Workflow Engine concrete package를 import하지 않고 Workflow Engine runtime retrieval production code는 `apps.gateway.*`를 import하지 않는다.

## MBA-233 Workflow Collection Routing Integration Tests

- Legacy direct-only graph, Collection-only graph와 mixed graph가 Shared/Gateway/Worker/
  Client validator에서 같은 pass/fail 결과를 사용한다. 각 list의 19/20은 성공하고
  21은 silent slicing 없이 실패한다. Malformed/non-canonical UUID, unknown item field,
  overlong/control display snapshot과 raw object echo를 거부한다.
- Route-safe Collection picker는 user-direct/active-Team/organization-manager effective
  `route` positive case와 read/manage/sync/domain-only, inactive membership, revoked,
  cross-organization, archived/deleted negative case를 검증한다. Response는 UUID와 optional
  approved safe label만 가지며 child/source/permission/hidden count를 포함하지 않는다.
  최근 unauthorized Collection 500개 뒤에 authorized Collection이 있는 fixture와 authorized
  Collection 501개 fixture로 permission scope가 limit보다 먼저 적용되고 authorized 결과가
  500개로 제한되는 순서를 검증한다.
- Draft/Agent Builder/optimizer/model-routing graph save는 direct KB effective `use`와
  source authorization, Collection `route`를 current editor로 다시 검증한다. 하나라도
  stale/forged/denied/cross-org이면 partial graph/success audit 없이 whole-write를
  rollback하고 safe generic error만 반환한다. Knowledge reference가 없는 root/nested legacy
  graph는 null organization/invalid legacy user identifier로 permission service를 만들지 않지만,
  malformed empty-list shape는 422 구조 오류로 유지한다. 과거 completed chunk가 남은
  `source_deleted` direct KB와 route grant/membership이 남은 `source_deleted` parent
  Collection은 picker, save, preflight와 runtime 모두 거부한다.
- Collection route는 있지만 child KB/source access가 전부 denied인 graph는 save할 수
  있고 runtime에서 zero candidate/no provider로 닫힌다. Save-time에 child membership이나
  source를 query하면 테스트 실패다.
- PostgreSQL coordinated revoke/save test는 revoke가 authorization read 전에 commit되면
  save가 실패함을 보이고, read 뒤 revoke 경합으로 configuration intent가 남더라도
  다음 MBA-232 invocation이 current permission으로 제외하며 save capability를 재사용하지
  않음을 검증한다.
- Deployment preview/create/activation/toggle과 nested workflow-node graph는 두 list를
  검증한다. Anonymous private Collection/direct KB와 source public exposure primitive가
  없는 source-managed content는 fixed blocker이고 hidden child ID/count를 반환하지 않는다.
  Direct/public-membership/Collection aggregate query 모두 `source_deleted` KB를 제외하는
  PostgreSQL predicate를 사용하고 direct KB에는 retrieval-visible completed chunk
  readiness를 적용하며 runtime resolver eligibility와 어긋나면 테스트 실패다.
  빠른 SQL compile test는 INNER JOIN 대상/조직 ON 조건/lifecycle/sync predicate를 검증하고,
  opt-in disposable PostgreSQL test는 active, source-deleted, archived, cross-organization,
  organization-mismatched membership이 실제 반환 집합과 candidate count에서 올바르게
  포함·제외되는지 migration 적용 스키마에서 검증한다. 같은 실제 DB 테스트에서 최근
  unauthorized 500개 뒤의 authorized Collection과 501개 authorized 결과 cap도 검증한다.
  Source-deleted parent Collection은 route permission이 남아 있어도 picker cap, save,
  preflight와 runtime candidate stream 어느 곳에도 포함되지 않아야 한다.
- 모든 production execution surface는 same resolver dependency를 주입한다. Direct-only,
  Collection-only와 mixed invocation은 resolver를 정확히 한 번 호출하며 ordered canonical
  candidate마다 retrieval을 최대 한 번 실행한다.
- Resolver policy zero-result와 insufficient evidence는 embedding/retrieval/provider를
  호출하지 않는다. Resolver infrastructure exception은 safe retryable workflow failure로
  Celery retry되고 `ragFailurePolicy=safe_no_result`로 낮아지지 않는다. Retry/redelivery는
  fresh snapshot을 열 수 있지만 exactly-once provider 호출을 주장하지 않는다.
- Agent Builder/optimizer/compare/copy/import/model routing/deployment snapshot은 unrelated
  edit에서 `knowledgeCollections`를 보존한다. Pre-execution sync는 direct KB만 처리하고
  Collection child를 열거하거나 connector를 호출하지 않는다.
- Public app/deployment graph는 두 reference list를 제거한다. API/SSE/error/log/trace/audit
  fixture는 Collection ID/name/provenance, hidden KB ID, raw graph/query/source/credential/
  provider payload가 없고 safe bucket/fixed code만 있음을 검증한다. Mixed successful
  retrieval에서는 explicit direct KB의 기존 KB/chunk/document lineage는 유지하지만
  Collection-derived evidence의 child KB/chunk/document ID와 per-KB rank는 result metadata, durable trace,
  audit 어디에도 나타나지 않는다. 최종 정렬·dedupe·top-k 이후의 `evidence_rank`는 direct와
  Collection-derived result/quality trace에 1부터 연속해서 나타나며 child KB별로 재시작하지
  않는다. Collection retrieval audit은 node target과 count bucket만
  포함한다. Collection-only/mixed trace는 authorized/selected KB exact count와 그 값에서
  유도되는 actual fan-out concurrency를 저장하지 않고 count bucket만 남긴다.
  Query-vector/fan-out INFO log도 KB/model/vector/failure exact count 대신 bucket만 기록한다.
  Anonymous/system actor와 invalid organization audit 경계도 같은 redaction을 쓴다.
- Worker-first canary는 구 task drain 뒤 Gateway write와 Client를 순서대로 노출하고,
  rollback은 Client/Gateway write 중지와 drain 뒤 Worker를 되돌린다. 구 Worker가
  Collection graph를 소비할 수 있는 상태에서는 rollout/rollback acceptance가 실패다.

## MBA-238 Internal Chatbot User Permission Integration Tests

- 실제 PostgreSQL production candidate adapter에서 같은 organization의 Dev Team 사용자,
  Planning Team 사용자, user-direct `operator` 사용자와 Knowledge 권한이 없는 사용자를
  한 fixture로 비교한다. 각 사용자는 자신의 team-bound 또는 user-direct KB `use`와
  선택한 Collection `route`를 모두 충족한 후보만 얻어야 한다.
- 다른 organization의 사용자와 동명 리소스는 target organization 후보에 포함되지 않는다.
  이 격리는 in-memory query fake가 아니라 실제 organization, membership, permission
  predicate로 검증한다.
- Runtime resolver가 반환하지 않은 KB는 embedding 또는 vector retrieval 입력에 전달되지
  않는다. 최종 후보가 0개이면 embedding, retrieval, LLM provider를 모두 건너뛰고 표준
  no-evidence 응답을 반환한다.
- Collection 유래 evidence와 권한 필터 관측값에는 child KB/Collection identity, raw content,
  정확한 denied count가 없어야 한다. 허용/거부 synthetic marker는 응답, citation,
  trace summary와 audit projection 전체에서 검사한다.
- 기존 MBA-232/MBA-233/MBA-241 테스트가 snapshot, bounded scan, resolver failure,
  citation redaction을 이미 검증하면 해당 테스트를 acceptance evidence로 재사용하고 같은
  단위 테스트를 MBA-238 이름으로 복제하지 않는다.

## Knowledge Base API Tests

- KB create는 blank name을 DB insert 전에 거부하고 safe validation reason code만 반환한다.
- KB create는 255자를 초과하는 name을 DB insert 전에 거부하고 safe validation reason code만 반환한다.
- KB create는 empty, secret-like, token-like, allowlist 밖 `embedding_model`을 DB insert 전에 거부한다.
- KB create validation failure는 partial KB row를 만들지 않고 raw request value, stack trace, SQL, credential을 response, audit, log에 노출하지 않는다.
- KB create는 trimming 후 저장되는 name과 `embedding_model`이 기존 API response shape를 깨뜨리지 않는다.
- 같은 organization 안에서 동일한 KB `name` create는 이름만으로 conflict 처리하지 않는다. KB name은 display label이며 identity가 아니므로 `knowledge_base_id`, source identity, sync/lifecycle state, safe metadata로 구분한다.
- 동일 문서의 version은 여러 개를 동시에 retrieval-visible 후보로 만들지 않는다. 내부 문서는 active/head pointer가 가리키는 ready version만 검색 노출하고, 외부 source-managed 문서는 정상 sync/finalization 이후 최신 active ready version만 검색 노출한다. Sync 실패나 stale 상태에서는 기존 active ready version만 warning과 함께 유지할 수 있으며, 이전/superseded/pre-finalized version은 selectable-ready 또는 evidence 후보가 아니다.
- Source-managed KB의 동일 source item 중복은 KB `name`이 아니라 protected source identity/source sync lineage invariant로 검증한다.
- KB detail과 direct document detail은 같은 document metadata projector를 사용한다. Safe progress/state/timestamp/processing option과 finite non-negative cost estimate만 반환하고, `api_config` 및 encrypted config field, `connection_id`, source/connector identifier, DB connection metadata, unknown nested field는 KB `read` 또는 더 강한 resource state에서도 반환하지 않는다.
- Document metadata projector는 non-mapping input, 잘못된 type, out-of-range progress, invalid timestamp, non-finite/negative cost와 oversized/unknown string을 생략하며 projection 실패 때문에 response 전체가 500이 되거나 내부 값을 그대로 fallback하지 않는다.
- KB `write` actor의 document settings 화면은 전용 edit-config API에서 기존 segment/chunk/selection과 DB selection/opaque connection reference를 복원한다. Read-only actor는 endpoint에서 hidden/denied되고, encrypted API URL/header/body와 credential/connection detail은 write actor에게도 반환되지 않는다. Edit config가 malformed, 개별/aggregate/serialized-size budget 초과 또는 load failure면 Client는 DB/API preview/process를 호출하지 않고 기존 저장 설정을 보존한다. 응답은 `Cache-Control: no-store`다.
- Document settings route 전환은 permission/readiness와 모든 source-specific state를 즉시 reset한다. Cleanup/generation 이후 늦게 도착한 이전 KB/document response는 현재 설정이나 action gate를 변경하지 못하며, 새 fetch failure도 이전 문서의 설정으로 action을 다시 열지 않는다.
- KB detail/direct document의 `error_message`와 progress SSE의 `message`/`error`는 arbitrary legacy exception 또는 processing-step 원문을 포함하지 않는다. Fixed safe message만 반환하고 raw input marker가 JSON/SSE/toast/log capture에 나타나지 않아야 하며 progress는 0..100 범위 밖 값을 전달하지 않는다. Redis progress는 `indexing`/`processing`에서만 사용하고 pending/approval 상태는 stale 100을 무시한다. SSE는 no-cache/no-store와 buffering disable header를 반환한다.
- Document settings의 PDF 원본 preview는 `X-Organization-Id`가 명시된 API client 요청으로 content를 가져오고, ephemeral Blob URL을 browser-native `object[type="application/pdf"]`와 `noopener noreferrer` 새 탭 fallback에 사용해야 한다. Native `object`/anchor가 organization header 없는 content API URL을 직접 요청하면 테스트 실패다. Local/external PDF content response는 `X-Content-Type-Options: nosniff`를 반환한다. PDF viewer를 위해 iframe sandbox에 `allow-scripts`를 추가하면 테스트 실패다.
- PDF가 아닌 FILE 원본 preview는 같은 authorized Blob을 `allow-same-origin`만 허용한 scriptless sandbox iframe에서 렌더링한다. Preview iframe에 `allow-downloads` 또는 `allow-scripts`가 있으면 테스트 실패다. Missing KB/document id 또는 filename에서는 content를 요청하지 않고, content fetch failure는 raw 오류를 표시하지 않는다. 문서 scope 전환/unmount는 요청을 abort하고 생성된 Blob URL을 revoke하며, 늦게 도착한 이전 scope content를 렌더링하지 않는다. 현재 document filename에 따라 PDF와 non-PDF viewer를 다시 선택한다.
- 처음부터 `completed`인 document settings route는 preview를 유지하고 3초 후 KB 상세로 이동하지 않는다. 같은 화면에서 `indexing` 또는 `processing` 상태를 실제로 관찰한 뒤 `completed`가 된 경우에만 기존 완료 후 이동 동작을 수행한다.

## Connector And Egress Tests

- Connector preview/test/fetch는 승인된 outbound guard factory 밖의 raw socket, ad hoc HTTP client, custom dialer를 사용할 수 없다.
- `/api/v1/rag/proxy/preview`, URL upload/preview(`s3FileUrl`, `apiUrl`), crawler, sitemap, future web/API connector, DB/SSH/SaaS/object-storage probe는 모두 central guard를 통과한다.
- `/api/v1/rag/upload` 신규 KB 생성은 `X-Organization-Id` active organization을 사용하며 primary organization fallback을 사용하지 않는다. 기존 KB 업로드는 KB organization과 active organization이 다르면 hidden/not-found로 닫는다.
- DNS rebinding, private IP redirect, link-local/metadata IP, private network target, unsupported scheme, HTTPS downgrade, `verify=false`, oversized response, timeout을 거부한다.
- IPv4 obfuscation, IDNA/punycode/CNAME trick, open redirect chain, redirect 시 sensitive header forwarding, compression/zip bomb payload, unapproved proxy/CA configuration, rate-limit bypass를 거부하거나 safe cap으로 제한한다.
- File/page artifact content는 egress guard 이후에도 untrusted로 처리한다. 지원 file type/content type allowlist 밖이면 document version, chunk, embedding, prompt-visible artifact가 생성되지 않는다.
- Macro-enabled Office document, embedded object/script, executable payload, active HTML/script, external reference를 포함한 artifact는 별도 opt-in policy 없이는 fail-closed 또는 remediation 상태가 된다.
- Archive ingestion은 nested depth, expanded size, contained file count, nested archive count cap을 적용하고, cap 초과 또는 archive 내부 executable/script/macro-enabled file을 indexing-visible artifact로 만들지 않는다.
- Malware/content scan result가 `unknown`, timeout, error이면 high-risk binary/Office/archive는 ready/indexing-visible 상태로 진행하지 않는다.
- Parser/extractor는 sandbox 또는 least-privilege worker에서 실행되고, parser가 document 내부 script/macro/external URL을 실행하거나 따라가면 테스트 실패다.
- Content safety failure, unsupported type, parser exception은 raw file bytes, active content marker, parser raw error를 audit, trace, log, retry/dead-letter payload, user-facing response에 남기지 않고 safe reason code와 remediation state만 남긴다.
- DB adapter는 arbitrary SQL을 거부하고 승인된 read-only probe/schema introspection만 cap 안에서 허용한다.
- SSH adapter는 arbitrary command execution과 승인되지 않은 tunnel/proxy behavior를 거부한다.
- Object storage adapter는 policy가 bounded listing을 명시적으로 허용하지 않는 한 과도한 bucket/listing operation을 거부한다.
- Egress/adapter error는 sanitized reason code를 반환하고 credential이나 raw connection string을 포함하지 않는다.
- Slack connector baseline은 channel을 collection으로, thread/huddle recap/canvas/bot-generated meeting summary/pinned-message group을 document-level KB로 매핑한다.
- Slack/meeting artifact-level ACL이 있으면 artifact ACL과 containing channel/workspace ACL의 교집합을 통과한 requester만 retrieval 후보를 얻는다.
- Slack/meeting artifact ACL을 확인할 수 없으면 fail-closed 또는 remediation 상태가 되고 channel membership만으로 공개되지 않는다.
- Slack/meeting DM, raw audio, raw transcript ingestion은 별도 opt-in policy 없이 실행되지 않는다.
- MCP/API source connector는 allowlist 밖 operation을 호출하지 않는다. 임의 MCP tool selection 또는 LLM-directed source raw data fetch가 가능하면 테스트 실패다.
- MCP/API source connector response size cap 초과, timeout, raw tool exception은 raw body/error 없이 safe reason code로 닫힌다.
- Runtime authorization primitive(`check_access_batch` 또는 bounded single `check_access`)가 없는 source는 private source-managed KB retrieval을 fail-closed 처리한다.
- Raw payload normalization 전 connector failure에서도 connector log, retry/dead-letter payload, audit, trace에 변환 전 raw payload가 남지 않는다.

## Sync And Ingestion Tests

- Sync lease는 두 worker가 같은 source item을 동시에 finalize하지 못하게 한다.
- 같은 document-level KB에 대한 concurrent ingestion은 하나의 finalization만 성공한다.
- A document moved to queued `indexing`/`processing` state must become `failed`
  with safe progress metadata only when no active fencing token and no
  processing progress/chunk/version artifact appears before the processing-start
  timeout.
- A document with an active fencing token must also become `failed` after the
  active processing stall timeout when no processing progress/chunk/version
  artifact exists, so crashed workers cannot leave the UI in processing forever.
- Redis lock/progress storage unavailable must not leave a document in infinite
  `indexing`/`processing`. Processing either continues through the local fallback
  lock path or closes with a safe failed state.
- Active processing with a recent DB progress heartbeat must remain in progress,
  but an old active fencing token with only a pre-finalized
  `DocumentVersion(status=indexing)` and no chunk/ready version must become
  `failed` after the active stall timeout.
- A document incorrectly marked failed with the processing-start timeout message
  must recover to completed when retrieval-visible chunks or a ready document
  version already exists.
- `content_hash`, chunking fingerprint, embedding model은 chunk/index artifact finalization 성공 전에는 새 processed state로 commit되지 않는다.
- Finalization 실패 뒤 다음 retry는 stale `content_hash` 때문에 skip하지 않고 다시 처리한다.
- Content cursor는 active version finalization 이후에만 전진하고, ACL/permission watermark는 source ACL state와 candidate cache invalidation commit 이후에만 전진한다.
- Content cursor 전진 실패와 ACL watermark 전진 실패는 서로를 암묵적으로 commit하지 않는다.
- Source content가 바뀌지 않고 ACL만 바뀐 경우에도 Source Authorization Provenance와 permission freshness를 갱신한다.
- Source deletion은 KB sync state를 `source_deleted`로 만들고 retrieval에서 제외하지만 audit/citation history를 기본 삭제하지 않는다.
- Connector access loss는 sync/permission state를 stale 또는 unverified로 표시하고 `source_deleted`로 처리하지 않는다.
- Indexing failure는 기존 active version을 retrieval 가능 상태로 유지한다.
- Successful indexing은 하나의 finalization contract 안에서 active version을 교체하고 이전 version을 superseded로 표시한다.
- Finalization 중 worker crash는 outbox/recovery scanner로 복구하고 pre-finalized artifact를 노출하지 않는다.
- Active pointer swap, previous version `superseded` 표시, processed state commit, cleanup/finalization outbox insert는 같은 DB transaction 안에서 일어난다.
- Pointer swap 이후 outbox insert 전에 crash가 발생하는 window를 허용하지 않는다.
- External index success 이후 DB finalize failure가 발생하면 이전 active version을 유지하고 orphan cleanup을 queue에 넣는다.
- DB finalize success 이후 object storage/vector index cleanup failure가 발생하면 새 active version은 유지하고 cleanup을 retry한다.
- DB source sync 또는 shared vector save path가 같은 KB/document chunks를 동시에 교체하려 할 때 advisory lock 또는 versioned chunk set이 lost update를 막는다.
- Target cleanup outbox/reconciler cutover는 Document/KB delete가 DB commit 전에 object storage 또는 raw artifact를 먼저 삭제하지 않고, physical cleanup을 outbox/reconciler가 idempotent하게 수행함을 검증한다.
- Current hard-delete baseline은 KB delete가 Knowledge lifecycle service boundary를 통과하고, organization field가 잘못된 legacy row를 포함해 해당 KB를 참조하는 direct KB permission row cleanup이 hard delete와 같은 transaction에서 먼저 일어나며, storage adapter 생성 또는 object delete 실패가 API 실패나 raw path/raw exception log 노출로 이어지지 않음을 검증한다. Storage adapter는 provider 세부정보가 없는 typed delete error를 호출자에게 전달하고, lifecycle service는 한 object cleanup 실패 뒤에도 나머지 object cleanup을 계속한다. Permission cleanup, ORM delete 또는 DB commit이 실패하면 session rollback 후 예외를 전파한다. 이 baseline은 MBA-184의 durable audit/outbox와 target cleanup outbox/reconciler cutover를 대체하지 않는다.
- S3 delete reference는 configured bucket의 `s3://`, virtual-host, 승인된 path-style URL과 canonical `uploads/` key만 허용한다. URL-encoded 공백/한글 key는 한 번 decode하고, bucket/host mismatch, HTTP, query/fragment, 빈 key, control/dot/backslash segment, `uploads/` 밖 key는 provider 호출 전에 safe typed error로 거부한다.
- Local delete reference는 configured upload root 내부 resolved path만 허용한다. Root 밖 절대/상대 경로와 symlink escape는 파일을 삭제하지 않고 safe typed error로 닫는다.
- Local storage는 컨테이너 기본 경로(`/app/uploads`)를 생성한 뒤 임시 파일 write/flush/delete probe까지 통과한 경우에만 사용한다. 기본 경로가 permission/read-only 오류로 생성되지 않거나 기존 directory가 실제로 쓰기 불가능하면 프로젝트 `uploads/` 경로를 같은 방식으로 검증해 fallback하며, 선택한 default root는 프로세스 안에서 lock으로 한 번만 고정한다. Probe artifact는 남지 않아야 하고 동시 service 생성도 다른 root를 선택하면 안 된다. 명시한 upload root는 같은 write probe 실패를 전파하고 fallback하지 않는다.
- Backend upload와 presigned upload가 생성한 S3 key 및 Local path는 같은 canonical builder/delete validator round-trip을 통과해야 한다. Filename 또는 user segment에 slash/backslash, `.`/`..`, control character, 과도한 길이가 있으면 object 생성/presign 전에 safe typed error로 거부하며, delete validator를 완화해 legacy unsafe key를 허용하지 않는다.

## Client/UI Tests

- Source upload 성공 후 create modal은 KB 상세 source list로 돌아가며, 등록된 `pending` source가 목록의 처리 CTA를 통해 document settings 화면으로 이동할 수 있어야 한다.
- KB 상세 source 목록은 `pending` document에 `처리 시작` action과 "처리 시작 전에는 RAG 검색에 사용되지 않는다"는 안내를 표시한다.
- KB 상세 source 목록은 `failed` document에 `재처리` action을 표시하고, `completed` document에는 처리 시작 CTA를 표시하지 않는다.
- Pending/failed processing CTA는 document settings 화면으로 이동하며 raw file path, source title, hidden KB id를 새로 노출하지 않는다.
- 지식 테스트 모달의 모델 목록, 일반 검색과 AI 답변 요청은 현재 활성 조직의 `X-Organization-Id` 헤더를 전송한다.
- Organization 또는 KB가 바뀌거나 modal scope가 닫히는 동안 이전 검색 요청이 완료되어도 해당 결과는 새 scope에 표시되지 않는다. 오류 UI는 raw backend/provider/source detail을 표시하지 않는다.
- AI 답변은 현재 organization에서 조회된 유효한 chat model이 선택된 경우에만 요청하며, 모델이 없거나 목록 응답 shape가 잘못되면 generation model이 빈 요청을 전송하지 않는다.
- 초기부터 `completed`인 document settings 화면은 자동 이동하지 않는다. 같은 document scope에서 `indexing|processing`을 관찰한 뒤 `completed`에 도달한 경우에만 KB 상세 이동을 한 번 예약한다. 이 active 상태는 현재 화면의 성공한 process/approval 요청 또는 처음부터 처리 중인 문서를 관찰하면서 시작될 수 있다.
- 비용 승인 취소, process/approval 요청 실패, `failed` 완료는 이동 intent를 만들지 않는다. Organization 전환 직후 이전 render의 handler는 process/analyze/preview/approval 요청을 시작하지 않으며, 이전 active organization/KB/document의 늦은 initial fetch, process/approval, SSE 또는 polling 결과는 현재 화면의 status/progress/edit gate를 변경하거나 이동을 예약하지 않는다.

## Retrieval And Agent Tests

- `internal_chatbot` 실행의 current user는 Runtime permission helper에 그대로 전달되고, 해당 user의 KB permission 또는 source ACL이 거부한 후보는 retrieval 전에 제외된다.
- 공개 `chatbot`은 execution subject나 owner fallback 없이 anonymous public-only로 검색하며, `internal_chatbot`의 public surface 실행은 safe 404로 거부된다.
- Auto mode는 collection route helper와 KB permission/source ACL helper 결과로 candidate set을 만든다.
- Auto mode의 collection/KB cap은 authorization 전 임의 row cap이 아니라 route/use/source ACL helper를 통과한 authorized subset에 적용한다.
- Builder/recommendation Auto mode에서 명시 `collection_ids`가 없으면 organization 전체 collection이 아니라 actor가 route할 수 있는 collection subset에서 시작한다. MBA-232 Workflow runtime은 missing/empty Collection scope를 0개로 유지하며 이 fallback을 사용하지 않는다.
- Router는 authorized safe candidate와 safe metadata만 받는다.
- Router는 raw source ACL fact, hidden KB id, raw source title/path/url, exact hidden count, raw content를 받지 않는다.
- Knowledge RAG Recommendation Adapter는 `KnowledgeCandidateResolver`가 반환한 safe KB candidate만 ranking하고, permission/source ACL row를 직접 조회하거나 해석하지 않는다.
- Recommendation response item은 초기 구현에서 `candidate_type=knowledge_base`만 사용한다. Collection label과 linked KB count는 `source_collection_summary` safe metadata로만 제공한다.
- `materialized_knowledge_bases`는 LLM node `knowledgeBases`로 변환 가능한 safe KB ref만 포함하고, `MAX_RAG_RETRIEVAL_KBS=20` cap을 넘지 않는다.
- Safe label이 없는 KB recommendation은 raw KB name을 fallback으로 사용하지 않고 `null` 또는 generic label만 사용한다.
- Recommendation request는 raw `workflow_intent`나 raw natural language 전체가 아니라 `StructuredRequest` 기반 `intent_summary`, `node_purpose_summary`, `knowledge_requirement`, `pending_resolution_ref`, `safe_workflow_context_summary`를 사용해야 한다. 이 safe structured input도 durable raw storage 금지, 길이 cap, control character normalization을 통과해야 한다.
- Workflow Builder RAG recommendation은 Agent Builder client가 직접 호출하는 public client endpoint가 아니라, Agent Builder backend가 server-resolved context를 확정한 뒤 호출하는 Knowledge domain boundary로 취급해야 한다.
- Public HTTP recommendation endpoint는 `mode=explicit_kb`와 raw KB id 기반 scope opening을 safe validation error로 거부한다. `mode=auto`에 raw KB/collection id가 섞여 있으면 권한 판단에 사용하지 않고 무시한다.
- Trusted backend/internal service boundary는 safe handle, authorized picker, server-resolved context를 통과한 경우에만 explicit KB 후보를 recommendation scope로 사용할 수 있다.
- Recommendation response는 `status`, `resolution_id`, `requirement_id`, `recommendations`, `clarification_options`, `user_safe_warning`, `fallback_reason` top-level envelope를 사용해야 하며 recommendation item list만 단독으로 반환하지 않아야 한다.
- Recommendation ranking은 `KnowledgeCandidateResolver`가 만든 server-issued reference 또는 같은 backend 내부 service call의 safe candidate set만 사용해야 하며, raw KB id나 raw source metadata로 권한 후보를 직접 만들지 않아야 한다. HTTP 또는 serialized boundary에서는 full candidate set 객체가 아니라 reference만 사용해야 한다.
- Recommendation ranking의 `score`는 DB 저장값이 아니라 요청 시점 계산값이어야 한다. Agent Builder가 구조화한 `safe_query_topics`가 `kb_relevance` 1차 입력이어야 하며, `웹훅`, `워크플로우`, `챗봇`, `KB` 같은 action/UI terms는 relevance를 올리지 않아야 한다. Relevance matching은 `safe_label`, `kb_safe_description`, `kb_safe_topics`만 사용하고 `collection_safe_label`, `collection_safe_topics`, Collection name/description, collection id/count를 사용하지 않아야 한다.
- Manual KB는 `name`/`description`을 sanitizer, length cap, secret/url/path 제거를 통과한 뒤 safe label/topics comparison text로 자동 생성할 수 있어야 한다. Source-managed KB는 display-policy-approved source safe metadata가 없으면 raw source-derived name/title/path/url을 safe label/topics 또는 keyword score 입력으로 사용하지 않아야 한다.
- KB detail UI는 `safe_label`과 `kb_safe_topics` 자동 생성 버튼을 각각 제공해야 한다. 저장 시 전용 `PATCH /api/v1/knowledge/{kb_id}/safe-metadata`는 KB `manage`를 확인하고 allowlisted 필드만 저장하며 raw source URL/path/title, secret-like value를 제거해야 한다. Creator 여부와 무관하게 effective resource `manager`는 `write`와 `manage`를 모두 포함하므로 일반 설정과 safe metadata를 편집할 수 있고, `builder`는 일반 설정만 편집할 수 있어야 한다. KB가 visible한 operator/viewer의 safe metadata mutation은 `403 permission.denied`, 완전히 invisible하거나 cross-organization인 대상은 `404 resource.hidden`이어야 한다. Detail capability에 따라 일반 설정과 safe metadata UI가 분리되어야 하며, audit의 `safe_metadata` before/after 값은 마스킹되어야 한다. 저장된 manual KB safe metadata는 Agent Builder recommendation에서 자동 생성값보다 우선해야 한다.
- Recommendation tokenizer는 한국어/영어/숫자 혼합 builder intent에서 `사내문서1`, `KB`, `웹훅`, `사내`, `문서`, `챗봇` 같은 safe term을 분리할 수 있어야 한다.
- Recommendation response item은 `score`, `confidence`, `reason_category`, `threshold_result`를 포함해야 하며 raw retrieval/provider score나 hidden resource identity를 노출하지 않아야 한다.
- Recommendation threshold 값은 구현 설정값으로 관리되고, 테스트 fixture에서는 고정되어 `high_confidence`, `close_score`, `below_threshold` 분기가 재현 가능해야 한다.
- Recommendation candidate set은 `source_deleted` KB, active ready document version과 legacy unversioned retrieval-visible chunk가 모두 없는 KB를 selectable ready 후보에서 제외해야 한다.
- 권한 확인된 KB에 document row나 pre-finalized chunk artifact가 있지만 active ready version 또는 legacy retrieval-visible chunk가 없으면, Recommendation/Builder picker는 이를 권한 없음이나 숨겨진 KB처럼 조용히 숨기지 않고 `candidate_not_ready` 또는 `indexing_in_progress` 수준의 safe warning/disabled option으로 표시해야 한다.
- KB detail response의 `documents[].chunk_count`와 LLM node Knowledge Base picker의 selectable-ready 판단은 같은 retrieval-visible 기준을 사용해야 한다. Active ready document version이 있으면 해당 version chunk만 세고, active version pointer가 없는 legacy KB는 legacy unversioned chunk만 fallback으로 센다.
- Completed가 아닌 document, `ready`가 아닌 active/pending version, superseded/failed/pre-finalized version chunk, active version과 연결되지 않은 stale chunk는 `documents[].chunk_count`와 selectable-ready 판단에 포함하지 않는다.
- Builder/recommendation Auto mode에서 route-allowed collection link 후보가 없고 client가 collection scope를 명시하지 않은 경우, Gateway resolver는 직접 권한 확인된 retrieval-visible KB를 fallback 후보로 반환할 수 있다. 명시적으로 빈 collection scope를 보낸 경우에는 direct fallback을 적용하지 않고 후보 없음으로 유지해야 한다. 이 동작을 MBA-232 Workflow runtime resolver에 재사용하면 테스트 실패다.
- 기존 active ready version은 유지되지만 sync state가 `stale` 또는 `failed`인 KB는 후보로 남을 수 있으며, safe warning과 score penalty 또는 낮은 confidence가 함께 반환되어야 한다.
- Adapter unavailable이고 권한 확인된 safe 후보 선택지가 있으면 `status=clarification_required`, `fallback_reason=adapter_unavailable`, `clarification_options`를 반환해야 한다. Safe 후보 선택지도 없으면 `status=unavailable`과 safe fallback reason으로 닫아야 한다.
- Recommendation provenance는 `recommendation_strategy`, `safe_reason_code`, `used_signals`, safe matched terms, bucketed counts 같은 allowlist만 포함하고 raw source title/path/url, hidden id/name, exact denied count를 포함하지 않는다.
- `high_risk_domain` hint는 `strict_citation` 같은 RAG option 추천에만 영향을 주고 권한, source ACL, policy block 결정을 대체하지 않는다.
- No recommendation result는 사용자 확인 필요 상태를 기본값으로 만들며, Builder 정책 gate 없이 자동으로 RAG 없는 LLM node를 생성하지 않는다.
- MBA-145 Agent Builder MVP는 Knowledge Skill body/checklist를 prompt context로 직접 로드하지 않는다. 후속 Skill 사용 흐름에서도 Workflow Builder는 safe skill metadata만 받고 raw skill body, hidden source reference, restricted document list를 받지 않는다.
- Skill Context Loader는 후속 target 흐름에서만 선택된 skill의 redaction-safe checklist/body를 빌더 단계에 필요한 시점에 로드하고, 실제 문서 내용은 workflow 테스트 또는 실행 시점 authorized retrieval로 가져온다.
- Skill source-of-truth tier는 LLM node의 RAG 옵션 구성과 routing/procedure hint로만 사용되고, citation/evidence는 KB/document version/chunk/decision record를 가리킨다.
- Workflow 실행 시점 RAG는 명시적으로 resolve된 execution subject가 있으면 해당 subject 기준으로 KB permission/source ACL을 평가한다. Subject가 없으면 workflow owner fallback 없이 anonymous public-only로 낮추고, 모호한 subject는 private retrieval fail-closed로 처리한다.
- `subject_type="organization"` source-policy KB use grant는 active organization member에게만 적용되고 removed/suspended/invited/non-member user에게는 적용되지 않는다.
- Runtime source authorization은 `check_access_batch`를 우선 사용하고, batch 미지원 source의 single `check_access` fallback은 bounded concurrency, per-call timeout, aggregate timeout을 강제한다.
- `check_access_batch`가 일부 `denied`, `unknown`, timeout을 반환하면 해당 evidence만 fail-closed 제외되고 raw source error나 denied item title/path는 응답/trace/log에 남지 않는다.
- 위 두 live runtime source authorization 항목은 후속 target flow다. MBA-232 candidate resolver test는 materialized provenance만 소비하고 live batch/single/cache 호출이 전혀 없음을 별도로 고정한다.
- 운영 `general RAG`도 KB permission/source ACL/final evidence gate를 통과한다. Test fixture에서 권한 없는 문서는 `general`, `permission_scoped`, `task_aware` 모든 mode의 prompt/citation/trace에 들어가지 않는다.
- `general RAG`는 authorized resource 안의 broad retrieval로 동작하고, `task_aware` 또는 `permission_scoped` mode는 같은 authorized resource 안에서 더 작은 evidence set을 선택한다.
- Query rewrite가 켜져도 user query와 safe skill/template만 입력으로 사용하며, 권한 없는 KB/문서를 candidate로 만들지 못한다.
- Query rewrite 결과 원문은 durable audit/trace/usage metadata, cache key, log에 저장되지 않고 `query_rewrite_applied`, `query_rewrite_strategy` 같은 safe summary만 남는다.
- Source-of-Truth Tier는 authorized evidence 안에서 ranking/tie-break에만 영향을 주며 KB permission/source ACL/final evidence gate를 대체하지 않는다.
- 여러 collection에 같은 KB가 포함되면 `knowledge_base_id` 기준으로 dedupe하고 safe attribution rule을 유지한다.
- Retrieval은 active ready document version만 검색한다.
- Chunk/document metadata가 dict/object가 아닌 문자열, list, corrupted JSON-like value로 저장되어 있어도 retrieval metadata summary 생성은 crash하지 않고 빈 safe metadata로 낮춰 처리한다.
- Permission/source ACL/final evidence failure는 fail-closed evidence exclusion이며 partial operational success로 처리하지 않는다.
- 일부 authorized KB의 operational failure는 `partial_result=true`, bucketed reason summary, failed-candidate bucket, retryability를 포함한 safe partial result를 반환할 수 있다.
- 모든 KB retrieval failure는 승인된 API matrix에 따라 safe no-result 또는 terminal operational error 중 하나로 반환한다.
- Authorized source에서 evidence가 없는 경우는 성공한 empty evidence response이며 hidden resource를 암시하지 않는다.
- Evidence sufficiency policy가 `minimum_evidence` 또는 `strict_citation`일 때 evidence가 없거나 score/citation coverage가 부족하면 `evidence_sufficient=false`와 safe `insufficiency_reason`을 반환하고 추측 답변을 생성하지 않는다.
- `insufficiency_reason`은 권한 없는 문서명, hidden KB id, exact denied count를 포함하지 않는다.
- Retrieved context, memory summary, upstream node output, external connector content에 `ignore previous instructions`, `system prompt`, 역할 위장 같은 prompt injection성 지시문이 포함되어도 LLM system/developer policy와 사용자 명시 요청보다 우선하지 않는다.
- Standalone Agent answer와 Workflow LLM node RAG path는 retrieved context를 system prompt 본문에 직접 합치지 않고 untrusted evidence delimiter로 감싸며, 의심 지시문 라인을 redaction하거나 무해화한다.
- Workflow LLM node의 system/assistant prompt template에 upstream referenced variable이 포함되면 원문 value는 privileged role에 직접 렌더링되지 않고 untrusted evidence block으로 분리된다.
- Prompt injection guard 테스트 fixture는 악성 chunk 원문이 provider messages의 system role, audit metadata, trace metadata, answer summary에 저장되지 않는지 확인한다.
- Explicit KB id not found, outside org, archived/deleted, requester source authorization denied, source ACL stale/unmapped/ambiguous/unverified/revoked, permission-unverified는 matrix가 요구하는 동일한 safe resource-hidden shape를 따른다.
- Hidden/resource-hidden path의 external JSON/SSE `reason_code`는 `resource.hidden`으로 일반화되며 `source_authorization.denied` 또는 `source_acl.stale/unmapped/ambiguous/unverified/revoked` 세부 reason을 반환하지 않는다.
- PII/final evidence policy block은 answer delta나 citation content preview가 emit되기 전에 발생한다.
- Workflow LLM node RAG path도 `classification=pii` chunk를 외부 LLM context에 넣기 전에 차단하고, safe no-result 또는 fail-node 정책에 따라 닫는다.
- Live-linked mode에서 requester-scoped source-side search API가 없는 source는 일반 RAG 후보가 아니다.
- Live-linked broad service-account source-side search가 title, snippet, count, score를 authorization 전에 반환하면 기본 구현은 실패해야 한다. Opaque source ref만 후보로 전달하고 runtime source authorization 이후에 metadata를 노출하는 flow만 허용한다.
- Live-linked source-side search가 unauthorized item을 반환해도 prompt, citation, trace, response에는 해당 item의 title/snippet/count/score가 나타나지 않는다.
- 현재 standalone single-KB Agent answer lifecycle과 same-scope blocked 처리 테스트는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)을 기준으로 유지하고, ADR-0017/implementation baseline matrix 테스트는 target cutover/source-managed/auto/multi-KB mode에 추가한다.

## Audit, Trace, And Privacy Tests

- Successful retrieval audit은 redaction-safe KB/document version/chunk id, score summary, correlation id, policy-safe metadata만 저장한다.
- Hidden/denied/resource-hidden path audit/trace metadata에는 raw title/path/url, exact hidden count, denied KB id, raw source ACL, raw exception을 포함하지 않는다.
- KB/document response projection test fixture와 failure log는 credential-like value나 raw payload를 출력하지 않는다. Encrypted/source config key가 응답, error, audit, trace, captured log에 나타나지 않는지만 구조적으로 검증한다.
- Partial result audit/trace는 safe partial marker, bucketed reason/retryability summary, request/correlation id만 저장한다.
- RAG strategy summary는 `retrieval_strategy`, `rag_mode`, selected collection/KB count, retrieved chunk count, citation count, context token estimate, retrieval latency, permission filter flag, policy result, partial result, safe exclusion summary, query rewrite 적용 여부, evidence sufficiency 결과만 포함한다.
- Skill usage summary는 workflow draft, LLM node의 RAG 옵션, workflow test run, RAG strategy comparison에서 skill id, skill version, freshness state, eval status, safe source tier, safe provenance refs만 포함한다.
- Skill provenance summary는 raw skill body, raw source title/path/url, hidden source refs, exact hidden/denied count를 포함하지 않는다.
- Trace side panel은 raw chunk content, raw source title/path/url, hidden document name/id, exact denied count, raw prompt/completion, provider raw response를 표시하지 않는다.
- Source ACL mapping audit은 safe principal reference만 저장한다.
- Raw content access는 별도 raw/compliance permission을 요구하고 audit을 남긴다.
- Raw content access는 active organization, KB visibility, source-managed KB의 fresh source ACL, retention/legal-hold/purge state를 확인하고, content 반환 전에 access audit을 기록한다.
- Raw content는 Agent answer, SSE stream, retrieval context, embedding input, prompt construction, citation summary, audit metadata, trace metadata, usage metadata, router input, log에 나타나지 않는다.
- Deleted/archived KB metadata에 대한 admin default view는 redacted 상태이며 raw content access를 암시하지 않는다.
- `rag_answer_runs`는 standalone answer anchor로 유지하고 trace/usage table에는 RAG-specific FK column을 추가하지 않는다.
- RAG answer lifecycle 상태 변경, `rag.answer.*` audit, LLM usage row 기록 중 일부가 실패하면 reconcile 또는 transactional outbox 기준에 따라 누락을 감지할 수 있다.
- Vector/keyword retrieval은 `organization_id + knowledge_base_id + active_document_version_id` 또는 동등한 tenant-scoped version namespace 없이 실행되지 않는다.
- RAG answer retention purge는 `completed`, `failed`, `cancelled`, `blocked` 같은 terminal status만 대상으로 삼고 `requested`/`running` row를 삭제하지 않는다.
- 동시 retention purge worker는 같은 answer run을 중복 삭제하거나 중복 purge audit count로 기록하지 않는다.
- Retention purge dry-run은 실제 `purged_count`가 아니라 `would_purge_count` 같은 safe preview 의미로만 표시한다.

## API And UI Tests

- Manual Collection CRUD API는 organization manager 또는 domain `catalog_manage`만 private Collection을 생성할 수 있게 하고, delegated create가 public metadata를 보내도 private로 저장한다. Collection content `read`가 없는 domain 관리자는 허용 action 수행에 필요한 safe 관리 projection만 받는다.
- 실제 PostgreSQL permission row를 사용하는 회귀 테스트는 active User direct grant와 active Team membership grant 각각에서 `catalog_manage`가 domain/list create capability와 POST create에 일관되게 반영되는지 검증한다. 생성 결과는 private/manual/active이고 canonical audit와 같은 transaction에 저장되며 Collection/KB content permission이나 route grant를 자동 생성하지 않아야 한다. 만료·inactive·cross-organization grant는 같은 경로에서 fail-closed해야 한다.
- Collection 관리 Client는 list management projection과 domain capability가 불일치해도 `domain-capabilities.can_create_collection`과 `can_change_public_visibility`를 사용해야 한다. Capability refresh 실패 뒤 이전 create/public control이 남거나, `catalog_manage`가 public visibility control을 활성화하면 테스트 실패다.
- Manual Collection 관리 UI는 생성·편집 가능한 Collection에 관리용 `name`과 별도의 nonblank 안전 표시 이름을 요구하고 request의 `safe_metadata.safe_label`로 전송해야 한다. Gateway는 제공된 label을 string으로 제한하고 공통 sanitizer와 255자 cap을 적용하며 control character·secret-like text·URL·email·path를 제거해야 한다. 타입이 잘못되거나 정제 후 안전 텍스트가 남지 않으면 입력값을 echo하지 않는 `400 validation.failed`여야 한다. Update는 기존 허용 safe metadata와 DB-owned visibility를 보존해야 한다.
- `safe_metadata.safe_label`이 없는 기존 Manual Collection은 관리 edit surface에 보완 필요 상태로 표시하고 raw `name`을 자동 복사하지 않아야 한다. 보완 전 route-safe picker는 `safe_label=null`을 반환하고 Client는 generic `지식 Collection`만 표시해야 한다. 서로 다른 안전 표시명을 저장한 route-allowed Collection은 LLM node picker에서 각각 구분되어야 하며 label 유무가 `route` 또는 child KB `use` 권한을 만들지 않아야 한다.
- Collection update/archive는 resource `manage`, 해당 domain action, 또는 organization manager를 허용하고 system-managed Collection의 source-owned field는 manual update로 바꾸지 못한다.
- Duplicate Collection safe name은 raw DB constraint나 internal value 없이 safe conflict response로 닫힌다.
- Collection item link는 `collection.manage`와 대상 KB `manage`를 모두 요구한다. 둘 중 하나만 있으면 실패하고 hidden KB id/name을 오류에 포함하지 않는다.
- Domain `catalog_manage` actor는 content 권한 없이 private Collection membership을 관리할 수 있다. Public Collection link/unlink/reorder는 domain/resource manage만으로는 실패하고 Organization manager acknowledgement와 source public approval gate를 요구한다.
- Domain `catalog_manage`만 가진 actor의 Collection item/link-candidate response는 manual KB에 유효한 `safe_metadata.safe_label`이 있으면 sanitizer를 통과한 label만 표시하고, 없으면 generic label을 표시한다. Raw `kb.name`은 독립 KB `read`가 확인된 actor에게만 허용하며 source-managed KB는 기존 display-policy-approved safe label 규칙을 계속 적용한다.
- Collection item duplicate link는 idempotent success 또는 문서화된 safe conflict 중 하나로 deterministic하게 처리한다.
- Collection item unlink와 reorder는 같은 Collection 안의 item만 대상으로 하며, 다른 organization 또는 hidden KB item을 조작하지 못한다.
- Link candidate API는 resource manager에게 KB `manage` 가능한 후보만 반환하고, domain `catalog_manage`에는 private membership 관리용 safe 후보만 반환한다. Public 후보는 Organization manager와 source exposure gate를 통과해야 한다.
- Collection permission grant/revoke는 `read`, `route`, `manage`, `sync`만 허용하고 explicit deny나 role inheritance를 만들지 않는다.
- Collection UI role bundle은 Viewer=`read`, Workflow Router=`read+route`, Maintainer=`read+manage`, Sync Operator=`read+sync` explicit row를 한 transaction에서 적용하며 어떤 bundle도 KB `use`를 만들지 않는다.
- Collection permission revoke는 자기 자신의 마지막 `manage` grant 제거 edge case를 safe denial 또는 organization manager 전용 동작으로 처리한다.
- KB permission list API는 `resource_type="knowledge_base"`와 team/user permission 목록을 반환하고, hidden KB id/name/count를 노출하지 않는다.
- KB team permission grant/revoke는 기존 team KB permission table을 사용하고, KB user direct permission grant/revoke는 `user_knowledge_permissions`를 사용한다.
- KB team/user permission grant/revoke는 권한 row 변경과 같은 transaction에서 canonical data-change audit row를 하나만 추가하며, Core upsert 또는 bulk delete가 ORM listener를 우회해도 audit이 누락되지 않는다.
- Resource permission registry contract는 schema가 허용하는 `workflow`, `llm_credential`, `knowledge_base` resource type과 Gateway routing key가 일치하는지 검증한다.
- `resource_type="knowledge_base"` grant/revoke/list는 `TeamKnowledgePermission`과 `UserKnowledgePermission`만 사용하고 LLM credential 또는 workflow permission fallback으로 흐르지 않는다.
- KB hard delete는 Knowledge lifecycle service boundary를 통과하고, `team_knowledge_permissions`, `user_knowledge_permissions` direct grant row를 같은 transaction에서 먼저 정리해 orphan permission이나 FK failure를 남기지 않는다. Disposable PostgreSQL integration은 owner predicate, wrong-owner no-mutation, legacy cross-organization permission cleanup, document/chunk cascade와 실제 FK delete 성공을 검증한다.
- KB hard delete는 Organization manager와 explicit acknowledgement만 허용한다. Resource manager와 domain lifecycle manager는 archive/restore만 수행하고 hard delete나 system-managed source-owned lifecycle을 수행하지 못한다. Permission cleanup, canonical audit, KB delete 중 하나라도 실패하면 DB mutation 전체를 rollback한다.
- Unknown/cross-org/invisible direct resource는 `404 resource.hidden`, same-scope visible action 부족은 `403 permission.denied`, 목록은 unauthorized row와 exact hidden count를 생략한다.
- Disposable PostgreSQL integration은 명시적 host/port/user/password를 요구하고 기본 credential을 사용하지 않는다. Loopback 밖 host는 exact host confirmation 없이는 연결하지 않으며, allowlist random DB name만 생성/삭제하고 subprocess에는 검증된 개별 DB 설정만 전달한다. 실패 출력과 config representation은 credential/connection detail을 노출하지 않는다.
- Runtime/builder bulk KB permission evaluation은 team KB permission과 `user_knowledge_permissions` direct grant를 모두 합산해야 한다. User direct grant만 있는 경우에도 해당 user의 KB `use` 권한이 허용되어야 한다.
- Conversation Memory authorization adapter는 decision/principal kind/authorization decision revision, KB lifecycle/resource, policy revision과 evaluated timestamp를 각 bulk result에 포함하고 source-managed KB의 source ACL revision을 decision revision에 반영한다.
- Bulk result 일부가 누락되거나 revision을 만들 수 없으면 해당 dependency를 `unknown`으로 반환하고 allow로 채우지 않는다.
- Permission revoke, membership state 변경, KB archive/delete와 source ACL version 변경은 관련 revision을 바꾸어 기존 Memory lease/context 재사용을 차단한다.
- Public audience는 synthetic subject 없이 `anonymous_public_audience`로 평가하고 login cookie/Conversation Access Grant를 private KB permission으로 사용하지 않는다.
- Knowledge retrieval result는 KB/document version, organization, sensitivity와 authorization-safe reference만 RuntimeDataDependencyEnvelope로 반환하고 raw title/path/URL/content/ACL을 포함하지 않는다.
- Client/node가 Knowledge dependency를 위조하거나 optional로 낮춰도 canonical envelope를 변경하지 못한다. Answer에 영향을 준 KB dependency 하나가 revoke되면 derived Memory entry 전체를 제외한다.
- Public visibility 전환은 organization manager와 explicit acknowledgement를 요구하고, 전환 audit에는 raw KB title/path/url, hidden KB id/name, exact denied count가 들어가지 않는다.
- Public visibility가 켜져도 인증 사용자 KB `use` 권한이나 source ACL requester authorization이 생기지 않는다.
- Source-managed KB는 collection public flag만으로 anonymous public-only 후보가 되지 않는다. Source/connector public exposure approval이 없거나 `approval_scope`와 target field가 맞지 않는 approval row만 있으면 후보에서 제외된다.
- MBA-176 preflight/runtime availability에서 source-managed KB public exposure approval primitive가 없으면 `source_public_exposure_required` blocked로 처리하고 warning으로 낮추지 않는다.
- Connector-wide public exposure approval은 expiry, reverification cadence, revocation behavior, explicit acknowledgement가 없으면 invalid policy로 처리된다.
- Knowledge Collection 관리 UI는 Workflow Builder와 분리되어 있고, Builder 화면에서 Collection 생성/삭제/권한관리를 주 기능으로 제공하지 않는다.
- Collection 관리 UI는 `can_manage_collection`, `can_manage_kb`, `can_use_kb`를 혼동하지 않고, item list에 보이는 KB가 runtime retrieval 가능성을 보장하지 않는다는 상태를 표현한다.
- Collection 관리 UI는 raw source title/path/url/principal, hidden KB name/id, exact denied count를 표시하지 않는다.
- Collection list는 safe redacted name/description과 non-color text label이 있는 state badge를 표시한다.
- Collection lifecycle list는 active와 archived query를 분리한다. Archived manual Collection restore는 Organization manager, Collection `manage`, domain `lifecycle_manage`에서 허용하고 active restore retry는 새 mutation/audit 없는 `204`여야 한다. Deleted/cross-organization 대상은 hidden, system-managed 대상은 source-owner policy denial, `source_deleted` 대상은 safe conflict로 처리한다.
- Archive와 restore는 실제 PostgreSQL에서 같은 Collection row를 `FOR UPDATE`로 잠근다. 두 concurrent restore는 상태 전이와 canonical audit를 한 번만 만들고 audit flush/commit 실패는 lifecycle mutation과 audit를 모두 rollback한다. Restore가 permission, membership, child KB `use` 또는 Workflow `route` row를 만들면 테스트 실패다.
- Item GET, link와 reorder success response는 최신 전체 ordered item projection, `order_revision`, `reorder_supported`, optional fixed `safe_reason_code`를 같은 의미로 반환한다. Unlink 204 뒤 GET revision은 이전 값과 달라야 한다.
- Reorder는 current 전체 item id set, unique item id, unique contiguous `0..N-1` rank와 `expected_order_revision`을 요구한다. Duplicate item overwrite, partial request, missing/foreign/extra item, duplicate/gapped/negative rank, malformed 또는 다른 Collection revision은 아무 mutation 없이 거부한다. Current order no-op에는 새 audit를 만들지 않는다. Deleted/cross-organization target은 authority 또는 item order 조회 전에 hidden `404`로 처리한다.
- Item 0개와 1개는 stable revision을 만들 수 있고 500개는 reorder 가능하다. 501개부터 `reorder_supported=false`, `safe_reason_code=item_reorder_limit_exceeded`이며 mutation을 허용하지 않는다. Token은 권한이나 item 조회 capability로 사용되지 않는다.
- Empty Collection reorder는 `items=[]`와 current revision을 수용해 no-op safe projection을 반환한다. Link의 legacy `rank` 값은 삽입 위치를 바꾸지 않고 새 item은 끝에 append되며 전체 rank가 연속값으로 정규화되어야 한다.
- Link/reorder mutation authority는 있지만 별도 Collection `read`가 없는 actor도 mutation commit 뒤 safe management projection을 받아야 한다. 성공한 DB mutation 뒤 response projection의 권한 오류로 실패 응답을 반환하면 테스트 실패다.
- PostgreSQL concurrent reorder/reorder는 먼저 commit한 한 요청만 성공하고 두 번째는 lock 뒤 stale conflict가 된다. Reorder/link, reorder/unlink, reorder/visibility도 같은 Collection-first lock protocol을 사용해 membership set, rank, public acknowledgement가 stale 판단으로 우회되지 않아야 한다. 최종 rank는 contiguous하고 audit failure는 전체 rank를 rollback한다.
- Public Collection/KB의 source identity뿐 아니라 Collection `source_connector_ref`도 public link/reorder/visibility에서 같은 `source_public_exposure_required` fail-closed 정책을 적용한다.
- Delegation subject endpoint는 authority 확인 전 Team/User SELECT를 실행하지 않는다. Collection endpoint는 Organization manager, Collection `manage`, domain `permission_delegate`; domain endpoint는 Organization manager를 먼저 검증한다.
- Subject page는 `subject_type=team|user`, safe prefix query 100자 이하, opaque cursor, 기본 limit 25/최대 50을 적용한다. Current organization active Team과 active member User만 반환하고 inactive/cross-organization row, email, login principal, raw source identity와 total count를 포함하지 않는다.
- Subject prefix search는 whitespace와 case를 일관되게 처리하고 `%`, `_`, quote를 SQL wildcard/injection으로 해석하지 않는다. 동일 safe label은 UUID keyset tie-break로 page 간 duplicate/skip 없이 반환한다. Subject type/query가 다른 cursor와 malformed/oversized cursor는 입력값을 echo하지 않는 bounded safe error다.
- Subject combobox는 Team을 기본값으로 두고 debounce, loading, empty, error/retry, next-page, stale response 폐기와 keyboard navigation을 제공한다. Type/query 변경 시 stale selection을 정리하고 email/raw UUID를 visible label fallback으로 사용하지 않는다.
- Bundle revoke는 Viewer=`read`, Workflow Router=`read+route`, Maintainer=`read+manage`, Sync Operator=`read+sync`의 현재 explicit row만 한 transaction에서 제거한다. 없는 row는 unchanged이며 Maintainer grant 뒤 Viewer revoke 결과는 `manage`만 남는다. UI/API가 이를 저장된 Maintainer role로 추론하면 테스트 실패다.
- Bundle grant/revoke 일부 row 또는 audit 저장 실패는 전체 rollback한다. Grant는 active subject만 허용하고 inactive Team/removed User의 기존 permission은 revoke할 수 있다. 어떤 bundle도 child KB `use`를 만들지 않는다.
- Domain `permission_delegate` actor의 self/own-active-Team bundle grant는 차단하고 revoke는 last-manage 검증 뒤 허용한다. Current actor의 마지막 `manage` 경로를 제거하는 single/bundle/bulk revoke는 Organization manager recovery가 아닌 경우 전체 거부하며 independent manage path가 있으면 허용한다.
- 모든 bulk target에 effective Collection `manage`가 있는 actor는 domain `permission_delegate`도 함께 보유했다는 이유만으로 self/own-Team grant가 차단되지 않는다. 일부 target에만 resource `manage`가 있으면 domain-delegate self-escalation 차단을 적용한다.
- Multi-Collection bulk bundle은 unique Collection id 1~50개와 한 subject/bundle/operation만 받는다. 0개, 51개, duplicate/malformed id와 invalid enum은 mutation 전에 거부한다. Collection을 UUID 순으로 잠그고 모든 target의 organization/authority/last-manage를 사전 검증하며 한 target 실패 시 permission/audit 전체를 rollback한다.
- Bulk response는 operation, subject type, bundle과 target/changed/unchanged count bucket만 포함하고 Collection/subject id, label, 실패 index나 exact hidden count를 반환하지 않는다. 11~50개 count는 `11-50` bucket을 사용하고 response validation은 permission/audit commit 전에 완료한다. 1, 2, 50개 grant/revoke와 retry는 duplicate permission row 없이 deterministic해야 한다.
- PostgreSQL bulk 검증은 cross-organization target 혼합, N-1 authorized + 1 unauthorized, 한 target의 last-manage 실패, 반대 순서 target을 가진 concurrent request와 audit failure를 포함한다. Query/lock capture는 organization predicate와 실제 `FOR UPDATE`를 확인하고 target 수만큼 authorization query가 늘어나는 N+1을 허용하지 않는다.
- Permission UI는 Team row와 User direct row를 분리한다. 같은 action에 두 source가 있을 때 direct revoke 뒤 Team effective allow가 남는 사실을 표시하고 revoke success를 전체 접근 차단으로 잘못 표현하지 않는다.
- MBA-264는 Collection sync 실행 endpoint/job/UI, explicit deny, per-Collection expiry, bundle 저장 row, child KB `use` 자동 grant와 Workflow graph/runtime 변경을 추가하지 않는다.
- Source metadata에서 유래한 system-managed collection display name/description은 storage/display 전에 redaction, cap, display-policy approval을 거친다.
- KB detail은 hidden source path를 누출하지 않으면서 sync failed, source ACL stale, source deleted, archived, deleted state를 구분한다.
- Remediation queue는 raw connector exception string이 아니라 safe reason code와 retryability를 표시한다.
- Citation은 target identity field(`citation_id`, `knowledge_base_id`, `document_version_id`, `chunk_id`, optional `collection_id`, optional `safe_source_ref`)를 사용한다. `safe_source_ref`는 protected/HMAC source reference이며 raw source id/url/path/principal을 대체한다.
- User-facing content preview는 redacted/capped 상태이며 durable audit/trace/usage summary에 복사하지 않는다.
- A/B 비교 UI는 권한 없는 문서명/ID를 표시하지 않고 authorized evidence 기준의 context token, retrieved chunk count, citation count, cost, latency, quality score만 비교한다.
- 향후 Skill management, Workflow Playground, Agent Builder skill-binding UI가 추가되면 safe skill metadata, freshness, eval status, publication/review 상태만 표시하고 hidden source title/path/url이나 raw skill resource를 표시하지 않는다.
- Workflow Playground에서 draft/unpublished skill 실험을 허용하는 정책을 채택하더라도, 운영 실행 시점 자동 후보에는 포함되지 않고 actor의 KB permission/source ACL/redaction gate를 우회하지 않는다.
- Demo fixture는 상담원 허용 문서와 제한 문서를 분리하고, 제한 문서가 모든 운영 RAG mode의 prompt/citation/trace에 포함되지 않는지 검증한다.

## Performance And Load Tests

- Bulk permission helper는 per-KB database query 없이 user-candidate lookup과 KB-centric lookup을 처리한다.
- Candidate cap은 stable ordering으로 큰 candidate set을 deterministic하게 잘라낸다.
- MBA-232 runtime candidate ID/authorization은 invocation 사이에 cache하지 않는다. 향후 별도 승인된 candidate cache는 permission/freshness revision을 포함하고 ACL revocation 시 invalidation되어야 한다.
- Runtime access cache key는 mapping epoch와 source ACL freshness epoch를 포함하고, source item/document version 단위로 분리된다.
- Skill candidate cache key는 skill version, freshness state, eval state, source version reference를 포함하고 stale skill/source-tier 변경 시 invalidation된다.
- 단일 filtered vector/keyword query를 우선한다. Bounded fanout을 사용하면 concurrency와 timeout cap을 강제한다.
- Query rewrite cache key는 rewrite mode, safe template id, skill version, permission/freshness epoch를 포함하고 raw rewritten query를 durable key로 사용하지 않는다.
- Retry/dead-letter는 idempotency key, retryable flag, attempt count, safe reason code, dead-letter state, re-drive path를 검증한다.
- Load test는 max candidate KB, max route collection, max retrieval KB, max chunks per KB, max total chunks, fanout timeout, aggregate interactive timeout, permission helper index, candidate cache, recovery scanner cadence, trace/audit payload size, partial operational failure behavior, query rewrite 추가 latency/cost budget을 포함한다.
- Concurrent ingestion, concurrent DB-source sync, concurrent retention purge, cleanup outbox retry의 race 테스트를 포함한다.

## Phase Acceptance Tests

- Phase 1 acceptance에는 egress negative paths, content safety/parser isolation, protected source identity, basic sync, redaction, active version swap, transactional outbox insert, fencing token, recovery scanner smoke 테스트가 포함된다.
- Phase 2 acceptance에는 source ACL freshness, content cursor와 ACL/permission watermark 분리, Knowledge Permission Helper, KB `use` + source ACL two-gate, source-policy grant inactive lifecycle 테스트가 포함된다.
- Phase 3 acceptance에는 multi-KB caps, final evidence recheck, resource hiding matrix, retry/dead-letter transition, partial result behavior, runtime authorization batch/fallback 테스트가 포함된다.
- Live-linked mode를 구현하는 phase는 requester-scoped/opaque-ref-only side-channel 테스트를 포함한다.
- Source-managed public exposure를 구현하는 phase는 approval scope/target validation과 revocation propagation 테스트를 포함한다.
- Golden questions, source tier tuning, LLM-assisted rewrite, advanced rerank는 core safety phases 이후 별도 acceptance로 확장한다.
