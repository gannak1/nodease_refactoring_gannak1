from apps.gateway.services.knowledge_document_projection import (
    project_safe_document_metadata,
)


def test_document_metadata_projection_returns_only_allowlisted_safe_fields():
    projected = project_safe_document_metadata(
        {
            "progress": 45,
            "processing_progress": 45.5,
            "processing_current_step": "Processing chunks.",
            "processing_enqueued_at": "2026-07-13T09:00:00+00:00",
            "processing_started_at": "2026-07-13T09:00:01Z",
            "processing_progress_updated_at": "2026-07-13T09:00:02+00:00",
            "processing_recovered_from_timeout": False,
            "remove_urls_emails": True,
            "remove_whitespace": False,
            "chunking_mode": "HIERARCHICAL",
            "strategy": "general",
            "upload_method": "direct",
            "cost_estimate": {"pages": 2, "credits": 2, "cost_usd": 0.006},
            "api_config": {
                "url_encrypted": None,
                "headers_encrypted": None,
                "body_encrypted": None,
            },
            "connection_id": None,
            "source_identity_id": None,
            "source_connector_ref": None,
            "db_config": {"connection_id": None},
            "unknown_nested": {"field": "not-projected"},
        }
    )

    assert projected == {
        "progress": 45,
        "processing_progress": 45.5,
        "processing_current_step": "Processing chunks.",
        "processing_enqueued_at": "2026-07-13T09:00:00+00:00",
        "processing_started_at": "2026-07-13T09:00:01Z",
        "processing_progress_updated_at": "2026-07-13T09:00:02+00:00",
        "processing_recovered_from_timeout": False,
        "remove_urls_emails": True,
        "remove_whitespace": False,
        "chunking_mode": "hierarchical",
        "strategy": "general",
        "upload_method": "direct",
        "cost_estimate": {"pages": 2, "credits": 2, "cost_usd": 0.006},
    }


def test_document_metadata_projection_omits_invalid_values_without_fallback():
    projected = project_safe_document_metadata(
        {
            "progress": True,
            "processing_progress": 101,
            "processing_current_step": ["unexpected"],
            "processing_enqueued_at": "2026-07-13T09:00:00",
            "processing_started_at": "not-a-timestamp",
            "processing_progress_updated_at": "x" * 65,
            "processing_recovered_from_timeout": "false",
            "remove_urls_emails": 1,
            "remove_whitespace": None,
            "chunking_mode": "unknown",
            "strategy": "custom",
            "upload_method": "other",
            "cost_estimate": {
                "pages": -1,
                "credits": float("inf"),
                "cost_usd": float("nan"),
            },
        }
    )

    assert projected == {}


def test_document_metadata_projection_accepts_partial_bounded_cost_estimate():
    projected = project_safe_document_metadata(
        {
            "cost_estimate": {
                "pages": 3,
                "credits": "3",
                "cost_usd": 0.009,
                "unknown": 10,
            }
        }
    )

    assert projected == {"cost_estimate": {"pages": 3, "cost_usd": 0.009}}


def test_document_metadata_projection_rejects_non_mapping_input():
    assert project_safe_document_metadata(["unexpected"]) == {}
