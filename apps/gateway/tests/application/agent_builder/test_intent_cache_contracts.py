import dataclasses
import json
import pickle
import uuid
from pathlib import Path

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


ROOT = Path(__file__).resolve().parents[5]


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
    with pytest.raises(ValidationError):
        CachedKnowledgeRequirement(
            requirement_ref="kr_1",
            required=True,
            evidence_kind="policy_or_reference",
            target_step_ref=_steps("knowledge_backed_llm")[0],
            topic_refs=("topic.internal_documents.v1",),
            provider_topic="internal documents",
        )
    with pytest.raises(ValidationError):
        CachedParameterGuidanceRef(
            logical_step_ref=_steps("slack_send")[0],
            parameter_key="channel",
            reason_template_ref=(
                "guidance.reason.delivery_destination_required.v1"
            ),
            input_guidance_template_ref=(
                "guidance.input.select_slack_channel_id.v1"
            ),
            rendered_reason="channel required",
        )


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
    with pytest.raises(ValidationError):
        CachedKnowledgeRequirement(
            requirement_ref="kr_1",
            required=True,
            evidence_kind="policy_or_reference",
            target_step_ref=_steps("knowledge_backed_llm")[0],
            topic_refs=("topic.unknown.v1",),
        )
    with pytest.raises(ValidationError):
        CachedKnowledgeRequirement(
            requirement_ref="kr_1",
            required=True,
            evidence_kind="policy_or_reference",
            target_step_ref=_steps("knowledge_backed_llm")[0],
            topic_refs=(
                "topic.internal_documents.v1",
                "topic.internal_documents.v1",
            ),
        )
    with pytest.raises(ValidationError):
        CachedParameterGuidanceRef(
            logical_step_ref=_steps("answer")[0],
            parameter_key="outputs",
            reason_template_ref=(
                "guidance.reason.delivery_destination_required.v1"
            ),
            input_guidance_template_ref=(
                "guidance.input.select_slack_channel_id.v1"
            ),
        )
    with pytest.raises(ValidationError):
        CachedParameterGuidanceRef(
            logical_step_ref=_steps("slack_send")[0],
            parameter_key="url",
            reason_template_ref=(
                "guidance.reason.delivery_destination_required.v1"
            ),
            input_guidance_template_ref=(
                "guidance.input.select_slack_channel_id.v1"
            ),
        )
    with pytest.raises(ValidationError):
        IntentPlanContractVersions(
            normalizer_version="normalizer-v1",
            cache_schema_version=1,
            planner_contract_version="planner-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v2",
            materializer_version="materializer-v1",
        )

    ordered_guidance = (
        CachedParameterGuidanceRef(
            logical_step_ref=LogicalStepRef(
                capability="slack_send",
                occurrence=2,
            ),
            parameter_key="channel",
            reason_template_ref=(
                "guidance.reason.delivery_destination_required.v1"
            ),
            input_guidance_template_ref=(
                "guidance.input.select_slack_channel_id.v1"
            ),
        ),
        CachedParameterGuidanceRef(
            logical_step_ref=LogicalStepRef(
                capability="slack_send",
                occurrence=1,
            ),
            parameter_key="channel",
            reason_template_ref=(
                "guidance.reason.delivery_destination_required.v1"
            ),
            input_guidance_template_ref=(
                "guidance.input.select_slack_channel_id.v1"
            ),
        ),
    )
    guidance_plan = minimal_plan(
        ordered_capabilities=("slack_send", "slack_send"),
        logical_steps=_steps("slack_send", "slack_send"),
        parameter_guidance_refs=ordered_guidance,
    )
    assert guidance_plan.parameter_guidance_refs == ordered_guidance


@pytest.mark.parametrize(
    ("capabilities", "integration_actions"),
    [
        (("answer",), ("github.pull_request.comment",)),
        (("github_pr_comment",), ()),
        (("answer",), ("github.pull_request.read",)),
        (("github_pr_read",), ()),
    ],
)
def test_integration_actions_and_capabilities_require_bidirectional_membership(
    capabilities,
    integration_actions,
):
    with pytest.raises(ValidationError):
        minimal_plan(
            ordered_capabilities=capabilities,
            logical_steps=_steps(*capabilities),
            integration_actions=integration_actions,
        )

    valid = minimal_plan(
        ordered_capabilities=("github_pr_read", "github_pr_comment"),
        logical_steps=_steps("github_pr_read", "github_pr_comment"),
        integration_actions=(
            "github.pull_request.read",
            "github.pull_request.comment",
        ),
    )
    assert valid.integration_actions == (
        "github.pull_request.read",
        "github.pull_request.comment",
    )


def test_knowledge_requirements_and_placements_form_a_closed_target_mapping():
    steps = _steps("start_input", "knowledge_backed_llm", "answer")
    requirement = CachedKnowledgeRequirement(
        requirement_ref="kr_1",
        required=True,
        evidence_kind="policy_or_reference",
        target_step_ref=steps[1],
        topic_refs=("topic.internal_documents.v1",),
    )

    with pytest.raises(ValidationError):
        minimal_plan(
            ordered_capabilities=tuple(step.capability for step in steps),
            logical_steps=steps,
            knowledge_requirements=(requirement,),
        )

    with pytest.raises(ValidationError):
        minimal_plan(
            ordered_capabilities=tuple(step.capability for step in steps),
            logical_steps=steps,
            knowledge_requirements=(requirement,),
            knowledge_placements=(
                CachedKnowledgePlacement(
                    requirement_ref="kr_1",
                    timing="after_graph",
                    effect_kind="binding_only",
                    target_step_ref=steps[2],
                ),
            ),
        )

    with pytest.raises(ValidationError):
        minimal_plan(
            ordered_capabilities=tuple(step.capability for step in steps),
            logical_steps=steps,
            knowledge_requirements=(requirement,),
            knowledge_placements=(
                CachedKnowledgePlacement(
                    requirement_ref="kr_1",
                    timing="before_graph",
                    effect_kind="insert_step",
                    target_step_ref=steps[1],
                    knowledge_step_ref=steps[2],
                    upstream_step_ref=steps[0],
                    downstream_step_ref=steps[2],
                    empty_selection_bridge="connect_upstream_to_downstream",
                ),
            ),
        )

    valid = minimal_plan(
        ordered_capabilities=tuple(step.capability for step in steps),
        logical_steps=steps,
        knowledge_requirements=(requirement,),
        knowledge_placements=(
            CachedKnowledgePlacement(
                requirement_ref="kr_1",
                timing="before_graph",
                effect_kind="insert_step",
                target_step_ref=steps[1],
                knowledge_step_ref=steps[1],
                upstream_step_ref=steps[0],
                downstream_step_ref=steps[2],
                empty_selection_bridge="connect_upstream_to_downstream",
            ),
        ),
    )
    assert valid.knowledge_placements[0].requirement_ref == "kr_1"


def test_catalog_snapshot_matches_current_catalog_v3_exactly():
    catalog = json.loads(
        (ROOT / "apps/shared/config/workflow_node_catalog.json").read_text(
            encoding="utf-8"
        )
    )
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
        {"topic.current_safe_message.v1", "topic.internal_documents.v1"}
    )
    assert CANONICAL_GUIDANCE_REASON_REFS == frozenset(
        {
            "guidance.reason.configuration_required.v1",
            "guidance.reason.delivery_destination_required.v1",
        }
    )
    assert CANONICAL_INPUT_GUIDANCE_REFS == frozenset(
        {
            "guidance.input.provide_parameter_value.v1",
            "guidance.input.select_slack_channel_id.v1",
        }
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
    assert CAPABILITY_PURPOSES == {
        "start_input": "사용자 입력을 받습니다.",
        "webhook_trigger": "Webhook payload를 받습니다.",
        "schedule_trigger": "설정된 일정에 따라 workflow를 시작합니다.",
        "file_extraction": "입력 파일에서 텍스트를 추출합니다.",
        "variable_extraction": "입력 데이터에서 필요한 변수를 추출합니다.",
        "github_pr_read": "GitHub Pull Request와 변경 파일을 조회합니다.",
        "mail_search": "메일을 검색합니다.",
        "gmail_reply_draft_create": (
            "원본 메일 thread에 Gmail 답장 초안을 생성합니다."
        ),
        "mail_terminal_acknowledgement": (
            "필수 작업 성공 후 원본 메일 처리를 완료합니다."
        ),
        "http_request": "외부 HTTP API를 호출합니다.",
        "workflow_call": "다른 workflow를 호출합니다.",
        "code_execution": "sandbox에서 코드를 실행합니다.",
        "template_render": "입력값으로 템플릿을 렌더링합니다.",
        "condition": "조건에 따라 흐름을 분기합니다.",
        "llm": "입력을 분석하고 결과를 생성합니다.",
        "knowledge_backed_llm": (
            "Knowledge Base 근거로 입력을 분석하고 결과를 생성합니다."
        ),
        "github_pr_comment": (
            "생성한 내용을 GitHub Pull Request 댓글로 등록합니다."
        ),
        "slack_send": "이전 단계 결과를 Slack 메시지로 전송합니다.",
        "answer": "이전 단계 결과를 응답으로 반환합니다.",
    }


def test_transient_context_preserves_request_specific_messages_and_topology():
    first = _context("첫 번째 safe request")
    second = _context("두 번째 safe request")

    assert first.full_safe_message == "첫 번째 safe request"
    assert second.full_safe_message == "두 번째 safe request"
    assert first.workflow_context.nodes[0].logical_ref == "n_1"
    assert first is not second


@pytest.mark.parametrize(
    "factory",
    [json.dumps, vars, dataclasses.asdict, pickle.dumps],
)
def test_transient_context_and_scope_reject_accidental_serialization(factory):
    context = _context()

    with pytest.raises(TypeError):
        factory(context)
    with pytest.raises(TypeError):
        factory(context.scope)
    assert not hasattr(context, "model_dump")
    assert not hasattr(context, "dict")
    assert not hasattr(context, "__getstate__")
    assert not hasattr(context.scope, "__getstate__")
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
        IntentLogicalTopology(
            workflow_present=True,
            nodes=(
                IntentLogicalNode(
                    logical_ref="n_2",
                    node_type="startNode",
                    safe_label="입력",
                    role="entry",
                ),
            ),
            edges=(),
        )
    with pytest.raises(ValidationError):
        PlannerRuntimeFingerprint(
            provider_ref="unknown",
            model_relation_fingerprint=_HEX_A,
            credential_relation_fingerprint=_HEX_B,
        )
    with pytest.raises(ValidationError):
        IntentLogicalNode(
            logical_ref="n_1",
            node_type="startNode",
            safe_label="입력",
            role="intermediate",
        )
    with pytest.raises(ValidationError):
        IntentLogicalTopology(
            workflow_present=True,
            nodes=(
                IntentLogicalNode(
                    logical_ref="n_1",
                    node_type="startNode",
                    safe_label="입력",
                    role="entry",
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
    with pytest.raises(ValidationError):
        IntentLogicalTopology(
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
                    source_handle_kind="condition_default",
                    source_handle_ordinal=None,
                    target_handle_kind="standard",
                ),
            ),
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

    valid_decisions = (
        CacheBoundaryDecision(outcome="miss", plan=None, reason=None),
        CacheBoundaryDecision(outcome="miss", plan=None, reason="not_found"),
        CacheBoundaryDecision(
            outcome="miss",
            plan=None,
            reason="invalid_cached_plan",
        ),
        CacheBoundaryDecision(
            outcome="miss",
            plan=None,
            reason="rehydration_failed",
        ),
        CacheBoundaryDecision(
            outcome="bypass",
            plan=None,
            reason="normalization_bypass",
        ),
        CacheBoundaryDecision(
            outcome="error",
            plan=None,
            reason="cache_unavailable",
        ),
    )
    assert tuple(decision.outcome for decision in valid_decisions) == (
        "miss",
        "miss",
        "miss",
        "miss",
        "bypass",
        "error",
    )

    invalid_decisions = (
        lambda: CacheBoundaryDecision(outcome="miss", plan=plan, reason=None),
        lambda: CacheBoundaryDecision(
            outcome="bypass",
            plan=None,
            reason=None,
        ),
        lambda: CacheBoundaryDecision(
            outcome="error",
            plan=plan,
            reason="cache_unavailable",
        ),
    )
    for factory in invalid_decisions:
        with pytest.raises(ValidationError):
            factory()


@pytest.mark.parametrize(
    "factory",
    [
        lambda unsafe: CachedIntentPlanV1(
            **minimal_plan().model_dump(),
            intent_summary=unsafe,
        ),
        lambda unsafe: CachedIntentPlanV1.model_validate(
            {
                **minimal_plan().model_dump(),
                "intent_summary": unsafe,
            },
            strict=True,
        ),
        lambda unsafe: CachedIntentPlanV1.model_validate_json(
            json.dumps(
                {
                    **minimal_plan().model_dump(mode="json"),
                    "intent_summary": unsafe,
                }
            ),
            strict=True,
        ),
        lambda unsafe: IntentCacheKey.model_validate_strings(
            {
                "namespace": "agent-builder:intent-plan",
                "key_version": unsafe,
                "digest": _HEX_A,
            },
            strict=True,
        ),
        lambda unsafe: IntentRehydrationResult(
            status="failure",
            structured_request=None,
            reason="summary_projection_failed",
            raw_payload=unsafe,
        ),
    ],
)
def test_validation_errors_hide_sensitive_input_values_in_all_public_views(factory):
    unsafe = "api_key=" + ("x" * 24)

    with pytest.raises(ValidationError) as captured:
        factory(unsafe)

    errors = captured.value.errors()
    rendered = (
        str(captured.value)
        + repr(captured.value)
        + captured.value.json()
        + repr(errors)
    )
    assert unsafe not in rendered
    assert "x" * 24 not in rendered
    assert all(error.get("input") is None for error in errors)
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None
