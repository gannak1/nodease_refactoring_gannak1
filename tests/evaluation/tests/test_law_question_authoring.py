from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

from tests.evaluation.corpus_authoring import PreparedCorpusSummary
from tests.evaluation.law_open_data import LawSourceCatalog
from tests.evaluation.law_question_authoring import (
    PILOT_CATEGORY_TARGETS,
    _SectionCandidate,
    _map_benchmark_questions,
    generate_law_development_questions,
    prepare_law_question_draft,
)
from tests.evaluation.protocol import canonical_hash


CLUSTERS = (
    "electronic-documents",
    "labor",
    "privacy",
    "procedure",
    "records",
    "safety",
)


def _fixture_catalog(
    catalog_id: str = "law-question-test-v1",
) -> LawSourceCatalog:
    entries = []
    for cluster in CLUSTERS:
        entries.extend(
            (
                {
                    "source_key": f"{cluster}_law",
                    "sampling_cluster_ref": cluster,
                    "split": "development",
                    "source_type": "law",
                    "analysis_role": "primary",
                    "exact_title": f"{cluster} 법률",
                    "history_versions": 1,
                },
                {
                    "source_key": f"{cluster}_decree",
                    "sampling_cluster_ref": cluster,
                    "split": "development",
                    "source_type": "law",
                    "analysis_role": "primary",
                    "exact_title": f"{cluster} 시행령",
                    "history_versions": 0,
                },
            )
        )
    return LawSourceCatalog.model_validate(
        {
            "schema_version": "1",
            "catalog_id": catalog_id,
            "license_ref": "law-test-license",
            "entries": entries,
        }
    )


def _fixture_candidates() -> list[_SectionCandidate]:
    candidates: list[_SectionCandidate] = []
    evidence_index = 1
    for cluster in CLUSTERS:
        for source_kind, version_role in (
            ("law", "current"),
            ("law", "history_01"),
            ("decree", "current"),
        ):
            source_key = f"{cluster}_{source_kind}"
            source_ref = f"src_{source_key}_{version_role}"
            title_suffix = "법률" if source_kind == "law" else "시행령"
            for ordinal in range(48):
                article = ordinal // 4
                paragraph = ordinal % 4
                candidates.append(
                    _SectionCandidate(
                        source_ref=source_ref,
                        source_key=source_key,
                        sampling_cluster_ref=cluster,
                        title=f"{cluster} {title_suffix}",
                        version_role=version_role,
                        analysis_role="primary",
                        section_key=(
                            f"article-{article:04d}-paragraph-{paragraph:03d}"
                        ),
                        evidence_ref=f"ev:{evidence_index:032x}",
                        ordinal=ordinal,
                        hierarchy_path=(
                            f"제{article + 1}장 테스트",
                            f"제{article + 1}조 공통 주제 {article}",
                            f"항목 {paragraph + 1}",
                        ),
                        content=(
                            f"제{article + 1}조 공통 주제 {article} 항목 {paragraph + 1}. "
                            "공개 법률 평가를 위한 충분한 테스트 내용으로 의무와 절차를 규정한다."
                        ),
                    )
                )
                evidence_index += 1
    return candidates


def _write_fixture_snapshot(
    root: Path,
    candidates: list[_SectionCandidate],
) -> None:
    root.mkdir(parents=True)
    canonical_rows = [
        {
            "content_hash": (
                "sha256:"
                + hashlib.sha256(candidate.content.encode("utf-8")).hexdigest()
            ),
            "evidence_ref": candidate.evidence_ref,
            "normalized_end": index + 1,
            "normalized_start": index,
            "ordinal": candidate.ordinal,
            "safe_source_ref": candidate.source_ref,
            "segmentation_version": "section_atomic_v1",
        }
        for index, candidate in enumerate(candidates)
    ]
    index_rows = [
        {
            "content": candidate.content,
            "evidence_ref": candidate.evidence_ref,
            "hierarchy_path": list(candidate.hierarchy_path),
            "safe_source_ref": candidate.source_ref,
            "section_key": candidate.section_key,
        }
        for candidate in candidates
    ]
    source_refs = sorted({candidate.source_ref for candidate in candidates})
    source_manifest = {
        "content_class": "public",
        "corpus_id": "law-question-test-v1",
        "license_ref": "law-test-license",
        "records": [{"safe_source_ref": source_ref} for source_ref in source_refs],
        "schema_version": "source_manifest_v1",
    }
    provenance_records = []
    for source_ref in source_refs:
        candidate = next(item for item in candidates if item.source_ref == source_ref)
        provenance_records.append(
            {
                "source_ref": source_ref,
                "title": candidate.title,
                "version_role": candidate.version_role,
            }
        )
    summary = PreparedCorpusSummary(
        schema_version="prepared_corpus_v1",
        review_state="draft_unfrozen",
        corpus_id="law-question-test-v1",
        content_class="public",
        source_count=len(source_refs),
        sampling_cluster_count=len(CLUSTERS),
        canonical_child_count=len(canonical_rows),
        question_count=0,
        source_manifest_hash=canonical_hash(source_manifest),
        canonical_children_hash=canonical_hash(canonical_rows),
        question_draft_hash=canonical_hash([]),
    )

    def write_json(name: str, value) -> None:
        (root / name).write_text(
            json.dumps(value, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )

    def write_jsonl(name: str, rows) -> None:
        (root / name).write_text(
            "".join(
                json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n"
                for row in rows
            ),
            encoding="utf-8",
        )

    write_json("summary.json", summary.model_dump(mode="json"))
    write_json("source_manifest.json", source_manifest)
    write_json("provenance.json", {"records": provenance_records})
    write_jsonl("canonical_children.jsonl", canonical_rows)
    write_jsonl("index_input.jsonl", index_rows)


def test_generated_law_questions_meet_development_distribution() -> None:
    candidates = _fixture_candidates()

    package = generate_law_development_questions(
        candidates,
        corpus_id="law-question-test-v1",
    )
    benchmark, worksheet = _map_benchmark_questions(package, candidates)

    assert len(benchmark) == 100
    assert len({question.question_id for question in benchmark}) == 100
    assert len({question.query for question in benchmark}) == 100
    assert Counter(question.category for question in benchmark) == Counter(
        PILOT_CATEGORY_TARGETS
    )
    assert max(Counter(question.sampling_cluster_ref for question in benchmark).values()) <= 17
    assert sum(question.answerable for question in benchmark) == 90
    assert all(
        len(question.required_evidence_refs) == 2
        for question in benchmark
        if question.category in {"multi_evidence", "boundary"}
    )
    assert all(
        not question.required_evidence_refs
        for question in benchmark
        if question.category == "unanswerable"
    )
    assert all(row["semantic_review"] == "pending" for row in worksheet)


def test_question_draft_is_create_only_and_not_quality_ready(tmp_path: Path) -> None:
    candidates = _fixture_candidates()
    snapshot = tmp_path / "snapshot-v1"
    output = tmp_path / "draft"
    _write_fixture_snapshot(snapshot, candidates)

    summary = prepare_law_question_draft(
        base_snapshot_dir=snapshot,
        base_snapshot_id="snapshot-v1",
        catalog=_fixture_catalog(),
        bundle_id="question-draft-v1",
        output_dir=output,
    )

    assert summary.structural_pilot_ready is True
    assert summary.quality_pilot_ready is False
    assert summary.blockers == (
        "human_semantic_review_pending",
        "paired_index_binding_pending",
        "development_protocol_pending",
    )
    assert len((output / "question_draft.jsonl").read_text(encoding="utf-8").splitlines()) == 100
    with pytest.raises(FileExistsError, match="law_question_draft_output_exists"):
        prepare_law_question_draft(
            base_snapshot_dir=snapshot,
            base_snapshot_id="snapshot-v1",
            catalog=_fixture_catalog(),
            bundle_id="question-draft-v1",
            output_dir=output,
        )


def test_question_draft_rejects_tampered_snapshot_hash(tmp_path: Path) -> None:
    candidates = _fixture_candidates()
    snapshot = tmp_path / "snapshot-v1"
    _write_fixture_snapshot(snapshot, candidates)
    summary_path = snapshot / "summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    summary["canonical_children_hash"] = f"sha256:{'0' * 64}"
    summary_path.write_text(json.dumps(summary), encoding="utf-8")

    with pytest.raises(ValueError, match="law_question_canonical_children_hash_mismatch"):
        prepare_law_question_draft(
            base_snapshot_dir=snapshot,
            base_snapshot_id="snapshot-v1",
            catalog=_fixture_catalog(),
            bundle_id="question-draft-v1",
            output_dir=tmp_path / "draft",
        )


def test_question_draft_rejects_tampered_index_content(tmp_path: Path) -> None:
    candidates = _fixture_candidates()
    snapshot = tmp_path / "snapshot-v1"
    _write_fixture_snapshot(snapshot, candidates)
    index_path = snapshot / "index_input.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    rows[0]["content"] = f"{rows[0]['content']} tampered"
    index_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="law_question_index_content_hash_mismatch"):
        prepare_law_question_draft(
            base_snapshot_dir=snapshot,
            base_snapshot_id="snapshot-v1",
            catalog=_fixture_catalog(),
            bundle_id="question-draft-v1",
            output_dir=tmp_path / "draft",
        )


def test_question_draft_rejects_duplicate_index_evidence_ref(tmp_path: Path) -> None:
    candidates = _fixture_candidates()
    snapshot = tmp_path / "snapshot-v1"
    _write_fixture_snapshot(snapshot, candidates)
    index_path = snapshot / "index_input.jsonl"
    rows = [json.loads(line) for line in index_path.read_text(encoding="utf-8").splitlines()]
    rows[1]["evidence_ref"] = rows[0]["evidence_ref"]
    index_path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="law_question_duplicate_index_evidence_ref"):
        prepare_law_question_draft(
            base_snapshot_dir=snapshot,
            base_snapshot_id="snapshot-v1",
            catalog=_fixture_catalog(),
            bundle_id="question-draft-v1",
            output_dir=tmp_path / "draft",
        )


@pytest.mark.parametrize(
    ("snapshot_name", "base_snapshot_id", "catalog_id", "reason"),
    (
        (
            "snapshot-v1",
            "different-snapshot",
            "law-question-test-v1",
            "law_question_base_snapshot_id_mismatch",
        ),
        (
            "snapshot-v1",
            "snapshot-v1",
            "different-catalog",
            "law_question_catalog_id_mismatch",
        ),
    ),
)
def test_question_draft_rejects_lineage_label_mismatch(
    tmp_path: Path,
    snapshot_name: str,
    base_snapshot_id: str,
    catalog_id: str,
    reason: str,
) -> None:
    candidates = _fixture_candidates()
    snapshot = tmp_path / snapshot_name
    _write_fixture_snapshot(snapshot, candidates)

    with pytest.raises(ValueError, match=reason):
        prepare_law_question_draft(
            base_snapshot_dir=snapshot,
            base_snapshot_id=base_snapshot_id,
            catalog=_fixture_catalog(catalog_id),
            bundle_id="question-draft-v1",
            output_dir=tmp_path / "draft",
        )
