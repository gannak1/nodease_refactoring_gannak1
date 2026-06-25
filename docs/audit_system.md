# Audit System — 구현 방식 및 사용법

사용자 작업 감사(Audit) 시스템의 **실제 구현**과 **사용법**을 정리한 문서입니다.
설계 배경은 [`spec.md`](./spec.md), 구현 순서는 [`plan.md`](./plan.md)를 참고하세요.

---

## 1. 개요

감사 로그는 두 가지를 기록합니다.

- **사용자 행동(계층 A)**: 로그인, 배포, 삭제 등 의미 있는 행위를 주체·결과와 함께 기록.
- **데이터 변경 이력(계층 B)**: 주요 모델의 변경 전/후(before/after)를 자동 기록.

두 계층 모두 동일한 `audit_logs` 테이블에 `category`로 구분해 저장하며, 기존
`log_system`의 **Celery 비동기 패턴**을 재사용해 **본 요청(트랜잭션)을 막지 않습니다.**

```
호출부(@audit / 명시적 record / ORM 리스너)
      → record_audit()
      → celery_app.send_task("audit.record", data)   # 비동기, 비차단
      → log_system 워커(audit_tasks.record_audit_log)
      → audit_logs 테이블 (append-only)
```

---

## 2. 구성 파일

| 파일 | 역할 |
|---|---|
| `apps/shared/db/models/audit_log.py` | `AuditLog` 모델 + `ActorType` / `AuditCategory` / `AuditStatus` Enum |
| `apps/shared/alembic/versions/a1b2c3d4e5f6_add_audit_logs_table.py` | `audit_logs` 테이블 마이그레이션 |
| `apps/shared/audit/logger.py` | `record_audit()` — 감사 이벤트 발행(직렬화 + `send_task`) |
| `apps/shared/audit/context.py` | 요청 단위 actor 전파용 `contextvar` |
| `apps/shared/audit/listeners.py` | 계층 B — ORM flush/commit/rollback 리스너 + 마스킹 |
| `apps/log_system/audit_tasks.py` | `audit.record` Celery 소비자 태스크 (DB 저장) |
| `apps/gateway/utils/audit.py` | 계층 A — `@audit` 데코레이터 |

**배선(기존 파일 수정)**

- `apps/shared/db/models/__init__.py`, `apps/shared/alembic/env.py` — 모델 등록
- `apps/shared/celery_app.py` — `audit.*` → `log` 큐 라우팅
- `apps/log_system/main.py` — `audit_tasks` import(태스크 등록)
- `apps/gateway/lifespan.py` — 부팅 시 ORM 리스너 등록

---

## 3. 데이터 모델 (`audit_logs`)

| 컬럼 | 타입 | 설명 |
|---|---|---|
| `id` | UUID PK | |
| `occurred_at` | timestamptz | 발생 시각(UTC), index |
| `actor_id` | UUID FK→users `SET NULL` | 행위 주체. 유저 삭제 시 null(로그는 보존) |
| `actor_type` | enum | `user` / `admin` / `system` |
| `category` | enum | `action`(계층 A) / `data_change`(계층 B) |
| `action` | str(100) | 예: `workflow.deploy`, `connection.updated` |
| `target_type` / `target_id` | str | 대상 리소스 |
| `before` / `after` | JSONB | 변경 전/후(계층 B) |
| `status` | enum | `success` / `failure` |
| `audit_metadata` | JSONB | ip, user_agent, request_id, **actor 스냅샷** |

> `actor_id`는 DB 레벨 FK(`SET NULL`)지만, "누가 했는지"는 `audit_metadata.actor`
> 스냅샷(id/email/name)으로 별도 보존합니다. 유저가 삭제돼도 행위자는 추적됩니다.
> SQLAlchemy 예약어 충돌을 피하려 메타데이터 컬럼명은 `audit_metadata`입니다.

---

## 4. 계층 B — 데이터 변경 이력 (자동)

`apps/gateway/lifespan.py`에서 리스너가 등록되면 **별도 코드 없이 자동 동작**합니다.

- **추적 대상 모델**: `App`, `Connection`, `LLMCredential`, `KnowledgeBase`, `User`
- **before/after**: SQLAlchemy 네이티브 attribute history로 **변경된 컬럼만** 산출
  (jsondiff 미사용 — ORM이 컬럼별 old/new를 이미 추적)
- **발행 시점**: `before_flush`에서 캡처하고 `after_commit`에서 발행합니다.
  rollback되면 후보 로그를 버려 실제 반영되지 않은 변경은 기록하지 않습니다.
- **동일 트랜잭션 병합**: 같은 객체가 commit 전 여러 번 flush되면 중간 상태를
  독립 로그로 남기지 않고 최종 commit 기준 이벤트로 병합합니다.
- **nested transaction**: savepoint 단위 감사는 아직 지원하지 않습니다. nested
  transaction이 감지되면 해당 트랜잭션의 계층 B 감사 후보를 버립니다.
- **action**: `{target_type}.{created|updated|deleted}` (예: `connection.updated`)
- **actor**: 요청 컨텍스트(contextvar)에서 가져오며, 없으면 `system`

### 민감 정보 마스킹

민감 필드는 평문 대신 `"***changed***"`로 저장됩니다. (`listeners.py`의 `SENSITIVE_FIELDS`)

| 모델 | 마스킹 필드 |
|---|---|
| `App` | `auth_secret` |
| `Connection` | `encrypted_password`, `encrypted_ssh_password`, `encrypted_ssh_private_key` |
| `LLMCredential` | `encrypted_config` |
| `User` | `password` |

**추적 모델/마스킹 필드 추가법** — `apps/shared/audit/listeners.py`:

```python
TRACKED_MODELS = {
    App: "app",
    Connection: "connection",
    # 새 모델 추가:
    # Workflow: "workflow",
}

SENSITIVE_FIELDS = {
    Connection: {"encrypted_password", ...},
    # 새 모델의 민감 필드 추가
}
```

---

## 5. 계층 A — 사용자 행동

### 5-1. 인증된 엔드포인트: `@audit` 데코레이터

`user: User = Depends(get_current_user)`가 있는 엔드포인트에 부착합니다.
actor/ip/user_agent/status는 자동 수집되고, 요청 동안 actor를 contextvar에 세팅하므로
**같은 요청이 일으킨 데이터 변경(계층 B)에도 actor가 함께 붙습니다.**

```python
from apps.gateway.utils.audit import audit

@router.delete("/workflows/{workflow_id}")
@audit("workflow.delete", target_param="workflow_id")
def delete_workflow(
    workflow_id: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    ...
```

- 데코레이터는 **라우터 데코레이터 아래**에 둡니다(`@router.x` 다음 줄).
- `action`: 기록할 행동 이름.
- `target_param`: target_id를 담은 인자 이름(경로/쿼리 파라미터). 생략 가능.
- `target_type`: 생략 시 `action`의 접두사(`workflow.delete` → `workflow`)를 사용.
- 핸들러가 예외를 던지면 `status="failure"`로 기록 후 예외를 그대로 재전파합니다.

### 5-2. 인증 전 엔드포인트(로그인 등): 명시적 호출

로그인 시점엔 `get_current_user`가 없고 actor가 **결과**에서 나오므로 데코레이터가
맞지 않습니다. 핸들러 내부에서 직접 `record_audit()`를 호출하세요.

```python
from apps.shared.audit import record_audit

@router.post("/login")
def login(request_obj: Request, request: LoginRequest, ...):
    try:
        result = AuthService.login(db, request)
    except Exception as e:
        record_audit(
            action="user.login_failed",
            category="action",
            actor_type="system",
            status="failure",
            metadata={"email": request.email, "error": str(e)},
        )
        raise

    record_audit(
        action="user.login",
        category="action",
        actor_id=result.user.id,
        actor_type="user",
        metadata={"actor": {"id": str(result.user.id), "email": result.user.email}},
    )
    return result
```

### `record_audit()` 시그니처

```python
record_audit(
    action: str,
    category: str,            # "action" | "data_change"
    *,
    actor_id=None,
    actor_type="user",       # "user" | "admin" | "system"
    target_type=None,
    target_id=None,
    before=None,
    after=None,
    status="success",        # "success" | "failure"
    metadata=None,
)
```

> 발행 실패가 본 요청을 막지 않도록 `record_audit()` 내부는 모든 예외를 잡아 로깅만 합니다.

### 5-3. 현재 부착 현황 (25건)

| 파일 | action |
|---|---|
| `auth.py` (명시적) | `user.login`(이메일/구글), `user.login_failed`, `user.logout`, `user.signup`, `user.signup_failed` |
| `app.py` | `app.create`, `app.update`, `app.delete`, `app.clone` |
| `workflow.py` | `workflow.create`, `workflow.update`(draft) |
| `deployment.py` | `workflow.deploy`, `deployment.toggle`, `deployment.delete` |
| `connectors.py` | `connection.create` |
| `llm.py` | `credential.create`, `credential.delete`, `model.pricing_update` |
| `knowledge.py` | `knowledge.create`, `knowledge.update`, `knowledge.delete`, `document.process` |
| `rag.py` | `document.upload`, `document.delete` |

미부착 라우트는 대부분 조회(GET)·위저드·실행(run/webhook, 기존 `WorkflowRun`이 추적) 등 감사 대상이 아닌 것들이다.

---

## 6. 적용/배포 절차

1. **마이그레이션 적용** (DB 실행 + 가상환경 활성화 후):

   ```bash
   alembic -c apps/shared/alembic.ini upgrade head
   ```

   롤백은 `alembic -c apps/shared/alembic.ini downgrade -1`.

2. **서비스 재시작** — gateway(리스너 등록) + log_system 워커(`audit.record` 소비).

3. (선택) 행동 로그를 남길 엔드포인트에 `@audit` 부착.

---

## 7. 조회 (MVP: 직접 쿼리)

전용 조회 API는 아직 없습니다. DB에서 직접 조회합니다.

```sql
-- 특정 유저의 최근 행동
SELECT occurred_at, action, status, target_type, target_id
FROM audit_logs
WHERE actor_id = '<user-uuid>'
ORDER BY occurred_at DESC
LIMIT 50;

-- 자격증명 변경 이력
SELECT occurred_at, action, before, after, audit_metadata->'actor' AS actor
FROM audit_logs
WHERE category = 'data_change' AND target_type = 'credential'
ORDER BY occurred_at DESC;
```

---

## 8. 알려진 갭 / 제약

### 8-1. admin 인증 부재 (audit 외부 과제)

`llm.py`의 `model.pricing_update`(PUT `/models/{model_id}/pricing`)와 `sync_system_pricing`은
주석에 `[Admin]`이라고 적혀 있으나 **실제로는 인증·권한 체크가 전혀 없습니다.**
`get_current_user`조차 없어 누구나 호출 가능하며, `User` 모델에도 `role`/`is_admin`
같은 권한 컬럼이 없습니다.

- 그 결과 `@audit`는 이 엔드포인트를 `actor_type="system"`(actor_id 없음)으로 기록합니다.
  버그가 아니라 **인증이 없으니 actor를 알 수 없는 현 상태의 정확한 반영**입니다.
- **이 admin 인증/권한 모델은 별도 작업자가 구현 중**이며 본 audit 범위 밖입니다.
  권한 모델이 도입되면: ① 해당 엔드포인트에 admin 의존성 추가 → audit actor 자동 채워짐,
  ② spec의 `user.role_change`가 의미를 갖게 됨, ③ 계층 B의 `User` 권한 필드 추적 강화.

### 8-2. 엔드포인트가 없어 미부착인 spec 행동

`workflow.delete`, `connection.delete`, `credential.update`는 해당 라우트가 아직 없고,
`user.invite`/`user.role_change`는 `users.py`가 비어 있어 부착 대상이 없습니다.
(추측으로 만들지 않고 라우트 생성 시 부착)

### 8-3. 문서 동기화 감사 미적용

`knowledge.py`의 문서 동기화(`/{kb_id}/documents/{document_id}/sync`)는 아직 별도
감사 action이 없습니다. 필요하면 `document.sync`로 부착합니다.

### 8-4. run.py 접근 감사 미적용

배포 실행(`run.py`)은 로그인 유저가 아니라 `app.auth_secret`(공유 시크릿) 또는 익명으로
호출되어 `@audit` 대상이 아닙니다. "실행 사실"은 기존 `WorkflowRun`이 추적하나, **외부
호출자 IP·인증 실패(시크릿 brute-force) 같은 보안 접근 감사는 미적용**입니다. 필요 시
명시적 `record()`(`deployment.run` / `deployment.run_denied`)와 `ActorType`에
`api`/`anonymous` 추가로 확장할 수 있습니다.

### 8-5. 기타 제약

- **리스너 등록 범위**: 현재 **gateway**에만 등록. 워커가 추적 대상 모델을 직접
  변경하는 경우 해당 워커에도 `register_audit_listeners()` 호출이 필요합니다.
- **범위 밖**(추후): 위변조 방지(해시 체인), 조회 API/대시보드, 보관 정책·파티셔닝,
  검색엔진 미러링. (spec 8장)

---

## 9. 검증 현황

이미 검증된 항목:

- **마이그레이션**: alembic 단일 head 연결 확인, 오프라인 SQL로 `audit_logs` 테이블·
  enum·인덱스·`ON DELETE SET NULL` FK DDL 및 다운그레이드 렌더링 확인.
- **계층 A 데코레이터**(런타임 스모크): FastAPI 시그니처 보존(의존성 주입 유지),
  record 발행 시 actor 스냅샷·target·ip 포함, contextvar 세팅/정리, 예외 시 `failure`
  기록 후 재전파.
- **계층 B 마스킹**(런타임): `Connection`/`LLMCredential` 민감 필드가 `***changed***`로
  치환되고 일반 필드는 보존됨.
- **계층 B 트랜잭션 경계**(단위 테스트): flush 후에는 발행하지 않고 commit 이후에만
  발행하며, rollback 시 후보 로그를 폐기함.
- **계층 B 이벤트 라이프사이클**(SQLAlchemy Session 테스트): 실제 Session에서
  commit/rollback, multi-flush 병합, nested transaction 생략을 확인함.

실제 DB·Redis 환경에서 추가로 확인 권장:

- 마이그레이션 실제 up/down 적용
- 추적 모델 변경 시 before/after 적재(특히 UPDATE의 변경 컬럼만 기록)
- Redis 다운 등 발행 실패 시 본 요청이 막히지 않는지
- log_system 워커가 `audit.record`를 소비해 `audit_logs`에 저장하는지
