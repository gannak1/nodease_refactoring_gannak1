# Glossary

Status: Draft

이 문서는 Nodease/Moduly 문서 전반에서 반복해서 쓰는 제품, 아키텍처, 데이터 모델 용어의 기준 정의다. 기능별 문서에서는 아래 용어를 재정의하지 않고 이 문서를 참조한다.

## 제품 명칭

| 용어 | 정의 |
| --- | --- |
| Nodease | 기존 Moduly 코드를 리팩토링해 만드는 신규 서비스명. 기업 내부 AI workflow/LLMOps 운영 플랫폼을 가리키는 제품 관점 명칭이다. |
| Moduly | 리팩토링의 출발점이 되는 기존 코드베이스와 현재 코드/배포 리소스에 남아 있는 명칭. 기존 코드, 컨테이너, Helm chart, README 실행 명령 등 인프라 식별자는 Moduly 기준으로 읽는다. |

## 조직과 권한

| 용어 | 정의 |
| --- | --- |
| Organization | 조직 범위와 tenant-like boundary. DB에서는 단수형 `organization` table을 사용한다. 리소스 접근 scope의 최상위 기준이다. |
| Active Organization | 요청자가 현재 작업 대상으로 선택한 organization. API 요청에서는 `X-Organization-Id` header로 전달한다. |
| Organization Scope | 리소스가 속한 organization 경계. scope 밖 리소스는 존재 여부를 숨기기 위해 `404`로 응답한다. |
| OrganizationMembership | User가 Organization에 직접 소속되어 있음을 나타내는 1차 관계. `organization_memberships` table이 기준이다. |
| Team | Organization 안의 권한 부여 단위. DB에서는 `teams` table을 사용한다. |
| TeamMembership | User가 Organization 안의 Team에 배정되어 있다는 관계. Team permission 계산의 전제이며, organization 소속 자체의 기준은 아니다. |
| RBAC | Role-Based Access Control. Nodease에서는 고정 role table 대신 organization membership, team permission, user direct permission, `auth_state`로 판정한다. |
| auth_state | DB enum이 아닌 application-level permission state string. 운영 권한은 `none`, `viewer`, `operator`, `builder`, `manager`, 감사 권한은 `auditor`, `raw_auditor`를 사용한다. |
| Team Permission | Team 단위 resource 권한. `team_workflow_permissions`, `team_knowledge_permissions`, `team_llm_permissions`, `team_audit_permissions`를 사용한다. |
| User Direct Permission | Team 권한으로 처리하기 어려운 user별 additive allow 예외 권한. 현재 코드 기준 workflow와 LLM credential에 대해 구현돼 있다. |
| Resource | 권한 판정 대상이 되는 업무 객체. 대표적으로 Workflow, Knowledge Base, LLM Credential, Audit 대상 organization이 있다. |
| Explicit Deny | 명시적 거부 권한. 현재 권한 모델에는 도입하지 않는다. 권한 판정은 허용 권한 중 가장 강한 값을 선택하는 방식이다. |

## Workflow와 실행

| 용어 | 정의 |
| --- | --- |
| App | 제품상 project boundary. DB에서는 기존 `apps` table을 사용한다. 하나의 App은 workflow와 deployment의 상위 단위로 취급된다. |
| Workflow | 사용자가 캔버스에서 구성하는 자동화 흐름. DB에서는 `workflows` table을 사용한다. |
| Canvas | Workflow를 편집하는 화면/표면을 가리키는 제품 용어. 별도 데이터 엔티티가 아니라 Workflow editing surface다. |
| Node | Workflow 안의 실행 단위. LLM, Condition, HTTP, Email, Code, Webhook 등 구체 노드 타입으로 동작한다. |
| Workflow Run | Workflow 실행 1회를 나타내는 실행 기록. DB에서는 `workflow_runs` table을 사용한다. |
| Workflow Node Run | Workflow Run 안에서 개별 node가 실행된 기록. DB에서는 `workflow_node_runs` table을 사용한다. |
| Deployment | Workflow를 외부 실행 가능한 형태로 공개/활성화한 결과. DB에서는 `workflow_deployments` table을 사용한다. |
| Schedule | Deployment 실행을 정해진 시간/주기로 트리거하는 설정. DB에서는 `schedules` table을 사용하며 deployment와 1:1 관계다. |
| Webhook | 외부 시스템이 HTTP 요청으로 Workflow를 실행하게 하는 인바운드 트리거. |
| Public Run API | 배포된 workflow를 app secret 기반 Bearer 인증으로 실행하는 public endpoint 계열. 일반 사용자 세션 인증과 구분한다. |

## Agent와 자동 생성

| 용어 | 정의 |
| --- | --- |
| Agent | 제품 문맥에서는 사용자의 자연어 요청을 받아 답변하거나 workflow 생성을 돕는 AI 실행 주체를 뜻한다. 현재 문서 범위에서 독립 DB 엔티티로 확정된 용어는 아니다. |
| Agent Builder | 자연어 프롬프트로 실행 가능한 Workflow 초안을 생성하는 기능. 기존 node 단위 wizard와 구분되는 신규 목표 기능이다. |
| Wizard | Prompt/code/template 같은 특정 node 설정을 개선하거나 생성하는 보조 기능. 현재 코드에는 node 단위 wizard가 존재한다. |

## Knowledge와 RAG

| 용어 | 정의 |
| --- | --- |
| Knowledge | 사내 문서와 데이터 소스를 저장, 색인, 검색, 추적하는 제품 영역을 가리키는 상위 용어다. |
| Knowledge Base | 목표 KB 통합 모델에서 문서/source item 1개에 대응하는 permission, retrieval, sync, lifecycle atom. DB에서는 `knowledge_bases` table을 사용한다. 현재 구현에는 여러 문서를 포함하는 legacy 의미가 남아 있으며, target cutover는 [ADR-0014](decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)의 gate를 따른다. |
| Knowledge Collection | 여러 document-level Knowledge Base를 묶는 grouping, routing, UX, operations 단위. Collection 권한은 하위 KB content retrieval 권한을 자동 부여하지 않는다. |
| Collection Route Permission | Collection을 Agent/router 후보 scope로 사용할 수 있는 권한. Collection을 볼 수 있는 `collection.read`와 다르며, 하위 KB content retrieval 권한을 자동 부여하지 않는다. |
| Document Version | document-level KB의 특정 색인/version artifact. 목표 모델에서는 active version만 기본 retrieval 대상이다. |
| Document | 현재 구현의 Knowledge Base에 업로드되거나 연결된 원본 문서 메타데이터. 목표 모델에서는 `document_versions`로 전환된다. |
| Document Chunk | 검색과 citation을 위해 Document 또는 Document Version을 나눈 텍스트 조각. 목표 모델에서 chunk text, embedding input, retrieval-visible artifact는 redacted canonical text에서 생성된다. |
| RAG | Retrieval-Augmented Generation. 질문에 답하기 전에 Knowledge Base에서 관련 문서 조각을 검색해 LLM 응답에 활용하는 방식이다. |
| Retrieval | 질문 또는 query에 맞는 Document Chunk를 찾는 검색 과정이다. |
| Citation | 답변이 근거로 삼은 문서/청크 출처 정보. 사용자와 감사자가 답변 근거를 확인하는 데 사용한다. |
| Source ACL | 외부 source system의 문서/source item 접근 제어 정보. source-managed KB에서는 mbased KB `use`와 별개의 필수 gate이며, stale/unmapped/ambiguous/unverified 상태는 fail-closed다. |
| Source ACL Provenance | Source ACL fact를 permission helper가 소비할 수 있게 materialize한 안전한 증거/상태. KB `use` permission 자체가 아니며 raw source permission 값을 직접 노출하지 않는다. |
| Source-Managed KB | 외부 connector/source sync가 생성·관리하는 document-level KB. 수동 grant만으로 source ACL freshness/requester authorization을 우회하지 않는다. |
| Safe Source Reference | raw source id/url/path/title 대신 citation, audit, UI에 제한적으로 사용할 수 있는 opaque/HMAC 기반 source reference. 구체 format은 protected source identity gate에서 확정한다. |
| Resource-Hidden Response | scope 밖, hidden, source ACL denied/stale 등 존재 추론 위험이 있는 경우의 안전한 응답 shape. HTTP/SSE shape와 audit 여부는 resource hiding API matrix gate에서 확정한다. |
| Redacted Canonical Text | source item에서 추출한 뒤 redaction/sanitization을 거친 canonical text. 목표 모델에서 chunk content, embedding input, retrieval-visible text의 기본 원천이다. |
| Privacy Redaction Policy | PII/secret detector, masking/hash/drop/block rule, output-target별 redaction을 정의하는 공통 정책. Platform hard baseline은 관리자가 약화할 수 없고, organization/collection/source/KB 정책은 더 엄격한 방향으로만 조정한다. |
| Raw Knowledge Artifact | RAG/embedding/prompt에는 사용하지 않는 protected raw source content 저장 단위. Organization/source opt-in, 암호화, retention/legal hold/purge, raw/compliance permission, fresh source ACL, access audit이 필요하다. |
| Raw/Compliance Access | Raw Knowledge Artifact를 조회하는 별도 권한/flow. Agent answer, SSE stream, retrieval context와 분리되며 raw access audit이 선행돼야 한다. |
| Capped Preview | 사용자에게 출처 이해를 돕기 위해 제공하는 redacted and length-limited 미리보기 텍스트. Durable audit/trace/usage summary나 embedding input으로 복사하지 않는다. |
| Metadata Filter | 문서 metadata의 allowlist된 필드로 검색 범위를 좁히는 필터. 권한의 source가 아니며 RBAC/source ACL 판정을 대체하지 않는다. |
| Classification | 문서 민감도 분류 metadata convention. 전용 column이 아니라 `documents.meta_info.classification`을 사용한다. |
| RAG Answer Run | standalone RAG Agent answer 실행 기록. DB에서는 `rag_answer_runs` table을 사용한다. trace/usage table과는 FK가 아니라 `correlation_id`로 느슨하게 연결한다. |

## LLM과 비용

| 용어 | 정의 |
| --- | --- |
| LLM Provider | OpenAI, Anthropic, Google 같은 외부 LLM 제공자. 호출은 `apps/shared/services/llm_client`의 자체 client 계층을 통해 수행한다. |
| LLM Model | Provider가 제공하는 구체 모델. DB에서는 `llm_models` table을 사용한다. |
| LLM Credential | Provider API 호출에 필요한 자격 정보. 사용자가 소유하고(`user_id`) organization scope에 속할 수 있다(`organization_id` nullable). DB에서는 `llm_credentials` table을 사용한다. secret 원문은 응답, 로그, trace에 노출하지 않는다. |
| Credential-Model Relation | 특정 credential로 어떤 model을 사용할 수 있는지 나타내는 연결. DB에서는 `llm_rel_credential_models` table을 사용한다. |
| LLM Usage Log | LLM 호출의 token, latency, cost 등 사용량 기록. DB에서는 `llm_usage_logs` table을 사용한다. |
| Cost Optimizer | Workflow의 현재 모델과 후보 모델을 비교 실행해 비용 절감률과 품질 차이를 제시하는 기능이다. |
| Model Compare | 기존 compare API를 사용해 같은 workflow를 다른 model 조건으로 실행하고 결과와 비용을 비교하는 흐름이다. |

## Audit와 Trace

| 용어 | 정의 |
| --- | --- |
| Audit | 사용자의 주요 action과 data change를 추적 가능한 기록으로 남기는 것. canonical 저장소는 `audit_logs` table이다. |
| Audit Log | actor, action, 대상 resource, status, metadata를 포함하는 감사 기록. |
| Canonical Action | audit log에 저장하는 표준 action 문자열. 예: `workflow.deploy`, `permission.denied`. |
| Trace | Workflow/RAG 실행 중 생긴 입력, 출력, 중간 결과, payload 접근 이력을 추적하는 실행 관측 데이터다. |
| Trace Payload | 실행 payload를 raw/redacted 정책에 맞춰 저장하는 기록. DB에서는 `trace_payloads` table을 사용한다. |
| Raw Payload | 마스킹 전 원본 payload. 접근은 최소화하고 조회 시 `trace_payload_access_events` 기록이 선행돼야 한다. |
| Redacted Payload | secret, credential, raw content 등 민감 값을 제거하거나 마스킹한 payload. 일반 조회는 redacted 기준을 우선한다. |
| Trace Payload Access Event | raw payload 등 민감 trace 접근을 별도로 기록하는 감사 이벤트. DB에서는 `trace_payload_access_events` table을 사용한다. |
| Policy Result | 정책 평가 결과. `pass`, `warn`, `block` 같은 값을 `audit_logs.audit_metadata.policy_result`에 저장한다. |
| Correlation ID | FK가 아닌 application-level 연결 식별자. standalone RAG answer와 trace/usage/audit을 느슨하게 연결하는 데 사용하며 권한 판정 기준으로 쓰지 않는다. |

## 운영과 외부 연동

| 용어 | 정의 |
| --- | --- |
| Admin Dashboard | 플랫폼 관리자와 감사자가 audit log, LLM usage/cost, 비정상 접근 시도, 사용자 비활성화 상태를 확인하는 운영 화면이다. |
| Gateway | `apps/gateway/` FastAPI 서비스. 인증된 API 진입점과 resource permission enforcement 경계다. |
| Workflow Engine | `apps/workflow_engine/` Celery worker. Workflow 실행과 node runtime을 담당한다. |
| Log System | `apps/log_system/` Celery worker. audit/trace/log 계열 비동기 처리를 담당한다. |
| Sandbox | `apps/sandbox/` NSJail 기반 격리 코드 실행 서비스. |
| Shared | `apps/shared/` 공통 패키지. DB model, schema, permission service, llm_client, tracing/audit utility를 포함한다. |
| Connection | 외부 DB나 외부 데이터 소스 연결 정보. DB에서는 `connections` table을 사용한다. 저장된 secret은 server-side에서만 사용하고 노출하지 않는다. |
| Outbound Egress Guard | Knowledge/RAG source-collection server-side outbound network dial 전 host/IP/port/proxy/timeout/size 정책을 검증하는 중앙 경계. HTTP URL fetch뿐 아니라 DB, SSH, SaaS, object storage connector도 대상이지만, workflow runtime outbound 전체는 별도 ADR 전에는 이 보호가 보장됐다고 해석하지 않는다. |
| Secret | API key, token, credential 원문, `encrypted_config`, `encrypted_password` 등 민감 값. 응답, 로그, trace, 문서, 테스트 fixture에 노출하지 않는다. |
