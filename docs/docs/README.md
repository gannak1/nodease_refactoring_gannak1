# Nodease 문서

Status: Draft
Authority: Documentation Index
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

이 디렉터리는 향후 저장소 루트의 `docs/`로 이동될 문서 세트다. 현재 물리 경로명은 임시 이름이므로 문서 내부 링크와 권위 규칙은 이 디렉터리를 문서 루트로 간주한다.

## 단일 기준 문서

문서 충돌은 [foundation/document-authority.md](foundation/document-authority.md)를 따른다.

| 영역 | 기준 문서 |
| --- | --- |
| 문서 권위, 용어, 범위 | [foundation/](foundation/README.md) |
| MVP 요구사항, 완료 기준, 제외 범위 | [requirements/](requirements/README.md) |
| 서비스 경계, 런타임, 보안/RBAC 구조 | [architecture/](architecture/README.md) |
| 물리 데이터 모델, 권한 정책, migration 정책 | [data-model/](data-model/README.md) |
| API 계약 | [api/](api/README.md) |
| 비가역적/중요 설계 결정 | [decisions/](decisions/README.md) |
| 구현 순서, 이슈 분해, 검증 계획 | [implementation-plan/](implementation-plan/README.md) |
| 과거 조사, 메모, 폐기 문서 | [references/](references/README.md) |

## 활성 문서

- [requirements/overview.md](requirements/overview.md)
- [requirements/mvp-1-foundation-llmops.md](requirements/mvp-1-foundation-llmops.md)
- [requirements/mvp-2-governance-rag-audit.md](requirements/mvp-2-governance-rag-audit.md)
- [requirements/mvp-3-enterprise-ops.md](requirements/mvp-3-enterprise-ops.md)
- [data-model/physical-data-model.md](data-model/physical-data-model.md)
- [data-model/rbac-permission-policy.md](data-model/rbac-permission-policy.md)
- [api/README.md](api/README.md)
- [implementation-plan/mvp-1-development-issue-plan.md](implementation-plan/mvp-1-development-issue-plan.md)
- [implementation-plan/risk-consistency-verification.md](implementation-plan/risk-consistency-verification.md)

## 참조 문서

참조 문서는 구현 기준이 아니다. 과거 분석이나 아이디어의 출처로만 사용한다.

- [references/moduly-architecture/](references/moduly-architecture/README.md): 과거 Moduly 역공학 참고 문서
- 삭제된 로컬 메모와 폐기 초안은 구현 기준이 아니다.

## 작성 규칙

- 한 문서는 하나의 권위 영역만 다룬다.
- 요구사항, 아키텍처, 데이터 모델, API 계약, 구현 계획을 한 파일에 섞지 않는다.
- 중요한 설계 변경은 [decisions/](decisions/README.md)에 ADR로 남긴다.
- `references/` 아래 문서는 active source of truth가 아니다.
- 문서 내부 링크는 이 문서 루트를 기준으로 상대 경로를 사용한다.
