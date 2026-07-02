# Cost Optimizer Requirements

Status: Draft
Related Features: workflow, llm-credentials, deployment, admin-dashboard

## Purpose

workflow의 현재 모델과 더 저렴한 후보 모델을 실제 실행으로 비교해, 비용 절감과 품질 트레이드오프를 근거로 제시한다. [PRD](../../PRD.md)의 FR-021~FR-022를 담당한다.

모델 비교 실행 API(`POST /api/v1/workflows/{workflow_id}/compare`)는 구현돼 있으며, 이 feature의 범위는 비교를 "비용 최적화" 흐름으로 묶는 UI와 추천 리포트다. **진입점과 실행 문맥은 workflow 화면이다.** Admin 대시보드는 비용이 큰 workflow를 발견해 이 흐름으로 이동하는 경로만 제공한다.

## User Stories

- 빌더로서, workflow 화면에서 "비용 최적화"를 실행해 더 싼 모델과의 비교 결과를 보고 싶다.
- 빌더로서, "모델 교체 시 비용 X% 절감, 품질 차이 Y" 요약을 보고 교체 여부를 결정하고 싶다.
- 플랫폼 관리자로서, 대시보드에서 비용이 큰 workflow를 찾아 해당 workflow의 비용 최적화 흐름으로 이동하고 싶다.

## Functional Requirements

- FR-021: workflow의 현재 모델과 후보 모델을 비교 실행한다. 기존 compare API를 사용하고 별도 실행 경로를 만들지 않는다.
- FR-022: 비교 결과를 비용 절감률과 품질 차이로 요약한 추천 리포트를 표시한다.

## Policies And Edge Cases

- 비교 실행에도 workflow 실행 권한과 대상 credential의 `use` 권한이 필요하다.
- 비교 실행에서 발생한 LLM 호출도 usage/비용으로 기록한다. 최적화 기능 자체의 비용이 숨겨지면 안 된다.
- 후보 모델은 요청 organization에서 사용 가능한(verified credential-model relation이 있는) 모델로 제한한다.

## Open Questions

- "품질 차이 Y"의 산정 방식: LLM judge, 규칙 기반, 사람 평가 — PRD Open Question과 연결.
- 후보 모델 선정 기준(가격표 기반 자동 추천 vs 사용자 지정).
