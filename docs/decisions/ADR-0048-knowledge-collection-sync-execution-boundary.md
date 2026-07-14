# ADR-0048: Knowledge Collection sync execution boundary

Status: Accepted
Related ADRs: [ADR-0020](ADR-0020-knowledge-mcp-incremental-sync-boundary.md), [ADR-0022](ADR-0022-incremental-hexagonal-architecture-adoption.md), [ADR-0034](ADR-0034-knowledge-delegated-administration-and-rbac-boundary.md), [ADR-0044](ADR-0044-knowledge-collection-operational-management-boundary.md)

## Context

Knowledge Collection permission에는 `sync` action과 Sync Operator(`read + sync`) bundle이
있고 domain delegation에는 `sync_manage`가 있다. Collection에는 `sync_state`도 있지만,
사용자가 KC sync를 명시적으로 요청하고 durable 상태를 확인하는 API/UI와 Celery 실행
경계는 연결되어 있지 않다.

Celery는 at-least-once delivery를 전제로 하므로 HTTP retry, 중복 click, message redelivery,
worker crash와 publish/commit gap을 함께 다뤄야 한다. 또한 Collection `sync`는 child KB
content 권한이 아니므로 status나 audit에 child identity와 source config를 노출해서는 안
된다. 현재 Workflow Engine이 실제로 재수집할 수 있는 source는 legacy DB document이며,
신규 MCP/API/source connector 구현은 MBA-265 범위 밖이다.

## Options Considered

1. Collection `sync_state`와 Celery result backend만 사용한다.
   - 장점: 새 table이 없다.
   - 단점: transaction, organization scope, child retry, partial failure, retention과 crash
     recovery의 durable source of truth가 없다.
2. Celery task ID와 autoretry만으로 중복 실행을 막는다.
   - 장점: worker 코드가 단순하다.
   - 단점: task ID는 broker dedupe가 아니며 DB commit 뒤 crash를 판별하지 못한다.
3. KC sync job/item table, idempotency key, active single-flight와 DB lease를 사용한다.
   - 장점: request, claim, target, retry, terminal 상태를 PostgreSQL constraint/transaction으로
     검증할 수 있다.
   - 단점: additive schema와 recovery worker가 필요하다.
4. Source/system-managed Collection까지 placeholder 성공으로 처리한다.
   - 장점: UI상 모든 KC가 동작하는 것처럼 보인다.
   - 단점: 실제 freshness를 갱신하지 않아 운영자에게 잘못된 성공 신호를 준다.
5. 현재 실행 가능한 Manual KC의 DB document만 지원하고 나머지는 fail-closed 한다.
   - 장점: 구현된 능력과 제품 표시가 일치한다.
   - 단점: 초기 지원 범위가 좁다.

## Decision

Option 3과 option 5를 채택한다.

### Authorization

- Sync request와 status 조회는 Organization manager, effective Collection `sync`, domain
  `sync_manage` 중 하나를 요구한다.
- Collection `manage`만으로 sync를 허용하지 않는다.
- `sync`/`sync_manage`는 child KB `read/use/write/manage` 또는 Collection `route`를 부여하지
  않는다.
- Gateway request와 Workflow worker claim에서 current authority를 각각 평가한다.
- Worker의 fresh authorization query를 concurrent revoke linearization point로 둔다. Revoke가
  query 전에 commit되면 cancel하고, query 뒤 commit되면 이미 시작한 bounded batch는
  완료하며 다음 claim부터 반영한다.

### Supported target

- Active Manual Collection의 active, non-source-managed child KB에 연결된 `SourceType.DB`
  document만 초기 sync target이다.
- Target order는 Collection item rank, item created time, KB UUID, document UUID다.
- System/source-managed Collection, source-managed child, API connector sync는 승인된 adapter가
  없는 동안 fail-closed 한다. FILE은 외부 sync 대상이 아니다.
- Target cap은 100, 한 delivery의 batch는 5, document concurrency는 1이다.
- Legacy `connections`에는 organization column이 없으므로 stored DB connection의 owner가 현재
  organization의 active member인지 worker가 검증한다. 불일치·inactive owner·지원하지 않는 DB
  type은 configuration failure로 닫고 connection/config 식별자는 외부로 투영하지 않는다.
- 문서 한 건의 source row limit은 초기 실행에서 최대 1,000으로 강제해 기존 저장 설정이 더
  크더라도 단일 job이 외부 DB와 embedding provider를 무제한 점유하지 않게 한다.
- Stored DB selection의 table/column/JOIN 값은 SQL fragment가 아니라 PostgreSQL 단일
  identifier로 인용한다. JOIN edge는 snapshot에 선택된 두 table만 참조할 수 있고 `LIMIT`은
  bounded integer로 정규화한다. 저장 metadata가 변조되었더라도 임의 expression, 추가 table,
  statement를 실행하지 않고 configuration failure로 닫는다.

### Idempotency and single-flight

- Client는 canonical UUID `Idempotency-Key`를 보낸다. DB에는 SHA-256 hash만 저장한다.
- Organization+Collection+request hash unique는 같은 request retry를 기존 job으로 결합한다.
- Queued/running job은 Collection별 PostgreSQL partial unique constraint로 하나만 허용한다.
- Celery delivery ID는 dedupe authority로 사용하지 않는다. Continuation/recovery delivery는
  broker가 각 ID를 생성하고, job status/lease가 모든 중복 판정의 execution authority다.

### Commit, dispatch, lease and retry

- Gateway는 job/items, Collection pending, requested audit를 같은 transaction에 저장하고 commit
  뒤 job UUID 하나만 task로 발행한다.
- Publish 실패는 queued job으로 남고 periodic recovery가 재발행한다.
- Task는 `acks_late`와 `reject_on_worker_lost`를 사용하되 business retry는 DB item attempt,
  next retry와 lease가 소유한다.
- Job claim 상한은 target 수의 정상 batch claim, 각 item의 최대 retry claim, stale recovery 5회를
  모두 수용하도록 target snapshot에서 계산한다. 100개 target의 초기 상한은 225이며 30분 overall
  deadline이 별도 시간 상한으로 유지된다.
- Unexpired running duplicate와 terminal redelivery는 no-op한다. Stale lease는 recovery가
  bounded retry하거나 deadline/max recovery 뒤 failed 처리한다.
- Target apply와 item success/progress는 가능한 한 같은 DB commit에 포함한다.
- KC sync와 기존 ingestion이 같은 document chunks를 교체하는 경로는 shared vector store의
  PostgreSQL transaction advisory lock으로 document 단위 직렬화한다. Lock key는 document UUID의
  namespaced digest에서 만들고 transaction commit/rollback과 함께 자동 해제한다. 모든 writer는
  advisory lock을 document/Collection/KB row lock보다 먼저 획득해 잠금 순서를 통일한다.

### Status, partial failure and retention

- Job status는 `queued`, `running`, `succeeded`, `partially_failed`, `failed`, `cancelled`다.
- 일부 success와 failed/changed target이 섞이면 `partially_failed`와 Collection `stale`, all
  failure는 `failed`, all success는 `succeeded`와 Collection `synced`다.
- User status는 범주형 progress와 allowlisted safe reason만 반환한다. Exact count와 child
  identity는 반환하지 않는다.
- User cancellation은 이번 범위에 포함하지 않는다. Permission/lifecycle invalidation은 claim
  전 system cancellation으로 처리하고 overall deadline은 30분으로 둔다.
- Terminal job/item은 기본 30일 뒤 bounded cleanup하며 canonical audit retention은 별도다.

## Rationale

PostgreSQL job/item과 single-flight는 HTTP와 Celery의 중복 전달을 한 경계에서 다룰 수 있다.
DB constraint, row lock, lease와 transaction을 사용하면 fake broker dedupe에 의존하지 않고
실제 동시성을 검증할 수 있다. Commit 뒤 publish와 recovery 조합은 worker가 아직 없는 row를
읽는 문제를 피하면서 broker 장애 뒤에도 durable request를 잃지 않는다.

지원 범위를 DB document로 제한하는 것은 임시 placeholder 성공보다 보수적이지만, 현재
코드가 실제로 제공하는 기능과 사용자에게 표시하는 freshness를 일치시킨다. Source-managed
sync는 MCP/API connector, source revision, ACL/public exposure와 content safety contract를
함께 구현해야 하므로 이 ADR에서 우회하지 않는다.

## Consequences

- `knowledge_collection_sync_jobs`와 `knowledge_collection_sync_job_items` additive table이
  추가된다.
- Gateway와 Workflow Engine에 각각 application/port/adapter/composition boundary가 생긴다.
- Celery Beat는 due/stale job recovery와 terminal retention cleanup task를 실행한다.
- Client는 polling 기반 safe status panel을 제공한다.
- Collection management projection은 권한인 `can_sync`와 현재 adapter 지원 여부인
  `sync_supported`를 분리해 UI가 unsupported source를 실행 가능하다고 표시하지 않게 한다.
- Sync Operator는 child content를 읽지 않고 운영 refresh를 요청할 수 있지만 raw child 결과를
  볼 수 없다.
- System/source-managed KC sync는 connector 구현 전까지 정책 오류로 남는다.

## Affected Official Documents

- [docs/architecture.md](../architecture.md)
- [docs/data_model.md](../data_model.md)
- [docs/glossary.md](../glossary.md)
- [docs/features/knowledge/requirements.md](../features/knowledge/requirements.md)
- [docs/features/knowledge/api_spec.md](../features/knowledge/api_spec.md)
- [docs/features/knowledge/component_spec.md](../features/knowledge/component_spec.md)
- [docs/features/knowledge/test_cases.md](../features/knowledge/test_cases.md)

## Follow-up Review Notes

- Source connector를 추가하는 PR은 stable source revision, cursor/watermark, source ACL freshness,
  public exposure와 content safety를 같은 job target contract에 추가해야 한다.
- API source ingestion을 shared port로 이관할 때 지원 target 확대를 검토한다.
- 운영 load test 뒤 target cap, batch size, lease와 retry backoff를 조정한다.
- Immediate mid-batch revoke 또는 user cancellation이 필요한 규제 요구가 생기면 cooperative
  cancellation/authorization epoch를 별도 ADR로 결정한다.
- Celery Beat가 없는 배포는 별도 dispatcher가 필요하며 queued job을 무기한 방치하면 안 된다.

## Non-Goals

- 신규 MCP/API/source connector protocol
- Live connector authorization/cache
- Source-managed public exposure primitive
- Child KB permission 자동 부여
- Workflow pre-execution direct-KB sync의 전면 교체
- User cancellation과 child-level redrive UI
- Raw connector payload/status surface
