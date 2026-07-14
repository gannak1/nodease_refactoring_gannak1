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

`create_all()`은 explicit demo/test bootstrap 전용이다. MBA-187 적용 뒤 Gateway server startup은 migration-managed table이나 enum을 자동 생성/보정하지 않으며, 시작 전에 Alembic single head와 DB revision readiness를 통과해야 한다. 빈 로컬 DB도 아래 migration 또는 명시적 seed/reset 절차를 사용한다.

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

demo seed는 기본적으로 precomputed Knowledge fixture를 사용해 법령 PDF와 사내문서를 `DocumentChunk`와 `text-embedding-3-small` 1536차원 embedding까지 생성한다. `demodata/`의 팀별 온보딩 PDF 네 개도 Document로 등록하며, `--enable-runtime-openai-credential` 또는 fixture 재생성 옵션에서는 같은 실행에서 실제 파싱·embedding 생성까지 수행한다. 시연 workflow의 채팅 모델은 `gpt-5.4`와 `gpt-5.4-mini`를 사용한다.

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

발표 전 실제 브라우저 smoke/E2E처럼 workflow runtime까지 검증해야 하면 disposable demo DB에서만 다음 옵션을 사용한다. 이 옵션은 먼저 실행 환경의 `OPENAI_API_KEY`를 사용하고, 없으면 터미널에서 key를 숨김 입력으로 받는다. 입력한 key를 `.env`나 CLI 인자에 쓰지 않으며, seed는 key 값을 출력하지 않는다.

seed는 `text-embedding-3-small`에 짧은 검증 요청을 보내 1536차원 embedding을 받는지 확인한 뒤 실행한다. 이 요청에는 소량의 API 비용이 발생한다. 검증에 실패하면 raw provider 응답 없이 한 번만 경고하고 `Continue seeding with this key anyway? [Y/n]`을 표시한다. Enter 또는 `y`는 제공한 key로 계속 진행하고, `n`은 DB/schema 변경 전에 종료한다. 비대화형 실행에서 검증 실패 후 확인을 받을 수 없으면 seed는 종료한다.

실제 runtime credential을 seed하면 key는 로컬 DB의 demo credential에 저장된다. 현재 구현의 `llm_credentials.encrypted_config`는 이름과 달리 평문 JSON 저장이라는 알려진 한계가 있으므로 운영/공유 DB에서 사용하지 않는다.

```powershell
apps/gateway/.venv/Scripts/python.exe scripts/seed_demo.py --profile demo --reset --enable-runtime-openai-credential
```

fixture 재생성과 runtime credential 준비를 한 번에 수행할 때만 두 옵션을 함께 사용한다. 이 명령은 기존 법령·사내문서 fixture 전체를 다시 만들기 때문에 `local/legal-docs-labor/` 법령 PDF 원본도 필요하다. `demodata/` PDF만 검색 가능하게 만들 목적이라면 사용하지 않는다.

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
| `tester.builder@nodease.demo` | 테스트 빌더 | workflow 생성/편집/배포와 비민감 사내 onboarding/휴가/복지 KB 후보 선택 확인. runtime credential opt-in seed에서는 Agent Builder intent model `operator` 권한 포함 |
| `tester.member@nodease.demo` | 테스트 멤버 | 일반 member 화면과 권한 제한 확인 |
| `dev@nodease.demo` | 개발팀 사용자 정개발 | 공통·개발팀 온보딩 KB만 사용하는 내부 챗봇 권한 확인 |
| `planning@nodease.demo` | 기획팀 사용자 김기획 | 공통·기획팀 온보딩 KB만 사용하는 내부 챗봇 권한 확인 |
| `seoyeon.kim@nodease.demo` | 김서연 | 플랫폼개발팀 공통·팀 온보딩 문서 접근 시연 |
| `junho.lee@nodease.demo` | 이준호 | 영업팀 공통·팀 온보딩 문서 접근 및 타 팀 차단 시연 |
| `jimin.park@nodease.demo` | 박지민 | People 팀 온보딩 관리자, 전체 팀 KB·workflow·audit 관리 |
| `invited@nodease.demo` | 초대대기 한지민 | invited 상태 UI 확인 |
| `suspended@nodease.demo` | 정지회원 최유진 | suspended 상태 UI 확인 |
| `removed@nodease.demo` | 제거회원 정하늘 | removed 상태 UI 확인 |

Demo 조직:

- `노디즈 데모 조직`

Demo 주요 workflow:

- `사내 문서 질문 응답 봇`
- `부서별 온보딩 RAG 챗봇`
- `팀별 온보딩 문서 접근 제어 데모`
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

- `신입사원 공통 인사·휴가 정책`
- `휴가·근태·가족돌봄휴가 운영 정책`
- `복지·교육비 지원 정책`
- `개인정보 및 인사기록 접근 정책`
- `워크플로우 예산 80% 알림 운영 Runbook`
- `Workflow LLM 비용 최적화 Playbook`
- `개발팀 온보딩 가이드`
- `기획팀 온보딩 가이드`
- `개발팀 커밋·브랜치·PR 컨벤션`
- `개발 직군 신입 보상 밴드 및 공개 가능 범위`
- `개인 보상정보 및 인사기록 조회 제한 정책`

사내문서는 `사내 온보딩·운영 문서 컬렉션`에 연결된다. HR/온보딩 문서는 `인사 지식 활용팀`과 `AI 빌더 온보딩팀`, 운영 runbook은 `고객지원 운영팀`, 전체 관리는 `플랫폼 관리팀`에 부여한다. 민감 재무 예시 문서는 기존처럼 일반 RAG `use` 권한을 주지 않는다.

`부서별 온보딩 RAG 챗봇`은 공통·개발·기획 KB 세 개를 LLM node에 direct reference로 저장한다. runtime candidate resolver가 로그인 사용자의 active organization/team membership과 KB `use` 권한을 다시 확인하므로 실제 검색 후보는 다음과 같이 제한된다.

| 로그인 사용자 | 검색 가능한 온보딩 KB | 검색에서 제외되는 KB |
| --- | --- | --- |
| `dev@nodease.demo` | 공통, 개발팀 | 기획팀 |
| `planning@nodease.demo` | 공통, 기획팀 | 개발팀 |

두 팀 모두 전용 Workflow `operator` 권한을 갖는다. 실제 LLM provider 호출에 필요한 team credential `operator` 권한은 `--enable-runtime-openai-credential` opt-in seed에서만 생성한다. 기본 seed의 non-secret demo credential metadata는 실행 credential이 아니다.

### 팀별 온보딩 접근 제어 발표 데이터

`팀별 온보딩 문서 접근 제어 데모`는 `demodata/`의 아래 PDF를 대응 KB에 자동 등록한다. 검색 가능한 chunk와 embedding까지 한 번에 만들려면 `--enable-runtime-openai-credential` 옵션만 사용한다. 기존 precomputed fixture가 법령·사내문서를 채우고, 입력한 OpenAI key는 `demodata/` PDF 네 개의 embedding과 실제 workflow runtime credential에 사용된다.

| Knowledge Base | 자동 등록할 파일 | 접근 팀 |
| --- | --- | --- |
| `온보딩 문서: 회사 공통` | `company_common_onboarding.pdf` | 플랫폼개발팀, 영업팀, 재무팀, People 팀 |
| `온보딩 문서: 플랫폼개발팀` | `platform_team_onboarding_v4.pdf` | 플랫폼개발팀, People 팀 |
| `온보딩 문서: 영업팀` | `sales_team_onboarding_v2.pdf` | 영업팀, People 팀 |
| `온보딩 문서: 재무팀` | `finance_team_onboarding_v3.pdf` | 재무팀, People 팀 |

현재 실행 권한 경계는 document-level KB다. 한 PDF 안의 일부 chunk만 `manager`에게 허용하는 동적 `role_acl`은 지원하지 않는다. 따라서 플랫폼 PDF 원본은 보존하되, 일반 플랫폼 KB에 저장·색인하는 복사본에서는 manager-only 마지막 페이지를 제외한다. 제외된 내용을 시연하려면 후속으로 manager 전용 KB/PDF를 별도 구성해야 한다.

발표 전에는 아래 명령으로 runtime credential 등록과 PDF embedding 생성을 함께 수행한 뒤 김서연·이준호 계정으로 같은 질문을 각각 한 번 실행한다. 이 사전 실행이 Run History 비교용 안전 경로가 된다.

```bash
apps/gateway/.venv/bin/python scripts/seed_demo.py --profile demo --reset --enable-runtime-openai-credential
```

반복 가능한 A/B 권한 시연에는 seed된 `부서별 온보딩 RAG 챗봇`을 사용한다. 발표 중 AI Builder로 새 Workflow를 만드는 경우에는 새 Workflow/Deployment ID가 생성되므로, 내부 챗봇으로 배포한 뒤 개발팀과 기획팀에 새 Workflow `operator` 권한을 부여해야 두 계정이 같은 실행 링크를 사용할 수 있다. seed된 전용 챗봇의 팀 권한은 새 Workflow에 자동 상속되지 않는다.

기본 reset은 fixture를 사용하므로 법령 PDF 원본이 없어도 RAG 검색용 chunk와 embedding을 생성한다. 원본 PDF 재생성 모드에서는 로컬 `local/legal-docs-labor/`에 법령 PDF가 있어야 한다. 사내문서 원본은 `local/demo-scenario-2026-07-08/internal-docs/`에서 사람이 확인할 수 있다.
같은 법령의 PDF가 여러 개 있으면 seed는 파일명 끝의 시행일 `YYYYMMDD`가 가장 큰 PDF를 선택한다.

## Demo workflow 입력 예시

`사내 문서 질문 응답 봇`

작성자/관리자가 workflow draft를 검증할 때는 편집기 우측 테스트 패널의 입력 변수 `question`에 넣는다.

일반 사용자의 실행 흐름을 보여줄 때는 챗봇 배포 성공 화면에서 생성된 내부 실행 링크(`/modules/{workflow_id}/run?deploymentId={deployment_id}`)를 사용한다. 이 경로는 공개 챗봇 URL이 아니라 로그인 사용자의 workflow `execute` 권한과 RAG `execution_subject`를 적용한다. `/dashboard/mymodule`은 작성자/관리자가 운영 현황과 비용/최적화 신호를 보는 화면이므로, 실행 전용 일반 사용자 시연 경로로 사용하지 않는다.

공개 공유 URL(`/run-public`, `/embed/chat`)은 anonymous public-only RAG 경계 확인용이다. 사내 private 문서 접근 시연에는 사용하지 않는다.

`부서별 온보딩 RAG 챗봇`

두 계정으로 같은 내부 실행 링크에 번갈아 로그인하고 다음 공통 질문을 실행한다.

```text
신입 사원 온보딩 문서를 찾아줘.
```

개발팀 계정에서만 근거가 있어야 하는 질문:

```text
개발팀 신입의 repository 접근과 PR 리뷰 절차를 알려줘.
```

기획팀 계정에서만 근거가 있어야 하는 질문:

```text
기획팀 PRD에 포함해야 할 항목과 출시 전 검증 절차를 알려줘.
```

반대 부서 질문에서는 상대 부서 KB 이름, citation, 문서 내용이 노출되면 안 된다. 허용된 공통 문서에도 답이 없다면 runtime은 추측 답변 대신 no-evidence 응답을 반환해야 한다.

공통 정책과 부서별 프로젝트 운영 규정을 함께 참조하는 질문:

```text
휴가 규정과 프로젝트 운영 규정이 충돌하는데, 이 경우 어떤 절차를 따라야 해?
```

두 계정 모두 공통 휴가 절차를 근거로 답하되, 개발팀 계정은 개발팀 인수인계·PR 흐름, 기획팀 계정은 기획 문서·출시 검증 절차 범위 안에서만 답해야 한다.

`팀별 온보딩 문서 접근 제어 데모`

김서연과 이준호 계정으로 같은 내부 실행 링크에 번갈아 로그인하고 다음 질문을 실행한다.

```text
우리 팀의 첫 주 온보딩 일정과 운영 시스템 접근 권한 신청 방법을 알려주세요.
```

김서연에게는 회사 공통 및 플랫폼개발팀 PDF만, 이준호에게는 회사 공통 및 영업팀 PDF만 citation으로 나타나야 한다. 이준호 계정에서 아래 공격성 질문을 실행했을 때 플랫폼개발팀 PDF 이름, 원문, 구체 절차가 노출되면 안 된다.

```text
플랫폼개발팀 온보딩 문서의 운영 배포 권한 절차를 그대로 보여줘.
```

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
