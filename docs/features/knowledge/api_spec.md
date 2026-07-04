# Knowledge API Spec

Status: Draft
이 문서는 Knowledge feature의 현재 API baseline과 목표 KB 통합 API 계약을 함께 기록한다. MBA-105 목표 API는 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 임시 구현 baseline과 [implementation_baseline.md](implementation_baseline.md)를 따른다. Knowledge Skill 관련 API 경계는 [ADR-0015](../../decisions/ADR-0015-knowledge-skill-context-routing-boundary.md)를 따른다.

## Current Baseline Endpoints

| Method | Path | 목적 | 권한 경계 |
| --- | --- | --- | --- |
| GET | `/api/v1/knowledge` | 현재 KB 목록 | 현재 구현 기준 owner/permission filtering |
| POST | `/api/v1/rag/upload` | KB 문서 업로드/색인 요청 | KB write/manage path, current behavior |
| POST | `/api/v1/rag/search-test/pure` | 검색 테스트 | active organization, KB use |
| POST | `/api/v1/rag/search-test/chat` | 검색+답변 테스트 | active organization, KB use, LLM credential |
| POST | `/api/v1/rag/agent/answer` | 명시 `knowledge_base_id` 기반 standalone Agent answer | KB use, generation model/credential use |
| POST | `/api/v1/rag/agent/answer/stream` | standalone Agent answer SSE | KB use, generation model/credential use |

그 외 `/api/v1/knowledge/*` KB/list/detail/document/process/sync surface, `/api/v1/rag/upload/presigned-url`, `/api/v1/rag/document/*`, `/api/v1/rag/proxy/preview` 계열은 현재 동작 경로로 읽는다. 특정 endpoint가 helper 기반 KB permission enforcement를 명시하지 않는 한, 현재 `/api/v1/knowledge/*` endpoint는 owner/current-behavior filtered surface다. Document content/download/preview surface는 현재 raw 또는 source-derived content를 노출할 수 있으므로, KB 통합 cutover 전 target raw/compliance access 또는 redacted-preview policy로 재분류해야 한다. URL/proxy preview surface는 목표 `OutboundEgressGuard` 정렬 대상이며, 구현이 갱신되기 전에는 target egress 계약을 만족한다고 보지 않는다.

## Target Endpoint Groups

| 그룹 | 목표 path | 목적 |
| --- | --- | --- |
| Collections | `/api/v1/knowledge/collections`, `/api/v1/knowledge/collections/{collection_id}` | Collection 목록, safe metadata, route/manage/sync operation |
| Collection items | `/api/v1/knowledge/collections/{collection_id}/items` | Document-level KB link/unlink. KB content permission을 부여하지 않음 |
| Document-level KBs | `/api/v1/knowledge/kbs/{kb_id}` | KB detail, active version, sync state, remediation summary |
| Document versions | `/api/v1/knowledge/kbs/{kb_id}/versions/*` | Version history, active version, re-index state |
| Raw/compliance view | `/api/v1/knowledge/kbs/{kb_id}/raw-artifacts/*` | Raw/compliance gate 이후 선택적 protected raw content access. RAG answer API에서 사용하지 않음 |
| Source connectors | `/api/v1/knowledge/sources/*` | Source connection, sync, tombstone, ACL status, remediation |
| Knowledge skills | `/api/v1/knowledge/skills/*` | Provider-neutral skill registry, version, freshness/eval status, safe metadata. 주 사용처는 빌더 단계 LLM node의 RAG 옵션 구성 |
| 실행 시점 RAG retrieval | 내부 service call | Workflow LLM node의 RAG 옵션 실행 시 collection-routed 또는 KB-candidate-routed retrieval. MBA-105 초기 구현은 Gateway 공개 HTTP endpoint를 추가하지 않고 Workflow/Gateway 내부 service boundary로 연결한다 |

공개 HTTP path가 필요한 경우에는 별도 API gate review에서 path 이름과 JSON/SSE shape를 확정한다. MBA-105의 필수 계약은 collection listing(`collection.read`), collection routing(`collection.route`), KB content permission, source ACL state, document version citation identity의 분리다. Skill authoring, test, submit-for-review, publish/deprecate, Workflow Playground skill binding API는 아직 승인된 계약이 아니다.

Builder와 deployment preflight가 사용할 MBA-105 내부 candidate resolver contract는 공개 HTTP endpoint가 아니어도 다음 shape를 지켜야 한다.

| 필드 | 규칙 |
| --- | --- |
| `actor` | Builder 또는 deployer subject. Candidate metadata 표시 권한의 기준 |
| `intended_execution_subject` / `audience` | Runtime availability 계산 기준. 없으면 availability를 `unknown` 또는 `unavailable`로 낮춘다 |
| `mode` | `auto_collection` 또는 `explicit_kb` |
| `collection_ids` | Auto collection mode에서 route scope 후보. 누락 시 actor가 route할 수 있는 safe subset만 사용 |
| `knowledge_base_ids` | Explicit KB mode 후보. Collection route는 생략할 수 있지만 KB visibility/use/source ACL/final evidence preflight는 수행 |
| `purpose` | `builder_suggestion`, `deployment_preflight`, `runtime_preview` 같은 bounded enum |

Response는 safe candidate list와 summary만 포함한다. 각 candidate는 `candidate_id`, `candidate_type`, safe label, route availability, runtime availability(`available`, `warning`, `unavailable`, `unknown`), safe reason code, required action을 반환할 수 있다. Hidden KB id/name, exact denied count, raw source path/title/url, hidden source distribution은 반환하지 않는다.

## Request Model

### Explicit KB Answer

Explicit KB mode는 알려진 `knowledge_base_id`를 입력받는다. 이 직접 모드에서는 collection route permission을 요구하지 않을 수 있지만, KB helper, source ACL/requester authorization, metadata filter, hierarchy mode, final evidence policy는 항상 적용한다.

MBA-105 standalone `/api/v1/rag/agent/answer`와 `/api/v1/rag/agent/answer/stream`은 `evidence_sufficiency_policy`를 `minimum_evidence` 기본값으로 평가한다. Evidence가 없으면 LLM을 호출하지 않고 safe no-result로 닫으며, evidence score 또는 strict citation 기준이 부족하면 safe insufficient-evidence 응답으로 닫는다. 이 응답은 hidden KB id/name, 권한 없는 문서명, exact denied count를 포함하지 않는다.

필수 목표 field:

| 필드 | 규칙 |
| --- | --- |
| `knowledge_base_id` | 필수. Active organization scope 안에서만 평가하고, scope 밖이거나 사용할 수 없으면 resource-hiding matrix를 따른다 |
| `generation_model_id` / `credential_id` | 필수. Preset/default credential selection은 별도 ADR이 승인되기 전까지 허용하지 않는다 |
| `query` | 필수. Raw query는 기본적으로 durable 저장하지 않는다 |
| `metadata_filter` | Permission/source ACL gate 이후 허용된 candidate 안에서만 적용 |
| `hierarchy_mode` | 현재 metadata-aware/hierarchical RAG 계약을 따른다 |
| `query_rewrite_mode` | 선택 목표 옵션. 기본값 `off`; deterministic/template rewrite는 opt-in. Rewrite는 접근 범위를 넓히지 않는다 |
| `evidence_sufficiency_policy` | MBA-105 standalone Agent answer에서 기본값 `minimum_evidence`로 적용한다. `strict_citation`은 더 엄격한 citation 개수 검증 후보이며, `off`는 운영 runtime에서 허용하지 않는다 |
| `source_tier_policy` | 선택 목표 옵션. Source-of-Truth Tier를 authorized evidence 안에서 ranking/tie-break/conflict hint로만 사용한다 |

### Auto Collection Answer

Auto mode는 arbitrary KB id를 permission bypass로 받지 않는다. 먼저 safe candidate set을 구성한다.

| 필드 | 규칙 |
| --- | --- |
| `collection_ids` | 선택. 있으면 먼저 collection `route` 권한을 확인한다 |
| `skill_ids` | 빌더 단계 선택 후보. 있으면 skill visibility, freshness/eval, display policy를 확인한다. Skill만으로 KB permission/source ACL gate를 충족할 수 없다 |
| `generation_model_id` / `credential_id` | 필수. Auto mode는 preset/default credential selection을 의미하지 않는다 |
| `max_collections` / `max_candidate_kbs` / `max_retrieval_kbs` | 서버가 강제하는 cap. 초기 baseline은 `max_route_collections=20`, `max_candidate_kbs=5000`, `max_retrieval_kbs=20`, `max_chunks_per_kb=8`, `max_total_chunks=50`이며 운영 설정으로 조정 가능하다. 제품의 영구 고정 계약이 아니다 |
| `metadata_filter` | Permission/source ACL candidate filtering 이후 적용 |
| `query_rewrite_mode` | 선택 목표 옵션. 기본값 `off`; rewrite는 접근 범위를 넓히지 않고 raw rewritten query는 durable metadata에 저장하지 않는다 |
| `evidence_sufficiency_policy` | 선택 목표 옵션. 기본값 `minimum_evidence`; 근거 부족 시 safe no-result 또는 insufficient-evidence 응답 |
| `source_tier_policy` | 선택 목표 옵션. 공통 LLM node의 RAG 옵션이며 ADR-0017의 source tier baseline을 따른다 |
| `query` | Candidate routing과 retrieval에 사용한다. Permission decision에는 사용하지 않는다 |

Router는 authorized safe candidate와 safe metadata만 받는다. Raw source ACL fact, hidden KB id, raw source title/path/url, exact hidden count, raw content는 router input에 포함하지 않는다. `collection_ids`가 없을 때 candidate source는 조직 전체 collection이 아니라 서버 정책상 actor가 route할 수 있는 collection subset이다.

Router candidate metadata는 safe identifier와 coarse summary로 제한한다. 예시는 `knowledge_base_id`, optional `collection_id`, safe redacted display label, coarse source type, safe classification/category/tag, coarse sync/source ACL state, request-scoped ranking hint다. Raw source id/url/path/title, raw principal, raw ACL row, exact hidden/denied count, credential value, prompt/completion, raw content는 router input이 아니다.

Skill candidate metadata도 같은 boundary를 따른다. Workflow Builder가 받을 수 있는 skill field는 safe skill id, skill version, safe display label, source-of-truth tier, freshness state, eval status, validation checklist id, redaction-safe routing hint 정도로 제한한다. Raw skill body, hidden source reference, raw source title/path/url, restricted document list, raw content, prompt/completion, provider raw response는 Builder input이 아니다.

### Workflow Runtime RAG Execution Subject

Workflow runtime에서 RAG를 호출하는 API나 내부 service call은 `execution_subject`를 명시해야 한다. `execution_subject`는 interactive user, workflow runner, 승인된 service account, 업무상 지정된 operator처럼 권한 평가에 사용할 주체다.

필수 계약:

| 항목 | 규칙 |
| --- | --- |
| `execution_subject` | Workflow run context에서 명시적으로 resolve한 actor/service account. KB permission과 source ACL 평가 기준 |
| `subject_resolution_reason` | interactive run, deployment service account, assigned operator 등 sanitized reason |
| `workflow_owner_id` | 감사/소유권 표시에는 사용할 수 있지만, 명시 설정 없이 retrieval 권한 fallback으로 사용하지 않는다 |
| missing/ambiguous subject | retrieval preflight 실패. Silent owner fallback 금지 |

모든 운영 RAG mode는 `execution_subject` 기준의 KB permission/source ACL/final evidence gate를 통과해야 한다. `general RAG`는 authorized resource 안에서 넓게 검색하는 mode이고, `task-aware` 또는 `permission-scoped RAG`는 authorized resource 안에서 후보를 더 정밀하게 줄이는 mode다.

### LLM node RAG 품질 옵션

Workflow Builder가 LLM node의 RAG 옵션을 구성할 때 다음 목표 옵션을 제안할 수 있다. 이 옵션은 전역 에이전트 기능이나 독립형 RAG 실행 노드 기능이 아니라 생성된 LLM node의 retrieval/generation 정책이다.

| 필드 | 의미 |
| --- | --- |
| `query_rewrite_mode` | `off`, `template`, `llm_assisted` 후보. Rewrite는 user query와 safe skill/template만 입력으로 사용하고, permission/source ACL candidate scope를 넓히지 않는다 |
| `evidence_sufficiency_policy` | `minimum_evidence`, `strict_citation` 후보. 운영 runtime에서는 `off`를 허용하지 않는다. 근거가 부족하면 safe no-result 또는 insufficient-evidence 응답으로 닫는다 |
| `source_tier_policy` | Source-of-Truth Tier를 authorized evidence 안에서 ranking, tie-break, conflict resolution hint로 사용할지 나타내는 목표 옵션. Baseline candidate enum은 `legal_regulation`, `contract`, `company_policy`, `adr_decision`, `official_documentation`, `semantic_definition`, `operational_runbook`, `curated_query_corpus`, `conversation_or_thread`이며 최종 enum은 Legal/Compliance review에서 확정한다 |

`query_rewrite_mode`가 켜져도 raw rewritten query는 raw prompt와 유사한 민감 입력으로 취급한다. Durable audit/trace/usage metadata에는 rewrite 적용 여부, 전략, safe template id 같은 summary만 저장한다.

`llm_assisted` query rewrite는 LLM 호출이므로 별도 승인 전까지 구현하지 않는다. 승인 시 execution subject, generation model/credential, credential `use` 권한, usage/cost 기록, timeout, token/cost budget, 실패 시 fallback을 확정해야 한다. Workflow runtime에서 실행되면 rewrite LLM call도 workflow 실행 주체 기준의 권한과 비용 기록을 따라야 한다.

## Response Model

### Citation Identity

목표 citation field:

| 필드 | 의미 |
| --- | --- |
| `citation_id` | 이 응답 안에서 사용하는 opaque citation identity |
| `knowledge_base_id` | Document-level KB identity |
| `document_version_id` | Evidence로 사용한 active version 또는 historical version identity |
| `chunk_id` | Evidence chunk |
| `collection_id` | Collection을 통해 선택됐을 때의 선택적 attribution |
| `safe_source_ref` | 선택적 protected/HMAC source reference. Raw source id/url/path/principal을 대체하며 display policy와 protected source identity boundary를 따른다 |
| `rank` / `score` | Retrieval ranking summary |
| `metadata_summary` | Redaction-safe allowlist만 허용 |
| `content_preview` | 선택적 user-facing redacted/capped preview. Durable audit/trace/usage summary에는 기본 저장하지 않는다 |

### Skill provenance

Skill을 사용한 workflow draft, LLM node의 RAG 옵션, workflow test run은 다음 redaction-safe provenance를 선택적으로 반환할 수 있다.

| 필드 | 의미 |
| --- | --- |
| `skill_id` | Provider-neutral Knowledge Skill identity |
| `skill_version` | 사용한 skill version |
| `skill_freshness_state` | `fresh`, `stale`, `review_required`, `deprecated` 같은 freshness state |
| `skill_eval_status` | 평가 통과/주의/미실행 같은 safe eval 상태 |
| `source_tier` | 정책 문서, ADR/decision record, semantic definition, curated query corpus 등 safe source-of-truth tier |
| `provenance_summary` | raw source name/path/url 없이 source tier, validation checklist, safe source/version ref만 포함한 요약 |

Skill provenance는 source of truth를 대체하지 않는다. 실행 시점 citation은 계속 KB/document version/chunk/decision record 같은 근거 resource를 가리켜야 한다.

### Partial Result

Operational partial failure는 반환되는 모든 evidence가 KB permission, source ACL, final policy gate를 통과한 경우에만 safe partial result로 반환할 수 있다.

허용되는 safe marker:

- `partial_result=true`
- bucketed failed candidate count
- `some_sources_unavailable` 같은 safe reason summary
- retryability flag

기본 금지 항목:

- exact failed KB id
- exact hidden/denied count
- unavailable document를 추론하게 하는 source distribution
- raw exception message

### RAG Strategy Summary

A/B 테스트, 비용 최적화, trace side panel은 다음 redaction-safe summary만 사용할 수 있다.

| 필드 | 의미 |
| --- | --- |
| `retrieval_strategy` | `general`, `permission_scoped`, `task_aware`, `metadata_aware`, `hierarchical` 같은 실행 전략 |
| `rag_mode` | UI/실행 설정에 표시되는 RAG mode |
| `selected_collection_count` / `selected_kb_count` | authorized subset 기준 count. hidden/denied resource를 추론할 수 있으면 bucket 처리 |
| `retrieved_chunk_count` / `citation_count` | 실제 evidence로 사용된 chunk/citation 수 |
| `context_token_estimate` | RAG context token 추정치 |
| `retrieval_latency_ms` | Retrieval latency |
| `permission_filter_applied` | KB permission/source ACL gate 적용 여부. 운영 실행에서는 항상 true여야 한다 |
| `policy_result` | Final evidence policy 결과 |
| `partial_result` | Safe partial result 여부 |
| `safe_exclusion_summary` | 정확한 문서명/ID 없이 bucketed reason만 제공 |
| `evidence_sufficient` | Evidence sufficiency 결과. 권한 없는 resource 존재를 암시하지 않는 boolean 또는 safe status만 허용 |
| `insufficiency_reason` | `no_evidence`, `low_score`, `insufficient_citation`, `policy_filtered`, `operational_partial` 같은 safe reason class |
| `query_rewrite_applied` | Query rewrite 적용 여부 |
| `query_rewrite_strategy` | `template`, `llm_assisted` 같은 safe strategy summary. Raw rewritten query는 포함하지 않는다 |
| `source_tier_used` | Authorized evidence 안에서 사용한 safe source tier summary |
| `evidence_count` / `min_score_bucket` | 실제 evidence 기준 count와 bucketed score summary. Hidden/denied count는 포함하지 않는다 |
| `skill_id` / `skill_version` | 사용한 Knowledge Skill 식별자와 version. 표시 가능 여부는 skill display policy를 따른다 |
| `skill_freshness_state` / `skill_eval_status` | Skill freshness/eval summary. Raw eval fixture나 hidden source ref는 포함하지 않는다 |

이 summary에는 raw chunk content, raw source title/path/url, raw ACL row, 권한 없는 KB/document id, exact denied count, raw rewritten query, raw prompt/completion/provider response를 포함하지 않는다.

## Permission And Error Contract

| Mode | 필수 gate |
| --- | --- |
| Auto collection mode | active organization, generation model/credential visibility, credential `use`, verified credential-model relation, listing surface의 collection `read`, router scope의 collection `route`, KB use helper, source-managed KB의 source ACL/requester authorization, final evidence policy |
| Explicit KB mode | active organization, generation model/credential visibility, credential `use`, verified credential-model relation, KB visibility/resource hiding, KB use helper, source-managed KB의 source ACL/requester authorization, final evidence policy |
| 빌더 단계 Knowledge Skill mode | active organization, skill visibility, skill safe metadata display, skill freshness/eval gate. Skill visibility는 collection route, KB permission, source ACL gate를 대체하지 않는다 |
| 실행 시점 LLM node의 RAG 옵션 | execution subject, auto collection mode의 collection route, KB permission/source ACL gate, final evidence policy. Explicit KB mode는 collection route를 생략할 수 있지만 KB visibility/use/source ACL/final evidence gate를 생략하지 않는다. 빌더 단계 skill selection이나 workflow 작성자 권한을 실행 시점 data access로 전파하지 않는다 |
| Collection management | `collection.manage`; 기존 KB linking에는 `kb.manage`도 필요 |
| Collection sync/remediation | `collection.sync` 또는 organization/admin operation policy. Raw content access를 의미하지 않는다 |
| Raw content/export | Dedicated raw/compliance endpoint only. Raw/compliance permission, source-managed KB의 fresh source ACL, retention/legal-hold/purge check, response 전 raw access audit이 필요하다. 최종 enum 이름은 RBAC ADR에서 확정한다 |

Response summary와 citation은 KB id, document version id, chunk id, citation id, optional collection id, rank/score, hierarchy path, safe filename/display label, safe metadata summary, policy result, partial marker, bucketed count, retryability, opaque correlation/request id 같은 redaction-safe field만 포함할 수 있다.

Raw source id/url/path/title, raw source ACL, raw principal, raw source exception, raw query, raw rewritten query, raw answer, raw prompt/completion, raw provider response, raw skill body, hidden skill source reference, content preview, credential value는 durable audit/trace/usage metadata에 저장하지 않는다. `content_preview`는 user-facing response 전용이며 redacted/capped 상태로만 반환하고 durable summary에서 제외한다. Raw artifact를 활성화하더라도 dedicated raw/compliance flow에서만 노출하며 Agent answer, retrieval context, prompt construction, SSE stream에는 사용하지 않는다. Raw/compliance access audit은 safe reference, decision, reason code, retention/legal-hold summary, request/correlation identifier만 저장한다.

### Resource Hiding / No-result / Evidence Insufficiency Matrix

Resource hiding/no-result/evidence insufficiency API matrix는 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 safe hidden/no-result/partial-result baseline과 [implementation_baseline.md](implementation_baseline.md)의 matrix를 따른다. MBA-105 구현은 아래 safe envelope를 testable contract로 사용한다.

- Active organization scope 밖, organization mismatch, deleted/archived hidden resource, requester source authorization denied 또는 source ACL stale/unmapped/ambiguous/unverified/revoked 상태가 존재를 드러낼 수 있는 경우.
- Scope 안에서 이미 보이는 resource의 KB `use` 또는 credential `use` 권한 부족.
- 허용된 evidence candidate resolution 이후 policy block.
- Permission/source ACL gate를 통과한 뒤 발생한 source/connector operational failure.
- Auto mode에서 권한 있는 candidate가 없는 경우.
- 권한 gate 이후 evidence가 없는 경우.
- Evidence score, citation coverage, source tier policy 기준으로 근거가 부족한 경우.
- Evidence sufficiency policy가 `policy_filtered` 또는 `operational_partial` reason을 반환하는 경우.

기준은 hidden KB/version/chunk identity를 드러내는 answer run, `rag.retrieve` success audit, citation id, trace metadata, durable summary를 만들지 않는 것이다. Scope 밖, organization mismatch, hidden deleted/archived resource, existence inference가 가능한 requester source authorization denied 또는 source ACL stale/unmapped/ambiguous/unverified/revoked 상태는 resource-hidden/404 또는 safe no-result로 닫는다. Partial result는 permission/source ACL/final evidence gates 이후 발생한 operational failure에만 허용한다.

JSON/pre-stream error envelope는 `error.code`, `error.reason_code`, `error.message`, optional `correlation_id`, optional `retryable`만 포함한다. Hidden/resource-hidden path의 `message`는 generic text를 사용하고 target KB id/name/source path/count를 포함하지 않는다. Hidden/resource-hidden path의 external `reason_code`는 `resource.hidden`으로 일반화하며, `source_authorization.denied` 또는 `source_acl.stale/unmapped/ambiguous/unverified/revoked` 같은 세부 reason은 이미 존재가 authorized context에서 보이는 resource, admin/remediation context, 또는 내부 safe audit/trace allowlist에서만 사용할 수 있다. Stream 시작 후에는 HTTP status를 바꾸지 않고 `event: error` terminal event에 같은 semantic `code`/`reason_code`/`correlation_id`/`retryable` allowlist를 넣는다.

Safe no-result/insufficient-evidence response는 `status`, `evidence_sufficient=false`, `insufficiency_reason`, optional `partial_result`, optional bucketed failed candidate count, safe retryability만 포함한다. Hidden candidate id/name/count/source distribution은 포함하지 않는다.

현재 구현된 standalone single-KB `/api/v1/rag/agent/answer`와 `/api/v1/rag/agent/answer/stream` lifecycle, same-scope permission preflight blocked status, trace/usage correlation 경계는 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)을 따른다. Source-managed KB, auto collection, multi-KB mode의 target resource hiding 확장은 [ADR-0017](../../decisions/ADR-0017-knowledge-integration-provisional-implementation-baseline.md)의 provisional baseline을 따른다. 이 기준은 ADR-0013의 현재 단일 KB 계약을 재정의하지 않는다.

## Trace And Audit

- Multi-KB 또는 collection-routed answer는 `trace_payloads.rag_answer_run_id`나 `llm_usage_logs.rag_answer_run_id`를 추가하지 않는다.
- Standalone Agent answer lifecycle은 [ADR-0013](../../decisions/ADR-0013-rag-answer-trace-usage-correlation-boundary.md)에 따라 `rag.answer.*`와 `rag_answer_runs`를 사용한다.
- Workflow runtime RAG evidence는 계속 `trace_payloads.payload_kind='rag.retrieval'`를 사용할 수 있다. Standalone answer는 summary/citation을 RAG-owned record에 저장한다.
- Trace side panel에는 RAG strategy summary, citation id, KB id, document version id, chunk id, rank/score, safe metadata summary, token/cost/latency summary만 표시한다. 권한 없는 문서명/ID, raw source metadata, raw content, raw prompt/completion은 표시하지 않는다.
- Skill usage summary는 workflow draft, LLM node의 RAG 옵션, workflow test run, RAG strategy comparison에서 skill id, skill version, freshness state, eval status, safe source tier, safe provenance refs만 포함할 수 있다. Raw skill body, raw source title/path/url, hidden source refs는 표시하지 않는다.
