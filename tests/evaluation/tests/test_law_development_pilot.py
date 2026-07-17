from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import numpy as np

from tests.evaluation.law_development_pilot import (
    PilotChild,
    PilotDbManifest,
    PilotInputs,
    TimingRecord,
    build_article_parents,
    build_exploratory_result,
    ordered_chunk_uuid,
    pilot_dataset_hash,
    prepare_embedding_cache,
    render_exploratory_reports,
)
from tests.evaluation.schemas import (
    ArtifactLineage,
    BenchmarkQuestion,
    BenchmarkRun,
    ConditionOutcome,
    PairedRetrievalSample,
    RetrievedEvidence,
)


SHA = f"sha256:{'a' * 64}"
EVIDENCE_A = f"ev:{'a' * 32}"
EVIDENCE_B = f"ev:{'b' * 32}"
EVIDENCE_C = f"ev:{'c' * 32}"
IRRELEVANT_TOP_FIVE = tuple(f"ev:{value * 32}" for value in ("d", "e", "f", "0", "1"))


def _child(index: int, evidence_ref: str, article: int, content: str) -> PilotChild:
    return PilotChild(
        evidence_ref=evidence_ref,
        source_ref="src_abcdefghijklmnop",
        ordinal=index,
        section_key=f"article-{article:04d}-paragraph-{index:03d}",
        content_hash=SHA,
        content=content,
        hierarchy_path=(f"제{article}장", f"제{article}조"),
    )


def test_article_parent_builder_preserves_child_boundary_and_coverage() -> None:
    children = (
        _child(0, EVIDENCE_A, 1, "가" * 300),
        _child(1, EVIDENCE_B, 1, "나" * 300),
        _child(2, EVIDENCE_C, 2, "다" * 300),
    )

    parents, mapping, fingerprint = build_article_parents(
        children,
        target_chars=500,
    )

    assert len(parents) == 3
    assert set(mapping) == {EVIDENCE_A, EVIDENCE_B, EVIDENCE_C}
    assert all(len(parent.child_refs) == 1 for parent in parents)
    assert fingerprint.startswith("sha256:")
    assert [parent.content for parent in parents] == [child.content for child in children]


def test_pilot_dataset_hash_serializes_nested_models() -> None:
    question = BenchmarkQuestion(
        question_id="q-1",
        sampling_cluster_ref="cluster-1",
        split="development",
        category="single_fact",
        difficulty="easy",
        answerable=True,
        query="질문",
        required_evidence_refs=(EVIDENCE_A,),
    )
    summary = SimpleNamespace(
        model_dump=lambda **_: {
            "base_snapshot_hash": SHA,
            "question_draft_hash": SHA,
        }
    )
    inputs = PilotInputs(
        source_summary=SimpleNamespace(),
        question_summary=summary,
        children=(_child(0, EVIDENCE_A, 1, "근거"),),
        questions=(question,),
    )

    first = pilot_dataset_hash(inputs)
    second = pilot_dataset_hash(inputs)

    assert first == second
    assert first.startswith("sha256:")


def test_ordered_chunk_uuid_preserves_shared_logical_order_across_conditions() -> None:
    flat = [ordered_chunk_uuid("run-a", "flat", "child", index) for index in range(8)]
    hierarchical = [
        ordered_chunk_uuid("run-a", "hierarchical", "child", index)
        for index in range(8)
    ]

    assert flat == sorted(flat)
    assert hierarchical == sorted(hierarchical)
    assert set(flat).isdisjoint(hierarchical)
    assert flat != [
        ordered_chunk_uuid("run-b", "flat", "child", index) for index in range(8)
    ]


class FakeEmbeddingClient:
    def __init__(self) -> None:
        self.calls = 0

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        self.calls += 1
        return [
            [float(len(text)), float(index + 1), 1.0]
            for index, text in enumerate(texts)
        ]


def test_embedding_cache_resumes_without_duplicate_provider_calls(tmp_path) -> None:
    children = (
        _child(0, EVIDENCE_A, 1, "첫 번째 근거"),
        _child(1, EVIDENCE_B, 2, "두 번째 근거"),
    )
    questions = (
        BenchmarkQuestion(
            question_id="q-1",
            sampling_cluster_ref="cluster-1",
            split="development",
            category="single_fact",
            difficulty="easy",
            answerable=True,
            query="첫 번째 질문",
            required_evidence_refs=(EVIDENCE_A,),
        ),
        BenchmarkQuestion(
            question_id="q-2",
            sampling_cluster_ref="cluster-2",
            split="development",
            category="single_fact",
            difficulty="easy",
            answerable=True,
            query="두 번째 질문",
            required_evidence_refs=(EVIDENCE_B,),
        ),
    )
    inputs = PilotInputs(
        source_summary=SimpleNamespace(),
        question_summary=SimpleNamespace(
            base_snapshot_hash=SHA,
            question_draft_hash=SHA,
        ),
        children=children,
        questions=questions,
    )
    parents, _, _ = build_article_parents(children, target_chars=500)
    first_client = FakeEmbeddingClient()

    first = __import__("asyncio").run(
        prepare_embedding_cache(
            client=first_client,
            inputs=inputs,
            parents=parents,
            cache_dir=tmp_path / "cache",
            embedding_model="embedding-test",
            batch_size=1,
        )
    )
    second_client = FakeEmbeddingClient()
    second = __import__("asyncio").run(
        prepare_embedding_cache(
            client=second_client,
            inputs=inputs,
            parents=parents,
            cache_dir=tmp_path / "cache",
            embedding_model="embedding-test",
            batch_size=1,
        )
    )

    assert first_client.calls == 6
    assert second_client.calls == 0
    assert np.array_equal(first.children, second.children)
    assert first.child_vector_hash == second.child_vector_hash


def _outcome(condition: str, refs: tuple[str, ...]) -> ConditionOutcome:
    return ConditionOutcome(
        condition=condition,
        status="success",
        evidence=tuple(
            RetrievedEvidence(evidence_ref=ref, score=1.0 - index * 0.1, rank=index + 1)
            for index, ref in enumerate(refs)
        ),
    )


def test_exploratory_metric_and_report_are_sanitized(tmp_path) -> None:
    samples = (
        PairedRetrievalSample(
            question_id="q-1",
            sampling_cluster_ref="cluster-1",
            category="single_fact",
            answerable=True,
            required_evidence_refs=(EVIDENCE_A,),
            flat=_outcome("flat", (*IRRELEVANT_TOP_FIVE, EVIDENCE_A)),
            hierarchical=_outcome("hierarchical", (EVIDENCE_A,)),
        ),
        PairedRetrievalSample(
            question_id="q-2",
            sampling_cluster_ref="cluster-2",
            category="multi_evidence",
            answerable=True,
            required_evidence_refs=(EVIDENCE_B, EVIDENCE_C),
            flat=_outcome("flat", (EVIDENCE_B,)),
            hierarchical=_outcome("hierarchical", (EVIDENCE_B, EVIDENCE_C)),
        ),
        PairedRetrievalSample(
            question_id="q-3",
            sampling_cluster_ref="cluster-2",
            category="unanswerable",
            answerable=False,
            required_evidence_refs=(),
            flat=_outcome("flat", (EVIDENCE_A,)),
            hierarchical=_outcome("hierarchical", (EVIDENCE_B,)),
        ),
    )
    lineage = ArtifactLineage(
        protocol_hash=SHA,
        dataset_hash=SHA,
        split_hash=SHA,
        config_hash=SHA,
        code_commit="a" * 40,
        source_equality_verified=True,
        child_boundary_equality_verified=True,
        child_vector_equality=True,
        segmentation_contract_version="section-v1",
        vector_equality_check_version="exact-v1",
        parent_builder_fingerprint=SHA,
    )
    run = BenchmarkRun(
        run_id="pilot-test",
        study_phase="development",
        seed=279,
        lineage=lineage,
        samples=samples,
        complete_pair_count=3,
        valid=True,
        attrition={},
    )
    manifest = PilotDbManifest(
        run_id="pilot-test",
        benchmark_fingerprint=SHA,
        flat_kb_id=uuid4(),
        hierarchical_kb_id=uuid4(),
        actor_user_id=uuid4(),
        organization_id=uuid4(),
        child_count=3,
        parent_count=2,
        vector_dimension=3,
        source_count=1,
        child_vector_hash=SHA,
        parent_vector_hash=SHA,
        parent_builder_fingerprint=SHA,
        chunk_id_ordering_version="shared-logical-ordinal-uuid-v1",
        source_equality_verified=True,
        child_boundary_equality_verified=True,
        child_vector_equality=True,
        flat_evidence_mapping={},
        hierarchical_evidence_mapping={},
    )
    timings = [
        TimingRecord("flat", "q-1", 10.0, True),
        TimingRecord("hierarchical", "q-1", 20.0, True),
        TimingRecord("flat", "q-2", 12.0, True),
        TimingRecord("hierarchical", "q-2", 24.0, True),
    ]

    result = build_exploratory_result(
        run=run,
        timings=timings,
        manifest=manifest,
        code_commit="a" * 40,
        working_tree_diff_hash=SHA,
        source_snapshot_hash=SHA,
        question_draft_hash=SHA,
        embedding_model="embedding-test",
        generated_at_utc="2026-07-16T00:00:00+00:00",
        controls={"top_k": 5},
    )
    paths = render_exploratory_reports(result, tmp_path / "reports")

    assert result.hierarchical.recall_at_5 > result.flat.recall_at_5
    assert result.flat.hit_at_5 == 0.5
    assert result.flat.recall_at_5 == 0.25
    assert result.hierarchical.multi_evidence_full_coverage == 1.0
    assert result.flat.multi_evidence_full_coverage == 0.0
    assert result.recall_delta_exploratory is True
    assert all(path.exists() for path in paths)
    report_text = "\n".join(path.read_text(encoding="utf-8") for path in paths)
    html_text = paths[2].read_text(encoding="utf-8")
    assert "RAW_QUERY_SENTINEL" not in report_text
    assert str(manifest.flat_kb_id) not in report_text
    assert "table-layout:fixed" in html_text
    assert "overflow-wrap:anywhere" in html_text
