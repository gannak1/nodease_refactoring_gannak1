# ADR-0074: Agent Builder Cache Safe Literal Normalization Amendment

Status: Accepted

Amends: [ADR-0073](ADR-0073-agent-builder-cache-exact-token-normalization-amendment.md) Decision 5 and its related consequences

Related ADRs: [ADR-0063](ADR-0063-agent-builder-deterministic-intent-plan-cache.md), [ADR-0024](ADR-0024-agent-builder-node-capability-catalog.md)

## Context

ADR-0073 correctly narrowed deterministic equality to NFKC/whitespace cleanup and Catalog-owned single-token exact canonicalization. Its Decision 5 additionally required a fixed eligibility vocabulary to explain every remaining request token, causing otherwise safe non-empty natural-language requests to be bypassed as `unknown_token_sequence`.

`intent-normalizer-v2` retains every non-Catalog segment as an ordered literal. This preserves the entire normalized request without inferring capability, synonymy, translation, or semantic equivalence.

## Decision

1. This ADR partially amends only ADR-0073 Decision 5 and its related consequences. ADR-0073 Decisions 2 through 4 remain unchanged: NFKC/whitespace cleanup and Catalog-owned single lexical-token exact aliases and exact node tokens are the only canonicalizing transformations.
2. After secret/redaction, truncation, explicit parameter value, malformed quote, and ambiguous selected-target modify gates, every non-empty safe request is cache-eligible for lookup and store.
3. The normalizer projects the complete normalized request as ordered typed segments. Catalog-owned exact tokens may become canonical references; every other segment, including unregistered natural language and unsupported node names, remains an ordered literal. `unknown_token_sequence` is reserved for an input that cannot be safely segmented, such as a malformed quote.
4. Ordered literal preservation means an exact cache hit is possible only for the same literal sequence after the retained NFKC/whitespace and Catalog exact-token rules. A literal never becomes a phrase alias, translation, partial capability signature, embedding/vector-search result, Graph Template RAG result, or semantic-similarity match.
5. The resulting full ordered projection remains the versioned `intent_signature`. This change increments the normalizer contract/version and creates a namespace miss for prior entries.

## Consequences

- Safe requests with Catalog-missing natural language no longer bypass merely because a token is unregistered.
- Repeating the same ordered literal request can use an exact warm hit, while a different literal expression cannot share that entry merely because its capability or meaning appears similar.
- Cache admission stays fail-closed for the listed safety gates and does not introduce a semantic retrieval or interpretation path.

## Rejected Alternatives

- **Preserve only recognized capabilities**: it would create a partial signature that cannot distinguish the complete request.
- **Phrase alias, translation, or synonym mapping**: each would enlarge equality beyond the Catalog exact-token contract.
- **Embedding, vector search, Graph Template RAG, or semantic similarity**: these require a separate retrieval, confidence, and validation design; they are not cache normalization.
