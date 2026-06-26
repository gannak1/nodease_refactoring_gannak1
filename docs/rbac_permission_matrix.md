# RBAC Permission Matrix

## 작성 기준

이 문서는 현재 RBAC 구조를 기준으로 권한 매트릭스를 정의한다.

현재 구조의 핵심 전제는 다음과 같다.

- User에게 직접 리소스 권한을 주지 않는다.
- User는 `team_memberships`를 통해 Team에 들어간다.
- Team은 Organization 안의 role, group, tag 역할을 한다.
- 리소스 권한은 Team 단위로 부여한다.
- 리소스별 권한 단계는 `auth_state`로 저장한다.
- Organization membership은 별도 테이블이 아니라 TeamMembership으로 간접 표현한다.

관련 문서:

- `docs/rbac_relationships.md`
- `docs/team_permission_db_design.md`
- `docs/team_workspace_plan.md`

## 권한 판정 원칙

### 기본 판정 흐름

```text
1. 요청 User를 식별한다.
2. 요청 Organization context를 결정한다.
3. User가 해당 Organization에서 속한 Team 목록을 조회한다.
4. 요청 리소스에 연결된 Team 권한 row를 조회한다.
5. User의 Team 목록과 리소스 권한 Team 목록의 교집합을 찾는다.
6. 교집합 Team 중 active Team만 인정한다.
7. 권한 row의 auth_state가 요청 action의 required_auth_state 이상인지 확인한다.
8. 리소스 Organization이 요청 Organization 범위 안에 있는지 확인한다.
```

### 여러 Team에 속한 경우

User가 여러 Team에 속하고, 각 Team이 같은 리소스에 다른 권한을 가지면 가장 높은 `auth_state`를 사용한다.

예시:

```text
User A
  -> Team viewer: workflow_1 read
  -> Team developer: workflow_1 write

최종 권한: write
```

### 권한 row가 없는 경우

리소스에 대해 User가 속한 Team의 권한 row가 없으면 `none`으로 본다.

```text
권한 row 없음 = none = 접근 불가
```

### deny 정책

현재 구조에는 명시적 deny가 없다.

따라서 다음 정책을 사용한다.

```text
allow만 저장한다.
deny가 필요하면 Team에서 User를 제거하거나 auth_state를 none으로 낮춘다.
```

명시적 deny가 필요해지면 별도 `effect = allow | deny` 컬럼 또는 deny 테이블이 필요하다.

## Auth State 단계

`auth_state`는 문자열로 저장하되, 비교는 서비스 코드에서 우선순위로 처리한다.

| 단계 | 점수 | 의미 |
| --- | ---: | --- |
| `none` | 0 | 접근 없음 |
| `read` | 1 | 조회 가능 |
| `execute` | 2 | 실행 가능 |
| `write` | 3 | 생성/수정 가능 |
| `manage` | 4 | 권한 부여, 연결, 설정 관리 가능 |
| `admin` | 5 | 해당 리소스 범위의 최고 권한 |

주의:

- `admin`은 전역 시스템 관리자 권한이 아니다.
- `admin`은 특정 리소스 또는 Organization context 안에서의 최고 권한이다.
- `execute`는 `read`보다 높은 단계로 둔다. 실행은 조회보다 더 큰 영향을 줄 수 있기 때문이다.

## Team 템플릿

현재 DB에는 고정 Role 테이블이 없으므로, 다음 Team 이름을 기본 role template으로 사용한다.

| Team | 용도 | 설명 |
| --- | --- | --- |
| `owner` | 조직 소유자 | Organization 삭제, 소유권 이전, 최고 관리자 역할 |
| `admin` | 조직 관리자 | 대부분의 리소스와 Team을 관리하지만 소유권 이전/삭제는 제외 |
| `developer` | 제작자 | Workflow, KnowledgeBase를 만들고 수정하는 역할 |
| `operator` | 운영자 | Workflow 실행, 배포 운영, 실행 로그 확인 역할 |
| `viewer` | 조회자 | 리소스 조회만 가능한 역할 |
| `auditor` | 감사자 | Audit, trace, log 조회 중심 역할 |
| `member` | 기본 멤버 | Organization membership을 표현하는 기본 Team |

필수 정책:

```text
Organization 생성 시 member Team을 자동 생성한다.
Organization에 User를 추가하면 member TeamMembership을 자동 생성한다.
```

선택 정책:

```text
Organization 생성자를 owner Team에 자동 추가한다.
owner Team을 단일 소유자로 쓰려면 owner TeamMembership을 1개로 제한한다.
GitHub식 다중 Owner를 허용하려면 owner TeamMembership을 여러 개 허용한다.
```

## Team별 기본 권한 매트릭스

이 표는 Organization 생성 시 기본 Team에 권장할 기본 권한이다. 실제 권한은 리소스별 권한 row로 저장한다.

| Team | Organization | Team 관리 | Workflow | KnowledgeBase | LLM Credential | Audit |
| --- | --- | --- | --- | --- | --- | --- |
| `owner` | `admin` | `admin` | `admin` | `admin` | `admin` | `admin` |
| `admin` | `manage` | `manage` | `manage` | `manage` | `manage` | `manage` |
| `developer` | `read` | `read` | `write` | `write` | `execute` | `none` |
| `operator` | `read` | `read` | `execute` | `read` | `execute` | `read` |
| `viewer` | `read` | `read` | `read` | `read` | `none` | `none` |
| `auditor` | `read` | `read` | `read` | `read` | `none` | `read` |
| `member` | `read` | `none` | `none` | `none` | `none` | `none` |

해석:

- `Organization`과 `Team 관리`는 현재 별도 리소스 권한 테이블이 없으므로 Team 이름 기반 정책으로 처리한다.
- `Workflow`, `KnowledgeBase`, `LLM Credential`, `Audit`은 각각 리소스별 권한 테이블의 `auth_state`로 처리한다.
- `member` Team은 접근 권한보다 Organization membership 표현이 주 목적이다.

## Organization 권한 매트릭스

Organization 자체에 대한 권한은 현재 별도 `team_organization_permissions` 테이블이 없다. 따라서 기본 Team 이름과 서비스 정책으로 판단한다.

| Action | 설명 | 허용 Team | 비고 |
| --- | --- | --- | --- |
| `organization:read` | Organization 정보 조회 | `owner`, `admin`, `developer`, `operator`, `viewer`, `auditor`, `member` | Organization member라면 조회 가능 |
| `organization:update` | 이름, 설명, 설정 수정 | `owner`, `admin` | `managed_by` 변경 포함 가능 |
| `organization:create_child` | 하위 Organization 생성 | `owner`, `admin` | `organization_structure` 갱신 필요 |
| `organization:deactivate` | Organization 비활성화 | `owner` | 삭제 대신 soft delete 권장 |
| `organization:delete` | Organization 삭제 | `owner` | 위험 작업, 하위 리소스 정책 필요 |
| `organization:transfer_owner` | 소유권 이전 | `owner` | owner Team 단일 정책이면 membership 교체 |
| `organization:read_descendants` | 하위 Organization 조회 | `owner`, `admin`, `auditor` | `organization_structure` 기준 |

Owner 정책:

- 단일 Owner를 원하면 `owner` TeamMembership을 1개로 제한한다.
- 다중 Owner를 허용하면 GitHub Organization과 더 유사하다.
- 별도 `owner_id`가 없으므로 DB만으로 단일 Owner는 보장되지 않는다.

## Team 관리 권한 매트릭스

Team은 Organization 안의 role/tag다.

| Action | 설명 | 허용 Team | 비고 |
| --- | --- | --- | --- |
| `team:read` | Team 목록/상세 조회 | 모든 Organization member | `member` Team 포함 |
| `team:create` | Team 생성 | `owner`, `admin` | 새 Team은 `teams.organization_id`에 귀속 |
| `team:update` | Team 이름/설명/상태 수정 | `owner`, `admin` | `owner` Team 수정은 owner만 허용 권장 |
| `team:delete` | Team 삭제 또는 비활성화 | `owner`, `admin` | 기본 `member`, `owner` Team 삭제 금지 권장 |
| `team:add_member` | User를 Team에 추가 | `owner`, `admin` | 대상 User가 Organization member인지 확인 |
| `team:remove_member` | User를 Team에서 제거 | `owner`, `admin` | 자기 자신을 마지막 owner에서 제거 금지 |
| `team:list_members` | Team 멤버 조회 | `owner`, `admin`, 같은 Team member | 개인정보 범위 주의 |
| `team:grant_resource` | Team에 리소스 권한 부여 | `owner`, `admin` | 리소스별 permission row 생성 |
| `team:revoke_resource` | Team의 리소스 권한 제거 | `owner`, `admin` | 권한 row 삭제 또는 `none` |

서비스 제약:

```text
team_id + grantee_organization_id는 teams.id + teams.organization_id와 일치해야 한다.
```

이 제약은 DB의 composite FK가 최종 방어한다.

## Workflow 권한 매트릭스

저장 테이블:

```text
team_workflow_permissions
```

| Action | 설명 | Required auth_state |
| --- | --- | --- |
| `workflow:list` | 접근 가능한 Workflow 목록 조회 | `read` |
| `workflow:read` | Workflow 상세/그래프 조회 | `read` |
| `workflow:create` | Workflow 생성 | `write` |
| `workflow:update` | Workflow 그래프/설정 수정 | `write` |
| `workflow:delete` | Workflow 삭제 | `admin` |
| `workflow:execute` | Workflow 수동 실행 | `execute` |
| `workflow:execute_stream` | Workflow 스트리밍 실행 | `execute` |
| `workflow:deploy` | Workflow 배포 생성/수정 | `manage` |
| `workflow:publish` | 공유/공개 설정 변경 | `manage` |
| `workflow:manage_permissions` | Workflow 권한 Team 부여/회수 | `manage` |
| `workflow:read_logs` | Workflow 실행 로그 조회 | `read` |
| `workflow:read_trace` | Trace metadata 조회 | `read` |
| `workflow:read_payload` | Redacted payload 조회 | `write` |
| `workflow:read_raw_payload` | Raw prompt/completion 조회 | `admin` + trace visibility policy |

권장 해석:

- `read`: 그래프와 실행 결과 metadata 조회
- `execute`: 실행 가능하지만 수정은 불가
- `write`: 그래프와 설정 수정 가능
- `manage`: 배포, 공유, 권한 부여 가능
- `admin`: 삭제와 민감 데이터 접근 가능

## KnowledgeBase 권한 매트릭스

저장 테이블:

```text
team_knowledge_permissions
```

| Action | 설명 | Required auth_state |
| --- | --- | --- |
| `knowledge:list` | 접근 가능한 KnowledgeBase 목록 조회 | `read` |
| `knowledge:read` | KnowledgeBase 상세 조회 | `read` |
| `knowledge:search` | 검색/RAG 참조 사용 | `read` |
| `knowledge:create` | KnowledgeBase 생성 | `write` |
| `knowledge:update` | 이름, 설명, 검색 설정 수정 | `write` |
| `knowledge:add_document` | 문서 업로드/추가 | `write` |
| `knowledge:update_document` | 문서 재처리/메타데이터 수정 | `write` |
| `knowledge:delete_document` | 문서 삭제 | `write` |
| `knowledge:reindex` | 재인덱싱 실행 | `write` |
| `knowledge:delete` | KnowledgeBase 삭제 | `admin` |
| `knowledge:manage_permissions` | KnowledgeBase 권한 Team 부여/회수 | `manage` |

권장 해석:

- `read`: 조회와 검색 가능
- `write`: 문서 추가/수정/삭제와 재인덱싱 가능
- `manage`: Team 권한 관리 가능
- `admin`: KnowledgeBase 자체 삭제 가능

주의:

- `knowledge_bases.organization_id`가 리소스 소유 Organization이다.
- 기존 데이터 중 `organization_id`가 `NULL`인 row는 legacy/private 데이터로 별도 정책이 필요하다.

## LLM Credential 권한 매트릭스

저장 테이블:

```text
team_llm_permissions
```

| Action | 설명 | Required auth_state |
| --- | --- | --- |
| `llm_credential:list` | 접근 가능한 credential 목록 조회 | `read` |
| `llm_credential:read` | credential metadata 조회 | `read` |
| `llm_credential:use` | Workflow/LLM node에서 credential 사용 | `execute` |
| `llm_credential:create` | 새 credential 등록 | `manage` |
| `llm_credential:update` | credential 이름/설정 수정 | `manage` |
| `llm_credential:rotate_secret` | API key 교체 | `admin` |
| `llm_credential:delete` | credential 삭제 | `admin` |
| `llm_credential:manage_permissions` | credential 권한 Team 부여/회수 | `manage` |
| `llm_model:read` | 사용 가능한 model/provider 조회 | `read` |

권장 해석:

- `read`: credential 존재와 preview metadata 조회
- `execute`: credential을 사용한 호출 가능
- `manage`: credential 연결과 일반 설정 관리 가능
- `admin`: secret 교체와 삭제 가능

주의:

- 원문 secret은 어떤 권한에서도 직접 반환하지 않는다.
- `read`는 `config_preview` 수준만 허용한다.

## Audit 권한 매트릭스

저장 테이블:

```text
team_audit_permissions
```

| Action | 설명 | Required auth_state |
| --- | --- | --- |
| `audit:list` | Audit event 목록 조회 | `read` |
| `audit:read` | Audit event 상세 조회 | `read` |
| `audit:export` | Audit 데이터 export | `write` |
| `audit:read_descendant` | 하위 Organization audit 조회 | `read` + organization scope |
| `audit:manage_policy` | Audit visibility/retention 정책 수정 | `manage` |
| `audit:read_sensitive` | 민감 필드 포함 audit 조회 | `admin` |

권장 해석:

- `read`: 일반 audit 조회
- `write`: export처럼 대량 반출 가능성이 있는 행위
- `manage`: audit 정책 변경
- `admin`: 민감 audit 데이터 접근

주의:

- Audit 대상은 `team_audit_permissions.target_organization_id`로 표현한다.
- 요청 Organization과 target Organization의 관계는 `organization_structure`로 확인한다.

## App 권한 매트릭스

현재 별도 `team_app_permissions` 테이블은 없다.

따라서 App 권한은 Workflow 권한을 통해 간접 처리한다.

| Action | 설명 | 판정 기준 |
| --- | --- | --- |
| `app:list` | 접근 가능한 App 목록 조회 | 연결된 Workflow에 `read` 이상 |
| `app:read` | App 상세 조회 | 연결된 Workflow에 `read` 이상 |
| `app:create` | App 생성 | Organization에서 `developer` 이상 또는 Workflow `write` 생성 권한 |
| `app:update` | App 이름/아이콘/설정 수정 | 연결된 Workflow에 `write` 이상 |
| `app:delete` | App 삭제 | 연결된 Workflow에 `admin` 이상 |
| `app:publish` | App 공개/공유 설정 | 연결된 Workflow에 `manage` 이상 |

주의:

- App이 Workflow 없이 독립 리소스로 강해지면 `team_app_permissions`가 필요하다.
- 현재는 App과 Workflow 권한을 분리하지 않는 것이 단순하다.

## Endpoint 권한 매트릭스 초안

현재 API 코드와 맞춰 적용할 때 사용할 기준표다. 실제 endpoint 이름은 구현 중 조정될 수 있다.

### Organization / Team

| Endpoint 패턴 | Required policy |
| --- | --- |
| `GET /organizations/{organization_id}` | `organization:read` |
| `PATCH /organizations/{organization_id}` | `organization:update` |
| `DELETE /organizations/{organization_id}` | `organization:delete` |
| `POST /organizations/{organization_id}/transfer-owner` | `organization:transfer_owner` |
| `GET /organizations/{organization_id}/teams` | `team:read` |
| `POST /organizations/{organization_id}/teams` | `team:create` |
| `PATCH /organizations/{organization_id}/teams/{team_id}` | `team:update` |
| `DELETE /organizations/{organization_id}/teams/{team_id}` | `team:delete` |
| `POST /organizations/{organization_id}/teams/{team_id}/users` | `team:add_member` |
| `DELETE /organizations/{organization_id}/teams/{team_id}/users/{user_id}` | `team:remove_member` |

### Workflow

| Endpoint 패턴 | Required auth_state |
| --- | --- |
| `GET /workflows` | `read` |
| `GET /workflows/{workflow_id}` | `read` |
| `POST /workflows` | `write` |
| `PATCH /workflows/{workflow_id}` | `write` |
| `DELETE /workflows/{workflow_id}` | `admin` |
| `POST /workflows/{workflow_id}/execute` | `execute` |
| `POST /workflows/{workflow_id}/deploy` | `manage` |
| `GET /workflows/{workflow_id}/logs` | `read` |
| `GET /workflows/{workflow_id}/traces` | `read` |

### KnowledgeBase

| Endpoint 패턴 | Required auth_state |
| --- | --- |
| `GET /knowledge` | `read` |
| `GET /knowledge/{kb_id}` | `read` |
| `POST /knowledge` | `write` |
| `PATCH /knowledge/{kb_id}` | `write` |
| `DELETE /knowledge/{kb_id}` | `admin` |
| `POST /knowledge/{kb_id}/documents` | `write` |
| `DELETE /knowledge/{kb_id}/documents/{document_id}` | `write` |
| `POST /knowledge/{kb_id}/reindex` | `write` |
| `POST /rag/query` | `read` on referenced KnowledgeBase |

### LLM

| Endpoint 패턴 | Required auth_state |
| --- | --- |
| `GET /llm/providers` | `read` |
| `GET /llm/models` | `read` |
| `GET /llm/credentials` | `read` |
| `POST /llm/credentials` | `manage` |
| `PATCH /llm/credentials/{credential_id}` | `manage` |
| `DELETE /llm/credentials/{credential_id}` | `admin` |
| `POST /llm/credentials/{credential_id}/rotate` | `admin` |

### Audit / Trace

| Endpoint 패턴 | Required auth_state |
| --- | --- |
| `GET /audit` | `read` |
| `GET /audit/{event_id}` | `read` |
| `GET /audit/export` | `write` |
| `GET /tracing/runs` | `read` on workflow or audit target |
| `GET /tracing/runs/{run_id}` | `read` on workflow |
| `GET /tracing/runs/{run_id}/payload` | `write` on workflow + visibility policy |
| `GET /tracing/runs/{run_id}/raw-payload` | `admin` on workflow + visibility policy |
| `PATCH /tracing/policies/*` | `manage` or system admin |

## Public / Webhook 예외 정책

### Public App

Public App 접근은 로그인 User의 Team 권한을 요구하지 않을 수 있다.

권장 정책:

```text
public/shared URL로 실행되는 요청은 Deployment의 공개 설정과 secret 검증을 기준으로 처리한다.
Team RBAC는 관리 화면, 배포 생성, 로그 조회에만 적용한다.
```

### Webhook

Webhook 실행은 User session이 없을 수 있다.

권장 정책:

```text
Webhook 실행 자체는 webhook secret 또는 deployment auth_secret으로 검증한다.
Webhook 설정 생성/수정/삭제는 Workflow manage 이상이 필요하다.
Webhook 실행 로그 조회는 Workflow read 이상이 필요하다.
```

## 실패 응답 정책

| 상황 | HTTP Status | Reason |
| --- | ---: | --- |
| 인증 정보 없음 | `401` | `authentication_required` |
| 인증은 되었지만 Organization member가 아님 | `403` | `organization_membership_required` |
| Team은 있으나 리소스 권한 row가 없음 | `403` | `resource_permission_required` |
| 권한 단계가 부족함 | `403` | `insufficient_auth_state` |
| 리소스가 없음 | `404` | `resource_not_found` |
| 존재하지만 권한 때문에 숨겨야 하는 리소스 | `404` | `resource_not_found` |
| public/webhook secret 불일치 | `401` 또는 `403` | `invalid_secret` |

권장:

- 일반 사용자 화면에서는 권한 없는 리소스를 `404`로 숨길 수 있다.
- 관리자/감사 로그에는 실제 원인을 남긴다.
- 권한 실패는 audit log에 남긴다.

## 최소 구현 우선순위

1. `auth_state` 우선순위 함수 정의
2. User의 Organization TeamMembership 조회 함수 정의
3. 리소스별 Team 권한 조회 함수 정의
4. Workflow 권한 적용
5. KnowledgeBase 권한 적용
6. LLM Credential 권한 적용
7. Audit/Trace 권한 적용
8. Organization/Team 관리 정책 적용

## 최종 판단

현재 RBAC는 다음 방식으로 운영하는 것이 가장 일관적이다.

```text
Team = Organization 안의 role/tag
TeamMembership = Organization membership의 source of truth
Resource permission table = Team이 리소스에 대해 가지는 권한
auth_state = 리소스별 행동 가능 단계
```

이 방식이면 별도 Role 테이블 없이도 권한 매트릭스를 운영할 수 있다.

단, 다음 정책은 반드시 서비스 코드에서 강제해야 한다.

- Organization member는 최소 하나의 TeamMembership을 가진다.
- 기본 `member` Team은 삭제할 수 없다.
- owner Team을 단일 Owner로 쓸지 다중 Owner로 쓸지 결정한다.
- 리소스 Organization scope와 Team Organization scope를 항상 함께 확인한다.
- 권한 row가 없으면 `none`으로 처리한다.
