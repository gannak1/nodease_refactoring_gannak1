# Cost Optimizer Requirements

Status: Draft
Related Features: workflow, llm-credentials, deployment, admin-dashboard, knowledge

## 목적

workflow의 현재 모델과 더 저렴한 후보 모델을 실제 실행으로 비교해, 비용 절감과 품질 트레이드오프를 근거로 제시한다. [PRD](../../PRD.md)의 FR-021~FR-022를 담당한다.

모델 비교 실행 API(`POST /api/v1/workflows/{workflow_id}/compare`)는 구현돼 있으며, 이 feature의 범위는 비교를 "비용 최적화" 흐름으로 묶는 UI와 추천 리포트다. **진입점과 실행 문맥은 workflow 화면이다.** Admin 대시보드는 비용이 큰 workflow를 발견해 이 흐름으로 이동하는 경로만 제공한다.

## 사용자 이야기

- 빌더로서, workflow 화면에서 "비용 최적화"를 실행해 더 싼 모델과의 비교 결과를 보고 싶다.
- 빌더로서, "모델 교체 시 비용 X% 절감, 품질 차이 Y" 요약을 보고 교체 여부를 결정하고 싶다.
- 플랫폼 관리자로서, 대시보드에서 비용이 큰 workflow를 찾아 해당 workflow의 비용 최적화 흐름으로 이동하고 싶다.

## 기능 요구사항

- FR-021: workflow의 현재 모델과 후보 모델을 비교 실행한다. 기존 compare API를 사용하고 별도 실행 경로를 만들지 않는다.
- FR-022: 비교 결과를 비용 절감률과 품질 차이로 요약한 추천 리포트를 표시한다.
- FR-023: RAG를 포함한 workflow 비교 실행은 일반 workflow 실행과 동일한 execution subject, KB permission, source ACL/requester authorization, final evidence policy gate를 사용한다.
- FR-024: RAG strategy 또는 model A/B 비교 summary는 Knowledge feature의 redaction-safe summary allowlist만 사용한다.
- FR-025: RAG strategy A/B에서 LLM node의 RAG 옵션 구성에 사용된 Knowledge Skill version 또는 freshness/eval state가 비교 변수로 쓰일 수 있다. 이 경우 비교 summary는 safe skill id/version/freshness/eval status만 표시한다.

## 정책과 Edge Case

- 비교 실행에도 workflow 실행 권한과 대상 credential의 `use` 권한이 필요하다.
- 비교 실행에서 발생한 LLM 호출도 usage/비용으로 기록한다. 최적화 기능 자체의 비용이 숨겨지면 안 된다.
- 후보 모델은 요청 organization에서 사용 가능한(verified credential-model relation이 있는) 모델로 제한한다.
- RAG 포함 비교에서 `general RAG` baseline을 사용하더라도 권한 없는 문서가 prompt, citation, trace, audit, 비교 UI에 들어가면 안 된다.
- 비교 리포트에는 context token estimate, retrieved chunk count, citation count, cost, latency, policy result, query rewrite 적용 여부, evidence sufficiency 결과, source tier summary 같은 safe summary만 표시한다. 권한 없는 문서명/ID, raw source metadata, raw rewritten query, raw prompt/completion, raw chunk content는 표시하지 않는다.
- Skill 기반 비교 리포트에도 raw skill body, hidden source refs, raw source title/path/url, restricted document list, raw eval fixture를 표시하지 않는다.
- `llm_assisted` query rewrite를 비교 변수로 삼으면 rewrite LLM call의 usage/cost도 비교 비용에 포함해야 한다. 단, 이 기능은 Knowledge G14 gate가 닫힌 뒤에만 사용할 수 있다.

## 열린 질문

- "품질 차이 Y"의 산정 방식: LLM judge, 규칙 기반, 사람 평가 — PRD Open Question과 연결.
- 후보 모델 선정 기준(가격표 기반 자동 추천 vs 사용자 지정).
- RAG strategy A/B 테스트의 품질 지표와 Knowledge retrieval summary field를 어떤 feature가 최종 소유할지.
- Skill version/freshness 차이를 비용 최적화 추천에서 자동 변수로 삼을지, 사용자가 명시 선택할 때만 비교할지.
