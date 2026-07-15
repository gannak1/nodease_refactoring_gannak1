# Git Convention

## Purpose

이 문서는 Nodease 개발 팀의 Git 사용 규칙을 정의한다.

목표는 다음과 같다.

- 브랜치와 커밋 이력을 보고 변경 의도를 빠르게 파악한다.
- PR 리뷰와 배포 추적을 쉽게 만든다.
- 충돌, 강제 push, 불명확한 커밋 메시지로 인한 협업 비용을 줄인다.

## Branch Strategy

기본 브랜치는 다음과 같이 사용한다.

```text
main    : 운영 배포 기준 브랜치
dev     : 다음 배포 후보가 모이는 통합 브랜치
feature : 기능 개발 브랜치
fix     : 버그 수정 브랜치
hotfix  : 운영 긴급 수정 브랜치
docs    : 문서 변경 브랜치
chore   : 설정, 빌드, 의존성, 기타 작업 브랜치
```

브랜치 이름은 다음 형식을 사용한다.

```text
<type>/<short-description>
```

예시:

```text
feature/workflow-budget-alert
feature/rag-document-lineage
fix/login-token-refresh
fix/docker-https-healthcheck
hotfix/gateway-migration-heads
docs/git-convention
chore/update-client-dependencies
```

브랜치 이름 규칙:

- 영어 소문자와 숫자를 사용한다.
- 단어 구분은 `-`를 사용한다.
- 공백, 한글, `_`, 대문자는 사용하지 않는다.
- 작업 범위가 명확히 드러나게 짧게 작성한다.

## Commit Message

커밋 메시지는 Conventional Commits 형식을 따른다.

```text
<type>(<scope>): <summary>
```

`scope`는 선택사항이다.

커밋 제목(summary)은 한국어로 작성한다.

```text
<type>: <summary>
```

사용 가능한 type:

```text
feat     : 새 기능
fix      : 버그 수정
docs     : 문서 변경
style    : 포맷, 세미콜론, CSS 등 동작 변경 없는 스타일 수정
refactor : 동작 변경 없는 코드 구조 개선
test     : 테스트 추가 또는 수정
chore    : 빌드, 설정, 패키지, 기타 유지보수
perf     : 성능 개선
ci       : CI/CD 설정 변경
revert   : 이전 커밋 되돌리기
```

scope 예시:

```text
client
gateway
workflow-engine
log-system
sandbox
shared
docker
docs
rag
rbac
audit
trace
```

좋은 커밋 메시지 예시:

```text
feat(client): add workflow budget alert panel
fix(gateway): reject unauthorized workflow execution
fix(docker): use alembic heads for gateway migration
docs: add git convention
test(shared): add permission schema regression tests
chore(client): update Next.js build configuration
```

나쁜 커밋 메시지 예시:

```text
fix
update
wip
작업함
asdf
bug fix
final
```

커밋 작성 규칙:

- summary는 명령형 현재시제로 작성한다.
- summary 첫 글자는 소문자로 작성한다.
- summary 끝에 마침표를 붙이지 않는다.
- 하나의 커밋은 하나의 논리적 변경만 담는다.
- secret, API key, token, credential 원문은 절대 커밋하지 않는다.

## Commit Body

변경 이유나 영향이 필요한 경우 body를 추가한다.

```text
fix(gateway): use alembic heads for migration

Gateway failed to start when multiple Alembic heads existed.
Using heads allows a fresh deployment database to apply all active heads.
```

Breaking change가 있으면 footer에 명시한다.

```text
feat(api): change workflow run response schema

BREAKING CHANGE: clients must read run_id from data.run_id instead of id.
```

## Pull Request

PR 제목은 커밋 메시지와 같은 형식을 사용한다.

```text
feat(client): add workflow budget alert panel
fix(docker): repair https deployment healthchecks
docs: add git convention
```

PR 본문은 아래 템플릿을 사용한다.

```md
## Summary

-

## Changes

-

## Test

- [ ] 실행한 테스트:
- [ ] 실행하지 못한 테스트와 이유:

## Risk

-

## Screenshot / Demo

-
```

PR 규칙:

- PR은 가능한 작게 유지한다.
- 기능 변경, API 변경, UI 변경, DB 변경은 PR 본문에 명확히 적는다.
- API 계약 변경 시 관련 문서를 함께 수정한다.
- UI 변경 시 스크린샷 또는 짧은 확인 내용을 남긴다.
- 테스트를 실행하지 못했으면 이유를 반드시 적는다.

## Merge Rule

기본 머지 방식은 squash merge를 사용한다.

Squash merge 메시지는 PR 제목과 같은 형식을 사용한다.

```text
feat(client): add workflow budget alert panel
```

머지 전 확인사항:

- PR 제목이 convention을 따른다.
- 불필요한 `console.log`, debug 코드가 없다.
- secret 값이 포함되어 있지 않다.
- 관련 테스트 또는 수동 검증 결과가 PR에 적혀 있다.
- 문서 변경이 필요한 경우 문서가 함께 수정되어 있다.

## Rebase And Sync

작업 브랜치는 최신 `dev`를 기준으로 자주 동기화한다.

```bash
git switch dev
git pull origin dev
git switch feature/my-work
git rebase dev
```

충돌 해결 후:

```bash
git add <resolved-files>
git rebase --continue
```

이미 원격에 공유된 브랜치를 force push 해야 하면 반드시 `--force-with-lease`를 사용한다.

```bash
git push --force-with-lease origin feature/my-work
```

## Hotfix Flow

운영 긴급 수정은 `main`에서 분기한다.

```bash
git switch main
git pull origin main
git switch -c hotfix/<short-description>
```

수정 후 `main`으로 PR을 만들고, 머지 후 `dev`에도 반영한다.

```bash
git switch dev
git pull origin dev
git merge main
git push origin dev
```

## Do Not

다음은 금지한다.

- `main`에 직접 push
- `dev`에 리뷰 없이 직접 push
- secret, API key, token, credential 원문 커밋
- `.env` 파일 커밋
- 대규모 리팩터링과 기능 변경을 한 PR에 섞기
- 의미 없는 커밋 메시지 사용
- 공유 브랜치에 무분별한 `git push --force`
- 사용자 변경사항을 확인 없이 되돌리기

## Quick Copy

새 기능 작업:

```bash
git switch dev
git pull origin dev
git switch -c feature/<short-description>
```

버그 수정:

```bash
git switch dev
git pull origin dev
git switch -c fix/<short-description>
```

커밋:

```bash
git add <files>
git commit -m "feat(client): add workflow budget alert panel"
```

푸시:

```bash
git push origin feature/<short-description>
```

최신 dev 반영:

```bash
git switch dev
git pull origin dev
git switch feature/<short-description>
git rebase dev
```
