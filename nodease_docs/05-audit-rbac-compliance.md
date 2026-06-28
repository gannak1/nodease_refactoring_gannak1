# Audit, RBAC, Compliance

## 왜 중요한가

메모에서 기업용 품질을 위해 가장 강조된 것은 감사와 접근 권한이다. 기업에서는 "잘 실행된다"만으로 부족하고, 누가 무엇을 했는지, 어떤 데이터가 어디로 갔는지, 어떤 정책이 적용됐는지를 나중에 증명할 수 있어야 한다.

## 감사 로그

감사 로그는 모든 중요한 행위를 시간순으로 남기는 기능이다.

### 실행 로그

- 워크플로우 실행 시작/종료
- 노드별 실행 상태
- LLM 호출 모델
- 입력/출력 토큰
- 비용
- 지연시간
- 실패 원인
- fallback 여부, 구현 시
- policy decision

### 변경 로그

- 워크플로우 수정
- 프롬프트 변경
- 모델 변경
- 데이터 소스 추가/삭제
- 정책 변경
- 권한 변경
- 배포 생성/이전 배포 활성화

### 승인 로그

- 승인 요청자
- 승인자
- 승인/반려 시각
- 승인 사유
- 관련 워크플로우/노드/데이터

## 감사 로그 필드 예시

```text
audit_logs
  id
  action
  actor_user_id
  effective_permission_snapshot
  source_team_ids
  organization_id
  project_id
  workflow_id
  node_id
  target_type
  target_id
  before_snapshot
  after_snapshot
  audit_metadata.policy_result
  ip_address
  user_agent
  created_at
```

## 로그 검색 UX

운영자는 로그를 다음 기준으로 볼 수 있어야 한다.

- 기간
- 사용자
- 프로젝트
- 워크플로우
- 노드
- 모델
- 데이터 등급
- 성공/실패
- 정책 위반
- 비용 범위
- 승인 여부

## RBAC 범위

메모에서는 노드 단위 권한까지 언급했지만, 우선순위상 최소 구현은 프로젝트/캔버스/데이터 소스 단위가 적절하다.

| 리소스 | 권한 | 우선순위 |
| --- | --- | --- |
| Project/App | read/write/manage | P0 |
| Workflow Canvas | read/write/execute/manage | P0 |
| Knowledge Base/Document | read/write/use/manage | P0 |
| DB Connection | secret/manage는 owner 또는 organization owner/manager, runtime use는 workflow/knowledge base 권한 | P0 |
| Deployment | deploy/activate/manage | P1 |
| LLM Credential/Model | credential use/manage와 credential-model relation | P1 |
| Node | read/write/execute | P2 |

## Team Template 예시

| Template | 설명 |
| --- | --- |
| Admin | 조직 정책, 사용자, 권한, 비용 한도 관리 |
| Builder | 워크플로우 생성/수정/테스트 |
| Operator | 배포, 실행 모니터링, 장애 대응 |
| Viewer | 로그와 실행 결과 조회 |
| Security Reviewer | 정책 위반, 데이터 리니지, 승인 처리 |

## 컴플라이언스 관점

원문 메모에는 GDPR이 audit 준비 맥락에서 직접 언급된다. HIPAA, ISMS는 `memo.md` 안의 ChatGPT 요약에서 확장된 해석으로 등장한다. 지금 단계에서 실제 인증이나 준수를 주장하기보다는, 규제 대응에 필요한 구조를 갖춘다고 표현하는 것이 안전하다.

| 규제/표준 | 제품에서 보여줄 수 있는 대응 요소 |
| --- | --- |
| GDPR | PII 탐지, 삭제/마스킹, 처리 이력, 접근 통제 |
| HIPAA | PHI 데이터 분류, 외부 전송 제한, 감사 로그. 요약 기반 확장 |
| ISMS-P | 접근 권한, 로그 보존, 정책 관리, 변경 이력. 요약 기반 확장 |
| SOC 2 | 보안 통제, 가용성, 변경 관리, 감사 가능성. 후속 검토 후보 |
| ISO 27001 | 정보보안 관리체계에 맞는 정책/로그 기반. 후속 검토 후보 |

원문에는 OIDC로 보이는 `oicd` 표현도 있지만, "복잡하니 role based로 가자"는 맥락이다. 현재 설계에서는 이를 DB role table이 아니라 organization/team 기반 RBAC와 team template으로 해석한다. 초기 구현은 외부 IdP 연동보다 자체 RBAC에 집중한다.

## 데모용 시나리오

1. HR 데이터 소스를 HR 그룹만 사용할 수 있게 설정한다.
2. 일반 사용자가 해당 데이터 소스를 포함한 워크플로우를 실행하면 차단된다.
3. 권한이 있는 사용자가 실행하면 성공한다.
4. 실행 로그에서 사용자, 데이터 소스, 모델, 비용, 정책 결과를 확인한다.
5. 프롬프트나 모델을 바꾸면 변경 로그가 남는다.
