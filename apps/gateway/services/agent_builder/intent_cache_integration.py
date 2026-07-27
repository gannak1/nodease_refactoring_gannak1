from __future__ import annotations

import hashlib
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedEditPlacement,
    CachedIntentPlanV1,
    CachedKnowledgePlacement,
    CachedKnowledgeRequirement,
    CachedParameterGuidanceRef,
    EphemeralCacheScope,
    IntentLogicalEdge,
    IntentLogicalNode,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanningContext,
    LogicalStepRef,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_rehydration import (
    CachedIntentPlanRehydrator,
    CurrentRehydrationContext,
)
from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    CanonicalIntentTextRegistry,
)
from apps.gateway.services.agent_builder_intent_service import (
    LLMAgentBuilderIntentExtractor,
)
from apps.gateway.services.agent_builder.intent_cache_knowledge import (
    current_knowledge_resolutions,
)
from apps.shared.db.models.llm import LLMModel
from apps.shared.schemas.agent_builder import (
    AgentBuilderMessageRequest,
    AgentBuilderStructuredRequest,
)
from apps.shared.services.permissions import has_active_organization_membership
from apps.shared.services.workflow_node_catalog import node_definition


_CACHE_PLANNER_CONTRACT_VERSION = "agent-builder-intent-v1"
_CACHE_MATERIALIZER_VERSION = "agent-builder-direct-edit-v1"
_CACHE_NORMALIZER_VERSION = "intent-normalizer-v2"
_ALLOWED_RISK_FLAGS = frozenset(
    {
        "external_action_requested",
        "slack_channel_unresolved",
        "github_configuration_unresolved",
        "gmail_credential_unresolved",
        "external_configuration_unresolved",
    }
)
_INTEGRATION_ACTIONS = {
    "github_pr_read": "github.pull_request.read",
    "github_pr_comment": "github.pull_request.comment",
}
logger = logging.getLogger(__name__)


def _planning_context_unavailable(reason: str) -> None:
    """Record a closed, payload-free reason for cache context bypass."""
    logger.info(
        "agent_builder.intent_cache_context outcome=unavailable reason=%s",
        reason,
    )
    return None
@dataclass(frozen=True, slots=True)
class CachePlanningInputs:
    context: IntentPlanningContext
    selected_target_logical_ref: str | None
    db: Any
    user_id: Any
    organization_id: Any
    extractor: LLMAgentBuilderIntentExtractor
    current_workflow_loader: Callable[[], object | None]
    safe_label: Callable[..., str]

    def rehydrator_factory(
        self,
        context: IntentPlanningContext,
        plan: CachedIntentPlanV1,
    ) -> CachedIntentPlanRehydrator:
        if context is not self.context:
            raise ValueError("unexpected request cache context")
        current_runtime = _planner_runtime_fingerprint(
            db=self.db,
            user_id=self.user_id,
            organization_id=self.organization_id,
            extractor=self.extractor,
        )
        try:
            current_projection = _logical_workflow_context(
                self.current_workflow_loader(),
                safe_label=self.safe_label,
            )
        except Exception:
            current_projection = None
        if current_projection is None:
            current_topology = None
            current_node_refs: dict[str, str] = {}
            current_edge_refs: dict[str, str] = {}
        else:
            current_topology, current_node_refs, current_edge_refs = current_projection

        selected_target_type = context.scope._selected_target_type
        selected_target_id = context.scope._selected_target_id
        selected_target_ref = (
            current_node_refs.get(selected_target_id)
            if selected_target_type == "selected_node"
            else current_edge_refs.get(selected_target_id)
            if selected_target_type == "selected_edge"
            else None
        )
        target_is_required = selected_target_type is not None
        selected_target_exists = not target_is_required or selected_target_ref is not None
        try:
            organization_membership_active = has_active_organization_membership(
                self.db,
                self.user_id,
                self.organization_id,
            )
        except Exception:
            organization_membership_active = False
        runtime_is_current = current_runtime is not None
        topology_is_current = current_topology is not None
        return current_rehydrator_for(
            context,
            plan,
            selected_target_logical_ref=selected_target_ref,
            knowledge_resolutions=current_knowledge_resolutions(
                db=self.db,
                user_id=self.user_id,
                organization_id=self.organization_id,
                context=context,
                plan=plan,
            ),
            current_planner_runtime=current_runtime,
            current_workflow_context=current_topology,
            workflow_context_current=topology_is_current,
            organization_membership_active=organization_membership_active,
            model_active=runtime_is_current,
            credential_active=runtime_is_current,
            model_credential_relation_verified=runtime_is_current,
            credential_use_allowed=runtime_is_current,
            selected_target_exists=selected_target_exists,
            selected_target_type_matches=(
                topology_is_current and selected_target_exists
            ),
            selected_target_placement_allowed=(
                topology_is_current
                and current_topology == context.workflow_context
                and selected_target_exists
            ),
        )

def _digest(*parts: object) -> str:
    framed = b"agent-builder:intent-cache:runtime\0"
    for part in parts:
        encoded = str(part).encode("utf-8")
        framed += len(encoded).to_bytes(4, "big") + encoded
    return hashlib.sha256(framed).hexdigest()


def _cache_generation_mode(value: str) -> str | None:
    return {
        "configure_and_generate": "guided_generate",
        "structure_only": "structure_only",
    }.get(value)


def _logical_workflow_context(
    workflow,
    *,
    safe_label,
) -> tuple[IntentLogicalTopology, dict[str, str], dict[str, str]] | None:
    if workflow is None:
        return IntentLogicalTopology(
            workflow_present=False,
            nodes=(),
            edges=(),
        ), {}, {}
    graph = getattr(workflow, "graph", None)
    # AppService creates the primary workflow before an editor graph exists.
    # Treat that durable empty state exactly like an explicit empty graph so a
    # new App can participate in the same deterministic cache contract.
    if graph is None:
        graph = {"nodes": [], "edges": []}
    if not isinstance(graph, dict):
        return None
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    if not isinstance(raw_nodes, list) or not isinstance(raw_edges, list):
        return None
    node_refs: dict[str, str] = {}
    node_kinds: dict[str, str] = {}
    nodes: list[IntentLogicalNode] = []
    for ordinal, node in enumerate(raw_nodes, start=1):
        if not isinstance(node, dict):
            return None
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "")
        definition = node_definition(node_type)
        connection_policy = (
            definition.get("connection_policy") if isinstance(definition, dict) else None
        )
        role = connection_policy.get("role") if isinstance(connection_policy, dict) else None
        if (
            not node_id
            or node_id in node_refs
            or role not in {"entry", "intermediate", "branch", "terminal"}
        ):
            return None
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        logical_ref = f"n_{ordinal}"
        try:
            nodes.append(
                IntentLogicalNode(
                    logical_ref=logical_ref,
                    node_type=node_type,
                    safe_label=safe_label(
                        data.get("title") or node_type,
                        fallback=node_type,
                    ),
                    role=role,
                )
            )
        except Exception:
            return None
        node_refs[node_id] = logical_ref
        node_kinds[node_id] = node_type

    edges: list[IntentLogicalEdge] = []
    for ordinal, edge in enumerate(raw_edges, start=1):
        if not isinstance(edge, dict):
            return None
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_refs or target not in node_refs:
            return None
        # Branch handle semantics carry current parameter state. Until a closed
        # ordinal projection exists, reject them rather than create a partial key.
        if edge.get("sourceHandle") is not None or edge.get("targetHandle") is not None:
            return None
        try:
            edges.append(
                IntentLogicalEdge(
                    logical_ref=f"e_{ordinal}",
                    source_node_ref=node_refs[source],
                    target_node_ref=node_refs[target],
                    source_handle_kind="standard",
                    source_handle_ordinal=None,
                    target_handle_kind="standard",
                )
            )
        except Exception:
            return None
    try:
        return (
            IntentLogicalTopology(
                workflow_present=True,
                nodes=tuple(nodes),
                edges=tuple(edges),
            ),
            node_refs,
            {
                str(edge.get("id")): f"e_{ordinal}"
                for ordinal, edge in enumerate(raw_edges, start=1)
                if isinstance(edge, dict) and edge.get("id")
            },
        )
    except Exception:
        return None


def _planner_runtime_fingerprint(
    *,
    db,
    user_id,
    organization_id,
    extractor: LLMAgentBuilderIntentExtractor,
) -> PlannerRuntimeFingerprint | None:
    try:
        runtime = extractor.runtime_loader(
            db=db,
            user_id=user_id,
            credential_id=extractor.credential_id,
            model_id=extractor.model_id,
            organization_id=organization_id,
            runtime_surface="agent_builder_intent",
        )
        model = db.query(LLMModel).filter(LLMModel.id == runtime.model_db_id).first()
        provider = getattr(getattr(model, "provider", None), "name", None)
        if provider not in {"openai", "google", "anthropic"}:
            return None
        return PlannerRuntimeFingerprint(
            provider_ref=provider,
            model_relation_fingerprint=_digest(
                organization_id,
                runtime.model_db_id,
                runtime.model_id,
            ),
            credential_relation_fingerprint=_digest(
                organization_id,
                runtime.credential_id,
                runtime.model_db_id,
            ),
        )
    except Exception:
        return None

def build_intent_planning_context(
    *,
    db,
    user_id,
    organization_id,
    extractor,
    request: AgentBuilderMessageRequest,
    workflow,
    safe_summary,
    safe_label,
    current_workflow_loader: Callable[[], object | None],
    knowledge_context_fingerprint_factory: Callable[..., str] | None,
) -> CachePlanningInputs | None:
    """Build the full transient DTO only when every projection is complete."""
    if not isinstance(extractor, LLMAgentBuilderIntentExtractor):
        return _planning_context_unavailable("extractor_unavailable")
    if extractor.credential_id is None or extractor.model_id is None:
        return _planning_context_unavailable("runtime_selection_unavailable")
    generation_mode = _cache_generation_mode(request.generation_mode)
    full_safe_message = safe_summary(request.message, limit=4001)
    if generation_mode is None or not full_safe_message or len(full_safe_message) >= 4000:
        return _planning_context_unavailable("request_projection_unavailable")
    projected = _logical_workflow_context(workflow, safe_label=safe_label)
    if projected is None:
        return _planning_context_unavailable("workflow_context_unavailable")
    topology, node_refs, edge_refs = projected
    selected_target_type = None
    selected_target_id = None
    if request.selected_node_id and request.selected_edge_id:
        return _planning_context_unavailable("selected_target_unavailable")
    if request.selected_node_id:
        selected_target_type = "selected_node"
        selected_target_id = request.selected_node_id
        if selected_target_id not in node_refs:
            return _planning_context_unavailable("selected_target_unavailable")
    elif request.selected_edge_id:
        selected_target_type = "selected_edge"
        selected_target_id = request.selected_edge_id
        if selected_target_id not in edge_refs:
            return _planning_context_unavailable("selected_target_unavailable")
    runtime_fingerprint = _planner_runtime_fingerprint(
        db=db,
        user_id=user_id,
        organization_id=organization_id,
        extractor=extractor,
    )
    if runtime_fingerprint is None:
        return _planning_context_unavailable("planner_runtime_unavailable")
    if not callable(knowledge_context_fingerprint_factory):
        return _planning_context_unavailable("knowledge_fingerprint_factory_unavailable")
    try:
        knowledge_context_fingerprint = knowledge_context_fingerprint_factory(
            db=db,
            user_id=user_id,
            organization_id=organization_id,
            full_safe_message=full_safe_message,
        )
    except Exception:
        return _planning_context_unavailable("knowledge_fingerprint_unavailable")
    selected_target_logical_ref = (
        node_refs.get(selected_target_id)
        if selected_target_type == "selected_node"
        else edge_refs.get(selected_target_id)
        if selected_target_type == "selected_edge"
        else None
    )
    return CachePlanningInputs(
        context=IntentPlanningContext(
            full_safe_message=full_safe_message,
            workflow_context=topology,
            planner_runtime=runtime_fingerprint,
            generation_mode=generation_mode,
            knowledge_context_fingerprint=knowledge_context_fingerprint,
            contract_versions=IntentPlanContractVersions(
                normalizer_version=_CACHE_NORMALIZER_VERSION,
                cache_schema_version=1,
                planner_contract_version=_CACHE_PLANNER_CONTRACT_VERSION,
                catalog_version=3,
                canonical_text_registry_version="intent-text-v1",
                materializer_version=_CACHE_MATERIALIZER_VERSION,
            ),
            scope=EphemeralCacheScope(
                actor_id=user_id,
                organization_id=organization_id,
                selected_target_type=selected_target_type,
                selected_target_id=selected_target_id,
            ),
        ),
        selected_target_logical_ref=selected_target_logical_ref,
        db=db,
        user_id=user_id,
        organization_id=organization_id,
        extractor=extractor,
        current_workflow_loader=current_workflow_loader,
        safe_label=safe_label,
    )

def current_rehydrator_for(
    context: IntentPlanningContext,
    plan: CachedIntentPlanV1,
    *,
    selected_target_logical_ref: str | None = None,
    knowledge_resolutions=(),
    current_planner_runtime: PlannerRuntimeFingerprint | None = None,
    current_workflow_context: IntentLogicalTopology | None = None,
    workflow_context_current: bool = False,
    organization_membership_active: bool = False,
    model_active: bool = False,
    credential_active: bool = False,
    model_credential_relation_verified: bool = False,
    credential_use_allowed: bool = False,
    selected_target_exists: bool = False,
    selected_target_type_matches: bool = False,
    selected_target_placement_allowed: bool = False,
) -> CachedIntentPlanRehydrator:
    """Build a fail-closed snapshot of request-current protected-resource state."""
    scope = context.scope

    return CachedIntentPlanRehydrator(
        CurrentRehydrationContext(
            actor_id=scope._actor_id,
            organization_id=scope._organization_id,
            organization_membership_active=organization_membership_active,
            workflow_context_current=workflow_context_current,
            workflow_context=current_workflow_context or context.workflow_context,
            planner_runtime=current_planner_runtime or context.planner_runtime,
            generation_mode=context.generation_mode,
            model_active=model_active,
            credential_active=credential_active,
            model_credential_relation_verified=model_credential_relation_verified,
            credential_use_allowed=credential_use_allowed,
            selected_target_type=scope._selected_target_type,
            selected_target_id=scope._selected_target_id,
            selected_target_logical_ref=selected_target_logical_ref,
            selected_target_exists=selected_target_exists,
            selected_target_type_matches=selected_target_type_matches,
            selected_target_placement_allowed=selected_target_placement_allowed,
            knowledge_context_fingerprint=context.knowledge_context_fingerprint,
            knowledge_resolutions=knowledge_resolutions,
        )
    )

def project_structured_intent_plan(
    structured: AgentBuilderStructuredRequest,
    context: IntentPlanningContext,
) -> CachedIntentPlanV1 | None:
    """Allowlist-only projection; any unmapped provider detail is store-ineligible."""
    if (
        structured.request_type not in {"new_workflow", "modify_workflow"}
        or structured.missing_information
        or structured.unsupported_requests
        or structured.explicit_parameter_values
        or set(structured.risk_flags) - _ALLOWED_RISK_FLAGS
    ):
        return None
    registry = CanonicalIntentTextRegistry()
    try:
        occurrences: dict[str, int] = {}
        step_refs_by_id: dict[str, LogicalStepRef] = {}
        ordered_capabilities: list[str] = []
        logical_steps: list[LogicalStepRef] = []
        for step in structured.planned_steps:
            if step.step_id in step_refs_by_id or registry.purpose_for(step.capability) != step.purpose:
                return None
            occurrences[step.capability] = occurrences.get(step.capability, 0) + 1
            step_ref = LogicalStepRef(
                capability=step.capability,
                occurrence=occurrences[step.capability],
            )
            ordered_capabilities.append(step.capability)
            logical_steps.append(step_ref)
            step_refs_by_id[step.step_id] = step_ref
        if not logical_steps:
            return None
        edit_placement = None
        if structured.draft_mode == "modify_workflow":
            if len(structured.edit_operations) != 1:
                return None
            operation = structured.edit_operations[0]
            if (
                operation.operation != "insert"
                or operation.target.reference_type not in {"selected_node", "selected_edge"}
                or operation.target.query is not None
                or operation.target.source_query is not None
                or operation.target.destination_query is not None
                or operation.target.capabilities
                or operation.target.node_types
            ):
                return None
            refs = tuple(step_refs_by_id.get(step_id) for step_id in operation.step_refs)
            if not refs or any(ref is None for ref in refs):
                return None
            edit_placement = CachedEditPlacement(
                placement=operation.placement,
                target_reference_type=operation.target.reference_type,
                step_refs=refs,
            )
        elif structured.draft_mode == "replace_workflow":
            if structured.request_type != "modify_workflow" or structured.edit_operations:
                return None
        elif structured.draft_mode != "new_workflow" or structured.edit_operations:
            return None
        guidance = []
        for hint in structured.parameter_guidance_hints:
            step_ref = step_refs_by_id.get(hint.step_id)
            if step_ref is None:
                return None
            projected_guidance = registry.project_guidance(
                capability=step_ref.capability,
                parameter_key=hint.parameter_key,
                reason=hint.reason,
                input_guidance=hint.input_guidance,
            )
            if projected_guidance is None:
                return None
            reason_ref, input_ref = projected_guidance
            guidance.append(
                CachedParameterGuidanceRef(
                    logical_step_ref=step_ref,
                    parameter_key=hint.parameter_key,
                    reason_template_ref=reason_ref,
                    input_guidance_template_ref=input_ref,
                )
            )
        knowledge_requirements = []
        requirement_refs = set()
        for requirement in structured.knowledge_requirements:
            if requirement.requirement_id in requirement_refs:
                return None
            target_step_ref = step_refs_by_id.get(requirement.target_step_ref or "")
            topic_refs = tuple(
                registry.project_topic(topic)
                for topic in requirement.query_topics
            )
            if any(ref is None for ref in topic_refs):
                return None
            if (
                target_step_ref is None
                or not topic_refs
                or any(ref is None for ref in topic_refs)
            ):
                return None
            knowledge_requirements.append(
                CachedKnowledgeRequirement(
                    requirement_ref=requirement.requirement_id,
                    required=requirement.required,
                    evidence_kind=requirement.expected_evidence_type,
                    target_step_ref=target_step_ref,
                    topic_refs=topic_refs,
                )
            )
            requirement_refs.add(requirement.requirement_id)
        knowledge_placements = []
        placement_refs = set()
        for placement in structured.knowledge_placements:
            if placement.requirement_id in placement_refs:
                return None

            def step_ref(step_id):
                if step_id is None:
                    return None
                return step_refs_by_id.get(step_id)

            cached_placement = CachedKnowledgePlacement(
                requirement_ref=placement.requirement_id,
                timing=placement.timing,
                effect_kind=placement.effect_kind,
                target_step_ref=step_ref(placement.target_step_id),
                knowledge_step_ref=step_ref(placement.knowledge_step_id),
                upstream_step_ref=step_ref(placement.upstream_step_id),
                downstream_step_ref=step_ref(placement.downstream_step_id),
                empty_selection_bridge=placement.empty_selection_bridge,
            )
            knowledge_placements.append(cached_placement)
            placement_refs.add(placement.requirement_id)
        if placement_refs != requirement_refs:
            return None
        integration_actions = tuple(
            action
            for capability, action in _INTEGRATION_ACTIONS.items()
            if capability in ordered_capabilities
        )
        return CachedIntentPlanV1(
            schema_version=1,
            request_type=structured.request_type,
            draft_mode=structured.draft_mode,
            ordered_capabilities=tuple(ordered_capabilities),
            logical_steps=tuple(logical_steps),
            edit_placement=edit_placement,
            integration_actions=integration_actions,
            parameter_guidance_refs=tuple(guidance),
            knowledge_requirements=tuple(knowledge_requirements),
            knowledge_placements=tuple(knowledge_placements),
            risk_flags=tuple(structured.risk_flags),
            contract_versions=context.contract_versions,
        )
    except Exception:
        return None
