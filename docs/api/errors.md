# 오류 계약

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

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
| `501` | API 경로는 있으나 계약 또는 기능이 아직 구현되지 않음 |

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
| `operation.not_implemented` | `501` | API 경로는 있으나 request/response 계약 또는 기능 구현이 아직 완료되지 않음 |
| `secret.not_returnable` | `500` 또는 `403` | secret 원문 반환 시도 차단 |

## 보안 규칙

- secret, token, credential, raw API key 원문은 error message에 포함하지 않는다.
- 401/403은 `audit_logs`에 기록할 수 있다.
- permission 실패 metadata에는 resource/action/effective permission 정도만 남기고 secret payload를 남기지 않는다.
