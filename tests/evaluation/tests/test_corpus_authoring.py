from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from tests.evaluation.corpus_authoring import (
    AuthoredSection,
    AuthoredSource,
    QuestionBlueprint,
    load_question_blueprints,
    load_synthetic_package,
    prepare_corpus,
)
from tests.evaluation import prepare_flat_hierarchical_corpus as preparation_cli
from tests.evaluation.protocol import validate_local_source_bindings
from tests.evaluation.schemas import BenchmarkQuestion, SourceBindingRecord


SOURCE_REF = "src_AAAAAAAAAAAAAAAA"


def _source(
    *,
    cluster: str = "cluster-a",
    split: str = "development",
) -> AuthoredSource:
    return AuthoredSource.model_validate(
        {
            "source_ref": SOURCE_REF,
            "sampling_cluster_ref": cluster,
            "split": split,
            "source_type": "synthetic",
            "version_role": "current",
            "title": "Synthetic access policy",
            "sections": [
                {
                    "section_key": "approval",
                    "hierarchy_path": ["Access", "Approval"],
                    "heading": "Approval",
                    "text": "Managers approve access before activation.",
                }
            ],
        }
    )


def _question(
    *,
    cluster: str = "cluster-a",
    split: str = "development",
) -> QuestionBlueprint:
    return QuestionBlueprint.model_validate(
        {
            "question_id": "question-001",
            "sampling_cluster_ref": cluster,
            "split": split,
            "category": "single_fact",
            "difficulty": "easy",
            "answerable": True,
            "query": "Who approves access?",
            "safe_display_label": "Access approver",
            "required_section_refs": [f"{SOURCE_REF}:approval"],
        }
    )


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_prepare_corpus_writes_bound_and_opaque_local_artifacts(tmp_path) -> None:
    output = tmp_path / "prepared"

    summary = prepare_corpus(
        corpus_id="synthetic-v1",
        content_class="synthetic",
        sources=(_source(),),
        questions=(_question(),),
        output_dir=output,
        license_ref=None,
        provenance_rows=({"created_from": "project_authored_synthetic"},),
    )

    assert summary.source_count == 1
    assert summary.canonical_child_count == 1
    assert summary.question_count == 1
    bindings = tuple(
        SourceBindingRecord.model_validate(row)
        for row in json.loads(
            (output / "source_bindings.json").read_text(encoding="utf-8")
        )
    )
    binding_summary = validate_local_source_bindings(output, bindings)
    assert binding_summary.binding_count == 1

    canonical = _jsonl(output / "canonical_children.jsonl")
    questions = _jsonl(output / "question_draft.jsonl")
    BenchmarkQuestion.model_validate(questions[0])
    assert canonical[0]["evidence_ref"].startswith("ev:")
    assert questions[0]["required_evidence_refs"] == [
        canonical[0]["evidence_ref"]
    ]
    assert SOURCE_REF not in questions[0]["required_evidence_refs"][0]


def test_prepare_corpus_never_overwrites_an_existing_snapshot(tmp_path) -> None:
    output = tmp_path / "prepared"
    arguments = {
        "corpus_id": "synthetic-v1",
        "content_class": "synthetic",
        "sources": (_source(),),
        "questions": (_question(),),
        "output_dir": output,
        "license_ref": None,
    }
    prepare_corpus(**arguments)
    summary_before = (output / "summary.json").read_bytes()

    with pytest.raises(FileExistsError, match="prepared_output_exists"):
        prepare_corpus(**arguments)

    assert (output / "summary.json").read_bytes() == summary_before


def test_prepare_corpus_rejects_a_broken_link_snapshot_when_supported(
    tmp_path,
) -> None:
    output = tmp_path / "prepared"
    try:
        output.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    except OSError:
        pytest.skip("symlink creation is unavailable")

    with pytest.raises(FileExistsError, match="prepared_output_exists"):
        prepare_corpus(
            corpus_id="synthetic-v1",
            content_class="synthetic",
            sources=(_source(),),
            questions=(_question(),),
            output_dir=output,
            license_ref=None,
        )


@pytest.mark.parametrize(
    ("question", "expected_error"),
    [
        (_question(cluster="cluster-b"), "question_section_cluster_mismatch"),
        (_question(split="holdout"), "question_section_split_mismatch"),
    ],
)
def test_prepare_corpus_rejects_question_source_boundary_mismatch(
    tmp_path,
    question,
    expected_error,
) -> None:
    with pytest.raises(ValueError, match=expected_error):
        prepare_corpus(
            corpus_id="synthetic-v1",
            content_class="synthetic",
            sources=(_source(),),
            questions=(question,),
            output_dir=tmp_path / "prepared",
            license_ref=None,
        )


def test_prepare_corpus_removes_stage_after_unsafe_raw_path(tmp_path) -> None:
    output = tmp_path / "prepared"

    with pytest.raises(ValueError, match="unsafe_generated_relative_path"):
        prepare_corpus(
            corpus_id="public-v1",
            content_class="public",
            sources=(
                _source().model_copy(update={"source_type": "law"}),
            ),
            questions=(),
            output_dir=output,
            license_ref="korea-law-open-data",
            source_files={"../outside.json": b"unsafe"},
        )

    assert not output.exists()
    assert not (tmp_path / "outside.json").exists()


def test_prepare_corpus_rejects_credential_fields_in_provenance(tmp_path) -> None:
    output = tmp_path / "prepared"

    with pytest.raises(ValueError, match="credential_field_in_provenance"):
        prepare_corpus(
            corpus_id="synthetic-v1",
            content_class="synthetic",
            sources=(_source(),),
            questions=(_question(),),
            output_dir=output,
            license_ref=None,
            provenance_rows=({"nested": {"oc": "must-not-be-written"}},),
        )

    assert not output.exists()


def test_authored_section_rejects_secret_markers() -> None:
    with pytest.raises(ValueError, match="corpus_text_secret_marker"):
        AuthoredSection(
            section_key="unsafe",
            hierarchy_path=("Security",),
            heading="Credential",
            text="api_key=must-not-be-stored",
        )


def test_public_corpus_requires_a_license_reference(tmp_path) -> None:
    with pytest.raises(ValueError, match="public_corpus_license_required"):
        prepare_corpus(
            corpus_id="public-v1",
            content_class="public",
            sources=(_source().model_copy(update={"source_type": "law"}),),
            questions=(),
            output_dir=tmp_path / "prepared",
            license_ref=None,
        )


@pytest.mark.parametrize("snapshot_id", ("../escape", "nested/path", "C:drive"))
def test_preparation_cli_rejects_unsafe_snapshot_ids(snapshot_id) -> None:
    with pytest.raises(ValueError, match="invalid_snapshot_id"):
        preparation_cli._snapshot_path("enterprise-policy", snapshot_id)


def test_tracked_synthetic_development_package_is_balanced_and_preparable(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    repo = Path(__file__).resolve().parents[3]
    dataset_root = (
        repo
        / "tests/evaluation/datasets/flat_hierarchical/enterprise-policy-v1"
    )
    corpus_path = dataset_root / "corpus.json"
    question_path = dataset_root / "questions.json"
    corpus = load_synthetic_package(corpus_path)
    questions = load_question_blueprints(question_path)

    assert len(corpus.documents) == 12
    assert len(questions.questions) == 20
    assert {document.split for document in corpus.documents} == {"development"}
    cluster_counts = Counter(
        question.sampling_cluster_ref for question in questions.questions
    )
    assert cluster_counts == {
        "leave": 5,
        "expense": 5,
        "security": 5,
        "records": 5,
    }
    assert all(count <= 5 for count in cluster_counts.values())
    assert sum(not question.answerable for question in questions.questions) == 4

    monkeypatch.setattr(preparation_cli, "LOCAL_DATA_ROOT", tmp_path)
    args = type(
        "Args",
        (),
        {
            "corpus": str(corpus_path),
            "questions": str(question_path),
            "snapshot_id": "test-snapshot",
        },
    )()
    preparation_cli._prepare_synthetic(args)

    status = json.loads(capsys.readouterr().out)
    output = tmp_path / "enterprise-policy" / "test-snapshot"
    assert status["status"] == "synthetic_snapshot_prepared"
    assert status["question_count"] == 20
    assert (output / "summary.json").is_file()
