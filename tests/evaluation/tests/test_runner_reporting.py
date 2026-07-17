from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from tests.evaluation.comparison_report import (
    _recommendation_status,
    render_reports,
    score_benchmark,
)
from tests.evaluation.judgment_pool import build_blind_pool, freeze_qrels
from tests.evaluation.rag_evaluator import EvaluationConfig, RAGEvaluator
from tests.evaluation.rag_metrics import EvaluationSample
from tests.evaluation.paired_runner import (
    BenchmarkOperationalError,
    PairedBenchmarkRunner,
    RetrievalResponse,
    RunnerConfig,
)
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import (
    BenchmarkResult,
    BenchmarkQuestion,
    QrelRecord,
    RetrievedEvidence,
)
from tests.evaluation.tests.support import make_lineage, make_protocol


class FakeRetriever:
    def __init__(self, *, fail_condition: str | None = None) -> None:
        self.fail_condition = fail_condition
        self.calls: list[tuple[str, str, object]] = []

    def retrieve(self, *, condition, question, query_vector, config):
        self.calls.append((condition, question.question_id, query_vector))
        if condition == self.fail_condition:
            raise BenchmarkOperationalError("retrieval_timeout")
        refs = {
            "flat": (
                "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "ev:cccccccccccccccccccccccccccccccc",
            ),
            "hierarchical": (
                "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            ),
        }[condition]
        return tuple(
            RetrievedEvidence(evidence_ref=ref, score=1.0 - index * 0.1, rank=index + 1)
            for index, ref in enumerate(refs)
        )


def question(
    question_id: str,
    cluster: str,
    *,
    answerable: bool = True,
    split: str = "development",
):
    return BenchmarkQuestion(
        question_id=question_id,
        sampling_cluster_ref=cluster,
        split=split,
        category="single_fact" if answerable else "unanswerable",
        difficulty="easy",
        answerable=answerable,
        query="RAW_QUERY_SENTINEL",
        required_evidence_refs=("ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",)
        if answerable
        else (),
    )


def test_runner_reuses_query_vector_and_balances_order() -> None:
    retriever = FakeRetriever()
    embed_calls: list[str] = []
    config = RunnerConfig(seed=279, study_phase="development")
    protocol = make_protocol(
        config,
        planned_answerable_n=2,
        planned_unanswerable_n=0,
    )
    runner = PairedBenchmarkRunner(
        retriever=retriever,
        embed_query=lambda query: embed_calls.append(query) or (0.1, 0.2),
        config=config,
        protocol=protocol,
    )
    run = runner.run(
        [question("q1", "c1"), question("q2", "c2")],
        run_id="synthetic-run",
        artifact_lineage=make_lineage(protocol, config),
    )
    assert len(embed_calls) == 2
    for question_id in ("q1", "q2"):
        vectors = [call[2] for call in retriever.calls if call[1] == question_id]
        assert vectors == [(0.1, 0.2), (0.1, 0.2)]
    first_condition_by_pair = [retriever.calls[index][0] for index in range(0, 4, 2)]
    assert set(first_condition_by_pair) == {"flat", "hierarchical"}
    assert all(
        outcome.latency_ms is None
        for sample in run.samples
        for outcome in (sample.flat, sample.hierarchical)
    )
    assert run.complete_pair_count == 2
    assert run.valid is True


def test_runner_separates_failure_from_no_evidence() -> None:
    config = RunnerConfig(seed=279, study_phase="development", max_attempts=1)
    protocol = make_protocol(
        config,
        planned_answerable_n=1,
        planned_unanswerable_n=0,
    )
    runner = PairedBenchmarkRunner(
        retriever=FakeRetriever(fail_condition="hierarchical"),
        embed_query=lambda _: (0.1,),
        config=config,
        protocol=protocol,
    )
    run = runner.run(
        [question("q1", "c1")],
        run_id="failed-run",
        artifact_lineage=make_lineage(protocol, config),
    )
    assert run.complete_pair_count == 0
    assert run.valid is False
    assert run.attrition == {"hierarchical.retrieval_timeout": 1}


def test_development_runner_allows_repeated_unanswerable_cluster() -> None:
    config = RunnerConfig(seed=279, study_phase="development")
    protocol = make_protocol(
        config,
        planned_answerable_n=0,
        planned_unanswerable_n=2,
    )
    runner = PairedBenchmarkRunner(
        retriever=FakeRetriever(),
        embed_query=lambda _: (0.1,),
        config=config,
        protocol=protocol,
    )

    run = runner.run(
        [
            question("q1", "shared-cluster", answerable=False),
            question("q2", "shared-cluster", answerable=False),
        ],
        run_id="development-unanswerable-run",
        artifact_lineage=make_lineage(protocol, config),
    )

    assert run.complete_pair_count == 2


def test_confirmatory_runner_rejects_repeated_unanswerable_cluster() -> None:
    config = RunnerConfig(seed=279, study_phase="confirmatory_holdout")
    protocol = make_protocol(
        config,
        planned_answerable_n=41,
        planned_unanswerable_n=59,
    )
    runner = PairedBenchmarkRunner(
        retriever=FakeRetriever(),
        embed_query=lambda _: (0.1,),
        config=config,
        protocol=protocol,
    )
    questions = [
        *[
            question(
                f"q-answerable-{index:02d}",
                f"answerable-cluster-{index:02d}",
                split="holdout",
            )
            for index in range(41)
        ],
        question("q-duplicate-1", "shared-cluster", answerable=False, split="holdout"),
        question("q-duplicate-2", "shared-cluster", answerable=False, split="holdout"),
        *[
            question(
                f"q-{index:02d}",
                f"cluster-{index:02d}",
                answerable=False,
                split="holdout",
            )
            for index in range(57)
        ],
    ]

    with pytest.raises(
        ValueError,
        match="runner_duplicate_unanswerable_safety_cluster",
    ):
        runner.run(
            questions,
            run_id="confirmatory-unanswerable-run",
            artifact_lineage=make_lineage(protocol, config),
        )


def test_primary_runner_rejects_rerank_or_rewrite() -> None:
    with pytest.raises(ValueError):
        RunnerConfig(use_rerank=True)
    with pytest.raises(ValueError):
        RunnerConfig(use_rewrite=True)
    with pytest.raises(ValueError):
        RunnerConfig(source_tier_policy="tie_break")


def test_confirmatory_runner_requires_frozen_protocol_before_execution() -> None:
    config = RunnerConfig(study_phase="confirmatory_holdout")
    with pytest.raises(ValueError, match="confirmatory_protocol_required"):
        PairedBenchmarkRunner(
            retriever=FakeRetriever(),
            embed_query=lambda _: (0.1,),
            config=config,
        )

    protocol = make_protocol(
        config,
        planned_answerable_n=41,
        planned_unanswerable_n=59,
    )
    runner = PairedBenchmarkRunner(
        retriever=FakeRetriever(),
        embed_query=lambda _: (0.1,),
        config=config,
        protocol=protocol,
    )
    outcome = runner._retrieve(
        condition="flat",
        question=question("q1", "c1").model_copy(update={"split": "holdout"}),
        query_vector=(0.1,),
    )
    assert outcome.status == "operational_failure"
    assert outcome.safe_reason_code == "final_diagnostics_missing"


def test_cutoff_tie_truncation_is_attrition_not_schema_failure() -> None:
    class TruncatedRetriever(FakeRetriever):
        def retrieve(self, *, condition, question, query_vector, config):
            evidence = super().retrieve(
                condition=condition,
                question=question,
                query_vector=query_vector,
                config=config,
            )
            return RetrievalResponse(
                evidence=tuple(evidence),
                tie_group_truncated=condition == "hierarchical",
            )

    config = RunnerConfig(study_phase="development")
    protocol = make_protocol(
        config,
        planned_answerable_n=1,
        planned_unanswerable_n=0,
    )
    run = PairedBenchmarkRunner(
        retriever=TruncatedRetriever(),
        embed_query=lambda _: (0.1,),
        config=config,
        protocol=protocol,
    ).run(
        [question("q1", "c1")],
        run_id="truncated-run",
        artifact_lineage=make_lineage(protocol, config),
    )

    assert run.valid is False
    assert run.complete_pair_count == 0
    assert run.attrition == {"hierarchical.tie_group_truncated": 1}


def test_flat_benefit_uses_mirrored_safety_latency_and_mrr_gates() -> None:
    config = RunnerConfig()
    protocol = make_protocol(
        config,
        planned_answerable_n=1,
        planned_unanswerable_n=1,
    )
    recall = SimpleNamespace(point=-0.10, lower=-0.12, upper=-0.08, exploratory=False)
    mrr = SimpleNamespace(point=-0.01, lower=-0.02, upper=0.0, exploratory=False)
    safety = SimpleNamespace(lower=-0.02, point=0.0, upper=0.02, sample_count=1)
    latency = SimpleNamespace(lower=0.90, point=1.0, upper=1.10)

    assert (
        _recommendation_status(
            valid=True,
            study_phase="confirmatory_holdout",
            recall_interval=recall,
            mrr_interval=mrr,
            safety=safety,
            latency=latency,
            protocol=protocol,
        )
        == "flat_benefit"
    )

    unsafe_for_flat = SimpleNamespace(
        lower=-0.10,
        point=-0.05,
        upper=0.0,
        sample_count=1,
    )
    assert (
        _recommendation_status(
            valid=True,
            study_phase="confirmatory_holdout",
            recall_interval=recall,
            mrr_interval=mrr,
            safety=unsafe_for_flat,
            latency=latency,
            protocol=protocol,
        )
        == "mixed"
    )


def test_synthetic_pipeline_is_blind_sanitized_and_reproducible(tmp_path) -> None:
    config = RunnerConfig(seed=279, study_phase="development")
    protocol = make_protocol(
        config,
        planned_answerable_n=1,
        planned_unanswerable_n=1,
    )
    runner = PairedBenchmarkRunner(
        retriever=FakeRetriever(),
        embed_query=lambda _: (0.1, 0.2),
        config=config,
        protocol=protocol,
    )
    questions = [question("q1", "c1"), question("q2", "c2", answerable=False)]
    run = runner.run(
        questions,
        run_id="synthetic-run",
        artifact_lineage=make_lineage(protocol, config),
    )
    sealed_hash = canonical_hash(run.model_dump(mode="json"))
    pool = build_blind_pool(
        run,
        sealed_output_hash=sealed_hash,
        depth=protocol.pooling_plan.depth,
        score_precision=protocol.tie_policy.score_precision,
        pool_seed=protocol.seeds.pool,
    )
    pool_dump = json.dumps(pool.model_dump(mode="json"), sort_keys=True)
    for forbidden in ("condition", "score", "rank", "RAW_QUERY_SENTINEL"):
        assert forbidden not in pool_dump

    qrels = freeze_qrels(
        pool,
        [
                QrelRecord(
                    question_id=record.question_id,
                    evidence_ref=record.evidence_ref,
                    relevance=int(
                        record.question_id == "q1"
                        and record.evidence_ref
                        == "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    ),
                    required=(
                        record.question_id == "q1"
                        and record.evidence_ref
                        == "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
                    ),
            )
            for record in pool.records
        ],
        protocol_hash=run.lineage.protocol_hash,
        dataset_hash=run.lineage.dataset_hash,
        sealed_output_hash=sealed_hash,
        qrels_version="qrels-v1",
    )
    result = score_benchmark(
        run,
        protocol=protocol,
        pool=pool,
        qrels=qrels,
        bootstrap_iterations=protocol.decision_gates.bootstrap_iterations,
    )
    output_dir = tmp_path / "report"
    markdown_path, html_path = render_reports(result, output_dir)
    first_json = json.dumps(result.model_dump(mode="json"), sort_keys=True)
    second = score_benchmark(
        run,
        protocol=protocol,
        pool=pool,
        qrels=qrels,
        bootstrap_iterations=protocol.decision_gates.bootstrap_iterations,
    )
    assert first_json == json.dumps(second.model_dump(mode="json"), sort_keys=True)

    for path in (markdown_path, html_path):
        rendered = path.read_text(encoding="utf-8")
        assert "RAW_QUERY_SENTINEL" not in rendered
        assert "controlled_child_boundary_retrieval_effect" in rendered
    assert "<script" not in html_path.read_text(encoding="utf-8").lower()
    html = html_path.read_text(encoding="utf-8")
    assert 'class="direction"' in html
    assert 'class="table-scroll"' in html
    assert "Registered gates" in html
    assert result.protocol_hash in html
    assert (
        result.win_tie_loss.wins
        + result.win_tie_loss.ties
        + result.win_tie_loss.losses
        == 1
    )

    invalid_payload = result.model_dump(mode="json")
    invalid_payload.update(valid=False, recommendation_status="invalid")
    invalid = BenchmarkResult.model_validate(invalid_payload)
    _, invalid_html_path = render_reports(invalid, tmp_path / "invalid-report")
    invalid_html = invalid_html_path.read_text(encoding="utf-8")
    assert "Metrics are diagnostic only" in invalid_html
    assert 'class="ci-axis"' not in invalid_html


def test_qrels_must_cover_pool_exactly() -> None:
    config = RunnerConfig(study_phase="development")
    protocol = make_protocol(
        config,
        planned_answerable_n=1,
        planned_unanswerable_n=0,
    )
    runner = PairedBenchmarkRunner(
        retriever=FakeRetriever(),
        embed_query=lambda _: (0.1,),
        config=config,
        protocol=protocol,
    )
    run = runner.run(
        [question("q1", "c1")],
        run_id="r",
        artifact_lineage=make_lineage(protocol, config),
    )
    pool = build_blind_pool(
        run,
        sealed_output_hash=canonical_hash(run.model_dump(mode="json")),
        depth=protocol.pooling_plan.depth,
        score_precision=protocol.tie_policy.score_precision,
        pool_seed=protocol.seeds.pool,
    )
    with pytest.raises(ValueError, match="qrels_pool_coverage_mismatch"):
        freeze_qrels(
            pool,
            [],
            protocol_hash=run.lineage.protocol_hash,
            dataset_hash=run.lineage.dataset_hash,
            sealed_output_hash=pool.sealed_output_hash,
            qrels_version="qrels-v1",
        )


def test_legacy_evaluator_failure_log_does_not_disclose_query_or_exception(
    capsys, tmp_path
) -> None:
    evaluator = RAGEvaluator(
        EvaluationConfig(
            dataset_name="safe",
            knowledge_base_id="safe",
            top_k_values=[1],
            report_dir=str(tmp_path),
        )
    )

    def fail(_query, _top_k):
        raise RuntimeError("RAW_EXCEPTION_SENTINEL")

    evaluator.evaluate(
        [
            EvaluationSample(
                query="RAW_QUERY_SENTINEL",
                relevant_passages=["approved safe answer"],
            )
        ],
        fail,
    )
    output = capsys.readouterr().out
    assert "retrieval_failed sample_index=1" in output
    assert "RAW_QUERY_SENTINEL" not in output
    assert "RAW_EXCEPTION_SENTINEL" not in output
