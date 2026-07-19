from apps.shared.services.llm_model_pricing import (
    calculate_text_token_cost,
    get_model_pricing,
    normalize_model_pricing_id,
)


def test_gemini_35_flash_uses_official_standard_text_prices():
    pricing = get_model_pricing("gemini-3.5-flash")

    assert pricing is not None
    assert pricing.standard_input_per_1k == 0.00075
    assert pricing.standard_output_per_1k == 0.0045


def test_model_pricing_normalizes_google_prefix_and_version_aliases():
    assert normalize_model_pricing_id("models/gemini-3.5-flash") == "gemini-3.5-flash"
    assert normalize_model_pricing_id("gpt-4o-2024-11-20") == "gpt-4o"


def test_openai_cached_input_tokens_use_cached_input_price():
    cost = calculate_text_token_cost(
        "gpt-4o-mini",
        prompt_tokens=1_000,
        completion_tokens=500,
        cached_input_tokens=400,
    )

    # $0.15 / 1M standard input, $0.075 / 1M cached input,
    # $0.60 / 1M output.
    assert cost == 0.00042


def test_unknown_conditional_prices_are_reported_as_standard_estimate():
    pricing = get_model_pricing("gemini-3.5-flash")

    assert pricing is not None
    assert pricing.long_context_input_per_1k is None
    assert pricing.batch_input_per_1k is None
