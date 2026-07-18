from apps.shared.services.model_routing_global_profile_catalog import (
    OFFICIAL_PROVIDER_CATALOG,
    SUPPORTED_MODEL_ROUTING_PROFILES,
    supported_model_routing_ids,
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
