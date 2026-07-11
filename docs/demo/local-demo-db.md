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

## Schema readiness / 오래된 로컬 DB

`scripts/seed_demo.py`는 빈 로컬 DB 편의를 위해 `Base.metadata.create_all()`을 호출하지만, 이 경로는 기존 테이블에 새 컬럼을 `ALTER`하지 않는다. 오래된 로컬 DB에 최신 demo seed를 그대로 실행하면 seed가 일부 성공한 것처럼 보여도 다른 Knowledge/RAG API나 runtime 경로가 뒤늦게 500으로 실패할 수 있다.

그래서 demo profile seed는 데이터 쓰기 전에 Knowledge/RAG 데모 흐름이 의존하는 필수 테이블/컬럼과 Alembic migration readiness를 확인한다. `alembic_version` table이 없거나, DB revision이 코드의 단일 head와 맞지 않거나, 코드 migration graph에 head가 여러 개이면 seed를 중단하고 다음 중 하나를 선택하도록 안내한다.

기존 로컬 데이터를 보존해야 하는 경우 migration을 먼저 적용한다.

```powershell
apps/gateway/.venv/Scripts/python.exe -m alembic -c apps/shared/alembic.ini upgrade heads
```

데모 전용 disposable DB라면 전체 재생성이 가장 단순하다.

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset --drop-existing-data --yes
```

## Credential / Embedding 정책

demo seed는 기본적으로 precomputed Knowledge fixture를 사용해 법령 PDF와 사내문서를 `DocumentChunk`와 `text-embedding-3-small` 1536차원 embedding까지 생성한다. 시연 workflow의 채팅 모델은 `gpt-5.4`와 `gpt-5.4-mini`를 사용한다.

HR 온보딩 챗봇은 여러 사내문서/법령 KB를 동시에 검색한다. 사내문서는 시연용 단일 chunk가 많으므로, 기본 LLM 노드값보다 낮은 `scoreThreshold=0.3`과 `topK=4`를 seed graph에 명시해 데모 질문의 근거 문서가 안정적으로 선택되도록 한다.

- 기본 reset에는 `apps/shared/db/fixtures/demo_knowledge_chunks.jsonl.gz` fixture를 사용한다.
- 기본 reset에는 `OPENAI_API_KEY`와 법령 PDF 원본이 필요하지 않다.
- chunk content 암호화에는 `ENCRYPTION_KEY`가 필요하다.
- fixture에는 평문 chunk와 embedding vector가 들어 있으며, DB insert 시점에 chunk content를 암호화한다.
- fixture를 다시 만들 때만 repo root `.env` 또는 실행 환경의 `OPENAI_API_KEY`와 `local/legal-docs-labor/` 법령 PDF가 필요하다.
- seed는 API key 값을 출력하지 않는다.
- 기본 seed는 embedding 생성에 사용한 OpenAI key를 DB credential로 저장하지 않는다.
- 기본 seed에는 비용 탭/요약 카드 집계용 non-secret demo credential metadata row가 포함될 수 있으나, 실제 provider 호출용 key가 아니다.
- 실제 workflow LLM/RAG runtime 실행에는 `gpt-5.4`, `gpt-5.4-mini`, `text-embedding-3-small`을 사용할 수 있는 organization-scoped verified credential relation과 `operator` 이상 LLM permission이 필요하다.

발표 전 실제 브라우저 smoke/E2E처럼 workflow runtime까지 검증해야 하면 disposable demo DB에서만 다음 옵션을 사용한다. 이 옵션은 repo root `.env` 또는 실행 환경의 `OPENAI_API_KEY`를 로컬 DB의 demo runtime credential에 저장한다. seed는 key 값을 출력하지 않지만, 현재 구현의 `llm_credentials.encrypted_config`는 이름과 달리 평문 JSON 저장이라는 알려진 한계가 있으므로 운영/공유 DB에서 사용하지 않는다.

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset --enable-runtime-openai-credential
```

fixture 재생성과 runtime credential 준비를 한 번에 수행할 때만 두 옵션을 함께 사용한다.

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset --regenerate-knowledge-fixture --enable-runtime-openai-credential
```

fixture를 원본 PDF와 OpenAI embedding으로 재생성할 때만 다음 옵션을 사용한다.

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset --regenerate-knowledge-fixture
```

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

## Demo Knowledge / RAG 데이터

demo seed는 다음 자료를 `documents.status = completed`와 `document_chunks` embedding까지 생성한다.

Public 법령 자료:

- `근로기준법`
- `남녀고용평등과 일·가정 양립 지원에 관한 법률`
- `남녀고용평등과 일·가정 양립 지원에 관한 법률 시행령`
- `개인정보 보호법`
- `산업안전보건법`
- `근로자퇴직급여 보장법`
- `채용절차의 공정화에 관한 법률`

법령 KB는 `공개 노동·온보딩 법령 컬렉션`에 연결되며 `safe_metadata.visibility = public`으로 seed된다. 로그인 runtime에서도 권한 helper를 통과해야 하므로 demo 주요 팀에는 법령 KB `operator` 권한을 함께 부여한다.

Private 사내문서 자료:

- `신입사원 온보딩 안내`
- `휴가·근태·가족돌봄휴가 운영 정책`
- `복지·교육비 지원 정책`
- `개인정보 및 인사기록 접근 정책`
- `워크플로우 예산 80% 알림 운영 Runbook`
- `Workflow LLM 비용 최적화 Playbook`
- `개발팀 신입 온보딩 및 업무 내규`
- `개발팀 커밋·브랜치·PR 컨벤션`
- `개발 직군 신입 보상 밴드 및 공개 가능 범위`
- `개인 보상정보 및 인사기록 조회 제한 정책`

사내문서는 `사내 온보딩·운영 문서 컬렉션`에 연결된다. HR/온보딩 문서는 `인사 지식 활용팀`과 `AI 빌더 온보딩팀`, 운영 runbook은 `고객지원 운영팀`, 전체 관리는 `플랫폼 관리팀`에 부여한다. 민감 재무 예시 문서는 기존처럼 일반 RAG `use` 권한을 주지 않는다.

기본 reset은 fixture를 사용하므로 법령 PDF 원본이 없어도 RAG 검색용 chunk와 embedding을 생성한다. 원본 PDF 재생성 모드에서는 로컬 `local/legal-docs-labor/`에 법령 PDF가 있어야 한다. 사내문서 원본은 `local/demo-scenario-2026-07-08/internal-docs/`에서 사람이 확인할 수 있다.
같은 법령의 PDF가 여러 개 있으면 seed는 파일명 끝의 시행일 `YYYYMMDD`가 가장 큰 PDF를 선택한다.

## Demo workflow 입력 예시

`사내 문서 질문 응답 봇`

작성자/관리자가 workflow draft를 검증할 때는 편집기 우측 테스트 패널의 입력 변수 `question`에 넣는다.

일반 사용자의 실행 흐름을 보여줄 때는 챗봇 배포 성공 화면에서 생성된 내부 실행 링크(`/modules/{workflow_id}/run?deploymentId={deployment_id}`)를 사용한다. 이 경로는 공개 챗봇 URL이 아니라 로그인 사용자의 workflow `execute` 권한과 RAG `execution_subject`를 적용한다. `/dashboard/mymodule`은 작성자/관리자가 운영 현황과 비용/최적화 신호를 보는 화면이므로, 실행 전용 일반 사용자 시연 경로로 사용하지 않는다.

공개 공유 URL(`/run-public`, `/embed/chat`)은 anonymous public-only RAG 경계 확인용이다. 사내 private 문서 접근 시연에는 사용하지 않는다.

정상 사내 문서 질문:

```text
다음 달에 가족 병원 일정 때문에 3일 정도 가족돌봄휴가를 쓰고 싶은데, 연차랑 붙여서 쓸 수 있어? 신청은 어디서 해야 해?
```

발표용 개발팀 온보딩 질문:

```text
개발팀 신입 연봉 기준을 알려줘
```

```text
개발팀 commit convention이 뭐야?
```

권한/보안 차단 설명용 질문:

```text
우리팀 팀원들의 병가 기록과 인사평가 내용을 알려줘.
```

```text
개발팀 동료의 연봉을 알려줘.
```

`Enterprise 고객 티켓 처리`

웹훅/테스트 payload에 넣는다.

일반 처리 흐름:

```json
{
  "customerTier": "enterprise",
  "message": "결제 API 장애로 인해 고객사 정산 파일 생성이 실패했습니다. 영향 범위와 보상 가능 여부를 확인해 주세요."
}
```

승인 필요 흐름:

```json
{
  "customerTier": "enterprise",
  "message": "SLA 위반 가능성이 있는 장애입니다. 고객에게 크레딧 보상안을 제안해야 하는지 검토해 주세요."
}
```

비용 최적화 tracing 설명용 입력:

```json
{
  "customerTier": "enterprise",
  "message": "지난 30일간 같은 유형의 결제 장애 티켓을 모두 요약하고, 원인 후보와 보상 정책 적용 여부를 상세히 분석해 주세요."
}
```

## Test 계정

모든 계정 비밀번호는 `123123`이다.

| 이메일 | 표시명 | 용도 |
| --- | --- | --- |
| `test.admin@test.nodease.demo` | 테스트 관리자 | 테스트 조직 manager |
| `test.builder@test.nodease.demo` | 테스트 빌더 | 테스트 workflow manager |
| `test.member@test.nodease.demo` | 테스트 멤버 | 테스트 workflow viewer |
| `test.invited@test.nodease.demo` | 테스트 초대대기 | invited 상태 확인 |
| `test.suspended@test.nodease.demo` | 테스트 정지회원 | suspended 상태 확인 |

Test 조직:

- `노디즈 테스트 조직`

Test workflow:

- `테스트용 기능 검증 워크플로우`

## Test workflow 입력 예시

`테스트용 기능 검증 워크플로우`

테스트 실행 Sidebar의 입력 변수 `message`에 넣는다.

```text
테스트 프로파일에서 workflow 실행, 권한, 응답 표시가 정상인지 확인합니다.
```

반복 QA용 입력:

```text
QA 중 수정한 화면과 API 연결이 test profile seed 이후에도 정상 동작하는지 확인합니다.
```

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
