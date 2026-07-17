# Flat/Hierarchical RAG Corpus Inputs

이 디렉토리는 비교 벤치마크의 재현 가능한 입력 정의만 저장한다. 국가법령정보센터 응답에서 credential-bearing detail link를 제거한 source JSON, 정규화 결과, 비공개 holdout 질문 및 실행 산출물은 Git에 저장하지 않는다.

## 데이터 트랙

- `kr-law-dry-run-v1/`: 현행 법령, 최근 연혁, 행정규칙, 탐색적 판례의 선택 카탈로그와 출처 고지
- `enterprise-policy-v1/`: 가상 기업 규정 12개 문서와 개발용 질문 20개

두 트랙 모두 개발·파이프라인 검증용이다. 확인적 성능 결론에는 별도로 동결한 로컬 holdout과 독립 평가자가 확정한 qrels를 사용한다.

Public-law 질문은 source catalog에 추가하지 않는다. 수집된 immutable snapshot에서 `draft-law-development`로 ignored local question bundle을 만들며, machine-assisted 질문과 evidence mapping은 사람의 semantic/answerability/evidence review 전까지 `pending_human_review`다.

## 저장 경계

준비 명령은 결과를 `local/evaluation-data/mba-279/<track>/<snapshot-id>/`에만 생성한다. 스냅샷은 기존 디렉토리를 덮어쓰지 않으며, 원문과 질문은 보고서에 직접 복사하지 않는다.
