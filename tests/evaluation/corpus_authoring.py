"""Local-only corpus preparation for the Flat/Hierarchical RAG benchmark."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from collections.abc import Mapping, Sequence
from pathlib import Path, PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from tests.evaluation.evidence_refs import OpaqueEvidenceRegistry
from tests.evaluation.protocol import canonical_hash
from tests.evaluation.schemas import BenchmarkQuestion, SourceBindingRecord


SAFE_ID_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$"
SOURCE_REF_PATTERN = r"^src_[A-Za-z0-9_-]{16,64}$"
SECTION_REF_PATTERN = re.compile(
    rf"^(?P<source>{SOURCE_REF_PATTERN[1:-1]}):(?P<section>{SAFE_ID_PATTERN[1:-1]})$"
)
SECRET_MARKER = re.compile(
    r"(?i)(?:\bsk-[a-z0-9]{8,}|\b(?:api[_-]?key|authorization|token)\s*[:=])"
)
FORBIDDEN_PROVENANCE_KEYS = {
    "api_key",
    "authorization",
    "credential",
    "nodease_eval_law_oc",
    "oc",
    "secret",
    "token",
}
ALLOWED_PROVENANCE_KEYS = {
    "analysis_role",
    "captured_order",
    "created_from",
    "effective_date",
    "official_resource_id",
    "official_resource_master_id",
    "source_ref",
    "source_relative_path",
    "source_type",
    "status",
    "title",
    "version_role",
}


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)


def _validate_human_text(value: str, *, allow_newlines: bool = False) -> str:
    normalized = unicodedata.normalize("NFC", value).strip()
    if not normalized:
        raise ValueError("empty_corpus_text")
    allowed_controls = {"\n", "\t"} if allow_newlines else set()
    if any(
        (ord(character) < 32 or ord(character) == 127)
        and character not in allowed_controls
        for character in normalized
    ):
        raise ValueError("corpus_text_control_character")
    if SECRET_MARKER.search(normalized):
        raise ValueError("corpus_text_secret_marker")
    return normalized


class AuthoredSection(_StrictModel):
    section_key: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    hierarchy_path: tuple[str, ...] = Field(min_length=1, max_length=12)
    heading: str = Field(min_length=1, max_length=300)
    text: str = Field(min_length=1, max_length=200_000)

    @field_validator("heading")
    @classmethod
    def validate_heading(cls, value: str) -> str:
        return _validate_human_text(value)

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        return _validate_human_text(value, allow_newlines=True)

    @field_validator("hierarchy_path")
    @classmethod
    def validate_path(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(_validate_human_text(value) for value in values)


class AuthoredSource(_StrictModel):
    source_ref: str = Field(pattern=SOURCE_REF_PATTERN)
    sampling_cluster_ref: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    split: Literal["development", "holdout"]
    source_type: Literal["law", "administrative_rule", "precedent", "synthetic"]
    analysis_role: Literal["primary", "exploratory"] = "primary"
    version_role: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    title: str = Field(min_length=1, max_length=500)
    sections: tuple[AuthoredSection, ...] = Field(min_length=1, max_length=10_000)

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: str) -> str:
        return _validate_human_text(value)

    @model_validator(mode="after")
    def validate_section_keys(self) -> "AuthoredSource":
        keys = [section.section_key for section in self.sections]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate_authored_section_key")
        return self


class SyntheticCorpusPackage(_StrictModel):
    schema_version: Literal["1"]
    corpus_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    documents: tuple[AuthoredSource, ...] = Field(min_length=1, max_length=1_000)

    @model_validator(mode="after")
    def validate_documents(self) -> "SyntheticCorpusPackage":
        if any(document.source_type != "synthetic" for document in self.documents):
            raise ValueError("synthetic_package_contains_non_synthetic_source")
        refs = [document.source_ref for document in self.documents]
        if len(refs) != len(set(refs)):
            raise ValueError("duplicate_source_ref")
        return self


class QuestionBlueprint(_StrictModel):
    question_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    sampling_cluster_ref: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    split: Literal["development", "holdout"]
    category: Literal[
        "single_fact",
        "section_context",
        "ambiguous_context",
        "multi_evidence",
        "distractor",
        "boundary",
        "unanswerable",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    answerable: bool
    query: str = Field(min_length=1, max_length=1_000)
    safe_display_label: str | None = Field(default=None, min_length=1, max_length=120)
    required_section_refs: tuple[str, ...] = ()

    @field_validator("query", "safe_display_label")
    @classmethod
    def validate_question_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return _validate_human_text(value)

    @field_validator("required_section_refs")
    @classmethod
    def validate_required_sections(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("duplicate_required_section_ref")
        if any(SECTION_REF_PATTERN.fullmatch(value) is None for value in values):
            raise ValueError("invalid_required_section_ref")
        return values

    @model_validator(mode="after")
    def validate_answerability(self) -> "QuestionBlueprint":
        if self.answerable and not self.required_section_refs:
            raise ValueError("answerable_question_requires_section")
        if not self.answerable and self.required_section_refs:
            raise ValueError("unanswerable_question_has_section")
        if self.answerable == (self.category == "unanswerable"):
            raise ValueError("question_category_answerability_mismatch")
        return self


class QuestionBlueprintPackage(_StrictModel):
    schema_version: Literal["1"]
    corpus_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    questions: tuple[QuestionBlueprint, ...] = Field(max_length=100_000)

    @model_validator(mode="after")
    def validate_question_ids(self) -> "QuestionBlueprintPackage":
        ids = [question.question_id for question in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_question_id")
        return self


class PreparedCorpusSummary(_StrictModel):
    schema_version: Literal["prepared_corpus_v1"]
    review_state: Literal["draft_unfrozen"]
    corpus_id: str = Field(pattern=SAFE_ID_PATTERN, max_length=64)
    content_class: Literal["synthetic", "public"]
    source_count: int = Field(ge=1)
    sampling_cluster_count: int = Field(ge=1)
    canonical_child_count: int = Field(ge=1)
    question_count: int = Field(ge=0)
    source_manifest_hash: str
    canonical_children_hash: str
    question_draft_hash: str


def load_synthetic_package(path: str | Path) -> SyntheticCorpusPackage:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return SyntheticCorpusPackage.model_validate(raw)


def load_question_blueprints(path: str | Path) -> QuestionBlueprintPackage:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return QuestionBlueprintPackage.model_validate(raw)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _jsonl_text(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(
        json.dumps(
            row,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
        for row in rows
    )


def _safe_relative_path(value: str) -> PurePosixPath:
    if "\\" in value or ":" in value:
        raise ValueError("unsafe_generated_relative_path")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("unsafe_generated_relative_path")
    return path


def _write_text(root: Path, relative_path: str, value: str) -> None:
    relative = _safe_relative_path(relative_path)
    target = root.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(value, encoding="utf-8", newline="\n")


def _write_bytes(root: Path, relative_path: str, value: bytes) -> None:
    relative = _safe_relative_path(relative_path)
    target = root.joinpath(*relative.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(value)


def _reject_forbidden_provenance(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            if str(key).strip().lower() in FORBIDDEN_PROVENANCE_KEYS:
                raise ValueError("credential_field_in_provenance")
            _reject_forbidden_provenance(nested)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for nested in value:
            _reject_forbidden_provenance(nested)


def _validate_provenance(rows: Sequence[Mapping[str, Any]]) -> None:
    _reject_forbidden_provenance(rows)
    for row in rows:
        if any(str(key) not in ALLOWED_PROVENANCE_KEYS for key in row):
            raise ValueError("provenance_field_not_allowed")
        if any(
            isinstance(value, Mapping)
            or (
                isinstance(value, Sequence)
                and not isinstance(value, (str, bytes, bytearray))
            )
            for value in row.values()
        ):
            raise ValueError("provenance_value_not_scalar")


def _render_source(
    source: AuthoredSource,
    registry: OpaqueEvidenceRegistry,
) -> tuple[str, list[dict[str, Any]], list[dict[str, Any]]]:
    blocks: list[str] = []
    canonical_rows: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    cursor = 0
    for ordinal, section in enumerate(source.sections):
        block = f"{section.heading}\n{section.text}"
        if blocks:
            cursor += 2
        start = cursor
        end = start + len(block)
        internal_key = f"{source.source_ref}:{section.section_key}"
        evidence_ref = registry.issue(internal_key)
        canonical_rows.append(
            {
                "content_hash": _sha256_bytes(block.encode("utf-8")),
                "evidence_ref": evidence_ref,
                "normalized_end": end,
                "normalized_start": start,
                "ordinal": ordinal,
                "safe_source_ref": source.source_ref,
                "segmentation_version": "section_atomic_v1",
            }
        )
        index_rows.append(
            {
                "content": block,
                "evidence_ref": evidence_ref,
                "hierarchy_path": list(section.hierarchy_path),
                "safe_source_ref": source.source_ref,
                "section_key": section.section_key,
            }
        )
        blocks.append(block)
        cursor = end
    return "\n\n".join(blocks) + "\n", canonical_rows, index_rows


def prepare_corpus(
    *,
    corpus_id: str,
    content_class: Literal["synthetic", "public"],
    sources: Sequence[AuthoredSource],
    questions: Sequence[QuestionBlueprint],
    output_dir: str | Path,
    license_ref: str | None,
    source_files: Mapping[str, bytes] | None = None,
    provenance_rows: Sequence[Mapping[str, Any]] = (),
) -> PreparedCorpusSummary:
    if not re.fullmatch(SAFE_ID_PATTERN, corpus_id):
        raise ValueError("invalid_corpus_id")
    if content_class == "public" and not license_ref:
        raise ValueError("public_corpus_license_required")
    if license_ref is not None and not re.fullmatch(SAFE_ID_PATTERN, license_ref):
        raise ValueError("invalid_license_ref")
    if not sources:
        raise ValueError("empty_corpus")

    source_refs = [source.source_ref for source in sources]
    if len(source_refs) != len(set(source_refs)):
        raise ValueError("duplicate_source_ref")
    section_index = {
        f"{source.source_ref}:{section.section_key}": source
        for source in sources
        for section in source.sections
    }
    question_ids = [question.question_id for question in questions]
    if len(question_ids) != len(set(question_ids)):
        raise ValueError("duplicate_question_id")
    for question in questions:
        for section_ref in question.required_section_refs:
            source = section_index.get(section_ref)
            if source is None:
                raise ValueError("question_section_not_found")
            if source.sampling_cluster_ref != question.sampling_cluster_ref:
                raise ValueError("question_section_cluster_mismatch")
            if source.split != question.split:
                raise ValueError("question_section_split_mismatch")

    _validate_provenance(provenance_rows)
    output = Path(output_dir)
    if os.path.lexists(output):
        raise FileExistsError("prepared_output_exists")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}.", dir=output.parent))
    registry = OpaqueEvidenceRegistry()
    canonical_rows: list[dict[str, Any]] = []
    index_rows: list[dict[str, Any]] = []
    source_records: list[dict[str, Any]] = []
    binding_rows: list[dict[str, Any]] = []
    try:
        for source in sorted(sources, key=lambda item: item.source_ref):
            normalized, source_children, source_index_rows = _render_source(
                source, registry
            )
            normalized_bytes = normalized.encode("utf-8")
            relative_path = f"normalized/{source.source_ref}.txt"
            _write_bytes(stage, relative_path, normalized_bytes)
            source_child_hash = canonical_hash(source_children)
            safe_metadata = {
                "analysis_role": source.analysis_role,
                "sampling_cluster_ref": source.sampling_cluster_ref,
                "source_ref": source.source_ref,
                "source_type": source.source_type,
                "split": source.split,
                "version_role": source.version_role,
            }
            source_records.append(
                {
                    "canonical_child_count": len(source_children),
                    "canonical_child_hash": source_child_hash,
                    "content_class": content_class,
                    "content_hash": _sha256_bytes(normalized_bytes),
                    "metadata_hash": canonical_hash(safe_metadata),
                    "safe_source_ref": source.source_ref,
                    "section_count": len(source.sections),
                }
            )
            binding = SourceBindingRecord(
                source_ref=source.source_ref,
                relative_path=relative_path,
                content_hash=_sha256_bytes(normalized_bytes),
                size_bytes=len(normalized_bytes),
            )
            binding_rows.append(binding.model_dump(mode="json"))
            canonical_rows.extend(source_children)
            index_rows.extend(source_index_rows)

        question_rows: list[dict[str, Any]] = []
        for blueprint in sorted(questions, key=lambda item: item.question_id):
            required_refs = tuple(
                registry.reference_for(section_ref)
                for section_ref in blueprint.required_section_refs
            )
            question = BenchmarkQuestion(
                question_id=blueprint.question_id,
                sampling_cluster_ref=blueprint.sampling_cluster_ref,
                split=blueprint.split,
                category=blueprint.category,
                difficulty=blueprint.difficulty,
                answerable=blueprint.answerable,
                query=blueprint.query,
                safe_display_label=blueprint.safe_display_label,
                required_evidence_refs=required_refs,
            )
            question_rows.append(question.model_dump(mode="json"))

        source_manifest = {
            "content_class": content_class,
            "corpus_id": corpus_id,
            "license_ref": license_ref,
            "records": source_records,
            "schema_version": "source_manifest_v1",
        }
        summary = PreparedCorpusSummary(
            schema_version="prepared_corpus_v1",
            review_state="draft_unfrozen",
            corpus_id=corpus_id,
            content_class=content_class,
            source_count=len(source_records),
            sampling_cluster_count=len(
                {source.sampling_cluster_ref for source in sources}
            ),
            canonical_child_count=len(canonical_rows),
            question_count=len(question_rows),
            source_manifest_hash=canonical_hash(source_manifest),
            canonical_children_hash=canonical_hash(canonical_rows),
            question_draft_hash=canonical_hash(question_rows),
        )
        _write_text(stage, "source_manifest.json", _json_text(source_manifest))
        _write_text(stage, "source_bindings.json", _json_text(binding_rows))
        _write_text(stage, "canonical_children.jsonl", _jsonl_text(canonical_rows))
        _write_text(stage, "index_input.jsonl", _jsonl_text(index_rows))
        _write_text(stage, "question_draft.jsonl", _jsonl_text(question_rows))
        _write_text(
            stage,
            "provenance.json",
            _json_text(
                {
                    "records": list(provenance_rows),
                    "schema_version": "local_provenance_v1",
                }
            ),
        )
        _write_text(stage, "summary.json", _json_text(summary.model_dump(mode="json")))
        for relative_path, payload in sorted((source_files or {}).items()):
            _write_bytes(stage, relative_path, payload)
        if os.path.lexists(output):
            raise FileExistsError("prepared_output_exists")
        stage.rename(output)
        return summary
    except Exception:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def prepare_synthetic_package(
    *,
    corpus: SyntheticCorpusPackage,
    question_blueprints: QuestionBlueprintPackage,
    output_dir: str | Path,
) -> PreparedCorpusSummary:
    if corpus.corpus_id != question_blueprints.corpus_id:
        raise ValueError("corpus_question_package_mismatch")
    provenance = [
        {
            "created_from": "project_authored_synthetic",
            "source_ref": source.source_ref,
            "title": source.title,
            "version_role": source.version_role,
        }
        for source in corpus.documents
    ]
    return prepare_corpus(
        corpus_id=corpus.corpus_id,
        content_class="synthetic",
        sources=corpus.documents,
        questions=question_blueprints.questions,
        output_dir=output_dir,
        license_ref=None,
        provenance_rows=provenance,
    )
