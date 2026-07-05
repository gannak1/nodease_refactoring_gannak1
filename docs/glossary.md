# Glossary

Status: Draft

이 문서는 Nodease/Moduly 문서 전반에서 반복해서 쓰는 제품, 아키텍처, 데이터 모델 용어의 기준 정의다. 기능별 문서에서는 아래 용어를 재정의하지 않고 이 문서를 참조한다.

## Product Naming

| 용어 | 정의 |
| --- | --- |
| Nodease | 기존 Moduly 코드를 리팩토링해 만드는 신규 서비스명. 기업 내부 AI workflow/LLMOps 운영 플랫폼을 가리키는 제품 관점 명칭이다. |
| Moduly | 리팩토링의 출발점이 되는 기존 코드베이스와 현재 코드/배포 리소스에 남아 있는 명칭. 기존 코드, 컨테이너, Helm chart, README 실행 명령 등 인프라 식별자는 Moduly 기준으로 읽는다. |

## Organization And Permissions

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

## Workflow And Execution

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

## Agent And Generation

| 용어 | 정의 |
| --- | --- |
| Agent | 제품 문맥에서는 사용자의 자연어 요청을 받아 workflow 생성을 돕거나 특정 workflow/node 안에서 제한된 작업을 수행하는 AI 실행 주체를 뜻한다. 현재 문서 범위에서 전역 Q&A 에이전트나 독립 DB 엔티티로 확정된 용어는 아니다. |
| Agent Builder | 자연어 프롬프트로 실행 가능한 Workflow 초안을 생성하는 기능. 기존 node 단위 wizard와 구분되는 신규 목표 기능이다. |
| Agent Skill | 특정 provider 기능이 아니라 Nodease 내부에서 재사용할 수 있는 일반적인 절차/context/routing artifact 개념. Workflow 생성, LLM node의 RAG 옵션 구성, 검증 checklist를 안내할 수 있지만 권한을 부여하거나 source of truth가 되지는 않는다. 현재 Knowledge 설계의 구체 구현 단위는 `Knowledge Skill`이며, Agent Skill은 전역 Q&A 에이전트나 독립 실행 권한을 뜻하지 않는다. |
| Wizard | Prompt/code/template 같은 특정 node 설정을 개선하거나 생성하는 보조 기능. 현재 코드에는 node 단위 wizard가 존재한다. |

## Knowledge And RAG

| 용어 | 정의 |
| --- | --- |
| Knowledge | 사내 문서와 데이터 소스를 저장, 색인, 검색, 추적하는 제품 영역을 가리키는 상위 용어다. |
| Knowledge Source | Knowledge가 수집하는 외부 또는 내부 원천 시스템. 예: Drive, Wiki, ticketing tool, chat archive, API, DB, object storage. Source 자체는 Nodease 권한을 부여하지 않으며 connector와 source ACL 정책을 통해 안전하게 수집된다. |
| Source Item | Knowledge Source 안에서 document-level KB 1개로 materialize될 수 있는 원자 항목. 파일, 페이지, ticket, thread, DB row 또는 API record가 될 수 있다. |
| Knowledge Source Connector | Source item과 source ACL을 열거, 가져오기, 동기화하는 adapter 계층. Connector는 mbased permission을 직접 결정하지 않고 Outbound Egress Guard와 protocol adapter policy를 통과해야 한다. |
| Knowledge Base | 목표 KB 통합 모델에서 문서/source item 1개에 대응하는 permission, retrieval, sync, lifecycle atom. DB에서는 `knowledge_bases` table을 사용한다. 현재 구현에는 여러 문서를 포함하는 legacy 의미가 남아 있으며, MBA-105 target baseline은 [ADR-0014](decisions/ADR-0014-knowledge-base-document-atom-and-collection-boundary.md)와 [ADR-0017](decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)을 따른다. |
| Knowledge Collection | 여러 document-level Knowledge Base를 묶는 grouping, routing, UX, operations 단위. Collection 권한은 하위 KB content retrieval 권한을 자동 부여하지 않는다. |
| Knowledge Skill | Workflow Builder가 LLM node의 RAG 옵션을 구성할 때 어떤 source-of-truth tier를 먼저 볼지, 어떤 collection/KB 후보를 고려할지, 어떤 query template과 검증 절차를 쓸지 정의하는 Knowledge 도메인의 provider-neutral 절차 지식 artifact. Skill metadata/body/resource도 권한과 redaction-safe boundary 안에 있으며, 실제 근거는 KB/document version/citation에서 가져온다. |
| Skill Metadata | Skill 선택에 필요한 name, description, tag, owner, source tier, freshness 같은 요약 정보. 이 값 자체도 민감 metadata일 수 있어 organization/permission/display policy와 redaction/cap을 거친 safe field만 Workflow Builder, router, 실행 시점 RAG 경로에 제공한다. |
| Skill Freshness | Skill이 참조하는 source-of-truth version, 업무 절차, eval 결과가 아직 유효한지를 나타내는 상태. 예: `fresh`, `stale`, `review_required`, `deprecated`. |
| Skill Provenance | workflow draft, LLM node의 RAG 옵션, workflow test run, RAG strategy 비교가 어떤 skill id/version/freshness/eval 상태와 safe source reference를 사용했는지 남기는 redaction-safe summary. Raw skill body나 hidden source reference는 포함하지 않는다. |
| Source-of-Truth Tier | 정책 문서, ADR/decision record, semantic definition, curated query corpus처럼 근거로 삼을 source의 신뢰/우선순위 계층. Skill은 tier 선택 절차를 제공할 뿐 source of truth 자체가 아니다. Retrieval에서는 authorized evidence 안에서 ranking, tie-break, conflict resolution hint로만 사용한다. |
| Query Rewrite | 사용자의 자연어 query를 검색 친화적인 표현으로 바꾸는 LLM node의 선택적 RAG 기능. 접근 범위를 넓히거나 권한 판단을 수행하지 않으며, user query와 safe skill/template만 입력으로 사용한다. |
| Evidence Sufficiency Policy | 검색 결과만으로 답변할 수 있는지 판단하는 LLM node의 RAG 정책. 근거가 부족하면 LLM이 추측 답변을 만들지 않고 safe no-result 또는 insufficient-evidence 응답으로 닫게 한다. |
| Golden Question | Skill이나 retrieval strategy 회귀 검증에 쓰는 대표 질문/기대 근거 세트. 실제 raw restricted content가 아니라 safe fixture와 평가 기준으로 관리한다. |
| Collection Route Permission | Collection을 Agent/router 후보 scope로 사용할 수 있는 권한. Collection을 볼 수 있는 `collection.read`와 다르며, 하위 KB content retrieval 권한을 자동 부여하지 않는다. |
| Source Authorization Provenance | 외부 source ACL fact를 Nodease가 requester authorization과 freshness 판단에 사용할 수 있게 materialize한 safe provenance. KB `use` 권한 자체가 아니며 raw source principal/path/url을 user-facing surface에 노출하지 않는다. |
| Auto-ingested KB Use Provisioning | 자동 수집된 document-level KB가 retrieval 후보가 되도록 mbased KB `use` allow를 부여하는 절차. ADR-0017 baseline에서는 admin/team/user grant 또는 organization-approved connector/source policy가 `source_policy_kb_use_grants` row를 만들 때만 허용한다. Source ACL fact만으로는 KB `use`가 충족되지 않는다. |
| Document Version | document-level KB의 특정 색인/version artifact. 목표 모델에서는 active version만 기본 retrieval 대상이다. |
| Active Document Version | document-level KB에서 현재 retrieval-visible한 ready version. 새 version indexing/finalization이 성공하기 전까지 기존 active version을 비활성화하지 않는다. |
| Active Version Finalization | 새 document version의 redacted canonical text, chunks, embeddings, index artifact가 모두 준비된 뒤 active pointer와 processed state를 같은 finalization boundary에서 전환하는 단계. Crash recovery, fencing, outbox gate가 필요하다. |
| Document | 현재 구현의 Knowledge Base에 업로드되거나 연결된 원본 문서 메타데이터. 목표 모델에서는 `document_versions`로 전환된다. |
| Document Chunk | 검색과 citation을 위해 Document 또는 Document Version을 나눈 텍스트 조각. 목표 모델에서 chunk text, embedding input, retrieval-visible artifact는 redacted canonical text에서 생성된다. |
| RAG | Retrieval-Augmented Generation. 질문에 답하기 전에 Knowledge Base에서 관련 문서 조각을 검색해 LLM 응답에 활용하는 방식이다. |
| Retrieval | 질문 또는 query에 맞는 Document Chunk를 찾는 검색 과정이다. |
| Citation | 답변이 근거로 삼은 문서/청크 출처 정보. 사용자와 감사자가 답변 근거를 확인하는 데 사용한다. |
| Knowledge Permission Helper | KB permission, collection route scope, source ACL freshness/requester authorization을 service가 재사용할 수 있는 형태로 평가하는 helper. Router나 controller가 permission row 또는 raw source ACL을 직접 조합하지 않게 하는 경계다. |
| Safe Candidate Set | Permission helper와 source ACL gate를 통과해 router, Workflow Builder, 실행 시점 RAG 경로에 제공할 수 있는 KB/collection/skill 후보와 safe metadata의 집합. 권한 없는 resource id, raw source path/url/title, raw ACL fact, exact denied count를 포함하지 않는다. |
| Collection Router | Safe Candidate Set 안에서 질문에 적합한 collection/KB 후보를 선택하는 routing component. Access control을 수행하지 않고, 이미 필터링된 safe metadata만 소비한다. |
| Auto Collection Mode | 요청자가 explicit KB id를 직접 고르지 않고, route-allowed collection scope와 KB permission helper 결과로 safe candidate set을 만든 뒤 router가 후보 KB를 선택하는 목표 retrieval mode. |
| Explicit KB Mode | 요청자가 특정 KB를 명시하는 mode. Collection route permission을 생략할 수 있지만 KB visibility, KB permission helper, source ACL gate, final evidence policy는 생략할 수 없다. |
| Final Evidence Policy | LLM prompt, answer delta, citation preview, trace/audit summary에 evidence가 들어가기 전에 적용하는 최종 정책 gate. PII/secret, classification, source ACL, permission 상태를 안전하게 검증한다. |
| Partial Result | 일부 authorized KB retrieval이 operational failure를 겪었지만 남은 evidence가 모두 permission/source ACL/final policy gate를 통과한 경우 반환할 수 있는 제한적 결과. 실패 후보는 safe/bucketed summary로만 표시한다. |
| Source ACL | 외부 source system의 문서/source item 접근 제어 정보. source-managed KB에서는 mbased KB `use`와 별개의 필수 gate이며, stale/unmapped/ambiguous/unverified/revoked 상태는 fail-closed다. |
| Source ACL Fact | Source system에서 가져온 ACL 원천 사실. Raw principal, raw path, raw title, raw permission 값은 user-facing UI, router, audit/trace summary에 직접 노출하지 않는다. |
| Source ACL Freshness | Source ACL이 최신이고 requester authorization에 사용할 수 있는지 나타내는 상태. 예: `fresh`, `stale`, `unmapped`, `ambiguous`, `unverified`, `revoked`. Fresh가 아니면 source-managed KB retrieval은 fail-closed다. |
| Source ACL Provenance | Source Authorization Provenance의 alias. 새 문서와 table/field 이름은 Source Authorization Provenance를 우선 사용한다. |
| Requester Authorization | 현재 요청 actor가 source-managed KB의 원천 source에서도 접근 가능한지 확인하는 source ACL 기반 gate. 판정 결과는 `allowed`, `denied`, `unknown`, `not_applicable` 같은 값으로 표현하며, source ACL freshness/mapping 상태와 분리한다. Organization manager나 manual KB grant가 기본적으로 이 gate를 우회하지 않는다. |
| Source-Managed KB | 외부 connector/source sync가 생성·관리하는 document-level KB. 수동 grant만으로 source ACL freshness/requester authorization을 우회하지 않는다. |
| Source Identity | Source item을 재동기화, tombstone matching, provenance 연결에 사용할 수 있게 식별하는 protected reference. Raw source id/url/path/title과 구분한다. |
| Protected Source Identity | 사용자-facing resource가 아닌 source identity 저장 경계. HMAC/hash ref, key version, rotation/backfill, tombstone matching 정책을 갖고 raw source id/url/path/title 노출을 막는다. |
| Safe Source Reference | raw source id/url/path/title 대신 citation, audit, UI에 제한적으로 사용할 수 있는 opaque/HMAC 기반 source reference. ADR-0017 provisional baseline은 protected source identity와 keyed HMAC reference를 사용하며, 구체 format과 key rotation/backfill column은 해당 migration/API 문서에서 고정한다. |
| Resource-Hidden Response | scope 밖, hidden, requester source authorization denied, source ACL stale 등 존재 추론 위험이 있는 경우의 안전한 응답 shape. Knowledge 목표 구조의 provisional matrix는 ADR-0017과 Knowledge implementation baseline을 따르며, 최종 HTTP/SSE shape와 audit 여부는 구현 PR의 API/test 계약에서 고정한다. |
| Redacted Canonical Text | source item에서 추출한 뒤 redaction/sanitization을 거친 canonical text. 목표 모델에서 chunk content, embedding input, retrieval-visible text의 기본 원천이다. |
| Canonical Metadata Source | Target cutover 후 metadata filter, citation summary, audit/trace summary에 사용할 authoritative metadata 위치. ADR-0017 provisional baseline은 document version 또는 canonical metadata table 쪽을 기준으로 두며, `documents.meta_info` 이후의 최종 table/column은 구현 PR의 migration과 API/schema 문서에서 고정한다. |
| Privacy Redaction Policy | PII/secret detector, masking/hash/drop/block rule, output-target별 redaction을 정의하는 공통 정책. Platform hard baseline은 관리자가 약화할 수 없고, organization/collection/source/KB 정책은 더 엄격한 방향으로만 조정한다. |
| Display Policy | Source-derived name, title, path, URL, description 같은 metadata를 UI에 표시해도 되는지 결정하는 redaction, length cap, allowlist, role/audience 정책. 표시 가능성과 durable audit/trace 저장 가능성은 별개다. |
| Raw Knowledge Artifact | RAG/embedding/prompt에는 사용하지 않는 protected raw source content 저장 단위. Organization/source opt-in, 암호화, retention/legal hold/purge, raw/compliance permission, fresh source ACL, access audit이 필요하다. |
| Raw/Compliance Access | Raw Knowledge Artifact를 조회하는 별도 권한/flow. Agent answer, SSE stream, retrieval context와 분리되며 raw access audit이 선행돼야 한다. |
| Capped Preview | 사용자에게 출처 이해를 돕기 위해 제공하는 redacted and length-limited 미리보기 텍스트. Durable audit/trace/usage summary나 embedding input으로 복사하지 않는다. |
| Metadata Filter | 문서 metadata의 allowlist된 필드로 검색 범위를 좁히는 필터. 권한의 source가 아니며 RBAC/source ACL 판정을 대체하지 않는다. |
| Classification | 문서 민감도 분류 metadata convention. 전용 column이 아니라 `documents.meta_info.classification`을 사용한다. |
| Ingestion Lock | 같은 source item 또는 document-level KB에 대한 동시 ingestion/finalization을 막는 lock. Owner token, TTL renew, fencing token 또는 DB advisory lock 같은 방어가 필요하다. |
| Fencing Token | 오래된 worker가 lock 만료 뒤 새 worker의 artifact를 finalize하거나 삭제하지 못하게 하는 단조 증가 또는 소유권 확인 token. |
| Knowledge Ingestion Outbox | DB state와 object storage, vector index, external artifact cleanup/finalization side effect를 조정하는 retry 가능한 outbox. DB commit 전 physical delete나 external side effect가 먼저 확정되는 것을 피한다. |
| Recovery Scanner | outbox, staging version, orphan artifact, failed cleanup 같은 불완전 상태를 찾아 idempotent하게 재시도하거나 dead-letter 처리하는 운영 worker. |
| Tombstone | Source item이 원천 source에서 삭제되었거나 더 이상 열거되지 않는 상태를 나타내는 marker. 기본적으로 citation/audit history를 즉시 삭제한다는 뜻은 아니다. |
| Sync Run | Connector가 source item/content/ACL을 동기화하는 실행 1회. Lease, cursor, retry/backoff, dead-letter 상태를 가져야 한다. |
| Dead Letter | 재시도 한도를 넘었거나 자동 복구가 위험한 sync/outbox 작업을 운영자 remediation 대상으로 격리한 상태. |
| RAG Answer Run | standalone RAG Agent answer 실행 기록. DB에서는 `rag_answer_runs` table을 사용한다. trace/usage table과는 FK가 아니라 `correlation_id`로 느슨하게 연결한다. |

## LLM And Cost

| 용어 | 정의 |
| --- | --- |
| LLM Provider | OpenAI, Anthropic, Google 같은 외부 LLM 제공자. 호출은 `apps/shared/services/llm_client`의 자체 client 계층을 통해 수행한다. |
| LLM Model | Provider가 제공하는 구체 모델. DB에서는 `llm_models` table을 사용한다. |
| LLM Credential | Provider API 호출에 필요한 자격 정보. 사용자가 소유하고(`user_id`) organization scope에 속할 수 있다(`organization_id` nullable). DB에서는 `llm_credentials` table을 사용한다. secret 원문은 응답, 로그, trace에 노출하지 않는다. |
| Credential-Model Relation | 특정 credential로 어떤 model을 사용할 수 있는지 나타내는 연결. DB에서는 `llm_rel_credential_models` table을 사용한다. |
| LLM Usage Log | LLM 호출의 token, latency, cost 등 사용량 기록. DB에서는 `llm_usage_logs` table을 사용한다. |
| Cost Optimizer | Workflow의 현재 모델과 후보 모델을 비교 실행해 비용 절감률과 품질 차이를 제시하는 기능이다. |
| Model Compare | 기존 compare API를 사용해 같은 workflow를 다른 model 조건으로 실행하고 결과와 비용을 비교하는 흐름이다. |

## Audit And Trace

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

## Operations And Integrations

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
