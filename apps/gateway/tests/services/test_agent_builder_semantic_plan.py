from apps.gateway.application.agent_builder.semantic_plan import (
    catalog_parameter_guide,
    normalize_parameter_guidance_hints,
    planned_step_ids,
)
from apps.shared.schemas.agent_builder import AgentBuilderParameterGuidanceHint


def test_catalog_parameter_guide_contains_only_catalog_parameters():
    guide = catalog_parameter_guide(["slack_send"])

    assert guide == {
        "step_slack": [
            {
                "parameter_key": "credential",
                "label": "Slack credential",
                "input_type": "credential_ref",
            },
                {
                    "parameter_key": "channel",
                    "label": "Slack channel",
                    "input_type": "text",
                },
        ]
    }


def test_planned_step_ids_are_stable_for_duplicate_capabilities():
    assert planned_step_ids(["llm", "llm", "answer"]) == [
        ("step_llm", "llm"),
        ("step_llm_2", "llm"),
        ("step_answer", "answer"),
    ]


def test_parameter_guidance_discards_unknown_mismatched_and_secret_like_hints():
    hints = [
        AgentBuilderParameterGuidanceHint(
            step_id="step_slack",
            parameter_key="channel",
            reason="메시지를 보낼 위치가 필요합니다.",
            input_guidance="Slack channel ID를 선택하세요.",
        ),
        AgentBuilderParameterGuidanceHint(
            step_id="step_slack",
            parameter_key="url",
            reason="다른 node의 parameter입니다.",
            input_guidance="URL을 입력하세요.",
        ),
        AgentBuilderParameterGuidanceHint(
            step_id="step_unknown",
            parameter_key="channel",
            reason="알 수 없는 step입니다.",
            input_guidance="값을 입력하세요.",
        ),
        AgentBuilderParameterGuidanceHint(
            step_id="step_slack",
            parameter_key="credential",
            reason="token=secret-value를 사용합니다.",
            input_guidance="credential을 입력하세요.",
        ),
    ]

    normalized = normalize_parameter_guidance_hints(
        hints,
        [("step_slack", "slack_send")],
    )

    assert normalized == [hints[0]]
