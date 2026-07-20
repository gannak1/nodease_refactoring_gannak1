import dataclasses
import json
import pickle
import uuid

import pytest
from pydantic import ValidationError

from apps.gateway.application.agent_builder.intent_cache import (
    CacheBoundaryDecision,
    CachedIntentPlanV1,
    EphemeralCacheScope,
    IntentCacheKey,
    IntentNormalizationResult,
    IntentPlanLoadResult,
    IntentPlanSaveResult,
    IntentPlanningContext,
    IntentRehydrationResult,
)
from apps.gateway.application.agent_builder.intent_cache.catalog_snapshot import (
    AGENT_BUILDER_NODE_SNAPSHOT,
    CANONICAL_GUIDANCE_REASON_REFS,
    CANONICAL_INPUT_GUIDANCE_REFS,
    CANONICAL_KNOWLEDGE_TOPIC_REFS,
    CAPABILITY_PURPOSES,
    SUMMARY_PROJECTION_DESCRIPTOR,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedEditPlacement,
    CachedKnowledgePlacement,
    CachedKnowledgeRequirement,
    CachedParameterGuidanceRef,
    IntentLogicalEdge,
    IntentLogicalNode,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    LogicalStepRef,
    PlannerRuntimeFingerprint,
)
from apps.shared.schemas.agent_builder import AgentBuilderStructuredRequest
from apps.shared.services.workflow_node_catalog import load_workflow_node_catalog


_HEX_A = "a" * 64
_HEX_B = "b" * 64


def _versions() -> IntentPlanContractVersions:
    return IntentPlanContractVersions(
        normalizer_version="normalizer-v1",
        cache_schema_version=1,
        planner_contract_version="planner-v1",
        catalog_version=3,
        canonical_text_registry_version="intent-text-v1",
        materializer_version="materializer-v1",
    )


def _steps(*capabilities: str) -> tuple[LogicalStepRef, ...]:
    occurrences: dict[str, int] = {}
    result = []
    for capability in capabilities:
        occurrences[capability] = occurrences.get(capability, 0) + 1
        result.append(
            LogicalStepRef(
                capability=capability,
                occurrence=occurrences[capability],
            )
        )
    return tuple(result)


def minimal_plan(**overrides) -> CachedIntentPlanV1:
    values = {
        "schema_version": 1,
        "request_type": "new_workflow",
        "draft_mode": "new_workflow",
        "ordered_capabilities": ("start_input", "answer"),
        "logical_steps": _steps("start_input", "answer"),
        "edit_placement": None,
        "integration_actions": (),
        "parameter_guidance_refs": (),
        "knowledge_requirements": (),
        "knowledge_placements": (),
        "risk_flags": (),
        "contract_versions": _versions(),
    }
    values.update(overrides)
    return CachedIntentPlanV1(**values)


def _structured_request() -> AgentBuilderStructuredRequest:
    return AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="safe summary",
    )


def _context(message: str = "입력과 응답 workflow를 만들어줘") -> IntentPlanningContext:
    scope = EphemeralCacheScope(
        actor_id=uuid.uuid4(),
        organization_id=uuid.uuid4(),
        selected_target_type=None,
        selected_target_id=None,
    )
    topology = IntentLogicalTopology(
        workflow_present=True,
        nodes=(
            IntentLogicalNode(
                logical_ref="n_1",
                node_type="startNode",
                safe_label="입력",
                role="entry",
            ),
            IntentLogicalNode(
                logical_ref="n_2",
                node_type="answerNode",
                safe_label="응답",
                role="terminal",
            ),
        ),
        edges=(
            IntentLogicalEdge(
                logical_ref="e_1",
                source_node_ref="n_1",
                target_node_ref="n_2",
                source_handle_kind="standard",
                source_handle_ordinal=None,
                target_handle_kind="standard",
            ),
        ),
    )
    return IntentPlanningContext(
        full_safe_message=message,
        workflow_context=topology,
        planner_runtime=PlannerRuntimeFingerprint(
            provider_ref="openai",
            model_relation_fingerprint=_HEX_A,
            credential_relation_fingerprint=_HEX_B,
        ),
        generation_mode="guided_generate",
        knowledge_context_fingerprint="c" * 64,
        contract_versions=_versions(),
        scope=scope,
    )


def test_minimal_plan_is_strict_frozen_and_preserves_semantic_order():
    plan = minimal_plan(
        ordered_capabilities=("start_input", "llm", "llm", "answer"),
        logical_steps=_steps("start_input", "llm", "llm", "answer"),
    )

    assert plan.ordered_capabilities == (
        "start_input",
        "llm",
        "llm",
        "answer",
    )
    assert tuple(step.occurrence for step in plan.logical_steps) == (1, 1, 2, 1)
    with pytest.raises(ValidationError):
        plan.request_type = "modify_workflow"


@pytest.mark.parametrize(
    "overrides",
    [
        {"request_type": "clarification"},
        {"request_type": "new_workflow", "draft_mode": "modify_workflow"},
        {"ordered_capabilities": ()},
        {"ordered_capabilities": ("unknown_capability",)},
        {
            "ordered_capabilities": ("start_input", "answer"),
            "logical_steps": _steps("answer", "start_input"),
        },
        {
            "ordered_capabilities": ("llm", "llm"),
            "logical_steps": (
                LogicalStepRef(capability="llm", occurrence=1),
                LogicalStepRef(capability="llm", occurrence=1),
            ),
        },
    ],
)
def test_plan_rejects_unsupported_pairs_members_and_logical_occurrences(overrides):
    with pytest.raises(ValidationError):
        minimal_plan(**overrides)


def test_plan_and_nested_contracts_forbid_unknown_fields():
    with pytest.raises(ValidationError):
        CachedIntentPlanV1(
            **minimal_plan().model_dump(),
            graph={"nodes": []},
        )
    with pytest.raises(ValidationError):
        LogicalStepRef(capability="answer", occurrence=1, node_id="node-1")


def test_modify_plan_accepts_only_selected_target_and_replace_has_no_target():
    step_refs = _steps("llm")
    placement = CachedEditPlacement(
        placement="after",
        target_reference_type="selected_node",
        step_refs=step_refs,
    )
    modify = minimal_plan(
        request_type="modify_workflow",
        draft_mode="modify_workflow",
        ordered_capabilities=("llm",),
        logical_steps=step_refs,
        edit_placement=placement,
    )
    replace = minimal_plan(
        request_type="modify_workflow",
        draft_mode="replace_workflow",
        edit_placement=None,
    )

    assert modify.edit_placement == placement
    assert replace.edit_placement is None
    with pytest.raises(ValidationError):
        CachedEditPlacement(
            placement="after",
            target_reference_type="natural_language_node",
            step_refs=step_refs,
        )
    with pytest.raises(ValidationError):
        minimal_plan(
            request_type="modify_workflow",
            draft_mode="replace_workflow",
            edit_placement=placement,
        )


def test_knowledge_and_guidance_refs_are_closed_and_context_applicable():
    capabilities = ("start_input", "knowledge_backed_llm", "slack_send", "answer")
    steps = _steps(*capabilities)
    plan = minimal_plan(
        ordered_capabilities=capabilities,
        logical_steps=steps,
        integration_actions=(),
        parameter_guidance_refs=(
            CachedParameterGuidanceRef(
                logical_step_ref=steps[2],
                parameter_key="channel",
                reason_template_ref=(
                    "guidance.reason.delivery_destination_required.v1"
                ),
                input_guidance_template_ref=(
                    "guidance.input.select_slack_channel_id.v1"
                ),
            ),
        ),
        knowledge_requirements=(
            CachedKnowledgeRequirement(
                requirement_ref="kr_1",
                required=True,
                evidence_kind="policy_or_reference",
                target_step_ref=steps[1],
                topic_refs=("topic.internal_documents.v1",),
            ),
        ),
        knowledge_placements=(
            CachedKnowledgePlacement(
                requirement_ref="kr_1",
                timing="after_graph",
                effect_kind="binding_only",
                target_step_ref=steps[1],
            ),
        ),
    )

    assert plan.parameter_guidance_refs[0].parameter_key == "channel"
    assert plan.knowledge_requirements[0].topic_refs == (
        "topic.internal_documents.v1",
    )

    with pytest.raises(ValidationError):
        minimal_plan(
            ordered_capabilities=("llm",),
            logical_steps=_steps("llm"),
            knowledge_requirements=(
                CachedKnowledgeRequirement(
                    requirement_ref="kr_1",
                    required=True,
                    evidence_kind="policy_or_reference",
                    target_step_ref=_steps("llm")[0],
                    topic_refs=("topic.internal_documents.v1",),
                ),
            ),
        )
    with pytest.raises(ValidationError):
        CachedParameterGuidanceRef(
            logical_step_ref=_steps("answer")[0],
            parameter_key="channel",
            reason_template_ref="guidance.reason.unknown.v1",
            input_guidance_template_ref=(
                "guidance.input.select_slack_channel_id.v1"
            ),
        )


def test_catalog_snapshot_matches_current_catalog_v3_exactly():
    catalog = load_workflow_node_catalog()
    current = tuple(
        (
            str(node["node_type"]),
            str(node["connection_policy"]["role"]),
            tuple(map(str, node["capabilities"])),
            tuple(
                (str(parameter["key"]), str(parameter["input_type"]))
                for parameter in node["parameters"]
            ),
        )
        for node in catalog["nodes"]
        if node.get("implemented") is True
        and node.get("agent_builder_supported") is True
    )
    snapshot = tuple(
        (
            node.node_type,
            node.role,
            node.capabilities,
            node.parameter_input_types,
        )
        for node in AGENT_BUILDER_NODE_SNAPSHOT
    )

    assert catalog["version"] == 3
    assert snapshot == current


def test_canonical_text_and_purpose_snapshots_are_exact_and_complete():
    assert CANONICAL_KNOWLEDGE_TOPIC_REFS == frozenset(
        {"topic.internal_documents.v1"}
    )
    assert CANONICAL_GUIDANCE_REASON_REFS == frozenset(
        {"guidance.reason.delivery_destination_required.v1"}
    )
    assert CANONICAL_INPUT_GUIDANCE_REFS == frozenset(
        {"guidance.input.select_slack_channel_id.v1"}
    )
    assert SUMMARY_PROJECTION_DESCRIPTOR == {
        "projection_id": "summary.current_safe_message.v1",
        "source": "IntentPlanningContext.full_safe_message",
        "whitespace_profile": "python-split-v1",
        "redaction_profile": "agent-builder-safe-summary-v1",
        "max_codepoints": 240,
        "failure": "summary_projection_failed",
        "provider_summary": "excluded",
        "persistence": "none",
    }
    assert len(CAPABILITY_PURPOSES) == 19
    assert CAPABILITY_PURPOSES["start_input"] == "사용자 입력을 받습니다."
    assert CAPABILITY_PURPOSES["knowledge_backed_llm"] == (
        "Knowledge Base 근거로 입력을 분석하고 결과를 생성합니다."
    )
    assert CAPABILITY_PURPOSES["answer"] == (
        "이전 단계 결과를 응답으로 반환합니다."
    )


def test_transient_context_preserves_request_specific_messages_and_topology():
    first = _context("첫 번째 safe request")
    second = _context("두 번째 safe request")

    assert first.full_safe_message == "첫 번째 safe request"
    assert second.full_safe_message == "두 번째 safe request"
    assert first.workflow_context.nodes[0].logical_ref == "n_1"
    assert first is not second


@pytest.mark.parametrize("factory", [json.dumps, vars, dataclasses.asdict, pickle.dumps])
def test_transient_context_and_scope_reject_accidental_serialization(factory):
    context = _context()

    with pytest.raises(TypeError):
        factory(context)
    with pytest.raises(TypeError):
        factory(context.scope)
    assert not hasattr(context, "model_dump")
    assert not hasattr(context, "dict")
    assert not hasattr(context.scope, "actor_id")
    assert repr(context) == "<IntentPlanningContext redacted>"
    assert repr(context.scope) == "<EphemeralCacheScope redacted>"
    with pytest.raises(TypeError):
        hash(context)


def test_transient_context_rejects_invalid_scope_topology_runtime_and_mode():
    with pytest.raises((TypeError, ValueError)):
        EphemeralCacheScope(
            actor_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            selected_target_type="selected_node",
            selected_target_id=None,
        )
    with pytest.raises(ValidationError):
        IntentLogicalNode(
            logical_ref="n_2",
            node_type="startNode",
            safe_label="입력",
            role="entry",
        )
    with pytest.raises(ValidationError):
        PlannerRuntimeFingerprint(
            provider_ref="unknown",
            model_relation_fingerprint=_HEX_A,
            credential_relation_fingerprint=_HEX_B,
        )
    context = _context()
    with pytest.raises((TypeError, ValueError)):
        IntentPlanningContext(
            full_safe_message=context.full_safe_message,
            workflow_context=context.workflow_context,
            planner_runtime=context.planner_runtime,
            generation_mode="configure_and_generate",
            knowledge_context_fingerprint=context.knowledge_context_fingerprint,
            contract_versions=context.contract_versions,
            scope=context.scope,
        )


def test_result_contracts_preserve_closed_status_and_union_invariants():
    plan = minimal_plan()
    structured = _structured_request()

    assert IntentNormalizationResult(
        status="eligible",
        intent_signature=_HEX_A,
        reason=None,
        normalizer_version="normalizer-v1",
        sensitive_input_detected=False,
    ).status == "eligible"
    assert IntentNormalizationResult(
        status="bypass",
        intent_signature=None,
        reason="sensitive_input",
        normalizer_version="normalizer-v1",
        sensitive_input_detected=True,
    ).status == "bypass"
    assert IntentRehydrationResult(
        status="success",
        structured_request=structured,
        reason=None,
    ).structured_request is structured
    assert IntentRehydrationResult(
        status="failure",
        structured_request=None,
        reason="summary_projection_failed",
    ).reason == "summary_projection_failed"
    assert IntentPlanLoadResult(status="hit", plan=plan, reason=None).plan is plan
    assert IntentPlanLoadResult(
        status="miss", plan=None, reason="not_found"
    ).status == "miss"
    assert IntentPlanSaveResult(status="stored", reason=None).status == "stored"

    invalid_values = (
        lambda: IntentNormalizationResult(
            status="eligible",
            intent_signature=None,
            reason="normalizer_disabled",
            normalizer_version="normalizer-v1",
            sensitive_input_detected=False,
        ),
        lambda: IntentRehydrationResult(
            status="failure", structured_request=structured, reason=None
        ),
        lambda: IntentPlanLoadResult(status="miss", plan=plan, reason="not_found"),
        lambda: IntentPlanSaveResult(
            status="unavailable", reason=None
        ),
    )
    for factory in invalid_values:
        with pytest.raises(ValidationError):
            factory()


def test_cache_key_and_boundary_decision_are_strict_closed_contracts():
    plan = minimal_plan()
    key = IntentCacheKey(
        namespace="agent-builder:intent-plan",
        key_version="key-v1",
        digest=_HEX_A,
    )
    assert key.digest == _HEX_A
    assert CacheBoundaryDecision(outcome="hit", plan=plan, reason=None).plan is plan
    assert CacheBoundaryDecision(
        outcome="bypass", plan=None, reason="feature_disabled"
    ).reason == "feature_disabled"

    with pytest.raises(ValidationError):
        IntentCacheKey(
            namespace="agent-builder:intent-plan",
            key_version="key-v1",
            digest="not-a-digest",
        )
    with pytest.raises(ValidationError):
        CacheBoundaryDecision(outcome="hit", plan=None, reason=None)
    with pytest.raises(ValidationError):
        CacheBoundaryDecision(
            outcome="error", plan=None, reason="not_found"
        )


def test_validation_errors_hide_sensitive_input_values():
    unsafe = "api_key=" + ("x" * 24)

    with pytest.raises(ValidationError) as captured:
        CachedIntentPlanV1(
            **minimal_plan().model_dump(),
            intent_summary=unsafe,
        )

    rendered = str(captured.value) + repr(captured.value)
    assert unsafe not in rendered
    assert "x" * 24 not in rendered
