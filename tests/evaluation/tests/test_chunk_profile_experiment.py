from __future__ import annotations

from tests.evaluation.chunk_profile_experiment import (
    AtomicEvidence,
    ChunkProfileInputs,
    ChunkProfileSpec,
    ProfileChunk,
    RankedProfileChunk,
    SourceContext,
    aggregate_profile_metrics,
    build_profile_chunks,
    evaluate_question_profile,
    stable_rank,
)
from tests.evaluation.schemas import BenchmarkQuestion


REF_A = "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
REF_B = "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
REF_C = "ev:cccccccccccccccccccccccccccccccc"
REF_D = "ev:dddddddddddddddddddddddddddddddd"


class CharacterEncoder:
    def encode(self, text: str) -> list[int]:
        return list(range(len(text)))


def _question(
    question_id: str,
    refs: tuple[str, ...],
    *,
    cluster: str = "cluster-a",
) -> BenchmarkQuestion:
    return BenchmarkQuestion(
        question_id=question_id,
        sampling_cluster_ref=cluster,
        split="development",
        category="multi_evidence" if len(refs) > 1 else "single_fact",
        difficulty="medium",
        answerable=True,
        query="검증 질문",
        required_evidence_refs=refs,
    )


def _inputs() -> ChunkProfileInputs:
    atoms = (
        AtomicEvidence(REF_A, "src-a", 0, "article-0001-paragraph-001", "A" * 20, ("제1조",)),
        AtomicEvidence(REF_B, "src-a", 1, "article-0001-paragraph-002", "B" * 20, ("제1조",)),
        AtomicEvidence(REF_C, "src-a", 2, "article-0002-paragraph-001", "C" * 20, ("제2조",)),
        AtomicEvidence(REF_D, "src-b", 3, "section", "D" * 200, ("절",)),
    )
    return ChunkProfileInputs(
        corpus_id="test-corpus",
        content_class="synthetic",
        source_snapshot_hash="sha256:" + "1" * 64,
        question_draft_hash="sha256:" + "2" * 64,
        atoms=atoms,
        questions=(_question("q-a", (REF_A,)),),
        source_contexts={
            "src-a": SourceContext("테스트 규정", "현행"),
            "src-b": SourceContext("별도 규정"),
        },
    )


def _ranked(
    ref: str,
    ordinal: int,
    score: float,
    tokens: int,
    evidence_refs: tuple[str, ...],
    fingerprint: str,
) -> RankedProfileChunk:
    return RankedProfileChunk(
        chunk_ref=ref,
        ordinal=ordinal,
        score=score,
        token_count=tokens,
        evidence_refs=evidence_refs,
        content_fingerprint=fingerprint,
    )


def test_grouped_profile_preserves_atomic_coverage_and_structure_boundaries() -> None:
    inputs = _inputs()
    chunks = build_profile_chunks(
        inputs,
        ChunkProfileSpec(
            profile_id="contextual_test",
            contextual=True,
            target_tokens=128,
        ),
        CharacterEncoder(),
    )

    assert [ref for chunk in chunks for ref in chunk.evidence_refs] == [
        REF_A,
        REF_B,
        REF_C,
        REF_D,
    ]
    assert chunks[0].evidence_refs == (REF_A, REF_B)
    assert chunks[1].evidence_refs == (REF_C,)
    assert chunks[2].evidence_refs == (REF_D,)
    assert chunks[2].token_count > 128
    assert chunks[0].content.count("[문서: 테스트 규정 | 버전: 현행]") == 1


def test_atomic_profiles_keep_one_evidence_per_chunk() -> None:
    inputs = _inputs()
    raw = build_profile_chunks(
        inputs,
        ChunkProfileSpec(profile_id="raw_test", contextual=False),
        CharacterEncoder(),
    )
    contextual = build_profile_chunks(
        inputs,
        ChunkProfileSpec(profile_id="contextual_test", contextual=True),
        CharacterEncoder(),
    )

    assert all(len(chunk.evidence_refs) == 1 for chunk in raw)
    assert all(len(chunk.evidence_refs) == 1 for chunk in contextual)
    assert not raw[0].content.startswith("[문서:")
    assert contextual[0].content.startswith("[문서:")


def test_stable_rank_uses_logical_ordinal_for_equal_scores() -> None:
    candidates = (
        _ranked("chunk-z", 2, 0.5, 10, (REF_C,), "f3"),
        _ranked("chunk-a", 0, 0.5, 10, (REF_A,), "f1"),
        _ranked("chunk-b", 1, 0.5, 10, (REF_B,), "f2"),
    )

    assert [item.ordinal for item in stable_rank(candidates)] == [0, 1, 2]


def test_aggregate_chunk_expands_atomic_evidence_for_metrics() -> None:
    question = _question("q-multi", (REF_B, REF_C))
    candidates = (
        _ranked("chunk-1", 0, 0.9, 100, (REF_A, REF_B), "same"),
        _ranked("chunk-2", 1, 0.8, 100, (REF_C,), "same"),
    )

    metric = evaluate_question_profile(
        question=question,
        candidates=candidates,
        context_budget_tokens=500,
        latency_ms=3.0,
    )

    assert metric.hit_at_5 == 1.0
    assert metric.recall_at_5 == 1.0
    assert metric.mrr_at_5 == 1.0
    assert metric.budget_recall == 1.0
    assert metric.top_5_unique_content_rate == 0.5


def test_context_budget_stops_before_first_non_fitting_ranked_chunk() -> None:
    question = _question("q-budget", (REF_B, REF_C))
    candidates = (
        _ranked("chunk-1", 0, 0.9, 1_000, (REF_A, REF_B), "f1"),
        _ranked("chunk-2", 1, 0.8, 1_200, (REF_C,), "f2"),
        _ranked("chunk-3", 2, 0.7, 20, (REF_C,), "f3"),
    )

    metric = evaluate_question_profile(
        question=question,
        candidates=candidates,
        context_budget_tokens=2_048,
        latency_ms=1.0,
    )

    assert metric.recall_at_5 == 1.0
    assert metric.budget_recall == 0.5
    assert metric.selected_chunk_count == 1
    assert metric.selected_token_count == 1_000


def test_profile_aggregate_uses_paired_cluster_delta() -> None:
    inputs = _inputs()
    chunks = build_profile_chunks(
        inputs,
        ChunkProfileSpec(profile_id="contextual_atomic", contextual=True),
        CharacterEncoder(),
    )
    profile_chunks = tuple(
        ProfileChunk(
            chunk_ref=chunk.chunk_ref.replace("contextual_atomic", "", 1),
            profile_id="contextual_256",
            source_ref=chunk.source_ref,
            ordinal=chunk.ordinal,
            content=chunk.content,
            token_count=chunk.token_count,
            content_fingerprint=chunk.content_fingerprint,
            evidence_refs=chunk.evidence_refs,
            hierarchy_path=chunk.hierarchy_path,
        )
        for chunk in chunks
    )
    questions = [
        _question(f"q-{index}", (REF_A,), cluster=f"cluster-{index}")
        for index in range(4)
    ]
    baseline_rows = [
        evaluate_question_profile(
            question=question,
            candidates=(_ranked("base", 0, 1.0, 10, (REF_A,), "f"),),
            context_budget_tokens=100,
            latency_ms=1.0,
        )
        for question in questions
    ]
    candidate_rows = [
        evaluate_question_profile(
            question=question,
            candidates=(_ranked("candidate", 0, 1.0, 10, (REF_A,), "f"),),
            context_budget_tokens=100,
            latency_ms=1.0,
        )
        for question in questions
    ]

    aggregates = aggregate_profile_metrics(
        specs=(
            ChunkProfileSpec(profile_id="contextual_atomic", contextual=True),
            ChunkProfileSpec(
                profile_id="contextual_256", contextual=True, target_tokens=256
            ),
        ),
        chunks_by_profile={
            "contextual_atomic": chunks,
            "contextual_256": profile_chunks,
        },
        metrics_by_profile={
            "contextual_atomic": baseline_rows,
            "contextual_256": candidate_rows,
        },
        bootstrap_iterations=1_000,
    )

    assert aggregates[1].delta_vs_contextual_atomic == 0.0
    assert aggregates[1].delta_ci_lower == 0.0
    assert aggregates[1].delta_ci_upper == 0.0
