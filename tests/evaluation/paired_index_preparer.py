"""Controlled paired-index preparation boundary and equality verification."""

from __future__ import annotations

import math
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tests.evaluation.schemas import OPAQUE_EVIDENCE_PATTERN, SHA256_PATTERN


class _StrictModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )


class CanonicalChildVector(_StrictModel):
    evidence_ref: str = Field(pattern=OPAQUE_EVIDENCE_PATTERN)
    source_ref: str = Field(pattern=r"^src_[A-Za-z0-9_-]{16,64}$")
    ordinal: int = Field(ge=0)
    normalized_text_hash: str = Field(pattern=SHA256_PATTERN)
    vector: tuple[float, ...] = Field(min_length=1)

    @field_validator("vector")
    @classmethod
    def finite_vector(cls, values: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(value) for value in values):
            raise ValueError("non_finite_child_vector")
        return values


class PreparedIndexManifest(_StrictModel):
    schema_version: Literal["1"] = "1"
    condition: Literal["flat", "hierarchical"]
    source_snapshot_ref: str = Field(pattern=r"^snapshot_[A-Za-z0-9_-]{8,64}$")
    source_snapshot_hash: str = Field(pattern=SHA256_PATTERN)
    segmentation_contract_version: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
    )
    embedding_contract_version: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
    )
    parent_builder_fingerprint: str | None = Field(default=None, pattern=SHA256_PATTERN)
    children: tuple[CanonicalChildVector, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_children_and_parent(self) -> "PreparedIndexManifest":
        refs = [child.evidence_ref for child in self.children]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_canonical_child_ref")
        source_ordinals = [(child.source_ref, child.ordinal) for child in self.children]
        if len(source_ordinals) != len(set(source_ordinals)):
            raise ValueError("duplicate_canonical_child_ordinal")
        dimension = len(self.children[0].vector)
        if any(len(child.vector) != dimension for child in self.children):
            raise ValueError("canonical_child_vector_dimension_mismatch")
        if self.condition == "hierarchical" and self.parent_builder_fingerprint is None:
            raise ValueError("parent_builder_fingerprint_required")
        if self.condition == "flat" and self.parent_builder_fingerprint is not None:
            raise ValueError("flat_parent_builder_fingerprint_forbidden")
        return self


class IndexEqualitySummary(_StrictModel):
    source_equality_verified: Literal[True]
    child_boundary_equality_verified: Literal[True]
    child_vector_equality: Literal[True]
    segmentation_contract_version: str
    vector_equality_check_version: Literal["exact_float_sequence_v1"]
    parent_builder_fingerprint: str = Field(pattern=SHA256_PATTERN)
    child_count: int = Field(ge=1)
    vector_dimension: int = Field(ge=1)


class PairedIndexBackend(Protocol):
    def build_flat(
        self, children: tuple[CanonicalChildVector, ...]
    ) -> PreparedIndexManifest: ...

    def build_hierarchical(
        self, children: tuple[CanonicalChildVector, ...]
    ) -> PreparedIndexManifest: ...


def verify_paired_index_manifests(
    flat: PreparedIndexManifest,
    hierarchical: PreparedIndexManifest,
) -> IndexEqualitySummary:
    if flat.condition != "flat" or hierarchical.condition != "hierarchical":
        raise ValueError("paired_index_condition_mismatch")
    if (
        flat.source_snapshot_ref != hierarchical.source_snapshot_ref
        or flat.source_snapshot_hash != hierarchical.source_snapshot_hash
    ):
        raise ValueError("source_snapshot_mismatch")
    if flat.segmentation_contract_version != hierarchical.segmentation_contract_version:
        raise ValueError("segmentation_contract_mismatch")
    if flat.embedding_contract_version != hierarchical.embedding_contract_version:
        raise ValueError("embedding_contract_mismatch")
    if not flat.children or len(flat.children) != len(hierarchical.children):
        raise ValueError("canonical_child_count_mismatch")

    expected_dimension = len(flat.children[0].vector)
    for flat_child, hierarchical_child in zip(flat.children, hierarchical.children):
        flat_boundary = (
            flat_child.evidence_ref,
            flat_child.source_ref,
            flat_child.ordinal,
            flat_child.normalized_text_hash,
        )
        hierarchical_boundary = (
            hierarchical_child.evidence_ref,
            hierarchical_child.source_ref,
            hierarchical_child.ordinal,
            hierarchical_child.normalized_text_hash,
        )
        if flat_boundary != hierarchical_boundary:
            raise ValueError("canonical_child_boundary_mismatch")
        if len(flat_child.vector) != expected_dimension or len(
            hierarchical_child.vector
        ) != expected_dimension:
            raise ValueError("child_vector_dimension_mismatch")
        if flat_child.vector != hierarchical_child.vector:
            raise ValueError("child_vector_mismatch")

    return IndexEqualitySummary(
        source_equality_verified=True,
        child_boundary_equality_verified=True,
        child_vector_equality=True,
        segmentation_contract_version=flat.segmentation_contract_version,
        vector_equality_check_version="exact_float_sequence_v1",
        parent_builder_fingerprint=hierarchical.parent_builder_fingerprint,
        child_count=len(flat.children),
        vector_dimension=expected_dimension,
    )


def prepare_paired_indexes(
    children: tuple[CanonicalChildVector, ...],
    *,
    backend: PairedIndexBackend,
) -> tuple[PreparedIndexManifest, PreparedIndexManifest, IndexEqualitySummary]:
    """Pass the exact same immutable child/vector sequence to both builders."""
    if not children:
        raise ValueError("empty_canonical_children")
    flat = backend.build_flat(children)
    hierarchical = backend.build_hierarchical(children)
    return flat, hierarchical, verify_paired_index_manifests(flat, hierarchical)
