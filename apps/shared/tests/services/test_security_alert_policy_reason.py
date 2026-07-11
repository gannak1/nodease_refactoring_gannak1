import importlib


def _normalizer():
    module = importlib.import_module(
        "apps.shared.services.security_alert_policy_reason"
    )
    return module.normalize_security_alert_policy_reason


def test_legacy_pii_policy_reason_maps_without_mutating_metadata():
    metadata = {
        "policy_result": {
            "result": "block",
            "reason_code": "pii_policy_blocked",
        }
    }
    original = {
        "policy_result": {
            "result": "block",
            "reason_code": "pii_policy_blocked",
        }
    }

    normalized = _normalizer()(metadata)

    assert normalized == "rag.pii_evidence_detected"
    assert metadata == original


def test_canonical_policy_reason_is_returned_without_mutating_metadata():
    metadata = {"policy_reason": "rag.pii_evidence_detected"}

    normalized = _normalizer()(metadata)

    assert normalized == "rag.pii_evidence_detected"
    assert metadata == {"policy_reason": "rag.pii_evidence_detected"}


def test_unknown_legacy_policy_reason_is_not_normalized():
    metadata = {
        "policy_result": {
            "result": "block",
            "reason_code": "unknown_policy_blocked",
        }
    }

    normalized = _normalizer()(metadata)

    assert normalized is None
