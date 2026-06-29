# Module List Access Operations UI

Status: Draft
Authority: Frontend Implementation Guide
Source of Truth: No
Verified Against: feature/mba-71 @ d2e791bab6920429bd3e4a15f50d5d3a14158ef6

## 목적

이 문서는 `/dashboard/mymodule`의 `내 모듈` 화면을 카드형 모듈 갤러리에서 team 기반 workflow 접근 현황을 확인하고 탐색할 수 있는 운영형 화면으로 바꾸기 위한 프론트 작업 기준을 정리한다.

현재 화면은 `AppCard` grid 중심이라 사용자가 "이 workflow에 내가 왜 접근 가능한지", "어느 team 권한으로 어떤 action이 가능한지", "배포 상태와 최근 실행 상태가 어떤지"를 한 번에 파악하기 어렵다.

이 작업의 목표는 모듈을 예쁘게 나열하는 것이 아니라, 반복 사용자가 빠르게 판단하고 행동할 수 있는 목록 화면을 만드는 것이다.

## 요청 유형 분류

이 문서는 구현 따라하기 문서에 가깝다.

- 화면/API/상태/권한별 동작을 구현 전에 정리한다.
- RBAC 개념 설명은 필요한 만큼만 포함한다.
- 실제 코드 수정은 이 문서 범위에 포함하지 않는다.

## 관련 기준 문서

| 영역 | 문서 |
| --- | --- |
| 프론트 문서 기준 | `docs/front/README.md` |
| Manager/member 홈·설정 분리 | `docs/front/rbac-mvp1-manager-member-home-settings.md` |
| Workflow 권한 UI | `docs/front/rbac-workflow-access-matrix.md` |
| RBAC API 연동 | `docs/front/rbac-permission-api-integration.md` |
| App/Workflow API | `docs/api/apps-workflows.md` |
| RBAC 정책 | `docs/data-model/rbac-permission-policy.md` |
| Active organization | `docs/architecture/auth-rbac.md` |

## 현재 상태

### 화면

현재 `/dashboard/mymodule`은 다음 구조다.

| 위치 | 현재 역할 |
| --- | --- |
| `apps/client/app/dashboard/mymodule/page.tsx` | 검색어 state, app 목록 로딩, 카드 grid 렌더링 |
| `apps/client/app/features/app/api/appApi.ts` | `/apps`, `/apps/explore`, app 생성/수정/삭제, deployment 조회/토글 API |
| `apps/client/app/features/app/components/AppCard.tsx` | 카드형 모듈 표시, 더보기 메뉴, 배포 토글, 배포 목록 모달 |

현재 필터는 이름 검색만 제공한다.

### 현재 App 응답으로 가능한 표시

`AppResponse` 기준으로 프론트가 바로 표시할 수 있는 값은 다음이다.

| 필드 | 화면 의미 |
| --- | --- |
| `name` | 모듈명 |
| `description` | 모듈 설명 |
| `workflow_id` | 권한 조회와 workflow 진입 기준 |
| `is_market` | 마켓 공개 여부 |
| `active_deployment_id` | 배포 존재 여부 |
| `active_deployment_type` | 배포 타입 |
| `active_deployment_is_active` | 활성 배포 on/off |
| `owner_name` | 소유자 표시 후보 |
| `created_at`, `updated_at` | 생성/수정 시각 |

### 현재 App 응답만으로 부족한 표시

사용자가 요청한 "어느 team으로서 어떤 권한으로 접근 가능한지"는 현재 `AppResponse`만으로는 알 수 없다.

| 필요한 정보 | 현재 API 상태 | 판단 |
| --- | --- | --- |
| effective workflow 권한 | `GET /workflows/{workflow_id}/permissions/me`로 가능 | FE에서 workflow별 추가 조회 필요 |
| team 권한 출처 | 현재 `permissions/me` 응답에 source team 목록 없음 | BE 응답 보강 필요 |
| user direct permission 출처 | 현재 `permissions/me` 응답에 source 정보 없음 | BE 응답 보강 필요 |
| 최근 실행 상태 | app 목록 응답에는 없음 | workflow run/status API 또는 summary API 필요 |
| 오류 상태 | app 목록 응답에는 없음 | 최근 run 실패/trace summary API 필요 |
| 배포 상세 상태 | active deployment 요약은 있음 | 상세 필터는 deployment API 추가 조회 필요 |

## 목표 화면

### 화면 성격

`내 모듈`은 "개요"라는 추상 용어보다 `운영 현황`이 더 적합하다.

이 화면은 사용자가 다음 질문에 답할 수 있어야 한다.

- 내가 접근 가능한 workflow는 무엇인가?
- 각 workflow에서 내가 할 수 있는 action은 무엇인가?
- 이 권한은 어느 team 또는 direct grant에서 온 것인가?
- 지금 배포되어 있는가?
- 최근 실행이 정상인지, 실패가 있는지?
- 누가 소유하거나 관리하는 workflow인가?
- 내가 바로 실행/수정/배포/권한 관리할 수 있는가?

### 권장 레이아웃

| 영역 | 목적 | 형태 |
| --- | --- | --- |
| 상단 헤더 | 페이지 목적과 주요 action | `DashboardPageHeader` 계열 |
| 운영 현황 | 실행 중/오류/배포/권한 상태를 빠르게 훑기 | compact list 또는 metric row |
| 검색/필터 바 | 반복 사용자의 탐색 속도 개선 | 검색 input + 필터 chips/select |
| 모듈 목록 | 카드 대신 정보 밀도 높은 table/list | row 기반 list |
| 상세 drawer | row 클릭 시 권한 출처, 배포, 최근 실행 상세 | drawer 또는 side panel |

카드 grid는 시각적으로는 편하지만 RBAC와 운영 상태를 비교하기에는 정보 밀도가 낮다. MVP1에서는 list/table 형태가 더 적합하다.

## 운영 현황 영역

상단의 "운영 현황"은 개별 카드를 크게 나열하지 말고, 빠르게 훑을 수 있는 리스트 또는 compact metric row로 둔다.

권장 항목은 다음이다.

| 항목 | 의미 | 현재 가능 여부 |
| --- | --- | --- |
| 배포 중 | `active_deployment_id`가 있고 `active_deployment_is_active === true` | 가능 |
| 배포 꺼짐 | active deployment는 있으나 inactive | 가능 |
| 미배포 | `active_deployment_id` 없음 | 가능 |
| 오류 있음 | 최근 실행 실패 또는 최근 배포 오류 | 추가 API 필요 |
| 내가 수정 가능 | `can_write === true` | `permissions/me` 조회 필요 |
| 내가 실행 가능 | `can_execute === true` | `permissions/me` 조회 필요 |
| 내가 관리 가능 | `can_manage === true` | `permissions/me` 조회 필요 |

예시 문구:

- `배포 중 3`
- `미배포 2`
- `최근 오류 1`
- `수정 가능 4`
- `실행 가능 5`
- `관리 가능 1`

`최근 오류`는 현재 app 목록만으로 계산하지 않는다. API가 없으면 placeholder 또는 "오류 상태 연동 예정"으로 표시해야 한다.

## 모듈 목록 row 설계

카드 대신 row 기반으로 바꾼다.

| 컬럼 | 표시 내용 | 근거 |
| --- | --- | --- |
| 모듈 | icon, name, description, updated_at | `AppResponse` |
| 소유자 | `owner_name` | 현재 응답은 manager 목록이 아니라 소유자/생성자 표시 후보 |
| 내 권한 | `viewer/operator/builder/manager` badge | `permissions/me` |
| 접근 경로 | team 이름 또는 direct grant | 추가 API 필요 |
| 배포 | 배포 중/꺼짐/미배포, type | `AppResponse` |
| 실행 상태 | 최근 성공/실패/실행 중 | 추가 API 필요 |
| 마지막 활동 | updated_at 또는 최근 run time | 일부 가능 |
| action | 열기, 실행, 수정, 배포, 권한 관리 | permission boolean |

### Action 노출 기준

| action | 조건 | UI |
| --- | --- | --- |
| 열기 | `can_read` | 기본 row click |
| 실행 | `can_execute` | 버튼 활성 |
| 수정 | `can_write` | 버튼 활성 |
| 배포 생성/활성화 | `can_deploy` | 버튼 활성 |
| 배포 삭제/위험 변경 | `can_manage` | 버튼 활성 |
| 권한 관리 | `can_manage` 또는 organization manager | 버튼 활성 |
| 앱 정보 수정 | organization owner/manager 또는 primary workflow `can_manage` | 버튼 활성 |

권한이 부족한 action은 숨김보다 disabled + tooltip을 우선 검토한다. 단, member에게 manager 전용 관리 action이 과하게 보이면 정보 노이즈가 커지므로 secondary menu 안에 제한적으로 둔다.

## 검색과 필터

### 검색

검색 대상:

- 모듈명
- 설명
- 소유자 이름
- team 이름

초기 구현에서는 모듈명/설명만 FE filter로 처리할 수 있다. team 이름 검색은 권한 출처 API가 생긴 뒤 가능하다.

### 필터

권장 필터는 다음이다.

| 필터 | 값 | 현재 가능 여부 |
| --- | --- | --- |
| 내 권한 | 전체, 조회, 실행, 수정, 관리 | `permissions/me` 필요 |
| 배포 상태 | 전체, 배포 중, 배포 꺼짐, 미배포 | 가능 |
| 실행 상태 | 전체, 정상, 오류, 실행 중 | 추가 API 필요 |
| 접근 경로 | 전체, team, direct grant | 추가 API 필요 |
| team | team 목록 | 추가 API 필요 |
| 소유자 | 소유자 이름 | `owner_name` 기반 제한적 가능 |
| 마켓 공개 | 전체, 공개, 비공개 | 가능 |

기본 필터 추천:

- 검색 input
- 권한 segmented control: `전체`, `실행 가능`, `수정 가능`, `관리 가능`
- 배포 상태 select: `전체`, `배포 중`, `미배포`
- 오류만 보기 toggle

`오류만 보기`는 API 연동 전에는 비활성 또는 숨김 처리한다.

## 권한 출처 표시

### 현재 가능한 최소 표시

현재는 effective permission만 표시한다.

예:

- `조회 가능`
- `실행 가능`
- `편집 가능`
- `관리자`

### 목표 표시

사용자가 원하는 정보는 아래 형태다.

```text
편집 가능
워크플로우 빌더팀 권한
```

또는 direct grant인 경우:

```text
실행 가능
개인 직접 권한
```

복수 team이 같은 workflow 권한을 주는 경우:

```text
관리자
AI 운영팀 외 2개 team
```

### 필요한 BE 응답 보강

`GET /api/v1/workflows/{workflow_id}/permissions/me` 응답에 source 정보를 추가하는 방식을 권장한다.

예시:

```json
{
  "workflow_id": "...",
  "auth_state": "builder",
  "can_read": true,
  "can_write": true,
  "can_execute": true,
  "can_deploy": false,
  "can_manage": false,
  "sources": [
    {
      "type": "team",
      "team_id": "...",
      "team_name": "워크플로우 빌더팀",
      "auth_state": "builder"
    },
    {
      "type": "user",
      "user_id": "...",
      "auth_state": "operator"
    }
  ]
}
```

MVP1에서 BE 보강 없이 FE만 진행한다면 source UI는 노출하지 않고 `권한 출처 연동 예정`으로 문서에 남긴다.

## 실행 상태 표시

사용자가 말한 "실행중이고 오류고 그런 정보"는 workflow runtime 상태다. 현재 `AppResponse`에는 없다.

권장 상태:

| 상태 | 의미 |
| --- | --- |
| 실행 중 | 최근 run이 running/pending |
| 정상 | 최근 run이 success |
| 오류 | 최근 run이 failure/error |
| 기록 없음 | run이 없음 |

필요한 API 선택지는 다음이다.

| 선택지 | 설명 | 장점 | 단점 |
| --- | --- | --- | --- |
| A. row별 run API 호출 | 각 workflow별 `/runs?limit=1` 호출 | BE 변경 적음 | N+1 호출 |
| B. module list summary API 추가 | app 목록과 권한/배포/최근 run 요약을 한 번에 반환 | 화면에 가장 적합 | BE 작업 필요 |
| C. 운영 현황만 후속 처리 | 우선 배포/권한만 표시 | FE 범위 작음 | 사용자가 원하는 실행 상태 부족 |

추천은 B다. `내 모듈`은 운영형 목록이므로 API가 화면 단위 summary를 제공하는 편이 장기적으로 맞다. 단, MBA-71 내 FE-only로 빠르게 가야 하면 A 또는 C로 제한한다.

## API 연동 설계

### FE-only 1차 구현

1차 구현은 현재 API로 가능한 범위만 다룬다.

```text
GET /api/v1/apps
-> app list
-> workflow_id 있는 app마다 GET /api/v1/workflows/{workflow_id}/permissions/me
-> app + effective permission merge
-> 검색/권한/배포 필터 적용
```

1차 구현에서 가능한 것:

- 카드 grid를 list/table로 전환
- 소유자 이름 표시
- 배포/미배포/배포 off 표시
- effective permission 표시
- 권한 기반 action disabled
- 이름/설명 검색
- 배포 상태 필터
- 권한 필터

1차 구현에서 하지 않는 것:

- team별 권한 출처 표시
- 최근 실행 오류/실행 중 표시
- team 필터
- 오류만 보기

### 목표 API 보강 제안

장기적으로는 다음 API가 필요하다. 이 endpoint는 프론트 작업 문서의 미승인 제안이며, `docs/api/`에 반영되기 전까지 구현 기준이나 API 계약으로 취급하지 않는다.

```text
GET /api/v1/apps/operations
```

응답 예시:

```json
[
  {
    "app": {
      "id": "...",
      "name": "고객 문의 분류",
      "description": "...",
      "workflow_id": "...",
      "owner_name": "어드민",
      "updated_at": "..."
    },
    "permission": {
      "auth_state": "builder",
      "can_read": true,
      "can_write": true,
      "can_execute": true,
      "can_deploy": false,
      "can_manage": false,
      "sources": []
    },
    "deployment": {
      "state": "active",
      "type": "webhook"
    },
    "latest_run": {
      "state": "success",
      "started_at": "...",
      "finished_at": "..."
    }
  }
]
```

이 API는 FE에서 N+1 permission/run 조회를 줄이고, 검색/필터를 서버로 넘길 수 있게 한다.

## 화면 상태

| 상태 | UI |
| --- | --- |
| loading | table skeleton, 운영 현황 skeleton |
| empty | "접근 가능한 모듈이 없습니다" + 생성 권한이 있으면 새 모듈 CTA |
| no search result | 필터 초기화 버튼 |
| permission fetch partial failure | 해당 row에 `권한 확인 실패` badge |
| deployment unknown | `배포 상태 확인 필요` |
| run status unavailable | 실행 상태 컬럼을 숨기거나 `연동 예정` 표시 |
| API error | 전체 실패 banner와 retry |

## Manager/member 차이

| 기능 | manager | member |
| --- | --- | --- |
| 전체 모듈 조회 | organization scope + read 가능 목록 | read 가능 목록 |
| team 권한 출처 | 표시 | 표시 |
| team 필터 | 가능 | 본인이 속한 team 기준만 가능 |
| 권한 관리 action | 가능 | 숨김 |
| 배포 생성/활성화 action | `can_deploy` | 권한 있을 때만 가능 |
| 배포 삭제/위험 변경 action | `can_manage` | 권한 있을 때만 가능 |
| 새 모듈 생성 | organization policy에 따라 가능 | 현재 앱 생성 권한 정책 확인 필요 |

`새 모듈` 버튼은 현재 UI에 항상 보인다. 하지만 RBAC 화면으로 정리하려면 생성 권한 정책을 확인해야 한다. `POST /api/v1/apps`는 active organization scope만 요구하고 생성자에게 manager 권한을 부여한다. 따라서 member에게도 새 모듈 생성을 허용할지, manager/builder로 제한할지는 제품 결정이 필요하다.

## 적용 선택지

### 지금 적용

- `내 모듈`을 list/table 중심으로 재구성
- `DashboardPageHeader`, `DashboardPanel` 같은 dashboard 공통 UI 재사용
- app list + workflow permission merge
- 배포 상태, 소유자, 권한 badge 표시
- 검색/권한/배포 필터
- 권한별 action enable/disable

### 짧게 소개하고 보류

- team 권한 출처 표시
- 실행 중/오류 상태 표시
- 오류만 보기 필터
- team 필터
- 운영 현황의 최근 실행 지표

이 항목들은 API 보강 전까지 정확한 값을 만들기 어렵다.

### 이번 범위에서 제외

- 전체 리브랜딩
- 조직 전환 UI 완성
- organization membership 기반 member 관리
- 서버 사이드 pagination/search/filter
- workflow run observability 상세 화면 개편

## 구현 단계 초안

1. `ModuleAccessRow` view model을 정의한다.
2. `appApi.listApps()` 결과를 가져온다.
3. `workflow_id`가 있는 app에 대해 `permissions/me`를 병렬 조회한다.
4. permission 실패는 row 단위 error로 보존한다.
5. deployment 상태와 permission 상태로 운영 현황 값을 계산한다.
6. 기존 `AppCard` grid를 `ModuleAccessTable` 또는 `ModuleAccessList`로 교체한다.
7. 검색, 권한 필터, 배포 필터를 추가한다.
8. row action을 permission boolean 기준으로 제어한다.
9. team 출처와 실행 상태는 API 보강 TODO로 남긴다.

## QA 체크리스트

- [ ] localStorage에 active organization이 없어도 `/dashboard/mymodule` 직접 진입이 400 없이 동작한다.
- [ ] manager는 모듈 목록에서 소유자 이름, 배포 상태, 권한 badge를 볼 수 있다.
- [ ] member는 접근 가능한 모듈만 볼 수 있다.
- [ ] `viewer`는 수정/실행/배포 action이 막힌다.
- [ ] `operator`는 실행 가능, 수정 불가로 표시된다.
- [ ] `builder`는 수정/실행 가능으로 표시된다.
- [ ] `manager`는 권한 관리 action이 가능하다.
- [ ] 미배포 모듈과 배포 중 모듈을 필터링할 수 있다.
- [ ] 검색어로 모듈명/설명을 필터링할 수 있다.
- [ ] 권한 조회 실패 row가 전체 목록을 깨지 않는다.
- [ ] 실행 상태/오류 상태는 API가 없으면 허위로 표시하지 않는다.

## 남은 결정

| 결정 | 질문 | 권장 |
| --- | --- | --- |
| team 권한 출처 API | `permissions/me`에 `sources`를 추가할까? | 추가 권장 |
| 운영 summary API | `/apps/operations` 같은 화면 전용 summary API를 만들까? | 장기적으로 권장 |
| member의 새 모듈 생성 | member도 app을 만들 수 있는가? | 제품 결정 필요 |
| 실행 상태 연동 | 최근 run API를 row별 호출할까, summary API로 묶을까? | summary API 권장 |
| 목록 형태 | table vs dense list | 운영 화면이면 dense table/list 권장 |

## 구현 요청 프롬프트

아래 프롬프트를 다음 구현 작업 요청으로 사용할 수 있다.

```text
MBA-71의 `/dashboard/mymodule` 화면을 카드형 모듈 grid에서 team/RBAC 기반 운영형 모듈 목록으로 개편해줘.

목표:
- 사용자가 각 모듈/workflow에 대해 어떤 권한으로 접근 가능한지 한눈에 볼 수 있어야 함.
- 카드 grid보다는 정보 밀도 높은 list/table 중심 UI로 바꿀 것.
- 상단에는 "개요" 대신 `운영 현황` 성격의 compact summary를 배치할 것.
- 모듈별 소유자 이름, 배포/미배포/배포 off 상태, 내 effective permission badge를 표시할 것.
- 검색과 필터를 제공할 것.

현재 API로 구현할 범위:
- `GET /api/v1/apps`로 app list 조회.
- 각 app의 `workflow_id`가 있으면 `GET /api/v1/workflows/{workflow_id}/permissions/me`로 내 effective permission 조회.
- app + permission을 merge해서 row view model을 만들 것.
- 배포 상태는 `active_deployment_id`, `active_deployment_type`, `active_deployment_is_active`로 계산할 것.
- 소유자 표시는 현재 `owner_name`을 사용할 것. `owner_name`은 RBAC `manager` 목록이 아니다.
- 권한 필터: 전체, 실행 가능, 수정 가능, 관리 가능.
- 배포 필터: 전체, 배포 중, 배포 꺼짐, 미배포.
- 검색 대상: 모듈명, 설명.
- permission 조회 실패는 전체 화면 실패로 만들지 말고 row에 `권한 확인 실패`로 표시할 것.

아직 구현하지 말고 TODO로 남길 범위:
- 어느 team 권한으로 접근 가능한지 표시.
- user direct permission 출처 표시.
- 실행 중/오류/최근 실행 상태 표시.
- team 필터, 오류만 보기 필터.

이 TODO는 현재 API 응답만으로 정확히 구현하기 어렵다. 문서 기준은 `docs/front/module-list-access-operations-ui.md`를 따른다.

UI/UX 기준:
- SaaS 운영 도구처럼 조용하고 정보 밀도 있게 만들 것.
- landing/marketing hero처럼 크게 꾸미지 말 것.
- 버튼은 권한 boolean에 따라 disabled/hidden을 결정하고, disabled일 때 이유를 tooltip 또는 보조 문구로 설명할 것.
- manager/member 모두 같은 목록을 보되 action 가능 여부가 권한에 따라 달라지게 할 것.
- 직접 QA는 manager `dev@moduly.app`, member `hyeyeon@moduly.app`로 확인할 것.

검증:
- `npx eslint app/dashboard/mymodule/page.tsx app/features/app/api/appApi.ts`
- `npm run build`
- localStorage에서 `moduly_active_organization_id`를 지운 뒤 `/dashboard/mymodule` 직접 진입해도 400이 나지 않아야 함.
```
