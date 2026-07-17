# Development Dataset AI Review Protocol

Status: Internal evaluation protocol

## Scope

This protocol qualifies the 100-question public-law development bundle for
exploratory engineering analysis. It does not create human-reviewed qrels or an
unseen confirmatory holdout.

## Reviewers

- Two isolated `gpt-5.6-sol` assessors use reasoning effort `max`.
- Reviewers receive no other review output and no retrieval metric, rank,
  condition name, or winner claim.
- Reviewers use only the immutable local question bundle and source snapshot.
- No browser, network service, external API, or model API is used.
- Pass one reads ascending question IDs; pass two reads descending question IDs.

## Rubric

Each question is judged for semantic naturalness, declared answerability,
required-evidence sufficiency, temporal scope, final accept/revise/reject decision,
confidence, bounded reason codes, and opaque replacement evidence references.

An accepted question must be natural enough for a real user, have the correct
answerability label, cite valid and sufficient evidence when answerable, and avoid
misleading temporal scope. An unanswerable question must be checked against the
available corpus before acceptance.

## Output Boundary

Row-level artifacts remain under the ignored local evaluation-data directory.
Tracked reports may contain only aggregate counts, rates, protocol and artifact
hashes, opaque question IDs for disagreements, and bounded field/reason names.
They must not contain raw queries, source text, source titles, section locators,
vectors, credentials, provider payloads, or local paths.

## Interpretation

Two-pass agreement qualifies machine-reviewed development evidence only. Any
unseen confirmatory claim remains subject to a frozen holdout, independent sampling
clusters, condition-blind relevance assessment, adjudication, and the separate
confirmatory issue's review policy.
