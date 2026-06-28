# 인증 API

Status: Draft
Authority: API
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs: [ADR-202606271559-active-organization](../decisions/ADR-202606271559-active-organization.md)

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

Active organization 전달 방식은 `X-Organization-Id` header로 확정한다.

| Status | Header/Cookie | 설명 |
| --- | --- | --- |
| Required for organization-scoped APIs | `X-Organization-Id` | API 요청에서 명시적으로 active organization을 전달한다. |
| Not used | session/cookie context | 서버 session에는 active organization을 저장하지 않는다. |
| Transition fallback | 없음 | header가 없는 과도기 요청은 첫 active team membership을 primary organization으로 사용할 수 있다. |

Gateway는 `X-Organization-Id` 값이 현재 사용자의 active team membership scope 안에 있는지 검증한다. Organization scope가 필요한 신규 API와 FE 요청은 header 전달을 기본 계약으로 삼는다.
