from __future__ import annotations

import ast
import dataclasses
import json
import pickle
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest

from apps.gateway.application.agent_builder.intent_cache.catalog_snapshot import (
    CAPABILITY_PURPOSES,
    SUMMARY_PROJECTION_DESCRIPTOR,
)
from apps.gateway.application.agent_builder.intent_cache.ports import (
    IntentPlanRehydratorPort,
)
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
    CurrentKnowledgeResolution,
    CurrentRehydrationContext,
)
from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    INTENT_TEXT_V1_MANIFEST,
    CanonicalIntentTextRegistry,
    GuidanceInputTypeError,
    RegistryContractError,
    RequestIntentSummaryProjector,
)

ROOT = Path(__file__).resolve().parents[5]
_HEX_A = "a" * 64
_HEX_B = "b" * 64
_HEX_C = "c" * 64


def _versions(*, planner: str = "planner-v1") -> IntentPlanContractVersions:
    return IntentPlanContractVersions(
        normalizer_version="normalizer-v1",
        cache_schema_version=1,
        planner_contract_version=planner,
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


def _plan(*capabilities: str, versions=None) -> CachedIntentPlanV1:
    capabilities = capabilities or ("start_input", "slack_send", "answer")
    steps = _steps(*capabilities)
    guidance = ()
    requirements = ()
    placements = ()
    risk_flags = ()
    if "slack_send" in capabilities:
        slack_step = next(step for step in steps if step.capability == "slack_send")
        guidance = (
            CachedParameterGuidanceRef(
                logical_step_ref=slack_step,
                parameter_key="channel",
                reason_template_ref=(
                    "guidance.reason.delivery_destination_required.v1"
                ),
                input_guidance_template_ref=(
                    "guidance.input.select_slack_channel_id.v1"
                ),
            ),
        )
        risk_flags = (
            "external_action_requested",
            "slack_channel_unresolved",
            "external_configuration_unresolved",
        )
    if "knowledge_backed_llm" in capabilities:
        knowledge_step = next(
            step for step in steps if step.capability == "knowledge_backed_llm"
        )
        requirements = (
            CachedKnowledgeRequirement(
                requirement_ref="kr_1",
                required=True,
                evidence_kind="policy_or_reference",
                target_step_ref=knowledge_step,
                topic_refs=("topic.internal_documents.v1",),
            ),
        )
        placements = (
            CachedKnowledgePlacement(
                requirement_ref="kr_1",
                timing="after_graph",
                effect_kind="binding_only",
                target_step_ref=knowledge_step,
            ),
        )
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=capabilities,
        logical_steps=steps,
        edit_placement=None,
        integration_actions=(),
        parameter_guidance_refs=guidance,
        knowledge_requirements=requirements,
        knowledge_placements=placements,
        risk_flags=risk_flags,
        contract_versions=versions or _versions(),
    )


def _modify_plan(*, selected_edge: bool = False) -> CachedIntentPlanV1:
    steps = _steps("slack_send")
    placement = "between" if selected_edge else "after"
    target_type = "selected_edge" if selected_edge else "selected_node"
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="modify_workflow",
        draft_mode="modify_workflow",
        ordered_capabilities=("slack_send",),
        logical_steps=steps,
        edit_placement=CachedEditPlacement(
            placement=placement,
            target_reference_type=target_type,
            step_refs=steps,
        ),
        integration_actions=(),
        parameter_guidance_refs=(
            CachedParameterGuidanceRef(
                logical_step_ref=steps[0],
                parameter_key="channel",
                reason_template_ref=(
                    "guidance.reason.delivery_destination_required.v1"
                ),
                input_guidance_template_ref=(
                    "guidance.input.select_slack_channel_id.v1"
                ),
            ),
        ),
        knowledge_requirements=(),
        knowledge_placements=(),
        risk_flags=(
            "external_action_requested",
            "slack_channel_unresolved",
            "external_configuration_unresolved",
        ),
        contract_versions=_versions(),
    )


def _context(
    message: str = "입력을 Slack으로 보내는 workflow를 만들어줘",
    *,
    target_type: str | None = None,
    target_id: str | None = None,
    versions=None,
) -> IntentPlanningContext:
    workflow_present = target_type is not None
    nodes = (
        (
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
        )
        if workflow_present
        else ()
    )
    edges = (
        (
            IntentLogicalEdge(
                logical_ref="e_1",
                source_node_ref="n_1",
                target_node_ref="n_2",
                source_handle_kind="standard",
                source_handle_ordinal=None,
                target_handle_kind="standard",
            ),
        )
        if workflow_present
        else ()
    )
    return IntentPlanningContext(
        full_safe_message=message,
        workflow_context=IntentLogicalTopology(
            workflow_present=workflow_present,
            nodes=nodes,
            edges=edges,
        ),
        planner_runtime=PlannerRuntimeFingerprint(
            provider_ref="openai",
            model_relation_fingerprint=_HEX_A,
            credential_relation_fingerprint=_HEX_B,
        ),
        generation_mode="guided_generate",
        knowledge_context_fingerprint=_HEX_C,
        contract_versions=versions or _versions(),
        scope=EphemeralCacheScope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            selected_target_type=target_type,
            selected_target_id=target_id,
        ),
    )


def _current(
    context: IntentPlanningContext,
    *,
    plan: CachedIntentPlanV1 | None = None,
    candidate_handles: tuple[str, ...] = (),
    knowledge_resolution_status: str | None = None,
    knowledge_resolution_overrides: dict | None = None,
    knowledge_resolution_prefix: str = "current-resolution",
    **overrides,
) -> CurrentRehydrationContext:
    resolution_overrides = knowledge_resolution_overrides or {}

    def current_resolution(requirement_ref, ordinal):
        values = {
            "requirement_ref": requirement_ref,
            "resolution_id": f"{knowledge_resolution_prefix}-{ordinal}",
            "status": (
                knowledge_resolution_status
                or ("ready" if candidate_handles else "empty")
            ),
            "candidate_handles": candidate_handles,
            "hierarchy_authorized": True,
            "permission_allowed": True,
            "lifecycle_active": True,
            "operationally_ready": True,
        }
        values.update(resolution_overrides)
        return CurrentKnowledgeResolution(**values)

    knowledge_resolutions = tuple(
        current_resolution(requirement.requirement_ref, ordinal)
        for ordinal, requirement in enumerate(
            plan.knowledge_requirements if plan is not None else (),
            start=1,
        )
    )
    selected_target_logical_ref = {
        "selected_node": "n_1",
        "selected_edge": "e_1",
    }.get(context.scope._selected_target_type)
    values = {
        "actor_id": context.scope._actor_id,
        "organization_id": context.scope._organization_id,
        "organization_membership_active": True,
        "workflow_context_current": True,
        "workflow_context": context.workflow_context,
        "planner_runtime": context.planner_runtime,
        "generation_mode": context.generation_mode,
        "model_active": True,
        "credential_active": True,
        "model_credential_relation_verified": True,
        "credential_use_allowed": True,
        "selected_target_type": context.scope._selected_target_type,
        "selected_target_id": context.scope._selected_target_id,
        "selected_target_logical_ref": selected_target_logical_ref,
        "selected_target_exists": True,
        "selected_target_type_matches": True,
        "selected_target_placement_allowed": True,
        "knowledge_context_fingerprint": context.knowledge_context_fingerprint,
        "knowledge_resolutions": knowledge_resolutions,
    }
    values.update(overrides)
    return CurrentRehydrationContext(**values)


def _rehydrate(plan, context, **state_overrides):
    state = _current(context, plan=plan, **state_overrides)
    return CachedIntentPlanRehydrator(state).rehydrate(plan, context)


def _semantic_view(structured):
    step_alias = {
        step.step_id: f"step_{index}"
        for index, step in enumerate(structured.planned_steps, start=1)
    }
    resolution_alias = {
        item.resolution_id: f"resolution_{index}"
        for index, item in enumerate(structured.pending_resolution, start=1)
    }
    return {
        "request_type": structured.request_type,
        "draft_mode": structured.draft_mode,
        "intent_summary": structured.intent_summary,
        "planned_steps": [
            (
                step_alias[step.step_id],
                step.capability,
                step.purpose,
                tuple(step_alias[item] for item in step.depends_on),
            )
            for step in structured.planned_steps
        ],
        "guidance": [
            (
                step_alias[hint.step_id],
                hint.parameter_key,
                hint.reason,
                hint.input_guidance,
            )
            for hint in structured.parameter_guidance_hints
        ],
        "knowledge": [
            (
                requirement.requirement_id,
                tuple(requirement.query_topics),
                requirement.expected_evidence_type,
                requirement.required,
                step_alias[requirement.target_step_ref],
            )
            for requirement in structured.knowledge_requirements
        ],
        "placements": [
            (
                placement.requirement_id,
                placement.timing,
                placement.effect_kind,
                step_alias.get(placement.target_step_id),
                step_alias.get(placement.knowledge_step_id),
                step_alias.get(placement.upstream_step_id),
                step_alias.get(placement.downstream_step_id),
                placement.empty_selection_bridge,
            )
            for placement in structured.knowledge_placements
        ],
        "required_capabilities": tuple(structured.required_capabilities),
        "pending": [
            (
                resolution_alias[item.resolution_id],
                item.slot_type,
                item.slot_key,
                item.blocking,
                step_alias.get(item.target_step_ref),
            )
            for item in structured.pending_resolution
        ],
        "edit": [
            (
                item.operation,
                item.placement,
                tuple(step_alias[step_id] for step_id in item.step_refs),
                item.target.reference_type,
            )
            for item in structured.edit_operations
        ],
        "risk_flags": tuple(structured.risk_flags),
    }


def _graph_topology(graph):
    node_alias = {
        str(node["id"]): f"node_{index}"
        for index, node in enumerate(graph["nodes"], start=1)
    }
    return (
        tuple(str(node["type"]) for node in graph["nodes"]),
        tuple(
            (
                node_alias[str(edge["source"])],
                node_alias[str(edge["target"])],
            )
            for edge in graph["edges"]
        ),
    )


def _parameter_task_view(group):
    assert group is not None
    return [
        (
            task.node_type,
            task.parameter_key,
            task.reason,
            task.input_guidance,
            task.node_purpose,
            task.resolution_source,
            task.status,
        )
        for task in group.tasks
    ]


def _replace_exact_values(value, aliases):
    if isinstance(value, dict):
        return {
            key: _replace_exact_values(item, aliases) for key, item in value.items()
        }
    if isinstance(value, list):
        return [_replace_exact_values(item, aliases) for item in value]
    if isinstance(value, tuple):
        return tuple(_replace_exact_values(item, aliases) for item in value)
    return aliases.get(value, value) if isinstance(value, str) else value


def _normalized_structured(structured):
    aliases = {
        step.step_id: f"step_{ordinal}"
        for ordinal, step in enumerate(structured.planned_steps, start=1)
    }
    aliases.update(
        {
            resolution.resolution_id: f"resolution_{ordinal}"
            for ordinal, resolution in enumerate(
                structured.pending_resolution,
                start=1,
            )
        }
    )
    aliases.update(
        {
            operation.operation_id: f"operation_{ordinal}"
            for ordinal, operation in enumerate(
                structured.edit_operations,
                start=1,
            )
        }
    )
    for requirement_ordinal, requirement in enumerate(
        structured.knowledge_requirements,
        start=1,
    ):
        aliases.update(
            {
                handle: (f"candidate_{requirement_ordinal}_{candidate_ordinal}")
                for candidate_ordinal, handle in enumerate(
                    requirement.suggested_candidate_handles,
                    start=1,
                )
            }
        )
    return _replace_exact_values(structured.model_dump(mode="json"), aliases)


def _normalized_graph(graph):
    aliases = {
        str(node["id"]): f"node_{ordinal}"
        for ordinal, node in enumerate(graph["nodes"], start=1)
    }
    aliases.update(
        {
            str(edge["id"]): f"edge_{ordinal}"
            for ordinal, edge in enumerate(graph["edges"], start=1)
        }
    )
    return _replace_exact_values(graph, aliases)


def _normalized_parameter_group(group, structured, graph):
    assert group is not None
    aliases = {
        str(group.group_id): "group_1",
        **{
            step.step_id: f"step_{ordinal}"
            for ordinal, step in enumerate(structured.planned_steps, start=1)
        },
        **{
            str(node["id"]): f"node_{ordinal}"
            for ordinal, node in enumerate(graph["nodes"], start=1)
        },
    }
    for ordinal, task in enumerate(group.tasks, start=1):
        aliases[str(task.task_id)] = f"task_{ordinal}"
        if task.recommendation_fingerprint is not None:
            aliases[task.recommendation_fingerprint] = (
                f"recommendation_fingerprint_{ordinal}"
            )
    return _replace_exact_values(group.model_dump(mode="json"), aliases)


def test_intent_text_v1_manifest_is_exact_closed_and_catalog_applicable():
    registry = CanonicalIntentTextRegistry()

    assert dataclasses.asdict(INTENT_TEXT_V1_MANIFEST) == {
        "registry_version": "intent-text-v1",
        "summary_projection": {
            "projection_id": "summary.current_safe_message.v1",
            "source": "IntentPlanningContext.full_safe_message",
            "max_codepoints": 240,
            "whitespace_profile": "python-split-v1",
            "redaction_profile": "agent-builder-safe-summary-v1",
        },
        "topics": (
            {
                "ref": "topic.internal_documents.v1",
                "canonical_text": "사내 문서",
                "aliases": ("내부 문서", "internal documents"),
            },
        ),
        "reason_templates": (
            {
                "ref": "guidance.reason.delivery_destination_required.v1",
                "canonical_template": "메시지 전달 위치가 필요합니다.",
                "aliases": (
                    "메시지 목적지가 필요합니다.",
                    "전송 대상을 선택해야 합니다.",
                    "delivery destination required",
                ),
                "allowed_input_types": ("text",),
            },
        ),
        "input_guidance_templates": (
            {
                "ref": "guidance.input.select_slack_channel_id.v1",
                "canonical_template": "Slack channel ID를 선택하세요.",
                "aliases": (
                    "Slack 채널 ID를 선택하세요.",
                    "select Slack channel ID",
                ),
                "allowed_input_types": ("text",),
            },
        ),
    }
    assert INTENT_TEXT_V1_MANIFEST.summary_projection.source == (
        SUMMARY_PROJECTION_DESCRIPTOR["source"]
    )
    assert INTENT_TEXT_V1_MANIFEST.registry_version == "intent-text-v1"
    assert [entry.ref for entry in INTENT_TEXT_V1_MANIFEST.topics] == [
        "topic.internal_documents.v1"
    ]
    assert [entry.ref for entry in INTENT_TEXT_V1_MANIFEST.reason_templates] == [
        "guidance.reason.delivery_destination_required.v1"
    ]
    assert [
        entry.ref for entry in INTENT_TEXT_V1_MANIFEST.input_guidance_templates
    ] == ["guidance.input.select_slack_channel_id.v1"]
    assert INTENT_TEXT_V1_MANIFEST.topics[0].canonical_text == "사내 문서"
    assert registry.project_topic("  INTERNAL\u3000DOCUMENTS ") == (
        "topic.internal_documents.v1"
    )
    assert registry.project_topic("similar internal policy") is None
    assert registry.render_topic("topic.internal_documents.v1") == "사내 문서"
    assert registry.capability_purposes == CAPABILITY_PURPOSES
    catalog = json.loads(
        (ROOT / "apps/shared/config/workflow_node_catalog.json").read_text(
            encoding="utf-8"
        )
    )
    slack = next(
        node for node in catalog["nodes"] if node["node_type"] == "slackPostNode"
    )
    channel = next(
        parameter for parameter in slack["parameters"] if parameter["key"] == "channel"
    )
    assert registry.guidance_catalog_context("slack_send", "channel") == (
        channel["label"],
        channel["input_type"],
    )
    rendered = registry.render_guidance(
        reason_ref="guidance.reason.delivery_destination_required.v1",
        input_guidance_ref="guidance.input.select_slack_channel_id.v1",
        capability="slack_send",
        parameter_key="channel",
        safe_label="Slack channel",
        input_type="text",
    )
    assert rendered == (
        "메시지 전달 위치가 필요합니다.",
        "Slack channel ID를 선택하세요.",
    )

    with pytest.raises(GuidanceInputTypeError):
        registry.render_guidance(
            reason_ref="guidance.reason.delivery_destination_required.v1",
            input_guidance_ref="guidance.input.select_slack_channel_id.v1",
            capability="slack_send",
            parameter_key="channel",
            safe_label="Slack channel",
            input_type="number",
        )


def test_registry_rejects_missing_member_alias_conflict_and_free_placeholder():
    with pytest.raises(RegistryContractError):
        CanonicalIntentTextRegistry(object())
    missing = dataclasses.replace(INTENT_TEXT_V1_MANIFEST, topics=())
    with pytest.raises(RegistryContractError):
        CanonicalIntentTextRegistry(missing)

    topic = INTENT_TEXT_V1_MANIFEST.topics[0]
    conflicting = dataclasses.replace(
        INTENT_TEXT_V1_MANIFEST,
        topics=(dataclasses.replace(topic, aliases=("사내 문서",)),),
    )
    with pytest.raises(RegistryContractError):
        CanonicalIntentTextRegistry(conflicting)

    ref_alias_conflict = dataclasses.replace(
        INTENT_TEXT_V1_MANIFEST,
        topics=(
            dataclasses.replace(
                topic,
                aliases=(*topic.aliases, topic.ref),
            ),
        ),
    )
    with pytest.raises(RegistryContractError):
        CanonicalIntentTextRegistry(ref_alias_conflict)
    reason = INTENT_TEXT_V1_MANIFEST.reason_templates[0]
    cross_kind_conflict = dataclasses.replace(
        INTENT_TEXT_V1_MANIFEST,
        reason_templates=(
            dataclasses.replace(
                reason,
                aliases=(*reason.aliases, "사내 문서"),
            ),
        ),
    )
    with pytest.raises(RegistryContractError):
        CanonicalIntentTextRegistry(cross_kind_conflict)
    unsupported = dataclasses.replace(
        INTENT_TEXT_V1_MANIFEST,
        reason_templates=(
            dataclasses.replace(reason, canonical_template="{free_text}"),
        ),
    )
    with pytest.raises(RegistryContractError):
        CanonicalIntentTextRegistry(unsupported)


def test_registry_rejects_same_version_canonical_text_drift():
    topic = INTENT_TEXT_V1_MANIFEST.topics[0]
    drifted = dataclasses.replace(
        INTENT_TEXT_V1_MANIFEST,
        topics=(dataclasses.replace(topic, canonical_text="changed text"),),
    )

    with pytest.raises(RegistryContractError, match="same-version"):
        CanonicalIntentTextRegistry(drifted)


def test_summary_projection_is_request_specific_bounded_and_fail_closed():
    projector = RequestIntentSummaryProjector()

    assert projector.project("  현재\t요청\n요약  ") == "현재 요청 요약"
    assert projector.project("가" * 241) == "가" * 240
    assert projector.project("   ") is None
    assert projector.project("안전한 문장 [redacted]") is None
    unsafe_current_messages = (
        "참조 " + "https:" + "//example.invalid/item",
        "Authorization: " + "Bearer " + "synthetic-value",
        "비밀번호 값은 " + "synthetic-value",
        "경로 " + "C:" + "\\private\\item",
        "연락처 " + "person" + "@example.invalid",
    )
    assert all(projector.project(value) is None for value in unsafe_current_messages)
    first_context = _context("첫 번째 안전 요청")
    second_context = _context("두 번째 안전 요청")
    plan = _plan()
    first = _rehydrate(plan, first_context)
    second = _rehydrate(plan, second_context)

    assert first.status == second.status == "success"
    assert first.structured_request.intent_summary == "첫 번째 안전 요청"
    assert second.structured_request.intent_summary == "두 번째 안전 요청"
    assert "provider" not in first.structured_request.model_dump()


@pytest.mark.parametrize(
    "override",
    [
        {"organization_membership_active": False},
        {"workflow_context_current": False},
        {"model_active": False},
        {"credential_active": False},
        {"model_credential_relation_verified": False},
        {"credential_use_allowed": False},
        {"generation_mode": "quick_generate"},
        {
            "planner_runtime": PlannerRuntimeFingerprint(
                provider_ref="openai",
                model_relation_fingerprint="d" * 64,
                credential_relation_fingerprint=_HEX_B,
            )
        },
    ],
)
def test_rehydration_rejects_every_stale_planner_runtime_dimension(override):
    context = _context()
    result = _rehydrate(_plan(), context, **override)

    assert result.status == "failure"
    assert result.reason == "current_context_invalid"
    assert result.structured_request is None


def test_rehydration_rejects_changed_current_workflow_topology():
    context = _context(
        "existing workflow receives a Slack step",
        target_type="selected_node",
        target_id="current-target",
    )
    result = _rehydrate(
        _modify_plan(),
        context,
        workflow_context=IntentLogicalTopology(
            workflow_present=False,
            nodes=(),
            edges=(),
        ),
    )

    assert result.status == "failure"
    assert result.reason == "current_context_invalid"
    assert result.structured_request is None

def test_rehydration_rejects_scope_and_contract_version_mismatch():
    context = _context()
    wrong_actor = _rehydrate(_plan(), context, actor_id=uuid4())
    wrong_versions = _rehydrate(
        _plan(versions=_versions(planner="planner-v2")),
        context,
    )

    assert wrong_actor.reason == "current_context_invalid"
    assert wrong_versions.reason == "contract_version_mismatch"


@pytest.mark.parametrize(
    "override",
    [
        {"selected_target_exists": False},
        {"selected_target_type_matches": False},
        {"selected_target_placement_allowed": False},
        {"selected_target_id": "different-current-target"},
        {"selected_target_logical_ref": "n_999"},
        {"selected_target_logical_ref": "e_1"},
    ],
)
def test_modify_rebinds_only_the_selected_target_in_current_server_graph(override):
    context = _context(
        "선택한 node 뒤에 Slack 전송을 추가해줘",
        target_type="selected_node",
        target_id="current-target",
    )
    result = _rehydrate(_modify_plan(), context, **override)

    assert result.status == "failure"
    assert result.reason == "logical_reference_invalid"
    assert "current-target" not in repr(result)


def test_modify_uses_current_selected_target_without_returning_its_identity():
    context = _context(
        "선택한 edge 사이에 Slack 전송을 추가해줘",
        target_type="selected_edge",
        target_id="current-edge",
    )
    plan = _modify_plan(selected_edge=True)

    first = _rehydrate(plan, context)
    second = _rehydrate(plan, context)

    assert first.status == second.status == "success"
    assert _normalized_structured(first.structured_request) == (
        _normalized_structured(second.structured_request)
    )
    first_operation = first.structured_request.edit_operations[0]
    second_operation = second.structured_request.edit_operations[0]
    assert UUID(first_operation.operation_id) != UUID(second_operation.operation_id)
    assert first_operation.target.reference_type == "selected_edge"
    assert first_operation.target.query is None
    assert first_operation.target.capabilities == []
    rendered = repr(first.structured_request.model_dump())
    assert "current-edge" not in rendered


@pytest.mark.parametrize(
    ("knowledge_resolution_overrides", "state_overrides"),
    [
        ({"hierarchy_authorized": False}, {}),
        ({"permission_allowed": False}, {}),
        ({"lifecycle_active": False}, {}),
        ({"operationally_ready": False}, {}),
        ({}, {"knowledge_context_fingerprint": "e" * 64}),
    ],
)
def test_knowledge_rehydration_rechecks_current_hierarchy_and_lifecycle(
    knowledge_resolution_overrides,
    state_overrides,
):
    context = _context("사내 문서를 참고해 답하고 Slack으로 보내줘")
    plan = _plan("start_input", "knowledge_backed_llm", "slack_send", "answer")
    result = _rehydrate(
        plan,
        context,
        knowledge_resolution_overrides=knowledge_resolution_overrides,
        **state_overrides,
    )

    assert result.status == "failure"
    assert result.reason == "current_context_invalid"


@pytest.mark.parametrize(
    ("status", "handles"),
    [
        ("empty", ()),
        ("ambiguous", ("rec-current-a", "rec-current-b")),
        ("ready", ("rec-current-a",)),
    ],
)
def test_knowledge_empty_ambiguity_and_ready_use_only_current_handles(
    status,
    handles,
):
    context = _context("사내 문서를 참고해 답하고 Slack으로 보내줘")
    plan = _plan("start_input", "knowledge_backed_llm", "slack_send", "answer")
    result = _rehydrate(
        plan,
        context,
        candidate_handles=handles,
        knowledge_resolution_status=status,
    )

    assert result.status == "success"
    requirement = result.structured_request.knowledge_requirements[0]
    assert requirement.query_topics == ["사내 문서"]
    assert requirement.suggested_candidate_handles == list(handles)
    assert result.structured_request.explicit_parameter_values == []
    assert result.structured_request.pending_resolution[0].slot_type == (
        "knowledge_base"
    )


@pytest.mark.parametrize(
    ("status", "handles"),
    [
        ("empty", ("candidate-current-a",)),
        ("ready", ()),
        ("ready", ("candidate-current-a", "candidate-current-b")),
        ("ambiguous", ("candidate-current-a",)),
    ],
)
def test_current_knowledge_resolution_status_cardinality_is_exact(
    status,
    handles,
):
    with pytest.raises(ValueError):
        CurrentKnowledgeResolution(
            requirement_ref="kr_1",
            resolution_id="current-resolution-a",
            status=status,
            candidate_handles=handles,
            hierarchy_authorized=True,
            permission_allowed=True,
            lifecycle_active=True,
            operationally_ready=True,
        )


def test_knowledge_rehydration_binds_each_current_resolution_by_requirement():
    context = _context("사내 문서를 참고해 요약해줘")
    plan = _plan("start_input", "knowledge_backed_llm", "answer")
    first_requirement = plan.knowledge_requirements[0]
    first_placement = plan.knowledge_placements[0]
    second_requirement = first_requirement.model_copy(
        update={"requirement_ref": "kr_2"},
    )
    second_placement = first_placement.model_copy(
        update={"requirement_ref": "kr_2"},
    )
    plan = plan.model_copy(
        update={
            "knowledge_requirements": (
                first_requirement,
                second_requirement,
            ),
            "knowledge_placements": (
                first_placement,
                second_placement,
            ),
        },
    )
    first_resolution = CurrentKnowledgeResolution(
        requirement_ref="kr_1",
        resolution_id="current-resolution-a",
        status="ready",
        candidate_handles=("candidate-current-a",),
        hierarchy_authorized=True,
        permission_allowed=True,
        lifecycle_active=True,
        operationally_ready=True,
    )
    second_resolution = CurrentKnowledgeResolution(
        requirement_ref="kr_2",
        resolution_id="current-resolution-b",
        status="ambiguous",
        candidate_handles=("candidate-current-b", "candidate-current-c"),
        hierarchy_authorized=True,
        permission_allowed=True,
        lifecycle_active=True,
        operationally_ready=True,
    )
    duplicate_id_resolution = CurrentKnowledgeResolution(
        requirement_ref="kr_2",
        resolution_id="current-resolution-a",
        status="ready",
        candidate_handles=("candidate-current-d",),
        hierarchy_authorized=True,
        permission_allowed=True,
        lifecycle_active=True,
        operationally_ready=True,
    )
    assert repr(first_resolution) == "<CurrentKnowledgeResolution redacted>"
    with pytest.raises(TypeError):
        pickle.dumps(first_resolution)
    with pytest.raises(TypeError):
        vars(first_resolution)
    with pytest.raises(TypeError):
        json.dumps(first_resolution)
    with pytest.raises(TypeError):
        dataclasses.asdict(first_resolution)

    result = CachedIntentPlanRehydrator(
        _current(
            context,
            plan=plan,
            knowledge_resolutions=(first_resolution, second_resolution),
        )
    ).rehydrate(plan, context)
    reordered = CachedIntentPlanRehydrator(
        _current(
            context,
            plan=plan,
            knowledge_resolutions=(second_resolution, first_resolution),
        )
    ).rehydrate(plan, context)
    duplicate_id = CachedIntentPlanRehydrator(
        _current(
            context,
            plan=plan,
            knowledge_resolutions=(first_resolution, duplicate_id_resolution),
        )
    ).rehydrate(plan, context)

    assert result.status == "success"
    assert [
        requirement.suggested_candidate_handles
        for requirement in result.structured_request.knowledge_requirements
    ] == [
        ["candidate-current-a"],
        ["candidate-current-b", "candidate-current-c"],
    ]
    assert [
        resolution.resolution_id
        for resolution in result.structured_request.pending_resolution[:2]
    ] == ["current-resolution-a", "current-resolution-b"]
    assert reordered.status == "failure"
    assert reordered.reason == "current_context_invalid"
    assert duplicate_id.status == "failure"
    assert duplicate_id.reason == "current_context_invalid"


def test_current_context_is_nonserializable_redacted_and_not_returned():
    context = _context(
        target_type="selected_node",
        target_id="current-protected-target",
    )
    current = _current(context, candidate_handles=("rec-current-only",))
    rehydrator = CachedIntentPlanRehydrator(current)
    assert isinstance(rehydrator, IntentPlanRehydratorPort)

    assert repr(current) == "<CurrentRehydrationContext redacted>"
    with pytest.raises(TypeError):
        pickle.dumps(current)
    with pytest.raises(TypeError):
        vars(current)
    with pytest.raises(TypeError):
        json.dumps(current)
    with pytest.raises(TypeError):
        dataclasses.asdict(current)

    result = rehydrator.rehydrate(
        _modify_plan(),
        context,
    )
    rendered = repr(result)
    assert "current-protected-target" not in rendered
    assert _HEX_A not in rendered
    assert _HEX_B not in rendered
    assert _HEX_C not in rendered


def test_cold_and_warm_rehydration_have_identity_normalized_semantic_parity():
    context = _context()
    plan = _plan()
    current = _current(context)
    rehydrator = CachedIntentPlanRehydrator(current)

    cold = rehydrator.rehydrate(plan, context).structured_request
    warm = rehydrator.rehydrate(plan, context).structured_request

    assert _semantic_view(cold) == _semantic_view(warm)
    assert _normalized_structured(cold) == _normalized_structured(warm)
    assert {step.step_id for step in cold.planned_steps}.isdisjoint(
        {step.step_id for step in warm.planned_steps}
    )


def test_knowledge_cold_warm_parity_uses_request_current_handles_only():
    context = _context("사내 문서를 참고해 답하고 Slack으로 보내줘")
    plan = _plan(
        "start_input",
        "knowledge_backed_llm",
        "slack_send",
        "answer",
    )
    cold = (
        CachedIntentPlanRehydrator(
            _current(
                context,
                plan=plan,
                candidate_handles=("rec-current-cold",),
                knowledge_resolution_prefix="cold-resolution",
            )
        )
        .rehydrate(plan, context)
        .structured_request
    )
    warm = (
        CachedIntentPlanRehydrator(
            _current(
                context,
                plan=plan,
                candidate_handles=("rec-current-warm",),
                knowledge_resolution_prefix="warm-resolution",
            )
        )
        .rehydrate(plan, context)
        .structured_request
    )

    assert _semantic_view(cold) == _semantic_view(warm)
    assert _normalized_structured(cold) == _normalized_structured(warm)
    assert cold.knowledge_requirements[0].query_topics == ["사내 문서"]
    assert warm.knowledge_requirements[0].query_topics == ["사내 문서"]
    assert cold.knowledge_requirements[0].suggested_candidate_handles == [
        "rec-current-cold"
    ]
    assert warm.knowledge_requirements[0].suggested_candidate_handles == [
        "rec-current-warm"
    ]
    assert {step.step_id for step in cold.planned_steps}.isdisjoint(
        {step.step_id for step in warm.planned_steps}
    )


def test_existing_materializer_keeps_topology_and_tasks_but_issues_fresh_ids():
    pytest.importorskip("cryptography")
    pytest.importorskip("psycopg2")
    from apps.gateway.application.agent_builder.service import (
        DirectEditOrchestrator,
    )
    from apps.gateway.services.agent_builder_service import AgentBuilderService

    context = _context()
    plan = _plan()
    rehydrator = CachedIntentPlanRehydrator(_current(context))
    cold = rehydrator.rehydrate(plan, context).structured_request
    warm = rehydrator.rehydrate(plan, context).structured_request
    materializer = object.__new__(AgentBuilderService)
    cold_graph = materializer._build_preview_graph(
        cold,
        workflow=None,
        kb_bindings=[],
    )
    warm_graph = materializer._build_preview_graph(
        warm,
        workflow=None,
        kb_bindings=[],
    )
    assert _graph_topology(cold_graph) == _graph_topology(warm_graph)
    assert _normalized_graph(cold_graph) == _normalized_graph(warm_graph)
    cold_node_ids = {str(node["id"]) for node in cold_graph["nodes"]}
    warm_node_ids = {str(node["id"]) for node in warm_graph["nodes"]}
    cold_edge_ids = {str(edge["id"]) for edge in cold_graph["edges"]}
    warm_edge_ids = {str(edge["id"]) for edge in warm_graph["edges"]}
    assert cold_node_ids.isdisjoint(warm_node_ids)
    assert cold_edge_ids.isdisjoint(warm_edge_ids)

    workflow = SimpleNamespace(
        id=uuid4(),
        graph={"nodes": [], "edges": []},
        updated_at=datetime.now(timezone.utc),
    )
    cold_issue = DirectEditOrchestrator().issue(
        workflow=workflow,
        structured_request=cold,
        candidate_graph=cold_graph,
        generation_mode="configure_and_generate",
    )
    warm_issue = DirectEditOrchestrator().issue(
        workflow=workflow,
        structured_request=warm,
        candidate_graph=warm_graph,
        generation_mode="configure_and_generate",
    )
    assert cold_issue.mutation.operation_id != warm_issue.mutation.operation_id
    assert _parameter_task_view(cold_issue.parameter_group) == (
        _parameter_task_view(warm_issue.parameter_group)
    )
    assert _normalized_parameter_group(
        cold_issue.parameter_group,
        cold,
        cold_graph,
    ) == _normalized_parameter_group(
        warm_issue.parameter_group,
        warm,
        warm_graph,
    )


def test_application_rehydration_modules_keep_the_dependency_boundary():
    forbidden = (
        "fastapi",
        "sqlalchemy",
        "redis",
        "apps.gateway.services",
    )
    for relative in (
        "apps/gateway/application/agent_builder/intent_rehydration.py",
        "apps/gateway/application/agent_builder/intent_rehydration_registry.py",
    ):
        source = (ROOT / relative).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.append(node.module)
        assert not any(
            imported == prefix or imported.startswith(prefix + ".")
            for imported in imports
            for prefix in forbidden
        )
