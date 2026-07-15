# 엔터프라이즈 모델 라우팅 실험 구현 안내

Status: Draft

## 구현 구성

| 파일 | 역할 |
| --- | --- |
| `scripts/experiment_enterprise_request_routing.py` | 합성 입력 생성, 로그인, 배포 실행, 로그·정책 조회, 결과 보고서 생성 |
| `tests/experiments/test_enterprise_request_routing_experiment.py` | 50건 수량, 입력군 균형, 무작위 순서 재현, 배포 payload와 호출 상한 검증 |
| `docs/demo/enterprise-request-routing-experiment.md` | 실험 목적, 데이터셋, 합격 기준과 실행 방법 |

## 서버 독립성

스크립트는 로컬 Python에서 실행하지만 서버 DB를 읽지 않는다. 다음 API만 사용한다.

1. `POST /api/v1/auth/login`
2. `GET /api/v1/deployments/{deployment_id}/run-info`
3. `POST /api/v1/deployments/{deployment_id}/run`
4. `GET /api/v1/workflows/{workflow_id}/runs/{run_id}`
5. `GET /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/model-routing/policy`
6. `POST /api/v1/workflows/{workflow_id}/llm-nodes/{node_id}/model-routing/preview`

따라서 원격 서버에서도 같은 배포 ID와 데모 계정이 준비돼 있으면 `--base-url`만 바꿔 실행한다.

## 실패와 재시작

각 실행 후 `state.json`을 원자적으로 교체 저장한다. 프로세스가 중단되면 같은 `--run-name`과 `--resume`을 사용해 완료되지 않은 case부터 이어서 실행한다.

```powershell
python .\scripts\experiment_enterprise_request_routing.py `
  --mode execute `
  --base-url https://example.nodease.internal `
  --run-name enterprise-routing-server-v1 `
  --resume `
  --confirm-live
```

개별 실행이 실패하면 safe error code만 기록하고 다음 합성 입력을 계속 실행한다. 정책 점검 완료 대기가 제한 시간을 넘으면 해당 checkpoint에 오류를 남기되 전체 보고서를 생성한다.

## 비용 상한

사전 계산은 운영 요청마다 임베딩 1회와 답변 LLM 1회를 잡는다. 네 입력군, 입력군당 최대 두 후보, 후보당 대표 입력 다섯 개, Replay와 Judge를 각각 한 번으로 계산하고 10회 단위 정책 점검과 여유분을 추가한다. 후보당 다섯 건은 `ModelRoutingValidationPlanner.REPLAYS_PER_CANDIDATE`의 실제 제품 조건과 같다.

현재 50건 계획의 보수적 상한은 205회로 `--max-provider-calls 500`보다 작다. 이 값은 호출 횟수 상한이며 실제 비용 보증값은 아니다. 실제 비용은 정책의 월간 검증 한도 `$3`과 provider 사용량 로그로 별도 확인한다.
