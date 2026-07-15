# PR CI 품질 게이트

Status: Draft
Verified Against: feature/mba-274 @ f3bbbb3f

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
| `knowledge-postgres-contracts` | Knowledge runtime/DB 영향 | 실제 PostgreSQL Knowledge 계약 검사 |
| `workflow-postgres-contracts` | migration/schedule/external effect 영향 | 실제 PostgreSQL workflow 계약 검사 |
| `agent-builder-postgres-contracts` | Agent Builder DB/CAS 영향 | 실제 PostgreSQL Agent Builder 계약 검사 |
| `ci-required` | 항상 | 필수 job 결과를 fail-closed로 집계 |
| `ci-control-review` | PR 생성·동기화 또는 명시적 재검증 | base 브랜치 정책으로 CI 제어 변경과 최신 승인 검증 |

`ci-required`는 선택된 job의 `success`만 허용한다. 선택된 job의 `failure`, `cancelled`, 비정상 `skipped`와 scope 결과 누락은 최종 실패다. 선택되지 않은 job의 의도된 `skipped`만 허용한다.

## CI 제어 신뢰 경계

PR workspace의 selector 결과만으로 required gate를 결정하지 않는다.

- 품질 게이트는 selector 실행 전에 `pr-quality-gate.yml`, `pr-ci-control-guard.yml`, `.github/actions/**`, `scripts/ci/**`, `tests/ci/**` 변경을 독립적으로 확인한다. 이 경로가 바뀌면 selector 출력과 무관하게 Client, Python service smoke, root, PostgreSQL 계약 검사를 모두 선택한다.
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
| 품질 게이트 CI 제어 파일 | 각 서비스 smoke, Client smoke, PostgreSQL 계약 test와 최신 독립 승인 |
| 기타 GitHub Actions workflow | 기존 영향 범위 검사와 최신 독립 승인 |
| 배포 workflow만 변경 | PR 공통 불변식만 실행하고 배포 검증과 분리 |
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

세 workflow는 PR에서는 통합 gate가 호출하고, `dev` push에서는 기존 post-merge 방어선으로 계속 실행한다.

## 로컬 재현

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

CI helper 자체는 다음으로 검증한다.

```powershell
python -m pytest tests/ci -q
python -m ruff check scripts/ci tests/ci
actionlint .github/workflows/pr-quality-gate.yml .github/workflows/pr-ci-control-guard.yml
```

각 서비스 test 실행 명령은 repository `AGENTS.md`를 따른다. 전체 `scripts/test.sh`는 일반 PR의 기본 required check가 아니다.

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
| `ci-required` | 선택된 하위 job의 실패, 취소 또는 비정상 skip |
| `trusted-ci-control/base-policy` | CI 제어 경로 변경, 현재 head 승인 부재, reviewer 권한 확인 실패, 변경 파일 열거 누락 |

검사가 실패했을 때 required check를 해제해 우회하지 않는다. selector 누락이면 mapping과 해당 단위 테스트를 함께 보강한다.

## GitHub ruleset 적용

workflow가 `dev`에 병합되고 probe PR에서 실제 context가 확인된 뒤 다음을 적용한다.

1. `ci-required`와 base 정책 status를 required status check로 등록한다.
2. 두 check의 expected source를 실제 probe에서 확인한 GitHub Actions app으로 제한한다.
3. required check가 최신 `dev` 기준으로 다시 실행되도록 strict 정책을 적용한다.
4. 최소 1명의 승인, 최신 reviewable push 승인, unresolved review thread resolution을 필수로 한다.
5. 현재 PR 경유, branch 삭제 방지, non-fast-forward 방지와 no-bypass 정책을 유지한다.

merge queue는 초기 범위가 아니다. 추후 도입하면 `merge_group` event에서도 같은 aggregate check가 생성되는지 먼저 검증한다.
