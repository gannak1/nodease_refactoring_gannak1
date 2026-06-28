# 구현 계획

Status: Draft
Authority: Implementation Plan
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

구현 계획 문서는 source-of-truth 문서를 실제 작업 순서와 이슈로 분해한다.

| 문서 | 역할 |
| --- | --- |
| [mvp-1-development-issue-plan.md](mvp-1-development-issue-plan.md) | MVP 1 개발 이슈 생성 계획 |
| [mvp-2-0-organization-membership-plan.md](mvp-2-0-organization-membership-plan.md) | MVP 2 선행 Organization membership/invitation 기반 계획 |
| [risk-consistency-verification.md](risk-consistency-verification.md) | 리스크, 정합성, 검증 매트릭스 |
| [implementation-decision-log.md](implementation-decision-log.md) | 구현 중 작은 결정, 기본값, 임시 호환 처리 기록 |

## 권위

- 구현 계획이 requirements, architecture, data-model, api 문서와 충돌하면 구현 계획을 수정한다.
- 미결정 ADR을 구현 전제로 삼지 않는다.
- 새 policy, architecture, security, data-storage 결정은 [decisions/](../decisions/README.md)에 기록한다.
- 작은 구현 결정은 [implementation-decision-log.md](implementation-decision-log.md)에 기록하되, 상위 source-of-truth와 충돌하면 상위 문서를 따른다.
