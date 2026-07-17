"""Canonical serialization, artifact sealing, and dataset validation."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
from pathlib import Path
from typing import Any, TypeVar

from pydantic import BaseModel

from tests.evaluation.schemas import (
    BenchmarkQuestion,
    DatasetPackage,
    FrozenProtocol,
    SourceBindingRecord,
    SourceBindingSummary,
)


ModelT = TypeVar("ModelT", bound=BaseModel)


def _json_value(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _json_value(value),
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def atomic_write_json(path: str | Path, value: Any) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(value) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink()


def atomic_create_json(path: str | Path, value: Any) -> None:
    """Atomically publish a new immutable artifact without replacing a file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    encoded = canonical_json_bytes(value) + b"\n"
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
        except FileExistsError:
            raise ValueError("artifact_output_exists") from None
    finally:
        if temporary.exists():
            temporary.unlink()


def write_sealed_artifact(
    path: str | Path,
    artifact_type: str,
    payload: Any,
) -> str:
    if not artifact_type or not artifact_type.replace("_", "").isalnum():
        raise ValueError("invalid_artifact_type")
    payload_value = _json_value(payload)
    artifact = {
        "schema_version": "1",
        "artifact_type": artifact_type,
        "payload_hash": canonical_hash(payload_value),
        "payload": payload_value,
    }
    atomic_create_json(path, artifact)
    return canonical_hash(artifact)


def read_sealed_artifact(
    path: str | Path,
    *,
    expected_type: str,
) -> Any:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "payload_hash",
        "payload",
    }:
        raise ValueError("invalid_sealed_artifact_shape")
    if raw["schema_version"] != "1":
        raise ValueError("unsupported_artifact_schema")
    if raw["artifact_type"] != expected_type:
        raise ValueError("artifact_type_mismatch")
    if raw["payload_hash"] != canonical_hash(raw["payload"]):
        raise ValueError("artifact_hash_mismatch")
    return raw["payload"]


def load_json_model(path: str | Path, model_type: type[ModelT]) -> ModelT:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return model_type.model_validate(raw)


def dataset_content_hashes(
    questions: tuple[BenchmarkQuestion, ...],
) -> tuple[str, str, str]:
    question_rows = [
        {
            "answerable": question.answerable,
            "category": question.category,
            "difficulty": question.difficulty,
            "query": question.query,
            "question_id": question.question_id,
            "safe_display_label": question.safe_display_label,
            "sampling_cluster_ref": question.sampling_cluster_ref,
            "split": question.split,
        }
        for question in questions
    ]
    evidence_rows = [
        {
            "question_id": question.question_id,
            "required_evidence_refs": sorted(question.required_evidence_refs),
        }
        for question in questions
    ]
    cluster_splits = sorted(
        {
            (question.sampling_cluster_ref, question.split)
            for question in questions
        }
    )
    split_rows = [
        {"sampling_cluster_ref": cluster_ref, "split": split}
        for cluster_ref, split in cluster_splits
    ]
    return (
        canonical_hash(question_rows),
        canonical_hash(evidence_rows),
        canonical_hash(split_rows),
    )


def validate_dataset(package: DatasetPackage) -> None:
    questions = package.questions
    manifest = package.manifest
    if len(questions) != manifest.question_count:
        raise ValueError("question_count_mismatch")
    ids = [question.question_id for question in questions]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate_question_id")

    development = sum(question.split == "development" for question in questions)
    holdout = sum(question.split == "holdout" for question in questions)
    if development != manifest.development_count or holdout != manifest.holdout_count:
        raise ValueError("split_count_mismatch")

    cluster_splits: dict[str, str] = {}
    for question in questions:
        existing = cluster_splits.setdefault(
            question.sampling_cluster_ref, question.split
        )
        if existing != question.split:
            raise ValueError("split_cluster_leakage")
    if len(cluster_splits) != manifest.sampling_cluster_count:
        raise ValueError("sampling_cluster_count_mismatch")
    question_hash, evidence_hash, split_hash = dataset_content_hashes(questions)
    if manifest.question_set_hash != question_hash:
        raise ValueError("question_set_hash_mismatch")
    if manifest.expected_evidence_hash != evidence_hash:
        raise ValueError("expected_evidence_hash_mismatch")
    if manifest.split_hash != split_hash:
        raise ValueError("split_hash_mismatch")


def validate_protocol(package: DatasetPackage, protocol: FrozenProtocol) -> None:
    validate_dataset(package)
    manifest = package.manifest
    if manifest.protocol_hash != canonical_hash(protocol):
        raise ValueError("dataset_protocol_hash_mismatch")
    if manifest.split_hash != protocol.split_hash:
        raise ValueError("dataset_protocol_split_hash_mismatch")

    split = "holdout" if protocol.study_phase == "confirmatory_holdout" else "development"
    selected = [question for question in package.questions if question.split == split]
    if len(selected) != protocol.sample_size_plan.planned_n:
        raise ValueError("planned_sample_count_mismatch")
    answerable = sum(question.answerable for question in selected)
    unanswerable = len(selected) - answerable
    if answerable != protocol.sample_size_plan.planned_answerable_n:
        raise ValueError("planned_answerable_count_mismatch")
    if unanswerable != protocol.sample_size_plan.planned_unanswerable_n:
        raise ValueError("planned_unanswerable_count_mismatch")

    cluster_counts: dict[str, int] = {}
    for question in selected:
        cluster_counts[question.sampling_cluster_ref] = (
            cluster_counts.get(question.sampling_cluster_ref, 0) + 1
        )
    if (
        protocol.study_phase == "confirmatory_holdout"
        and len(cluster_counts) < protocol.cluster_plan.minimum_independent_clusters
    ):
        raise ValueError("independent_cluster_floor_not_met")
    if any(
        count > protocol.cluster_plan.maximum_questions_per_cluster
        for count in cluster_counts.values()
    ):
        raise ValueError("questions_per_cluster_cap_exceeded")
    if protocol.study_phase == "confirmatory_holdout":
        unanswerable_clusters = [
            question.sampling_cluster_ref
            for question in selected
            if not question.answerable
        ]
        if len(unanswerable_clusters) != len(set(unanswerable_clusters)):
            raise ValueError("duplicate_unanswerable_safety_cluster")


def artifact_file_hash(path: str | Path) -> str:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return canonical_hash(raw)


def _is_reparse_point(file_stat: os.stat_result) -> bool:
    attributes = getattr(file_stat, "st_file_attributes", 0)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return bool(attributes & reparse_flag)


def _safe_lstat(path: Path) -> os.stat_result:
    try:
        return path.lstat()
    except OSError:
        raise ValueError("source_binding_unavailable") from None


def _safe_resolve(path: Path) -> Path:
    try:
        return path.resolve(strict=True)
    except OSError:
        raise ValueError("source_binding_unavailable") from None


def validate_local_source_bindings(
    root: str | Path,
    records: tuple[SourceBindingRecord, ...],
) -> SourceBindingSummary:
    if not records:
        raise ValueError("empty_source_bindings")
    root_path = _safe_resolve(Path(root))
    if not root_path.is_dir():
        raise ValueError("source_binding_root_not_directory")
    refs = [record.source_ref for record in records]
    paths = [record.relative_path for record in records]
    if len(refs) != len(set(refs)):
        raise ValueError("duplicate_source_binding_ref")
    if len(paths) != len(set(paths)):
        raise ValueError("duplicate_source_binding_path")

    total_size = 0
    for record in records:
        candidate = root_path.joinpath(*record.relative_path.split("/"))
        current = root_path
        for part in record.relative_path.split("/"):
            current = current / part
            current_stat = _safe_lstat(current)
            if current.is_symlink() or _is_reparse_point(current_stat):
                raise ValueError("source_binding_link_forbidden")

        resolved = _safe_resolve(candidate)
        try:
            resolved.relative_to(root_path)
        except ValueError as exc:
            raise ValueError("source_binding_root_escape") from exc
        before = _safe_lstat(candidate)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("source_binding_not_regular_file")
        if before.st_nlink != 1:
            raise ValueError("source_binding_hardlink_forbidden")

        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(candidate, flags)
        except OSError:
            raise ValueError("source_binding_open_failed") from None
        digest = hashlib.sha256()
        bytes_read = 0
        try:
            try:
                opened = os.fstat(descriptor)
            except OSError:
                raise ValueError("source_binding_read_failed") from None
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError("source_binding_changed_during_open")
            while True:
                try:
                    chunk = os.read(descriptor, 1024 * 1024)
                except OSError:
                    raise ValueError("source_binding_read_failed") from None
                if not chunk:
                    break
                digest.update(chunk)
                bytes_read += len(chunk)
        finally:
            os.close(descriptor)

        after = _safe_lstat(candidate)
        before_fingerprint = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
        after_fingerprint = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
        if before_fingerprint != after_fingerprint:
            raise ValueError("source_binding_changed_during_read")
        if bytes_read != record.size_bytes or bytes_read != after.st_size:
            raise ValueError("source_binding_size_mismatch")
        if "sha256:" + digest.hexdigest() != record.content_hash:
            raise ValueError("source_binding_hash_mismatch")
        total_size += bytes_read

    return SourceBindingSummary(
        binding_count=len(records),
        total_size_bytes=total_size,
        root_boundary_verified=True,
        content_hashes_verified=True,
        verification_version="local_source_binding_v1",
    )
