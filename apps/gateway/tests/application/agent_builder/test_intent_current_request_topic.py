from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    CanonicalIntentTextRegistry,
)


def test_current_safe_message_topic_is_rendered_from_the_hit_request():
    registry = CanonicalIntentTextRegistry()

    ref = registry.project_current_safe_message_topic("LLM 노드 생성")

    assert ref == "topic.current_safe_message.v1"
    assert registry.render_topic(ref, full_safe_message="LLM 노드 생성") == "LLM 노드 생성"
