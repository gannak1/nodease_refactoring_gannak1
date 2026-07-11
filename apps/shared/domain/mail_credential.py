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
        "processing_mode",
        "referenced_variables",
        "displayNumber",
        "visibleProperties",
    }
)

MAIL_NODE_VISIBLE_PROPERTY_KEYS = frozenset({"credential_id", "folder", "filters"})

GMAIL_DRAFT_NODE_ALLOWED_DATA_FIELDS = frozenset(
    {
        "title",
        "description",
        "parameters",
        "credential_id",
        "configuration_state",
        "processing_ref_selector",
        "reply_body_selector",
        "displayNumber",
        "visibleProperties",
    }
)
MAIL_ACKNOWLEDGE_NODE_ALLOWED_DATA_FIELDS = frozenset(
    {
        "title",
        "description",
        "parameters",
        "processing_ref_selector",
        "required_effect_ref_selectors",
        "displayNumber",
        "visibleProperties",
    }
)


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

    processing_mode = data.get("processing_mode", "search_only")
    if processing_mode not in {"search_only", "durable"}:
        raise MailNodeCredentialBoundaryError()
    if processing_mode == "durable" and data.get("mark_as_read") is True:
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


def validate_mail_processing_node_boundary(
    node_type: str, data: Any, *, allow_unresolved: bool = False
) -> None:
    if not isinstance(data, Mapping):
        raise MailNodeCredentialBoundaryError()
    if node_type == "gmailDraftNode":
        allowed = GMAIL_DRAFT_NODE_ALLOWED_DATA_FIELDS
        selector_fields = ("processing_ref_selector", "reply_body_selector")
    elif node_type == "mailAcknowledgeNode":
        allowed = MAIL_ACKNOWLEDGE_NODE_ALLOWED_DATA_FIELDS
        selector_fields = ("processing_ref_selector",)
    else:
        raise MailNodeCredentialBoundaryError()
    if set(data) - allowed or data.get("parameters") not in (None, {}):
        raise MailNodeCredentialBoundaryError()
    for field_name in selector_fields:
        selector = data.get(field_name)
        if not _valid_selector(selector) and not (
            allow_unresolved and selector in (None, [])
        ):
            raise MailNodeCredentialBoundaryError()
    if node_type == "mailAcknowledgeNode":
        effect_selectors = data.get("required_effect_ref_selectors")
        if (
            not isinstance(effect_selectors, list)
            or (not effect_selectors and not allow_unresolved)
            or any(not _valid_selector(selector) for selector in effect_selectors)
        ):
            raise MailNodeCredentialBoundaryError()


def _valid_selector(value: Any) -> bool:
    return (
        isinstance(value, list)
        and len(value) >= 2
        and all(isinstance(item, str) and item.strip() for item in value)
    )
