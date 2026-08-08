# Agent Builder Cache Component Specification

Status: Draft

MBA-343 cache spine의 내부 module 분리와 disabled runtime seam은
[MBA-343 component specification](../agent-builder-cache-343/component_spec.md)이 이 문서의
`intent_cache/` package 내부 소유권을 구체화한다. 전체 coordinator, Redis adapter와 rehydration의
책임 경계는 이 문서가 계속 소유한다.

## Design Goals

- Cache correctness를 자연어 의미 추론과 분리한다.
- Application domain이 Redis와 provider client 구현에 직접 결합되지 않게 한다.
- Cache hit와 miss가 structured request 이후 동일한 direct-edit 경계를 사용하게 한다.
- Cache가 protected resource authorization이나 durable workflow state를 소유하지 않게 한다.
- Cache 삭제, 장애와 version rotation이 기능 rollback 수단이 되게 한다.

## Component Boundaries

| Component | Responsibility | Must not do |
|---|---|---|
| `DeterministicIntentNormalizer` | 전체 표현 cleanup, Catalog exact-token segment projection, admission bypass와 versioned signature 생성 | phrase/semantic capability 추론, LLM 결과 수정 |
| `IntentContextFingerprinter` | safe graph/selection/Knowledge context의 canonical digest | raw graph/config 저장 |
| `IntentPlanCacheKeyBuilder` | versioned key material과 HMAC key 생성 | plaintext identity/key 노출 |
| `IntentPlanCacheEnvelopeCodec` | canonical payload와 key를 인증하고 strict value를 decode | MAC 미검증 payload 반환 |
| `IntentPlanCachePolicy` | lookup/store admission과 bypass reason 결정 | provider 호출, graph 생성 |
| `IntentPlanCachePort` | cache/lease 의미 계약 | Redis 타입 노출 |
| `RedisIntentPlanCacheAdapter` | bounded Redis get/put/lease/wait | business validation |
| `IntentPlanL2EnvelopeCodec` | repository 전용 lookup token, Fernet envelope와 independent HMAC binding | Redis envelope 재사용, raw request/graph/credential을 envelope에 포함 |
| `PostgresIntentPlanRepository` | allowlisted organization의 L2 load/save와 짧은 독립 DB transaction | authorization·GraphMutation·request replay 소유, L2 commit 전 L1 promotion 허용 |
| Agent Builder L2 retention task | 만료 semantic child를 먼저 purge한 뒤 encrypted L2 row를 bounded hard-delete하고 retry | cache plan serving, cache audit/replay record 또는 별도 semantic worker 생성 |
| `CachedIntentPlanCodec` | strict serialization, max size와 forbidden field validation | Pydantic validation 우회 |
| `CanonicalIntentTextRegistry` | provider topic/guidance의 exact ref projection, request-specific safe-summary projection descriptor와 purpose fixed rendering | fuzzy/semantic mapping, 자유 형식 template argument |
| `RequestIntentSummaryProjector` | current `full_safe_message`에서 versioned bounded `intent_summary` 생성 | provider summary 또는 request/draft 공통 문장 재사용 |
| `CachedIntentPlanRehydrator` | current context와 canonical registry에서 structured request 재구성 | 과거 UUID/handle 또는 provider text 재사용 |
| `AgentBuilderIntentCoordinator` | cache, Planner와 rehydration orchestration | GraphMutation/CAS 소유 |
| Existing Planner Adapter | provider invoke, schema parse, semantic repair와 usage | cache policy 결정 |
| Existing `AgentBuilderService` | full safe planning context DTO 생성, target resolve, Catalog materialization, validation | DTO 절단, Redis 직접 접근 |

## Dependency Direction

```text
HTTP endpoint
  -> Agent Builder composition
      -> existing auth / organization / request admission
      -> AgentBuilderIntentCoordinator
          -> application normalizer/policy/fingerprinter/rehydrator
           -> IntentPlanCachePort
               <- RedisIntentPlanCacheAdapter
           -> optional PostgresIntentPlanRepository
               <- IntentPlanL2EnvelopeCodec / SessionLocal
           -> existing Planner port
               <- provider-backed intent extractor
       -> existing structured request / GraphMutation / CAS services

Celery Beat -> Log System L2 retention task -> expired semantic children -> expired L2 rows
```

Application types는 `redis.Redis`, FastAPI Request와 SQLAlchemy model을 import하지 않는다. Composition이
현재 user/organization과 concrete adapter를 조립한다.

Cache coordinator는 기존 request admission과 cancellation/version fence 뒤에 호출한다. Cache miss의
provider invoke 직전에만 기존 usage reservation을 시작한다. Hit는 request admission과 session 직렬화를
우회하는 fast path가 아니다.

**Lifecycle amendment.** Gateway lifespan constructs the enabled concrete Redis adapter and coordinator once,
stores the boundary in FastAPI app state, and closes the owned client/pool once during shutdown. Request
composition receives that shared boundary with its current user/organization and never calls Redis client
construction. Disabled configuration constructs no adapter; initialization failure remains a safe
fail-open to the existing Planner path, and shutdown errors are contained without configuration-secret disclosure.

**Durable L2 amendment.** The coordinator reads L2 only after an L1 miss. A cache-eligible cold plan first
commits through `PostgresIntentPlanRepository`; it attempts the lease-owner L1 save only when that commit reports
`stored`. L2 is optional and fail-closed for invalid configuration or missing schema, while the existing Planner
response remains available. The Log System task is a retention executor only: every five minutes it processes at
most five 1,000-row batches, rechecks expiry at delete time, and never serves or audits cache payloads.

**Approved cross-cutting integration scope.** MBA-348 retains three minimal
user-approved integration surfaces: the `from_url` adapter's idempotent app-owned
pool close; the rehydrator's current-logical-topology validation input; and the
opt-in, non-serialized Knowledge candidate/Collection projection used only to
produce a current HMAC fingerprint and reissue handles. They do not redesign Redis
codec/single-flight or rehydrator plan contracts, alter public API/durable schema/
permission policy/GraphMutation/CAS, or retain protected identity outside the
request. Actual protected-resource consumer-boundary and production-serving
evidence remains MBA-349.

## Proposed File Ownership

| Path | Content |
|---|---|
| `apps/gateway/application/agent_builder/intent_normalization.py` | signature와 normalization policy |
| `apps/gateway/application/agent_builder/intent_cache/` | MBA-343의 `catalog_snapshot.py`, `contracts.py`, `codec.py`, `ports.py`, `disabled.py`; Catalog v3 node/capability/parameter key·input type, request-summary projection descriptor와 canonical purpose snapshot, cache DTO, strict codec, ports와 no-op 경계 |
| `apps/gateway/application/agent_builder/intent_cache_coordinator.py` | cache hit/miss/bypass, Planner, rehydration과 usage orchestration |
| `apps/gateway/services/agent_builder/intent_cache_integration.py` | request-transient planning context, safe Intent Plan projection, and rehydrator factory |
| `apps/gateway/services/agent_builder/intent_cache_knowledge.py` | current Knowledge fingerprint, semantic metadata allowlist, and candidate-handle reissue |
| `apps/gateway/services/knowledge_rag_recommendation_service.py` | cache-only request-transient current candidate/Collection projection; it remains outside API serialization |
| `apps/shared/schemas/knowledge.py` | non-serialized private response attributes for the cache-only current Knowledge projection |
| `apps/gateway/application/agent_builder/intent_cache_observability.py` | allowlisted cache metrics and safe diagnostic logging adapter |
| `apps/gateway/application/agent_builder/intent_rehydration.py` | current-context rehydration |
| `apps/gateway/application/agent_builder/intent_rehydration_registry.py` | versioned topic/guidance/purpose manifest, request-summary projection과 fixed template rendering |
| `apps/gateway/adapters/cache/agent_builder_intent_plan.py` | Redis adapter/codec boundary and app-owned client/pool close |
| `apps/gateway/adapters/cache/agent_builder_intent_plan_l2.py` | repository HMAC/Fernet envelope, organization-scoped L2 lookup/save와 schema-readiness safe-disable |
| `apps/gateway/composition/agent_builder_cache.py` | process-lifetime enabled cache construction, app-state ownership, safe close |
| `apps/gateway/composition/agent_builder.py` | request composition of the shared cache boundary and service |
| `apps/gateway/lifespan.py` | cache runtime initialization after startup and one-time shutdown close |
| `apps/gateway/services/agent_builder_service.py` | transient full safe planning context DTO와 coordinator seam |
| `apps/gateway/services/agent_builder_intent_service.py` | provider-backed extraction과 repair 유지 |
| `apps/shared/services/agent_builder_intent_plan_l2_retention.py` | expiry recheck를 포함한 bounded semantic-child pre-purge와 L2 hard-delete batch |
| `apps/log_system/tasks.py` | 5분 Beat가 발행한 L2 retention task의 bounded batch loop와 retry |

`intent_cache_coordinator.py`는 `intent_cache/`의 DTO와 port를 의존할 수 있지만 반대 방향 import는
허용하지 않는다. Redis client 타입은 adapter 밖의 application module에 노출하지 않는다.
현재 분할 구현에서는 위 responsibility boundary를 가로질러 module을 합치지 않는다. 같은 responsibility
안의 세부 helper만 합칠 수 있으며 normalization, cache adapter, provider invoke와 graph materialization
책임은 계속 분리한다. Boundary 간 파일 통합이 필요하면 현재 기능 전달 뒤 별도 refactor로 결정한다.

## Normalization Pipeline

1. 기존 secret 경계가 API에서 허용된 전체 요청을 검사하고 저장되지 않는 `full_safe_message`를 만든다.
2. Unicode NFKC, CR/LF/tab 공백화, 연속 ASCII space 축소와 trim으로 저장하지 않는 cleanup detection form을 만든다.
3. Raw message와 cleanup detection form 모두에서 secret/redaction marker와 input truncation 징후를 검사하고 closed reason으로 bypass한다. 이 검사는 deny-only이며 signature input을 추가하지 않는다.
4. Explicit parameter value와 selected target 없는 ambiguous natural-language modify를 bypass한다. 인용문 안의 Catalog parameter key/display label 뒤 non-empty value는 value 감지에만 쓰며 label canonicalization을 허용하지 않는다.
5. 인용문과 node label span을 exact token canonicalization에서 보호한다.
6. Catalog v3의 단일 lexical-token exact alias와 exact node token만 boundary-aware typed segment로 바꾼다.
   Case-insensitive canonicalization도 이 token에만 적용한다. Catalog에 없는 token은 admission을 막지 않고
   원문 literal segment로 보존한다.
7. 위치, 순서, 부정과 숫자는 변환하지 않고 원래 순서의 literal segment로 보존한다.
8. 닫히지 않은 인용문처럼 안전하게 segment화할 수 없는 입력만 `unknown_token_sequence`으로 lookup/store를
   bypass하고 partial signature를 만들지 않는다.
9. `normalizer_version`과 전체 ordered segments를 domain-separated canonical JSON으로 만들고 SHA-256 signature를 반환한다.

Normalizer는 권위 Catalog v3 JSON의 alias/node metadata를 읽고 alias 충돌을 정적 초기화에서 거부한다.
Catalog의 multi-token Planner alias, UI 설명과 Planner prompt에서 별도 cache alias를 파생하지 않는다.
번역, 일반 동의어, phrase 재작성, 조사·형태소 제거, 어순 재구성, embedding과 semantic similarity는 적용하지
않는다. 미인식 literal은 bypass 근거가 아니라 signature의 ordered segment이며, Profile과 synthetic adversarial
corpus는 같은 `normalizer_version`으로 추적한다. equality 규칙 변경은 namespace miss를 만든다.


**MBA-344 pipeline clarification.** The numbered pipeline above is the executable order: create the transient NFKC/whitespace cleanup form, then inspect it and the raw safe message before any signature/projection. The safety-gate match result is deny-only and never persisted or added as separate signature material; the required cleanup transformations still feed the later normalized typed projection. Quoted Catalog display labels are inspected only to fail closed on an attached value, never canonicalized. Static initialization rejects a node-token/alias collision unless the alias resolves to a capability declared by the same node.

## Workflow Context Fingerprint

Fingerprint projection은 다음만 포함한다.

- node type, sanitized role/label과 configuration presence
- source/target logical topology
- selected node/edge의 존재와 structural role
- workflow present/blank context
- generation mode

Position, measured size, viewport, raw node data, credential/resource reference와 parameter value는 제외한다.
Node label이 target 의미에 필요하면 plaintext를 저장하지 않고 key HMAC input의 canonical projection에만
Node 개수 상한으로 topology 일부를 버리지 않는다. 전체 logical topology는 hit 재검증에만 사용하고 cache key에는 포함하지 않는다. 전체 projection을 만들 수 없으면 cache를 우회한다.

`AgentBuilderService`는 Planner prompt용 2,000자 summary 또는 50-node projection을 재사용하지 않고
cache coordinator 전용 transient DTO를 만든다. Actor/organization scope와 명시적인 selected node/edge
identity는 HMAC material 생성에만 사용한다. Selected target identity는 non-serializable ephemeral field로
key 생성 직후 폐기하며, 그 밖의 workflow/node/edge/Knowledge resource identity, request/operation identity와
raw configuration은 DTO에 넣지 않는다.

## Cache State Model

| State | Transition |
|---|---|
| `disabled` | configuration 또는 feature flag로 Planner 직행 |
| `bypass` | normalization/admission 불가로 Planner 직행 |
| `miss` | lease admission 뒤 Planner 호출 |
| `hit_candidate` | value decode와 version 검증 진행 |
| `rehydrating` | current permission/context로 structured request 재구성 |
| `hit_valid` | 기존 structured validation으로 전달 |
| `hit_rejected` | current mismatch로 miss 전환 |
| `cache_error` | safe metric 후 miss 전환 |

이 상태는 durable session 상태가 아니며 DB에 저장하지 않는다.

Knowledge candidate fingerprint admission uses explicit current safe policy revision when present, otherwise a deterministic `derived-policy-state-v1` digest of current permission state (`effective_auth_state`, `source_acl_state`, `reason_code`, and nonnegative `freshness_epoch`). It bypasses to Planner only when neither representation can be formed. Candidate와 Collection의 safe label/name은
presentation 데이터이므로 HMAC projection에 넣지 않는다.
- Cache-specific candidate, permission, and collection metadata uses a closed semantic allowlist before the outer context HMAC. Nested protected-resource IDs and safe label/name/description presentation values are omitted; adding a semantic field requires an explicit projection and contract test.

- For cache-enabled eligible requests, the coordinator checks the request cancellation/version fence before normalizer/key lookup, after load before direct-hit rehydration, before every Planner entry (including normalizer bypass and cache I/O, lease, or follower-wait fail-open fallback), and before follower value use. `canceled` or `stale` aborts cache work rather than using a value or starting Planner work.

## Single-Flight

- Lease key는 cache value key와 분리된 namespace를 사용한다.
- Owner token은 random request-local value이며 log하지 않는다.
- `SET NX EX`와 owner-token 비교 release를 사용한다.
- Owner는 provider 호출 전 lease를 얻고 valid plan put 뒤 release한다.
- Follower는 configured wait와 현재 request의 남은 deadline 중 짧은 시간까지 value만 조회하며 owner의
  provider response를 직접 공유하지 않는다. 초기 configured wait는 기본 45초, 최대 60초다.
- Wait는 짧은 bounded slice로 나누고 slice 사이와 value 사용 직전에 cancellation/request version fence를
  확인한다. Cancellation/version change와 value 도착이 경합하면 cancellation/version change가 우선한다.
- Follower wait는 process-wide non-blocking slot을 사용한다. 기본 8개, 허용 범위 1~64개이며 상한을 넘은
  요청은 `overflow`로 기록하고 기다리지 않은 채 기존 Planner를 호출한다.
- Slot은 timeout, cancellation, version change, Redis error와 예외를 포함한 모든 종료 경로에서 반환한다.
- Owner는 valid plan 저장, clarification, unsupported, provider failure와 store-ineligible 결과를 포함한 모든
  정상 terminal path에서 lease를 해제한다. Value가 없는 정상 종료는 owner token을 비교해 관찰된 lease
  generation과 묶인 짧은 coordination signal인 `owner_completed_without_value` 기록과 release를 원자적으로
  수행한다. Follower는 자신이 관찰한 generation과 일치할 때만 즉시 Planner로 진행한다. 이 신호는 cache
  value나 negative result cache가 아니며 이전 generation 신호는 새 lease에 적용하지 않는다.
- Owner가 wait 안에 value를 저장한 경우에만 provider 단일 호출을 보장한다. Timeout 뒤 follower는
  Planner를 호출할 수 있다. Lease가 correctness lock은 아니므로 요청 실패나 무한 대기를 만들지 않는다.
- Provider 호출과 follower wait 동안 DB transaction/row lock을 유지하지 않는다.

- A request-bound transaction guard ends only a clean service read transaction before every Redis I/O: lookup, lease, follower wait, and save/completion/release after current-context rehydration. If that boundary cannot be established, subsequent Redis I/O is skipped and the existing Planner or already canonical result path is preserved. An unavailable initial guard invokes the existing Planner once only; a Planner exception propagates without a cache-triggered retry.
  If the guard becomes unavailable after owner lease acquisition, completion and release remain skipped under the dirty Session; that lease expires via TTL and followers use their bounded fallback rather than treating it as a no-value signal.

## Hit Rehydration

Cache admission을 통과한 miss도 valid extraction을 `CachedIntentPlan`으로 projection한 직후 이 rehydration을
거친다. 최초 miss와 이후 hit는 같은 canonical structured request를 downstream에 전달한다. LLM extraction의
자유 형식 summary/guidance를 cache-eligible miss에서만 직접 사용하는 별도 경로를 두지 않는다.
Store-ineligible result는 기존 non-cache 경로이므로 이 제한의 대상이 아니다.

`intent_summary`는 plan이나 request/draft 공통 template에서 만들지 않는다. Rehydrator는 매 요청의 transient
`IntentPlanningContext.full_safe_message`를 `summary.current_safe_message.v1` descriptor에 따라 whitespace
collapse, fail-closed redaction과 240-code-point 상한으로 projection한다. Empty 또는 redaction marker가 남으면
rehydration을 fail-closed한다. Cache-eligible cold miss에서는 provider summary 대신 이 projection을 사용하므로
같은 current request의 miss/hit는 같고, 같은 logical plan을 만든 서로 다른 safe request는 각 request-specific
summary를 유지한다. Summary projection은 cache value, diagnostic, metric과 audit에 문자열을 남기지 않는다.

Projection은 provider의 모든 `knowledge_topics`와 `parameter_guidance_hints`를 versioned registry의 closed
reference로 표현할 수 있을 때만 cache-safe plan을 만든다. Topic은 순서 있는 `topic_ref`, guidance는
logical step ref, Catalog `parameter_key`와 reason/input-guidance template ref로 투영한다. Exact alias/template
match만 허용하며 하나라도 매핑되지 않으면 전체 result를 store-ineligible로 분류한다. 이 경우 coordinator는
원본 extraction을 기존 non-cache downstream에 전달하고 put하지 않는다. 이는 projection 성공 뒤의
cold-miss rehydration failure와 구분한다.

Warm hit의 rehydration failure는 해당 hit를 버리고 Planner를 최대 한 번 호출하는 miss로 전환한다.
Cold miss의 rehydration failure는 이미 provider attempt가 발생한 terminal failure다. 원본 extraction을
우회 사용하거나 같은 요청에서 Planner cycle을 다시 시작하지 않으며 cache put, GraphMutation과 save를
수행하지 않는다. 이미 발생한 provider/repair usage는 그대로 기록한다.

### Planner Runtime

Cache hit도 active organization membership, credential status, model status, verified relation과 use permission을
검사한다. Cache가 이전 authorization 결과를 저장하지 않는다. 검증 실패는 기존 permission/runtime error로
닫고 다른 model의 cached plan을 자동 사용하지 않는다.

### Target

Existing `AgentBuilderService` target resolver가 current selected node/edge identity를 server-loaded graph의
logical ref에 bind한다. Rehydrator는 target kind에 맞는 current node/edge logical ref membership을 다시
확인한다. Binding이 유일하지 않거나 membership이 없으면 hit를 버리고 Planner 또는 clarification 경계로
진행한다. Cache plan이나 rehydrated output 안에 target UUID를 넣지 않는다.

### Knowledge

Cache에는 closed requirement, 순서 있는 `topic_ref`와 placement만 둔다. Existing current candidate resolver가
각 requirement별 Collection/KB 권한, lifecycle, readiness와 score를 다시 계산하고 request-current candidate
handle과 resolution ID를 발급한다. Rehydrator는 requirement ref와 current resolution의 순서가 정확히 일치할
때만 registry의 canonical `query_topics`와 해당 candidate handle을 structured request에 bind한다. Selection handle
발급과 선택 materialization은 기존 downstream Knowledge selection 경계가 소유하며, cache 당시 추천 순서나
선택을 자동 복원하지 않는다.

### Parameter Guidance

Provider free-form guidance never enters a cache value or a cache-eligible structured response unchanged. After secret screening and Catalog step/key validation, the registry preserves the existing Slack-channel-specific pair only when it is exact; every other safe guidance hint is deterministically rewritten to the closed `guidance.reason.configuration_required.v1` / `guidance.input.provide_parameter_value.v1` pair. The rendered input mentions only the allowlisted Catalog parameter key. The same rendered pair is projected on a cold miss and rehydrated on a warm hit, so the two paths have identical structured guidance. Invalid Catalog members and secret-like guidance remain discarded before projection.

Cache에는 logical step ref, Catalog `parameter_key`, `reason_template_ref`와
`input_guidance_template_ref`만 둔다. Rehydrator는 현재 logical step을 bind하고 Catalog parameter 및
template input-type applicability를 검증한 뒤 registry의 고정 template을 렌더링한다. Template에는 현재
Catalog의 allowlisted key, safe label과 input type만 주입할 수 있고 자유 형식 argument는 없다. Unknown ref,
registry version mismatch와 Catalog incompatibility를 fallback text로 보정하지 않는다.

Registry module은 `topic.<slug>.v1`, `guidance.reason.<slug>.v1`, `guidance.input.<slug>.v1` namespace와
strict manifest를 소유한다. 같은 version은 `summary.current_safe_message.v1` projection descriptor와
capability별 step purpose의 exact table도 소유한다. Closed ref enum, summary projection descriptor와 purpose
contract snapshot은 `intent_cache/` package가 소유하고 codec가 unknown ref를 거부한다.
Startup/static validation은 enum 대비 누락·초과 ref, ref/alias/canonical text 중복, alias의 다중 ref 매핑,
지원하지 않는 placeholder와 빈 input-type applicability를 거부한다. Manifest 또는 enum 변경은
`canonical_text_registry_version`과 regression fixture를 함께 변경한다.

### Graph

현재 Catalog template으로 node와 edge를 새로 만들고 전체 graph를 검증한다. Cache hit는 GraphMutation
operation ID, base hash, expected result hash와 updated_at을 현재 요청에서 새로 계산한다. 이후 저장과
acknowledgement는 miss 경로와 같다.

## Payload Safety

Codec는 allowlist schema 외 field를 거부한다. Serialization 전과 decode 후 다음 방어를 적용한다.

- maximum depth/list length/string length
- maximum encoded bytes
- forbidden key pattern for token, secret, credential, URL/path와 raw payload
- request/session/draft ID와 raw audit payload/metadata 원문 금지
- UUID-like protected identity가 허용 field에 들어오지 않는지 검사
- deterministic canonical JSON serialization
- final Redis key digest와 canonical payload를 domain-separated HMAC으로 묶은 authenticated envelope
- constant-time MAC comparison before plan use

Forbidden payload는 cache에 쓰지 않고 safe reason metric만 기록한다.

## Observability

Metric cardinality를 제한하기 위해 user, organization, workflow, model ID와 key digest를 label로 사용하지 않는다.
허용 label은 outcome, reason code, schema/normalizer version, latency bucket과 single-flight role이다.
운영 지표는 hit ratio, bypass ratio, error ratio, lookup latency, avoided provider attempts와 single-flight contention이다.
Single-flight role은 `owner|follower|overflow|none`이고 overflow reason은
`waiter_capacity_exceeded`다. Process/request/cache key identity는 label에 사용하지 않는다.

Cache hit는 비용 0인 LLM usage row를 만들지 않는다. Provider가 호출된 miss/repair만 기존 usage recorder가
기록한다. Workflow mutation audit은 hit 여부와 무관하게 기존 경계에서 남는다.
PostgreSQL audit는 Redis cache value의 durable copy나 replay source가 아니다. Redis data loss는 cold miss와
Planner로 복구하며 audit에는 allowlisted outcome/reason/latency만 남긴다.

## Deployment and Rollback

1. Cache disabled 상태로 코드와 configuration validation을 배포한다.
2. Development/test에서 deterministic key와 payload safety test를 통과한다.
3. 관찰 모드가 필요하면 lookup 결과를 serving하지 않고 eligibility/miss metric만 확인한다.
4. 작은 TTL로 serving을 활성화하고 hit rejection과 provider call reduction을 확인한다.
5. 문제 발생 시 feature flag를 끄거나 namespace version을 올린다.

Redis flush, TTL expiry와 HMAC rotation은 DB migration을 요구하지 않는다. Cache disabled 상태가 기능의
정상 rollback 경로다.

Cache serving is requested by default, but it never falls back to Celery broker/result Redis. Missing or invalid cache-specific configuration disables only cache. `scripts/dev-local.ps1` supplies explicit development cache configuration with a cache-only Redis DB, ephemeral HMAC key, and version, so ordinary local Agent Builder requests begin cache-on. A direct `development`, `test`, or unset-environment Gateway without complete configuration remains cache-disabled. Production/staging serving still requires a dedicated Redis URL, HMAC key/version, valid bounded configuration, and explicit production-ready attestation. Runtime evaluates only that attestation and configuration; operators set it after external validation.

Cache 구현은 전용 URL 지원과 증거가 없을 때 cache를 끄는 configuration gate까지만 포함한다. 전용 instance,
Helm/Kubernetes secret과 URL wiring, capacity/eviction, failure/network test, monitoring/rollback과 staged rollout은
별도 후속 운영 이슈다. Adapter는 자기 key의 direct get/set/delete만 사용하고 broad scan/flush를 하지 않는다.
후속 운영 작업의 진행 여부는 cache 코드·필수 검증 완료와 분리한다. 운영 증거가 없으면 attestation을 설정하지
않아야 하며 production/staging serving은 비활성이다.

HMAC key와 Redis URL은 기존 secret injection 경계를 사용하며 configuration repr, startup error, log,
trace와 audit에 원문을 노출하지 않는다. Key version rotation은 dual-read 없이 namespace miss로 처리한다.

## PRD and Core Document Impact

사용자 기능, API와 workflow 결과를 바꾸지 않는 내부 최적화이므로 PRD 요구사항을 추가하지 않는다.
전체 architecture에는 Gateway 내부 cache component와 Redis의 비권위적 역할을 추가하고 glossary에 용어를
등록한다. 구현이 사용자에게 cache 상태나 제어 UI를 노출하게 된다면 별도 제품 결정을 먼저 요구한다.

## Internal Latency Benchmark Boundary

Latency benchmark는 제품 API나 cache diagnostic UI를 추가하지 않는 내부 evaluation 도구다.

- Planning timer는 safe request/context 준비 뒤 cache coordinator 진입부터 canonical structured request
  반환까지 측정한다.
- End-to-end timer는 기존 Agent Builder message API 제출 직전부터 terminal response와 canonical
  reconciliation 완료까지 측정한다.
- Raw LLM extractor를 직접 호출하는 기존 intent accuracy benchmark는 cache coordinator를 우회하므로
  deterministic cache latency 근거로 사용하지 않는다.
- Live collector는 DB에 등록된 permission-aware credential/model selection을 사용하고 코드나 report에
  API token을 받지 않는다.
- 같은 paired run은 graph mutation의 영향을 제거하기 위해 동일한 초기 graph snapshot 또는 동등한
  fresh workflow에서 실행한다.
- Report generator는 회차별 `runs.csv`, vector graph와 JSON/CSV/Markdown summary를 생성한다.
- Benchmark row의 cache outcome은 `disabled|hit|miss|bypass|error`이며 런타임 diagnostic outcome과 별도다.
- `disabled`는 cache-off baseline row에만 허용하고 cache-on row는 실제 `hit|miss|bypass|error`를 기록한다.
- Exploratory 실행은 ignored path에 두고, PPT/README에서 인용한 최종 safe bundle은
  `docs/features/agent-builder-cache/benchmarks/<benchmark-id>/`에 Git으로 고정한다. Report row에는
  prompt 대신 case ID를 사용한다.
- Bundle `README.md`는 핵심 요약과 회차별 data, graph, JSON/CSV summary의 상세 상대 경로를 모두 기록한다.
- 최종 summary는 측정 warm-hit/cold-miss mean에서 hit rate 25%, 50%, 75%의 planning/end-to-end 예상값을
  계산하고 `modeled_estimate`로 표시한다. 이 모델링 계산 자체는 provider를 호출하지 않는다.

의미가 비슷하다는 이유만으로 같은 plan을 기대하는 dataset은 후속 Graph RAG 이슈가 소유한다.
이 benchmark에서는 승인된 deterministic alias만 warm normalization hit로 측정하며 semantic-only 문장은
bypass/negative control로만 남긴다.

### Normalization v2 amendment

The normalization pipeline no longer rejects a request because a word is absent from a fixed vocabulary. After deny-only safety checks, it emits an ordered projection of the entire normalized request: Catalog-owned exact aliases are replaced with their canonical references and every other token is retained as a literal. Thus any safe natural-language request reaches the existing Redis lookup; semantic equivalence beyond the documented NFKC, whitespace, and Catalog exact-alias rules remains out of scope.

## JEO-8 Private Dense Semantic Cache

This section describes the Accepted, default-disabled JEO-8 implementation. It does not change the Redis/L2 exact-cache order or enable a live production provider call. The semantic index is a private candidate-assist store, not a GraphRAG corpus, template recommender, cache replay store, public API or Client surface.

### Additional component boundaries

| Component | Responsibility | Must not do |
|---|---|---|
| `SemanticQueryProjectionV1` | carry only a non-truncated, at-most-240-code-point `summary.current_safe_message.v1` redaction output and its version for one owner execution | accept `full_safe_message` directly, return a first-240 slice of longer cleaned text, serialize, log or survive the request |
| `IntentPlanL2SaveResult` / `IntentPlanL2StoredReceipt` | distinguish L2 `stored|unavailable` and carry the same-transaction actual parent ID, timezone-aware expiry and write kind only for `stored` | alter Redis `IntentPlanSaveResult`, serialize/observe a receipt, accept guessed ID/current-time expiry or allow contradictory status/receipt/reason |
| `SemanticExternalCallBinding` | carry one opaque request-local `query_embedding|semantic_verification` execution/usage binding from admission to exactly the matching provider port | serialize, log, persist, expose its execution reference or reuse one purpose as the other |
| `SemanticExternalCallAdmissionPort` | after a separately approved Agent Builder `query_embedding` authority exists, authorize the current actor/organization's capability/profile, model/credential lifecycle and durable usage attribution in a short independent Session and return a purpose-bound binding only for `admitted` | reuse deployment/node-bound capability for Agent Builder, read an environment credential directly, retain permission identity, return a binding for `denied|unavailable`, or hold the service Session while resolving authority |
| `SemanticEmbeddingProviderPort` | embed only a transient `SemanticQueryProjectionV1` with its admitted `query_embedding` binding | retain raw input, accept full message/normalizer internals, call without/mismatch a binding, choose a production model/default threshold, expose provider payload |
| `SemanticIntentPlanIndexPort` | personal scope/version/expiry-filtered pgvector top-k lookup and best-effort index append | return cross-user/organization rows, decrypt/serve a plan without L2 codec |
| `SemanticCandidateVerifierPort` | return a closed `verified|rejected|uncertain|unavailable|error` decision for an in-memory candidate and declare whether it is provider-call-free | infer authorization, persist a decision, turn similarity into equality or enable Planner-free serving from a provider-backed verifier |
| `PostgresSemanticIntentPlanIndexAdapter` | join semantic metadata to its L2 parent, apply SQL predicates before vector ordering, own a short independent session | store request text, plan/envelope duplicate, graph or protected identity in observability |
| `SemanticCachePolicy` | distinguish assist from Planner-free serving and decide safe fallback | bypass exact L1/L2 order or permit serving without verifier/rehydration |

The dependency direction becomes:

```text
AgentBuilderIntentCacheCoordinator
  -> Redis L1 exact port
  -> optional Postgres L2 exact repository
  -> optional SemanticCachePolicy
       -> SemanticExternalCallAdmissionPort
       -> SemanticEmbeddingProviderPort
       -> SemanticIntentPlanIndexPort <- PostgresSemanticIntentPlanIndexAdapter (pgvector + short Session)
       -> SemanticCandidateVerifierPort
  -> existing CachedIntentPlanRehydrator
  -> existing Planner port
```

Composition injects only enabled, validated semantic ports. JEO-8 unit tests may inject fakes, but production composition has no live embedding/provider-backed-verifier adapter until a separately approved Agent Builder `query_embedding` capability/profile and durable usage binding exist. Application modules continue to depend on ports and strict DTOs rather than PostgreSQL, pgvector or provider-client types. The semantic adapter may reuse JEO-7 `IntentPlanL2EnvelopeCodec` to validate/decrypt the joined parent envelope, but it may not duplicate or redesign the parent L2 row.

### Exact-first and semantic flow

1. Existing request admission, cancellation/version fence, safe normalization and HMAC exact-key construction run unchanged.
2. Redis L1 exact hit rehydrates immediately; it does not create an embedding, vector query or verifier decision.
3. Only an L1 miss reads JEO-7 L2. A valid L2 hit rehydrates and may promote the existing L1 entry; it does not create an embedding, vector query or verifier decision. Only an explicit L2 `status=miss` is semantic-eligible. L2 `None|invalid|unavailable`, disabled, `write_only`, allowlist-out and schema-unready proceed to the existing Planner without any semantic I/O or append.
4. A usable L1/L2 double miss first acquires the existing JEO-7 single-flight lease. Only its owner reaches semantic policy; a follower performs no embedding, vector lookup, verifier or candidate rehydration and keeps the existing follower contract.
5. The owner checks semantic eligibility before projection. `selected_target` presence or modify/replace request makes the request semantic-ineligible: semantic provider/repository/verifier/index calls are all zero and the owner enters the existing Planner path. Exact L1/L2 and Planner behavior remain unchanged.
6. An eligible owner builds transient `SemanticQueryProjectionV1` only by combining current normalizer eligibility with `summary.current_safe_message.v1`. Whitespace/redaction-cleaned output of exactly 240 code points is allowed; longer output is semantic-ineligible and is not sliced for embedding or verification. Missing, over-limit, redacted or version-mismatched projection enters Planner with `miss` and without embedding/vector/verifier/index I/O. `full_safe_message` and normalizer intermediate text never cross the embedding port.
7. Before every semantic external/repository I/O, the request-bound guard ends the clean service read transaction. A future live adapter first uses `SemanticExternalCallAdmissionPort` in a separate short Session to validate an approved Agent Builder `query_embedding` capability/profile, current actor/organization, model/credential `use`, lifecycle and durable usage attribution. `admitted` must return an opaque non-serialized binding whose purpose matches `query_embedding` or `semantic_verification`; `denied|unavailable` cannot return one. A provider-backed verifier obtains a separate verification admission/binding and cannot reuse the embedding binding. JEO-8 production composition omits those adapters until the authority exists.
8. The embedding provider receives only the transient projection and matching `query_embedding` binding. The index adapter binds organization and user scope, generation mode, `semantic_query_projection_version`, embedding profile/model version, planner/catalog/normalizer and rehydration contract versions, and both index/parent expiry predicates in SQL before `ORDER BY` vector distance and `LIMIT top_k`.
9. A candidate is not a hit. After strict L2 envelope decode and before either verifier or rehydrator, the coordinator requires `request_type=new_workflow`, `draft_mode=new_workflow` and `edit_placement=null`. It discards an ineligible candidate without calling those ports, proceeds in rank order to the next bounded candidate and enters Planner when none remain. An eligible candidate still requires a closed verifier decision and the same current rehydrator used by exact L2. Model/credential use permission, target-independent workflow context, Catalog validation, Knowledge/Collection permission·lifecycle·readiness and current graph materialization remain authoritative.
10. `semantic_candidate_assist` returns `PlannerRequired` regardless of candidate outcome. `planner_free_semantic_serving` may return a rehydrated result only when its independently enabled flag and a provider-call-free verifier produce `verified`; all other normal paths call the existing Planner once. The coordinator rechecks cancellation/request-version after admission, embedding, vector lookup and verifier, and again before candidate use or Planner fallback. A canceled/stale request performs no further Planner/provider or cache write. Candidate rehydration may open only a clean service read transaction; the guard must close it before serving or Planner. If it cannot, the request ends with a bounded transaction-boundary error rather than waiting on a provider or repository while holding the connection. Planner-free serving does not promise a provider-call-free request because the query embedding may still use an admitted provider call with durable usage attribution. A serving result attempts `save_if_lease_owner` for the current exact L1 key before response; a failed promotion does not invalidate the verified owner response but completes the lease without a follower value.
11. After a Planner result projects to `CachedIntentPlanV1`, the existing JEO-7 repository commits L2 first and returns strict `IntentPlanL2SaveResult(status=stored)` with a non-serialized `IntentPlanL2StoredReceipt` from the same short independent transaction. The repository locks an existing unique-key row with `SELECT ... FOR UPDATE`; unexpired rows update only the envelope and preserve expiry, while expired rows update envelope/created/expiry. A missing row uses `INSERT ... ON CONFLICT DO NOTHING RETURNING`; only a concurrent insert loser performs one same-transaction locked read. The receipt contains the DB-confirmed actual parent ID, timezone-aware immutable expiry and `inserted|unexpired_conflict|expired_replacement`, never a guessed ID, application-clock substitute or post-commit re-read. Existing Redis `IntentPlanSaveResult` remains unchanged. A semantic append is permitted only when that result, receipt and the already-created in-memory embedding all exist; Planner completion never starts a new embedding call. The append SQL fences on current `IntentPlanningContext.organization_id` plus the receipt parent ID/expiry. `inserted|unexpired_conflict` inserts a missing child and does nothing on existing conflict. `expired_replacement` inserts when retention already removed the child, otherwise updates only an older child. Parent expiry mismatch, same/newer child or late receipt is zero-write. Semantic-only missing-table/column readiness errors disable semantic lookup/append without undoing L2, L1 promotion or the Planner result.

### Semantic index shape and lifecycle

The additive model `AgentBuilderIntentPlanSemanticCacheEntry` has no request text or plan payload. It contains `organization_id`, `user_id`, generation mode, `semantic_query_projection_version`, embedding profile/model version, planner/catalog/normalizer and required rehydration contract versions, `safe_query_embedding`, `intent_plan_record_id`, `created_at` and `expires_at`.

- `organization_id + intent_plan_record_id` references the corresponding L2 organization/id candidate key, so an index row cannot point at another tenant's L2 record. A parent/profile/projection/contract-version unique constraint makes inserted/unexpired appends idempotent; expired-parent replacement uses an expiry-fenced conditional update and is not a similarity or permission assertion.
- The index has organization/user/version/expiry filtering indexes; the concrete pgvector index/operator class is profile/dimension compatible deployment configuration, not a hard-coded production model or threshold.
- The L2 parent is the sole plan authority and supplies the child's intended immutable expiry. Index `expires_at` is copied from the same-transaction receipt, is never extended for an unexpired parent, is conditionally replaced with the new immutable expiry when the L2 parent is replaced after expiry and is checked together with parent expiry on reads. The existing L2 retention task first hard-deletes expired semantic children in a savepoint or separate short transaction with a delete-time expiry recheck, then deletes expired parents; parent `ON DELETE CASCADE` removes any remaining child. Child `42P01|42703` rolls back only that step, does not set a process-lifetime flag and does not stop parent purge. The same worker re-probes on the next Beat. Child and parent each use the validated limit, and `batch_full` remains true when either count reaches it so the existing maximum-five-batch loop can drain both. If best-effort replacement fails after an expired parent is renewed in place, the next schema-ready retention run removes the old expired embedding without deleting the renewed parent.
- Migration downgrade first refuses while semantic rows exist, then removes the semantic table and the parent composite candidate key. JEO-7's parent-table downgrade guard remains unchanged.

### Payload, transaction and observability constraints

`SemanticQueryProjectionV1` text and `safe_query_embedding` are derived sensitive data. Neither live value is emitted to a diagnostic, metric, audit, trace, exception message or captured production fixture; unit tests use only synthetic vectors without provider payload or user provenance. The same prohibition applies to raw/full/normalized text, vector score, L2 record identity, graph/node/edge identity, credential/Knowledge/Connection identity, explicit parameter value, permission decision and provider payload. Existing `intent_cache_outcome` remains coarse: Planner-free semantic serving is `hit`, normal semantic fallback is `miss`, semantic infrastructure/readiness fallback is `error`, and a semantic flow not started retains the exact-cache outcome. Terminal failure restores the selected allowlisted outcome without recording its source.

The request-owned service Session may not remain open while waiting for the embedding provider, Planner provider, Redis or either independent repository session. A semantic guard failure is sticky for the request: retained projection/embedding cannot authorize later append, and an uncloseable post-rehydration transaction ends before Planner/provider/cache writes. A future external semantic provider adapter is preceded by approved Agent Builder capability/profile, current model/credential `use` and lifecycle admission in its own short Session; only the opaque purpose-bound binding crosses into the provider port and it carries no observable raw credential or permission decision. No semantic retry, outbox, background verifier, audit event or new retention task is added. The existing L2 retention task is extended with per-run recoverable child-expiry purge, while current-parent receipt fencing owns replacement concurrency.

### Rollout boundary

Both semantic flags default to disabled. Tests may inject fake ports, but production has no live embedding/provider-backed-verifier composition until a separately approved Agent Builder `query_embedding` capability/profile and durable usage binding exist. `semantic_candidate_assist` then needs validated authority, embedding profile, repository and bounded top-k configuration. `planner_free_semantic_serving` additionally needs an explicit provider-call-free verifier and current rehydration evidence; its query embedding may still be an admitted provider call. Production values for embedding provider/model, dimension, top-k and threshold are deployment configuration decisions; this specification intentionally supplies no defaults. GraphRAG, workflow-template recommendation and shared semantic retrieval remain separately scoped follow-up work.
