from apps.gateway.services.llm_service import LLMService


def test_gpt_5_6_tiers_have_display_names_and_prices():
    """새 durable model tier는 seed/비용 표시가 가능한 Gateway catalog에 등록된다."""
    expected_prices = {
        "gpt-5.6": {"input": 0.005, "output": 0.03},
        "gpt-5.6-terra": {"input": 0.0025, "output": 0.015},
        "gpt-5.6-luna": {"input": 0.001, "output": 0.006},
    }

    for model_id, price in expected_prices.items():
        assert LLMService.MODEL_DISPLAY_NAMES[model_id]
        assert LLMService.KNOWN_MODEL_PRICES[model_id] == price
