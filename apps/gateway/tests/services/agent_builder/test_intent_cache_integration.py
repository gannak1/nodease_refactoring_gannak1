from __future__ import annotations

from uuid import uuid4

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    EphemeralCacheScope,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanningContext,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_rehydration_registry import (
    CanonicalIntentTextRegistry,
)
from apps.gateway.services.agent_builder.intent_cache_integration import (
    current_rehydrator_for,
    project_structured_intent_plan,
)
from apps.shared.schemas.agent_builder import (
    AgentBuilderExplicitParameterValue,
    AgentBuilderKnowledgePlacement,
    AgentBuilderKnowledgeRequirement,
    AgentBuilderPlannedStep,
    AgentBuilderStructuredRequest,
)


def _context() -> IntentPlanningContext:
    return IntentPlanningContext(
        full_safe_message="입력과 응답 workflow를 만들어줘",
        workflow_context=IntentLogicalTopology(
            workflow_present=False,
            nodes=(),
            edges=(),
        ),
        planner_runtime=PlannerRuntimeFingerprint(
            provider_ref="openai",
            model_relation_fingerprint="a" * 64,
            credential_relation_fingerprint="b" * 64,
        ),
        generation_mode="guided_generate",
        knowledge_context_fingerprint="c" * 64,
        contract_versions=IntentPlanContractVersions(
            normalizer_version="intent-normalizer-v1",
            cache_schema_version=1,
            planner_contract_version="agent-builder-intent-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v1",
            materializer_version="agent-builder-direct-edit-v1",
        ),
        scope=EphemeralCacheScope(
            actor_id=uuid4(),
            organization_id=uuid4(),
            selected_target_type=None,
            selected_target_id=None,
        ),
    )


def test_projection_uses_logical_refs_and_never_keeps_provider_summary():
    registry = CanonicalIntentTextRegistry()
    structured = AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="provider-owned summary must not persist",
        planned_steps=[
            AgentBuilderPlannedStep(
                step_id="provider_step_1",
                capability="start_input",
                purpose=registry.purpose_for("start_input"),
            ),
            AgentBuilderPlannedStep(
                step_id="provider_step_2",
                capability="answer",
                purpose=registry.purpose_for("answer"),
                depends_on=["provider_step_1"],
            ),
        ],
        required_capabilities=["start_input", "answer"],
    )

    plan = project_structured_intent_plan(structured, _context())

    assert plan is not None
    assert [step.occurrence for step in plan.logical_steps] == [1, 1]
    assert "provider-owned summary" not in plan.model_dump_json()
    assert "provider_step_1" not in plan.model_dump_json()


def test_current_rehydrator_fails_closed_without_an_authoritative_snapshot():
    registry = CanonicalIntentTextRegistry()
    context = _context()
    structured = AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="safe",
        planned_steps=[
            AgentBuilderPlannedStep(
                step_id="step_start",
                capability="start_input",
                purpose=registry.purpose_for("start_input"),
            ),
            AgentBuilderPlannedStep(
                step_id="step_answer",
                capability="answer",
                purpose=registry.purpose_for("answer"),
                depends_on=["step_start"],
            ),
        ],
        required_capabilities=["start_input", "answer"],
    )
    plan = project_structured_intent_plan(structured, context)

    assert plan is not None
    result = current_rehydrator_for(context, plan).rehydrate(plan, context)

    assert result.status == "failure"
    assert result.reason == "current_context_invalid"

def test_projection_rejects_explicit_parameter_values_instead_of_storing_them():
    registry = CanonicalIntentTextRegistry()
    structured = AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="safe",
        planned_steps=[
            AgentBuilderPlannedStep(
                step_id="step_1",
                capability="slack_send",
                purpose=registry.purpose_for("slack_send"),
            )
        ],
        explicit_parameter_values=[
            AgentBuilderExplicitParameterValue(
                step_id="step_1",
                parameter_key="channel",
                value="C0123456",
            )
        ],
    )

    assert project_structured_intent_plan(structured, _context()) is None


def test_knowledge_projection_stores_closed_topic_ref_not_topic_or_handle():
    registry = CanonicalIntentTextRegistry()
    structured = AgentBuilderStructuredRequest(
        request_type="new_workflow",
        draft_mode="new_workflow",
        intent_summary="safe",
        planned_steps=[
            AgentBuilderPlannedStep(
                step_id="step_kb",
                capability="knowledge_backed_llm",
                purpose=registry.purpose_for("knowledge_backed_llm"),
            )
        ],
        knowledge_requirements=[
            AgentBuilderKnowledgeRequirement(
                requirement_id="kr_1",
                query_topics=["사내 문서"],
                suggested_candidate_handles=["current-request-only-handle"],
                expected_evidence_type="policy_or_reference",
                required=True,
                target_step_ref="step_kb",
            )
        ],
        knowledge_placements=[
            AgentBuilderKnowledgePlacement(
                requirement_id="kr_1",
                timing="after_graph",
                effect_kind="binding_only",
                target_step_id="step_kb",
            )
        ],
    )

    plan = project_structured_intent_plan(structured, _context())

    assert plan is not None
    assert plan.knowledge_requirements[0].topic_refs == ("topic.internal_documents.v1",)
    payload = plan.model_dump_json()
    assert "사내 문서" not in payload
    assert "current-request-only-handle" not in payload
