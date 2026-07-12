import uuid

import pytest
from apps.shared.domain.mail_credential import (
    MailNodeCredentialBoundaryError,
    validate_mail_node_credential_boundary,
    validate_mail_processing_node_boundary,
)


def test_durable_mail_node_rejects_immediate_mark_as_read():
    with pytest.raises(MailNodeCredentialBoundaryError):
        validate_mail_node_credential_boundary(
            {
                "title": "Mail",
                "credential_id": str(uuid.uuid4()),
                "processing_mode": "durable",
                "mark_as_read": True,
            }
        )


def test_gmail_draft_boundary_accepts_only_opaque_selectors():
    validate_mail_processing_node_boundary(
        "gmailDraftNode",
        {
            "title": "Draft",
            "credential_id": None,
            "configuration_state": "unresolved",
            "processing_ref_selector": ["mail", "processing_ref"],
            "reply_body_selector": ["llm", "result"],
        },
    )
    with pytest.raises(MailNodeCredentialBoundaryError):
        validate_mail_processing_node_boundary(
            "gmailDraftNode",
            {
                "title": "Draft",
                "processing_ref_selector": ["mail", "processing_ref"],
                "reply_body_selector": ["llm", "result"],
                "recipient": "attacker@example.com",
            },
        )


def test_mail_acknowledge_boundary_requires_effect_selectors():
    with pytest.raises(MailNodeCredentialBoundaryError):
        validate_mail_processing_node_boundary(
            "mailAcknowledgeNode",
            {
                "title": "Acknowledge",
                "processing_ref_selector": ["mail", "processing_ref"],
                "required_effect_ref_selectors": [],
            },
        )


def test_processing_node_allows_empty_selectors_only_for_unresolved_draft():
    data = {
        "title": "Draft",
        "credential_id": None,
        "configuration_state": "unresolved",
        "processing_ref_selector": [],
        "reply_body_selector": [],
    }

    validate_mail_processing_node_boundary(
        "gmailDraftNode",
        data,
        allow_unresolved=True,
    )
    with pytest.raises(MailNodeCredentialBoundaryError):
        validate_mail_processing_node_boundary("gmailDraftNode", data)


def test_mail_node_credential_boundary_accepts_only_reference_configuration():
    validate_mail_node_credential_boundary(
        {
            "title": "Mail",
            "credential_id": None,
            "configuration_state": "unresolved",
            "parameters": {},
        }
    )


@pytest.mark.parametrize(
    "data",
    [
        "synthetic-only",
        {"title": "Mail", "app_password": "synthetic-only"},
        {"title": "Mail", "parameters": {"secret": "synthetic-only"}},
        {"title": "Mail", "credential": "synthetic-only"},
    ],
)
def test_mail_node_credential_boundary_rejects_alternate_secret_fields(data):
    with pytest.raises(
        MailNodeCredentialBoundaryError,
        match="^mail.credential_reference_required$",
    ):
        validate_mail_node_credential_boundary(data)
