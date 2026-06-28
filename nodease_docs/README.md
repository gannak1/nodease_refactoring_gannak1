# Nodease 메모 정리 문서

작성 기준: [memo.md](./memo.md)

이 문서는 흩어진 피드백과 아이디어를 제품 방향, 기능 요구사항, 구현 우선순위로 재구성한 로컬 문서다. 원문은 회의 메모에 가깝기 때문에, 여기서는 발표/구현/리서치에 바로 쓸 수 있도록 중복 표현을 줄이고 의사결정 단위로 정리했다.

주의: `memo.md`에는 원문 메모와 별도의 ChatGPT 요약이 함께 들어 있다. 이 문서 세트는 원문에서 직접 나온 요구와 ChatGPT 요약에서 확장된 해석을 구분해서 다룬다.

## 한 줄 요약

Nodease는 단순 노드 기반 자동화 툴이 아니라, 기업이 AI 워크플로우를 안전하게 설계, 비교, 배포, 감사, 최적화할 수 있는 엔터프라이즈 AI Workflow / LLMOps 플랫폼으로 보여야 한다.

## 문서 구조

| 문서 | 목적 |
| --- | --- |
| [00-overview.md](./00-overview.md) | 전체 문서의 단일 Overview |
| [01-product-direction.md](./01-product-direction.md) | 제품 포지셔닝과 핵심 메시지 |
| [02-feature-map.md](./02-feature-map.md) | 메모에서 나온 기능을 우선순위별로 구조화 |
| [03-llmops-gateway.md](./03-llmops-gateway.md) | LLM Gateway 중심 기능 정리 |
| [04-rag-data-governance.md](./04-rag-data-governance.md) | 동적 데이터, RAG, 청킹, 데이터 거버넌스 |
| [05-audit-rbac-compliance.md](./05-audit-rbac-compliance.md) | 감사 로그, RBAC, 컴플라이언스 관점 |
| [06-optimization-evaluation.md](./06-optimization-evaluation.md) | 모델/프롬프트/청크 최적화와 평가 |
| [07-implementation-roadmap.md](./07-implementation-roadmap.md) | 다음 주 데모 기준 구현 로드맵 |
| [08-interpretation-audit.md](./08-interpretation-audit.md) | 원문 대비 과한 해석, 모호한 표현, 확인 필요 사항 |

## 메모에서 반복된 핵심 판단

1. LLMOps Gateway 기능을 제품의 중심에 둔다.
2. 기업용 제품처럼 보이려면 보안, 감사, 권한, 비용, 신뢰성이 전면에 있어야 한다.
3. PII 탐지 하나만으로는 부족하고, 데이터 거버넌스와 리니지까지 보여야 한다.
4. RAG 데이터가 고정되지 않는 현실을 반영해야 한다.
5. 프롬프트 엔지니어링보다 청크 엔지니어링, 데이터 갱신, 평가 자동화가 더 중요하다.
6. 모델/프롬프트/청크/비용/품질을 비교하고 추천하는 시스템이 있어야 한다.
7. 배포 후에도 비용, 정책, 로그, 모델 사용량을 운영 관점에서 추적해야 한다.
8. 단순히 노드가 연결된 그림이 아니라, 기업이 실제로 운영할 수 있는 시스템처럼 보여야 한다.

## 발표용 제품 정의

Nodease는 기업용 AI Workflow / LLMOps 운영 플랫폼이다. 사용자는 AI 워크플로우를 노드 기반으로 설계하고, 실행 전에 모델/프롬프트/데이터 정책을 검증하며, 배포 이후에는 비용, 실패, 데이터 흐름, 권한 위반, 실행 이력을 감사할 수 있다.

멀티에이전트 포지셔닝은 `memo.md` 안의 ChatGPT 요약에서 강하게 등장하지만, 원문 직접 요구는 LLMOps Gateway, audit, RBAC, RAG 데이터 갱신, 비용 최적화 쪽이 더 강하다. 따라서 멀티에이전트는 보조 메시지로 두고, 중심 메시지는 기업용 LLMOps 운영으로 잡는 것이 더 안전하다.

## 구현 방향 요약

P0는 보여줄 수 있는 엔터프라이즈 LLMOps 경험을 만드는 것이다.

- LLM Gateway 대시보드: 모델 사용량, 비용, 실패, 지연시간, 요청 로그
- 노드별 비용/시간/토큰 표시
- 프롬프트/모델 비교 또는 추천 UI
- RAG 데이터 갱신/감사: 전체 재색인 vs 부분 재색인 vs incremental indexing, 어떤 청크가 사용됐는지 추적
- 감사 로그: 누가, 언제, 무엇을 실행/수정/배포했는지
- RBAC 최소 단위: 프로젝트/캔버스/데이터 소스에 대한 read/write/execute
- 데이터 리니지: 데이터가 어느 노드와 모델을 거쳐 어디로 갔는지
- 에디터 UX: Moduly보다 편한 property settings와 비교/추천 중심 UI
