# ADR-0059: Judge Bootstrap과 점진 학습 로컬 모델 라우팅

Status: Accepted

Supersedes: [ADR-0058](ADR-0058-bootstrap-difficulty-routing-policy.md)

## Context

ADR-0045의 bootstrap 복잡도 회귀기는 Planner가 만든 소수 예시만으로 첫 요청부터
모델을 선택했다. 실제 운영 요청과 예시의 분포가 다르면, 로컬 회귀기는 충분한 근거 없이
낮거나 높은 모델을 선택할 수 있었다. 반대로 운영 성적만 신뢰하면 새 모델을 실행해
증거를 쌓지 못해 기본 모델에 고착될 수 있다.

Nodease는 첫 요청부터 자동 라우팅을 제공해야 하지만, 매 요청마다 Judge를 영구적으로
호출해 비용과 지연 시간을 계속 늘리는 구조도 피해야 한다.

## Decision

자동 모델 라우팅은 `judge_bootstrap_incremental_v1` 전략을 사용한다.

1. **Judge bootstrap**: 자동 라우팅을 처음 켠 배포 정책은 각 운영 요청마다 짧은 Judge
   호출을 실행한다. Judge는 현재 변수 치환이 끝난 요청과 노드의 고정 계약, 실행 주체가
   사용할 수 있는 후보 모델만 보고 선택 모델과 신뢰도를 반환한다.
2. **학습 표본**: Judge 선택, 후보 집합, 로컬 분류용 numeric artifact, 실제 실행 모델,
   schema/downstream/성공/비용/지연 결과를 정책 단위 안전 요약으로 남긴다. 원문 prompt,
   입력 payload, RAG 문서 원문, credential은 저장하지 않는다.
3. **점진 전환**: 로컬 mDeBERTa 모델 선택 분류기는 Judge가 부여한 선택 label을
   요청 처리 중 메모리에서 학습하고, 가중치만 정책 artifact에 저장한다. 완료된 운영 결과가
   최소 표본 수와 품질 기준을 충족하면 정책은 `local_first`로 전환한다.
4. **낮은 신뢰도 보완**: `local_first`에서도 로컬 분류기의 신뢰도가 기준 미만이거나,
   선택 모델이 현재 실행 주체에게 더 이상 허용되지 않으면 Judge를 다시 호출한다.
5. **안전한 실패 처리**: Judge 호출·응답 파싱·학습이 실패해도 workflow 실행은 막지 않는다.
   사용자가 정한 기본 모델과 기본 대체 모델로 닫는다.
6. **성과 반영**: 배포 후 운영 실행만 품질·비용·지연 성적에 반영한다. 재평가 주기에는
   완료된 Judge 표본과 운영 성적을 점검해 local-first 전환을 유지하거나 Judge-first로
   되돌린다. Test Sidebar 실행은 학습 및 집계 대상이 아니다.

Judge 비용은 일반 LLM 실행 비용과 구분해 같은 workflow run의 별도 usage row와 trace
metadata에 기록한다. 따라서 운영 총비용에는 포함되지만 노드 본 실행의 모델 성적을
오염시키지 않는다.

## Consequences

- 새 workflow도 첫 배포 실행부터 Judge가 여러 후보 중 하나를 선택하므로, 검증 모델이
  없어 기본 모델만 계속 쓰는 순환 구조를 만들지 않는다.
- 초기에는 요청당 Judge 비용과 지연 시간이 추가된다. 이 비용은 local-first 전환 뒤에는
  낮은 신뢰도 요청에만 발생한다.
- 로컬 모델은 Judge의 결정을 그대로 흉내 내는 데서 끝나지 않는다. 운영 결과의
  schema/downstream/실행 성공률이 기준을 통과하지 못하면 local-first 전환을 보류하거나
  되돌린다.
- 과거 전략의 DB row와 migration schema는 데이터 호환을 위해 유지하지만 신규 runtime은
  이를 실행하지 않는다. refresh 시 정적 rule을 제거한 Judge-first 정책으로 한 번 이관하고,
  이관 전 실행은 노드에 저장된 기본 모델로 안전하게 닫는다.
