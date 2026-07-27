from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedParameterGuidanceRef,
    LogicalStepRef,
)
from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    CanonicalIntentTextRegistry,
)
from apps.gateway.application.agent_builder.semantic_plan import (
    normalize_parameter_guidance_hints,
)
from apps.shared.schemas.agent_builder import AgentBuilderParameterGuidanceHint


def test_safe_provider_guidance_is_canonicalized_for_cache_and_rehydration():
    hints = normalize_parameter_guidance_hints(
        [
            AgentBuilderParameterGuidanceHint(
                step_id="step_http",
                parameter_key="url",
                reason="A destination endpoint still needs to be configured.",
                input_guidance="Enter the endpoint to call for this workflow.",
            )
        ],
        [("step_http", "http_request")],
    )

    assert [(hint.reason, hint.input_guidance) for hint in hints] == [
        (
            "Additional configuration is required.",
            "Provide a value for url.",
        )
    ]

    registry = CanonicalIntentTextRegistry()
    hint = hints[0]
    projected = registry.project_guidance(
        capability="http_request",
        parameter_key="url",
        reason=hint.reason,
        input_guidance=hint.input_guidance,
    )
    assert projected == (
        "guidance.reason.configuration_required.v1",
        "guidance.input.provide_parameter_value.v1",
    )
    reason_ref, input_ref = projected

    cached = CachedParameterGuidanceRef(
        logical_step_ref=LogicalStepRef(capability="http_request", occurrence=1),
        parameter_key="url",
        reason_template_ref=reason_ref,
        input_guidance_template_ref=input_ref,
    )
    safe_label, input_type = registry.guidance_catalog_context(
        cached.logical_step_ref.capability,
        cached.parameter_key,
    )
    assert registry.render_guidance(
        reason_ref=cached.reason_template_ref,
        input_guidance_ref=cached.input_guidance_template_ref,
        capability=cached.logical_step_ref.capability,
        parameter_key=cached.parameter_key,
        safe_label=safe_label,
        input_type=input_type,
    ) == (hint.reason, hint.input_guidance)
