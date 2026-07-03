# 로컬 Demo/Test DB Seed

Status: Draft

## 목적

최종 시연용 DB 상태와 개발/QA 테스트용 DB 상태를 분리해서 관리한다.

- `demo` profile: 최종 발표 시연 기준 데이터다. 시연 직전에 같은 상태로 복원한다.
- `test` profile: 팀원이 기능 구현 중 자유롭게 조작하고 다시 덮어쓸 수 있는 테스트 데이터다.

두 profile은 다른 조직, 계정, workflow UUID를 사용한다. 테스트 데이터를 반복 갱신해도 최종 시연용 demo seed를 직접 덮어쓰지 않는다.

## 공통 실행 위치

각자 로컬에 clone한 repo root에서 실행한다. 아래 경로는 예시이며, 팀원마다 다를 수 있다.

```powershell
cd <YOUR_NODEASE_REPO_ROOT>
```

로컬 venv 기준으로 실행한다.

Windows:

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --dry-run
```

macOS/Linux:

```bash
apps/gateway/.venv/bin/python scripts/seed_demo.py --dry-run
```

## Demo Profile

최종 시연 기준 DB로 맞춘다.

Windows:

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset
```

macOS/Linux:

```bash
apps/gateway/.venv/bin/python scripts/seed_demo.py --profile demo --reset
```

기존 명령과의 호환을 위해 `--profile demo`는 생략할 수 있다.

Windows:

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --reset
```

macOS/Linux:

```bash
apps/gateway/.venv/bin/python scripts/seed_demo.py --reset
```

동작:

- demo seed가 관리하는 고정 UUID row만 삭제하고 다시 만든다.
- 기존 로컬 DB 전체를 비우지는 않는다.
- 최종 발표 직전에는 이 명령을 사용한다.

## Test Profile

팀원 개발/QA용 테스트 DB 상태로 맞춘다.

Windows:

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile test --reset
```

macOS/Linux:

```bash
apps/gateway/.venv/bin/python scripts/seed_demo.py --profile test --reset
```

동작:

- `노디즈 테스트 조직` 아래 테스트 계정, 팀, workflow, 권한만 삭제하고 다시 만든다.
- demo profile 데이터는 건드리지 않는다.
- 팀원이 기능 구현 중 테스트 데이터를 직접 변경했더라도 이 명령으로 테스트 기준 상태를 다시 덮어쓸 수 있다.

새로운 기능의 고정 테스트 더미 데이터가 필요하면 `apps/shared/db/demo_seed.py`의 test profile seed 영역에 추가한다. 최종 발표용 데이터가 아니라면 demo profile에 바로 넣지 않는다.

## 전체 로컬 DB 초기화

로컬 DB를 완전히 비우고 선택한 profile만 다시 만든다.

Demo만 재생성:

Windows:

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset --drop-existing-data --yes
```

macOS/Linux:

```bash
apps/gateway/.venv/bin/python scripts/seed_demo.py --profile demo --reset --drop-existing-data --yes
```

Test만 재생성:

Windows:

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile test --reset --drop-existing-data --yes
```

macOS/Linux:

```bash
apps/gateway/.venv/bin/python scripts/seed_demo.py --profile test --reset --drop-existing-data --yes
```

주의:

- 내부적으로 PostgreSQL `public` schema를 `CASCADE`로 재생성한다.
- 기존 개발/QA 데이터가 모두 삭제된다.
- 실수 방지를 위해 `--drop-existing-data`는 `--reset --yes`와 함께 쓸 때만 동작한다.

## Credential 정책

seed는 LLM Credential을 만들지 않는다.

- 실제 API key, Slack token, production secret은 seed하지 않는다.
- 더미 credential row도 만들지 않는다.
- 팀원이 LLM 실행을 실험해야 하면 관리자 화면에서 각자 실제 credential을 등록한다.
- seed reset은 과거 seed에서 만들었던 legacy demo credential row가 있으면 청소하지만, 새 credential은 생성하지 않는다.

## Demo 계정

모든 계정 비밀번호는 `123123`이다.

| 이메일 | 표시명 | 용도 |
| --- | --- | --- |
| `admin@nodease.demo` | 관리자 김도윤 | 권한 신청 승인, audit/운영 지표 확인 |
| `rookie@nodease.demo` | 신입사원 이서연 | 최초 생성/배포 권한 없음, 승인 후 workflow 생성/배포/사용 |
| `author@nodease.demo` | 운영자 박민준 | 비용 위험 workflow 운영, trace 확인, LLM 노드 최적화 |
| `tester.manager@nodease.demo` | 테스트 관리자 | manager 권한 확인 |
| `tester.builder@nodease.demo` | 테스트 빌더 | workflow 생성/편집/배포 확인 |
| `tester.member@nodease.demo` | 테스트 멤버 | 일반 member 화면과 권한 제한 확인 |
| `invited@nodease.demo` | 초대대기 한지민 | invited 상태 UI 확인 |
| `suspended@nodease.demo` | 정지회원 최유진 | suspended 상태 UI 확인 |
| `removed@nodease.demo` | 제거회원 정하늘 | removed 상태 UI 확인 |

Demo 조직:

- `노디즈 데모 조직`

Demo 주요 workflow:

- `사내 문서 질문 응답 봇`
- `Enterprise 고객 티켓 처리`
- `테스트용 문의 응답 워크플로우`
- 비용 위험 표시용 workflow 3종

## Test 계정

모든 계정 비밀번호는 `123123`이다.

| 이메일 | 표시명 | 용도 |
| --- | --- | --- |
| `test.admin@nodease.local` | 테스트 관리자 | 테스트 조직 manager |
| `test.builder@nodease.local` | 테스트 빌더 | 테스트 workflow manager |
| `test.member@nodease.local` | 테스트 멤버 | 테스트 workflow viewer |
| `test.invited@nodease.local` | 테스트 초대대기 | invited 상태 확인 |
| `test.suspended@nodease.local` | 테스트 정지회원 | suspended 상태 확인 |

Test 조직:

- `노디즈 테스트 조직`

Test workflow:

- `테스트용 기능 검증 워크플로우`

## Docker Gateway에 적용

Docker gateway 이미지가 seed 파일 변경 전 빌드라면 컨테이너 안에 최신 `scripts/seed_demo.py`가 없을 수 있다.
그 경우 이미지를 다시 빌드하거나, 임시로 파일을 복사한 뒤 실행한다.

gateway 컨테이너명은 Docker Compose project name이나 실행 방식에 따라 달라질 수 있다. 먼저 gateway 컨테이너명을 확인한다.

```powershell
docker ps --format "table {{.Names}}\t{{.Image}}\t{{.Status}}"
```

아래 명령의 `<GATEWAY_CONTAINER>`를 실제 gateway 컨테이너명으로 바꿔 실행한다. 기본 docker compose 설정에서는 `moduly-gateway`일 수 있다.

```powershell
docker exec <GATEWAY_CONTAINER> mkdir -p /app/scripts /app/apps/shared/db
docker cp scripts/seed_demo.py <GATEWAY_CONTAINER>:/app/scripts/seed_demo.py
docker cp apps/shared/db/demo_seed.py <GATEWAY_CONTAINER>:/app/apps/shared/db/demo_seed.py
docker exec <GATEWAY_CONTAINER> sh -lc "PYTHONPATH=/app python /app/scripts/seed_demo.py --profile demo --reset"
```

Test profile 적용:

```powershell
docker exec <GATEWAY_CONTAINER> sh -lc "PYTHONPATH=/app python /app/scripts/seed_demo.py --profile test --reset"
```
