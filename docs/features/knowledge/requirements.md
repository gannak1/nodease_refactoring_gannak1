# Knowledge Requirements

Status: Draft
Related Features: auth, organization, workflow, agent-builder

## Purpose

흩어진 사내 데이터를 하나의 지식 베이스로 통합하고, 질문한 사용자의 권한에 맞는 자료만 검색해 답변하는 통합 RAG를 제공한다. [PRD](../../PRD.md)의 FR-031~FR-033을 담당한다.

KB 구축/검색과 metadata-aware·hierarchical retrieval은 구현돼 있으며, 이 feature의 범위는 통합 저장소로서의 보강, 검색 품질/성능 개선, citation 추적 UX다. 용어와 경계는 [ADR-0012](../../decisions/ADR-0012-metadata-aware-hierarchical-rag-boundary.md)를 따른다.

## User Stories

- 빌더로서, 사내 문서를 Knowledge Base에 올리고 팀 단위로 사용 권한을 부여하고 싶다.
- 현업 사용자로서, 질문하면 내 권한 안의 자료에서 찾은 답변과 출처(citation)를 받고 싶다.
- 감사자로서, 특정 답변이 어떤 문서 조각에서 나왔는지 retrieval 기록으로 추적하고 싶다.

## Functional Requirements

- FR-031: 문서 업로드/색인과 KB 단위 권한 관리를 제공한다. KB 접근은 organization scope와 team/user knowledge permission으로 판정한다.
- FR-032: 검색은 권한 필터와 allowlist 기반 metadata 필터를 적용하고, 답변에 citation을 반환한다.
- FR-033: retrieval 기록을 redaction-safe metadata(chunk/document id, rank, score)로 남기고 추적할 수 있다. raw chunk content는 trace에 저장하지 않는다.

## Policies And Edge Cases

- Metadata는 permission source가 아니다. 권한 판정은 organization manager override와 team/user knowledge permission의 effective permission으로만 한다.
- `pii`/`confidential` classification 문서는 [ADR-0007](../../decisions/ADR-0007-mvp2-classification-metadata-storage.md)과 ADR-0012의 정책(`policy.block`/`policy.warn`, audit 기록)을 따른다.
- 권한 없는 KB는 검색 결과에서 제외될 뿐 존재 여부를 노출하지 않는다.

## Open Questions

- 통합 대상 데이터 소스 범위: 파일 업로드 외에 어떤 사내 시스템(위키, 드라이브 등)을 연동할지.
- 검색 품질 개선의 측정 기준(평가셋, 지표)을 무엇으로 둘지 — `tests/evaluation`의 RAG 벤치마크와 연결 여부.
