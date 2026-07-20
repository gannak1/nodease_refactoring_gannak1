from __future__ import annotations

import re
import uuid
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    StringConstraints,
    ValidationError,
    model_validator,
)

from apps.gateway.application.agent_builder.intent_cache.catalog_snapshot import (
    CANONICAL_GUIDANCE_REASON_REFS,
    CANONICAL_INPUT_GUIDANCE_REFS,
    CANONICAL_KNOWLEDGE_TOPIC_REFS,
    CAPABILITY_PARAMETER_INPUT_TYPES,
    CATALOG_NODE_ROLES,
)


_SAFE_REFERENCE_LOCATION_PARTS = frozenset(
    {
        "reference",
        "capability",
        "ordered_capabilities",
        "logical_steps",
        "edit_placement",
        "step_refs",
        "integration_actions",
        "parameter_key",
        "reason_template_ref",
        "input_guidance_template_ref",
        "requirement_ref",
        "target_step_ref",
        "topic_refs",
        "contract_versions",
        "normalizer_version",
        "planner_contract_version",
        "canonical_text_registry_version",
        "materializer_version",
    }
)

_SAFE_VALIDATION_LOCATION_PARTS = _SAFE_REFERENCE_LOCATION_PARTS | frozenset(
    {
        "cache_schema_version",
        "draft_mode",
        "effect_kind",
        "empty_selection_bridge",
        "evidence_kind",
        "knowledge_placements",
        "knowledge_requirements",
        "knowledge_step_ref",
        "occurrence",
        "parameter_guidance_refs",
        "placement",
        "request_type",
        "required",
        "risk_flags",
        "schema_version",
        "target_reference_type",
        "timing",
    }
)
_SAFE_VALIDATION_MESSAGE = "intent cache contract validation failed"
_INTEGRATION_CAPABILITY_BY_ACTION = {
    "github.pull_request.read": "github_pr_read",
    "github.pull_request.comment": "github_pr_comment",
}


class _ReferenceContractViolation(ValueError):
    """Internal marker for a semantic reference contract violation."""


def _redacted_validation_error(error: ValidationError) -> ValidationError:
    safe_lines = []
    for item in error.errors(
        include_url=False,
        include_context=True,
        include_input=False,
    ):
        context = item.get("ctx") or {}
        if isinstance(context.get("error"), _ReferenceContractViolation):
            safe_location = ("reference",)
        else:
            safe_location = tuple(
                part
                if isinstance(part, int)
                or part in _SAFE_VALIDATION_LOCATION_PARTS
                else "contract"
                for part in item.get("loc", ())
            )
        safe_lines.append(
            {
                "type": "value_error",
                "loc": safe_location,
                "input": None,
                "ctx": {"error": ValueError(_SAFE_VALIDATION_MESSAGE)},
            }
        )
    if not safe_lines:
        safe_lines.append(
            {
                "type": "value_error",
                "loc": (),
                "input": None,
                "ctx": {"error": ValueError(_SAFE_VALIDATION_MESSAGE)},
            }
        )
    return ValidationError.from_exception_data(
        error.title,
        safe_lines,
        input_type="python",
        hide_input=True,
    )


def _call_with_redacted_validation_error(callback):
    redacted_error = None
    try:
        return callback()
    except ValidationError as error:
        redacted_error = _redacted_validation_error(error)
    raise redacted_error


class _RedactingModelMetaclass(type(BaseModel)):
    def __call__(cls, *args, **kwargs):
        constructor = super().__call__
        return _call_with_redacted_validation_error(
            lambda: constructor(*args, **kwargs)
        )


VersionRef = Annotated[
    str,
    StringConstraints(
        strict=True,
        pattern=r"^[a-z0-9][a-z0-9._:-]{0,127}$",
    ),
]
HexDigest = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^[a-f0-9]{64}$"),
]
RequirementRef = Annotated[
    str,
    StringConstraints(strict=True, pattern=r"^kr_[1-8]$"),
]

CapabilityRef = Literal[
    "answer",
    "code_execution",
    "condition",
    "file_extraction",
    "github_pr_comment",
    "github_pr_read",
    "gmail_reply_draft_create",
    "http_request",
    "knowledge_backed_llm",
    "llm",
    "mail_search",
    "mail_terminal_acknowledgement",
    "schedule_trigger",
    "slack_send",
    "start_input",
    "template_render",
    "variable_extraction",
    "webhook_trigger",
    "workflow_call",
]
NodeTypeRef = Literal[
    "startNode",
    "webhookTrigger",
    "scheduleTrigger",
    "llmNode",
    "workflowNode",
    "codeNode",
    "conditionNode",
    "fileExtractionNode",
    "variableExtractionNode",
    "answerNode",
    "httpRequestNode",
    "slackPostNode",
    "templateNode",
    "githubNode",
    "mailNode",
    "gmailDraftNode",
    "mailAcknowledgeNode",
]
CanonicalKnowledgeTopicRef = Literal["topic.internal_documents.v1"]
CanonicalGuidanceReasonRef = Literal[
    "guidance.reason.delivery_destination_required.v1"
]
CanonicalInputGuidanceRef = Literal[
    "guidance.input.select_slack_channel_id.v1"
]
IntegrationActionRef = Literal[
    "github.pull_request.read",
    "github.pull_request.comment",
]
CacheRiskFlag = Literal[
    "external_action_requested",
    "slack_channel_unresolved",
    "github_configuration_unresolved",
    "gmail_credential_unresolved",
    "external_configuration_unresolved",
]


class _StrictFrozenModel(BaseModel, metaclass=_RedactingModelMetaclass):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )

    @classmethod
    def model_validate(cls, obj, **kwargs):
        validator = super().model_validate
        return _call_with_redacted_validation_error(
            lambda: validator(obj, **kwargs)
        )

    @classmethod
    def model_validate_json(cls, json_data, **kwargs):
        validator = super().model_validate_json
        return _call_with_redacted_validation_error(
            lambda: validator(json_data, **kwargs)
        )

    @classmethod
    def model_validate_strings(cls, obj, **kwargs):
        validator = super().model_validate_strings
        return _call_with_redacted_validation_error(
            lambda: validator(obj, **kwargs)
        )


class LogicalStepRef(_StrictFrozenModel):
    capability: CapabilityRef
    occurrence: StrictInt = Field(ge=1, le=32)


class CachedEditPlacement(_StrictFrozenModel):
    placement: Literal["before", "after", "between"]
    target_reference_type: Literal["selected_node", "selected_edge"]
    step_refs: tuple[LogicalStepRef, ...] = Field(min_length=1, max_length=32)

    @model_validator(mode="after")
    def validate_target_kind(self):
        if self.placement in {"before", "after"}:
            if self.target_reference_type != "selected_node":
                raise _ReferenceContractViolation(
                    "selected node placement required"
                )
        elif self.target_reference_type != "selected_edge":
            raise _ReferenceContractViolation("selected edge placement required")
        return self


class CachedKnowledgeRequirement(_StrictFrozenModel):
    requirement_ref: RequirementRef
    required: StrictBool
    evidence_kind: Literal["policy_or_reference"]
    target_step_ref: LogicalStepRef
    topic_refs: tuple[CanonicalKnowledgeTopicRef, ...] = Field(
        min_length=1,
        max_length=20,
    )

    @model_validator(mode="after")
    def validate_topic_refs(self):
        if len(self.topic_refs) != len(set(self.topic_refs)):
            raise _ReferenceContractViolation("duplicate topic reference")
        if not set(self.topic_refs).issubset(CANONICAL_KNOWLEDGE_TOPIC_REFS):
            raise _ReferenceContractViolation("unknown topic reference")
        return self


class CachedKnowledgePlacement(_StrictFrozenModel):
    requirement_ref: RequirementRef
    timing: Literal["before_graph", "after_graph"]
    effect_kind: Literal["insert_step", "binding_only"]
    target_step_ref: LogicalStepRef | None = None
    knowledge_step_ref: LogicalStepRef | None = None
    upstream_step_ref: LogicalStepRef | None = None
    downstream_step_ref: LogicalStepRef | None = None
    empty_selection_bridge: Literal["connect_upstream_to_downstream"] | None = None

    @model_validator(mode="after")
    def validate_placement(self):
        if self.timing == "after_graph":
            if self.effect_kind != "binding_only" or self.target_step_ref is None:
                raise ValueError("after graph binding target required")
            if any(
                value is not None
                for value in (
                    self.knowledge_step_ref,
                    self.upstream_step_ref,
                    self.downstream_step_ref,
                    self.empty_selection_bridge,
                )
            ):
                raise ValueError("after graph topology reference forbidden")
        else:
            if self.effect_kind != "insert_step":
                raise ValueError("before graph insert required")
            if any(
                value is None
                for value in (
                    self.target_step_ref,
                    self.knowledge_step_ref,
                    self.upstream_step_ref,
                    self.downstream_step_ref,
                    self.empty_selection_bridge,
                )
            ):
                raise ValueError("before graph topology references required")
        return self


class CachedParameterGuidanceRef(_StrictFrozenModel):
    logical_step_ref: LogicalStepRef
    parameter_key: StrictStr = Field(min_length=1, max_length=128)
    reason_template_ref: CanonicalGuidanceReasonRef
    input_guidance_template_ref: CanonicalInputGuidanceRef

    @model_validator(mode="after")
    def validate_applicability(self):
        parameters = CAPABILITY_PARAMETER_INPUT_TYPES.get(
            self.logical_step_ref.capability,
            {},
        )
        if self.parameter_key not in parameters:
            raise _ReferenceContractViolation("unknown capability parameter")
        if self.reason_template_ref not in CANONICAL_GUIDANCE_REASON_REFS:
            raise _ReferenceContractViolation(
                "unknown guidance reason reference"
            )
        if self.input_guidance_template_ref not in CANONICAL_INPUT_GUIDANCE_REFS:
            raise _ReferenceContractViolation(
                "unknown input guidance reference"
            )
        if not (
            self.logical_step_ref.capability == "slack_send"
            and self.parameter_key == "channel"
            and parameters[self.parameter_key] == "text"
        ):
            raise _ReferenceContractViolation(
                "guidance reference is not applicable"
            )
        return self


class IntentPlanContractVersions(_StrictFrozenModel):
    normalizer_version: VersionRef
    cache_schema_version: Literal[1]
    planner_contract_version: VersionRef
    catalog_version: Literal[3]
    canonical_text_registry_version: Literal["intent-text-v1"]
    materializer_version: VersionRef


class CachedIntentPlanV1(_StrictFrozenModel):
    schema_version: Literal[1]
    request_type: Literal["new_workflow", "modify_workflow"]
    draft_mode: Literal["new_workflow", "modify_workflow", "replace_workflow"]
    ordered_capabilities: tuple[CapabilityRef, ...] = Field(
        min_length=1,
        max_length=32,
    )
    logical_steps: tuple[LogicalStepRef, ...] = Field(
        min_length=1,
        max_length=32,
    )
    edit_placement: CachedEditPlacement | None = None
    integration_actions: tuple[IntegrationActionRef, ...] = Field(
        default=(),
        max_length=16,
    )
    parameter_guidance_refs: tuple[CachedParameterGuidanceRef, ...] = Field(
        default=(),
        max_length=128,
    )
    knowledge_requirements: tuple[CachedKnowledgeRequirement, ...] = Field(
        default=(),
        max_length=8,
    )
    knowledge_placements: tuple[CachedKnowledgePlacement, ...] = Field(
        default=(),
        max_length=8,
    )
    risk_flags: tuple[CacheRiskFlag, ...] = Field(default=(), max_length=8)
    contract_versions: IntentPlanContractVersions

    @model_validator(mode="after")
    def validate_plan(self):
        valid_pair = (
            (self.request_type == "new_workflow" and self.draft_mode == "new_workflow")
            or (
                self.request_type == "modify_workflow"
                and self.draft_mode in {"modify_workflow", "replace_workflow"}
            )
        )
        if not valid_pair:
            raise ValueError("request and draft mode mismatch")
        if self.draft_mode == "modify_workflow":
            if self.edit_placement is None:
                raise ValueError("selected edit placement required")
        elif self.edit_placement is not None:
            raise ValueError("edit placement forbidden")

        if len(self.logical_steps) != len(self.ordered_capabilities):
            raise _ReferenceContractViolation(
                "logical step cardinality mismatch"
            )
        occurrences: dict[str, int] = {}
        for capability, step in zip(
            self.ordered_capabilities,
            self.logical_steps,
            strict=True,
        ):
            occurrences[capability] = occurrences.get(capability, 0) + 1
            if (
                step.capability != capability
                or step.occurrence != occurrences[capability]
            ):
                raise _ReferenceContractViolation(
                    "logical step sequence mismatch"
                )

        step_members = {
            (step.capability, step.occurrence) for step in self.logical_steps
        }
        if self.edit_placement is not None and any(
            (step.capability, step.occurrence) not in step_members
            for step in self.edit_placement.step_refs
        ):
            raise _ReferenceContractViolation(
                "edit step reference is not a plan member"
            )

        if len(self.integration_actions) != len(set(self.integration_actions)):
            raise _ReferenceContractViolation("duplicate integration action")
        action_members = set(self.integration_actions)
        capability_members = set(self.ordered_capabilities)
        for action, capability in _INTEGRATION_CAPABILITY_BY_ACTION.items():
            if (action in action_members) != (capability in capability_members):
                raise _ReferenceContractViolation(
                    "integration action and capability mismatch"
                )
        if len(self.risk_flags) != len(set(self.risk_flags)):
            raise ValueError("duplicate risk flag")

        guidance_keys: set[tuple[str, int, str]] = set()
        for guidance in self.parameter_guidance_refs:
            step_key = (
                guidance.logical_step_ref.capability,
                guidance.logical_step_ref.occurrence,
            )
            if step_key not in step_members:
                raise _ReferenceContractViolation(
                    "guidance step reference is not a plan member"
                )
            key = (*step_key, guidance.parameter_key)
            if key in guidance_keys:
                raise _ReferenceContractViolation(
                    "duplicate parameter guidance"
                )
            guidance_keys.add(key)

        requirements: dict[str, CachedKnowledgeRequirement] = {}
        for requirement in self.knowledge_requirements:
            if requirement.requirement_ref in requirements:
                raise _ReferenceContractViolation(
                    "duplicate knowledge requirement"
                )
            step_key = (
                requirement.target_step_ref.capability,
                requirement.target_step_ref.occurrence,
            )
            if step_key not in step_members:
                raise _ReferenceContractViolation(
                    "knowledge target is not a plan member"
                )
            if requirement.target_step_ref.capability != "knowledge_backed_llm":
                raise _ReferenceContractViolation(
                    "knowledge topic target is not applicable"
                )
            requirements[requirement.requirement_ref] = requirement

        placement_refs: set[str] = set()
        for placement in self.knowledge_placements:
            if placement.requirement_ref not in requirements:
                raise _ReferenceContractViolation(
                    "knowledge placement requirement is missing"
                )
            if placement.requirement_ref in placement_refs:
                raise _ReferenceContractViolation(
                    "duplicate knowledge placement"
                )
            placement_refs.add(placement.requirement_ref)
            requirement = requirements[placement.requirement_ref]
            if placement.target_step_ref != requirement.target_step_ref:
                raise _ReferenceContractViolation(
                    "knowledge placement target mismatch"
                )
            if (
                placement.timing == "before_graph"
                and placement.knowledge_step_ref != requirement.target_step_ref
            ):
                raise _ReferenceContractViolation(
                    "knowledge insertion step mismatch"
                )
            for step in (
                placement.target_step_ref,
                placement.knowledge_step_ref,
                placement.upstream_step_ref,
                placement.downstream_step_ref,
            ):
                if step is not None and (
                    step.capability,
                    step.occurrence,
                ) not in step_members:
                    raise _ReferenceContractViolation(
                        "knowledge topology reference is not a plan member"
                    )
        if placement_refs != set(requirements):
            raise _ReferenceContractViolation(
                "knowledge requirement placement is missing"
            )
        return self


class IntentLogicalNode(_StrictFrozenModel):
    logical_ref: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^n_[1-9][0-9]*$"),
    ]
    node_type: NodeTypeRef
    safe_label: StrictStr = Field(min_length=1, max_length=255)
    role: Literal["entry", "intermediate", "branch", "terminal"]

    @model_validator(mode="after")
    def validate_catalog_role(self):
        if CATALOG_NODE_ROLES.get(self.node_type) != self.role:
            raise ValueError("node role mismatch")
        return self


class IntentLogicalEdge(_StrictFrozenModel):
    logical_ref: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^e_[1-9][0-9]*$"),
    ]
    source_node_ref: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^n_[1-9][0-9]*$"),
    ]
    target_node_ref: Annotated[
        str,
        StringConstraints(strict=True, pattern=r"^n_[1-9][0-9]*$"),
    ]
    source_handle_kind: Literal[
        "standard",
        "condition_case",
        "condition_default",
    ]
    source_handle_ordinal: StrictInt | None = Field(default=None, ge=1, le=32)
    target_handle_kind: Literal["standard"]

    @model_validator(mode="after")
    def validate_handle(self):
        if self.source_node_ref == self.target_node_ref:
            raise ValueError("self edge forbidden")
        if self.source_handle_kind == "condition_case":
            if self.source_handle_ordinal is None:
                raise ValueError("condition case ordinal required")
        elif self.source_handle_ordinal is not None:
            raise ValueError("source handle ordinal forbidden")
        return self


class IntentLogicalTopology(_StrictFrozenModel):
    workflow_present: StrictBool
    nodes: tuple[IntentLogicalNode, ...]
    edges: tuple[IntentLogicalEdge, ...]

    @model_validator(mode="after")
    def validate_topology(self):
        if not self.workflow_present and (self.nodes or self.edges):
            raise ValueError("absent workflow topology must be empty")
        for ordinal, node in enumerate(self.nodes, start=1):
            if node.logical_ref != f"n_{ordinal}":
                raise ValueError("node logical ordinal mismatch")
        node_refs = {node.logical_ref for node in self.nodes}
        for ordinal, edge in enumerate(self.edges, start=1):
            if edge.logical_ref != f"e_{ordinal}":
                raise ValueError("edge logical ordinal mismatch")
            if (
                edge.source_node_ref not in node_refs
                or edge.target_node_ref not in node_refs
            ):
                raise ValueError("dangling logical edge")
            source_index = int(edge.source_node_ref.removeprefix("n_")) - 1
            source_role = self.nodes[source_index].role
            if (
                edge.source_handle_kind.startswith("condition_")
                and source_role != "branch"
            ):
                raise ValueError("condition handle requires branch source")
        return self


class PlannerRuntimeFingerprint(_StrictFrozenModel):
    provider_ref: Literal["openai", "google", "anthropic"]
    model_relation_fingerprint: HexDigest
    credential_relation_fingerprint: HexDigest


class EphemeralCacheScope:
    __slots__ = (
        "_actor_id",
        "_organization_id",
        "_selected_target_type",
        "_selected_target_id",
    )
    __hash__ = None

    def __init__(
        self,
        *,
        actor_id: uuid.UUID,
        organization_id: uuid.UUID,
        selected_target_type: Literal["selected_node", "selected_edge"] | None,
        selected_target_id: str | None,
    ) -> None:
        if type(actor_id) is not uuid.UUID or type(organization_id) is not uuid.UUID:
            raise TypeError("ephemeral scope identity must be UUID")
        if (selected_target_type is None) != (selected_target_id is None):
            raise ValueError("selected target fields must be paired")
        if selected_target_type not in {None, "selected_node", "selected_edge"}:
            raise ValueError("invalid selected target type")
        if selected_target_id is not None and (
            type(selected_target_id) is not str
            or not 1 <= len(selected_target_id) <= 255
        ):
            raise ValueError("invalid selected target identity")
        object.__setattr__(self, "_actor_id", actor_id)
        object.__setattr__(self, "_organization_id", organization_id)
        object.__setattr__(self, "_selected_target_type", selected_target_type)
        object.__setattr__(self, "_selected_target_id", selected_target_id)

    def __repr__(self) -> str:
        return "<EphemeralCacheScope redacted>"

    def __getattribute__(self, name):
        if name == "__getstate__":
            raise AttributeError(name)
        return object.__getattribute__(self, name)

    def __reduce_ex__(self, _protocol):
        raise TypeError("EphemeralCacheScope is not serializable")


class IntentPlanningContext:
    __slots__ = (
        "full_safe_message",
        "workflow_context",
        "planner_runtime",
        "generation_mode",
        "knowledge_context_fingerprint",
        "contract_versions",
        "scope",
    )
    __hash__ = None

    def __init__(
        self,
        *,
        full_safe_message: str,
        workflow_context: IntentLogicalTopology,
        planner_runtime: PlannerRuntimeFingerprint,
        generation_mode: Literal[
            "guided_generate",
            "quick_generate",
            "structure_only",
        ],
        knowledge_context_fingerprint: str,
        contract_versions: IntentPlanContractVersions,
        scope: EphemeralCacheScope,
    ) -> None:
        if (
            type(full_safe_message) is not str
            or not 1 <= len(full_safe_message) <= 4000
        ):
            raise ValueError("invalid full safe message")
        if not isinstance(workflow_context, IntentLogicalTopology):
            raise TypeError("invalid logical topology")
        if not isinstance(planner_runtime, PlannerRuntimeFingerprint):
            raise TypeError("invalid planner runtime fingerprint")
        if generation_mode not in {
            "guided_generate",
            "quick_generate",
            "structure_only",
        }:
            raise ValueError("invalid generation mode")
        if type(knowledge_context_fingerprint) is not str or re.fullmatch(
            r"[a-f0-9]{64}",
            knowledge_context_fingerprint,
        ) is None:
            raise ValueError("invalid knowledge context fingerprint")
        if not isinstance(contract_versions, IntentPlanContractVersions):
            raise TypeError("invalid contract versions")
        if not isinstance(scope, EphemeralCacheScope):
            raise TypeError("invalid ephemeral scope")
        object.__setattr__(self, "full_safe_message", full_safe_message)
        object.__setattr__(self, "workflow_context", workflow_context)
        object.__setattr__(self, "planner_runtime", planner_runtime)
        object.__setattr__(self, "generation_mode", generation_mode)
        object.__setattr__(
            self,
            "knowledge_context_fingerprint",
            knowledge_context_fingerprint,
        )
        object.__setattr__(self, "contract_versions", contract_versions)
        object.__setattr__(self, "scope", scope)

    def __repr__(self) -> str:
        return "<IntentPlanningContext redacted>"

    def __getattribute__(self, name):
        if name == "__getstate__":
            raise AttributeError(name)
        return object.__getattribute__(self, name)

    def __reduce_ex__(self, _protocol):
        raise TypeError("IntentPlanningContext is not serializable")


class IntentCacheKey(_StrictFrozenModel):
    namespace: Literal["agent-builder:intent-plan"]
    key_version: VersionRef
    digest: HexDigest


class IntentNormalizationResult(_StrictFrozenModel):
    status: Literal["eligible", "bypass"]
    intent_signature: HexDigest | None = None
    reason: Literal[
        "sensitive_input",
        "explicit_value_suspected",
        "unknown_token_sequence",
        "ambiguous_target",
        "unsupported_request_shape",
        "normalizer_disabled",
        "input_projection_truncated",
        "graph_projection_incomplete",
    ] | None = None
    normalizer_version: VersionRef
    sensitive_input_detected: StrictBool

    @model_validator(mode="after")
    def validate_result(self):
        if self.status == "eligible":
            if (
                self.intent_signature is None
                or self.reason is not None
                or self.sensitive_input_detected
            ):
                raise ValueError("invalid eligible normalization result")
        else:
            if self.intent_signature is not None or self.reason is None:
                raise ValueError("invalid bypass normalization result")
            if self.sensitive_input_detected != (self.reason == "sensitive_input"):
                raise ValueError("sensitive input flag mismatch")
        return self


class IntentPlanLoadResult(_StrictFrozenModel):
    status: Literal["hit", "miss", "invalid", "unavailable"]
    plan: CachedIntentPlanV1 | None = None
    reason: Literal[
        "not_found",
        "invalid_cached_plan",
        "cache_unavailable",
    ] | None = None

    @model_validator(mode="after")
    def validate_result(self):
        expected = {
            "hit": (True, None),
            "miss": (False, "not_found"),
            "invalid": (False, "invalid_cached_plan"),
            "unavailable": (False, "cache_unavailable"),
        }[self.status]
        if (self.plan is not None, self.reason) != expected:
            raise ValueError("invalid load result")
        return self


class IntentPlanSaveResult(_StrictFrozenModel):
    status: Literal["stored", "unavailable"]
    reason: Literal["cache_unavailable"] | None = None

    @model_validator(mode="after")
    def validate_result(self):
        expected_reason = None if self.status == "stored" else "cache_unavailable"
        if self.reason != expected_reason:
            raise ValueError("invalid save result")
        return self


class CacheBoundaryDecision(_StrictFrozenModel):
    outcome: Literal["hit", "miss", "bypass", "error"]
    plan: CachedIntentPlanV1 | None = None
    reason: Literal[
        "not_found",
        "invalid_cached_plan",
        "rehydration_failed",
        "feature_disabled",
        "normalization_bypass",
        "cache_unavailable",
    ] | None = None

    @model_validator(mode="after")
    def validate_decision(self):
        if self.outcome == "hit":
            valid = self.plan is not None and self.reason is None
        elif self.outcome == "miss":
            valid = self.plan is None and self.reason in {
                None,
                "not_found",
                "invalid_cached_plan",
                "rehydration_failed",
            }
        elif self.outcome == "bypass":
            valid = self.plan is None and self.reason in {
                "feature_disabled",
                "normalization_bypass",
            }
        else:
            valid = self.plan is None and self.reason == "cache_unavailable"
        if not valid:
            raise ValueError("invalid cache boundary decision")
        return self
