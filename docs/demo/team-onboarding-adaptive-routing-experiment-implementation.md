# 팀별 온보딩 적응형 모델 라우팅 실험 구현 가이드

Status: Draft

## 문서 유형

이 문서는 **구현 따라하기 문서**다. 실험의 기획 의도보다, 같은 실험을 로컬 또는
원격 서버에서 실제로 준비하고 실행하고 실패를 진단하는 방법에 집중한다.

## 현재 상태

기존 `팀별 온보딩 문서 접근 제어` workflow는 회사 공통, 플랫폼개발팀, 영업팀,
재무팀 PDF를 같은 LLM node의 Knowledge Base로 사용한다. 원본 workflow는 권한에
따른 검색 후보 차단을 보여 주지만 자동 모델 라우팅은 꺼져 있다.

실험용 복제본 `팀별 온보딩 적응형 모델 라우팅`은 원본 graph를 깊은 복사한 뒤 다음
설정만 바꾼다.

| 설정 | 실험값 |
| --- | --- |
| workflow id | `10200000-0000-0000-0000-000000000508` |
| deployment id | `10200000-0000-0000-0000-000000000608` |
| target node | `llm-answer` |
| 기본 모델 | `gpt-5.6-luna` |
| 자동 모델 라우팅 | ON |
| 정책 점검 주기 | 5회 |
| 월간 모델 검증 한도 | $3 |
| 최대 입력군 | 6개 |
| 제외 모델 | `gpt-5.6-sol` |
| 입력군 초안 | 공통 계정·보안, 플랫폼 접근, 영업 지원 |

## 목표 상태

1. 빌더가 아직 배포하지 않은 workflow draft에서도 입력군을 생성·수정·삭제한다.
2. 첫 terminal 운영 실행이 policy를 만들 때 초안 UUID를 보존해 DB 입력군으로 승격한다.
3. 원격 스크립트가 DB에 직접 연결하지 않고 인증 배포 API만 61회 호출한다.
4. 재무 트렌드를 자동 발견하고, 영업 트렌드를 휴면시킨 뒤 다시 활성화한다.
5. 모델 Replay/Judge 검증, 실제 라우팅 모델, RAG 출처, 정책 버전을 보고서로 남긴다.

스크립트는 16·36·56회 구간에서 비동기 Replay 검증이 끝날 때까지 기다린다. 마지막
실행 뒤에도 기본 15초를 기다린 후 진행 중인 검증 batch가 있으면 terminal 상태까지
확인한다. 따라서 실행 직후 아직 저장되지 않은 정책 상태를 최종 결과로 오인하지 않는다.

적응형 입력군은 신규 trend 발견 때 0.50 경계를 사용한다. 실제 운영 관찰과 runtime
라우팅은 자동 입력군 0.55, 직접 등록 입력군 0.60을 사용한다. Runtime은 centroid 하나가
아니라 대표 문의와 신뢰 가능한 최근 관찰 vector를 최대 8개까지 비교한다.

## 파일 책임

| 파일 | 책임 |
| --- | --- |
| `apps/shared/services/model_routing_cohort_drafts.py` | node graph 안의 입력군 초안 CRUD와 제외 모델 정규화 |
| `apps/gateway/api/v1/endpoints/workflow.py` | 배포 전·후 입력군 API 경계를 하나로 제공 |
| `apps/workflow_engine/services/model_routing_policy_store.py` | 초안을 첫 policy의 DB cohort로 승격하고 실패 시 재시도 |
| `apps/shared/db/demo_seed.py` | 원본 workflow 복제본, Luna, 입력군 3개, 권한과 배포 seed |
| `scripts/experiment_team_onboarding_adaptive_routing.py` | 원격 로그인, 61회 실행, 로그·policy 수집, 보고서 생성 |
| `tests/experiments/test_team_onboarding_adaptive_routing.py` | 데이터 순서와 provider 호출 상한 계약 |

## 처리 흐름

```text
workflow draft에서 입력군 저장
  -> graph node의 model_routing_policy.cohort_drafts에 stable UUID 저장
  -> 자동 라우팅 설정을 포함해 배포
  -> 첫 terminal 운영 실행
  -> persisted policy 생성
  -> 대표 문의 embedding
  -> 같은 UUID의 manual cohort DB row 생성
  -> 운영 입력 관찰 및 입력군 매칭
  -> 5회마다 policy refresh
  -> 월 $3 안에서 후보 Replay/Judge 검증
  -> gate를 통과한 모델만 cohort rule에 연결
```

초안 저장에서는 embedding을 호출하지 않는다. 배포 전에 외부 provider 장애 때문에
사용자 설정 저장이 막히는 일을 피하기 위해서다. 첫 승격에서 embedding이 실패하면
workflow 자체는 성공시키고, 다음 성공 운영 실행에서 아직 승격되지 않은 초안을 다시
처리한다.

## 원격 서버 준비 조건

- Gateway, Workflow Engine, Log System worker, Redis, PostgreSQL이 실행 중이어야 한다.
- 최신 migration이 적용되어 Alembic head가 하나여야 한다.
- `demo` profile seed가 적용되어야 한다.
- demo seed의 실제 OpenAI credential이 `verified` 상태여야 한다.
- 실제 API key와 `ENCRYPTION_KEY`는 서버 환경변수로만 제공한다.
- `gpt-5.6-luna`가 실제 credential에서 호출 가능해야 한다.

스크립트는 credential 원문을 인자로 받지 않는다. 데모 계정 비밀번호도
`NODEASE_DEMO_PASSWORD` 환경변수에서만 읽는다.

## 실행 방법

PowerShell 기준 사전 점검:

```powershell
$env:NODEASE_DEMO_PASSWORD = '<demo password>'
python .\scripts\experiment_team_onboarding_adaptive_routing.py `
  --mode preflight `
  --base-url http://localhost
```

실제 provider 호출 실행:

```powershell
python .\scripts\experiment_team_onboarding_adaptive_routing.py `
  --mode execute `
  --base-url http://localhost `
  --confirm-live
```

원격 서버에서는 `--base-url https://<server>`만 바꾼다. 실행은 최대 500 provider
호출의 보수적 상한과 120분 제한을 먼저 확인한다. 중단된 동일 실행을 이어갈 때는
같은 `--run-name`과 `--resume`을 사용한다.

## 생성 결과

기본 결과 경로:

```text
reports/model-routing/team-onboarding/<run-name>/
  state.json
  result.json
  report.md
```

- `state.json`: 매 실행 뒤 원자적으로 갱신하는 재개용 checkpoint
- `result.json`: 최종 구조화 결과
- `report.md`: 사람이 읽는 결과와 입력 순서, RAG 근거, 정책 상태 변화

보고서에는 실제 비밀번호, API key, credential 설정, 원문 Knowledge chunk, 운영 고객
payload를 넣지 않는다. 실험 스크립트가 자체 생성한 합성 질문만 표시한다.

## 실패 해석

| 실패 | 의미 | 확인할 곳 |
| --- | --- | --- |
| 시드 입력군 3개 없음 | demo seed 또는 draft cohort 저장이 적용되지 않음 | policy GET 응답의 `adaptive.cohorts` |
| `run_id` 없음 | Gateway와 Workflow Engine 실행 응답 계약이 오래됨 | 배포 run API와 task 반환값 |
| Luna 호출 실패 | catalog 등록과 실제 provider 지원은 별개 | credential model relation과 provider 응답 |
| RAG 출처 없음 | 권한 차단, 인덱싱 실패 또는 trace 출처 요약 누락 | node trace의 RAG summary |
| 자동 입력군 미발견 | 재무 입력이 기존 centroid에 매칭됐거나 두 window/5 distinct 조건 미달 | observation match와 cohort 상태 |
| 모델이 계속 동일 | 후보 Replay/Judge gate 미통과, 예산 부족 또는 credential 제한 | `adaptive.latest_batch`, evidence, budget |

## 완료 기준

- draft cohort API와 UI test가 통과한다.
- 첫 policy 생성과 승격 재시도 test가 통과한다.
- 제외 모델이 runtime/validation/refresh 후보에 들어가지 않는다.
- demo seed 복제 graph의 RAG·prompt·일반 parameter가 원본과 같다.
- 원격 preflight가 workflow, input schema, 입력군 3개를 확인한다.
- 실제 실행 보고서가 61개 run id, 모델, 입력군, RAG 출처, policy version을 기록한다.
- 재무 자동 발견과 영업 휴면·재활성화가 실제 결과로 확인되거나, 실패 이유가 근거와
  함께 보고서에 남는다.
