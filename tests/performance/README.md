# Observability Query Benchmark

감사·추적 조회의 변경 전/후 SQL을 같은 임시 PostgreSQL 데이터에서 비교한다. 임시 테이블만 사용하며 애플리케이션 데이터는 수정하지 않는다.

```bash
PYTHONPATH=$(git rev-parse --show-toplevel) apps/gateway/.venv/bin/python \
  tests/performance/benchmark_observability_queries.py \
  --rows 100000 --iterations 5
```

결과의 `before_ms`/`after_ms`는 반복 실행 중앙값이고 `speedup`은 `before / after`다. 합성 데이터 결과이므로 운영 DB에서는 `EXPLAIN (ANALYZE, BUFFERS)`로 다시 확인한다.

Trace 항목은 실제 visibility policy join 전체가 아니라 `5,000건 fetch 후 필터`와 `SQL에서 visible 20건 제한`의 조회량 차이를 단순화해 측정한다. 실제 `/api/v1/traces` 응답 시간으로 해석하지 않는다.

측정 결과는 `reports/`에 실행 날짜별 JSON으로 보관한다.
