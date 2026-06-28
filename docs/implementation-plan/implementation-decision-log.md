# 구현 결정 로그

Status: Draft
Authority: Implementation Plan
Source of Truth: No
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d
Related ADRs:

## 목적

이 문서는 구현 중 발생하는 작은 결정, 기본값, 임시 호환 처리, 테스트/rollout 판단을 기록한다.

이 문서는 ADR이 아니다. Requirements, Architecture, Data Model, API, Decision 문서와 충돌하면 상위 source-of-truth 문서를 따른다.

## ADR과의 구분

| 구분 | 위치 | 예시 |
| --- | --- | --- |
| 큰 정책/아키텍처 결정 | `decisions/` ADR | active organization 방식, audit table 재사용, RBAC schema 확장 |
| 작은 구현 결정 | 이 문서 | RAG chunk 기본값, 임시 compatibility mapping, 테스트 fixture 선택 |
| 확정된 현재 기준 | 각 권위 문서 | API request/response, table/column, 권한 matrix |

## 기록할 것

- 구현 중 정한 기본값
- 한 모듈 안에서의 tradeoff
- 임시 compatibility 처리
- 테스트, rollout, fallback 결정
- 나중에 ADR로 승격할 수 있는 후보 결정

## 기록하지 않을 것

- secret, token, credential, `.env` 값
- 단순 코드 스타일 선택
- 이미 상위 문서에 명확히 정의된 기준
- 여러 권위 문서를 바꾸는 큰 결정

## ADR 승격 기준

아래 중 하나라도 해당하면 이 문서에만 두지 말고 ADR 후보로 올린다.

- 여러 권위 문서나 여러 모듈에 영향을 준다.
- DB schema, RBAC, audit, data retention, organization boundary, 보안 경계에 영향을 준다.
- 되돌리기 어렵거나 migration이 필요하다.
- 제품 요구사항/API 계약/운영 정책이 바뀐다.
- 선택지를 비교한 근거를 나중에 방어해야 한다.

## 기본 양식

```md
## YYYY-MM-DD

### 결정 제목

- 상태: Active | Superseded | Promoted to ADR
- 맥락:
- 결정:
- 근거:
- 범위:
- 영향 파일:
- 관련 문서:
- 후속 검토:
- ADR 승격 여부: Yes | No
```

## 2026-06-27

### 구현 계획 디렉터리명

- 상태: Active
- 맥락: `implementation/` 이름은 코드 구현 전반이나 실제 구현 파일을 담는 디렉터리로 오해될 수 있다.
- 결정: 구현 순서, 이슈 분해, 검증 계획 문서는 `implementation-plan/` 디렉터리 아래에 둔다.
- 근거: 현재 문서 체계에서 해당 영역은 실행 코드가 아니라 source-of-truth 문서를 작업 단위로 분해한 계획이므로 `implementation-plan`이 더 명확하다.
- 범위: 활성 문서 루트의 구현 계획 문서 링크와 권위 표기.
- 영향 파일: `README.md`, `foundation/document-authority.md`, `requirements/README.md`, `decisions/ADR-*.md`, `implementation-plan/README.md`.
- 관련 문서: [implementation-plan/README.md](README.md)
- 후속 검토: 실제 개발 이슈 관리 도구로 분리되면 이 디렉터리의 역할을 다시 검토한다.
- ADR 승격 여부: No. 문서 분류와 링크 명확화에 한정되며 아키텍처나 제품 정책을 바꾸지 않는다.

### RAG chunk 기본값

- 상태: Active
- 맥락: RAG document preview와 ingestion의 초기 chunk 기본값이 필요하다.
- 결정: `chunk_size=500`, `chunk_overlap=50`을 기본값으로 사용한다.
- 근거: 초기 preview 속도와 검색 품질의 균형을 위한 구현 기본값이다.
- 범위: RAG preview/ingestion 기본 request 값.
- 영향 파일: `api/knowledge-rag.md`, RAG ingestion 관련 구현 파일.
- 관련 문서: [api/knowledge-rag.md](../api/knowledge-rag.md)
- 후속 검토: 실제 검색 품질과 비용을 평가한 뒤 조정한다.
- ADR 승격 여부: No. 단, 모든 tenant에 강제되는 제품 정책이 되거나 재색인 migration에 영향을 주면 ADR 후보로 승격한다.
