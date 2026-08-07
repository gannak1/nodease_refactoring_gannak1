from __future__ import annotations

from cryptography.fernet import Fernet
import pytest

from apps.gateway.adapters.cache.agent_builder_intent_plan_l2 import (
    IntentPlanL2EnvelopeCodec,
    IntentPlanL2EnvelopeError,
)
from apps.gateway.application.agent_builder.intent_cache.contracts import (
    CachedIntentPlanV1,
    IntentPlanContractVersions,
    LogicalStepRef,
)
from apps.shared.services.credential_encryption import CredentialEncryptionService


def _plan() -> CachedIntentPlanV1:
    versions = IntentPlanContractVersions(
        normalizer_version="intent-normalizer-v2",
        cache_schema_version=1,
        planner_contract_version="agent-builder-intent-v1",
        catalog_version=3,
        canonical_text_registry_version="intent-text-v1",
        materializer_version="agent-builder-direct-edit-v1",
    )
    return CachedIntentPlanV1(
        schema_version=1,
        request_type="new_workflow",
        draft_mode="new_workflow",
        ordered_capabilities=("start_input", "answer"),
        logical_steps=(
            LogicalStepRef(capability="start_input", occurrence=1),
            LogicalStepRef(capability="answer", occurrence=1),
        ),
        contract_versions=versions,
    )


def _codec() -> IntentPlanL2EnvelopeCodec:
    encryption = CredentialEncryptionService(
        {"l2-v1": Fernet.generate_key().decode("utf-8")},
        "l2-v1",
        subject_label="Agent Builder L2 cache",
    )
    return IntentPlanL2EnvelopeCodec(
        hmac_key=b"l2-test-hmac-key-material-at-least-32-bytes",
        hmac_key_version="l2-hmac-v1",
        encryption=encryption,
        max_payload_bytes=32 * 1024,
    )


def test_l2_lookup_token_is_versioned_and_uses_full_canonical_material():
    codec = _codec()

    organization_a = codec.lookup_token(b'{"organization_id":"organization-a"}')
    organization_b = codec.lookup_token(b'{"organization_id":"organization-b"}')

    assert organization_a != organization_b
    assert len(organization_a) == 64
    assert codec.lookup_key_version == "l2-hmac-v1"


def test_l2_envelope_round_trip_never_persists_plaintext_plan():
    codec = _codec()
    lookup_token = codec.lookup_token(b"canonical-material")

    envelope = codec.encode(_plan(), lookup_token=lookup_token)

    assert envelope.encryption_key_version == "l2-v1"
    assert envelope.encryption_algorithm == "fernet-v1"
    assert "start_input" not in envelope.ciphertext
    assert codec.decode(envelope, lookup_token=lookup_token) == _plan()


def test_l2_envelope_cannot_be_moved_to_another_lookup_token():
    codec = _codec()
    envelope = codec.encode(
        _plan(),
        lookup_token=codec.lookup_token(b"organization-a"),
    )

    with pytest.raises(IntentPlanL2EnvelopeError):
        codec.decode(
            envelope,
            lookup_token=codec.lookup_token(b"organization-b"),
        )
