# RAG Evaluation Test Suite

RAG(Retrieval-Augmented Generation) 검색 시스템의 성능을 평가하기 위한 종합 테스트 스위트입니다.

## 🚀 Quick Start (전체 워크플로우)

```bash
cd apps/server

# 1. HotpotQA 데이터셋 다운로드 (50개 샘플)
python tests/evaluation/prepare_datasets.py --dataset hotpotqa --samples 50

# 2. 문서를 Knowledge Base에 인덱싱
python tests/evaluation/index_documents.py --dataset hotpotqa --kb-name "RAG Eval - HotpotQA"

# 3. 벤치마크 실행 (KB ID는 2번에서 출력됨)
python tests/evaluation/run_benchmark.py --kb-id YOUR_KB_ID --dataset hotpotqa --samples 50

# 4. 리포트 확인
cat tests/evaluation/reports/rag_eval_hotpotqa_*.md
```

## 📂 구조

```
tests/evaluation/
├── __init__.py
├── rag_metrics.py        # 평가 지표 구현
├── rag_evaluator.py      # 평가 프레임워크
├── test_rag_baseline.py  # 베이스라인 테스트
├── datasets/
│   └── sample_qa.json    # 샘플 데이터셋
└── reports/              # 평가 리포트 저장
```

## 🚀 사용법

### 1. 단위 테스트 실행

```bash
cd apps/server
pytest tests/evaluation/test_rag_baseline.py -v
```

### 2. 베이스라인 성능 측정

```python
from tests.evaluation.rag_evaluator import RAGEvaluator, EvaluationConfig, DatasetLoader
from tests.evaluation.rag_metrics import RetrievalResult

# 설정
config = EvaluationConfig(
    dataset_name="baseline_v1",
    knowledge_base_id="your-kb-id",
    top_k_values=[1, 3, 5, 10]
)

# 샘플 로드
samples = DatasetLoader.load_json("tests/evaluation/datasets/sample_qa.json")

# 평가 실행
evaluator = RAGEvaluator(config)
results = evaluator.evaluate(samples, your_retrieval_func)

# 리포트 저장
evaluator.save_report(results)
print(results.summary())
```

### 3. 성능 비교

```python
# 두 리포트 비교
comparison = evaluator.compare_reports([
    "reports/rag_eval_baseline_v1.json",
    "reports/rag_eval_improved_v2.json"
])
```

## 📊 지원 지표

| 지표            | 설명                             | 범위      |
| --------------- | -------------------------------- | --------- |
| **Recall@K**    | 정답이 top-k에 포함된 비율       | 0.0 - 1.0 |
| **Precision@K** | top-k 중 정답인 비율             | 0.0 - 1.0 |
| **Hit@K**       | 정답이 top-k에 하나라도 있으면 1 | 0 or 1    |
| **MRR**         | 첫 번째 정답의 역순위            | 0.0 - 1.0 |
| **NDCG@K**      | 순위 가중 정확도                 | 0.0 - 1.0 |

## 📁 데이터셋

### 지원 형식

1. **JSON 파일**

   ```json
   [{ "query": "질문", "relevant_passages": ["정답1", "정답2"] }]
   ```

2. **HuggingFace Datasets**
   - Natural Questions
   - HotpotQA

### 샘플 데이터셋

`datasets/sample_qa.json` - 10개의 사내 FAQ QA 쌍

## 📈 리포트 예시

```
============================================================
RAG Evaluation Report
============================================================
Dataset: baseline_v1
Samples: 100
Timestamp: 2026-01-13T12:00:00
------------------------------------------------------------
Metrics:
  hit@1: 0.4500
  hit@3: 0.6800
  hit@5: 0.7500
  mrr: 0.5234
  ndcg@5: 0.6123
  precision@5: 0.3200
  recall@5: 0.7500
============================================================
```

## 🔄 개선 추적

1. 베이스라인 측정 → `baseline_v1.json`
2. 개선 적용 (예: Query Rewriting)
3. 재측정 → `improved_v2.json`
4. 비교 리포트 생성

## ⚠️ 주의사항

- 실제 DB 연결 테스트는 `@pytest.mark.skip` 처리되어 있음
- HuggingFace 데이터셋 사용 시 `pip install datasets` 필요

## Agent Builder Cache Latency Offline Report

`agent_builder_cache_latency_report.py`는 live provider나 Redis를 호출하지 않고,
고정된 comparison row에서 CACHE-05 latency evidence bundle을 생성한다. 이 도구는
`run_agent_builder_intent_benchmark.py`의 live planner accuracy 측정이나 CACHE-01 runtime
contract를 대체하거나 수정하지 않는다.

합성 fixture로 결정적인 예시 bundle을 생성하려면 다음 명령을 사용한다.

```powershell
python tests/evaluation/agent_builder_cache_latency_report.py `
  --dataset tests/evaluation/datasets/agent_builder_cache_latency_v1.json `
  --output local/mba-347/evidence/generated-synthetic
```

외부 collector가 만든 `runs.csv`를 입력할 때는 `--runs-csv`, `--dataset-version`,
`--cache-contract-version`, `--run-date`, `--git-sha`, `--benchmark-kind`로 metadata를
명시한다. 입력 CSV의 열 순서는 다음과 같으며 정확히 일치해야 한다.

```text
case_id,pair_id,run_id,comparison_group,is_warmup,cache_outcome,planning_latency_ms,end_to_end_latency_ms,provider_call_count,repair_call_count,terminal_status,validation_passed,result_fingerprint
```

`provider_call_count`는 기존 planner attempt 계약에 따라 0~2만 허용하며 모든 `cache_outcome=hit`는
terminal status와 관계없이 `0/0`이다. Warm-hit rehydration fallback은 같은 comparison group에서 실제
`cache_outcome=miss`와 provider/repair 관측으로 기록한다. 성공 non-hit 경로는 1~2여야 한다.
`repair_call_count`는 `0|1`만 허용하며 provider 경로는 최초 attempt 하나와 repair 수의 합(`provider_call_count = 1 + repair_call_count`)으로 기록한다. Provider 미호출은 `0/0`이다.
Row-level parsing/validation 오류는 원문 값 없이 safe row 번호와 field name만 반환한다.

`terminal_status=success`이면서 `validation_passed=true`인 비-warm-up row만 latency 평균,
P50, P95(type-7 linear
interpolation), 모집단 표준편차, 최소/최대에 포함한다. 실패율은 measured row 전체에서
계산하고, 실패 row와 warm-up row는 `runs.csv`와 두 SVG에는 유지하되 성공 latency
통계에서는 분리한다. Paired delta는 같은 `pair_id`의 baseline latency에서 candidate
latency를 뺀 값이며, improvement rate는 `delta / baseline`, speedup은
`baseline / candidate`이다.

25/50/75% hit-rate 값은 측정치가 아니라
`(1 - h) * cold_candidate_mean + h * warm_candidate_mean`으로 계산한
`modeled_estimate`이다. `warm_candidate_mean`은 실제 `cache_outcome=hit`인 성공 warm row만 사용한다.
Warm-hit rehydration fallback `miss`의 latency는 W에 포함하지 않는다. 합성 fixture는 도구와 schema
검증용이며 final live evidence로 간주하지 않는다.

bundle에는 다음 7개 파일이 생성된다.

- `README.md`: cold/warm measured planning/end-to-end 핵심 요약과 아래 모든 상세 파일의 상대 경로
- `runs.csv`: 모든 회차의 canonical row
- `latency-comparison.svg`: 모든 회차의 planning/end-to-end latency surface, 열린 warm-up marker와 각 가용 surface의 실패 cross 비교 그래프
- `cache-hit-scenarios.svg`: 모든 회차의 outcome/call/terminal/validation 상태 그래프
- `summary.json`: 구조화된 전체 요약
- `summary.csv`: group, pair, modeled estimate의 long-form 요약
- `summary.md`: 사람이 읽을 수 있는 상세 요약

생성 전에 source row와 렌더링될 artifact 전체를 검사하며 raw prompt/provider payload,
credential·token·API key, Bearer 값, private key, URL userinfo, protected-resource UUID가
감지되면 출력 디렉터리를 만들지 않고 실패한다. 로컬 탐색용 출력은 `local/` 아래에
두고, 별도의 live collector가 검증을 마친 final bundle만 추적 대상으로 승격한다.

## Agent Builder Intent Evaluation

`run_agent_builder_intent_benchmark.py`는 permission-aware 실제 planner model의 새 workflow/수정/전체 교체/unsupported 분류, capability 순서, 기존 node target/placement, 명시적 integration action을 측정한다. Deterministic unit test에는 포함하지 않는다. Dataset에는 `GitHub`와 `깃허브`로 표기한 GitHub Pull Request 생성 삽입 요청을 각각 포함한다.

```powershell
$env:NODEASE_EVAL_USER_ID = "<user uuid>"
$env:NODEASE_EVAL_ORGANIZATION_ID = "<organization uuid>"
$env:NODEASE_EVAL_CREDENTIAL_ID = "<credential uuid>"
$env:NODEASE_EVAL_MODEL_ID = "<model uuid>"
python tests/evaluation/run_agent_builder_intent_benchmark.py --output tests/evaluation/reports/agent_builder_intent.json
```

Runner는 DB의 active organization, credential `use` 권한, verified model relation을 그대로 검증한다. Report에는 case ID, 기대/실제 구조 필드, 지표만 기록하고 prompt, credential 원문, provider payload, node/edge ID를 기록하지 않는다. 기본 gate는 request type/draft mode 0.90, ordered capability exact match 0.80, target/placement 0.85, 명시된 integration action exact match 1.00, invalid output rate 0.05 이하이다.
