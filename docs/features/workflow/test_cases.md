# Workflow Test Cases

Status: Draft
Verified Against: TBD

## Unit Tests

- Workflow run context resolver는 interactive user, approved service account, assigned operator를 구분해 `execution_subject`를 만든다.
- Missing 또는 ambiguous execution subject는 fail-closed 결과를 반환하고 workflow owner fallback을 만들지 않는다.
- LLM node의 RAG 옵션은 Builder-time skill selection과 runtime data access 권한을 분리한다.

## API Tests

- LLM node의 RAG 옵션 실행 요청은 Knowledge service에 `execution_subject`와 sanitized `subject_resolution_reason`을 전달한다.
- Execution subject가 없거나 inactive/suspended/removed membership이면 RAG preflight가 실패한다.
- Schedule/webhook/API trigger 실행은 배포 시 승인된 service account 또는 정책상 지정된 execution subject가 없으면 Knowledge retrieval을 실행하지 않는다.

## E2E Tests

- 배포된 workflow의 LLM node의 RAG 옵션은 execution subject 기준으로 KB permission/source ACL gate를 다시 평가하고, Builder actor 권한으로 fallback하지 않는다.
- Evidence sufficiency가 insufficient인 경우 workflow는 추측 답변을 생성하지 않고 safe no-result 응답 또는 명시된 분기 결과를 반환한다.
- Query rewrite가 켜진 LLM node의 RAG 옵션도 권한 없는 KB/source ACL denied 문서를 prompt, citation, trace에 포함하지 않는다.

## Permission Tests

- Workflow owner가 KB `use` 권한을 갖고 있어도 execution subject가 권한을 갖지 않으면 RAG retrieval은 실패하거나 resource-hidden/no-result matrix를 따른다.
- Skill visibility 또는 workflow 작성 권한만으로 runtime KB permission/source ACL gate가 충족되지 않는다.
- RAG를 포함한 workflow compare/A-B 실행도 일반 workflow 실행과 같은 execution subject를 사용한다.

## Edge Cases

- `llm_assisted` query rewrite가 실패하면 G14에서 정한 fallback 정책에 따라 원 query 사용 또는 terminal error로 처리하고, raw rewritten query를 durable metadata에 저장하지 않는다.
- 일부 authorized KB retrieval만 operational failure가 발생하면 Knowledge partial-result 정책에 맞춘 safe summary만 반환한다.
- Workflow runtime outbound egress guard는 Knowledge source collection egress boundary와 별도 gate이므로, Knowledge source connector guard가 workflow HTTP node 전체를 보호한다고 가정하지 않는다.
