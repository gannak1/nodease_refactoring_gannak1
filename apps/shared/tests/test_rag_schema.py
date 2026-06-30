from datetime import datetime, timezone

import pytest
from apps.shared.schemas.rag import MetadataFilter, SearchQuery, TagFilter
from apps.shared.services.rag_filters import (
    build_keyword_filter_clause,
    build_sqlalchemy_filter_conditions,
    normalize_metadata_filter,
)
from pydantic import ValidationError


def test_search_query_accepts_metadata_filter_contract():
    query = SearchQuery(
        query="policy",
        top_k=20,
        metadata_filter=MetadataFilter(
            classification=["INTERNAL", "confidential"],
            tags=TagFilter(mode="contains_all", values=["policy", "hr"]),
            source_type=["file"],
            effective_at=datetime(2026, 6, 30, tzinfo=timezone.utc),
        ),
        hierarchy_mode="flat",
    )

    assert query.metadata_filter.classification == ["internal", "confidential"]
    assert query.metadata_filter.tags.values == ["policy", "hr"]
    assert query.metadata_filter.source_type == ["FILE"]


def test_search_query_rejects_duplicate_shortcuts():
    with pytest.raises(ValidationError):
        SearchQuery(
            query="policy",
            metadata_filter=MetadataFilter(classification=["internal"]),
            classification_filter=["public"],
        )


def test_metadata_filter_rejects_free_form_keys():
    with pytest.raises(ValidationError):
        MetadataFilter(hierarchy_mode="parent_child")


def test_search_query_rejects_top_k_over_cap():
    with pytest.raises(ValidationError):
        SearchQuery(query="policy", top_k=21)


def test_tag_filter_rejects_contract_limit_violations():
    assert TagFilter(values=["Policy", "policy"]).values == ["policy"]

    with pytest.raises(ValidationError):
        TagFilter(values=[f"tag-{index}" for index in range(21)])

    with pytest.raises(ValidationError):
        TagFilter(values=["x" * 65])


def test_normalized_metadata_filter_audit_summary_is_redaction_safe():
    effective_at = datetime(2026, 6, 30, tzinfo=timezone.utc)
    normalized = normalize_metadata_filter(
        classification_filter=["confidential"],
        tags=TagFilter(mode="contains_any", values=["policy", "secret-key"]),
        source_type=["DB"],
        effective_at=effective_at,
    )

    assert normalized.audit_summary() == {
        "classification": ["confidential"],
        "tags": {"mode": "contains_any", "count": 2},
        "source_type": ["DB"],
        "effective_at": effective_at.isoformat(),
    }


def test_tag_filter_builders_compare_lowercase_tag_values():
    normalized = normalize_metadata_filter(
        tags=TagFilter(mode="contains_any", values=["Policy", "policy"])
    )

    assert normalized.tags.values == ("policy",)
    keyword_clause = build_keyword_filter_clause(normalized)
    sqlalchemy_conditions = build_sqlalchemy_filter_conditions(normalized)

    assert any("lower(tag.value)" in fragment for fragment in keyword_clause.fragments)
    assert any("lower(tag.value)" in str(condition) for condition in sqlalchemy_conditions)
    assert any("jsonb_typeof" in fragment for fragment in keyword_clause.fragments)
    assert any("jsonb_typeof" in str(condition) for condition in sqlalchemy_conditions)


def test_effective_at_filter_builders_do_not_cast_malformed_metadata_dates():
    effective_at = datetime(2026, 6, 30, tzinfo=timezone.utc)
    normalized = normalize_metadata_filter(effective_at=effective_at)

    keyword_clause = build_keyword_filter_clause(normalized)
    sqlalchemy_conditions = build_sqlalchemy_filter_conditions(normalized)

    keyword_sql = " ".join(keyword_clause.fragments)
    sqlalchemy_sql = " ".join(str(condition) for condition in sqlalchemy_conditions)

    assert "::timestamptz" not in keyword_sql
    assert "::timestamptz" not in sqlalchemy_sql
    assert "metadata_effective_pattern" in keyword_sql
    assert "metadata_effective_pattern" in sqlalchemy_sql
    assert keyword_clause.params["metadata_effective_at"] == "2026-06-30T00:00:00+00:00"


def test_effective_at_filter_normalizes_to_utc_iso_string():
    effective_at = datetime(2026, 6, 30, 9, 0, 0, tzinfo=timezone.utc)
    normalized = normalize_metadata_filter(effective_at=effective_at)

    keyword_clause = build_keyword_filter_clause(normalized)

    assert keyword_clause.params["metadata_effective_at"] == "2026-06-30T09:00:00+00:00"
    assert r"\+00:00" in keyword_clause.params["metadata_effective_pattern"]
