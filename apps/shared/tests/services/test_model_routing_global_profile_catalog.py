from apps.shared.services.model_routing_global_profile_catalog import (
    OFFICIAL_PROVIDER_CATALOG,
    SUPPORTED_MODEL_ROUTING_PROFILES,
    canonical_model_routing_id,
    catalog_metadata_for_model_id,
    supported_model_routing_ids,
)
from apps.shared.services.model_routing_model_filter import (
    filter_model_routing_available_model_ids,
)
from apps.workflow_engine.services.model_router import WORKFLOW_CHAT_MODEL_ALIASES


def test_official_catalog_covers_all_workflow_chat_model_ids():
    expected_ids = set(WORKFLOW_CHAT_MODEL_ALIASES)

    assert set(OFFICIAL_PROVIDER_CATALOG) == expected_ids
    assert len(OFFICIAL_PROVIDER_CATALOG) == 38


def test_supported_candidates_are_explicit_and_exclude_unprofiled_models():
    candidates = supported_model_routing_ids(
        ["gpt-4o-mini", "gpt-5.4", "gpt-5.6-sol", "unknown-model", "gpt-5.4"]
    )

    assert candidates == ["gpt-4o-mini", "gpt-5.4", "gpt-5.6-sol"]


def test_supported_candidates_collapse_provider_aliases_to_available_canonical_id():
    candidates = supported_model_routing_ids(
        ["gpt-4o-mini", "gpt-5.6", "gpt-5.6-sol", "o3"]
    )

    assert candidates == ["gpt-4o-mini", "gpt-5.6-sol", "o3"]
    assert canonical_model_routing_id("gpt-5.6") == "gpt-5.6-sol"


def test_supported_candidates_preserve_executable_alias_when_canonical_is_unavailable():
    assert supported_model_routing_ids(["gpt-5.6"]) == ["gpt-5.6"]


def test_excluded_model_filter_matches_provider_aliases_by_canonical_id():
    allowed = filter_model_routing_available_model_ids(
        ["gpt-5.6", "gpt-5.6-sol", "gpt-5.6-luna"],
        node_data={
            "model_routing_policy": {"excluded_model_ids": ["gpt-5.6-sol"]}
        },
    )

    assert allowed == ["gpt-5.6-luna"]


def test_official_catalog_profiles_do_not_claim_unmeasured_runtime_metrics():
    for profile in SUPPORTED_MODEL_ROUTING_PROFILES.values():
        assert profile.quality_by_difficulty == {}
        assert profile.uncertainty_by_difficulty == {}
        assert profile.expected_latency_ms_by_input_profile == {}
        assert profile.prior_strength == 0


def test_each_catalog_entry_has_provider_documentation_sources():
    for entry in OFFICIAL_PROVIDER_CATALOG.values():
        assert entry.model_source_url.startswith("https://")
        assert entry.pricing_source_url.startswith("https://")
        assert entry.provider in {"openai", "anthropic", "google"}


def test_official_catalog_keeps_provider_claims_distinct_from_runtime_evidence():
    sol = catalog_metadata_for_model_id("gpt-5.6-sol")
    o3 = catalog_metadata_for_model_id("o3")

    assert sol["canonical_model_id"] == "gpt-5.6-sol"
    assert sol["evidence_type"] == "provider_documentation"
    assert sol["model_role"] == "frontier_generalist"
    assert sol["specialization_tags"] == [
        "complex_professional_work",
        "complex_reasoning",
        "coding",
    ]
    assert o3["specialization_tags"] == [
        "multi_step_reasoning",
        "math_reasoning",
        "scientific_reasoning",
        "code_reasoning",
        "visual_reasoning",
        "technical_writing",
        "instruction_following",
    ]
    assert o3["model_role"] == "reasoning_specialist"
    assert sol["specialization_tags"] != o3["specialization_tags"]
