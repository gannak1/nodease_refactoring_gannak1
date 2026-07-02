# Nodease - Product Requirements Document

Status: Draft

> 명칭: Nodease는 기존 Moduly 코드를 리팩토링해 만드는 신규 서비스명이다. 코드와 배포 리소스에는 아직 `Moduly` 명칭이 남아 있으므로, 이 문서는 제품 관점에서는 Nodease를 사용하고 기존 코드/인프라 식별자는 Moduly 기준으로 읽는다.

## 1. 제품 개요

Nodease는 기존 Moduly 코드를 리팩토링해 만드는 기업 내부 AI 플랫폼이다. 한 회사의 플랫폼 조직이 운영하고, 사내 여러 팀이 AI workflow를 만들고 실행하고 배포하는 데 사용한다. 기존 Moduly의 workflow builder/runtime 위에 조직 단위 권한(RBAC), 감사/추적(audit/tracing), LLM 사용량/비용 관측을 내장해 "만들 수 있는 플랫폼"을 "운영할 수 있는 플랫폼"으로 확장한다.

### 해결하는 문제

사내 LLM 활용이 늘어날 때 생기는 세 가지 운영 문제를 해결한다.

1. **자동화 진입 장벽**: 비개발자 현업은 workflow를 직접 조립하기 어렵다. 자연어로 요청하면 실행 가능한 workflow가 만들어져야 한다.
2. **추적 불가능한 사용**: 누가 어떤 데이터와 모델을 언제 사용했는지 조직 차원에서 답할 수 없다. 권한 차단과 감사 기록이 기본값이어야 한다.
3. **통제되지 않는 비용**: LLM 호출 비용이 workflow/팀 단위로 보이지 않고, 더 싼 모델로 바꿀 근거도 없다.
4. **흩어진 사내 지식**: 문서가 시스템마다 흩어져 있어 필요한 정보를 찾기 어렵고, 권한 통제 없이 한곳에 모으면 봐서는 안 될 사람에게 노출된다.

### 핵심 가치

- **자연어로 시작하는 자동화**: 프롬프트 한 줄로 workflow 초안이 생성된다 (Agent Builder).
- **권한과 감사가 내장된 운영**: 모든 리소스 접근은 organization/team/user 권한으로 판정되고, 주요 행위는 audit log로 남는다.
- **모든 사내 데이터가 모이는 통합 RAG**: 흩어진 사내 데이터를 하나의 지식 베이스로 통합하고, 질문한 사용자의 권한에 맞는 자료만 찾아 답변한다.
- **비용을 아는 운영**: workflow별 비용이 보이고, 모델 교체 시 절감/품질 트레이드오프를 제시한다.

## 2. 사용자

기업 내부 사용자를 RBAC 역할 기준으로 구분한다. 권한 상태 정의는 [ADR-0006](decisions/ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md)을 따른다.

| 사용자 | 역할 | 주요 행동 |
| --- | --- | --- |
| 플랫폼 관리자 | organization owner/manager | 조직/팀/멤버 관리, 권한 부여, 운영 대시보드 확인 |
| 빌더 | builder | workflow 생성/편집/배포, Agent Builder 사용 |
| 현업 사용자 | operator/viewer | 배포된 workflow 실행, RAG 질의 |
| 감사자 | auditor/raw_auditor | audit log 검색, 접근 이력 확인 |

## 3. 범위 정의

### 3.1 이번 범위: 4개 데모 축

| 축 | 현재 상태 | 이번에 만드는 것 |
| --- | --- | --- |
| **Agent Builder** | node 단위 wizard만 존재 (prompt/code/template 개선·생성) | 프롬프트 입력 → workflow 자동 생성. 예: "고객 문의 이메일을 분류하고 답변해줘" → `[Webhook] → [LLM 분류] → [Condition] → [LLM 답변] → [이메일]` |
| **Admin 대시보드** | `audit_logs`, `llm_usage_logs`, `workflow_runs` 데이터는 이미 쌓임 | 조회 UI: 누가 언제 뭘 했는지(audit), workflow별 비용(usage), 비정상 접근 시도 표시, 유저 비활성화 |
| **비용 최적화** | `POST /api/v1/workflows/{id}/compare` 모델 비교 API 구현됨 | "비용 최적화" UI: 현재 모델 vs 더 싼 모델 자동 비교 → "모델 교체 시 비용 X% 절감, 품질 차이 Y" 표시 |
| **통합 RAG** | KB 구축/검색, metadata-aware·hierarchical retrieval 구현됨 | 사내 데이터 통합 저장소로서의 보강과 검색 품질/성능 개선, citation 추적 UX |

### 3.2 기반 기능 (구현됨, 유지 대상)

이번 범위의 전제가 되는 기존 기능이다. 깨뜨리지 않는 것이 요구사항이다.

- Workflow 생성/편집/실행/배포 (schedule/webhook/API 트리거 포함)
- Organization/Team 관리, 초대, RBAC 권한 부여와 차단
- LLM credential 관리와 모델 연결
- Audit/tracing 기록 (canonical action 기준: [ADR-0008](decisions/ADR-0008-audit-action-naming-standard.md))

### 3.3 제외 (이번 범위 아님)

- 외부 고객 대상 SaaS 과금/구독
- SSO/외부 IdP 연동
- Marketplace 공개 정책, deployment 권한 고도화 ([ADR-0010](decisions/ADR-0010-resource-access-403-404-policy.md) 제외 항목)
- user direct audit permission (`user_audit_permissions`)
- explicit deny 권한 모델 ([ADR-0006](decisions/ADR-0006-accept-rbac-auth-state-and-user-direct-permission.md)에서 도입하지 않기로 결정)
- 모바일 전용 UI

## 4. 사용자 시나리오

### 시나리오 1: 자연어로 workflow 만들기 (빌더)

1. 빌더가 Agent Builder에 "고객 문의 이메일을 받아서 자동으로 분류하고 답변해줘"를 입력한다.
2. 시스템이 노드 그래프 초안(`Webhook → LLM 분류 → Condition → LLM 답변 → 이메일`)을 생성해 캔버스에 표시한다.
3. 빌더가 노드 설정을 확인/수정하고 테스트 실행한다.
4. 결과 확인 후 배포한다. 배포는 `workflow.deploy`로 audit에 기록된다.

### 시나리오 2: 조직/권한 관리 (플랫폼 관리자)

1. 관리자가 조직에 멤버를 초대하고, 팀에 배정한다.
2. 팀/개인 단위로 workflow와 LLM credential 권한(auth_state)을 부여한다.
3. 권한 없는 사용자가 workflow 실행을 시도하면 403으로 차단되고 `permission.denied`가 audit에 남는다. 다른 조직 리소스는 404로 숨겨진다.
4. 관리자가 대시보드에서 차단 이력을 확인한다.

### 시나리오 3: 통합 RAG 질의와 추적 (현업 사용자 + 감사자)

1. 빌더가 사내 문서를 Knowledge Base에 업로드하고 팀에 사용 권한을 부여한다.
2. 현업 사용자가 질문하면 권한과 metadata 필터가 적용된 검색으로 답변과 citation을 받는다.
3. 감사자가 해당 답변의 retrieval 기록(chunk/document id, score)을 추적한다. raw 본문은 trace에 저장되지 않는다 ([ADR-0012](decisions/ADR-0012-metadata-aware-hierarchical-rag-boundary.md)).

### 시나리오 4: 감사/비용 관측과 모델 최적화 (플랫폼 관리자)

1. 관리자가 Admin 대시보드에서 기간별 audit log를 검색한다 (행위자, action, 대상 필터).
2. workflow별 LLM 비용을 확인하고 비용이 큰 workflow를 찾는다.
3. "비용 최적화"를 실행해 현재 모델과 후보 모델의 실행 결과·비용을 비교한다.
4. "모델 교체 시 비용 X% 절감, 품질 차이 Y" 리포트를 보고 교체를 결정한다.
5. 비정상 접근 시도를 확인하고 필요 시 해당 유저를 비활성화한다.

## 5. 핵심 기능 목록

세부 명세(API, 화면, 테스트)는 각 feature 문서를 기준으로 한다. PRD는 무엇이 필요한지만 정의한다.

### Agent Builder — [features/agent-builder/](features/agent-builder/requirements.md)

- FR-001: 자연어 프롬프트로부터 실행 가능한 workflow 노드 그래프 생성
- FR-002: 생성된 workflow의 캔버스 편집과 테스트 실행
- FR-003: 생성 결과에 필요한 credential/권한이 없으면 사전 안내

### Admin 대시보드 — [features/admin-dashboard/](features/admin-dashboard/requirements.md)

- FR-011: audit log 검색/필터 (행위자, action, 대상, 기간)
- FR-012: workflow별 LLM 사용량/비용 집계 표시
- FR-013: 권한 차단(`permission.denied`) 등 비정상 접근 시도 표시
- FR-014: 유저 비활성화 (기존 `deactivated_at` 활용)

### 비용 최적화 — [features/cost-optimizer/](features/cost-optimizer/requirements.md)

- FR-021: workflow의 현재 모델 vs 후보 모델 비교 실행 (기존 compare API 활용)
- FR-022: 비용 절감률과 품질 차이를 요약한 추천 리포트

### 통합 RAG — [features/knowledge/](features/knowledge/requirements.md)

- FR-031: 사내 문서 업로드/색인과 KB 단위 권한 관리
- FR-032: 권한·metadata 필터가 적용된 검색과 citation 반환
- FR-033: retrieval 기록 추적 (redaction-safe metadata 기준)

## 6. 비기능 요구사항

| ID | 항목 | 기준 |
| --- | --- | --- |
| NFR-001 | 권한 enforcement | 모든 리소스 API는 서버(Gateway)에서 권한을 판정한다. 프론트 UI 차단만으로 처리하지 않는다. |
| NFR-002 | 테넌시 경계 | 리소스 접근은 organization 경계 안에서만 허용한다 (`X-Organization-Id`, [ADR-0009](decisions/ADR-0009-active-organization-header-context.md)). |
| NFR-003 | 감사 기록 | 주요 행위는 canonical audit action으로 기록한다 ([ADR-0008](decisions/ADR-0008-audit-action-naming-standard.md)). |
| NFR-004 | Secret 비노출 | credential 원문, API key, token, raw payload는 응답/로그/trace에 노출하지 않는다. |
| NFR-005 | 기존 경로 보존 | workflow 생성/저장/실행/배포의 기존 경로가 깨지지 않는다. |
| NFR-006 | 성능 목표 | TBD (데모 환경 기준 목표치 확정 필요) |

## 7. 성공 지표

이 프로젝트의 성공 기준은 **데모 시나리오 완주**다. 아래 조건이 모두 시연 환경에서 끝까지 동작하면 성공으로 판단한다.

- [ ] 시나리오 1: 프롬프트 입력부터 배포까지 사전 조작 없이 완주
- [ ] 시나리오 2: 권한 부여 → 차단(403) → audit 확인이 실제 데이터로 재현
- [ ] 시나리오 3: 문서 업로드부터 citation 추적까지 완주, 권한 없는 KB는 검색에서 제외됨을 시연
- [ ] 시나리오 4: 비용 확인 → 모델 비교 → 절감 리포트 표시까지 완주

## 8. Open Questions

- Agent Builder가 생성할 수 있는 노드 타입 범위를 어디까지 허용할지 (전체 vs 안전한 부분집합)
- 비용 최적화의 "품질 차이 Y"를 어떤 지표로 계산할지 (LLM judge, 규칙 기반, 사람 평가)
- Admin 대시보드의 "비정상 접근"을 어떤 기준으로 정의할지 (차단 횟수 임계값 등)
- NFR-006 성능 목표치
