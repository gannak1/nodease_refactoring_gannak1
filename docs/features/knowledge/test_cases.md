# Knowledge Test Cases

Status: Draft
Verified Against: TBD

[PRD](../../PRD.md) 시나리오 3과 FR-031~FR-033을 검증한다. 경계 근거는 [ADR-0012](../../decisions/ADR-0012-metadata-aware-hierarchical-rag-boundary.md), [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)이다.

## Unit Tests

- (FR-032) metadata filter가 allowlist 기반으로 동작한다: 허용되지 않은 key/operator, free-form dict, JSONPath, raw SQL fragment는 거부된다.
- (FR-032) `meta_info.classification`이 없는 문서는 `internal`로 해석된다 ([ADR-0007](../../decisions/ADR-0007-mvp2-classification-metadata-storage.md)).
- hierarchical retrieval: parent chunk는 coarse retrieval에 사용되고 최종 citation은 child chunk로 반환된다. hierarchy가 없는 flat KB는 fallback으로 동작한다.
- `document_chunks.metadata`와 `documents.meta_info`가 충돌하면 document 값을 우선한다.

## API Tests

- (FR-031) 문서 업로드 → 색인 상태 전이(`documents.status`)가 정상 완료되고, 실패 시 `error_message`가 남는다.
- (FR-031) KB 권한 부여/회수 API가 team knowledge permission row를 생성/삭제하고 data-change audit(`team_knowledge_permission.*`)을 기록한다.
- (FR-032) 검색 응답에 citation(document/chunk id, rank, score, filename/heading)이 포함되고 raw chunk content 노출 규칙을 따른다.
- (FR-033) retrieval 기록이 redaction-safe metadata(chunk/document id, score summary)로 저장되고, raw chunk content가 trace에 저장되지 않는다.
- standalone answer 실행 시 `rag_answer_runs` row가 생성되고 `correlation_id`로 audit과 연결된다. raw query/answer는 저장되지 않는다.

## E2E Tests

- **시나리오 3 완주**: 빌더가 문서 업로드 → 관리자(또는 KB manager)가 팀에 `use` 권한 부여 → 현업 사용자 질의 → 권한/metadata 필터 적용된 답변 + citation 수신 → 감사자가 retrieval 기록 추적.
- **권한 제외 시연**: 권한 없는 KB의 문서가 검색 결과에 포함되지 않음을 같은 질의로 시연한다 (성공 지표 항목).

## Permission Tests

- KB `use` 권한이 없는 사용자의 검색에서 해당 KB가 제외되고, KB 존재 여부가 노출되지 않는다.
- `manage` 권한이 없는 builder의 KB 권한 부여 시도 → `403 permission.denied` (권한 부여는 organization owner/manager 또는 해당 KB의 effective manager만 가능).
- organization membership만으로는 KB `read`/`use`가 허용되지 않는다 — team/user permission 또는 manager override가 필요하다 (metadata는 permission source가 아니다).
- 다른 organization의 KB id로 접근 → `404 resource.not_found`.
- `pii` classification 문서가 external LLM prompt 경로에 포함될 때 `policy.block` + audit 기록, internal search preview에서는 `policy.warn`.
- `confidential` 문서는 KB `use` 통과 시 허용하되 policy result가 audit/trace에 남는다.

## Edge Cases

- 검색 결과가 없는 질의 → 빈 citation의 정상 응답 (오류 아님).
- 색인 중 실패한 문서는 검색 대상에서 제외되고 재색인이 가능하다.
- 삭제된 문서/chunk를 참조하는 과거 retrieval 기록이 깨지지 않는다 (id 참조만 저장하므로 조회 시 누락 허용).
- retrieval 기록과 `rag_answer_runs`의 retention 만료(`retention_expires_at`) 후 purge가 동작하고 `rag.answer.purge` audit이 남는다.
