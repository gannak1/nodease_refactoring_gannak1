from __future__ import annotations

import json

import pytest

from tests.evaluation.paired_index_preparer import (
    CanonicalChildVector,
    PreparedIndexManifest,
    prepare_paired_indexes,
    verify_paired_index_manifests,
)


SHA = "sha256:" + "a" * 64
PARENT_SHA = "sha256:" + "b" * 64


def children() -> tuple[CanonicalChildVector, ...]:
    return (
        CanonicalChildVector(
            evidence_ref="ev:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
            source_ref="src_AAAAAAAAAAAAAAAA",
            ordinal=0,
            normalized_text_hash=SHA,
            vector=(0.1, 0.2),
        ),
        CanonicalChildVector(
            evidence_ref="ev:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
            source_ref="src_AAAAAAAAAAAAAAAA",
            ordinal=1,
            normalized_text_hash="sha256:" + "c" * 64,
            vector=(0.3, 0.4),
        ),
    )


def manifest(condition, child_rows=None):
    return PreparedIndexManifest(
        condition=condition,
        source_snapshot_ref="snapshot_safe_v01",
        source_snapshot_hash=SHA,
        segmentation_contract_version="canonical-child-v1",
        embedding_contract_version="embedding-v1",
        parent_builder_fingerprint=PARENT_SHA if condition == "hierarchical" else None,
        children=child_rows or children(),
    )


def test_exact_paired_manifest_passes_without_exposing_vectors_in_summary() -> None:
    summary = verify_paired_index_manifests(manifest("flat"), manifest("hierarchical"))
    dumped = json.dumps(summary.model_dump(mode="json"), sort_keys=True)
    assert summary.child_vector_equality is True
    assert "0.1" not in dumped
    assert "normalized_text_hash" not in dumped
    assert "source_snapshot_hash" not in dumped


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [
        ("vector", "child_vector_mismatch"),
        ("order", "canonical_child_boundary_mismatch"),
        ("boundary", "canonical_child_boundary_mismatch"),
    ],
)
def test_pair_mismatch_is_a_hard_failure(mutation: str, reason: str) -> None:
    rows = list(children())
    if mutation == "vector":
        rows[0] = rows[0].model_copy(update={"vector": (0.1, 0.2000001)})
    elif mutation == "order":
        rows.reverse()
    else:
        rows[0] = rows[0].model_copy(update={"ordinal": 2})
    with pytest.raises(ValueError, match=reason):
        verify_paired_index_manifests(manifest("flat"), manifest("hierarchical", tuple(rows)))


def test_source_snapshot_mismatch_is_rejected() -> None:
    hierarchical = manifest("hierarchical").model_copy(
        update={"source_snapshot_hash": "sha256:" + "d" * 64}
    )
    with pytest.raises(ValueError, match="source_snapshot_mismatch"):
        verify_paired_index_manifests(manifest("flat"), hierarchical)


def test_preparer_passes_same_child_tuple_to_both_builders() -> None:
    class Backend:
        seen = []

        def build_flat(self, child_rows):
            self.seen.append(child_rows)
            return manifest("flat", child_rows)

        def build_hierarchical(self, child_rows):
            self.seen.append(child_rows)
            return manifest("hierarchical", child_rows)

    backend = Backend()
    prepare_paired_indexes(children(), backend=backend)
    assert backend.seen[0] is backend.seen[1]


def test_manifest_rejects_duplicate_ordinal_and_mixed_vector_dimensions() -> None:
    duplicate = list(children())
    duplicate[1] = duplicate[1].model_copy(update={"ordinal": 0})
    with pytest.raises(ValueError, match="duplicate_canonical_child_ordinal"):
        manifest("flat", tuple(duplicate))

    mixed = list(children())
    mixed[1] = mixed[1].model_copy(update={"vector": (0.3,)})
    with pytest.raises(ValueError, match="canonical_child_vector_dimension_mismatch"):
        manifest("flat", tuple(mixed))
