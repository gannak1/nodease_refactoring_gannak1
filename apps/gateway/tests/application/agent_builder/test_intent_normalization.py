import hashlib
import json
import uuid
from pathlib import Path

import pytest

import apps.gateway.application.agent_builder.intent_normalization as normalization_module
from apps.gateway.application.agent_builder.intent_cache import IntentNormalizerPort
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    EphemeralCacheScope,
    IntentLogicalTopology,
    IntentPlanContractVersions,
    IntentPlanningContext,
    PlannerRuntimeFingerprint,
)
from apps.gateway.application.agent_builder.intent_normalization import (
    NORMALIZER_VERSION,
    DeterministicIntentNormalizer,
)


ROOT = Path(__file__).resolve().parents[5]
FIXTURE_PATH = (
    ROOT
    / "apps/gateway/tests/fixtures/agent_builder_intent_normalization_v2.json"
)
HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def _context(
    message: str,
    *,
    selected_target_type: str | None = None,
    normalizer_version: str = NORMALIZER_VERSION,
) -> IntentPlanningContext:
    return IntentPlanningContext(
        full_safe_message=message,
        workflow_context=IntentLogicalTopology(
            workflow_present=False,
            nodes=(),
            edges=(),
        ),
        planner_runtime=PlannerRuntimeFingerprint(
            provider_ref="openai",
            model_relation_fingerprint=HEX_A,
            credential_relation_fingerprint=HEX_B,
        ),
        generation_mode="guided_generate",
        knowledge_context_fingerprint=HEX_C,
        contract_versions=IntentPlanContractVersions(
            normalizer_version=normalizer_version,
            cache_schema_version=1,
            planner_contract_version="planner-v1",
            catalog_version=3,
            canonical_text_registry_version="intent-text-v1",
            materializer_version="materializer-v1",
        ),
        scope=EphemeralCacheScope(
            actor_id=uuid.uuid4(),
            organization_id=uuid.uuid4(),
            selected_target_type=selected_target_type,
            selected_target_id=(
                uuid.uuid4().hex if selected_target_type is not None else None
            ),
        ),
    )


def _fixture_cases() -> list[dict[str, object]]:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixture["fixture_version"] == "agent-builder-intent-normalization-v2"
    assert fixture["normalizer_version"] == NORMALIZER_VERSION
    return fixture["cases"]


def test_versioned_fixture_covers_expected_status_reason_and_equivalence():
    normalizer = DeterministicIntentNormalizer()
    cases = _fixture_cases()
    results = {}

    for case in cases:
        result = normalizer.normalize(
            _context(
                str(case["synthetic_message"]),
                selected_target_type=case.get("selected_target_type"),
            )
        )
        results[str(case["id"])] = result
        assert result.status == case["expected_status"], case["id"]
        assert result.reason == case.get("expected_reason"), case["id"]
        assert result.normalizer_version == NORMALIZER_VERSION
        assert result.sensitive_input_detected is (
            case.get("expected_reason") == "sensitive_input"
        )
        if case["expected_status"] == "bypass":
            assert result.intent_signature is None, case["id"]
        else:
            assert result.intent_signature is not None, case["id"]

    groups: dict[str, list[str]] = {}
    pairs: dict[str, list[str]] = {}
    for case in cases:
        if group := case.get("equivalence_group"):
            groups.setdefault(str(group), []).append(str(case["id"]))
        if pair := case.get("distinct_pair"):
            pairs.setdefault(str(pair), []).append(str(case["id"]))

    for case_ids in groups.values():
        signatures = {results[case_id].intent_signature for case_id in case_ids}
        assert len(signatures) == 1
        assert None not in signatures
    for case_ids in pairs.values():
        signatures = {results[case_id].intent_signature for case_id in case_ids}
        assert len(signatures) == len(case_ids)
        assert None not in signatures
    for case in cases:
        if distinct_group := case.get("distinct_group"):
            group_signatures = {
                results[group_case_id].intent_signature
                for group_case_id in groups[str(distinct_group)]
            }
            assert results[str(case["id"])].intent_signature not in group_signatures


def test_signature_is_full_projection_and_version_domain_separated():
    normalizer = DeterministicIntentNormalizer()
    result = normalizer.normalize(_context("LLM 노드 추가"))

    canonical_projection = json.dumps(
        {
            "normalizer_version": NORMALIZER_VERSION,
            "segments": [
                ["catalog_capability", "llm"],
                ["literal", " 노드 추가"],
            ],
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    expected = hashlib.sha256(
        b"agent-builder:intent-normalization\x00" + canonical_projection
    ).hexdigest()

    assert result.intent_signature == expected
    assert result.model_dump() == {
        "status": "eligible",
        "intent_signature": expected,
        "reason": None,
        "normalizer_version": NORMALIZER_VERSION,
        "sensitive_input_detected": False,
    }


def test_version_mismatch_bypasses_instead_of_reading_another_namespace():
    result = DeterministicIntentNormalizer().normalize(
        _context("LLM 노드 추가", normalizer_version="intent-normalizer-v1")
    )

    assert result.status == "bypass"
    assert result.reason == "unsupported_request_shape"
    assert result.intent_signature is None
    assert result.normalizer_version == NORMALIZER_VERSION


def test_exact_alias_preserves_non_catalog_tokens_without_rewriting():
    normalizer = DeterministicIntentNormalizer()

    embedded_upper = normalizer.normalize(_context("drILLM node create"))
    embedded_lower = normalizer.normalize(_context("drillm node create"))
    quoted_upper = normalizer.normalize(_context('label "GitHub" LLM node create'))
    quoted_lower = normalizer.normalize(_context('label "github" LLM node create'))

    assert embedded_upper.status == embedded_lower.status == "eligible"
    assert embedded_upper.intent_signature != embedded_lower.intent_signature
    assert quoted_upper.status == quoted_lower.status == "eligible"
    assert quoted_upper.intent_signature != quoted_lower.intent_signature

@pytest.mark.parametrize("action", ["modify", "change", "변경"])
def test_modify_admission_ignores_quoted_labels_and_requires_selected_target(
    action: str,
):
    normalizer = DeterministicIntentNormalizer()

    ambiguous = normalizer.normalize(_context(f"{action} LLM"))
    selected = normalizer.normalize(
        _context(f"{action} LLM", selected_target_type="selected_node")
    )

    assert ambiguous.status == "bypass"
    assert ambiguous.reason == "ambiguous_target"
    assert ambiguous.intent_signature is None
    assert selected.status == "eligible"

    quoted_label = normalizer.normalize(
        _context(f'label "{action}" LLM node create')
    )
    assert quoted_label.status == "eligible"


def test_catalog_token_map_keeps_unsupported_node_tokens_as_literals():
    normalizer = DeterministicIntentNormalizer()

    upper = normalizer.normalize(_context("Loop node create"))
    lower = normalizer.normalize(_context("loop node create"))

    assert upper.status == lower.status == "eligible"
    assert upper.intent_signature != lower.intent_signature

def test_unclosed_quote_and_non_request_shape_never_create_partial_signature():
    normalizer = DeterministicIntentNormalizer()

    unclosed_quote = normalizer.normalize(_context('label "GitHub LLM node create'))
    punctuation_only = normalizer.normalize(_context("!!!"))

    assert unclosed_quote.status == "bypass"
    assert unclosed_quote.reason == "unknown_token_sequence"
    assert unclosed_quote.intent_signature is None
    assert punctuation_only.status == "bypass"
    assert punctuation_only.reason == "unsupported_request_shape"
    assert punctuation_only.intent_signature is None

    invalid_context = normalizer.normalize(object())  # type: ignore[arg-type]
    assert invalid_context.status == "bypass"
    assert invalid_context.reason == "normalizer_disabled"
    assert invalid_context.intent_signature is None

def test_catalog_exact_alias_conflict_fails_static_validation(monkeypatch):
    catalog = {
        "version": 3,
        "nodes": [
            {
                "node_type": "syntheticNode",
                "implemented": True,
                "agent_builder_supported": True,
                "capabilities": ["synthetic_a", "synthetic_b"],
                "parameters": [],
            }
        ],
        "capability_contracts": {
            "synthetic_a": {"planner_aliases": ["collision"]},
            "synthetic_b": {"planner_aliases": ["Collision"]},
        },
    }
    monkeypatch.setattr(
        normalization_module,
        "_load_catalog_normalization_metadata",
        lambda: catalog,
    )

    with pytest.raises(
        RuntimeError,
        match="catalog exact alias maps to multiple capabilities",
    ):
        normalization_module._catalog_exact_token_map()



def test_catalog_node_token_conflict_with_unowned_alias_fails_static_validation(
    monkeypatch,
):
    catalog = {
        "version": 3,
        "nodes": [
            {
                "node_type": "collisionNode",
                "implemented": True,
                "agent_builder_supported": True,
                "capabilities": ["synthetic_node"],
                "parameters": [],
            },
            {
                "node_type": "otherNode",
                "implemented": True,
                "agent_builder_supported": True,
                "capabilities": ["synthetic_other"],
                "parameters": [],
            },
        ],
        "capability_contracts": {
            "synthetic_node": {"planner_aliases": []},
            "synthetic_other": {"planner_aliases": ["collision"]},
        },
    }
    monkeypatch.setattr(
        normalization_module,
        "_load_catalog_normalization_metadata",
        lambda: catalog,
    )

    with pytest.raises(
        RuntimeError,
        match="catalog exact node token maps to conflicting capability",
    ):
        normalization_module._catalog_exact_token_map()


def test_max_length_projection_is_treated_as_potential_truncation():
    result = DeterministicIntentNormalizer().normalize(_context("L" * 4000))

    assert result.status == "bypass"
    assert result.reason == "input_projection_truncated"


def test_normalizer_implements_existing_port_without_raw_message_surface():
    normalizer = DeterministicIntentNormalizer()
    message = "safe synthetic normalization text"
    result = normalizer.normalize(_context(message))

    assert isinstance(normalizer, IntentNormalizerPort)
    assert repr(normalizer) == "<DeterministicIntentNormalizer intent-normalizer-v2>"
    assert message not in repr(normalizer)
    assert message not in result.model_dump_json()


@pytest.mark.parametrize(
    "message",
    [
        "<redacted> 노드 추가",
        "***REDACTED*** 노드 추가",
        "LLM 노드 추가 …[truncated]",
    ],
)
def test_marker_variants_fail_closed_without_echo(message):
    result = DeterministicIntentNormalizer().normalize(_context(message))

    assert result.status == "bypass"
    assert result.intent_signature is None
    assert message not in result.model_dump_json()
