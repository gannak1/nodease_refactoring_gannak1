# ADR-0058: 로그 유무를 모두 처리하는 Bootstrap 난이도 라우팅 정책

Status: Accepted

Related ADRs: [ADR-0038](ADR-0038-workflow-aware-adaptive-routing.md)

## Context

기존 자동 모델 라우팅은 검증된 입력군과 후보 모델 증거가 있어야 rule을 만들 수 있었다.
그래서 자동 라우팅을 처음 켠 노드는 운영 로그와 검증 증거가 없다는 이유로 저장 모델을
계속 사용했고, 새 모델을 실행해 증거를 만드는 단계도 시작하지 못하는 순환 문제가 있었다.

또한 이미 운영 로그가 있는 workflow와 새 workflow를 같은 방식으로 다루면 안 된다.
운영 로그가 충분한 경우에는 실제 요청의 형태를 학습 재료로 써야 하고, 로그가 없거나
부족한 경우에는 작업 설정으로부터 실행 가능한 입력 예시를 보완해야 한다.

## Decision

자동 모델 라우팅을 켤 때 workflow/node 단위 `routing bootstrap` artifact를 만든다.
artifact의 작업 지문은 prompt, 입력 매핑, 출력 schema, RAG 설정, downstream 계약을
포함하고 수동 모델/fallback/토글 값은 제외한다. 따라서 모델만 바뀌면 artifact를 재사용할
수 있지만, 실제 작업을 바꾸는 설정이 바뀌면 artifact는 오래됨 상태가 된다.

초기 표본은 다음처럼 선택한다.

| 같은 작업 지문의 성공 운영 로그 | 표본 구성 | bootstrap source |
| --- | --- | --- |
| 0건 | Planner가 생성한 안전한 합성 payload | `synthetic` |
| 1~11건 | 가림 처리한 운영 표본과 부족한 범위의 합성 payload | `hybrid` |
| 12건 이상 | 최대 24개 대표 운영 표본 | `history` |

Planner는 표본을 `economy`, `balanced`, `advanced` 난이도로 라벨링한다. mDeBERTa
분류기는 저장된 표본 feature로 난이도별 중심 벡터를 만들고, runtime은 현재 입력과 노드
작업 지문을 이 분류기에 넣어 난이도 확률을 계산한다. confidence가 기준보다 낮으면 사용자가
정한 기본 모델을 사용하고, provider 호출이 실패한 경우에만 기본 대체 모델을 한 번 시도한다.

초기 routing은 후보 모델의 사전 품질 검증을 기다리지 않는다. 실행 주체가 사용할 수 있는
채팅 모델을 경제형/균형형/고성능형 후보로 분류해 첫 배포부터 routing한다. 모델별 품질·비용
증거는 배포 후 별도 replay 재평가에서 쌓고, 품질 gate를 통과한 경우에만 난이도별 모델을
교체한다. 일반 실행마다 Planner나 Judge LLM을 호출하지 않는다.

## Consequences

- 새 workflow도 초기 bootstrap 생성이 끝나면 첫 배포 실행부터 여러 모델로 routing할 수 있다.
- 초기 Planner 호출 비용은 사용자가 정한 1회 예산에서만 사용하고, 배포 후 replay 비용은
  월간 재검증 예산에서 분리한다.
- 운영 원문 입력과 RAG 원문은 artifact/sample DB에 저장하지 않는다. 안전 요약, feature hash,
  Planner가 부여한 난이도와 근거만 저장한다.
- mDeBERTa 모델 가중치는 Docker 이미지에 포함되거나 첫 기동 시 model cache에서 준비되어야
  한다. 준비에 실패하면 runtime은 기본 모델로 닫고 routing 자체가 workflow 실행을 막지 않는다.
- ADR-0038의 semantic cohort/catalog 중심 initial routing 결정은 이 ADR로 대체한다. 기존
  cohort table과 호환 API는 삭제 전까지 이력/호환 용도로만 유지한다.
