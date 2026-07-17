from __future__ import annotations

import hashlib
import os

import pytest
from pydantic import ValidationError

from tests.evaluation.protocol import validate_local_source_bindings
from tests.evaluation.schemas import SourceBindingRecord


def record(path, source_ref="src_AAAAAAAAAAAAAAAA"):
    data = path.read_bytes()
    return SourceBindingRecord(
        source_ref=source_ref,
        relative_path=path.name,
        content_hash="sha256:" + hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
    )


def test_source_binding_validates_hash_size_and_returns_only_summary(tmp_path) -> None:
    source = tmp_path / "safe.txt"
    source.write_text("approved synthetic content", encoding="utf-8")
    summary = validate_local_source_bindings(tmp_path, (record(source),))
    assert summary.binding_count == 1
    assert summary.content_hashes_verified is True
    assert "content_hash" not in summary.model_dump()


def test_source_binding_rejects_hash_and_size_mismatch(tmp_path) -> None:
    source = tmp_path / "safe.txt"
    source.write_text("approved synthetic content", encoding="utf-8")
    source_record = record(source)
    with pytest.raises(ValueError, match="source_binding_hash_mismatch"):
        validate_local_source_bindings(
            tmp_path,
            (source_record.model_copy(update={"content_hash": "sha256:" + "a" * 64}),),
        )
    with pytest.raises(ValueError, match="source_binding_size_mismatch"):
        validate_local_source_bindings(
            tmp_path,
            (source_record.model_copy(update={"size_bytes": source_record.size_bytes + 1}),),
        )


def test_source_binding_rejects_path_traversal_and_duplicate_mapping(tmp_path) -> None:
    source = tmp_path / "safe.txt"
    source.write_text("safe", encoding="utf-8")
    with pytest.raises(ValidationError, match="unsafe_source_relative_path"):
        SourceBindingRecord(
            source_ref="src_AAAAAAAAAAAAAAAA",
            relative_path="../outside.txt",
            content_hash="sha256:" + "a" * 64,
            size_bytes=1,
        )
    source_record = record(source)
    with pytest.raises(ValueError, match="duplicate_source_binding_path"):
        validate_local_source_bindings(
            tmp_path,
            (
                source_record,
                source_record.model_copy(update={"source_ref": "src_BBBBBBBBBBBBBBBB"}),
            ),
        )


def test_source_binding_rejects_hardlinks(tmp_path) -> None:
    source = tmp_path / "safe.txt"
    source.write_text("safe", encoding="utf-8")
    os.link(source, tmp_path / "second-link.txt")
    with pytest.raises(ValueError, match="source_binding_hardlink_forbidden"):
        validate_local_source_bindings(tmp_path, (record(source),))


def test_source_binding_rejects_symlink_when_supported(tmp_path) -> None:
    source = tmp_path / "safe.txt"
    source.write_text("safe", encoding="utf-8")
    link = tmp_path / "linked.txt"
    try:
        link.symlink_to(source)
    except OSError:
        pytest.skip("symlink creation is unavailable")
    with pytest.raises(ValueError, match="source_binding_link_forbidden"):
        validate_local_source_bindings(tmp_path, (record(link),))


def test_missing_binding_error_does_not_disclose_local_path(tmp_path) -> None:
    binding = SourceBindingRecord(
        source_ref="src_AAAAAAAAAAAAAAAA",
        relative_path="RAW_PATH_SENTINEL.txt",
        content_hash="sha256:" + "a" * 64,
        size_bytes=1,
    )
    with pytest.raises(ValueError, match="source_binding_unavailable") as captured:
        validate_local_source_bindings(tmp_path, (binding,))
    assert "RAW_PATH_SENTINEL" not in str(captured.value)
