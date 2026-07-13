# Auth Test Cases

Status: Draft

## Minimum Failure Rule

이 문서는 정상 시나리오를 길게 반복하지 않고, 각 auth 조건을 깨뜨리는 최소 입력, 상태, 또는 관찰값을 기준으로 테스트 케이스를 정의한다.

각 테스트는 해당 최소 조건 하나만으로 실패를 유도하거나, 성공 경로의 필수 관찰값 하나가 빠졌을 때 실패로 판단할 수 있어야 한다.

## Unit Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| AUTH-TC-U001 | 비밀번호 해시는 원문과 구분되어야 한다. | 저장된 password 값이 원문과 같거나 `salt$hash` 형식이 아니다. | 테스트 실패. |
| AUTH-TC-U002 | 같은 비밀번호는 저장된 해시와 일치해야 한다. | 원문 비밀번호 한 글자만 다른 값을 입력한다. | `verify_password`가 false를 반환한다. |
| AUTH-TC-U003 | 잘못된 해시 형식은 인증되지 않아야 한다. | 저장된 해시 문자열에 `$` 구분자가 없다. | `verify_password`가 false를 반환한다. |
| AUTH-TC-U004 | 회원가입은 중복 이메일을 거부해야 한다. | DB 조회 결과에 같은 email 사용자가 이미 있다. | `400`, `이미 등록된 이메일입니다`. |
| AUTH-TC-U005 | 회원가입 성공은 이메일/비밀번호 사용자를 만들어야 한다. | 신규 사용자 저장값의 `social_provider`가 `none`이 아니거나 password가 해시 형식이 아니다. | 테스트 실패. |
| AUTH-TC-U006 | 회원가입 성공은 초기 세션 상태를 만들어야 한다. | `last_login_at`이 비어 있거나 JWT payload에 `user_id` 또는 `exp`가 없다. | 테스트 실패. |
| AUTH-TC-U007 | 회원가입 성공은 기본 organization 컨텍스트를 생성해야 한다. | 신규 사용자는 저장되지만 기본 organization 컨텍스트가 준비되지 않는다. | 테스트 실패. |
| AUTH-TC-U008 | 로그인은 없는 사용자를 거부해야 한다. | DB 조회 결과가 없다. | `401`, `이메일 또는 비밀번호가 올바르지 않습니다`. |
| AUTH-TC-U009 | 로그인은 비밀번호 없는 사용자를 거부해야 한다. | 사용자 row는 있으나 password 값이 비어 있다. | `401`, `이메일 또는 비밀번호가 올바르지 않습니다`. |
| AUTH-TC-U010 | 로그인은 잘못된 비밀번호를 거부해야 한다. | 저장된 해시와 입력 비밀번호가 일치하지 않는다. | `401`, `이메일 또는 비밀번호가 올바르지 않습니다`. |
| AUTH-TC-U011 | 로그인은 비활성 사용자를 거부해야 한다. | 올바른 비밀번호를 입력했지만 `deactivated_at`이 설정되어 있다. | `403`, `비활성화된 계정입니다`, `last_login_at` 미갱신. |
| AUTH-TC-U012 | 로그인은 비밀번호 검증 전 비활성 상태를 노출하지 않아야 한다. | 비활성 사용자에게 틀린 비밀번호를 입력한다. | `401`, `last_login_at` 미갱신. |
| AUTH-TC-U013 | 토큰 인증은 토큰 없음을 거부해야 한다. | `auth_token`이 `None` 또는 빈 값이다. | `401`, `로그인이 필요합니다`. |
| AUTH-TC-U014 | 토큰 인증은 유효하지 않은 JWT를 거부해야 한다. | JWT decode가 실패하거나 `user_id`를 반환하지 않는다. | `401`, `유효하지 않거나 만료된 토큰입니다`. |
| AUTH-TC-U015 | 토큰 인증은 삭제된 사용자를 거부해야 한다. | JWT의 `user_id`로 DB 사용자를 찾을 수 없다. | `401`, `유저를 찾을 수 없습니다`. |
| AUTH-TC-U016 | 토큰 인증은 비활성 사용자를 거부해야 한다. | JWT는 유효하지만 조회된 사용자에 `deactivated_at`이 설정되어 있다. | `403`, `비활성화된 계정입니다`. |
| AUTH-TC-U017 | 기존 소셜 사용자는 provider, social id, avatar 변경을 반영해야 한다. | 같은 email 사용자의 소셜 필드가 입력값과 다르다. | 변경된 필드가 저장된다. |
| AUTH-TC-U018 | 신규 소셜 사용자는 기본 organization 컨텍스트를 생성해야 한다. | 같은 email 사용자가 없고 Google user info가 유효하지만 기본 organization 컨텍스트가 준비되지 않는다. | 테스트 실패. |
| AUTH-TC-U019 | 비활성 소셜 사용자는 재로그인할 수 없어야 한다. | 같은 email 사용자에 `deactivated_at`이 설정되어 있다. | `403`, `비활성화된 계정입니다`. |
| AUTH-TC-U020 | Auth return validator는 중첩 encoding과 URL 정규화 우회를 막아야 한다. | 절대 URL, protocol-relative URL, backslash, dot segment, control character, malformed/과다 중첩 encoding 중 하나를 입력한다. | `/dashboard` fallback. |
| AUTH-TC-U021 | OAuth return context는 짧은 수명과 1회 소비를 강제해야 한다. | 같은 session context를 두 번 소비하거나 발급 10분 후 또는 미래 issued-at으로 소비한다. | 첫 정상 소비만 원래 경로, 나머지는 `/dashboard`. |
| AUTH-TC-U022 | Production session 서명키 구성은 fail-closed해야 한다. | `NODE_ENV=production`에서 키가 누락·공백·개발 placeholder 중 하나다. | Gateway 구성 오류. Secret 원문 미출력. |

## API Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| AUTH-TC-A001 | `POST /auth/signup`은 이메일 형식을 검증해야 한다. | `email` 값이 EmailStr 검증을 통과하지 않는다. | `422` 검증 오류 envelope. |
| AUTH-TC-A002 | `POST /auth/signup`은 필수 필드를 요구해야 한다. | `email`, `password`, `name` 중 하나가 없다. | `422` 검증 오류 envelope. |
| AUTH-TC-A003 | `POST /auth/signup` 성공은 LoginResponse를 반환해야 한다. | 응답에 `user.id`, `user.email`, `user.name`, `user.created_at`, `session.token`, `session.expires_at` 중 하나가 없다. | 테스트 실패. |
| AUTH-TC-A004 | `POST /auth/signup` 성공은 `auth_token` 쿠키를 설정해야 한다. | 성공 응답에 `auth_token` Set-Cookie가 없다. | 테스트 실패. |
| AUTH-TC-A005 | `POST /auth/login`은 필수 필드를 요구해야 한다. | `email` 또는 `password` 중 하나가 없다. | `422` 검증 오류 envelope. |
| AUTH-TC-A006 | `POST /auth/login`은 잘못된 credential을 거부해야 한다. | 없는 email, password 없는 사용자, 또는 틀린 password 중 하나만 충족한다. | `401`, `이메일 또는 비밀번호가 올바르지 않습니다`. |
| AUTH-TC-A007 | `POST /auth/login`은 비활성 사용자를 거부해야 한다. | 올바른 credential의 사용자에 `deactivated_at`이 설정되어 있다. | `403`, `비활성화된 계정입니다`. |
| AUTH-TC-A008 | `POST /auth/login` 성공은 LoginResponse와 `auth_token` 쿠키를 반환해야 한다. | 응답 body의 session token이 비어 있거나 Set-Cookie가 없다. | 테스트 실패. |
| AUTH-TC-A009 | localhost signup/login 쿠키는 secure를 끄고 발급해야 한다. | Host가 `localhost` 또는 `127.0.0.1`인데 `auth_token` 쿠키에 `secure=true`가 적용된다. | 테스트 실패. |
| AUTH-TC-A010 | localhost signup/login 쿠키는 `samesite=lax`여야 한다. | Host가 `localhost` 또는 `127.0.0.1`인데 `auth_token` 쿠키의 samesite가 `lax`가 아니다. | 테스트 실패. |
| AUTH-TC-A011 | localhost signup/login 쿠키는 전체 경로에 적용되어야 한다. | Host가 `localhost` 또는 `127.0.0.1`인데 `auth_token` 쿠키 path가 `/`가 아니다. | 테스트 실패. |
| AUTH-TC-A012 | localhost signup/login 쿠키는 6시간 만료여야 한다. | Host가 `localhost` 또는 `127.0.0.1`인데 `auth_token` 쿠키 max-age가 21600초가 아니다. | 테스트 실패. |
| AUTH-TC-A013 | localhost signup/login 쿠키는 domain을 설정하지 않아야 한다. | Host가 `localhost` 또는 `127.0.0.1`인데 `auth_token` 쿠키 domain이 설정된다. | 테스트 실패. |
| AUTH-TC-A014 | non-local signup/login 쿠키는 secure로 발급되어야 한다. | Host가 non-local인데 `auth_token` 쿠키에 `secure=true`가 적용되지 않는다. | 테스트 실패. |
| AUTH-TC-A015 | non-local signup/login 쿠키는 `samesite=none`이어야 한다. | Host가 non-local인데 `auth_token` 쿠키의 samesite가 `none`이 아니다. | 테스트 실패. |
| AUTH-TC-A016 | non-local signup/login 쿠키는 전체 경로에 적용되어야 한다. | Host가 non-local인데 `auth_token` 쿠키 path가 `/`가 아니다. | 테스트 실패. |
| AUTH-TC-A017 | non-local signup/login 쿠키는 6시간 만료여야 한다. | Host가 non-local인데 `auth_token` 쿠키 max-age가 21600초가 아니다. | 테스트 실패. |
| AUTH-TC-A018 | non-local signup/login 쿠키는 설정 가능한 domain을 사용해야 한다. | `COOKIE_DOMAIN` 또는 요청 host에서 계산 가능한 domain이 있는데 `auth_token` 쿠키 domain이 적용되지 않는다. | 테스트 실패. |
| AUTH-TC-A019 | `POST /auth/logout`은 요청 본문 없이 성공해야 한다. | body 없이 요청한다. | `200`, 로그아웃 확인 응답. |
| AUTH-TC-A020 | `POST /auth/logout`은 `auth_token` 쿠키를 삭제해야 한다. | 응답에 `auth_token` 삭제 Set-Cookie가 없다. | 테스트 실패. |
| AUTH-TC-A021 | `GET /auth/me`는 쿠키 없음을 거부해야 한다. | 요청에 `auth_token` 쿠키가 없다. | `401`, `로그인이 필요합니다`. |
| AUTH-TC-A022 | `GET /auth/me`는 invalid token을 거부해야 한다. | `auth_token`이 JWT 검증을 통과하지 않는다. | `401`, `유효하지 않거나 만료된 토큰입니다`. |
| AUTH-TC-A023 | `GET /auth/me`는 삭제된 사용자를 거부해야 한다. | JWT는 유효하지만 user id로 DB 사용자를 찾지 못한다. | `401`, `유저를 찾을 수 없습니다`. |
| AUTH-TC-A024 | `GET /auth/me`는 비활성 사용자를 거부해야 한다. | JWT는 유효하지만 사용자의 `deactivated_at`이 설정되어 있다. | `403`, `비활성화된 계정입니다`. |
| AUTH-TC-A025 | `GET /auth/me` 성공은 현재 사용자와 세션을 반환해야 한다. | 유효한 `auth_token` 요청의 응답에서 user 또는 session 필드가 빠진다. | 테스트 실패. |
| AUTH-TC-A026 | `GET /auth/google/login`은 non-local redirect URI를 https로 만들어야 한다. | Host가 non-local인데 OAuth redirect URI가 `http://`로 전달된다. | 테스트 실패. |
| AUTH-TC-A027 | Google OAuth callback은 token 교환 실패를 안전하게 거부해야 한다. | `authorize_access_token`이 raw marker를 포함한 예외를 던진다. | `400`, 고정 본문 `OAuth authentication failed`; 응답·로그·audit에 raw marker 없음. |
| AUTH-TC-A028 | Google OAuth callback은 malformed/email 없는 identity를 거부해야 한다. | token 또는 user info가 mapping이 아니거나 Google user info에 `email`이 없다. | `400`, 고정 본문 `OAuth authentication failed`. |
| AUTH-TC-A029 | Google OAuth callback 성공은 세션 쿠키를 설정해야 한다. | 유효한 user info인데 `auth_token` 쿠키가 없다. | 테스트 실패. |
| AUTH-TC-A030 | Google OAuth callback 성공은 서명 session의 safe `next`로 리다이렉트해야 한다. | 유효한 user info와 10분 이내 복귀 컨텍스트가 있는데 원래 path/query/hash로 `302` redirect하지 않는다. | 테스트 실패. |
| AUTH-TC-A031 | localhost Google OAuth callback은 대응하는 client origin으로 redirect해야 한다. | Host가 정확히 `localhost:8000` 또는 `127.0.0.1:8000`인데 대응하는 3000 포트의 safe `next`가 아니다. | 테스트 실패. |
| AUTH-TC-A032 | 회원가입 성공은 audit 이벤트를 기록해야 한다. | signup 성공 응답이 반환되었는데 audit 기록 호출이 없다. | 테스트 실패. |
| AUTH-TC-A033 | 회원가입 실패는 audit 이벤트를 기록해야 한다. | signup 실패 응답이 반환되었는데 audit 기록 호출이 없다. | 테스트 실패. |
| AUTH-TC-A034 | 로그인 성공은 audit 이벤트를 기록해야 한다. | login 성공 응답이 반환되었는데 audit 기록 호출이 없다. | 테스트 실패. |
| AUTH-TC-A035 | 로그인 실패는 audit 이벤트를 기록해야 한다. | login 실패 응답이 반환되었는데 audit 기록 호출이 없다. | 테스트 실패. |
| AUTH-TC-A036 | Google OAuth 성공은 audit 이벤트를 기록해야 한다. | Google OAuth callback 성공 응답이 반환되었는데 audit 기록 호출이 없다. | 테스트 실패. |
| AUTH-TC-A037 | 로그아웃은 audit 이벤트를 기록해야 한다. | logout 성공 응답이 반환되었는데 audit 기록 호출이 없다. | 테스트 실패. |
| AUTH-TC-A038 | Google OAuth 시작 실패는 fixed safe 응답을 반환해야 한다. | `authorize_redirect`가 raw marker를 포함한 예외를 던진다. | `503`, `OAuth login is unavailable`; 응답·로그·audit에 raw marker 없음. |
| AUTH-TC-A039 | Google OAuth return context replay는 기본 경로로 닫혀야 한다. | 성공 callback 뒤 같은 signed session으로 callback을 다시 호출한다. | 첫 호출은 safe `next`, 두 번째는 `/dashboard`. |
| AUTH-TC-A040 | Google OAuth unsafe `next`는 session에 권한 경로로 저장되지 않아야 한다. | 절대/protocol-relative/중첩-encoded/dot-segment 값으로 login을 시작한다. | callback은 `/dashboard`, 외부 host 비노출. |
| AUTH-TC-A041 | Non-local 유사 loopback host는 HTTPS callback을 사용해야 한다. | Host가 `localhost.attacker.example`처럼 loopback 문자열만 포함한다. | HTTPS non-local callback; local client redirect 미적용. |
| AUTH-TC-A042 | Credentialed CORS 구성은 wildcard와 malformed origin을 거부해야 한다. | `*`, 빈 목록, userinfo/path/query/fragment 또는 비-HTTP(S) 값 중 하나를 설정한다. | Gateway 구성 오류. |

## Component And Hook Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| AUTH-TC-C001 | `authApi.signup`은 `/auth/signup`으로 POST해야 한다. | signup 호출이 다른 path 또는 GET/PUT으로 나간다. | 테스트 실패. |
| AUTH-TC-C002 | `authApi.login`은 `/auth/login`으로 POST해야 한다. | login 호출이 다른 path 또는 GET/PUT으로 나간다. | 테스트 실패. |
| AUTH-TC-C003 | `authApi.logout`은 `/auth/logout`으로 POST해야 한다. | logout 호출이 다른 path로 나가거나 body 없는 POST를 처리하지 못한다. | 테스트 실패. |
| AUTH-TC-C004 | `authApi.me`는 `/auth/me`로 GET해야 한다. | me 호출이 다른 path 또는 POST로 나간다. | 테스트 실패. |
| AUTH-TC-C005 | `authApi.googleLogin`은 safe 복귀 경로와 함께 Google login endpoint로 이동시켜야 한다. | 호출 후 `window.location.href`가 `${apiBaseUrl}/auth/google/login?next=<encoded-safe-path>`가 아니다. | 테스트 실패. |
| AUTH-TC-C006 | API client는 credential 포함 요청을 사용해야 한다. | `publicApiClient` 또는 `apiClient`의 `withCredentials`가 false이다. | 테스트 실패. |
| AUTH-TC-C007 | 401 인터셉터는 보호 경로에서 로그인으로 보내고 중복 이동을 조정해야 한다. | 현재 path가 `/auth/*`도 `/`도 아닌데 401 후 `/auth/login`으로 이동하지 않거나 같은 path의 동시 interceptor/page redirect가 2초 안에 둘 다 navigation을 소유한다. | 테스트 실패. |
| AUTH-TC-C008 | 401 인터셉터는 auth 화면에서 자동 이동하지 않아야 한다. | 현재 path가 `/auth/login` 또는 `/auth/signup`인데 401 후 `window.location.href`가 바뀐다. | 테스트 실패. |
| AUTH-TC-C009 | 401 인터셉터는 홈에서 자동 이동하지 않아야 한다. | 현재 path가 `/`인데 401 후 `window.location.href`가 바뀐다. | 테스트 실패. |
| AUTH-TC-C010 | `useAuthRedirect`는 인증 성공 시 지정 경로로 replace해야 한다. | `authApi.me()`가 resolve되지만 `router.replace(redirectTo)`가 호출되지 않는다. | 테스트 실패. |
| AUTH-TC-C011 | `useAuthRedirect`는 인증 실패 시 공개 화면을 렌더링 가능하게 해야 한다. | `authApi.me()`가 reject되었는데 `isLoading`이 false가 되지 않는다. | 테스트 실패. |
| AUTH-TC-C012 | `useAuthRedirect`는 인증 확인 중 loading을 유지해야 한다. | `authApi.me()`가 pending인데 `isLoading`이 false이다. | 테스트 실패. |

## UI Flow Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| AUTH-TC-E001 | 로그인 화면은 이메일/비밀번호 성공 후 대시보드로 이동해야 한다. | `authApi.login`이 성공했는데 `/dashboard`로 이동하지 않는다. | 테스트 실패. |
| AUTH-TC-E002 | 로그인 화면은 401을 사용자 메시지로 표시해야 한다. | login 요청이 401로 reject된다. | 인라인 오류와 toast에 `이메일 또는 비밀번호가 올바르지 않습니다.` 표시. |
| AUTH-TC-E003 | 로그인 화면은 배열 detail 422를 사용자 메시지로 표시해야 한다. | login 요청이 `status=422`, `detail=[]`로 reject된다. | `입력한 값이 올바르지 않습니다.` 표시. |
| AUTH-TC-E004 | 로그인 화면은 비배열 detail 422를 사용자 메시지로 표시해야 한다. | login 요청이 `status=422`, 배열이 아닌 detail로 reject된다. | `입력 형식이 올바르지 않습니다.` 표시. |
| AUTH-TC-E005 | 로그인 화면은 5xx를 사용자 메시지로 표시해야 한다. | login 요청이 500 이상으로 reject된다. | `서버에 문제가 발생했습니다. 잠시 후 다시 시도해주세요.` 표시. |
| AUTH-TC-E006 | 로그인 화면은 네트워크 실패를 사용자 메시지로 표시해야 한다. | Axios error에 `response`가 없다. | `네트워크 연결을 확인해주세요.` 표시. |
| AUTH-TC-E007 | 로그인 화면은 Google 로그인 버튼을 safe 복귀 경로가 있는 OAuth 진입점에 연결해야 한다. | `구글로 로그인` 클릭 후 검증된 `next`가 `authApi.googleLogin`에 전달되지 않는다. | 테스트 실패. |
| AUTH-TC-E008 | 회원가입 화면은 비밀번호 불일치를 API 호출 전에 막아야 한다. | `password`와 `confirmPassword`가 다르다. | `authApi.signup` 미호출, `비밀번호가 일치하지 않습니다.` 표시. |
| AUTH-TC-E009 | 회원가입 화면은 성공 후 대시보드로 이동해야 한다. | `authApi.signup`이 성공했는데 성공 toast 또는 `/dashboard` 이동 중 하나가 없다. | 테스트 실패. |
| AUTH-TC-E010 | 회원가입 화면은 backend detail을 우선 표시해야 한다. | signup 요청이 `{ detail: "..." }`로 reject된다. | 해당 detail이 인라인 오류와 toast에 표시. |
| AUTH-TC-E011 | 회원가입 화면은 5xx를 사용자 메시지로 표시해야 한다. | signup 요청이 500 이상이고 detail이 없다. | `서버에 문제가 발생했습니다. 잠시 후 다시 시도해주세요.` 표시. |
| AUTH-TC-E012 | 회원가입 화면은 네트워크 실패를 사용자 메시지로 표시해야 한다. | Axios error에 `response`가 없다. | `네트워크 연결을 확인해주세요.` 표시. |
| AUTH-TC-E013 | 홈 화면은 인증 성공 시 landing을 보여주지 않아야 한다. | `authApi.me()`가 성공한다. | `/dashboard`로 replace되고 landing이 렌더링되지 않는다. |
| AUTH-TC-E014 | 홈 화면은 인증 실패 시 landing을 보여야 한다. | `authApi.me()`가 실패한다. | loading이 해제되고 landing이 렌더링된다. |
| AUTH-TC-E015 | 실제 로그아웃 사용자 경로는 서버 로그아웃 후 로그인 화면으로 이동해야 한다. | 연결된 로그아웃 UI에서 `authApi.logout()` 성공 후 `/auth/login`으로 이동하지 않는다. | 테스트 실패. |

## Permission Tests

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| AUTH-TC-P001 | auth 공개 엔드포인트는 resource permission을 요구하지 않아야 한다. | signup, login, logout, Google login, Google callback 중 하나가 resource permission dependency를 요구한다. | 테스트 실패. |
| AUTH-TC-P002 | `GET /auth/me`의 인증 경계는 `auth_token` 쿠키여야 한다. | Authorization header만 있고 `auth_token` 쿠키가 없다. | `401`, `로그인이 필요합니다`. |
| AUTH-TC-P003 | Gateway 공통 인증 dependency는 쿠키 토큰을 AuthService로 위임해야 한다. | `get_current_user`가 `auth_token` 쿠키를 `AuthService.get_user_from_token`에 전달하지 않는다. | 테스트 실패. |
| AUTH-TC-P004 | 인증 실패 401은 permission denied audit로 기록되어야 한다. | 인증 실패 응답이 401인데 `auth.permission_denied` 감사 이벤트가 없다. | 테스트 실패. |
| AUTH-TC-P005 | 인증/권한 거부 403은 permission denied audit로 기록되어야 한다. | 인증 또는 권한 경계에서 403이 발생했는데 `auth.permission_denied` 감사 이벤트가 없다. | 테스트 실패. |
| AUTH-TC-P006 | Conversation/Purge capability는 current user 인증으로 해석되지 않아야 한다. | Capability header만으로 `get_current_user` 또는 `/auth/me`가 user를 반환한다. | 401 또는 capability 전용 dependency에서만 처리. |
| AUTH-TC-P007 | Public Chatbot은 login cookie가 있어도 anonymous audience를 유지해야 한다. | Public route가 cookie user를 execution subject로 승격해 private resource를 허용한다. | Public-only authorization. |
| AUTH-TC-P008 | Authenticated internal surface는 public capability fallback을 허용하지 않아야 한다. | Expired/missing auth cookie를 valid Conversation grant로 대체한다. | 401/403, user identity 미생성. |
| AUTH-TC-P009 | Public capability lifecycle audit은 synthetic user actor를 만들지 않아야 한다. | App/deployment owner, credential/billing principal 또는 grant reference가 `actor_id`로 기록된다. | `actor_id=null`, `actor_type='public'`. |

## Edge Cases

| ID | 검증 조건 | 최소 실패 조건 | 기대 결과 |
| --- | --- | --- | --- |
| AUTH-TC-X001 | LoginResponse의 session token은 쿠키와 별도로 body에 존재해야 한다. | signup/login 성공 body에서 `session.token`이 빠진다. | 테스트 실패. |
| AUTH-TC-X002 | audit metadata는 세션 token 원문을 남기지 않아야 한다. | signup, login, logout, auth failure audit metadata에 JWT 또는 `auth_token` 원문이 포함된다. | 테스트 실패. |
| AUTH-TC-X003 | logout audit은 actor id 없이도 기록될 수 있어야 한다. | logout 요청에 현재 사용자 식별이 없다는 이유만으로 audit 기록이 실패한다. | 테스트 실패. |
| AUTH-TC-X004 | OAuth 실패 audit은 raw provider 예외를 저장하지 않아야 한다. | provider 예외 문자열에 credential-like marker를 포함한다. | audit에는 fixed reason code만 있고 raw marker는 없다. |
