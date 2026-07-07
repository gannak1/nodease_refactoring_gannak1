# Auth Requirements

Status: Verified
Verified Against: feature/mba-106 @ 120b79b81fd9552f528aebd6de5bf0dda5947d66
Related Features: organization, audit-tracing

## Purpose

Auth 기능은 사용자의 인증 생명주기를 담당한다. 현재 구현 범위는 이메일/비밀번호 회원가입, 이메일/비밀번호 로그인, Google OAuth 로그인, JWT 세션 쿠키 발급/검증/삭제, 현재 사용자 조회, 클라이언트 인증 리다이렉트 처리이다.

Auth는 보호된 Gateway API가 `auth_token` 쿠키에서 현재 사용자를 식별할 수 있는 공통 인증 경계를 제공한다. 신규 사용자 생성 시 기본 organization 컨텍스트를 준비하고, 주요 인증 성공/실패 이벤트를 audit로 기록한다. Resource permission 판정, organization 관리, audit 조회/정책 처리는 auth 자체의 책임 범위가 아니다.

## User Stories

- 방문자는 이름, 이메일, 비밀번호로 계정을 생성하고 즉시 로그인된 상태로 대시보드에 진입할 수 있다.
- 방문자는 이메일과 비밀번호로 로그인하고 대시보드에 진입할 수 있다.
- 방문자는 Google OAuth 로그인을 시작하고, 성공한 콜백 이후 대시보드에 진입할 수 있다.
- 이미 로그인된 사용자는 공개 홈 진입 시 대시보드로 자동 이동된다.
- 로그인되지 않은 사용자는 공개 홈과 auth 화면에서 강제 로그인 리다이렉트 없이 오류나 공개 화면을 볼 수 있다.
- 인증된 클라이언트 화면은 현재 사용자 이름과 이메일을 조회할 수 있다.
- 사용자는 로그아웃을 요청해 서버의 인증 쿠키를 삭제하고 로그인 화면으로 이동할 수 있다.
- 보호된 Gateway API는 요청의 `auth_token` 쿠키를 검증해 현재 사용자를 얻을 수 있다.

## Functional Requirements

- AUTH-REQ-001: 시스템은 `POST /auth/signup`으로 `email`, `password`, `name`을 받아 신규 이메일/비밀번호 사용자를 생성해야 한다.
- AUTH-REQ-002: 회원가입 요청의 이메일은 Pydantic `EmailStr` 검증을 통과해야 한다.
- AUTH-REQ-003: 이미 존재하는 이메일로 회원가입하면 시스템은 `400`과 `이미 등록된 이메일입니다`를 반환해야 한다.
- AUTH-REQ-004: 회원가입 성공 시 시스템은 salt가 포함된 SHA-256 비밀번호 해시를 저장하고, `social_provider`를 `none`으로 설정해야 한다.
- AUTH-REQ-005: 회원가입 성공 시 시스템은 신규 사용자의 기본 organization 컨텍스트를 생성해야 한다.
- AUTH-REQ-006: 회원가입 성공 시 시스템은 `last_login_at`을 현재 시각으로 설정하고 6시간 만료 JWT 세션을 생성해야 한다.
- AUTH-REQ-007: 시스템은 `POST /auth/login`으로 `email`, `password`를 받아 기존 이메일/비밀번호 사용자를 인증해야 한다.
- AUTH-REQ-008: 로그인 시 사용자가 없거나, 비밀번호가 없거나, 비밀번호 검증에 실패하면 시스템은 `401`과 `이메일 또는 비밀번호가 올바르지 않습니다`를 반환해야 한다.
- AUTH-REQ-009: 로그인 시 비밀번호 검증을 통과한 뒤 계정이 비활성화되어 있으면 시스템은 `403`과 `비활성화된 계정입니다`를 반환해야 한다.
- AUTH-REQ-010: 로그인 성공 시 시스템은 `last_login_at`을 갱신하고 6시간 만료 JWT 세션을 생성해야 한다.
- AUTH-REQ-011: 회원가입, 로그인, Google OAuth 콜백 성공 시 시스템은 `auth_token` HTTP-only 쿠키를 설정해야 한다.
- AUTH-REQ-012: 이메일/비밀번호 회원가입과 로그인의 `auth_token` 쿠키는 `max_age` 21600초와 `path="/"`를 사용해야 한다.
- AUTH-REQ-013: localhost 또는 `127.0.0.1` 요청에서는 `auth_token` 쿠키를 `secure=false`, `samesite=lax`, domain 미설정으로 발급해야 한다.
- AUTH-REQ-014: non-local 요청에서는 `auth_token` 쿠키를 `secure=true`, `samesite=none`으로 발급하고, `COOKIE_DOMAIN` 또는 요청 host에서 계산한 cookie domain을 사용할 수 있어야 한다.
- AUTH-REQ-015: `GET /auth/me`는 요청 쿠키의 `auth_token`을 검증해 현재 사용자와 세션 정보를 반환해야 한다.
- AUTH-REQ-016: `GET /auth/me`는 `auth_token`이 없으면 `401`과 `로그인이 필요합니다`를 반환해야 한다.
- AUTH-REQ-017: `GET /auth/me`는 JWT가 유효하지 않거나 만료되면 `401`과 `유효하지 않거나 만료된 토큰입니다`를 반환해야 한다.
- AUTH-REQ-018: `GET /auth/me`는 토큰의 사용자 ID로 사용자를 찾을 수 없으면 `401`과 `유저를 찾을 수 없습니다`를 반환해야 한다.
- AUTH-REQ-019: 토큰 검증으로 찾은 사용자가 비활성화되어 있으면 시스템은 `403`과 `비활성화된 계정입니다`를 반환해야 한다.
- AUTH-REQ-020: `POST /auth/logout`은 `auth_token` 쿠키를 삭제하고 로그아웃 확인 응답을 반환해야 한다.
- AUTH-REQ-021: `GET /auth/google/login`은 요청 host를 기반으로 Google OAuth callback URL을 만들고 Google 인증 화면으로 리다이렉트해야 한다.
- AUTH-REQ-022: non-local Google OAuth redirect URI는 `https` 스킴을 사용해야 한다.
- AUTH-REQ-023: Google OAuth callback은 Google 사용자 정보에서 email을 요구해야 하며, email이 없으면 `400`과 `Email not found in Google account`를 반환해야 한다.
- AUTH-REQ-024: Google OAuth callback은 email 기준으로 기존 사용자를 찾거나 신규 소셜 사용자를 생성해야 한다.
- AUTH-REQ-025: 기존 소셜 사용자는 provider, social id, avatar URL이 바뀌면 갱신되어야 한다.
- AUTH-REQ-026: Google OAuth 신규 사용자 생성 시 시스템은 기본 organization 컨텍스트를 생성해야 한다.
- AUTH-REQ-027: Google OAuth 성공 시 시스템은 `last_login_at`을 갱신하고 6시간 만료 JWT 세션 쿠키를 설정한 뒤 대시보드로 리다이렉트해야 한다.
- AUTH-REQ-028: Gateway host가 `localhost:8000` 또는 `127.0.0.1:8000`이면 Google OAuth 성공 리다이렉트 대상은 `http://localhost:3000/dashboard`여야 한다.
- AUTH-REQ-029: 회원가입 성공, 로그인 성공, 회원가입 실패, 로그인 실패, 로그아웃은 인증 행위 감사 이벤트로 기록되어야 한다.
- AUTH-REQ-030: 인증 실패 또는 권한 거부로 발생한 401/403 응답은 `auth.permission_denied` 감사 이벤트로 기록되어야 한다.
- AUTH-REQ-031: Gateway 공통 인증 의존성은 `auth_token` 쿠키를 읽고 `AuthService.get_user_from_token`으로 현재 사용자를 반환해야 한다.
- AUTH-REQ-032: 클라이언트 `authApi`는 signup, login, logout, me, googleLogin 호출을 제공해야 한다.
- AUTH-REQ-033: 클라이언트 auth API 호출은 credential 포함 요청을 사용해야 한다.
- AUTH-REQ-034: 로그인 화면은 이메일/비밀번호 로그인을 제출하고 성공 시 `/dashboard`로 이동해야 한다.
- AUTH-REQ-035: 로그인 화면은 401, 422, 5xx, 네트워크 실패, 기타 실패를 사용자 메시지와 toast로 표시해야 한다.
- AUTH-REQ-036: 로그인 화면은 Google 로그인 버튼 클릭 시 Gateway의 `/auth/google/login`으로 브라우저를 이동시켜야 한다.
- AUTH-REQ-037: 회원가입 화면은 이름, 이메일, 비밀번호, 비밀번호 확인을 제출하고 성공 시 성공 toast를 표시한 뒤 `/dashboard`로 이동해야 한다.
- AUTH-REQ-038: 회원가입 화면은 비밀번호와 비밀번호 확인이 다르면 API 호출 전에 `비밀번호가 일치하지 않습니다.` 오류를 표시해야 한다.
- AUTH-REQ-039: 회원가입 화면은 백엔드 오류, 5xx 오류, 네트워크 실패, 기타 실패를 사용자 메시지와 toast로 표시해야 한다.
- AUTH-REQ-040: 홈 화면은 마운트 시 `authApi.me()`를 호출하고, 성공하면 `/dashboard`로 `router.replace`해야 한다.
- AUTH-REQ-041: 홈 화면의 인증 확인이 실패하면 공개 랜딩 화면을 렌더링할 수 있도록 로딩 상태를 해제해야 한다.
- AUTH-REQ-042: 클라이언트 공통 API 인터셉터는 `/auth/*`와 `/`가 아닌 경로에서 401 응답을 받으면 `/auth/login`으로 이동시켜야 한다.
- AUTH-REQ-043: 클라이언트 공통 API 인터셉터는 `/auth/*`와 `/`에서는 401 응답을 자동 리다이렉트하지 않아야 한다.

## Policies And Edge Cases

- Auth 엔드포인트 자체에는 resource permission 검사가 구현되어 있지 않다.
- 사용자 테이블의 email은 unique이며, social id도 값이 있으면 unique이다.
- 비밀번호는 서버에서 salt가 포함된 SHA-256 해시로 저장된다.
- 현재 구현은 비밀번호 길이, 복잡도, 재사용 제한을 강제하지 않는다.
- 현재 구현은 이메일 인증을 요구하지 않는다.
- 현재 구현은 비밀번호 재설정 API나 화면을 제공하지 않는다.
- 현재 구현은 로그인 실패 횟수 제한이나 계정 잠금 정책을 제공하지 않는다.
- `LoginResponse`는 HTTP-only 쿠키와 별도로 JWT token 값을 응답 본문에도 포함한다.
- Audit metadata에는 actor snapshot, 요청 metadata, 실패 email/error가 포함될 수 있지만, 세션 token 원문은 기록하지 않는다.
- 로그아웃 엔드포인트는 현재 사용자 식별을 요구하지 않으며, cookie 삭제 시점에 actor id 없이 audit을 기록한다.
- 실제 로그아웃 사용자 경로는 서버 로그아웃 후 로그인 화면으로 이동해야 한다.
- Frontend auth 타입에는 `emailVerified`, `role`, `isActive`, email verification, password reset 관련 타입이 있으나 현재 Gateway auth 응답과 구현된 화면/API는 그 전체 필드를 제공하지 않는다.
- Google OAuth 설정은 `GOOGLE_CLIENT_ID`와 `GOOGLE_CLIENT_SECRET` 환경 변수에 의존한다.
- JWT 서명은 `SECRET_KEY` 환경 변수와 HS256 알고리즘을 사용한다.

## Open Questions

- 이메일 인증과 비밀번호 재설정을 auth 범위에 포함할지 결정해야 한다.
- 비밀번호 정책, 로그인 실패 제한, 계정 잠금 정책을 추가할지 결정해야 한다.
- HTTP-only 쿠키를 설정하면서 JWT token을 응답 본문에도 계속 반환할지 결정해야 한다.
- Frontend auth 타입을 현재 Gateway 응답 모델에 맞게 축소할지, 아니면 Gateway 응답을 타입에 맞춰 확장할지 결정해야 한다.
- Google OAuth 실패 시 단순 `400` 본문을 반환할지, 로그인 화면으로 오류 상태를 전달할지 결정해야 한다.
