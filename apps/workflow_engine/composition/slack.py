"""Production composition for the Slack external-effect adapter."""

from apps.shared.services.egress_guard import EgressGuardPolicy, OutboundEgressGuard
from apps.workflow_engine.adapters.providers.slack import (
    SlackDeliveryMode,
    SlackDeliveryPolicy,
    SlackEffectAdapter,
)


def build_slack_effect_adapter(mode: SlackDeliveryMode) -> SlackEffectAdapter:
    policy = SlackDeliveryPolicy()
    guard = OutboundEgressGuard(
        EgressGuardPolicy(
            allowed_schemes=frozenset({"https"}),
            allowed_methods=frozenset({"POST"}),
            allowed_ports=frozenset({443}),
            max_request_bytes=policy.max_request_bytes,
            max_response_bytes=policy.max_response_bytes,
            allow_compressed_response=False,
            force_identity_encoding=True,
        )
    )
    return SlackEffectAdapter(mode, egress_guard=guard, policy=policy)
