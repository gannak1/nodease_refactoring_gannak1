# 오류 계약

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1
Related ADRs: [ADR-202606291315-resource-access-403-404-policy](../decisions/ADR-202606291315-resource-access-403-404-policy.md)

## 범위

공통 HTTP status, error response, reason code 기준을 정의한다.

## 현재 구현 기준

현재 Gateway는 FastAPI `HTTPException` 기반 응답을 사용한다. 기본 형태는 다음과 같다.

```json
{
  "detail": "error message"
}
```

`detail`은 string 또는 object일 수 있다. 기존 endpoint와 호환이 필요하므로 즉시 전역 envelope로 바꾸지 않는다.

## 목표 Error Envelope

신규 또는 정리 대상 API는 아래 형태를 목표로 한다.

```json
{
  "error": {
    "code": "permission.denied",
    "message": "요청한 작업을 수행할 권한이 없습니다.",
    "request_id": "req_xxx",
    "details": {}
  }
}
```

## HTTP Status

| Status | 의미 |
| --- | --- |
| `400` | request validation 외의 잘못된 입력 |
| `401` | 인증되지 않음 |
| `403` | 인증됐지만 권한 없음 |
| `404` | 리소스 없음 또는 접근 가능한 scope 안에 없음 |
| `409` | 중복 또는 상태 충돌 |
| `422` | Pydantic/FastAPI validation 실패 |
| `500` | 서버 내부 오류 |

## Resource 접근 403/404 경계

App/Workflow 같은 organization-scoped resource는 아래 기준을 따른다.

- 리소스가 없으면 `404 resource.not_found`를 반환한다.
- 요청 user가 리소스의 organization scope 밖이면 `404 resource.not_found`로 숨긴다.
- 요청 user가 같은 organization scope 안에 있지만 필요한 resource action 권한이 없으면 `403 permission.denied`를 반환한다.
- 목록 API는 접근 가능한 resource만 반환하고 숨겨진 resource 수는 노출하지 않는다.

현재 App/Workflow endpoint의 403/404 응답 body는 기존 호환을 위해 plain FastAPI `detail` 형식이다.

```json
{
  "detail": "Forbidden"
}
```

```json
{
  "detail": "App not found"
}
```

위 reason code는 정책과 목표 envelope 기준이며, App/Workflow plain `detail` 응답을 전역 envelope로 정렬하는 작업은 별도 변경으로 다룬다.

## Reason Code

| Code | HTTP | 설명 |
| --- | --- | --- |
| `auth.required` | `401` | session/token 없음 |
| `auth.invalid` | `401` | session/token invalid |
| `permission.denied` | `403` | resource permission 부족 |
| `organization.required` | `400` | active organization이 필요하지만 결정되지 않음 |
| `resource.not_found` | `404` | 리소스 없음 |
| `resource.conflict` | `409` | 중복 또는 상태 충돌 |
| `validation.failed` | `422` | request schema validation 실패 |
| `secret.not_returnable` | `500` 또는 `403` | secret 원문 반환 시도 차단 |

## 보안 규칙

- secret, token, credential, raw API key 원문은 error message에 포함하지 않는다.
- 401/403은 `audit_logs`에 기록할 수 있다.
- permission 실패 metadata에는 resource/action/effective permission 정도만 남기고 secret payload를 남기지 않는다.
