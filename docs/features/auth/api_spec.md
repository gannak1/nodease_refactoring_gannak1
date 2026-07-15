# Auth API Spec

Status: Draft
Verified Against: feature/mba-234 @ 647913b9

기본 경로: `/api/v1`

## Endpoints

| 메서드 | 경로 | 설명 | 인증 |
| --- | --- | --- | --- |
| POST | `/auth/signup` | 이메일/비밀번호 사용자를 생성하고, 6시간짜리 JWT 세션을 만들며, `auth_token` 쿠키를 설정한 뒤 사용자/세션 데이터를 반환한다. | 공개 |
| POST | `/auth/login` | 분산 account/network admission 뒤 이메일/비밀번호 사용자를 인증하고, 6시간짜리 JWT 세션을 만들며, `auth_token` 쿠키를 설정한 뒤 사용자/세션 데이터를 반환한다. | 공개 |
| POST | `/auth/logout` | `auth_token` 쿠키를 삭제하고 로그아웃 확인 응답을 반환한다. | 공개 |
| GET | `/auth/me` | 쿠키에서 `auth_token`을 읽어 검증하고 현재 사용자/세션 데이터를 반환한다. | `auth_token` 쿠키 필요 |
| GET | `/auth/google/login` | 선택적 safe `next`를 서명 세션에 저장하고 Google 인증 화면으로 리디렉션한다. | 공개 |
| GET | `/auth/google/callback` | Google OAuth를 완료하고, 소셜 사용자를 생성하거나 갱신하며, `auth_token` 쿠키를 설정한 뒤 1회용 safe 복귀 경로로 리디렉션한다. | Google OAuth 콜백 |

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

Password 검증 전 admission:

| Dimension | Capacity | Full refill time | 성공 시 reset |
| --- | ---: | ---: | --- |
| account+network | 5 | 300초 | 예 |
| account | 20 | 900초 | 예 |
| network | 100 | 300초 | 아니요 |

Gateway는 raw email과 source address를 Redis에 저장하지 않고 versioned HMAC fingerprint를 사용한다. Source network는 trusted proxy peer에서 온 forwarded chain만 해석한다. 모든 bucket에 token이 있을 때만 password 검증을 수행한다.

제한 응답: `429 Too Many Requests`.

```json
{
  "detail": "로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요."
}
```

응답에는 `Retry-After: <1..300>` header가 포함된다. Body와 header는 account 존재 여부, blocked dimension, current count, threshold와 fingerprint를 포함하지 않는다.

Limiter가 admission을 판정할 수 없는 경우: `503 Service Unavailable`.

```json
{
  "detail": "로그인을 일시적으로 사용할 수 없습니다."
}
```

응답에는 `Retry-After: 30` header가 포함되며 password 검증, JWT 발급과 `last_login_at` mutation은 발생하지 않는다.

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

Query:

| 필드 | 타입 | 필수 | 제약 |
| --- | --- | --- | --- |
| `next` | `string` | 아니요 | 최대 2,048자. Gateway가 상대 same-origin 경로로 다시 검증하며 안전하지 않으면 `/dashboard`를 저장한다. |

성공 응답: Google OAuth 인증 화면으로 이동하는 리디렉션 응답.

Gateway는 검증한 `next`와 발급 시각을 서명 세션에 저장한다. 이 컨텍스트는 10분 안에 한 번만 소비할 수 있고 callback query나 provider payload로 대체할 수 없다.

### `GET /auth/google/callback`

요청 본문: 없음.

OAuth 입력: Google OAuth 콜백 요청과 세션 상태.

성공 응답: `302 Found`, `auth_token` 쿠키 설정, 소비된 safe `next`로 리디렉션. 복귀 컨텍스트가 없거나 만료·재사용·형식 오류이면 `/dashboard`를 사용한다. Gateway 호스트가 정확히 `localhost:8000` 또는 `127.0.0.1:8000`이면 각각 대응하는 client origin의 3000 포트로 이동한다. `AUTH_FRONTEND_ORIGIN`이 설정되어 있으면 Gateway가 검증한 해당 HTTP(S) origin을 사용한다.

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
| 400 | `GET /auth/google/callback` | `OAuth authentication failed` | token 교환, token/user info 타입, user info 조회 또는 email 검증에 실패한다. Provider exception 원문은 반환하지 않는다. |
| 503 | `GET /auth/google/login` | `OAuth login is unavailable` | provider authorization 시작에 실패한다. Exception 원문은 반환하지 않는다. |
| 401 | `POST /auth/login` | `이메일 또는 비밀번호가 올바르지 않습니다` | 사용자가 없거나, 비밀번호가 없거나, 비밀번호 검증에 실패한다. |
| 429 | `POST /auth/login` | `로그인 시도가 너무 많습니다. 잠시 후 다시 시도해주세요.` | Account, source network 또는 account+network admission token이 부족하다. `Retry-After`는 1~300초이며 제한 차원은 노출하지 않는다. |
| 503 | `POST /auth/login` | `로그인을 일시적으로 사용할 수 없습니다.` | Redis limiter 연결, script 또는 result 판정에 실패한다. `Retry-After: 30`, credential verifier 미호출. |
| 401 | `GET /auth/me` | `로그인이 필요합니다` | `auth_token` 쿠키가 없다. |
| 401 | `GET /auth/me` | `유효하지 않거나 만료된 토큰입니다` | JWT 검증에 실패한다. |
| 401 | `GET /auth/me` | `유저를 찾을 수 없습니다` | 토큰의 user id가 사용자로 해석되지 않는다. |
| 403 | `POST /auth/login`, `GET /auth/me`, `GET /auth/google/callback` | `비활성화된 계정입니다` | 조회된 사용자에 `deactivated_at`이 설정되어 있다. |
| 422 | `POST /auth/signup`, `POST /auth/login` | 검증 오류 envelope | 요청 본문이 Pydantic 검증에 실패한다. |

## Permissions

이 엔드포인트들에는 resource permission 검사가 구현되어 있지 않다.

`GET /auth/me`는 `AuthService.get_user_from_token`을 통해 `auth_token` 쿠키를 검증해서 인증한다.

회원가입, 로그인, 로그아웃, Google OAuth 진입/콜백은 공개 인증 생명주기 엔드포인트이다. 공개라는 의미는 resource permission이 필요 없다는 뜻이며 password login admission을 우회한다는 뜻이 아니다.

회원가입, 로그인, 로그아웃, Google 로그인 성공, 인증 실패는 Gateway에 감사 이벤트를 기록한다. Password login은 성공에 `user.login`, invalid/inactive/limited/limiter-unavailable에 `user.login_failed`를 사용하고 safe reason code로 구분한다. Password login이 전용 감사를 기록한 `401/403`은 전역 `auth.permission_denied` 감사를 중복 생성하지 않는다. Login audit의 성공 actor snapshot은 opaque user ID와 표시 이름만 포함하며 raw email, IP/forwarded header, HMAC fingerprint, Redis key와 exception message를 저장하지 않는다.

## Session And Browser Configuration

- `NODE_ENV=production`에서는 `SECRET_KEY`가 없거나 공백이거나 알려진 개발 placeholder이면 Gateway가 시작되지 않는다. 검사와 오류 메시지는 secret 값을 출력하지 않는다.
- Credentialed CORS는 `CORS_ORIGINS`의 명시적인 HTTP(S) origin만 허용한다. Wildcard, 빈 목록, userinfo/path/query/fragment가 있는 origin은 시작 시 거부한다.
- Production password login limiter는 dedicated versioned HMAC keyring과 primary version을 요구한다. Trusted proxy CIDR은 실제 ingress topology에 맞게 명시하며 direct Gateway deployment는 빈 목록으로 forwarded address를 무시한다.
- Login limiter는 기존 Redis host/port/password와 전용 logical DB를 사용한다. Admission dependency가 실패하면 password login만 `503`으로 닫고 기존 JWT session 검증은 유지한다.
- 이 CORS allowlist는 브라우저가 credentialed JSON 요청을 보내는 현행 제품 경계다. 별도 CSRF token과 exact-Origin 검사는 Target이며 현재 구현으로 표현하지 않는다.

## Target Runtime Principal Boundary

- `auth_token` cookie/JWT가 검증한 current user만 authenticated identity를 제공한다. Organization membership, resource permission, LLM credential과 billing scope는 각 소유 도메인이 별도로 평가한다.
- `Authorization: Conversation <token>`과 `Authorization: Purge <receipt>`는 public Conversation Memory capability이며 `get_current_user`, `/auth/me`와 authenticated route의 user identity로 수용하지 않는다.
- Public Chatbot route는 login cookie가 함께 있어도 anonymous public audience를 유지한다. Current authenticated internal Chatbot은 별도 route, cookie auth와 configured credentialed CORS/JSON-only mutation 경계를 사용한다. 별도 access grant, CSRF token과 exact-Origin 검사는 Target이며 아직 구현되지 않았다.
- Public create/close/reset/delete request와 capability lifecycle AuditLog는 `actor_id=null`, `actor_type='public'`을 사용한다. 비동기 purge completion은 `system` actor를 사용한다. App/deployment owner, credential/billing principal과 capability reference를 user actor로 합성하지 않는다.

이 section은 ADR-0030 target integration contract이며 현재 auth endpoint 구현이 Conversation Memory capability를 이미 제공한다는 뜻이 아니다.
