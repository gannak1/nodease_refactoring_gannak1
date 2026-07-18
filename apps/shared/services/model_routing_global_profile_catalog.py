"""Provider documentation-backed catalog for initial model-routing candidates.

This module deliberately does not invent quality, latency, or fallback numbers.
Those values must come from Nodease operational evidence, not vendor marketing.
The catalog only records the provider's published positioning and source links.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable

CATALOG_SOURCE = "official_provider_catalog"
CATALOG_PROFILE_VERSION = "official-provider-catalog-v1"

OPENAI_MODELS_URL = "https://developers.openai.com/api/docs/models"
OPENAI_PRICING_URL = "https://developers.openai.com/api/docs/pricing"
ANTHROPIC_MODELS_URL = "https://docs.anthropic.com/en/docs/about-claude/models/overview"
ANTHROPIC_PRICING_URL = "https://docs.anthropic.com/en/docs/about-claude/pricing"
GOOGLE_MODELS_URL = "https://ai.google.dev/gemini-api/docs/models"
GOOGLE_PRICING_URL = "https://ai.google.dev/gemini-api/docs/pricing"


@dataclass(frozen=True)
class OfficialProviderCatalogEntry:
    """Provider-published positioning, not a Nodease performance measurement."""

    provider: str
    capability_tier: str
    official_position: str
    lifecycle: str
    model_source_url: str
    pricing_source_url: str


@dataclass(frozen=True)
class ModelRoutingCatalogProfile:
    """DB-compatible profile with no unmeasured runtime claims."""

    capability_tier: str
    quality_by_difficulty: dict[str, float]
    uncertainty_by_difficulty: dict[str, float]
    expected_latency_ms_by_input_profile: dict[str, int]
    fallback_rate: Decimal
    prior_strength: Decimal


def _entries(
    model_ids: tuple[str, ...],
    *,
    provider: str,
    capability_tier: str,
    official_position: str,
    lifecycle: str = "listed",
    model_source_url: str,
    pricing_source_url: str,
) -> dict[str, OfficialProviderCatalogEntry]:
    return {
        model_id: OfficialProviderCatalogEntry(
            provider=provider,
            capability_tier=capability_tier,
            official_position=official_position,
            lifecycle=lifecycle,
            model_source_url=model_source_url,
            pricing_source_url=pricing_source_url,
        )
        for model_id in model_ids
    }


# Keep this list in exact sync with WORKFLOW_CHAT_MODEL_ALIASES. Tiers are a
# coarse representation of provider-published product positioning only. They
# are not a quality score and must not override Nodease operational evidence.
OFFICIAL_PROVIDER_CATALOG: dict[str, OfficialProviderCatalogEntry] = {
    **_entries(
        ("gpt-4o-mini", "gpt-5-mini", "gpt-5-nano", "gpt-5.4-nano", "gpt-5.6-luna"),
        provider="openai",
        capability_tier="economy",
        official_position="cost_sensitive",
        model_source_url=OPENAI_MODELS_URL,
        pricing_source_url=OPENAI_PRICING_URL,
    ),
    **_entries(
        ("gpt-4o", "gpt-4.1-mini", "gpt-5", "gpt-5.1", "gpt-5.2", "gpt-5.4-mini", "gpt-5.6-terra"),
        provider="openai",
        capability_tier="balanced",
        official_position="balanced_capability_cost",
        model_source_url=OPENAI_MODELS_URL,
        pricing_source_url=OPENAI_PRICING_URL,
    ),
    **_entries(
        ("gpt-4.1", "gpt-5.4", "gpt-5.4-pro", "gpt-5.5", "gpt-5.5-pro", "gpt-5.6", "gpt-5.6-sol", "o3", "o3-pro"),
        provider="openai",
        capability_tier="advanced",
        official_position="high_capability_reasoning",
        model_source_url=OPENAI_MODELS_URL,
        pricing_source_url=OPENAI_PRICING_URL,
    ),
    **_entries(
        ("claude-haiku-4-5", "claude-haiku-4-5-20251001"),
        provider="anthropic",
        capability_tier="economy",
        official_position="fast_cost_efficient",
        model_source_url=ANTHROPIC_MODELS_URL,
        pricing_source_url=ANTHROPIC_PRICING_URL,
    ),
    **_entries(
        ("claude-sonnet-4-5-20250929", "claude-sonnet-4-6", "claude-sonnet-5"),
        provider="anthropic",
        capability_tier="balanced",
        official_position="balanced_capability_cost",
        model_source_url=ANTHROPIC_MODELS_URL,
        pricing_source_url=ANTHROPIC_PRICING_URL,
    ),
    **_entries(
        ("claude-fable-5", "claude-opus-4-5-20251101", "claude-opus-4-6", "claude-opus-4-7", "claude-opus-4-8"),
        provider="anthropic",
        capability_tier="advanced",
        official_position="high_capability_reasoning",
        model_source_url=ANTHROPIC_MODELS_URL,
        pricing_source_url=ANTHROPIC_PRICING_URL,
    ),
    **_entries(
        ("gemini-2.5-flash-lite", "gemini-3.1-flash-lite"),
        provider="google",
        capability_tier="economy",
        official_position="cost_efficient_high_volume",
        model_source_url=GOOGLE_MODELS_URL,
        pricing_source_url=GOOGLE_PRICING_URL,
    ),
    **_entries(
        ("gemini-2.5-flash", "gemini-3.5-flash"),
        provider="google",
        capability_tier="balanced",
        official_position="fast_general_capability",
        model_source_url=GOOGLE_MODELS_URL,
        pricing_source_url=GOOGLE_PRICING_URL,
    ),
    **_entries(
        ("gemini-2.5-pro",),
        provider="google",
        capability_tier="advanced",
        official_position="complex_problem_solving",
        model_source_url=GOOGLE_MODELS_URL,
        pricing_source_url=GOOGLE_PRICING_URL,
    ),
    **_entries(
        ("gemini-3-flash-preview", "gemini-3.1-pro-preview"),
        provider="google",
        capability_tier="advanced",
        official_position="preview_advanced_capability",
        lifecycle="preview",
        model_source_url=GOOGLE_MODELS_URL,
        pricing_source_url=GOOGLE_PRICING_URL,
    ),
}


# The global profile table currently requires these legacy metric columns.
# Empty metrics and zero prior strength explicitly mean "not measured".
SUPPORTED_MODEL_ROUTING_PROFILES: dict[str, ModelRoutingCatalogProfile] = {
    model_id: ModelRoutingCatalogProfile(
        capability_tier=entry.capability_tier,
        quality_by_difficulty={},
        uncertainty_by_difficulty={},
        expected_latency_ms_by_input_profile={},
        fallback_rate=Decimal("0"),
        prior_strength=Decimal("0"),
    )
    for model_id, entry in OFFICIAL_PROVIDER_CATALOG.items()
}


def normalize_model_id(value: object) -> str:
    return str(value or "").strip().lower().removeprefix("models/")


def supported_model_routing_ids(model_ids: Iterable[str]) -> list[str]:
    """Preserve input order and retain only explicitly cataloged model IDs."""

    seen: set[str] = set()
    supported: list[str] = []
    for model_id in model_ids:
        normalized = normalize_model_id(model_id)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if normalized in SUPPORTED_MODEL_ROUTING_PROFILES:
            supported.append(str(model_id).strip())
    return supported


def catalog_metadata_for_model_id(model_id: object) -> dict[str, str]:
    entry = OFFICIAL_PROVIDER_CATALOG.get(normalize_model_id(model_id))
    if entry is None:
        return {}
    return {
        "provider": entry.provider,
        "official_position": entry.official_position,
        "lifecycle": entry.lifecycle,
        "model_source_url": entry.model_source_url,
        "pricing_source_url": entry.pricing_source_url,
    }


def seed_model_routing_global_profiles(db: Any) -> dict[str, int]:
    """Create or refresh official provider catalog rows idempotently.

    Manually edited or operational profiles are not overwritten. Runtime metrics
    remain empty until Nodease has collected actual operational evidence.
    """

    from apps.shared.db.models.llm import LLMModel
    from apps.shared.db.models.model_routing_policy import LLMModelRoutingGlobalProfile

    model_rows = (
        db.query(LLMModel)
        .filter(LLMModel.model_id_for_api_call.in_(OFFICIAL_PROVIDER_CATALOG))
        .all()
    )
    if not model_rows:
        return {"created": 0, "updated": 0, "skipped": 0}

    existing_by_model_id = {
        row.llm_model_id: row
        for row in db.query(LLMModelRoutingGlobalProfile)
        .filter(LLMModelRoutingGlobalProfile.llm_model_id.in_([row.id for row in model_rows]))
        .all()
    }
    created = updated = skipped = 0
    replaceable_sources = {CATALOG_SOURCE, "routing_catalog_seed"}
    for model in model_rows:
        model_id = normalize_model_id(model.model_id_for_api_call)
        catalog = SUPPORTED_MODEL_ROUTING_PROFILES.get(model_id)
        if catalog is None:
            continue
        row = existing_by_model_id.get(model.id)
        if row is None:
            row = LLMModelRoutingGlobalProfile(
                llm_model_id=model.id,
                source=CATALOG_SOURCE,
                profile_version=CATALOG_PROFILE_VERSION,
            )
            db.add(row)
            created += 1
        elif row.source not in replaceable_sources:
            skipped += 1
            continue
        elif row.profile_version == CATALOG_PROFILE_VERSION and row.source == CATALOG_SOURCE:
            skipped += 1
            continue
        else:
            updated += 1
        row.capability_tier = catalog.capability_tier
        row.quality_by_difficulty = dict(catalog.quality_by_difficulty)
        row.uncertainty_by_difficulty = dict(catalog.uncertainty_by_difficulty)
        row.expected_latency_ms_by_input_profile = dict(
            catalog.expected_latency_ms_by_input_profile
        )
        row.fallback_rate = catalog.fallback_rate
        row.prior_strength = catalog.prior_strength
        row.source = CATALOG_SOURCE
        row.profile_version = CATALOG_PROFILE_VERSION
        row.is_active = True
    db.flush()
    return {"created": created, "updated": updated, "skipped": skipped}
