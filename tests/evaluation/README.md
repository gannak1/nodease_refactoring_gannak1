# RAG Evaluation Test Suite

RAG retrieval 품질을 검증하는 내부 QA/engineering 도구다. Production API나 사용자 기능이 아니며 benchmark 결과가 runtime 설정을 자동 변경하지 않는다.

기존 `rag_evaluator.py`/`rag_metrics.py`는 legacy substring baseline 호환용이다. Flat·Hierarchical 비교는 strict dataset, opaque evidence ref, sealed artifact lineage와 paired statistics를 사용하는 별도 명령을 사용한다.

## Flat·Hierarchical 비교 범위

- Primary estimand: `controlled_child_boundary_retrieval_effect`
- Independent variable: `hierarchy_mode=flat|parent_child`
- Controls: 같은 source snapshot, child boundary/vector, query vector, hybrid setting, threshold/top-k, actor와 permission
- Primary source tier policy: `ignore` (hierarchy 효과와 tier tie-break 효과 분리)
- Primary run: retrieval-only, reranker/rewrite OFF
- Inference: source/topic sampling-cluster paired delta, BCa bootstrap 95% CI
- Safety: unanswerable paired-binomial risk-difference CI
- Output: sanitized canonical JSON, Markdown, offline self-contained HTML

Generation 평가와 제품 dashboard는 이 초기 범위에 포함하지 않는다.

## 📂 구조

```
tests/evaluation/
├── __init__.py
├── rag_metrics.py                         # legacy baseline metric
├── rag_evaluator.py                       # legacy baseline runner
├── schemas.py / protocol.py               # strict contract와 artifact lineage
├── evidence_refs.py / judgment_pool.py    # opaque ref와 blind pool
├── paired_metrics.py / paired_statistics.py
├── paired_runner.py / comparison_report.py
├── run_flat_hierarchical_benchmark.py
├── law_development_pilot.py / run_law_development_pilot.py
├── corpus_authoring.py / law_open_data.py
├── prepare_flat_hierarchical_corpus.py
├── test_rag_baseline.py
├── tests/                                  # deterministic benchmark tests
├── datasets/
│   ├── sample_qa.json                      # legacy 샘플 데이터셋
│   └── flat_hierarchical/                  # source catalog와 synthetic input
└── reports/              # 평가 리포트 저장
```

## 🚀 사용법

### 1. 단위 테스트 실행

```powershell
$env:PYTHONPATH=(git rev-parse --show-toplevel)
apps/gateway/.venv/Scripts/python.exe -m pytest tests/evaluation/test_rag_baseline.py tests/evaluation/tests -q
```

### Flat·Hierarchical strict workflow

```powershell
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py validate --dataset <dataset.json> --protocol <protocol.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py plan-sample --pilot <pilot-summary.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py verify-indexes --flat-manifest <ignored-flat-index.json> --hierarchical-manifest <ignored-hierarchical-index.json> --output <safe-equality-summary.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py seal-run --input <retrieval-run.json> --output <sealed-output.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py build-judgment-pool --sealed-input <sealed-output.json> --protocol <protocol.json> --output <blind-pool.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py freeze-qrels --sealed-input <sealed-output.json> --pool <blind-pool.json> --assessments <blind-assessment-bundle.json> --output <final-qrels.json> --summary-output <assessment-summary.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py verify-stability --primary-sealed <sealed-output.json> --replicate-sealed <replicate-sealed-output.json> --protocol <protocol.json> --output <stability-summary.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py score --sealed-input <sealed-output.json> --protocol <protocol.json> --pool <blind-pool.json> --qrels <final-qrels.json> --output <result.json> --latency-observations <optional-latency-artifact.json>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_flat_hierarchical_benchmark.py render --input <result.json> --output-dir tests/evaluation/reports/<run-id>
```

`sealed-output`, blind assessment와 final qrels에는 승인된 safe corpus만 사용한다. Restricted corpus와 source binding은 Git ignored local 경로에 두고 raw source content, vector, credential이나 secret을 CLI argument 또는 report에 넣지 않는다. Blind pool은 사전 작성 required evidence와 양쪽 condition 후보를 포함하되 condition/score/rank를 제거한다. 정확히 두 평가자의 독립 판정, 역할 분리 확인, 모든 disagreement adjudication이 완료되어야 qrels를 동결할 수 있다.

Evaluation observer는 `EvaluationRetrievalDiagnostics.from_protocol(...)`로 생성한다. 이 factory가 `scan_cap`과 `score_precision`을 각각 protocol의 `complete_tie_group_cap`과 `score_precision`에서 가져온다. Scan cap은 최소 `max(pool depth, top_k * 10)`이어야 한다. `score`의 bootstrap 횟수는 protocol에서 파생되며, `--bootstrap-iterations`를 명시하면 protocol 값과 정확히 같아야 한다. `seal-run`은 기존 output을 덮어쓰지 않으므로 새 protocol/dataset version 없이 같은 holdout artifact를 교체할 수 없다.

Stability 비교는 selection depth와 그 cutoff의 complete exact-score tie group까지만 수행한다. Observer가 진단을 위해 더 수집한 scan-cap tail은 pool, metric 또는 stability 대상이 아니다. Paired index의 condition별 chunk UUID는 서로 달라도 canonical child ordinal의 상대 순서를 같게 보존해야 하며, 임의 UUID 순서가 RRF rank 차이가 되면 index equality를 충족한 것으로 보지 않는다.

### Corpus acquisition and preparation

국가법령정보센터 Open API 인증 식별자는 저장소 루트 `.env`의 `NODEASE_EVAL_LAW_OC`로만 주입한다. 값은 명령 인자나 출력에 넣지 않는다. Open API 신청 화면에서 이 카탈로그가 사용하는 법령, 행정규칙과 판례 목록·본문 범위를 먼저 활성화해야 한다.

```powershell
$catalog = "tests/evaluation/datasets/flat_hierarchical/kr-law-dry-run-v1/catalog.json"
$corpus = "tests/evaluation/datasets/flat_hierarchical/enterprise-policy-v1/corpus.json"
$questions = "tests/evaluation/datasets/flat_hierarchical/enterprise-policy-v1/questions.json"

apps/gateway/.venv/Scripts/python.exe tests/evaluation/prepare_flat_hierarchical_corpus.py probe-law-access --catalog $catalog
apps/gateway/.venv/Scripts/python.exe tests/evaluation/prepare_flat_hierarchical_corpus.py collect-law --catalog $catalog --snapshot-id <new-snapshot-id>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/prepare_flat_hierarchical_corpus.py draft-law-development --catalog $catalog --snapshot-id <existing-law-snapshot-id> --bundle-id <new-question-bundle-id>
apps/gateway/.venv/Scripts/python.exe tests/evaluation/prepare_flat_hierarchical_corpus.py prepare-synthetic --corpus $corpus --questions $questions --snapshot-id <new-snapshot-id>
```

산출물은 `local/evaluation-data/mba-279/kr-law/<snapshot-id>/`, `local/evaluation-data/mba-279/kr-law-development/<bundle-id>/` 또는 `local/evaluation-data/mba-279/enterprise-policy/<snapshot-id>/`에 생성된다. 기존 snapshot과 question bundle은 덮어쓰지 않는다. 국가법령 source JSON은 API가 OC를 포함해 반환하는 미사용 detail-link field를 제거한 뒤 `source-json/`에 저장한다. 정규화 content, source binding과 provenance도 ignored local 경로에만 두며 Git에는 source selection catalog와 출처 고지만 저장한다. 외부 JSON의 단일 객체/배열 차이는 target별 adapter가 내부 canonical section으로 정규화한다. Public-law question bundle은 source snapshot을 수정하지 않고 100개 development draft와 local review worksheet를 만든다. 구조 검증 결과인 `structural_pilot_ready=true`는 사람의 semantic/answerability/evidence review 완료를 뜻하지 않으며 `quality_pilot_ready=false`인 bundle을 품질 결론에 사용하지 않는다. 추적되는 synthetic package는 development pipeline 검증용이고 unseen confirmatory holdout이 아니다. 판례 결과는 `exploratory`로만 해석한다.

### Public-law development retrieval dry-run

실제 provider credential, migrated PostgreSQL, active evaluation actor가 준비된 로컬 환경에서만 실행한다. 출력 경로는 create-only ignored local artifact이며 CI에서 실행하지 않는다.

```powershell
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_law_development_pilot.py `
  --snapshot-dir local/evaluation-data/mba-279/kr-law/<snapshot-id> `
  --bundle-dir local/evaluation-data/mba-279/kr-law-development/<bundle-id> `
  --run-root local/evaluation-data/mba-279/pilot-runs/<run-id> `
  --run-id <run-id> `
  --env-file .env `
  --threshold 0.0 `
  --hybrid-search
```

현재 non-rerank hybrid/hierarchy branch는 similarity가 아니라 RRF score에 threshold를 적용하므로 engineering dry-run은 `threshold=0.0`으로 candidate truncation을 분리한다. 이 값은 production 권장값이나 safety abstention 정책이 아니다. Human review가 끝나지 않은 question bundle의 출력은 `exploratory_unreviewed_labels`이며, 실제 실행했다는 이유로 quality gate나 runtime default를 변경하지 않는다.

### Development question AI review

현재 100문항 development bundle은 두 개의 격리된 `gpt-5.6-sol` maximum-reasoning pass로 전수
검토할 수 있다. 두 pass는 retrieval condition, rank, metric과 서로의 결과를 받지 않고 반대 question ID
순서로 검토한다. 검토 중에는 browser, network와 외부 model API를 사용하지 않는다. 정확한 rubric과
비노출 경계는 `ai_review_protocol.md`를 따른다.

각 pass의 row-level JSONL은 ignored local evaluation-data 경로에만 둔다. 다음 명령은 두 파일의 strict
schema, 100개 unique question ID, field-level agreement와 disagreement 목록을 검증하고 raw query나
source text가 없는 create-only summary를 만든다.

```powershell
apps/gateway/.venv/Scripts/python.exe -m tests.evaluation.ai_review_agreement `
  --pass-one local/evaluation-data/mba-279/ai-review/<run-id>/pass-1.jsonl `
  --pass-two local/evaluation-data/mba-279/ai-review/<run-id>/pass-2.jsonl `
  --protocol tests/evaluation/ai_review_protocol.md `
  --output local/evaluation-data/mba-279/ai-review/<run-id>/agreement.json
```

어느 review field라도 불일치하면 두 pass를 보지 않은 blind third pass로 해당 question ID만 다시
검토한다. 최종 실행에서는 `--adjudication <adjudication.jsonl>`과
`--final-output <final-review.json>`을 함께 지정하고 새 summary output 경로를 사용한다. Adjudication
파일은 최초 agreement가 열거한 disagreement ID와 정확히 일치해야 한다.

이 검토는 immutable question bundle을 덮어쓰거나 기존 dry-run status를 바꾸지 않는다. 두 pass의
일치성은 machine-reviewed development evidence만 보강한다. Human-reviewed qrels, unseen holdout,
confirmatory cluster floor와 adjudication을 대체하지 않으며 production 기본값의 승인 근거로 사용하지
않는다. MBA-279의 sanitized aggregate 결과와 해석 경계는
`docs/engineering/rag-flat-hierarchical-development-evaluation.md`에 기록한다.

### Chunk profile development ablation

`run_chunk_profile_experiment.py`는 같은 prepared corpus, 질문, query vector, embedding model과 실제
PostgreSQL hybrid retrieval에서 다음 profile을 비교한다.

- raw atomic evidence
- deterministic source context를 붙인 atomic evidence
- 구조 경계를 넘지 않는 contextual 256/512/1024/2000-token chunk

합쳐진 검색 chunk는 포함한 canonical atomic evidence 전체로 relevance를 판정한다. Top-5 metric과 함께
고정 context-token budget 안에 실제로 들어가는 evidence coverage를 계산한다. 이 runner는 development
ablation 전용이며 hierarchy mode, generation 품질 또는 production 기본값을 자동 변경하지 않는다.

```powershell
apps/gateway/.venv/Scripts/python.exe tests/evaluation/run_chunk_profile_experiment.py `
  --snapshot-dir local/evaluation-data/mba-279/kr-law/<snapshot-id> `
  --bundle-dir local/evaluation-data/mba-279/kr-law-development/<bundle-id> `
  --run-root local/evaluation-data/mba-279/profile-runs/<run-id> `
  --run-id <run-id> `
  --env-file .env `
  --context-budget-tokens 2048 `
  --retrieval-depth 100 `
  --hybrid-search
```

Token 측정은 명시한 tokenizer를 사용하고 기본값은 `cl100k_base`다. 원자 evidence 하나가 목표 token을
초과하면 정답 경계를 임의 분할하지 않고 over-target 예외로 집계한다. Source text, query, vector, DB
resource ID와 credential은 ignored local artifact 밖으로 내보내지 않는다. 각 결과에는 code commit과
실행에 사용한 source byte fingerprint가 함께 기록된다.

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
- 실제 retrieval/pilot은 승인된 평가 organization, actor, KB와 provider credential이 필요하며 CI에서 실행하지 않는다.
- Holdout은 protocol/code/split/N을 freeze한 뒤 한 번의 complete paired execution으로 봉인한다.
- Generated Flat·Hierarchical report는 기본적으로 Git에 포함하지 않는다.

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
