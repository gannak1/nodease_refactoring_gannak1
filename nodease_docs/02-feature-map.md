# 기능 구조화

이 문서는 메모에 나온 기능을 제품 영역과 우선순위로 묶은 것이다.

## 우선순위 기준

| 우선순위 | 의미 |
| --- | --- |
| P0 | 다음 주 데모에서 제품 방향을 보여주기 위해 필요 |
| P1 | P0 이후 엔터프라이즈 완성도를 높이는 기능 |
| P2 | 구현 범위가 크거나 리서치가 더 필요한 확장 기능 |

## 기능 맵

| 영역 | 기능 | 우선순위 | 설명 |
| --- | --- | --- | --- |
| LLMOps Gateway | 모델 라우팅/접근 제어 | P0 | 사용자/역할/프로젝트별로 사용 가능한 모델 제한 |
| LLMOps Gateway | 요청/응답 트레이싱 | P0 | 어떤 워크플로우, 노드, 모델, 프롬프트가 호출됐는지 기록 |
| LLMOps Gateway | 비용/토큰/지연시간 집계 | P0 | 노드별, 모델별, 워크플로우별 관측성 제공 |
| LLMOps Gateway | fallback/retry | P1 | 모델 실패 시 대체 모델로 전환하거나 재시도 |
| LLMOps Gateway | 캐시 | P1 | 반복 요청 비용 절감 |
| Optimization | 저비용 모델 추천 | P0 | 품질 손실이 작을 때 더 싼 모델을 추천 |
| Optimization | 프롬프트 A/B 테스트 | P0 | 프롬프트별 결과, 비용, 지연시간 비교 |
| Optimization | 청크 전략 비교 | P1 | chunk size/overlap/top-k에 따른 품질과 비용 비교 |
| Evaluation | 품질 점수화 | P0 | 정확도, 일관성, 정책 위반, 사용자 평가 등을 기준으로 scoring |
| RAG | 동적 데이터 갱신 | P0 | 전체 재색인, 부분 재색인, incremental indexing 전략 표시 |
| RAG | RAG/청크 감사 | P0 | 어떤 데이터/청크가 검색되고 모델에 전달됐는지 추적 |
| RAG | 데이터 수집/변경 감지 | P1 | CDC, scheduled sync, webhook 기반 변경 감지 |
| Governance | 글로벌 정책 | P0 | 조직 전체 모델/데이터/비용/감사 정책 |
| Governance | 노드별 override | P1 | 특정 노드에 더 강한 정책이나 예외 설정 |
| Governance | 데이터 분류 | P0 | Public/Internal/Confidential/PII/PHI 등급 |
| Audit | 실행 감사 로그 | P0 | 누가, 언제, 무엇을 실행했는지 |
| Audit | 변경 감사 로그 | P0 | 프롬프트/모델/정책/워크플로우 변경 이력 |
| Audit | 로그 검색/필터 | P1 | 기간, 사용자, 워크플로우, 데이터 등급 기준 조회 |
| RBAC | 프로젝트/캔버스 권한 | P0 | read/write/execute 권한 |
| RBAC | 데이터 소스 권한 | P0 | HR, Finance 등 특정 그룹만 접근 가능 |
| RBAC | 노드 단위 권한 | P2 | 구현 복잡도가 높으므로 후순위 |
| Deployment | 배포 후 설정 변경 | P1 | 모델, 비용 한도, 정책, 승인 플로우 수정 |
| Deployment | SaaS/Open Source/K8s 전략 | P2 | 최종 배포 형태 결정 |
| MCP | MCP Gateway / MCP 연결 | P1 | 외부 도구와 사내 시스템을 안전하게 연결 |
| Workflow Runtime | DAG 실행/스케줄링 | P1 | Airflow처럼 실행/스케줄 개념을 고려 |
| Workflow Runtime | 비동기 결과 merge | P1 | 응답 속도가 다른 노드 결과를 어떻게 합칠지 정의 |
| UX | 추천 모드 | P0 | 반짝이 아이콘처럼 best prompt/model/chunk 추천 |
| UX | 비교 중심 UI | P0 | 프롬프트, 모델, 비용, 품질, 실행 결과를 나란히 비교 |
| UX | Property settings 개선 | P0 | Moduly보다 편한 설정 편집 경험 제공 |

## 기능 간 관계

```text
Workflow Canvas
  -> LLM Gateway
      -> Model Policy
      -> Cost Tracking
      -> Tracing
      -> Fallback / Cache
  -> Data Governance
      -> Data Classification
      -> PII Handling
      -> Lineage
  -> Optimization
      -> Prompt Compare
      -> Model Compare
      -> Chunk Compare
  -> Runtime
      -> DAG Execution
      -> Schedule
      -> Async Merge
  -> Audit / RBAC
      -> Execution Logs
      -> Change Logs
      -> Access Control
```

## 데모에서 반드시 보여줄 장면

1. 사용자가 워크플로우를 실행한다.
2. 각 노드에 비용, 토큰, 지연시간, 사용 모델이 표시된다.
3. 특정 노드에서 더 싼 모델 추천이 나온다.
4. 프롬프트 또는 모델 A/B 비교 결과를 본다.
5. RAG 데이터가 변경되었을 때 재색인 범위를 선택한다.
6. 감사 로그에서 누가 무엇을 실행했는지 확인한다.
7. 데이터 소스 또는 프로젝트에 RBAC 정책을 적용한다.
8. 에디터에서 복잡한 설정을 빠르게 바꾸고 비교 결과를 확인한다.
