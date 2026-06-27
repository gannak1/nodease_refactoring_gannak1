# RBAC Permission Matrix

개발 구현 기준으로 사용하는 RBAC 권한 Matrix다. 상세 배경은 `local/erd_docs/03-permission-matrix.md`를 따른다.

## 1. 원칙

- 기본 권한 subject는 `team`이다.
- user는 `team_memberships`를 통해 team 권한을 받는다.
- user별 예외 권한은 resource별 `user_*_permissions`로만 추가한다.
- user direct permission은 additive allow만 지원한다. deny는 없다.
- 권한 row가 없거나 `auth_state='none'`이면 거부한다.
- `organization.created_by` 또는 `organization.managed_by` user는 해당 organization scope에서 `manager`다.
- 권한 부여/회수는 organization owner/manager 또는 해당 resource의 effective `manager`만 가능하다.
- 권한 부여/회수/차단은 `audit_logs`에 기록한다.

## 2. 만들지 않는 Table

`roles`, `user_roles`, polymorphic `resource_permissions`, `audit_events`, `rag_retrieval_traces`, `user_connection_permissions`, `user_app_permissions`, `user_document_permissions`, `user_model_permissions`

## 3. Permission Tables

| Resource | Team | User direct |
| --- | --- | --- |
| Workflow | `team_workflow_permissions` | `user_workflow_permissions` |
| Knowledge Base | `team_knowledge_permissions` | `user_knowledge_permissions` |
| LLM Credential | `team_llm_permissions` | `user_llm_permissions` |
| Audit | `team_audit_permissions` | `user_audit_permissions` |

## 4. `auth_state`

| `auth_state` | 의미 |
| --- | --- |
| `none` | 접근 불가 |
| `viewer` | 조회 |
| `operator` | 조회 + 실행/사용 |
| `builder` | 조회 + 수정 + 실행/사용 |
| `manager` | 전체 권한 + 권한 관리 |
| `auditor` | audit/redacted trace 조회 |
| `raw_auditor` | audit/redacted trace 조회 + raw trace 조회 |

강도:

```text
none < viewer < operator < builder < manager
auditor < raw_auditor < manager
```

## 5. Resource Matrix

### Workflow

| State | read | write | execute | deploy | manage |
| --- | --- | --- | --- | --- | --- |
| `viewer` | Yes | No | No | No | No |
| `operator` | Yes | No | Yes | No | No |
| `builder` | Yes | Yes | Yes | No | No |
| `manager` | Yes | Yes | Yes | Yes | Yes |

### Knowledge Base

| State | read | write | use | manage |
| --- | --- | --- | --- | --- |
| `viewer` | Yes | No | No | No |
| `operator` | Yes | No | Yes | No |
| `builder` | Yes | Yes | Yes | No |
| `manager` | Yes | Yes | Yes | Yes |

### LLM Credential

| State | read | use | write | manage |
| --- | --- | --- | --- | --- |
| `viewer` | Yes | No | No | No |
| `operator` | Yes | Yes | No | No |
| `builder` | Yes | Yes | No | No |
| `manager` | Yes | Yes | Yes | Yes |

Model 사용 제한은 별도 model permission table이 아니라 credential 권한과 credential-model relation으로 처리한다.

### Audit

| State | read | view_raw | manage |
| --- | --- | --- | --- |
| `auditor` | Yes | No | No |
| `raw_auditor` | Yes | Yes | No |
| `manager` | Yes | Yes | Yes |

raw trace 조회는 audit 권한과 `trace_visibility_policies`가 모두 허용해야 한다.

## 6. Special Resources

| Target | Rule |
| --- | --- |
| App read | organization owner/manager 또는 primary workflow `read` |
| App settings | organization owner/manager 또는 primary workflow `manage` |
| Deployment read | workflow `read` |
| Deployment create/activate | workflow `deploy` |
| Previous deployment activate | workflow `deploy`; `audit_logs.action='deployment.activate_previous'` |
| Deployment delete/risky change | workflow `manage` |
| Connection secret/manage | connection owner 또는 organization owner/manager |
| Runtime connection use | consuming workflow `execute` 또는 knowledge base `use` |

Connection secret은 client/API 응답에 노출하지 않고 server-side runtime에서만 사용한다.

## 7. Decision Algorithm

1. user 인증.
2. active organization 결정.
3. resource organization scope 확인.
4. organization owner/manager면 `manager` 반환.
5. user의 team 목록 조회.
6. resource별 team permission 조회.
7. resource별 user direct permission 조회.
8. team/user direct 중 더 강한 권한을 effective permission으로 선택.
9. trace policy, connection secret, data/model policy 같은 추가 조건 평가.
10. 허용/거부 반환.
11. 거부 또는 민감 action은 audit 기록.

## 8. Enforcement Points

| Location | Required permission |
| --- | --- |
| Workflow read | workflow `read` |
| Workflow save | workflow `write` |
| Workflow execute | workflow `execute` |
| LLM node runtime | credential `use` |
| RAG node runtime | knowledge base `use` |
| DB node runtime | workflow `execute`; connection secret은 server-side only |
| Deployment create/activate | workflow `deploy` |
| Permission grant/revoke | organization owner/manager 또는 resource `manage` |
| Audit search | audit `read` |
| Raw trace read | audit `view_raw` + trace visibility policy |

## 9. Required Tests

- 권한 row 없음 또는 `none`이면 거부.
- `viewer`는 workflow 실행 불가.
- `operator`는 workflow 실행 가능, 수정 불가.
- `builder`는 workflow 수정/실행 가능, 배포 불가.
- `manager`는 배포와 권한 관리 가능.
- team `viewer` + user direct `builder` => `builder`.
- team `manager` + user direct `viewer` => `manager`.
- LLM node는 credential `use` 없으면 차단.
- RAG node는 knowledge base `use` 없으면 차단.
- connection runtime use는 workflow/knowledge base 권한으로 허용.
- raw trace는 `raw_auditor` 또는 `manager`만 가능.
