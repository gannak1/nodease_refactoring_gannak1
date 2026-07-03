# Cost Optimizer Test Cases

Status: Draft
Verified Against: TBD

[PRD](../../PRD.md) 시나리오 1의 4단계(배포 전 비용 최적화)와 FR-021~FR-022를 검증한다.

## Unit Tests

- (FR-022) 비용 절감률 계산이 두 variant의 실제 실행 비용 기준으로 정확하다.
- (FR-022) 리포트 요약이 필수 필드(현재 모델, 후보 모델, 절감률, 품질 차이, variant별 결과 참조)를 포함한다. 품질 차이 산정 방식은 PRD Open Question 확정 후 케이스를 구체화한다.
- 후보 모델 선정이 organization에서 사용 가능한 모델(verified credential-model relation, `is_active`)로만 제한된다.
- RAG strategy 비교 summary builder는 `retrieval_strategy`, `rag_mode`, selected collection/KB count, retrieved chunk count, citation count, context token estimate, cost, latency, policy result, `query_rewrite_applied`, `query_rewrite_strategy`, `evidence_sufficient`, `insufficiency_reason`, `source_tier_used` 같은 safe field만 사용하고 raw source metadata, raw rewritten query, raw chunk content를 포함하지 않는다.

## API Tests

- (FR-021) compare 실행이 두 variant의 실행 결과와 비용을 반환한다 (기존 `POST /api/v1/workflows/{workflow_id}/compare` 계약 유지).
- (FR-021) 비교 실행에서 발생한 LLM 호출이 `llm_usage_logs`에 기록된다 — 최적화 기능 자체의 비용이 누락되지 않는다.
- (FR-023) RAG 포함 workflow compare는 workflow runtime의 `execution_subject` 기준으로 KB permission/source ACL/final evidence gate를 적용한다.
- `llm_assisted` query rewrite가 비교 변수에 포함되면 rewrite LLM call의 usage/cost도 variant 비용에 포함한다. Knowledge G14 gate가 닫히기 전에는 해당 variant를 생성하지 않거나 명시적으로 제외한다.
- verified relation이 없는 모델을 후보로 지정한 요청 → 거부 또는 후보에서 제외.
- 존재하지 않거나 다른 조직의 workflow id로 비교 요청 → `404 resource.not_found`.

## E2E Tests

- **시나리오 1의 4단계 완주**: workflow 화면에서 "비용 최적화" 실행 → 현재 모델 vs 후보 모델 비교 → "비용 X% 절감, 품질 차이 Y" 리포트 표시 → 모델 결정 후 배포로 진행.
- 시나리오 4와의 연결: 대시보드에서 비용이 큰 workflow를 찾아 해당 workflow의 비용 최적화 흐름으로 이동할 수 있다 (진입 링크).

## Permission Tests

- workflow 실행 권한이 없는 사용자(viewer)의 compare 실행 → `403 permission.denied`.
- 후보 모델의 credential에 `use` 권한이 없는 사용자의 비교 → 해당 후보 거부 또는 제외 (`permission.denied` audit 기준은 runtime 차단 규칙을 따른다).
- organization scope 밖 workflow에 대한 비교 → 404로 숨김.
- RAG 포함 workflow compare에서 권한 없는 KB/source ACL denied 문서는 두 variant 모두 prompt, citation, trace, 비교 UI에 포함되지 않는다.
- Query rewrite와 evidence sufficiency 옵션이 켜진 variant도 권한 없는 KB/source ACL denied 문서를 후보로 만들지 못한다.

## Edge Cases

- 더 저렴한 후보 모델이 없는 경우 → "절감 가능 없음" 안내 (빈 리포트가 아니라 명시적 결과).
- 한쪽 variant 실행이 실패한 경우 → 부분 결과와 실패 원인을 구분해 반환하고, 절감률을 계산하지 않는다.
- 가격 정보가 없는 모델(`input_price_1k`/`output_price_1k` NULL) → 비용 비교 불가를 명시하고 자동 추천에서 제외.
- 응답에 credential 원문/`encrypted_config`가 포함되지 않는다 (모델/credential 식별자는 allowlist 안에서만).
- RAG 포함 비교에서 일부 authorized KB retrieval만 operational failure가 발생하면 Knowledge partial-result 정책에 맞춘 safe summary만 표시하고, hidden/denied 문서명이나 정확한 제외 개수는 표시하지 않는다.
- Evidence insufficiency가 발생한 variant는 추측 답변을 품질 성공으로 계산하지 않고, safe `insufficiency_reason`을 비교 리포트에 표시한다.
