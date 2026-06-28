# 인증 API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: feature/mba-59 @ b92bc9e0f38588495d228fc0d17b10dfaaed03c1
Related ADRs: [ADR-202606290145-active-organization-header-context](../decisions/ADR-202606290145-active-organization-header-context.md)
Background ADRs: [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md)

## 범위

인증, session cookie, 현재 사용자 조회, active organization context 전달 계약을 정의한다.

## 현재 구현 엔드포인트

| Status | Method | Path | Request | Response | 설명 |
| --- | --- | --- | --- | --- | --- |
| Implemented | `POST` | `/api/v1/auth/signup` | `SignupRequest` | `LoginResponse` | email/password/name 기반 가입 후 session 발급 |
| Implemented | `POST` | `/api/v1/auth/login` | `LoginRequest` | `LoginResponse` | 로그인 후 session 발급 |
| Implemented | `POST` | `/api/v1/auth/logout` | 없음 | `{ "message": string }` | session cookie 제거 |
| Implemented | `GET` | `/api/v1/auth/me` | 없음 | `LoginResponse` | 현재 session 사용자 조회 |
| Implemented | `GET` | `/api/v1/auth/google/login` | 없음 | redirect | Google OAuth 시작 |
| Implemented | `GET` | `/api/v1/auth/google/callback` | OAuth callback | redirect | Google OAuth 완료 |

## 스키마

### `SignupRequest`

| Field | Type | Required | 설명 |
| --- | --- | --- | --- |
| `email` | email | Yes | 사용자 email |
| `password` | string | Yes | 사용자 password |
| `name` | string | Yes | 사용자 표시 이름 |

### `LoginRequest`

| Field | Type | Required | 설명 |
| --- | --- | --- | --- |
| `email` | email | Yes | 사용자 email |
| `password` | string | Yes | 사용자 password |

### `LoginResponse`

| Field | Type | 설명 |
| --- | --- | --- |
| `user` | `UserResponse` | 사용자 정보 |
| `session` | `SessionInfo` | token과 만료 시각 |

`SessionInfo.token`은 민감 값으로 취급한다. 로그나 문서 예시에 원문 token을 남기지 않는다.

## Active Organization Context

Active organization은 request header로 전달한다. 서버는 active organization을 session/cookie에 저장하지 않는다.

| Status | Header/Cookie | 설명 |
| --- | --- | --- |
| Implemented | `X-Organization-Id` | API 요청에서 명시적으로 active organization을 전달한다. |
| Not selected | session/cookie context | 서버 session이나 cookie에 active organization을 저장하지 않는다. |
| Legacy fallback | 없음 | organization context가 없는 과도기 경로에서 첫 active team membership을 primary organization으로 사용할 수 있다. |

`GET /api/v1/organizations/current`는 `X-Organization-Id` 값을 검증해 현재 요청의 active organization을 반환한다. 상세 endpoint는 [organization-rbac.md](organization-rbac.md)를 따른다.
