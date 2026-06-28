# MVP 2: Governance 및 RAG Audit

## 목표

MVP 2는 MVP 1에서 설계한 RBAC/audit/policy 기반과 MVP 2-0의 organization membership/invitation 기반을 실제 데이터 소스와 RAG 실행 경로에 적용한다.

결과물:

```text
작동하는 워크플로우 빌더
  + 데이터 소스 권한 차단
  + data classification
  + RAG chunk lineage
  + 문서 변경/재색인 흐름
  + audit log 검색
```

## 의존 기반

| 기반 | 재사용 방식 |
| --- | --- |
| MVP 2-0 organization membership | active organization member만 knowledge base permission subject가 될 수 있다. document 접근은 knowledge base 권한과 document metadata policy로 제한한다. team membership은 organization 안의 custom team 배정으로만 사용 |
| MVP 1 permission model | knowledge base `use` 권한으로 확장. connection runtime `use`는 consuming workflow/knowledge base 권한으로 허용 |
| MVP 1 `audit_logs` | 권한 변경, policy warn/block, RAG/re-index action 저장 |
| MVP 1 policy decision | `allow/warn/block` 결과 저장 |
| Knowledge Base | 데이터 소스 권한 대상 |
| Document `content_hash` | 변경 감지 |
| Document Chunk | lineage 대상 |
| RAG search-test | 검색 결과 UI 기반 |
| LLM Node `knowledgeBases` | 실제 RAG 실행 지점 |
| DB Connector | enterprise data source 시나리오 |
| Workflow Run/Node Run | trace 연결 기준 |

## Governance 범위

MVP 2에서 실제 enforcement를 붙이는 resource:

| 대상 | 정책 |
| --- | --- |
| `knowledge_base` | active organization member 중 해당 KB의 team permission 또는 user direct grant를 받은 user만 `use` 가능 |
| `document` | PII/confidential 문서는 warn/block 가능 |
| `connection` | 독립 permission resource가 아니다. secret/manage는 제한하고 runtime `use`는 workflow/knowledge base 권한으로 확인 |
| `llm_model` | MVP 1의 model `use` 정책 유지 |
| `workflow` | `viewer` `execute` 차단 유지 |

`knowledge_base` 권한은 MVP 2-0의 organization membership 전제를 반드시 따른다. Active organization member라는 사실만으로 KB `use`가 허용되지는 않으며, active membership은 필요조건이고 `team_knowledge_permissions` 또는 `user_knowledge_permissions`가 충분조건이다.

```text
knowledge base use =
  active organization membership
  + organization manager override 또는 KB team/user permission
```

`user_knowledge_permissions`는 team에 속하지 않은 active organization member에게도 부여할 수 있다. invited, suspended, removed, non-member user는 permission row가 있더라도 KB 접근과 direct grant 대상에서 제외한다.

권한 체크 위치:

```text
Gateway API
  -> knowledge base 설정 권한
  -> audit log 조회 권한

Workflow Engine
  -> knowledge base use 권한과 document metadata policy
  -> LLM node 실행 전 knowledgeBases permission 검증
  -> policy decision 기록
```

API에서만 체크하면 실행 경로 우회 문제가 생기므로 Workflow Engine의 RAG retrieval 직전에도 검사한다.

## Data Classification

지원 classification:

| Classification | 의미 | 기본 정책 |
| --- | --- | --- |
| `public` | 공개 가능 | 일반 실행 허용 |
| `internal` | 사내 업무 데이터 | 로그인 사용자/프로젝트 범위 허용 |
| `confidential` | 민감 업무 데이터 | 권한 필요, audit 필수 |
| `pii` | 개인정보 가능성 | 경고 또는 차단 |

MVP 2에서는 자동 PII 탐지를 완성하지 않는다. 초기 방식은 사용자가 classification을 수동 지정하고, 간단한 regex 기반 PII warning 후보를 제공하며, classification이 `pii`이면 외부 모델 호출 전 warn/block한다. 모든 policy decision은 `audit_logs.audit_metadata.policy_result`에 남긴다.

classification 저장은 `knowledge_bases.classification` 또는 `documents.classification` 신규 column을 추가하지 않는다. MVP 2에서는 기존 metadata, audit metadata, trace payload convention 안에서만 저장/조회하고, DB column 기반 필터링이 필요해지면 별도 schema extension으로 분리한다.

## RAG Retrieval Trace Metadata

MVP 2에서 필요한 RAG trace 정보는 신규 `rag_retrieval_traces` table을 만들지 않고 `trace_payloads` 또는 run/node trace metadata에 저장한다.

```text
trace_payloads / trace metadata
  workflow_run_id
  node_id
  knowledge_base_id
  retrieved_chunks[]
    document_id
    chunk_id
    rank
    score
    token_count
```

이 trace는 "어떤 청크가 모델에 들어갔는가"를 설명하는 핵심 근거다. RAG 없는 LLM node는 기존처럼 동작해야 한다.

## RAG 변경 정책과 Re-index

문서 변경 감지는 기존 `documents.content_hash`를 활용한다.

초기 정책:

- hash가 바뀌면 문서 processing status를 새 enum으로 바꾸기보다 `meta_info.needs_reindex=true` 같은 metadata flag를 우선 사용한다.
- full re-index와 partial re-index 선택지를 제공한다.
- MVP 2의 partial re-index는 chunk-level incremental indexing이 아니라 변경된 문서 단위 재색인으로 제한한다.
- MVP 2는 FILE/hash 중심으로 시작한다.
- CDC와 webhook sync는 MVP 3 이후 후보로 둔다.
- re-index action을 `audit_logs`에 저장한다.

## Audit Log Search

UI와 API는 최소한 아래 필터를 제공한다.

- 기간
- actor
- audit action
- target type
- workflow
- run
- node
- deployment
- policy result
- success/failure

MVP 2에서 검색해야 하는 대표 이벤트:

- `permission.grant`
- `permission.revoke`
- `policy.warn`
- `policy.block`
- `workflow.blocked`
- `organization.invite`
- `organization.member.accept`
- `organization.member.update`
- `organization.member.remove`
- `rag.retrieve`
- `rag.reindex`

## 사용자 흐름

1. organization owner/manager가 HR knowledge base를 만든다.
2. active organization member 중 HR team permission 또는 직접 grant를 받은 user만 해당 knowledge base를 `use`할 수 있게 설정한다.
3. `builder` 권한 user가 HR knowledge base를 사용하는 RAG workflow를 만든다.
4. 권한 없는 사용자의 실행은 차단된다.
5. 권한 있는 사용자의 실행은 성공한다.
6. 실행 상세에서 검색된 document/chunk list를 본다.
7. 문서가 변경되면 `meta_info.needs_reindex=true` 같은 재색인 필요 표시가 뜬다.
8. organization owner/manager 또는 knowledge base `write` 이상 권한 user가 partial re-index를 실행한다.
9. audit log에서 권한 차단, 실행, 재색인 이벤트를 검색한다.

## 추가 개발 범위

- knowledge base team/user permission grant/revoke API/UI
- knowledge base 권한 enforcement와 document metadata policy enforcement
- DB connection secret/manage/use 분리 enforcement
- RAG retrieval trace metadata 저장
- metadata 기반 data classification
- policy decision 저장
- audit log 검색 API/UI
- re-index 상태 UI
- 수동 classification과 간단한 regex 후보 기반 PII/confidential warning/block

## 작업 순서

0. MVP 2-0 Organization Membership Foundation 확인

작업:

- `organization_memberships` migration/backfill 완료 확인
- active organization member만 team membership과 user direct permission 대상이 되는지 확인
- organization member invite/accept/remove audit event가 검색 가능한지 확인

검증:

- team에 속하지 않은 active organization member에게 knowledge base direct permission을 줄 수 있음
- organization member가 아닌 user에게 knowledge base direct permission을 줄 수 없음
- invited, suspended, removed member는 knowledge base permission row가 있어도 접근할 수 없음

1. Data Source Permission Enforcement

작업:

- knowledge base team/user permission grant/revoke 구현
- active organization membership 확인 후 knowledge base `use` 권한 체크
- document metadata policy 체크와 connection secret/manage/use 분리 구현
- LLM node 실행 전 knowledgeBases permission 검증
- 권한 실패 시 policy block + `audit_logs` row 저장

검증:

- team에 속하지 않은 active organization member에게 user direct KB `use` 권한 부여 가능
- non-member, invited, suspended, removed user에게 user direct KB 권한 부여 불가
- active membership이 없으면 team/user permission row가 있어도 RAG 실행 차단
- 권한 없는 RAG workflow 실행 차단
- 권한 있는 실행 성공

2. Data Classification

작업:

- knowledge base/document classification metadata convention 정의
- UI badge 추가
- classification 변경 `audit_logs` row 저장
- `public/internal/confidential/pii` 지원

검증:

- classification 변경/조회
- `audit_logs` row 생성

3. RAG Retrieval Trace Metadata

작업:

- retrieval 결과에서 document id, chunk id, score, rank 추출
- `trace_payloads` 또는 run/node trace metadata에 저장
- workflow run/node id와 metadata 연결
- run detail API에 trace 포함

검증:

- RAG LLM node 실행 후 chunk trace 조회
- RAG 없는 LLM node는 기존처럼 동작

4. Re-index Flow

작업:

- 기존 `content_hash` 변경 감지 표시
- processing status를 바꾸지 않고 `meta_info.needs_reindex` 같은 metadata flag 정의
- full re-index와 변경 문서 단위 partial re-index action UI
- re-index `audit_logs` row 저장

검증:

- 문서 변경 후 재색인 필요 표시
- 변경 문서 단위 partial re-index 후 metadata flag 갱신

5. Audit Log Search

작업:

- audit log list API
- filters: 기간, actor, action, target, policy result
- dashboard 또는 settings 하위 Audit 화면

검증:

- 권한 차단 이벤트 검색
- RAG retrieval/re-index 이벤트 검색

## 완료 기준

| 영역 | 완료 기준 |
| --- | --- |
| KB permission grant | active organization member만 team/user knowledge base permission subject가 될 수 있고, team에 속하지 않은 active member도 user direct grant를 받을 수 있음 |
| RBAC enforcement | active organization membership 선검증 후 knowledge base `use` 권한이 Gateway와 Workflow Engine 실행 경로에서 적용됨 |
| Fail-closed membership | invited, suspended, removed, non-member user는 knowledge base permission row가 있어도 RAG 실행과 direct grant가 차단됨 |
| RAG trace | 사용된 document/chunk/rank/score가 run detail에서 보임 |
| Data governance | classification metadata와 policy decision이 저장됨 |
| Re-index | 변경 문서에 대해 metadata 기반 재색인 필요 표시와 변경 문서 단위 re-index action이 보임 |
| Audit UI | 실행/차단/재색인/권한 변경과 organization membership 이벤트를 검색 가능 |

## Demo Script

```text
1. organization owner/manager가 HR KB 또는 document를 metadata 기반 confidential로 분류한다.
2. active organization member 중 HR team permission 또는 직접 grant를 받은 user만 use 가능하게 설정한다.
3. `builder` 권한 user가 해당 KB를 쓰는 RAG workflow를 만든다.
4. 권한 없는 사용자는 실행 차단된다.
5. HR 권한 사용자는 실행 성공한다.
6. 실행 상세에서 사용된 chunk list를 확인한다.
7. 문서를 변경하고 partial re-index를 실행한다.
8. Audit Log에서 모든 이벤트를 확인한다.
```

## 테스트 범위

- knowledge base permission enforcement
- knowledge base team/user permission grant/revoke
- active organization member without team direct grant
- non-member, invited, suspended, removed member fail-closed
- policy decision allow/warn/block
- rag trace metadata create/query
- document re-index state
- audit log filter including organization membership events
- 기존 RAG search-test 회귀 테스트

## MVP 2에서 하지 않을 것

- 전체 CDC
- OIDC/SSO
- 노드 단위 세밀 권한
- 완전 자동 PII redaction
- 컴플라이언스 리포트
