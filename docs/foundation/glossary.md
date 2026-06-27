# 용어집

Status: Draft
Authority: Foundation
Source of Truth: Yes
Verified Against: origin/dev @ 5def9053fe5d72e7ac67fe2e27c8545a5124791d

| 용어 | 의미 |
| --- | --- |
| App | 제품상 project boundary. 기존 `apps` table을 사용한다. |
| Canvas | 제품상 workflow editing surface. 기존 `workflows`를 사용한다. |
| Organization | 조직 범위와 tenant-like boundary. 기존 `organization` table을 사용한다. |
| Team | Organization 안의 권한 부여 단위. 기존 `teams` table을 사용한다. |
| TeamMembership | User가 Organization의 Team에 속한다는 관계. 기존 `team_memberships` table을 사용한다. |
| Team permission | Resource별 team 권한. `team_workflow_permissions`, `team_knowledge_permissions`, `team_llm_permissions`, `team_audit_permissions`를 사용한다. |
| User direct permission | Team 권한으로 처리하기 어려운 user별 additive allow 예외 권한. ADR 승인이 필요하다. |
| auth_state | DB enum이 아닌 application-level permission state string. 최종 표준 전환은 ADR을 따른다. |
| Audit | 사용자 action과 data change 기록. MVP 목표 상태에서는 `audit_logs`를 canonical table로 사용한다. |
| Trace payload | raw/redacted payload 분리 저장 구조. MVP 목표 상태에서는 `trace_payloads`와 `trace_payload_access_events`를 사용한다. |
