import pytest
from apps.shared.domain.mail_credential import (
    MailNodeCredentialBoundaryError,
    validate_mail_node_credential_boundary,
)


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
