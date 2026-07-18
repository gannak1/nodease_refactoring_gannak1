# Judge-first 80건 4-arm 경제성 실험

Status: Draft

## 목적

같은 80개 synthetic 요청을 아래 네 방식으로 실행해 자동 모델 라우팅의 품질·비용·시간 trade-off를 확인한다.

| Arm | 고정 조건 |
| --- | --- |
| `high_fixed` | `gpt-5.4` |
| `mid_fixed` | `gpt-5.4-mini` |
| `low_fixed` | `gpt-4o-mini` |
| `automatic` | `judge_bootstrap_incremental_v1`의 실제 Runtime Judge/local router 선택 |

총 workflow 실행은 `80 x 4 = 320회`다. 각 요청의 네 출력은 arm, 모델, 비용, 지연, 실행 순서를 숨긴 뒤 별도 품질 Judge가 한 번에 평가한다. 품질 Judge 80회 비용은 제품 운영 비용과 분리한다.

## 데이터셋과 workflow

실행기와 계약 테스트:

- `scripts/experiment_judge_first_economics_80.py`
- `tests/experiments/test_judge_first_economics_80.py`

데이터셋은 중복 없는 요청 80개이며 다음 축을 모두 포함한다.

- 입력 구조: `flat_text`, `nested_ticket`, `conversation`, `batch_record` 각 20개
- 입력 길이: `short`, `medium`, `long`, `very_long` 각 20개
- 예상 난이도: `economy`, `balanced`, `advanced`
- 내용: 제품 안내, 계정·권한, 재무, 보안·개인정보, 장애, 데이터 거버넌스, 계약, 분석, 연동, 위험 분류

길이 차이는 의미 없는 반복문이 아니라 확인 전 배경, 운영 제약, 승인 조건, 후속 질문 같은 실제 처리 맥락으로 만든다. Workflow는 네 payload 구조를 하나의 LLM 노드 입력으로 정규화하고 동일 JSON 계약을 후속 추출·분기 노드에 전달한다.

## 측정값

- 품질: blind Judge 평균, 계약 통과율, 요청별 고가 대비 승·무·패, 10점 이상 심각 회귀
- 비용: 처리 모델 비용, Runtime Judge 비용, 총 제품 비용, 고가 대비 절감액·절감률
- 시간: LLM 노드 시간, workflow end-to-end 평균과 P95, 고가 대비 변화
- 운영성: workflow 성공률, JSON schema 통과율, fallback, 자동 선택 모델 분포, local router takeover
- 세그먼트: 난이도, 입력 구조, 입력 길이, 업무 영역별 동일 지표

품질 손실을 달러로 임의 환산하지 않는다. 대신 `고가 대비 총 절감액 / 평균 품질 손실 점수`를 함께 제공한다. 실제 금전 손실을 계산하려면 품질 1점 또는 실패 1건의 사업 가치가 별도로 필요하다.

## Trade-off gate

다음 조건을 모두 만족할 때만 합리적인 trade-off로 판정한다.

- 고가 고정 대비 총 제품 비용이 감소한다.
- 평균 품질 손실이 3점 이하다.
- JSON 계약과 workflow 성공률 하락이 각각 2%p 이하다.
- 품질 계약 통과율 하락이 5%p 이하다.
- 10점 이상 심각 회귀가 전체의 5% 이하다.
- end-to-end 지연 증가가 고가 고정의 25% 이하다.

## 실행

외부 provider 호출과 비용 발생 없이 데이터셋 계약만 확인:

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) \
  apps/workflow_engine/.venv/bin/python \
  scripts/experiment_judge_first_economics_80.py --count 80
```

실제 실행은 synthetic payload를 외부 provider에 보내고 DB run/usage log를 쓴다. 이를 명시적으로 승인받은 뒤 10건씩 실행하고 `--resume --offset <N>`으로 이어 간다. 결과는 `reports/model-routing/runs/judge-first/<run-id>/`에 JSON과 Markdown으로 저장한다.
