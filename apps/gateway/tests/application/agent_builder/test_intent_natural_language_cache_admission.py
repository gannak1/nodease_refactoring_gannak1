import uuid

from apps.gateway.application.agent_builder.intent_cache.contracts import (
    EphemeralCacheScope,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanningContext,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_normalization import (
    DeterministicIntentNormalizer,
)


def _context(message: str) -> IntentPlanningContext:
    return IntentPlanningContext(
        full_safe_message=message,
        workflow_context=IntentLogicalTopology(workflow_present=False, nodes=(), edges=()),
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
            planner_contract_version="planner-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v1",
            materializer_version="materializer-v1",
        ),
        scope=EphemeralCacheScope(
            actor_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            selected_target_type=None,
            selected_target_id=None,
        ),
    )


def test_general_natural_language_is_cache_eligible_without_phrase_allowlist():
    normalizer = DeterministicIntentNormalizer()

    slack = normalizer.normalize(_context("슬랙 노드 생성"))
    slack_spacing = normalizer.normalize(_context("  슬랙\t노드\n생성  "))
    llm = normalizer.normalize(_context("LLM 노드 생성"))
    other = normalizer.normalize(_context("매일 오전에 보고서를 요약해 보내 줘"))

    assert slack.status == "eligible"
    assert slack_spacing.status == "eligible"
    assert slack.intent_signature == slack_spacing.intent_signature
    assert llm.status == "eligible"
    assert other.status == "eligible"
