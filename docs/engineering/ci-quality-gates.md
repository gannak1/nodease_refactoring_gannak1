# PR CI 품질 게이트

Status: Draft
Verified Against: feature/mba-328 @ a7bc1d3b

## 목적

Nodease의 PR 품질 게이트는 모든 테스트를 매번 실행하는 장치가 아니다. 변경 파일을 기능·도메인 영향 범위로 변환하고, 해당 변경에 필요한 검사만 실행한 뒤 하나의 안정적인 최종 check로 병합 가능 여부를 판단한다.

Coverage threshold는 MBA-192, Client 기존 ESLint warning 정리는 MBA-252, 전체 cross-domain 회귀는 MBA-30, AWS 배포 인증과 CD는 MBA-224가 소유한다.

## 진입점

PR 검증 진입점은 `.github/workflows/pr-quality-gate.yml`과 `.github/workflows/pr-ci-control-guard.yml`이다.

- 품질 게이트는 모든 `pull_request`에 실행되며 repository content read 권한만 사용한다.
- 신뢰 가드는 base 브랜치의 `pull_request_target` workflow로 실행되며 PR 코드를 checkout하거나 실행하지 않는다.
- 신뢰 가드는 변경 파일, review, reviewer 권한만 GitHub API로 읽고 현재 PR head에 정책 status만 기록한다.
- 같은 PR에 새 commit이 push되면 이전 실행을 취소하고 새 head를 다시 판정한다.
- AWS credential, 배포 secret 또는 장기 credential을 요구하지 않는다.
- required check 후보는 `PR Quality Gate / ci-required`와 `trusted-ci-control/base-policy`다.

실제 required check context는 workflow가 `dev`에 병합된 뒤 probe PR에서 확인한다. 확인 전에는 GitHub ruleset에 이름을 추측해 등록하지 않는다.

## Job 구성

| Job | 실행 조건 | 책임 |
| --- | --- | --- |
| `change-scope` | 항상 | base와 head 사이의 변경 경로 분류 |
| `alembic-single-head` | 항상 | revision 중복, 누락 parent, cycle, multiple heads 검사 |
| `python-lint` | Python 파일 변경 | 존재하는 변경 Python 파일만 Ruff 검사 |
| `client-quality` | Client 영향 | ESLint, typecheck, 변경 dependency Vitest, build |
| `gateway-and-root-tests` | Gateway 또는 root 영향 | 선택된 Gateway와 root pytest |
| `workflow-engine-tests` | Workflow Engine 영향 | 선택된 Workflow Engine pytest |
| `shared-tests` | Shared 영향 | 선택된 Shared pytest |
| `log-system-tests` | Log System 영향 | 선택된 Log System pytest |
| `sandbox-tests` | Sandbox 영향 | Sandbox pytest |
| `deployment-config-validation` | Actions·Helm·Kubernetes·Terraform·Compose·Dockerfile 영향 | 변경된 배포 설정의 정적 검사 |
| `knowledge-postgres-contracts` | Knowledge runtime/ingestion/DB 영향 | 실제 PostgreSQL Knowledge 계약 검사 |
| `workflow-postgres-contracts` | migration/schedule/external effect 영향 | 실제 PostgreSQL workflow 계약 검사 |
| `agent-builder-postgres-contracts` | Agent Builder DB/CAS 영향 | 실제 PostgreSQL Agent Builder 계약 검사 |
| `memory-postgres-contracts` | Memory DB/adapter 영향 | 실제 PostgreSQL Memory 계약 검사 |
| `ci-required` | 항상 | 필수 job 결과를 fail-closed로 집계 |
| `ci-control-review` | PR 생성·동기화 또는 명시적 재검증 | base 브랜치 정책으로 CI 제어 변경과 최신 승인 검증 |

`ci-required`는 선택된 job의 `success`만 허용한다. 선택된 job의 `failure`, `cancelled`, 비정상 `skipped`와 scope 결과 누락은 최종 실패다. 선택되지 않은 job의 의도된 `skipped`만 허용한다.

## CI 제어 신뢰 경계

PR workspace의 selector 결과만으로 required gate를 결정하지 않는다.

- 품질 게이트는 selector 실행 전에 `pr-quality-gate.yml`, `pr-ci-control-guard.yml`, `.github/actions/**`, `scripts/ci/**`, `tests/ci/**` 변경을 독립적으로 확인한다. 이 경로가 바뀌면 selector 출력과 무관하게 Client, Python service smoke, root, PostgreSQL 계약 검사와 Actions·Helm·Kubernetes·Terraform·Compose·Dockerfile 정적 검증을 모두 선택한다.
- 신뢰 가드는 base 브랜치에서 `.github/workflows/**`, `.github/actions/**`, `scripts/ci/**`, `tests/ci/**` 변경을 별도로 확인한다. rename은 이전 경로와 새 경로를 모두 검사하고, 변경 파일 전체를 열거하지 못하면 실패한다.
- CI 제어 변경은 PR 작성자가 아닌 write 이상 권한 보유자가 현재 head commit에 남긴 `APPROVED` review가 있어야 통과한다. 이전 commit 승인은 재사용하지 않는다.
- 승인 뒤 `/recheck-ci-control`을 PR conversation에 comment하면 base 브랜치 가드가 정책 status를 다시 계산한다.
- 동시성 제어는 이벤트와 comment body 조건을 통과한 `ci-control-review` job에만 적용한다. 일반 Linear/Codex/user comment는 기존 정책 검사를 취소하지 않으며, 새 PR head 또는 정확한 `/recheck-ci-control` 요청만 같은 PR의 이전 유효 검사를 교체한다.
- 승인 부재나 변경 파일 열거 누락 같은 정책 미충족은 PR head의 `trusted-ci-control/base-policy` status를 실패로 기록하되 evaluator job 자체는 정상 완료한다. `/recheck-ci-control`은 같은 head status를 다시 계산하므로 최초 `pull_request_target`의 실패 check run이 남아 병합을 막지 않는다. PR 번호 확인이나 status 기록 자체가 실패한 운영 오류만 evaluator job을 실패시킨다.
- 신뢰 가드는 PR source, test, build script를 checkout하거나 실행하지 않으며 repository secret을 사용하지 않는다.

가드를 최초로 추가하는 PR은 base 브랜치에 가드가 아직 없으므로 자기 자신을 보호할 수 없다. 최초 승격은 독립 review와 actionlint 결과를 수동으로 확인하고, 병합 뒤 probe PR에서 status 생성과 승인 재검증을 확인해야 한다.

## 변경 범위 규칙

| 변경 | 기본 검사 |
| --- | --- |
| 문서만 변경 | scope, Alembic graph, aggregate |
| `apps/client/**` | Client lint, typecheck, 관련 Vitest, build |
| `apps/gateway/**` | 대응 기능 test 또는 Gateway layer test |
| `apps/workflow_engine/**` | 대응 기능 test 또는 Workflow Engine layer test |
| `apps/shared/**` | Shared 대응 test와 실제 소비 서비스 관련 test |
| Log System task가 직접 소비하는 Shared service | Shared, Gateway, Workflow Engine, Log System 관련 test |
| Shared schema/DB model | Shared, Gateway, Workflow Engine, Log System, root 관련 test |
| `apps/shared/alembic/**` | 위 Python 범위와 PostgreSQL 계약 test |
| Knowledge runtime 경로 | Knowledge PostgreSQL 계약 test |
| schedule/external effect 경로 | Workflow PostgreSQL 계약 test |
| Agent Builder DB/CAS 경로 | Agent Builder PostgreSQL 계약 test |
| 품질 게이트 CI 제어 파일 | 각 서비스 smoke, Client smoke, PostgreSQL 계약 test, 전체 배포 정적 검증과 최신 독립 승인 |
| 기타 GitHub Actions workflow | 기존 영향 범위 검사와 최신 독립 승인 |
| 배포 workflow만 변경 | actionlint를 실행하고 runtime test는 선택하지 않음 |
| Helm/Kubernetes/Terraform 변경 | 변경 종류에 맞는 lint, render, validate 실행 |
| Docker Compose/Dockerfile 변경 | 변경 파일의 config 또는 build check 실행 |
| 알 수 없는 실행 경로 | Client와 Python smoke 범위로 fail-closed 확장 |

변경 경로가 없거나 분류할 수 없다고 해서 모든 도메인 검사를 생략하지 않는다.

## Python test 선택

`scripts/ci/select_pytest_targets.py`는 다음 우선순위를 사용한다.

1. 변경된 `test_*.py` 파일을 직접 실행한다.
2. source 파일명과 기능 token이 대응되는 test를 찾는다.
3. 직접 대응 test가 없으면 해당 layer/domain test 디렉토리로 확장한다.
4. 공통 CI 변경은 서비스 전체 suite 대신 명시된 smoke target을 사용한다.
5. schema, DB model, migration처럼 영향이 넓은 변경은 관련 서비스와 PostgreSQL 계약 범위로 확장한다.

Gateway job이 선택되면 기능 test와 별개로 소규모 architecture import-boundary suite를 항상 실행한다.

`manual`, `load`, `evaluation`, browser E2E는 PR unit target에서 자동 선택하지 않는다. 이들은 해당 이슈 또는 전체 회귀 절차에서 명시적으로 실행한다.

테스트 개수 자체보다 실행 시간과 영향 범위를 기준으로 판단한다. 예를 들어 Shared domain에 테스트 케이스가 많아도 실행 시간이 짧으면 domain fallback으로 유지할 수 있다.

## Client 검사

Client 영향이 있으면 다음을 실행한다.

```powershell
Set-Location apps/client
npm ci
npm run lint
npm run typecheck
npm run test -- --changed=<BASE_SHA> --passWithNoTests
npm run build
```

CI 제어 파일 변경은 dependency 기반 test가 0개일 수 있으므로 `proxy.test.ts` smoke를 추가 실행한다. 기존 ESLint warning은 MBA-252 범위이며 현재 gate는 error exit code를 기준으로 판정한다.

`package.json`, lockfile 또는 Client 공통 설정처럼 모든 test에 영향을 줄 수 있는 변경은 Vitest가 Client 전체 test를 선택할 수 있다. 이는 일반 기능 변경의 기본 동작이 아니라 공통 dependency/configuration 변경에 대한 의도된 확장이다.

## Alembic과 PostgreSQL

`scripts/ci/check_alembic_graph.py`는 migration module을 실행하지 않고 AST로 `revision`과 `down_revision`만 읽는다. 다음 상태는 모든 PR에서 실패한다.

- revision ID 중복
- 존재하지 않는 parent 참조
- revision cycle
- head가 0개 또는 2개 이상인 상태

DB 관련 변경에서는 graph 검사에 더해 disposable PostgreSQL upgrade와 다중 session 계약을 기존 reusable workflow로 실행한다.

- `.github/workflows/test-knowledge-runtime-postgres.yml`
- `.github/workflows/test-schedule-dispatch-postgres.yml`
- `.github/workflows/test-agent-builder-postgres.yml`
- `.github/workflows/test-memory-postgres.yml`

네 workflow는 PR에서는 통합 gate가 호출하고, `dev` push에서는 기존 post-merge 방어선으로 계속 실행한다. Knowledge workflow는 runtime candidate SQL뿐 아니라 durable ingestion의 동시 claim, lease 만료, fencing, heartbeat, late finalization과 DB wall clock 계약을 실제 PostgreSQL에서 검증한다. PostgreSQL 전용 파일은 일반 Gateway/Shared selector에서 제외해 skip 결과를 성공 근거로 사용하지 않는다.

## 검증 및 실패 재현

정상 개발 절차에서는 push 전에 변경 범위의 빠른 검사를 로컬에서 먼저 실행한다.

- Python: 변경 파일 lint와 직접 관련된 pytest
- Client: 변경 범위 lint, typecheck와 직접 관련된 Vitest
- CI·배포 설정: 변경된 workflow의 actionlint와 사용 가능한 로컬 정적 검사
- Migration: Alembic revision graph 검사

disposable PostgreSQL 계약, E2E, 전체 build처럼 시간이 오래 걸리거나 실행 환경에 의존하는 검사는 원격 CI를 판정 기준으로 사용한다. 로컬 검사가 통과해도 required CI를 생략하거나 우회하지 않는다. 변경과 무관한 도메인의 전체 회귀는 로컬에서 반복하지 않는다.

selector 또는 CI 제어 코드를 수정할 때는 다음 빠른 검사를 push 전에 실행한다. CI에서 추가 실패가 발생하면 해당 job과 도메인만 최소 범위로 재현한다.

먼저 비교할 commit SHA를 준비한다.

```powershell
$base = git rev-parse origin/dev
$head = git rev-parse HEAD
```

변경 범위를 확인한다.

```powershell
python -m scripts.ci.changed_scope --base $base --head $head
```

Alembic graph를 확인한다.

```powershell
python scripts/ci/check_alembic_graph.py
```

선택될 pytest target을 실행하지 않고 확인한다.

```powershell
python -m scripts.ci.select_pytest_targets `
  --component gateway `
  --base $base `
  --head $head `
  --broad false
```

CI helper 변경은 다음 범위로 검증한다.

```powershell
python -m pytest tests/ci -q
python -m ruff check scripts/ci tests/ci
actionlint .github/workflows/pr-quality-gate.yml .github/workflows/pr-ci-control-guard.yml
```

각 서비스 test 실행 명령은 repository `AGENTS.md`를 따른다. 전체 `scripts/test.sh`와 disposable PostgreSQL 계약은 일반적인 로컬 선행 검사가 아니며, 원격 CI 실패와 무관한 전체 회귀를 반복 실행하지 않는다.

## 배포 설정 검증

`deployment-config-validation`은 일반 배포 설정 변경에서는 변경된 종류만 검사한다. 품질 게이트 CI 제어 파일이 바뀌면 검증 명령 자체의 회귀를 놓치지 않도록 여섯 배포 검증기를 모두 실행한다.

- GitHub Actions: 일반 변경에서는 추가·수정·이름 변경된 workflow를 검사한다. CI 제어 변경에서는 기존 배포 workflow의 ShellCheck 부채와 분리된 안정적 smoke 대상으로 품질 게이트, 신뢰 가드와 네 PostgreSQL 계약 workflow를 고정 버전 actionlint로 검사한다.
- Helm: dependency lock 기반 build, 기본/production values lint와 template render
- Kubernetes: 목표 EKS `1.31`과 CI Go 1.25 도구체인에 맞춘 `kubeconform v0.7.0` strict schema 검증을 실행하며 cluster API에 접속하지 않음
- Terraform: 실제 Terraform 변경은 `infra/terraform`을 대상으로 format, backend 없는 init, validate를 실행한다. CI 제어만 변경된 경우에는 provider와 module lock 부채에 영향을 받지 않는 `tests/ci/fixtures/terraform-smoke`로 같은 명령 계약을 검증한다.
- Docker Compose: Compose 변경 또는 CI 제어 변경 시 tracked Compose 구성을 모두 해석한다. `compose.<variant>.yml`과 `docker-compose.<variant>.yml`은 같은 디렉터리의 기본 Compose 파일과 합성하고 선언된 profile을 활성화해 검사한다.
- Dockerfile: 일반 변경에서는 변경된 Dockerfile을 검사하고, CI 제어 변경에서는 tracked Dockerfile 전체에 BuildKit check를 실행한다.

CI 제어와 PostgreSQL workflow가 사용하는 공식 Action은 40자리 commit SHA로 고정한다. Action 내부 runtime은 Node 24 기반 공식 major를 사용한다. Client build의 Node 20은 현재 Docker runtime과 별도 제품 계약이므로 이 문서의 Action runtime 전환 대상이 아니다. AWS·Docker 배포 Action과 장기 credential 전환은 MBA-224/MBA-329가 소유한다.

## Cache와 artifact

- Client는 `package-lock.json` 기반 npm cache를 사용한다.
- Python은 uv dependency cache를 사용한다.
- Workflow Engine과 Log System은 기존 `uv.lock`을 사용한다. Gateway와 Shared의 독립 lock 정책은 별도 engineering 과제로 남아 있으며 cache가 재현성을 보장하지는 않는다.
- test selection state나 이전 성공 결과는 cache하지 않는다.
- 초기 gate는 별도 artifact를 업로드하지 않고 Actions log를 사용한다.
- DB dump, `.env`, raw payload, token과 credential은 cache나 artifact에 넣지 않는다.

## 실패 해석

| 실패 check | 우선 확인할 내용 |
| --- | --- |
| `change-scope` | base/head fetch, 잘못된 path, selector 단위 테스트 |
| `alembic-single-head` | 같은 parent에서 분기한 migration, 누락 merge revision |
| `python-lint` | 변경 Python 파일의 Ruff 오류 |
| `client-quality` | ESLint error, test fixture 타입, 영향 test, build |
| Python service job | Actions log에 출력된 실제 선택 target과 dependency 설치 |
| PostgreSQL contract | migration upgrade, race, 실제 SQL 계약 |
| `deployment-config-validation` | actionlint, Helm dependency/render, manifest, Terraform, Compose, Dockerfile 오류 |
| `ci-required` | 선택된 하위 job의 실패, 취소 또는 비정상 skip |
| `trusted-ci-control/base-policy` | CI 제어 경로 변경, 현재 head 승인 부재, reviewer 권한 확인 실패, 변경 파일 열거 누락 |

검사가 실패했을 때 required check를 해제해 우회하지 않는다. selector 누락이면 mapping과 해당 단위 테스트를 함께 보강한다.

## GitHub ruleset 적용

MBA-326의 기존 red 상태는 PR #546으로 해소되었고, MBA-328은 해당 변경이 포함된 `dev @ 29a2bcf8` 위로 rebase했다. MBA-328 workflow가 `dev`에 병합된 뒤 probe PR에서 실제 context를 확인한다. 확인 전에는 ruleset을 먼저 활성화하지 않는다.

1. `dev`와 `main` 모두 `PR Quality Gate / ci-required`를 required status check로 등록한다.
2. CI control 변경의 `trusted-ci-control/base-policy`가 non-control PR에서도 안정적인 success context를 만드는지 probe로 확인한 뒤 required 등록 방식을 확정한다.
3. check의 expected source를 실제 probe에서 확인한 GitHub Actions app으로 제한한다.
4. required check가 최신 base 기준으로 다시 실행되고 stale head 결과를 재사용하지 않도록 strict 정책을 적용한다.
5. 두 branch 모두 PR 경유, unresolved review conversation 해결, branch 삭제 방지와 non-fast-forward 방지를 요구한다.
6. `main`은 최소 1명의 독립 승인을 요구한다. `dev`의 일반 승인 수는 CI control 변경의 독립 승인 정책과 분리한다.
7. 일반 bypass는 추가하지 않는다. 감사 가능한 예외 절차는 MBA-271에서 별도로 결정한다.

merge queue는 초기 범위가 아니다. 추후 도입하면 `merge_group` event에서도 같은 aggregate check가 생성되는지 먼저 검증한다.
