# ADR-0075: Agent Builder Durable Intent Plan Repository

Status: Accepted

Related ADRs: [ADR-0057](ADR-0057-llm-credential-at-rest-encryption-and-rotation.md), [ADR-0063](ADR-0063-agent-builder-deterministic-intent-plan-cache.md)

## Context

ADR-0063의 Redis cache는 짧은 TTL L1 serving cache다. Redis 데이터가 소실되면 같은 안전한
Intent Plan도 다시 Planner를 호출해야 한다. Agent Builder는 raw request, graph, provider response,
credential reference 또는 과거 authorization decision을 durable cache로 보존할 수 없다.

JEO-7은 현재 L1 계약을 유지한 채, cache-safe `CachedIntentPlanV1`만 PostgreSQL에 보관하는
tenant-scoped L2를 추가한다. 이 결정은 Graph Template RAG, LLM node cache, public cache API 또는
production cohort 활성화를 포함하지 않는다.

## Decision

1. Redis는 L1으로 먼저 조회한다. L1 miss일 때만 organization-scoped, versioned HMAC lookup token으로 L2를 조회한다.
2. L2 row는 organization FK, lookup token/version, 암호화된 strict plan envelope, envelope MAC, encryption key version/algorithm, 생성·만료 시각만 가진다. raw request, graph, node/edge UUID, request/operation ID, credential reference, parameter value, permission decision은 저장하지 않는다.
3. L2 envelope는 cache 전용 Fernet keyring으로 암호화하고, Redis key/value MAC domain과 분리된 repository HMAC domain으로 lookup token과 envelope metadata/ciphertext를 결합한다. MAC, 복호화, codec 또는 현재-state revalidation 실패 row는 사용하거나 L1에 승격하지 않는다.
4. Cache-eligible Planner 결과는 외부 I/O와 request-owned transaction을 포함하지 않는 짧은 독립 transaction에서 L2에 먼저 commit한다. 그 commit이 성공한 뒤에만 L1에 저장한다. L2 write failure는 valid Planner 응답을 실패시키지 않지만 L1 write도 하지 않는다.
5. L2 row는 생성 시점부터 정확히 30일 보관한다. Read는 expiry를 연장하지 않으며, bounded background purge가 만료 row를 hard-delete한다. purge마다 canonical cache audit event를 만들지 않는다.
6. L2는 `disabled`, `write_only`, `read` mode와 strict organization UUID allowlist를 함께 만족할 때만 적용한다. 기본값은 `disabled`이고 빈 allowlist는 어떤 organization에도 L2를 적용하지 않는다. 롤아웃은 `disabled -> write_only -> read`, rollback은 역순이다.
7. L2가 disabled이거나 allowlist 밖이면 ADR-0063의 L1-only 동작을 유지한다. PostgreSQL `undefined table` 또는 `undefined column` schema-readiness 오류는 process에서 L2만 비활성화하고 L1-only 동작을 유지한다. 그 외 L2 read/query/write failure는 Planner fallback으로 열리되, 대상 cohort의 cold result는 L2 commit 성공 전 L1에 저장하지 않는다.
8. L2 hit은 기존 cache hit와 같은 현재 membership, credential/model relation, workflow/target, Catalog와 Knowledge revalidation 및 rehydration을 통과한 뒤에만 L1으로 승격한다.
9. `agent_builder_requests`에는 schema readiness가 확인된 경우에만 allowlisted `intent_cache_outcome` (`disabled|hit|miss|bypass|error`)을 기록한다. rolling deploy의 이전 schema 또는 readiness 확인 실패에서는 이 best-effort telemetry만 process lifetime 동안 생략하고 request insert, L1과 Planner 흐름은 유지한다. L1/L2 source, lookup token, envelope, plan, protected identifier와 failure detail은 response, audit, metric, trace, log에 남기지 않는다.
10. migration은 additive이며 organization cascade, organization+lookup-version+token unique index, expiry index와 downgrade guard를 제공한다. L2 record가 남아 있으면 downgrade는 거부한다.
11. Schema/keyring/mode configuration이 불완전하면 L2를 serving하지 않는다. 기존 Agent Builder Planner, permission, usage, GraphMutation/CAS와 audit 경계는 그대로 유지한다.

## Consequences

- Redis 데이터 소실 뒤에도 허용된 organization에서 안전한 L2 candidate를 재검증해 provider 호출 없이 재사용할 수 있다.
- L2는 authorization이나 graph replay source가 아니며, current request의 rehydration이 유일한 사용 경계다.
- DB-first 순서는 Redis와 PostgreSQL의 distributed transaction을 만들지 않고 partial failure에서 stale L1 promotion을 방지한다.
- 운영자는 실제 allowlist 값을 tracked file, log, audit 또는 artifact에 남기지 않는다. Production activation은 이 ADR의 범위 밖이다.

## Rejected Alternatives

- **L1과 L2 동시 또는 L1 우선 저장**: L2 commit 실패 뒤 Redis만 남아 durable-write 계약을 깨뜨린다.
- **raw request 또는 completed graph 보관**: secret·protected identifier·stale GraphMutation replay 위험을 만든다.
- **L2 read를 모든 organization에 즉시 적용**: current serving evidence 없이 blast radius를 넓힌다.
- **outbox-only 비동기 저장**: 이번 합의의 synchronous DB-first invariance와 맞지 않으며 별도 durable worker/claim 설계가 필요하다.
