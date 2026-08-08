# Agent Builder Cache Protected Resource Completion

Status: Draft

## Applicability

이 기능은 cache key를 organization/user scope로 제한하고, hit 결과가 model credential,
Knowledge/Collection과 workflow graph에 영향을 줄 수 있으므로 protected-resource completion
검토 대상이다. Cache 자체는 protected resource를 durable하게 저장하지 않는다.

MBA-348은 normalizer, Redis/single-flight adapter, current-context rehydrator를 coordinator로 조합하고
`AgentBuilderService`의 planning seam과 composition root에 연결하는 Redis/config/coordinator/lifecycle 런타임 통합을 완료했다.
Cache-off는 기존 Planner 경로를 유지하고, cache hit/miss/error 진단은 allowlist된 안전한 값만 남긴다.
기능 플래그는 기본적으로 enabled를 요청하며 `scripts/dev-local.ps1`는 cache-on으로 시작한다. 직접 실행에서
전용 Redis URL·HMAC key/version·bounded configuration이 불완전하면 Celery Redis fallback 없이 cache만
비활성화한다. production/staging serving은 운영 evidence와 명시적 readiness attestation 전까지 비활성이다.

**MBA-348 코드 수준 상태.** 아래 matrix는 구현 완료된 코드 수준 경계와 MBA-349가 검증할 실제 소비·운영 경계를 구분한다.
MBA-349는 실제 Postgres permission/lifecycle/Collection 소비 경계, GraphMutation/CAS/acknowledgement,
durable audit 및 production serving 증거를 계속 소유한다. MBA-350은 live benchmark와 최종 증거를 소유한다.
| Boundary | 현재 상태 | Decision and safe interim state | Evidence target |
|---|---|---|---|
| 정책·식별자 | MBA-343~346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 소비 경계·운영 증거 | MBA-343 plan은 protected identity를 저장하지 않는다. MBA-344 normalizer는 protected identity를 읽지 않고 전체 safe message에서 유도한 normalized ordered typed canonical projection의 domain-separated SHA-256 `intent_signature`만 반환하며 version mismatch는 bypass한다. MBA-345~346 leaf와 MBA-348 coordinator는 organization/user scope, selected target identity와 Knowledge candidate fingerprint를 HMAC boundary 밖으로 노출하지 않는다. Cache serving은 기본 요청이지만 production/staging은 evidence와 attestation 전 비활성이다. | ADR-0063, ADR-0073, ADR-0074, ABC343-FR-002~005, ABC343-T011~018, ABC-FR-001~008, ABC-T001~019 |
| 관리 API/UI | 해당 없음 | Cache는 관리 리소스가 아니며 public endpoint, picker, 권한 관리 UI와 client diagnostic을 추가하지 않는다. 기존 Agent Builder UI 계약을 유지한다. | `api_spec.md` External API Boundary, `component_spec.md` PRD and Core Document Impact |
| Cache storage·GraphMutation | MBA-343~346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 GraphMutation/CAS 소비 경계 검증 | MBA-343은 cache-safe typed plan과 forbidden-content 계약을 제공한다. MBA-348은 adapter에 Resource ID, handle, credential, graph와 operation을 제외한 plan만 저장하고, 결과는 기존 GraphMutation/CAS 경로로만 전달한다. | ABC343-FR-001~004, ABC343-T001~028, ABC-FR-030~036, ABC-FR-044, ABC-T066~068 |
| Cache integrity | MBA-343 codec 및 MBA-348 adapter 통합 구현·회귀 검증; MBA-349 운영 evidence | Canonical codec·size·schema·forbidden-content 검증과 authenticated envelope가 key digest와 payload를 묶고 MAC 확인 전 plan 사용을 막는다. 운영 evidence/attestation이 없으면 production/staging serving만 비활성이다. | ABC343-FR-004, ABC343-T019~028, ABC343-T059~067, ABC-FR-026, ABC-FR-034~036, ABC-T031~035 |
| HMAC secret | 후속 이슈: MBA-345, MBA-349 | 기존 untracked/production secret injection 경계만 사용하고 tracked env, repr, log, trace와 audit 노출을 금지한다. | ABC-FR-025, ABC-FR-087~089, ABC-T126~129 |
| Redis connection secret | 후속 이슈: MBA-345, MBA-349 | URL password와 query credential을 configuration error와 diagnostic에 노출하지 않는다. | ABC-FR-087, ABC-T126, ABC-T129 |
| Cache process lifecycle | MBA-348 code-level implementation/regression; MBA-349 serving evidence | Gateway lifespan owns one optional configured Redis adapter/pool in app state; requests reuse its boundary, disabled cache constructs none, and shutdown closes it once. No Redis URL, HMAC material, cache value, or protected identity is retained outside the process-owned adapter. | `component_spec.md` Lifecycle amendment, ABC-T101, ABC-T133 |
| Organization scope | MBA-345 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 소비 경계 검증 | Active organization과 user를 HMAC key material에 포함하고 사용자 간 entry를 공유하지 않는다. | ABC-FR-020~024, ABC-T020~027 |
| Request admission | MBA-348 code-level implementation/regression; MBA-349 actual consumer-boundary evidence | After existing authentication, permission and foreground admission, a cache-enabled coordinator checks the request cancellation/version fence before normalizer/lookup, before a direct hit is rehydrated, before owner Planner work, and in follower waits. The same bound fence applies when planning-context construction bypasses at the 4,000-character safe-message limit. Canceled or stale requests do not consume a cache value or start Planner work; cache-off calls only the existing Planner. | ABC-FR-009, ABC-FR-075, ABC-T052~054 |
| Planner model/credential | MBA-346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 permission/lifecycle 소비 경계 검증 | Hit 전 valid credential, active model, verified relation과 use permission을 다시 검증한다. | ABC-FR-040, ABC-FR-054, ABC-T060~061 |
| Knowledge/Collection | MBA-346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 permission/lifecycle/Collection 소비 경계 검증 | Hit마다 현재 route/use permission, lifecycle/readiness를 다시 계산하고 handle을 새로 발급한다. | ABC-FR-050~054, ABC-T080~087 |
| Workflow target | MBA-345~346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 소비 경계 검증 | Selected target identity는 ephemeral HMAC input으로만 사용한다. Hit에서는 server-loaded graph와 target을 다시 resolve하고 UUID를 재사용하지 않는다. | ABC-FR-019, ABC-FR-041~043, ABC-T036, ABC-T062~066 |
| Deployment preflight | 해당 없음 | Cache는 graph/deployment에 reference를 추가하지 않고 생성 단계 plan에만 사용한다. 생성된 graph는 cache outcome과 무관하게 기존 deployment preflight를 그대로 통과한다. | ABC-FR-044, ABC-T142 |
| Deployment preflight와 generated graph runtime | 해당 없음 | Cache는 graph/deployment reference를 추가하거나 workflow를 실행하지 않는다. Generated graph의 runtime 권한·lifecycle 검사는 기존 계약이 계속 소유한다. | Side-effect boundary regression, ABC-T142~143 |
| L2 retention background task | In Progress | 5분 Beat와 Log System task는 만료 encrypted L2 row만 bounded hard-delete한다. Cache plan을 serving하거나 protected authority를 부여하지 않고 cache audit/replay record도 만들지 않는다. | ADR-0075 Decision 5, ABC-FR-099, ABC-T149c |
| Transaction/TOCTOU | MBA-345 and MBA-348 code-level implementation/regression; MBA-349 actual consumer-boundary evidence | A request-bound guard ends only a clean service read transaction before every Redis operation: lookup, lease, follower wait, save, completion signal and release. This includes Redis work reached after current runtime, graph, membership or Knowledge rehydration has read the service Session. Its terminal-state fence queries through a separate autocommit connection. If the clean boundary cannot be established, the coordinator skips subsequent Redis I/O and preserves the existing Planner or already canonical result path. An unavailable initial guard reaches the existing Planner once only, and a Planner exception is not retried as cache I/O handling. Provider consumer-boundary verification and final request-state CAS remain MBA-349 downstream evidence. | ABC-FR-063, ABC-FR-068, ABC-T053, ABC-T106, ABC-T110~114 |
| Retry·idempotency | MBA-345 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 GraphMutation/CAS 소비 경계 검증 | Single-flight는 best-effort 비용 최적화이고 기존 provider usage identity, GraphMutation/CAS idempotency를 대체하지 않는다. | ABC-FR-062~069, ABC-T102~116, ABC-T131~132 |
| Background coordination | 해당 없음 | Lease는 foreground request의 bounded single-flight에만 사용하며 worker claim이나 durable background coordination을 만들지 않는다. | `component_spec.md` Single-Flight, ABC-T102~116 |
| Lifecycle | MBA-346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 lifecycle 소비 경계 검증 | Revoked/deleted/stale resource는 hit revalidation에서 제외하거나 기존 permission/stale 계약으로 차단한다. | ABC-FR-040~048, ABC-FR-050~054, ABC-T060~068, ABC-T080~084 |
| Cache key rotation·migration | 후속 이슈: MBA-345, MBA-349 | HMAC key/version 변경은 dual-read, migration과 backfill 없이 namespace miss를 만든다. | ABC-FR-082~083, ABC-FR-088, ABC-T125, ABC-T128 |
| Legacy data | 해당 없음 | Serving cache, DB schema와 기존 cache data는 없다. MBA-343 spine은 value를 저장하지 않으며 신규 namespace는 이전 value를 읽지 않는다. | ADR-0063 Decision 12~14, ABC343-FR-007~009 |
| 오류·resource hiding | MBA-345~346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 소비 경계 검증 | Redis 오류는 safe fail-open, protected-resource permission/CAS 오류는 기존 fail-closed 계약으로 처리하고 식별자를 diagnostic에 노출하지 않는다. | ABC-FR-060~061, ABC-FR-073, ABC-T100, ABC-T120~121 |
| Audit | MBA-348 코드 수준 구현·회귀 검증; MBA-349 durable audit 소비 경계 검증 | Cache hit가 workflow mutation audit을 대체하지 않는다. Audit는 cache key/value/plan의 durable copy나 Redis 복구 replay source가 아니다. | ABC-FR-074, ABC-FR-077, ABC-T124, ABC-T130 |
| Usage/cost | MBA-348 코드 수준 구현·회귀 검증; MBA-349 실제 usage/audit 소비 경계 검증 | Hit는 provider usage가 없고 miss/repair만 기존 recorder를 사용한다. | ABC-FR-070~071, ABC-T048~050, ABC-T122~123 |
| Redaction | MBA-343~346 및 MBA-348 코드 수준 구현·회귀 검증; MBA-349~350 실제 소비 경계·최종 증거 | MBA-343은 cache DTO/codec validation input, 원본 validator context와 exception chain을 제거한다. MBA-344는 redaction/secret marker를 `sensitive_input`으로 bypass하고 result/repr에 message를 노출하지 않는다. 현재 serving 경계도 raw request, cache key digest 전체, protected identity, secret과 provider payload를 log, metric, audit와 artifact에 남기지 않는다. Cache serving은 기본 요청이지만 production/staging은 evidence와 attestation 전 비활성이다. | ABC343-FR-003, ABC343-FR-010, ABC343-T011~T018, ABC343-T056, ABC343-T059, ABC343-T063~T067; ADR-0073, ADR-0074, ABC-FR-001~008, ABC-T001~019; ABC-FR-032~036, ABC-FR-073, ABC-NFR-014~015, ABC-T027~035, ABC-T121, ABC-T126~130, ABC-T158, ABC-T165~167 |
| Redis isolation·운영 serving | MBA-345 코드 수준 구현·회귀 검증; MBA-349 운영 serving 검증 | MBA-345는 전용 URL, no-Celery-fallback과 `NODE_ENV=production|staging` readiness gate를 소유한다. MBA-349는 운영 evidence 부재 시 fail-closed 통합 검증을 소유한다. 실제 instance/secret wiring/capacity·eviction/failure/network/monitoring/rollback은 별도 운영 범위이며 evidence 전 serving을 비활성으로 유지한다. | ABC-FR-085~094, ABC-T107, ABC-T117~119, 운영 serving 전 evidence |
| 문서·테스트 | MBA-343~346 및 MBA-348 로컬 코드 수준 evidence 완료; MBA-349~350 후속 evidence | 각 leaf와 MBA-348 통합의 코드·회귀·review evidence를 local 경로에 기록한다. MBA-349가 실제 소비 경계 및 serving 통합 evidence로 이 matrix를 다시 갱신한다. | `requirements.md`, `api_spec.md`, `component_spec.md`, `test_cases.md`, `../agent-builder-cache-343/`, `local/mba-343/evidence/README.md`, `local/mba-344/evidence/README.md`, `local/mba-348/` |


**MBA-344 redaction clarification.** Raw safe input and its transient NFKC/whitespace cleanup form both pass fail-closed secret/redaction/truncation gates before lookup/store. The safety-gate match result is not retained, surfaced, or separately signed; the required cleanup transformations still feed the normal signature projection. Quoted Catalog display labels are used only as a value-bypass signal.

## JEO-7 Durable L2 Completion Record

JEO-7 진행 상태: In Progress

ADR-0075의 L2는 protected resource의 durable reference를 저장하지 않지만 organization scope,
credential/model relation, workflow target와 Knowledge revalidation을 다시 소비한다. 이 matrix는
JEO-7 implementation에서 각 경계를 코드·테스트·문서로 연결한다.

| Boundary | Status | JEO-7 contract and evidence target |
|---|---|---|
| Durable cache storage | In Progress | `AgentBuilderIntentPlanCacheRecord`에는 organization scope, encrypted strict plan, MAC와 retention metadata만 저장한다. Graph, raw request, credential reference, parameter value와 authorization decision은 forbidden-content codec 및 repository tests로 차단한다. |
| Organization and request admission | In Progress | L2 lookup은 authenticated active organization, request admission, cancellation fence와 L1 miss 뒤에만 실행한다. Repository predicate와 unique index는 organization scope를 강제하고 cross-organization integration test가 증명한다. |
| Credential/model and Knowledge lifecycle | In Progress | L2 hit은 기존 current rehydrator를 재사용한다. current credential/model relation, workflow/target, Catalog와 Knowledge permission/lifecycle 검증을 통과하지 못하면 promotion하지 않고 Planner path를 따른다. |
| Secret and envelope integrity | In Progress | cache 전용 Fernet keyring과 repository HMAC domain을 사용한다. key, allowlist, lookup token, ciphertext, plan과 protected identifier는 response, audit, metric, trace, log와 fixture에서 금지한다. |
| DB-first transaction boundary | In Progress | Planner/provider/Redis I/O와 분리한 independent short L2 transaction을 사용한다. L2 commit 성공 뒤에만 L1 write하고 failure는 response를 실패시키지 않되 L1 write를 하지 않는다. |
| Lifecycle and deletion | In Progress | `expires_at`은 30-day immutable retention이다. read와 unexpired same-key 재저장은 연장하지 않고, bounded purge는 delete 시 expiry를 재검사해 갱신 row를 hard-delete하지 않는다. organization delete는 FK cascade이며 downgrade는 L2 row 존재 시 거부한다. |
| Audit and command history | In Progress | canonical cache-purge audit은 만들지 않는다. schema-ready `agent_builder_requests.intent_cache_outcome`에는 allowlisted outcome만 기록하며 cache source/payload/key/detail을 남기지 않는다. rolling deploy의 이전 schema 또는 readiness 확인 실패에서는 이 telemetry만 생략하고 request 흐름을 유지한다. |
| Runtime/background | In Progress | purge task는 bounded expired-row deletion만 수행하며 cache plan을 serving하거나 protected authority를 부여하지 않는다. production allowlist activation은 JEO-7 범위 밖이다. |

## Merge Blocking Conditions

- Cache value나 diagnostic에 protected resource ID 또는 credential이 노출된다.
- Cache hit가 현재 permission/lifecycle 검사를 생략한다.
- Cache hit가 Agent Builder request admission, cancellation 또는 foreground request 직렬화를 우회한다.
- Cache hit가 기존 graph resource validation 또는 CAS를 우회한다.
- Redis 장애가 Agent Builder 요청 자체를 차단한다.
- HMAC key 또는 Redis connection secret 원문이 configuration error, log, trace, audit 또는 fixture에 노출된다.
- Production 운영 증거 확인 전에 운영자가 ready attestation을 설정하거나 Agent Builder intent cache를 활성화한다.
- 전용 cache Redis URL 없이 Celery broker/result Redis로 자동 fallback한다.
- Cache hit에서 provider usage row를 허위로 만들거나 miss provider cost를 누락한다.
- Cache payload authenticity를 검증하지 않거나 다른 key의 valid payload 교체를 허용한다.
- Cache memory pressure가 Celery broker/result key를 eviction할 수 있는 상태로 production serving을 켠다.

위 항목은 운영 증거 확인 전에는 운영자가 ready attestation을 설정할 수 없다는 의미다. 런타임은 별도 evidence
저장소를 조회하지 않고 attestation과 bounded configuration을 검사한다. Cache 코드·필수 검증 완료는 운영
작업 번호와 독립적으로 판정하며, 실제 Production Redis evidence 전에는 production/staging serving만 비활성으로 유지한다.

## MBA-349 Actual Consumer Verification

MBA-349 검증 상태: Local Integration Verified (current disposable PostgreSQL rerun)

| Boundary | Status | Code and test evidence | Remaining condition |
| --- | --- | --- | --- |
| Cache storage, GraphMutation, CAS, acknowledgement | Complete | `test_actual_cache_hit_reaches_safe_envelope_cas_ack_audit_and_blocks_revoked_credential` passed against disposable PostgreSQL. The current combined workflow-CAS and intent-usage PostgreSQL rerun passed `56` tests. Warm hit reached the ordinary safe envelope, workflow CAS save, and acknowledgement. | No cache plan is persisted with a GraphMutation envelope. |
| Model/credential permission and lifecycle | Complete | The same PostgreSQL consumer test queries current credential, model, and verified relation state on cache-context construction and revalidation; a committed credential revoke returns `configuration_required` without a GraphMutation or usage row. | No prior permission decision is reused. |
| Current workflow target and Knowledge/Collection | Complete | Existing current-target and current-Knowledge rehydration regressions cover changed/deleted target and current handle reissue; the PostgreSQL consumer test reaches the same rehydrator factory before GraphMutation. | Current server resolution remains authoritative. |
| Redis TTL, authenticated envelope, generation fence, rotation | Complete | Existing CACHE-03 Redis integration, including the current stale-lease fenced-save regression, passed (`6 passed`). A live Redis smoke check used two ephemeral HMAC versions and verified new namespace cold miss without dual-read. | Namespace rotation remains a cold-miss contract. |
| Cache-off, Redis outage, and serving gate | Complete | Existing cache-off service regression remains unchanged. `test_actual_cache_cold_paths_record_single_provider_usage` proves cache-enabled cold miss and cache-unavailable fail-open each call the synthetic provider once and create one request-scoped durable usage row. | Production/staging serving remains disabled without operational evidence. |
| Audit, usage, and event redaction | Complete | The PostgreSQL consumer test proves a warm hit creates no provider call or usage row, preserves issued/acknowledged audit events, and retains no cached plan in the safe envelope. The cold/error path test proves one provider call and one request-scoped usage row per request. Existing observer/codec tests cover allowlisted redaction. | Cache events are not a durable replay source. |
| Final benchmark artifact redaction | Complete | MBA-350 final live bundle passed the runner's row, pair, outcome, and artifact-redaction validation before publication. | The published bundle contains only allowlisted summaries, CSV/JSON, and SVG evidence; it is not a serving or replay store. |
| Deployment preflight and generated-graph runtime | Not applicable | Cache adds no deployment reference or workflow runtime work. | Existing generated-graph consumers retain these checks. |
| L2 retention background task | In Progress | JEO-7 adds a five-minute Beat-triggered Log System task that bounded-hard-deletes expired encrypted L2 rows only; it neither serves a cache plan nor grants protected authority. | The JEO-7 completion record above owns repository/retention tests; no cache audit or replay source is created. |
| Production Redis rollout | Follow-up operational issue | Production/staging serving gate stays fail closed until operational evidence and attestation; the default cache request remains enabled. | Instance, secret wiring, capacity, failure, monitoring, rollback, and operational attestation are outside CACHE-07. |

Current local execution used the repository's explicit disposable PostgreSQL configuration sourced without printing connection values from the running Compose service. The combined CAS and intent-usage modules passed `56` tests. The Redis integration, including stale-lease fenced-save coverage, passed `6` tests, and the rotation smoke check emitted no key, value, credential, or request content.

## MBA-349 Consumer-Evidence Correction

This section supersedes the MBA-349 consumer-evidence counts and descriptions above.

- The current disposable PostgreSQL workflow-CAS plus intent-usage module result is `56 passed`; it supersedes the historical `19` and `21` counts.
- The selected-target regression builds a planning context from a persisted workflow, removes the selected target before cache rehydration, and verifies that the real coordinator discards the warm plan before any mutation path.
- The Knowledge regression deletes a persisted Knowledge row before the current resolver runs and verifies that rehydration emits no restored candidate handle. It does not claim that a historical Knowledge identifier was cached; plan contracts intentionally contain no durable Knowledge identity.
- The consumer audit query recursively rejects cache-plan and raw-payload metadata field names in durable issued and acknowledged audit rows. It proves that a warm hit has no provider call or planner usage row.
- The cache-enabled cold-miss and cache-unavailable fail-open regression invokes the synthetic provider once and records one durable usage row for its own request, proving lazy usage-context creation does not lose or duplicate attribution.
- Credential/model/relation state is separately re-read from PostgreSQL; a committed credential revoke is fail closed before GraphMutation, CAS, acknowledgement, usage, or external provider work.

MBA-350 final benchmark artifacts are recorded in the safe published bundle and remain evaluation evidence only. The actual consumer boundaries above are complete only for the local disposable PostgreSQL environment; production serving remains gated by the existing operational attestation requirement.

## JEO-8 Private Dense Semantic Cache Completion

JEO-8 상태: 구현 완료, production 기본 비활성. ADR-0076에 따라 transient semantic 계약, pgvector index adapter/migration, verifier/current rehydration gate와 retention 정합성을 구현했다. 승인된 Agent Builder `query_embedding` authority, live provider adapter와 durable usage binding이 없어 production semantic assist와 serving은 composition하지 않는다. JEO-7 L2 plan row는 계속 source of truth이며 새 index는 protected resource reference나 authorization decision을 저장하지 않는다.

| Boundary | Safe state | Implementation and verification evidence |
|---|---|---|
| Policy and identity | Semantic candidate scope is exactly active `organization_id + user_id` and target-independent `new_workflow`; selected-target and modify/replace requests never enter semantic I/O or persistence. A decoded candidate must independently prove `request_type=new_workflow`, `draft_mode=new_workflow`, `edit_placement=null` before verifier/rehydration. A vector score never proves equality or authority. | ADR-0076 Decision 1~8; ABC-FR-103~110, ABC-FR-124, ABC-FR-128; ABC-T180~189, ABC-T198, ABC-T202, ABC-T206 |
| Management API/UI | 해당 없음. JEO-8 creates no management API, public cache endpoint, Client UI, picker or grant model. `api_spec.md` changes only to document the internal L2 receipt/projection/retention port amendment. | Public request/response unchanged; ABC-FR-117, ABC-FR-121; ABC-T210 |
| Durable storage | Only safe embedding, `semantic_query_projection_version`, other safe scope/version metadata and an L2 record FK are stored. Raw request/query, graph, plan/envelope copy, protected IDs, parameter values and permission decisions remain forbidden. | ABC-FR-110~111; ABC-T185, ABC-T194; model/codec/repository tests |
| Tenant isolation | Index query and write use organization plus user predicates; composite FK binds the index organization to the parent L2 organization. | ABC-FR-109~110; ABC-T182~185; PostgreSQL FK/query test |
| Embedding provider | JEO-8 production composition has no live adapter until an approved Agent Builder `query_embedding` capability/profile and durable usage binding exist. `admitted` requires an opaque, repr-redacted, non-serialized purpose binding; embedding consumes only `query_embedding` and a provider-backed verifier obtains a separate `semantic_verification` binding. Fake tests accept only a non-truncated transient `SemanticQueryProjectionV1` of at most 240 cleaned code points; longer text never reaches semantic I/O. | ABC-FR-105, ABC-FR-114, ABC-FR-117~119, ABC-FR-123~124, ABC-FR-130, ABC-FR-133; ABC-T190, ABC-T194, ABC-T196, ABC-T198, ABC-T204, ABC-T209, ABC-T215 |
| Semantic verifier | Missing, uncertain, failed or provider-I/O verifier cannot enable Planner-free serving. A provider-backed verifier is assist-only and uses the same current admission/usage boundary. Planner-free serving may still use an admitted query-embedding provider call; similarity alone always falls back. | ABC-FR-106~108, ABC-FR-124; ABC-T187~189, ABC-T193, ABC-T198 |
| Model/credential, target and Knowledge lifecycle | Target-bound requests are semantic-ineligible. Target-independent candidate reuse still passes current model/credential, graph context and Knowledge rehydration so it does not reuse past permission or lifecycle state. | ABC-FR-104, ABC-FR-107~108, ABC-FR-128; ABC-T189, ABC-T202; existing ABC-T060~068 and ABC-T080~087 regressions |
| Transaction/TOCTOU | The JEO-7 clean request-transaction boundary expands to embedding, semantic repository, verifier, candidate rehydration and fallback Planner. A semantic guard failure is sticky: no retained embedding append or later semantic I/O. Candidate rehydration must close its clean read transaction before serving/Planner; failure ends before provider/cache write. Cancellation/version is rechecked after each semantic external boundary and before value use/Planner. | ABC-FR-114, ABC-FR-132; ABC-T196, ABC-T214; coordinator guard/fence tests |
| Write ordering and retry | Same short independent L2 transaction locks/classifies the unique row and returns strict `IntentPlanL2SaveResult` with a DB-confirmed `IntentPlanL2StoredReceipt`; Redis save DTO remains unchanged. That receipt plus an existing in-memory embedding precedes one best-effort index append. Current `IntentPlanningContext.organization_id` and receipt parent ID/expiry are fenced in append SQL. Insert/unexpired conflict insert a missing child and no-op on conflict; expired replacement inserts an already-purged child or updates only an older child. No receipt/embedding means no append; parent mismatch, late receipt and same/newer child are zero-write; append failure never rolls back L2/L1/Planner result. | ABC-FR-115~117, ABC-FR-126~129; ABC-T191~192, ABC-T200~203, ABC-T208, ABC-T210~211 |
| Lifecycle and background | Parent L2 record supplies the intended 30-day child expiry. The existing L2 retention task purges expired children in an isolated savepoint/transaction with delete-time expiry recheck before parent purge, and parent delete cascades remaining children. Readiness disables only that invocation's child step; the same worker re-probes next Beat. Child/parent counts and `batch_full` keep the existing five-loop run bounded while either per-kind batch is full. A failed best-effort child replacement therefore cannot retain an old embedding until the renewed parent expires. No new semantic worker/audit/replay task exists. | ADR-0076 Decision 4/12; ABC-FR-112~113, ABC-FR-127, ABC-FR-129; ABC-T186, ABC-T195, ABC-T197, ABC-T207, ABC-T212~213 |
| Deployment preflight and generated runtime | 해당 없음. Semantic index does not enter graph, deployment or runtime configuration; generated graph remains on its existing preflight/runtime authority. | ABC-FR-121; direct-edit regression |
| Audit, metrics and redaction | Existing coarse cache outcome maps semantic serving to `hit`, normal fallback to `miss`, infrastructure/readiness fallback to `error`, and semantic-not-started to the exact outcome; rollback restores it. Semantic source, candidate, score, projection, embedding and protected identity are not observed. | ABC-FR-119~120, ABC-FR-130~131; ABC-T194, ABC-T204~205 |
| Configuration and rollout | Assist and Planner-free serving are independently default-disabled. Tests may inject fakes, but no production live adapter is composed before approved Agent Builder provider authority. No production provider/model/dimension/top-k/threshold is fixed; semantic-only stale-schema readiness is independently safe-disabled. | ABC-FR-118, ABC-FR-123~124, ABC-FR-127; ABC-T193, ABC-T201, ABC-T204 |
| Migration and downgrade | Additive semantic schema can be removed only after semantic rows are gone; JEO-7 L2 downgrade guard still protects parent records. | ABC-FR-113; ABC-T197 |
| Documents and tests | Requirements, internal API, component, test and this completion record track the implementation. Narrow coordinator/contracts/repository/config/migration/retention/composition tests provide local evidence; real PostgreSQL/pgvector and full regression remain rollout/CI gates. | ADR-0076; `test_intent_semantic_cache_*`, `test_agent_builder_intent_plan_semantic_repository.py`, `test_agent_builder_semantic_cache_migration.py`; ABC-T180~215 |

### JEO-8 merge blockers

- A semantic candidate is served from similarity, rank or threshold without an explicit verifier decision and current rehydration.
- A selected-target or modify/replace request reaches semantic embedding, retrieval, serving or index append.
- Semantic lookup or write can cross an organization/user boundary, or the database FK permits an index row to reference another organization’s L2 parent.
- Raw request/query text, live/derived vector value or score, plan/envelope duplicate, graph or protected resource identity reaches storage, log, metric, trace, audit or captured production fixture. Synthetic unit-test vectors without provider/user provenance are allowed.
- Service DB transaction/connection remains open while embedding provider, Planner provider, Redis, verifier provider or a separate semantic session is awaited.
- A semantic guard failure leaves an embedding eligible for later append, candidate rehydration leaves a service transaction open into Planner, or cancellation/stale after a semantic external boundary still reaches serving, Planner or cache writes.
- A live production embedding/provider-backed-verifier adapter is composed before approved Agent Builder `query_embedding` authority and durable usage binding, receives full/raw text instead of `SemanticQueryProjectionV1`, skips current admission, or enables Planner-free serving with a provider-I/O verifier.
- An admitted provider call lacks a purpose-matching opaque binding, reuses the query-embedding binding for provider-backed verification, or exposes/serializes the binding or its execution reference.
- A semantic projection longer than 240 cleaned code points is sliced and sent to embedding/verifier instead of failing closed to Planner.
- A lease follower executes semantic I/O, or a semantic serving result skips its owner-only current-key L1 promotion attempt.
- Semantic index append occurs before L2 `stored` commit/receipt, or L2 failure can still leave an index row.
- Semantic receipt is not represented by an L2-only strict stored-result/receipt contract, is not the same-transaction DB-confirmed parent ID/immutable expiry/write kind, or relies on a guessed ID/post-commit read/unbounded retry.
- Semantic append omits the current-context organization plus receipt parent ID/expiry fence; cannot insert a missing child after retention; leaves the old embedding after a successful replacement; allows a late receipt to recreate/overwrite a newer child; or makes duplicate unexpired appends non-idempotent.
- Expired parent L2 data remains retrievable through the semantic index, parent purge does not cascade its semantic rows, failed expired-parent child replacement can retain the old expired embedding past the next schema-ready retention run, or retention readiness remains disabled after migration until worker restart.
- A decoded candidate whose request type, draft mode or edit placement is not target-independent `new_workflow` reaches the verifier or rehydrator.
- Missing/uncertain/provider-I/O verifier or disabled serving flag can suppress the existing Planner call.
- Semantic serving/fallback/infra failure or terminal rollback records a coarse outcome outside the agreed `hit|miss|error|existing` mapping.

GraphRAG, workflow template recommendation and organization/shared semantic cache are named follow-up scopes, not JEO-8 completion substitutes.
