# Optimization & Evaluation

## 메모의 문제의식

메모는 "싼 모델 추천", "A/B 테스트", "quality score", "프롬프트 suggestion", "청크 최적화"를 반복해서 언급한다. 즉, Nodease는 AI 워크플로우를 실행하는 도구를 넘어 trial-and-error를 체계화하는 플랫폼이어야 한다.

## 최적화 대상

| 대상 | 비교 기준 |
| --- | --- |
| Model | 비용, 지연시간, 품질, 실패율, 정책 적합성 |
| Prompt | 정확도, 일관성, 토큰 수, 안전성, 사용자 평가 |
| Chunking | 검색 품질, 토큰 비용, 처리 시간, 재색인 비용 |
| Retrieval | top-k, similarity threshold, reranker 사용 여부 |
| Workflow | 전체 비용, 병목 노드, 실패율, 병렬 실행 효율 |

## 품질 점수 정의

품질은 모델 이름만으로 결정되지 않는다. 높은 가격의 모델이 항상 더 좋은 결과를 내는 것도 아니다. 따라서 quality score는 여러 지표를 조합해야 한다.

아래 지표는 확정 스펙이 아니라 후보 목록이다. 원문은 "quality를 어떻게 score할까?"라고 문제를 제기했을 뿐, 단일 정답을 제시하지 않는다.

| 지표 | 설명 |
| --- | --- |
| Task Accuracy | 정답 또는 기대 결과와 얼마나 맞는가 |
| Groundedness | RAG context에 근거해 답했는가 |
| Consistency | 같은 입력에 안정적으로 비슷한 답을 내는가 |
| Policy Compliance | 개인정보, 금칙어, 보안 정책을 지켰는가 |
| Human Rating | 사용자의 thumbs up/down 또는 점수 |
| Latency | 응답 시간이 허용 범위 안인가 |
| Cost Efficiency | 품질 대비 비용이 적절한가 |

## 추천 로직 예시

아래 로직은 구현 방향 예시다. 실제 제품에서는 태스크별 평가 데이터가 부족하면 자동 추천 대신 "비용/지연시간/사용자 평가를 근거로 한 제안"부터 시작하는 것이 현실적이다.

```text
Model Recommendation
  IF cheaper_model_quality >= current_quality - tolerance
  AND cheaper_model_cost <= current_cost * 0.7
  THEN recommend cheaper_model

Prompt Recommendation
  IF prompt_token_count is high
  AND output_quality is similar
  THEN suggest shorter prompt

Chunk Recommendation
  IF top_k results include duplicate chunks
  THEN reduce overlap or top_k
```

## 비교 UI

비교는 제품의 중심 경험이어야 한다.

### 모델 비교

| 모델 | 비용 | 지연시간 | 품질 점수 | 실패율 | 추천 |
| --- | --- | --- | --- | --- | --- |
| GPT-4 계열 | 높음 | 중간 | 높음 | 낮음 | 고품질 태스크 |
| GPT-4o-mini 계열 | 낮음 | 빠름 | 중간~높음 | 낮음 | 비용 최적화 |
| 사내 모델 | 낮음 | 환경 의존 | 태스크 의존 | 환경 의존 | 민감 데이터 |

### 프롬프트 비교

- prompt version
- 변경 diff
- token count
- 샘플 입력별 응답
- 품질 점수
- 정책 위반 여부
- 예상 월 비용

### 청크 비교

- chunk size
- overlap
- top-k
- recall score
- 평균 context token
- 평균 latency
- 예상 embedding cost
- 재색인 범위

## 배포 전 체크

배포 전에는 아래를 자동으로 보여주면 좋다.

- 예상 월 비용
- 가장 비싼 노드
- 가장 느린 노드
- 실패 가능성이 높은 노드
- 권한 정책 위반
- PII 포함 가능성
- 외부 모델 호출 여부
- 새 버전과 이전 버전의 비용/품질 차이

## 배포 후 최적화

운영 중에는 실제 로그 기반으로 추천해야 한다.

- 특정 노드의 비용 급증
- 캐시 가능한 반복 요청
- 품질 점수가 낮은 프롬프트
- 실패율 높은 모델
- latency 병목 노드
- 재색인이 과도하게 발생하는 데이터 소스
- 사용하지 않는 고가 모델

## UX 아이디어

메모의 "반짝이 아이콘" 아이디어는 추천 모드로 정리할 수 있다.

- 모델 추천 버튼
- 프롬프트 개선 버튼
- 청크 설정 최적화 버튼
- 비용 절감 시뮬레이션 버튼
- 배포 전 위험 점검 버튼

이 버튼들은 단순 설명이 아니라, 실제 현재 워크플로우의 로그와 설정을 바탕으로 제안을 생성해야 한다.
