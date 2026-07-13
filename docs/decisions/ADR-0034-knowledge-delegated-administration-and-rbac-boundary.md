# ADR-0034: Knowledge 위임 관리와 KB RBAC 경계

Status: Accepted

Related ADRs: [ADR-0006](ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md), [ADR-0010](ADR-0010-resource-access-403-404-policy.md), [ADR-0014](ADR-0014-knowledge-base-document-atom-and-collection-boundary.md), [ADR-0017](ADR-0017-knowledge-integration-provisional-implementation-baseline.md), [ADR-0022](ADR-0022-incremental-hexagonal-architecture-adoption.md), [ADR-0023](ADR-0023-audit-actor-access-management-boundary.md)

## Context

Knowledge Base API에는 Team/User resource permission이 이미 있지만, 일부 KB
설정·문서·처리·삭제 경로는 `knowledge_bases.user_id`를 권한 근거로 사용한다.
이 때문에 Team에 실무 권한을 부여해도 owner가 아니면 관리할 수 없는 경로와,
owner라는 이유만으로 중앙 RBAC를 우회하는 경로가 함께 존재한다.

Organization manager가 모든 KB와 Collection을 직접 만들고 사용자별 권한을
계속 부여하는 운영 방식도 확장하기 어렵다. 반면 Knowledge 관리 위임을 KB
content 사용 권한과 합치면 카탈로그 담당자가 인사·법무 문서 원문까지 읽는
과도한 권한을 얻게 된다. 관리 plane과 content plane을 분리하면서 Team 중심
위임, resource 담당자 예외, public exposure 통제가 함께 필요하다.

## Options

1. `user_id` owner bypass를 유지하고 누락 endpoint만 보강한다.
2. 모든 Knowledge 작업을 Organization manager 전용으로 만든다.
3. owner를 귀속 정보로 전환하고, resource RBAC와 별도의 organization-scoped
   Knowledge 관리 action을 도입한다.

## Decision

선택지 3을 채택한다.

### KB resource actions

KB의 canonical action은 다음과 같다.

| action | 최소 `auth_state` | 범위 |
| --- | --- | --- |
| `read` | `viewer` | safe KB label, 설명, 상태, safe document summary |
| `use` | `operator` | RAG retrieval. Source-managed KB는 source authorization gate도 필요 |
| `write` | `builder` | 이름·설정 변경, manual document 등록·처리·preview·sync |
| `content_read` | `builder` | eligible manual original content. Source-managed content는 별도 source/display policy도 필요 |
| `manage` | `manager` | resource permission, safe catalog metadata, archive/restore |

Organization manager override와 active Team/User direct grant 중 가장 강한
additive allow를 사용한다. Source policy grant는 문서화된 `use` 경로에만
합산하고 source authorization을 우회하지 않는다. `content_read`는 별도 저장
state를 만들지 않고 `builder` 이상에 매핑하되 property-level gate로 평가한다.

### Owner migration and creation

- `knowledge_bases.user_id`는 생성자/귀속/audit attribution이다. owner bypass는
  migration 완료 후 권한 근거로 사용하지 않는다.
- 같은 organization의 active member인 legacy owner에게 user-direct `manager`
  grant를 idempotent하게 backfill한다. 조직 불일치, inactive user, membership
  부재 또는 모호한 row는 grant하지 않고 safe finding code와 bucketed count만
  남긴다.
- Active organization member는 manual KB를 만들 수 있다. KB row, 생성자의
  user-direct `manager` grant, data-change audit는 한 transaction에서 commit한다.
- KB는 Collection에 속하지 않아도 되고, 0개 이상의 Collection에 연결될 수
  있다.

### Organization-scoped Knowledge delegation

다음 additive allow table을 도입한다.

- `team_knowledge_domain_permissions`
- `user_knowledge_domain_permissions`

각 row는 organization, grantee, `permission_action`, `assigned_by`,
`assigned_at`, optional `expires_at`, non-negative `flags`를 가진다. 허용 action은
다음과 같다.

| action | 허용 | 명시적 제외 |
| --- | --- | --- |
| `catalog_manage` | private manual Collection 생성, safe catalog metadata와 private membership 관리 | KB `use`/원문, Collection `route`, public exposure |
| `permission_delegate` | KB/Collection resource permission 조회·부여·회수 | domain permission 부여, self/own-Team content access 상승 |
| `lifecycle_manage` | eligible manual KB/Collection archive·restore | hard delete, system-managed source-owned mutation |
| `sync_manage` | 승인된 sync/remediation 실행 | source ACL 우회, raw source/credential 조회 |

Organization manager만 domain permission을 부여하거나 회수할 수 있다. Domain
permission은 KB `read/use/write/content_read/manage` 또는 Collection
`read/route/manage/sync`를 암묵적으로 부여하지 않는다.

`permission_delegate`만으로 resource permission을 관리하는 actor는 자신,
자신으로 resolve되는 user, 자신이 active member인 Team에 content-plane grant를
부여할 수 없다. Organization manager는 이미 recovery authority를 가지므로 이
제한에서 제외한다. Resource-specific KB/Collection manager는 해당 resource
범위 안에서만 기존 grant를 관리할 수 있다.

### Collection and destructive operations

- Domain `catalog_manage`로 생성한 Collection은 client 입력과 무관하게 private다.
- Private Collection membership은 Collection `manage` + 대상 KB `manage`, 또는
  domain `catalog_manage`로 관리한다.
- Public Collection의 link, unlink, reorder는 visibility flag 변경과 같은 public
  exposure mutation이다. Organization manager와 명시적 acknowledgement가
  필요하며 source-managed KB public approval은 별도로 검증한다.
- Public/private visibility 전환과 KB hard delete는 V1에서 Organization manager
  전용이다. Hard delete는 명시적 acknowledgement와 retention gate를 요구한다.
- UI role bundle은 explicit action row를 transactionally 적용하는 편의 기능이다.
  Viewer=`read`, Workflow Router=`read+route`, Maintainer=`read+manage`, Sync
  Operator=`read+sync`이며 KB `use`를 만들지 않는다.
- 위임 대상 picker는 권한 변경 권한을 통과한 actor에게만 active Team/User의
  opaque id와 safe label을 반환한다. Team을 기본 선택으로 두며 raw principal,
  email, source identity는 위임 대상 응답과 감사 metadata에 포함하지 않는다.

### Resource hiding, audit, and architecture

- unknown, cross-organization, deleted 또는 completely invisible resource는
  `404 resource.hidden`; same-scope visible resource의 action 부족은
  `403 permission.denied`; list는 unauthorized row를 생략한다.
- 응답과 오류는 hidden id/name/count, raw source metadata, raw payload,
  credential을 포함하지 않는다.
- Permission, lifecycle, membership, domain grant/revoke mutation과 canonical
  audit row는 같은 transaction에서 commit한다. Audit에는 actor, organization,
  target type/id, action, 결과와 변경된 permission code 같은 safe metadata만
  허용한다.
- 신규 mutation flow는 ADR-0022의 application use case, port, SQLAlchemy adapter,
  UnitOfWork 경계를 따른다. Controller는 request/dependency/response mapping만
  담당한다.

## Consequences

장점:

- Organization manager → Knowledge 전담 Team → 개별 KB/Collection 담당자 구조를
  최소 권한으로 운영할 수 있다.
- owner-only와 resource RBAC가 섞인 경로를 하나의 object/property authorization
  계약으로 정리한다.
- 카탈로그 관리자가 문서 원문이나 RAG 사용 권한을 자동으로 얻지 않는다.
- 공개 노출과 hard delete의 위험한 권한을 조직 관리자에게 유지한다.

비용:

- additive schema, owner backfill, endpoint cutover와 client capability migration이
  필요하다.
- Domain permission과 resource permission을 UI에서 명확히 분리해야 한다.
- Source-managed original content는 approved display/raw primitive가 없으면
  manager에게도 fail-closed된다.

## Follow-up

- MBA-231은 이 ADR의 관리/RBAC/schema/API/UI cutover를 구현한다.
- MBA-232는 이 permission contract를 사용해 direct KB + selected Collection
  runtime candidate resolver를 구현한다.
- MBA-233은 LLM node graph, Builder, deployment preflight와 Workflow Engine에
  resolver를 연결한다.
