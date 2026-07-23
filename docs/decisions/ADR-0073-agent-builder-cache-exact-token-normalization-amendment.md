# ADR-0073: Agent Builder Cache Exact-Token Normalization Amendment

Status: Accepted

Amends: [ADR-0063](ADR-0063-agent-builder-deterministic-intent-plan-cache.md)

Partially amended by: [ADR-0074](ADR-0074-agent-builder-cache-safe-literal-normalization-amendment.md) (Decision 5 and the related consequences)

Related ADRs: [ADR-0024](ADR-0024-agent-builder-node-capability-catalog.md)

## Context

ADR-0063 Decision 2는 deterministic cache normalization profile에 영문 case,
전체-token/phrase alias, 조사·정중 표현과 위치 표현 canonicalization을 허용했다.
이 범위는 cache hit를 늘릴 수 있지만 자연어 phrase와 형태를 동등하다고 판단하는
별도 언어 정책을 필요로 한다. Catalog의 Planner용 multilingual phrase alias는 provider가
capability를 해석하기 위한 guide이며, 그 사실만으로 두 raw request가 cache key에서
동일하다고 증명되지는 않는다.

MBA-344의 CACHE-02 범위는 의미 판단이 아니라 표현 정리만 소유한다. 따라서 broad alias
문구를 그대로 구현하면 번역, 조사 제거 또는 어순 처리의 작은 변경이 cache equality를
넓히고 Planner를 건너뛰는 결과를 만들 수 있다.

## Decision

1. 이 ADR은 ADR-0063 Decision 2의 normalization profile만 다음 항목으로 좁힌다.
   ADR-0063의 cache value, HMAC key, permission/lifecycle 재검증, rehydration, single-flight,
   fail-open과 serving gate 결정은 변경하지 않는다.
2. 모든 입력에 공통으로 적용하는 표현 정리는 Unicode NFKC, CR/LF/tab의 ASCII space 변환,
   연속 ASCII space 축소와 양 끝 ASCII space 제거뿐이다. 임의 영문 token의 casefold,
   조사·정중 표현 제거, 형태소 처리와 위치/연결 표현 canonicalization은 하지 않는다.
3. 예외적으로 Catalog v3가 소유한 단일 lexical-token `planner_aliases`와 exact node token만
   typed canonical segment로 바꿀 수 있다. Case-insensitive match도 이 exact Catalog token에만
   적용한다. `GitHub`와 `github`는 `githubNode`의 exact node token으로 같게 처리할 수 있다.
   반면 standalone Catalog alias가 아닌 `깃허브`를 `github`로 번역하지 않는다.
4. Catalog의 multi-token phrase alias, 일반 동의어, 번역, phrase 재작성, 어순 재구성,
   embedding과 semantic similarity는 deterministic normalization에 사용하지 않는다.
   Multi-token Planner alias는 Planner guide로 계속 사용할 수 있지만 cache equality 근거가 아니다.
5. Normalizer는 정리된 전체 요청을 순서 있는 typed segment projection으로 표현한다.
   Versioned exact eligibility vocabulary는 위치·부정·수량·작업 문법을 인식하는 admission membership만
   제공하며 해당 literal을 변환하거나 서로 같은 표현으로 취급하지 않는다. Exact Catalog token과 이
   vocabulary로 전체 요청을 설명할 수 있을 때만 signature를 만든다. Catalog multi-token phrase alias,
   미인식 표현과 지원하지 않는 node 표현이 하나라도 남으면 `unknown_token_sequence`로 lookup/store를
   모두 bypass하며 capability만 남긴 부분 signature를 만들지 않는다. 이 admission 부분은 ADR-0074가
   safe literal preservation 규칙으로 부분 개정한다.
6. 인용문과 node label span은 exact token canonicalization에서 보호한다. 숫자, 부정, 순서와
   위치는 literal order로 보존한다. Parameter-like span에 explicit value가 있으면 보존된 값으로
   key를 만들지 않고 lookup/store를 모두 bypass한다.
7. Secret/redaction marker, explicit parameter value, truncated input projection과 명시적인 selected
   node/edge가 없는 ambiguous natural-language modify target은 closed reason으로 bypass한다.
8. `normalizer_version`은 result뿐 아니라 intent signature projection과 후속 cache key namespace/version
   material에 포함한다. Profile 또는 regression corpus의 equality 규칙이 바뀌면 version을 올리고
   이전 namespace를 읽지 않는다.

## Consequences

- NFKC/whitespace와 Catalog가 소유한 exact token 변형은 warm normalization hit를 만들 수 있다.
  ADR-0074에 따라 Catalog 미등록 literal도 변환 없이 보존되어, 같은 ordered literal 요청과만 exact warm hit를 만들 수 있다.
- Planner가 이해할 수 있는 multilingual phrase 또는 미등록 표현은 cache equality에서 번역·alias·semantic
  equivalence가 되지 않는다. Safety gate를 통과하면 ordered literal signature로 lookup/store에 참여하되,
  capability만 남긴 부분 signature나 다른 표현과의 재사용은 만들지 않는다.
- 인용문, label, 숫자, 부정, 순서와 위치가 cache equality에서 사라지지 않는다.
- Catalog의 Planner alias 계약과 cache normalization 계약이 분리되며, cache normalizer는
  provider capability 해석이나 LLM 결과 수정을 소유하지 않는다.

## Rejected Alternatives

- **Catalog phrase alias 전체 재사용**: Planner 해석용 phrase가 cache equality를 증명하지 않으므로 거부한다.
- **한국어 조사·정중 표현 제거**: 형태와 위치에 따라 의미가 달라지는 별도 언어 정책이 필요해 거부한다.
- **미인식 표현을 버리고 capability만 hashing**: 전체 요청을 bypass하지 않은 채 일부 capability만
  signature로 남기면 전체 요청을 설명하지 못하므로 거부한다.
- **Embedding 또는 semantic similarity**: Graph Template RAG의 별도 confidence/validation 경계가 필요해 거부한다.
