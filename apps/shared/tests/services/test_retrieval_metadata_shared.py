from types import SimpleNamespace
from uuid import uuid4

from apps.shared.services.retrieval_metadata import (
    chunk_metadata,
    hierarchy_path,
    metadata_summary,
)


def test_chunk_metadata_merges_document_safe_metadata_and_hierarchy_fields():
    parent_chunk_id = uuid4()
    chunk = SimpleNamespace(
        metadata_={"page": 2, "classification": "internal"},
        parent_chunk_id=parent_chunk_id,
        token_count=123,
        chunk_level="child",
        source_tier=None,
        document_version=SimpleNamespace(source_tier="company_policy"),
        section_path=["Policy", "Access"],
        heading="Access rules",
    )
    doc = SimpleNamespace(
        source_type="FILE",
        meta_info={"classification": "confidential", "tags": ["document"]},
    )

    metadata = chunk_metadata(chunk, doc)

    assert metadata["classification"] == "confidential"
    assert metadata["tags"] == ["document"]
    assert metadata["page"] == 2
    assert metadata["source_type"] == "FILE"
    assert metadata["parent_chunk_id"] == str(parent_chunk_id)
    assert metadata["token_count"] == 123
    assert metadata["chunk_level"] == "child"
    assert metadata["source_tier"] == "company_policy"
    assert hierarchy_path(metadata) == ["Policy", "Access"]


def test_metadata_summary_redacts_non_allowlisted_payload_fields():
    summary = metadata_summary(
        {
            "classification": "internal",
            "hierarchy_fallback": True,
            "content": "raw evidence text",
            "api_config": {"key": "secret"},
        }
    )

    assert summary == {
        "classification": "internal",
        "hierarchy_fallback": True,
    }


def test_metadata_summary_excludes_raw_source_identity_and_provider_payload():
    summary = metadata_summary(
        {
            "classification": "internal",
            "source_tier": "company_policy",
            "raw_source_url": "https://example.test/private?token=secret",
            "source_path": "/private/hr/salary.pdf",
            "prompt": "raw prompt",
            "completion": "raw completion",
            "provider_response": {"id": "raw-response"},
            "encrypted_config": "ciphertext",
            "access_token": "secret-token",
        }
    )

    assert summary == {
        "classification": "internal",
        "source_tier": "company_policy",
    }


def test_chunk_metadata_ignores_non_dict_metadata_without_crashing():
    chunk = SimpleNamespace(
        metadata_="bad chunk metadata",
        parent_chunk_id=None,
        token_count=None,
        chunk_level=None,
    )
    doc = SimpleNamespace(
        source_type="FILE",
        meta_info=["bad document metadata"],
    )

    metadata = chunk_metadata(chunk, doc)

    assert metadata == {
        "source_type": "FILE",
        "chunk_level": "flat",
    }


def test_hierarchy_path_accepts_string_path_or_heading_fallback():
    assert hierarchy_path({"section_path": "A / B / C"}) == ["A", "B", "C"]
    assert hierarchy_path({"heading": "Only heading"}) == ["Only heading"]
    assert hierarchy_path({}) is None
