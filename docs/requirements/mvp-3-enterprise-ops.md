# MVP 3: 최적화 및 엔터프라이즈 운영

## 목표

MVP 3는 MVP 1, 2에서 쌓은 실행/비용/권한/RAG/audit 데이터를 운영자가 실제로 활용할 수 있는 형태로 만든다.

결과물:

```text
기업용 AI Workflow / LLMOps 운영 MVP
  + 비용 최적화 추천
  + 배포 전 체크
  + workflow version diff
  + operations dashboard
  + trigger mode 정합성
  + 배포 재현성
```

## 재사용/의존 기반

| 기반 | 재사용 방식 |
| --- | --- |
| 기존 Moduly `workflow_deployments.graph_snapshot` | version diff와 deploy checklist |
| 기존 Moduly `llm_usage_logs` | cost recommendation |
| 기존 Moduly `workflow_runs` | failure/latency aggregation |
| MVP 1-2 `audit_logs` | policy block/permission change aggregation |
| MVP 2 RAG trace metadata | RAG risk and stale index check |
| MVP 2-0 organization membership | operations dashboard scope와 audit visibility의 active/suspended/removed member 필터. 제거된 member의 permission row는 cleanup되므로 dashboard는 과거 permission row에 의존하지 않는다. |
| 기존 Moduly Scheduler/Webhook/API 실행 | trigger별 운영 통계 |
| 기존 Moduly Docker/Helm/K8s | 배포 재현성 |

## 배포 권한과 이전 배포 활성화

현재 Moduly 기준 deployment API에는 `create`, `get`, `toggle`, `delete`가 있고 별도 `rollback` API는 없다. 하지만 `toggle`로 예전 deployment를 다시 active로 만들면, 같은 app의 다른 active deployment가 비활성화되고 `app.active_deployment_id`가 그 deployment로 바뀐다.

따라서 사용자는 "이전 배포로 되돌리기"처럼 사용할 수 있지만, 제품/코드 레벨에서는 아직 `rollback`이라는 명시 기능이 아니라 `deployment activate` 동작이다. MVP 계획에서는 `rollback`을 별도 permission으로 두지 않는다. Workflow `builder` 이상은 `deploy` 권한으로 deployment 생성/활성화/이전 배포 활성화를 수행할 수 있고, deployment 삭제나 권한 변경 같은 위험 작업은 `manager`의 `manage` 권한으로 제한한다. 이전 deployment를 다시 활성화하는 경우 `audit_logs.action='deployment.activate_previous'`로 남길 수 있다.

## 사용자 흐름

1. `builder` 권한 user가 workflow를 수정하고 배포를 시도한다.
2. Deploy checklist가 비용, 권한, PII, RAG 변경 위험을 보여준다.
3. 고비용 노드에 대해 저비용 모델 후보가 추천된다.
4. `builder` 권한 user가 model/prompt 변경을 적용한다.
5. Version diff에서 이전 배포 대비 변경을 확인한다.
6. 배포 후 운영 dashboard에서 비용/실패율/latency/policy block을 본다.
7. API/Webhook/Scheduler 실행이 올바른 trigger mode로 기록된다.
8. Docker Compose 또는 K8s 기준으로 동일 MVP를 재현한다.

## 추가 개발 범위

- deploy checklist API/UI. 결과는 `audit_logs.action='deployment.check'`와 `audit_logs.audit_metadata`에 저장
- workflow version diff
- cost recommendation rule
- cache candidate detection
- fallback/retry 최소 정책
- audit visibility permission API/UI와 `user_audit_permissions` additive grant
- operations dashboard raw-query aggregation
- trigger mode logging 정합성 수정
- Docker/K8s 실행 문서 정리

## 작업 순서

1. Trigger Mode 정합성

작업:

- API/Webhook/Scheduler/App 실행 context 정리
- log system trigger mode normalization 수정
- 기존 run 기록과 dashboard aggregation 기준 확정

검증:

- 각 trigger별 실행 후 `workflow_runs.trigger_mode` 정확성 확인

주의:

- 기존 문서상 REST API 실행은 `trigger_mode="api"`를 전달하지만 `DeploymentService.run_deployment()` 내부 `execution_context.trigger_mode`는 `"app"`으로 고정될 수 있다.
- Webhook 실행 context에는 `trigger_mode=webhook`이 들어가지만 log 정규화가 `webhook`을 정확히 매핑하지 않으면 fallback으로 `api`가 기록될 수 있다.
- Scheduler는 context에 `trigger_mode=schedule`을 넣지만 `workflow_runs.trigger_mode` enum 값은 `scheduler`라서 정규화 정책이 필요하다.

2. Version Diff

작업:

- deployment snapshot diff 유틸 작성
- prompt/model/config/knowledge base 변경 추출
- UI에서 이전 배포와 현재 draft 비교

검증:

- prompt 변경, model 변경, RAG source 변경이 diff에 표시

3. Deploy Checklist

작업:

- 예상 비용 계산
- 고비용 node 탐지
- 권한 위반 탐지. `builder`의 배포는 허용하고, `manage`가 필요한 작업은 차단한다.
- PII/confidential warning
- RAG stale index warning
- 모델 가격 누락 경고

검증:

- warning/block 구분
- 배포 차단 정책 적용 가능

4. Cost Recommendation

작업:

- high cost node rule
- cheaper model candidate rule
- prompt token warning
- cache candidate detection
- recommendation lifecycle event를 `audit_logs.action='recommendation.*'`와 `audit_logs.audit_metadata`에 저장

검증:

- 추천 결과가 실제 usage log 기반으로 생성
- 가격 정보 없는 모델은 추천 제외 또는 경고 처리

별도 `recommendation_events` table은 만들지 않는다. 추천을 장기 상태로 관리해야 하면 MVP 3 이후 schema extension으로 분리한다.

5. Audit Visibility

작업:

- `user_audit_permissions` migration/model/API 추가
- audit visibility team/user permission grant/revoke UI
- audit log search와 trace 조회에서 `team_audit_permissions`, `user_audit_permissions`, active organization membership 선검증 적용
- raw trace payload 조회는 `raw_auditor` 또는 audit `manager`와 `trace_visibility_policies`를 함께 평가

검증:

- active organization member에게 user direct audit visibility를 부여할 수 있음
- removed/suspended/non-member는 audit visibility permission row가 있어도 audit log와 raw trace 조회가 차단됨
- raw trace 조회 시도는 성공/실패 모두 `trace_payload_access_events`에 남음

6. Operations Dashboard

작업:

- model별 비용
- workflow별 비용
- user와 organization membership 상태별 실행량
- team별 집계는 현재 `team_memberships` 기준으로 제공
- failure rate
- latency p50/p95
- policy block count
- cache/fallback 후보 count
- deployment diff/check, recommendation, cache/fallback 관련 event 집계

검증:

- dashboard 집계가 raw log와 일치
- suspended/removed organization member의 과거 실행량은 보존하되, 현재 active member scope와 구분된다.
- removed member의 과거 실행량은 `organization_memberships`의 soft-removed row와 run/usage/audit raw data로 구분하고, cleanup된 team/direct permission row에 의존하지 않는다.
- historical team membership 재구성은 MVP 3 기본 범위가 아니다. 실행 시점 team snapshot이 필요해지면 `workflow_runs.trace_metadata` 또는 `audit_logs.audit_metadata` 확장으로 별도 결정한다.

dashboard API는 별도 aggregate table 없이 `organization_memberships`, `workflow_runs`, `workflow_node_runs`, `trace_payloads`, `llm_usage_logs`, `audit_logs` raw query로 시작한다.

7. Deployment Reproducibility

작업:

- Docker Compose 실행 절차 점검
- 필수 env 정리
- migration 실행 정책 문서화
- demo seed/fixture 작성
- K8s/Helm values에서 Nodease 추가 env 정리

검증:

- 새 환경에서 seed workflow 실행 가능

## 완료 기준

| 영역 | 완료 기준 |
| --- | --- |
| Deploy check | 실제 graph/log/policy/RAG 상태 기반 warning/block 표시. `builder` deploy 허용과 `manager` manage 제한을 구분 |
| Recommendation | 최소 rule-based 비용 절감 추천 동작 |
| Version diff | prompt/model/config/knowledge 변경 비교 |
| Audit visibility | `team_audit_permissions`와 `user_audit_permissions`가 audit log/raw trace 조회에 적용되고 active membership이 없으면 fail-closed |
| Ops dashboard | 비용, 실패율, latency, policy block, current membership state별 집계 |
| Trigger logging | api/webhook/scheduler/app이 정확히 기록 |
| Deployment | 로컬 Docker Compose 기준 재현 가능 |

## Demo Script

```text
1. `builder` 권한 user가 workflow를 수정한다.
2. Deploy checklist를 실행한다.
3. 비용/권한/RAG/PII warning을 확인한다.
4. 추천된 저비용 모델을 적용한다.
5. Version diff를 확인하고 배포한다.
6. API/Webhook/Scheduler로 실행한다.
7. Auditor 권한 user가 audit log와 redacted trace를 확인한다.
8. Raw trace 권한이 없는 auditor는 raw payload 조회가 차단되는지 확인한다.
9. Ops dashboard에서 비용/실패/latency/policy block과 active/suspended/removed member scope 구분을 확인한다.
```

## 테스트 범위

- trigger mode normalization
- deployment diff
- deploy checklist rules
- builder deploy / manager manage permission rule
- audit visibility team/user permission
- raw trace visibility fail-closed
- recommendation rules
- dashboard aggregation and membership state filtering
- Docker Compose smoke test

## MVP 3에서 하지 않을 것

- 정교한 ML 기반 품질 평가
- 실제 과금/결제
- 정식 SOC 2/ISO 인증 대응
- 완전한 MCP Gateway
- 전체 CDC 실시간 sync
