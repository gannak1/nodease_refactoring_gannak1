from __future__ import annotations

import uuid
from typing import Literal

from pydantic import ValidationError

from apps.gateway.application.agent_builder.intent_cache.catalog_snapshot import (
    CAPABILITY_PARAMETER_INPUT_TYPES,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    IntentLogicalTopology,
    IntentPlanningContext,
    LogicalStepRef,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_cache.ports import (
    IntentRehydrationResult,
)
from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    CanonicalIntentTextRegistry,
    CanonicalReferenceError,
    GuidanceInputTypeError,
)
from apps.shared.schemas.agent_builder import (
    AgentBuilderEditOperation,
    AgentBuilderEditTargetReference,
    AgentBuilderKnowledgePlacement,
    AgentBuilderKnowledgeRequirement,
    AgentBuilderParameterGuidanceHint,
    AgentBuilderPendingResolution,
    AgentBuilderPlannedStep,
    AgentBuilderStructuredRequest,
)

_KNOWLEDGE_STATUS = frozenset({"ready", "empty", "ambiguous"})
_GENERATION_MODES = frozenset({"guided_generate", "quick_generate", "structure_only"})


class CurrentKnowledgeResolution:
    """One request-current Knowledge resolution; never a cache value."""

    __slots__ = (
        "requirement_ref",
        "resolution_id",
        "status",
        "candidate_handles",
        "hierarchy_authorized",
        "permission_allowed",
        "lifecycle_active",
        "operationally_ready",
        "_sealed",
    )
    __hash__ = None

    def __init__(
        self,
        *,
        requirement_ref: str,
        resolution_id: str,
        status: Literal["ready", "empty", "ambiguous"],
        candidate_handles: tuple[str, ...],
        hierarchy_authorized: bool,
        permission_allowed: bool,
        lifecycle_active: bool,
        operationally_ready: bool,
    ) -> None:
        if type(requirement_ref) is not str or not 1 <= len(requirement_ref) <= 64:
            raise ValueError("current Knowledge requirement ref is invalid")
        if type(resolution_id) is not str or not 1 <= len(resolution_id) <= 255:
            raise ValueError("current Knowledge resolution ID is invalid")
        if status not in _KNOWLEDGE_STATUS:
            raise ValueError("current Knowledge resolution status is invalid")
        if type(candidate_handles) is not tuple:
            raise TypeError("current Knowledge handles are invalid")
        if (
            len(candidate_handles) > 20
            or len(candidate_handles) != len(set(candidate_handles))
            or any(
                type(handle) is not str or not 1 <= len(handle) <= 255
                for handle in candidate_handles
            )
        ):
            raise ValueError("current Knowledge handles are invalid")
        if status == "empty" and candidate_handles:
            raise ValueError("empty Knowledge resolution has candidates")
        if status == "ready" and len(candidate_handles) != 1:
            raise ValueError("ready Knowledge resolution is not unique")
        if status == "ambiguous" and len(candidate_handles) < 2:
            raise ValueError("ambiguous Knowledge resolution is not ambiguous")
        flags = (
            hierarchy_authorized,
            permission_allowed,
            lifecycle_active,
            operationally_ready,
        )
        if any(type(flag) is not bool for flag in flags):
            raise TypeError("current Knowledge validation flag is invalid")

        for name, value in (
            ("requirement_ref", requirement_ref),
            ("resolution_id", resolution_id),
            ("status", status),
            ("candidate_handles", candidate_handles),
            ("hierarchy_authorized", hierarchy_authorized),
            ("permission_allowed", permission_allowed),
            ("lifecycle_active", lifecycle_active),
            ("operationally_ready", operationally_ready),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("CurrentKnowledgeResolution is immutable")
        object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return "<CurrentKnowledgeResolution redacted>"

    def __getattribute__(self, name):
        if name == "__getstate__":
            raise AttributeError(name)
        return object.__getattribute__(self, name)

    def __reduce_ex__(self, _protocol):
        raise TypeError("CurrentKnowledgeResolution is not serializable")


class CurrentRehydrationContext:
    """Request-current authoritative results; never a cache value or diagnostic."""

    __slots__ = (
        "actor_id",
        "organization_id",
        "organization_membership_active",
        "workflow_context_current",
        "workflow_context",
        "planner_runtime",
        "generation_mode",
        "model_active",
        "credential_active",
        "model_credential_relation_verified",
        "credential_use_allowed",
        "selected_target_type",
        "selected_target_id",
        "selected_target_logical_ref",
        "selected_target_exists",
        "selected_target_type_matches",
        "selected_target_placement_allowed",
        "knowledge_context_fingerprint",
        "knowledge_resolutions",
        "_sealed",
    )
    __hash__ = None

    def __init__(
        self,
        *,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        organization_membership_active: bool,
        workflow_context_current: bool,
        workflow_context: IntentLogicalTopology,
        planner_runtime: PlannerRuntimeFingerprint,
        generation_mode: Literal["guided_generate", "quick_generate", "structure_only"],
        model_active: bool,
        credential_active: bool,
        model_credential_relation_verified: bool,
        credential_use_allowed: bool,
        selected_target_type: Literal["selected_node", "selected_edge"] | None,
        selected_target_id: str | None,
        selected_target_logical_ref: str | None,
        selected_target_exists: bool,
        selected_target_type_matches: bool,
        selected_target_placement_allowed: bool,
        knowledge_context_fingerprint: str,
        knowledge_resolutions: tuple[CurrentKnowledgeResolution, ...],
    ) -> None:
        if type(actor_id) is not uuid.UUID or type(organization_id) is not uuid.UUID:
            raise TypeError("current scope identity is invalid")
        boolean_values = (
            organization_membership_active,
            workflow_context_current,
            model_active,
            credential_active,
            model_credential_relation_verified,
            credential_use_allowed,
            selected_target_exists,
            selected_target_type_matches,
            selected_target_placement_allowed,
        )
        if any(type(value) is not bool for value in boolean_values):
            raise TypeError("current validation flag is invalid")
        if not isinstance(planner_runtime, PlannerRuntimeFingerprint):
            raise TypeError("current planner runtime is invalid")
        if not isinstance(workflow_context, IntentLogicalTopology):
            raise TypeError("current workflow context is invalid")
        if generation_mode not in _GENERATION_MODES:
            raise ValueError("current generation mode is invalid")
        if selected_target_type not in {None, "selected_node", "selected_edge"}:
            raise ValueError("current target type is invalid")
        target_fields_are_none = (
            selected_target_type is None,
            selected_target_id is None,
            selected_target_logical_ref is None,
        )
        if len(set(target_fields_are_none)) != 1:
            raise ValueError("current target fields must be paired")
        if selected_target_id is not None and (
            type(selected_target_id) is not str
            or not 1 <= len(selected_target_id) <= 255
        ):
            raise ValueError("current target identity is invalid")
        if selected_target_logical_ref is not None and (
            type(selected_target_logical_ref) is not str
            or not 1 <= len(selected_target_logical_ref) <= 255
        ):
            raise ValueError("current target logical ref is invalid")
        if (
            type(knowledge_context_fingerprint) is not str
            or len(knowledge_context_fingerprint) != 64
            or any(
                character not in "abcdef0123456789"
                for character in knowledge_context_fingerprint
            )
        ):
            raise ValueError("current Knowledge fingerprint is invalid")
        if type(knowledge_resolutions) is not tuple or any(
            type(resolution) is not CurrentKnowledgeResolution
            for resolution in knowledge_resolutions
        ):
            raise TypeError("current Knowledge resolutions are invalid")

        for name, value in (
            ("actor_id", actor_id),
            ("organization_id", organization_id),
            (
                "organization_membership_active",
                organization_membership_active,
            ),
            ("workflow_context_current", workflow_context_current),
            ("workflow_context", workflow_context),
            ("planner_runtime", planner_runtime),
            ("generation_mode", generation_mode),
            ("model_active", model_active),
            ("credential_active", credential_active),
            (
                "model_credential_relation_verified",
                model_credential_relation_verified,
            ),
            ("credential_use_allowed", credential_use_allowed),
            ("selected_target_type", selected_target_type),
            ("selected_target_id", selected_target_id),
            ("selected_target_logical_ref", selected_target_logical_ref),
            ("selected_target_exists", selected_target_exists),
            ("selected_target_type_matches", selected_target_type_matches),
            (
                "selected_target_placement_allowed",
                selected_target_placement_allowed,
            ),
            (
                "knowledge_context_fingerprint",
                knowledge_context_fingerprint,
            ),
            ("knowledge_resolutions", knowledge_resolutions),
        ):
            object.__setattr__(self, name, value)
        object.__setattr__(self, "_sealed", True)

    def __setattr__(self, name, value):
        if getattr(self, "_sealed", False):
            raise AttributeError("CurrentRehydrationContext is immutable")
        object.__setattr__(self, name, value)

    def __repr__(self) -> str:
        return "<CurrentRehydrationContext redacted>"

    def __getattribute__(self, name):
        if name == "__getstate__":
            raise AttributeError(name)
        return object.__getattribute__(self, name)

    def __reduce_ex__(self, _protocol):
        raise TypeError("CurrentRehydrationContext is not serializable")


class CachedIntentPlanRehydrator:
    def __init__(
        self,
        current: CurrentRehydrationContext,
        registry: CanonicalIntentTextRegistry | None = None,
    ) -> None:
        if not isinstance(current, CurrentRehydrationContext):
            raise TypeError("current rehydration context is required")
        self._current = current
        self._registry = registry or CanonicalIntentTextRegistry()

    @staticmethod
    def _failure(reason: str) -> IntentRehydrationResult:
        return IntentRehydrationResult(
            status="failure",
            structured_request=None,
            reason=reason,
        )

    def _current_runtime_is_valid(self, context: IntentPlanningContext) -> bool:
        current = self._current
        scope = context.scope
        return bool(
            current.actor_id == scope._actor_id
            and current.organization_id == scope._organization_id
            and current.organization_membership_active
            and current.workflow_context_current
            and current.workflow_context == context.workflow_context
            and current.planner_runtime == context.planner_runtime
            and current.generation_mode == context.generation_mode
            and current.model_active
            and current.credential_active
            and current.model_credential_relation_verified
            and current.credential_use_allowed
            and current.knowledge_context_fingerprint
            == context.knowledge_context_fingerprint
        )

    def _target_is_valid(
        self,
        plan: CachedIntentPlanV1,
        context: IntentPlanningContext,
    ) -> bool:
        if plan.draft_mode == "replace_workflow":
            return context.workflow_context.workflow_present
        if plan.draft_mode != "modify_workflow":
            return True
        placement = plan.edit_placement
        if placement is None or not context.workflow_context.workflow_present:
            return False
        scope = context.scope
        current = self._current
        if (
            scope._selected_target_type is None
            or scope._selected_target_id is None
            or current.selected_target_type != scope._selected_target_type
            or current.selected_target_id != scope._selected_target_id
            or current.selected_target_logical_ref is None
            or placement.target_reference_type != scope._selected_target_type
            or not current.selected_target_exists
            or not current.selected_target_type_matches
            or not current.selected_target_placement_allowed
        ):
            return False
        if scope._selected_target_type == "selected_node":
            return any(
                node.logical_ref == current.selected_target_logical_ref
                for node in context.workflow_context.nodes
            )
        return any(
            edge.logical_ref == current.selected_target_logical_ref
            for edge in context.workflow_context.edges
        )

    def _knowledge_is_valid(self, plan: CachedIntentPlanV1) -> bool:
        requirement_refs = tuple(
            requirement.requirement_ref for requirement in plan.knowledge_requirements
        )
        resolutions = self._current.knowledge_resolutions
        resolution_refs = tuple(
            resolution.requirement_ref for resolution in resolutions
        )
        resolution_ids = tuple(resolution.resolution_id for resolution in resolutions)
        return bool(
            resolution_refs == requirement_refs
            and len(resolution_ids) == len(set(resolution_ids))
            and all(
                resolution.hierarchy_authorized
                and resolution.permission_allowed
                and resolution.lifecycle_active
                and resolution.operationally_ready
                for resolution in resolutions
            )
        )

    @staticmethod
    def _step_key(step: LogicalStepRef) -> tuple[str, int]:
        return (step.capability, step.occurrence)

    def rehydrate(
        self,
        plan: CachedIntentPlanV1,
        context: IntentPlanningContext,
    ) -> IntentRehydrationResult:
        if not isinstance(plan, CachedIntentPlanV1) or not isinstance(
            context, IntentPlanningContext
        ):
            return self._failure("current_context_invalid")
        if plan.contract_versions != context.contract_versions:
            return self._failure("contract_version_mismatch")
        if (
            plan.contract_versions.canonical_text_registry_version
            != self._registry.registry_version
        ):
            return self._failure("contract_version_mismatch")
        if not self._current_runtime_is_valid(context):
            return self._failure("current_context_invalid")
        if not self._target_is_valid(plan, context):
            return self._failure("logical_reference_invalid")
        if not self._knowledge_is_valid(plan):
            return self._failure("current_context_invalid")

        summary = self._registry.project_summary(context.full_safe_message)
        if summary is None:
            return self._failure("summary_projection_failed")

        nonce = uuid.uuid4().hex
        step_ids: dict[tuple[str, int], str] = {}
        planned_steps: list[AgentBuilderPlannedStep] = []
        dependency: str | None = None
        required_capabilities: list[str] = []
        try:
            for index, step in enumerate(plan.logical_steps, start=1):
                purpose = self._registry.purpose_for(step.capability)
                step_id = f"step_{step.capability}_{step.occurrence}_{index}_{nonce}"
                step_ids[self._step_key(step)] = step_id
                planned_steps.append(
                    AgentBuilderPlannedStep(
                        step_id=step_id,
                        capability=step.capability,
                        purpose=purpose,
                        depends_on=[dependency] if dependency else [],
                    )
                )
                dependency = step_id
                capabilities = (
                    ("llm", "knowledge_base")
                    if step.capability == "knowledge_backed_llm"
                    else (step.capability,)
                )
                for capability in capabilities:
                    if capability not in required_capabilities:
                        required_capabilities.append(capability)
        except CanonicalReferenceError:
            return self._failure("catalog_member_missing")

        guidance_hints: list[AgentBuilderParameterGuidanceHint] = []
        try:
            for guidance in plan.parameter_guidance_refs:
                step_id = step_ids.get(self._step_key(guidance.logical_step_ref))
                if step_id is None:
                    return self._failure("logical_reference_invalid")
                capability = guidance.logical_step_ref.capability
                input_type = CAPABILITY_PARAMETER_INPUT_TYPES.get(capability, {}).get(
                    guidance.parameter_key
                )
                if input_type is None:
                    return self._failure("catalog_member_missing")
                safe_label, catalog_input_type = (
                    self._registry.guidance_catalog_context(
                        capability,
                        guidance.parameter_key,
                    )
                )
                if catalog_input_type != input_type:
                    return self._failure("guidance_input_type_incompatible")
                reason, input_guidance = self._registry.render_guidance(
                    reason_ref=guidance.reason_template_ref,
                    input_guidance_ref=(guidance.input_guidance_template_ref),
                    capability=capability,
                    parameter_key=guidance.parameter_key,
                    safe_label=safe_label,
                    input_type=input_type,
                )
                guidance_hints.append(
                    AgentBuilderParameterGuidanceHint(
                        step_id=step_id,
                        parameter_key=guidance.parameter_key,
                        reason=reason,
                        input_guidance=input_guidance,
                    )
                )
        except CanonicalReferenceError:
            return self._failure("canonical_reference_missing")
        except GuidanceInputTypeError:
            return self._failure("guidance_input_type_incompatible")

        knowledge_requirements: list[AgentBuilderKnowledgeRequirement] = []
        pending_resolution: list[AgentBuilderPendingResolution] = []
        try:
            for ordinal, requirement in enumerate(
                plan.knowledge_requirements,
                start=1,
            ):
                current_resolution = self._current.knowledge_resolutions[ordinal - 1]
                target_step_id = step_ids.get(
                    self._step_key(requirement.target_step_ref)
                )
                if target_step_id is None:
                    return self._failure("logical_reference_invalid")
                topics = [
                    self._registry.render_topic(
                        topic_ref,
                        full_safe_message=context.full_safe_message,
                    )
                    for topic_ref in requirement.topic_refs
                ]
                knowledge_requirements.append(
                    AgentBuilderKnowledgeRequirement(
                        requirement_id=requirement.requirement_ref,
                        query_topics=topics,
                        suggested_candidate_handles=list(
                            current_resolution.candidate_handles
                        ),
                        expected_evidence_type=requirement.evidence_kind,
                        required=requirement.required,
                        target_step_ref=target_step_id,
                    )
                )
                pending_resolution.append(
                    AgentBuilderPendingResolution(
                        resolution_id=current_resolution.resolution_id,
                        slot_type="knowledge_base",
                        slot_key="llm.knowledgeBases",
                        blocking=True,
                        target_step_ref=target_step_id,
                    )
                )
        except CanonicalReferenceError:
            return self._failure("canonical_reference_missing")

        knowledge_placements: list[AgentBuilderKnowledgePlacement] = []
        for placement in plan.knowledge_placements:

            def bound(step_ref):
                if step_ref is None:
                    return None
                return step_ids.get(self._step_key(step_ref))

            target_step_id = bound(placement.target_step_ref)
            knowledge_step_id = bound(placement.knowledge_step_ref)
            upstream_step_id = bound(placement.upstream_step_ref)
            downstream_step_id = bound(placement.downstream_step_ref)
            required_refs = (
                (target_step_id,)
                if placement.timing == "after_graph"
                else (
                    target_step_id,
                    knowledge_step_id,
                    upstream_step_id,
                    downstream_step_id,
                )
            )
            if any(value is None for value in required_refs):
                return self._failure("logical_reference_invalid")
            try:
                knowledge_placements.append(
                    AgentBuilderKnowledgePlacement(
                        requirement_id=placement.requirement_ref,
                        timing=placement.timing,
                        effect_kind=placement.effect_kind,
                        target_step_id=target_step_id,
                        knowledge_step_id=knowledge_step_id,
                        upstream_step_id=upstream_step_id,
                        downstream_step_id=downstream_step_id,
                        empty_selection_bridge=placement.empty_selection_bridge,
                    )
                )
            except ValidationError:
                return self._failure("logical_reference_invalid")

        slack_ordinal = 0
        for step in plan.logical_steps:
            if step.capability != "slack_send":
                continue
            slack_ordinal += 1
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id=f"res_slack_{slack_ordinal}_{nonce}",
                    slot_type="other",
                    slot_key="slack.channel",
                    blocking=False,
                    target_step_ref=step_ids[self._step_key(step)],
                )
            )

        first_step_by_capability: dict[str, str] = {}
        for step in plan.logical_steps:
            first_step_by_capability.setdefault(
                step.capability,
                step_ids[self._step_key(step)],
            )
        if {"github_pr_read", "github_pr_comment"}.intersection(
            first_step_by_capability
        ):
            capability = (
                "github_pr_read"
                if "github_pr_read" in first_step_by_capability
                else "github_pr_comment"
            )
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id=f"res_github_1_{nonce}",
                    slot_type="other",
                    slot_key="github.credential_and_target",
                    blocking=False,
                    target_step_ref=first_step_by_capability[capability],
                )
            )
        if "gmail_reply_draft_create" in first_step_by_capability:
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id=f"res_gmail_1_{nonce}",
                    slot_type="other",
                    slot_key="gmail_draft.credential_id",
                    blocking=False,
                    target_step_ref=first_step_by_capability[
                        "gmail_reply_draft_create"
                    ],
                )
            )

        edit_operations: list[AgentBuilderEditOperation] = []
        if plan.edit_placement is not None:
            edit_step_ids = [
                step_ids.get(self._step_key(step))
                for step in plan.edit_placement.step_refs
            ]
            if any(step_id is None for step_id in edit_step_ids):
                return self._failure("logical_reference_invalid")
            edit_operations.append(
                AgentBuilderEditOperation(
                    operation_id=str(uuid.uuid4()),
                    operation="insert",
                    placement=plan.edit_placement.placement,
                    step_refs=[str(step_id) for step_id in edit_step_ids],
                    target=AgentBuilderEditTargetReference(
                        reference_type=(plan.edit_placement.target_reference_type),
                        query=None,
                        source_query=None,
                        destination_query=None,
                        capabilities=[],
                        node_types=[],
                    ),
                )
            )
            pending_resolution.append(
                AgentBuilderPendingResolution(
                    resolution_id=f"res_target_1_{nonce}",
                    slot_type="target",
                    slot_key="edit_operations.0.target",
                    blocking=True,
                    target_step_ref=str(edit_step_ids[0]),
                )
            )

        try:
            structured_request = AgentBuilderStructuredRequest(
                request_type=plan.request_type,
                draft_mode=plan.draft_mode,
                intent_summary=summary,
                planned_steps=planned_steps,
                parameter_guidance_hints=guidance_hints,
                explicit_parameter_values=[],
                knowledge_requirements=knowledge_requirements,
                knowledge_placements=knowledge_placements,
                required_capabilities=required_capabilities,
                pending_resolution=pending_resolution,
                edit_operations=edit_operations,
                missing_information=[],
                unsupported_requests=[],
                risk_flags=list(plan.risk_flags),
            )
        except ValidationError:
            return self._failure("logical_reference_invalid")
        return IntentRehydrationResult(
            status="success",
            structured_request=structured_request,
            reason=None,
        )
