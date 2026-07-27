from __future__ import annotations

import uuid

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    EphemeralCacheScope,
    IntentLogicalNode,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanningContext,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_cache_coordinator import (
    AgentBuilderIntentCacheCoordinator,
)


def _context(topology: IntentLogicalTopology) -> IntentPlanningContext:
    return IntentPlanningContext(
        full_safe_message="safe request",
        workflow_context=topology,
        planner_runtime=PlannerRuntimeFingerprint(
            provider_ref="openai",
            model_relation_fingerprint="a" * 64,
            credential_relation_fingerprint="b" * 64,
        ),
        generation_mode="guided_generate",
        knowledge_context_fingerprint="c" * 64,
        contract_versions=IntentPlanContractVersions(
            normalizer_version="intent-normalizer-v2",
            cache_schema_version=1,
            planner_contract_version="agent-builder-intent-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v1",
            materializer_version="agent-builder-direct-edit-v1",
        ),
        scope=EphemeralCacheScope(
            actor_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
            organization_id=uuid.UUID("00000000-0000-0000-0000-000000000002"),
            selected_target_type=None,
            selected_target_id=None,
        ),
    )


def test_graph_topology_change_does_not_change_intent_cache_lookup_material() -> None:
    empty = _context(IntentLogicalTopology(workflow_present=False, nodes=(), edges=()))
    changed = _context(
        IntentLogicalTopology(
            workflow_present=True,
            nodes=(
                IntentLogicalNode(
                    logical_ref="n_1",
                    node_type="startNode",
                    safe_label="Input",
                    role="entry",
                ),
            ),
            edges=(),
        )
    )

    assert (
        AgentBuilderIntentCacheCoordinator._canonical_key_material(empty, "d" * 64)
        == AgentBuilderIntentCacheCoordinator._canonical_key_material(changed, "d" * 64)
    )
