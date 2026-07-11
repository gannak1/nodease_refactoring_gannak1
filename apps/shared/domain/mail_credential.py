from __future__ import annotations

from collections.abc import Mapping
from typing import Any

MAIL_CREDENTIAL_REFERENCE_REQUIRED = "mail.credential_reference_required"

MAIL_NODE_ALLOWED_DATA_FIELDS = frozenset(
    {
        "title",
        "description",
        "parameters",
        "credential_id",
        "configuration_state",
        "keyword",
        "sender",
        "subject",
        "start_date",
        "end_date",
        "folder",
        "max_results",
        "unread_only",
        "mark_as_read",
        "referenced_variables",
        "displayNumber",
        "visibleProperties",
    }
)

MAIL_NODE_VISIBLE_PROPERTY_KEYS = frozenset({"credential_id", "folder", "filters"})


class MailNodeCredentialBoundaryError(ValueError):
    def __init__(self) -> None:
        super().__init__(MAIL_CREDENTIAL_REFERENCE_REQUIRED)
        self.reason_code = MAIL_CREDENTIAL_REFERENCE_REQUIRED


def validate_mail_node_credential_boundary(data: Any) -> None:
    """Reject Mail graph fields that can become an alternate credential store."""
    if not isinstance(data, Mapping):
        raise MailNodeCredentialBoundaryError()
    if set(data) - MAIL_NODE_ALLOWED_DATA_FIELDS:
        raise MailNodeCredentialBoundaryError()

    # BaseNodeData.parameters is intentionally flexible for other nodes. Mail
    # credentials have a dedicated resource, so this alternate storage bag must
    # stay empty.
    parameters = data.get("parameters")
    if parameters not in (None, {}):
        raise MailNodeCredentialBoundaryError()

    display_number = data.get("displayNumber")
    if display_number is not None and (
        not isinstance(display_number, int)
        or isinstance(display_number, bool)
        or display_number < 1
    ):
        raise MailNodeCredentialBoundaryError()

    visible_properties = data.get("visibleProperties")
    if visible_properties is not None and (
        not isinstance(visible_properties, list)
        or any(
            not isinstance(item, str) or item not in MAIL_NODE_VISIBLE_PROPERTY_KEYS
            for item in visible_properties
        )
    ):
        raise MailNodeCredentialBoundaryError()
