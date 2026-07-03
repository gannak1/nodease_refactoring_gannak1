# Auth API Spec

Status: Verified
Verified Against: dev @ dc756c0

기본 경로: `/api/v1`

## Endpoints

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| POST | `/auth/signup` | 이메일/비밀번호 사용자를 생성하고, 6시간짜리 JWT 세션을 만들며, `auth_token` 쿠키를 설정한 뒤 사용자/세션 데이터를 반환한다. | 공개 |
| POST | `/auth/login` | 이메일/비밀번호 사용자를 인증하고, 6시간짜리 JWT 세션을 만들며, `auth_token` 쿠키를 설정한 뒤 사용자/세션 데이터를 반환한다. | 공개 |
| POST | `/auth/logout` | `auth_token` 쿠키를 삭제하고 로그아웃 확인 응답을 반환한다. | 공개 |
| GET | `/auth/me` | 쿠키에서 `auth_token`을 읽어 검증하고 현재 사용자/세션 데이터를 반환한다. | `auth_token` 쿠키 필요 |
| GET | `/auth/google/login` | Google 인증 화면으로 리디렉션해 Google OAuth를 시작한다. | 공개 |
| GET | `/auth/google/callback` | Google OAuth를 완료하고, 소셜 사용자를 생성하거나 갱신하며, `auth_token` 쿠키를 설정한 뒤 대시보드로 리디렉션한다. | Google OAuth 콜백 |

## Request And Response Models

### `POST /auth/signup`

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `email` | `EmailStr` | 예 | Pydantic 이메일 검증을 통과해야 한다. |
| `password` | `string` | 예 | salt가 포함된 SHA-256 비밀번호 해시로 저장된다. |
| `name` | `string` | 예 | 사용자 표시 이름이다. |

성공 응답: `200 OK`, `LoginResponse`, `auth_token` 쿠키 설정.

### `POST /auth/login`

요청 본문:

| 필드 | 타입 | 필수 | 비고 |
| --- | --- | --- | --- |
| `email` | `EmailStr` | 예 | Pydantic 이메일 검증을 통과해야 한다. |
| `password` | `string` | 예 | 저장된 비밀번호 해시와 비교된다. |

성공 응답: `200 OK`, `LoginResponse`, `auth_token` 쿠키 설정.

### `POST /auth/logout`

요청 본문: 엔드포인트 구현상 필수 요청 본문은 없다.

성공 응답: `200 OK`, `auth_token` 쿠키 삭제, 아래 본문 반환.

```json
{
  "message": "Logged out successfully"
}
```

### `GET /auth/me`

요청 본문: 없음.

인증 입력: `auth_token` 쿠키.

성공 응답: `200 OK`, `LoginResponse`.

### `GET /auth/google/login`

요청 본문: 없음.

성공 응답: Google OAuth 인증 화면으로 이동하는 리디렉션 응답.

### `GET /auth/google/callback`

요청 본문: 없음.

OAuth 입력: Google OAuth 콜백 요청과 세션 상태.

성공 응답: `302 Found`, `auth_token` 쿠키 설정, `/dashboard`로 리디렉션. Gateway 호스트가 `localhost:8000` 또는 `127.0.0.1:8000`이면 `http://localhost:3000/dashboard`로 리디렉션한다.

### 공통 응답 모델

`LoginResponse`:

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `user` | `UserResponse` | 현재 인증된 사용자이다. |
| `session` | `SessionInfo` | JWT 세션 데이터이다. |

`UserResponse`:

| 필드 | 타입 |
| --- | --- |
| `id` | `string` |
| `email` | `string` |
| `name` | `string` |
| `created_at` | `datetime` |

`SessionInfo`:

| 필드 | 타입 | 비고 |
| --- | --- | --- |
| `token` | `string` | JWT 액세스 토큰이다. signup/login/OAuth 콜백에서 같은 값이 `auth_token` 쿠키에 설정된다. |
| `expires_at` | `datetime` | 현재 시각에 6시간을 더해 계산된다. |

`LoginResponse` 예시:

```json
{
  "user": {
    "id": "00000000-0000-0000-0000-000000000000",
    "email": "user@example.com",
    "name": "홍길동",
    "created_at": "2026-07-04T00:00:00Z"
  },
  "session": {
    "token": "<jwt-token>",
    "expires_at": "2026-07-04T06:00:00Z"
  }
}
```

### 쿠키 동작

회원가입, 로그인, Google 콜백은 `auth_token`을 `max_age` 6시간의 HTTP-only 쿠키로 설정한다.

이메일/비밀번호 signup 및 login의 경우:

| 환경 | `path` | `secure` | `samesite` | `domain` |
| --- | --- | --- | --- | --- |
| Localhost 또는 `127.0.0.1` 호스트 | `/` | `false` | `lax` | 설정하지 않음 |
| Non-local 호스트 | `/` | `true` | `none` | `COOKIE_DOMAIN`, 또는 마지막 두 호스트 라벨 앞에 `.`를 붙인 값 |

Google 콜백에서 `secure`는 같은 운영 환경 감지 방식을 따르고, `samesite`는 `lax`이다.
Google 콜백은 코드에서 `path`를 명시하지 않는다.

`path="/"`는 브라우저가 같은 도메인의 전체 경로에 `auth_token` 쿠키를 보낼 수 있다는 뜻이다. `POST /auth/logout`은 `path="/"`로 `auth_token` 쿠키를 삭제한다.

## Errors

HTTP 예외는 다음 형식으로 반환된다.

```json
{
  "detail": "..."
}
```

검증 오류는 다음 형식으로 반환된다.

```json
{
  "error": {
    "code": "validation.failed",
    "message": "Request validation failed.",
    "request_id": "...",
    "details": {
      "errors": []
    }
  }
}
```

구현된 auth 오류 사례:

| 상태 | 엔드포인트 | 상세 / 본문 | 조건 |
| --- | --- | --- | --- |
| 400 | `POST /auth/signup` | `이미 등록된 이메일입니다` | 이메일이 이미 존재한다. |
| 400 | `GET /auth/google/callback` | `OAuth Authentication Failed: ...` | Google token 교환에 실패한다. |
| 400 | `GET /auth/google/callback` | `Email not found in Google account` | Google 사용자 정보에 email이 없다. |
| 401 | `POST /auth/login` | `이메일 또는 비밀번호가 올바르지 않습니다` | 사용자가 없거나, 비밀번호가 없거나, 비밀번호 검증에 실패한다. |
| 401 | `GET /auth/me` | `로그인이 필요합니다` | `auth_token` 쿠키가 없다. |
| 401 | `GET /auth/me` | `유효하지 않거나 만료된 토큰입니다` | JWT 검증에 실패한다. |
| 401 | `GET /auth/me` | `유저를 찾을 수 없습니다` | 토큰의 user id가 사용자로 해석되지 않는다. |
| 403 | `POST /auth/login`, `GET /auth/me`, `GET /auth/google/callback` | `비활성화된 계정입니다` | 조회된 사용자에 `deactivated_at`이 설정되어 있다. |
| 422 | `POST /auth/signup`, `POST /auth/login` | 검증 오류 envelope | 요청 본문이 Pydantic 검증에 실패한다. |

## Permissions

이 엔드포인트들에는 resource permission 검사가 구현되어 있지 않다.

`GET /auth/me`는 `AuthService.get_user_from_token`을 통해 `auth_token` 쿠키를 검증해서 인증한다.

회원가입, 로그인, 로그아웃, Google OAuth 진입/콜백은 공개 인증 생명주기 엔드포인트이다. 회원가입, 로그인, 로그아웃, Google 로그인 성공, 인증 실패는 Gateway에 감사 이벤트를 기록한다.
