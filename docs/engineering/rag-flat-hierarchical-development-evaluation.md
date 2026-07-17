# Flat·Hierarchical RAG Development Evaluation

Status: Experimental engineering evidence

## Purpose

This report records the completed MBA-279 development benchmark and the
independent AI review of its 100-question public-law dataset. It is an internal
engineering result, not a production default, legal-quality certification, or
human-reviewed confirmatory benchmark.

## Evaluation Scope

The retrieval experiment compared Flat and parent-child Hierarchical retrieval
with the same source snapshot, child boundary, child embedding, query vector,
hybrid-search setting, permission context, and Top-5 cutoff. Two independent
index replicates produced the same quality metrics.

The subsequent dataset review used two isolated `gpt-5.6-sol` passes with
reasoning effort `max`. The passes read question IDs in opposite directions and
did not receive retrieval condition names, ranks, metrics, winner claims, or the
other pass's results. No browser, network service, external API, or model API was
used. A third equally isolated pass adjudicated only the 17 rows whose fields
differed.

## Two-Pass Agreement

| Measure | Result |
| --- | ---: |
| Questions reviewed per pass | 100 |
| Substantive exact agreement | 84/100 (84%) |
| All-field exact agreement | 83/100 (83%) |
| Pass decision agreement | 96% |
| Decision Cohen's kappa | 0.909584 |
| Blind third-pass adjudication | 17 rows |

Field-level agreement:

| Field | Agreement |
| --- | ---: |
| Semantic review | 97% |
| Answerability review | 97% |
| Evidence sufficiency | 97% |
| Temporal scope | 100% |
| Decision | 96% |
| Confidence | 96% |
| Reason codes | 90% |
| Proposed evidence references | 91% |

Pass one classified 66 rows as accept and 34 as revise. Pass two classified 68
as accept and 32 as revise. Neither pass rejected a row.

## Adjudicated Dataset Result

| Final decision | Count |
| --- | ---: |
| Accept | 69 |
| Revise | 31 |
| Reject | 0 |

| Answerability result | Count |
| --- | ---: |
| Confirm answerable | 88 |
| Confirm unanswerable | 6 |
| Revise unanswerable to answerable | 4 |
| Ambiguous | 2 |

All 31 revise decisions require evidence-set correction. Four questions declared
unanswerable have answer evidence in the corpus, and two answerable questions
remain semantically ambiguous. The result therefore identifies material label
and qrel debt rather than qualifying the existing machine-authored labels as a
frozen ground truth.

| Question category | Accept | Revise |
| --- | ---: | ---: |
| Ambiguous context | 3 | 12 |
| Boundary | 8 | 2 |
| Distractor | 9 | 1 |
| Multi-evidence | 10 | 5 |
| Section context | 14 | 6 |
| Single fact | 19 | 1 |
| Unanswerable | 6 | 4 |

## Retrieval Result Boundary

The valid development replicates observed the following retrieval metrics before
the AI evidence review:

| Metric | Flat | Hierarchical | Delta |
| --- | ---: | ---: | ---: |
| Recall@5 | 43.89% | 45.00% | +1.11%p |
| Hit@5 | 48.89% | 50.00% | +1.11%p |
| MRR@5 | 29.80% | 30.02% | +0.22%p |
| Multi-evidence full coverage | 12.00% | 12.00% | 0.00%p |

These values remain useful for diagnosing the evaluation pipeline, stable paired
ordering, candidate ranking, and runtime cost. They are not recalculated against
the adjudicated review because 31 rows require a new immutable question/evidence
bundle rather than an in-place qrel mutation. They therefore do not establish a
global Hierarchical advantage or justify changing the Flat production default.

## Reproducibility And Data Boundary

The row-level passes, adjudication, final review, source text, questions, and
evidence previews remain in the ignored local evaluation-data boundary. This
tracked report contains only aggregate values and hashes.

- Review protocol hash: `sha256:829b063b916c2516adefd5b9f4d86b8e854b1bef4eaa4f412de2428c5770ccc4`
- Pass one hash: `sha256:8a347d45f043b3d69fa4b64077ebf94799d8eaa7a7bda52ce1e9dc82243b5330`
- Pass two hash: `sha256:bfc556e1f60ec1cff09e38c92da248d25c961bf6ec0400b8a14bfa599cf1222f`
- Adjudication hash: `sha256:e7915e72ae85cf910ea1fcc98c01b83035b766d34f8168d46133eb2b25243533`
- Final review hash: `sha256:9fe48e0a74186a230a714449f9cab60190e0468490f370b92fc6aeb123af8f47`

Raw queries, source text, source identity, section locators, vectors, credentials,
provider payloads, and local paths are not included.

## Completion And Handoff

MBA-279 is complete as a development benchmark, diagnostic toolkit, and
machine-reviewed exploratory result. The following confirmatory requirements are
owned by MBA-309:

- create a corrected, immutable question/evidence bundle instead of mutating the
  MBA-279 development artifact;
- prepare a source-cluster-separated unseen holdout with at least 30 independent
  sampling clusters;
- complete condition-blind human or approved independent expert relevance review
  and disagreement adjudication for the holdout;
- compare document-type-specific chunk profiles and then repeat the controlled
  Flat/Hierarchical comparison with the selected child profile;
- use a frozen protocol, immutable model versions, complete pairs, and
  cluster-aware confidence intervals;
- run latency separately with at least five repeats across three independent
  sessions;
- evaluate answer correctness, citation quality, faithfulness, and abstention as
  a separate secondary generation phase.

Until those gates are complete, neither chunk size nor hierarchy mode is promoted
to a production default.

## Verification

The AI review validator covers strict row schema, unique and complete question
sets, field-level agreement, safe disagreement projection, exact adjudication-set
matching, and final aggregate generation. The evaluation-domain regression
passed 155 tests with one existing skip, and Ruff passed on the changed Python
scope. A create-only CLI replay produced byte-identical agreement and final-review
outputs.
