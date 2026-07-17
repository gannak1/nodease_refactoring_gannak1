from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from tests.evaluation.assessment_resolver import (
    AssessmentBundle,
    BlindAssessment,
    RequiredEvidence,
)
from tests.evaluation.paired_runner import PairedBenchmarkRunner, RunnerConfig
from tests.evaluation.protocol import atomic_write_json, load_json_model
from tests.evaluation.schemas import (
    BenchmarkQuestion,
    BlindPoolArtifact,
    RetrievedEvidence,
)
from tests.evaluation.tests.support import make_lineage, make_protocol


class Retriever:
    def retrieve(self, *, condition, question, query_vector, config):
        refs = (
            (
                "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            )
            if condition == "flat"
            else (
                "ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
                "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            )
        )
        return tuple(
            RetrievedEvidence(evidence_ref=ref, score=0.9 - index * 0.1, rank=index + 1)
            for index, ref in enumerate(refs)
        )


def _run_cli(repo: Path, *arguments: str) -> str:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(repo)
    completed = subprocess.run(
        [
            sys.executable,
            str(repo / "tests/evaluation/run_flat_hierarchical_benchmark.py"),
            *arguments,
        ],
        cwd=repo,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr
    assert "RAW_QUERY_SENTINEL" not in completed.stdout
    return completed.stdout


def test_cli_seal_pool_assess_score_and_render(tmp_path) -> None:
    repo = Path(__file__).resolve().parents[3]
    config = RunnerConfig(seed=279)
    protocol = make_protocol(
        config,
        planned_answerable_n=1,
        planned_unanswerable_n=1,
    )
    questions = [
        BenchmarkQuestion(
            question_id="q1",
            sampling_cluster_ref="c1",
            split="development",
            category="single_fact",
            difficulty="easy",
            answerable=True,
            query="RAW_QUERY_SENTINEL",
            required_evidence_refs=("ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",),
        ),
        BenchmarkQuestion(
            question_id="q2",
            sampling_cluster_ref="c2",
            split="development",
            category="unanswerable",
            difficulty="hard",
            answerable=False,
            query="approved synthetic unknown",
            required_evidence_refs=(),
        ),
    ]
    run = PairedBenchmarkRunner(
        retriever=Retriever(),
        embed_query=lambda _query: (0.1, 0.2),
        config=config,
        protocol=protocol,
    ).run(
        questions,
        run_id="cli-e2e",
        artifact_lineage=make_lineage(protocol, config),
    )

    run_path = tmp_path / "run.json"
    protocol_path = tmp_path / "protocol.json"
    sealed_path = tmp_path / "sealed.json"
    pool_path = tmp_path / "pool.json"
    bundle_path = tmp_path / "assessment-bundle.json"
    qrels_path = tmp_path / "qrels.json"
    summary_path = tmp_path / "assessment-summary.json"
    result_path = tmp_path / "result.json"
    report_dir = tmp_path / "report"
    atomic_write_json(run_path, run)
    atomic_write_json(protocol_path, protocol)

    _run_cli(repo, "seal-run", "--input", str(run_path), "--output", str(sealed_path))
    _run_cli(
        repo,
        "build-judgment-pool",
        "--sealed-input",
        str(sealed_path),
        "--protocol",
        str(protocol_path),
        "--output",
        str(pool_path),
    )
    pool = load_json_model(pool_path, BlindPoolArtifact)
    assessments = []
    for record in pool.records:
        relevance = int(
            record.question_id == "q1"
            and record.evidence_ref == "ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        )
        for assessor in ("assessor_left", "assessor_right"):
            assessments.append(
                BlindAssessment(
                    question_id=record.question_id,
                    evidence_ref=record.evidence_ref,
                    assessor_ref=assessor,
                    relevance=relevance,
                )
            )
    atomic_write_json(
        bundle_path,
        AssessmentBundle(
            qrels_version="qrels-v1",
            role_separation_attested=True,
            assessments=tuple(assessments),
            required_evidence=(
                RequiredEvidence(
                    question_id="q1",
                    evidence_ref="ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
                ),
            ),
        ),
    )
    _run_cli(
        repo,
        "freeze-qrels",
        "--sealed-input",
        str(sealed_path),
        "--pool",
        str(pool_path),
        "--assessments",
        str(bundle_path),
        "--output",
        str(qrels_path),
        "--summary-output",
        str(summary_path),
    )
    _run_cli(
        repo,
        "score",
        "--sealed-input",
        str(sealed_path),
        "--protocol",
        str(protocol_path),
        "--pool",
        str(pool_path),
        "--qrels",
        str(qrels_path),
        "--output",
        str(result_path),
    )
    _run_cli(
        repo,
        "render",
        "--input",
        str(result_path),
        "--output-dir",
        str(report_dir),
    )

    for path in (
        sealed_path,
        pool_path,
        qrels_path,
        summary_path,
        result_path,
        report_dir / "result.json",
        report_dir / "report.md",
        report_dir / "report.html",
    ):
        assert path.exists()
        assert "RAW_QUERY_SENTINEL" not in path.read_text(encoding="utf-8")
    assert "controlled_child_boundary_retrieval_effect" in (
        report_dir / "report.html"
    ).read_text(encoding="utf-8")
