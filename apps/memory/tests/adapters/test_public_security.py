from __future__ import annotations

import secrets

from cryptography.fernet import Fernet

from apps.memory.adapters.security import (
    FernetSecretReplayCipher,
    HmacPublicSecretIssuer,
)


def test_access_and_purge_capabilities_have_separate_hmac_purposes():
    issuer = HmacPublicSecretIssuer(secrets.token_bytes(32))

    access = issuer.issue_access_grant()
    receipt = issuer.issue_purge_receipt()

    assert issuer.access_grant_verifier(access.raw_value) == (
        access.verifier_key_version,
        access.verifier_hash,
    )
    assert issuer.purge_receipt_verifier(receipt.raw_value) == (
        receipt.verifier_key_version,
        receipt.verifier_hash,
    )
    assert issuer.access_grant_verifier(receipt.raw_value) is None
    assert issuer.purge_receipt_verifier(access.raw_value) is None


def test_malformed_public_capability_never_has_a_verifier():
    issuer = HmacPublicSecretIssuer(secrets.token_bytes(32))

    assert issuer.access_grant_verifier("bad") is None
    assert issuer.access_grant_verifier("cag_v1_unsafe value") is None
    assert issuer.purge_receipt_verifier("cpr_v1_short") is None


def test_replay_ciphertext_requires_matching_idempotency_associated_data():
    cipher = FernetSecretReplayCipher(Fernet.generate_key())
    issuer = HmacPublicSecretIssuer(secrets.token_bytes(32))
    issued = issuer.issue_access_grant()
    digest = "a" * 64

    envelope = cipher.encrypt(issued.raw_value, associated_data_digest=digest)

    assert (
        cipher.decrypt(
            envelope.ciphertext,
            key_version=envelope.key_version,
            associated_data_digest=digest,
        )
        == issued.raw_value
    )
    assert (
        cipher.decrypt(
            envelope.ciphertext,
            key_version=envelope.key_version,
            associated_data_digest="b" * 64,
        )
        is None
    )
    assert (
        cipher.decrypt(
            b"invalid-ciphertext",
            key_version=envelope.key_version,
            associated_data_digest=digest,
        )
        is None
    )
