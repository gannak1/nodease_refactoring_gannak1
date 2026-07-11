"""Mail node credential reference tests."""

import imaplib
import ssl
import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from apps.workflow_engine.services.mail_credential_service import (
    ResolvedMailCredential,
)
from apps.workflow_engine.workflow.core.workflow_node_factory import NodeFactory
from apps.workflow_engine.workflow.nodes.mail.entities import MailNodeData, MailVariable
from apps.workflow_engine.workflow.nodes.mail.mail_node import (
    MAIL_IMAP_TIMEOUT_SECONDS,
    MailNode,
)


@pytest.fixture
def mock_imap():
    with patch(
        "apps.workflow_engine.workflow.nodes.mail.mail_node._PinnedIMAP4SSL"
    ) as mock:
        yield mock


@pytest.fixture
def resolved_credential():
    return ResolvedMailCredential(
        credential_id=uuid.uuid4(),
        email_address="mailbox@example.test",
        imap_host="imap.example.test",
        imap_port=993,
        resolved_ip="203.0.113.10",
        use_ssl=True,
        secret="synthetic-mail-secret",
    )


@pytest.fixture
def credential_resolver(resolved_credential):
    with patch(
        "apps.workflow_engine.workflow.nodes.mail.mail_node."
        "MailCredentialResolver.resolve",
        return_value=resolved_credential,
    ) as resolver:
        yield resolver


def _node_data(credential_id: uuid.UUID, **overrides) -> MailNodeData:
    data = {
        "title": "Mail Search",
        "credential_id": credential_id,
        "keyword": "test",
        "folder": "INBOX",
        "max_results": 10,
        "referenced_variables": [],
    }
    data.update(overrides)
    return MailNodeData(**data)


def _node(data: MailNodeData) -> MailNode:
    subject_id = uuid.uuid4()
    return MailNode(
        id="mail-test",
        data=data,
        execution_context={
            "user_id": str(uuid.uuid4()),
            "execution_subject": {
                "type": "user",
                "id": str(subject_id),
            },
            "organization_id": str(uuid.uuid4()),
            "db": MagicMock(),
        },
    )


def test_mail_search_success(mock_imap, resolved_credential, credential_resolver):
    mock_mail = MagicMock()
    mock_mail.select.return_value = ("OK", [b"INBOX"])
    mock_mail.search.return_value = ("OK", [b"1 2 3"])
    mock_email_data = b"""From: sender@example.com
To: recipient@example.com
Subject: Test Email
Date: Mon, 05 Jan 2026 10:00:00 +0000

This is a test email body.
"""
    mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822 {123})", mock_email_data)])
    mock_imap.return_value = mock_mail

    node = _node(_node_data(resolved_credential.credential_id))
    result = node._run(inputs={})

    assert result["total_count"] == 3
    assert result["folder"] == "INBOX"
    assert result["emails"][0]["subject"] == "Test Email"
    mock_mail.login.assert_called_once_with(
        "mailbox@example.test", "synthetic-mail-secret"
    )
    assert credential_resolver.call_count == 1
    _, kwargs = mock_imap.call_args
    tls_context = kwargs["ssl_context"]
    assert tls_context.verify_mode == ssl.CERT_REQUIRED
    assert tls_context.check_hostname is True
    assert kwargs["timeout"] == MAIL_IMAP_TIMEOUT_SECONDS


def test_mail_variable_substitution(
    mock_imap, resolved_credential, credential_resolver
):
    mock_mail = MagicMock()
    mock_mail.select.return_value = ("OK", [b"INBOX"])
    mock_mail.search.return_value = ("OK", [b"1"])
    mock_email_data = b"""From: sender@example.com
To: recipient@example.com
Subject: PR #123
Date: Mon, 05 Jan 2026 10:00:00 +0000

Pull request merged.
"""
    mock_mail.fetch.return_value = ("OK", [(b"1 (RFC822 {123})", mock_email_data)])
    mock_imap.return_value = mock_mail
    node = _node(
        _node_data(
            resolved_credential.credential_id,
            keyword="{{pr_number}}",
            referenced_variables=[
                MailVariable(name="pr_number", value_selector=["start-123", "pr_id"])
            ],
        )
    )

    result = node._run(inputs={"start-123": {"pr_id": "PR #123"}})

    assert result["total_count"] == 1
    mock_mail.search.assert_called_once_with(None, mock_mail.search.call_args.args[1])
    assert 'TEXT "PR #123"' in mock_mail.search.call_args.args[1]


def test_mail_search_criteria_escape_quotes_and_backslashes():
    node = _node(_node_data(uuid.uuid4()))

    query = node._build_search_query('report "Q3" \\ final', "", "")

    assert query.startswith('TEXT "report \\"Q3\\" \\\\ final"')


@pytest.mark.parametrize("value", ["safe\r\nA1 NOOP", "safe\x00A1 NOOP"])
def test_mail_search_criteria_reject_protocol_control_characters(value):
    node = _node(_node_data(uuid.uuid4()))

    with pytest.raises(RuntimeError, match="^mail.search_criteria_invalid$"):
        node._build_search_query(value, "", "")


def test_mail_authentication_failure_is_redacted(
    mock_imap, resolved_credential, credential_resolver
):
    mock_imap.return_value.login.side_effect = imaplib.IMAP4.error(
        "provider detail must not escape"
    )
    node = _node(_node_data(resolved_credential.credential_id))

    with pytest.raises(RuntimeError, match="^mail.authentication_failed$") as exc:
        node._run(inputs={})

    assert "provider detail" not in str(exc.value)
    mock_imap.return_value.shutdown.assert_called_once_with()


def test_mail_post_login_provider_failure_is_redacted(
    mock_imap, resolved_credential, credential_resolver
):
    mock_mail = MagicMock()
    mock_mail.select.return_value = ("OK", [b"INBOX"])
    mock_mail.search.side_effect = imaplib.IMAP4.error(
        "provider mailbox detail must not escape"
    )
    mock_imap.return_value = mock_mail
    node = _node(_node_data(resolved_credential.credential_id))

    with pytest.raises(RuntimeError, match="^mail.operation_failed$") as exc:
        node._run(inputs={})

    assert "provider mailbox detail" not in str(exc.value)
    mock_mail.logout.assert_called_once()


def test_mail_logout_failure_does_not_override_successful_result(
    mock_imap, resolved_credential, credential_resolver
):
    mock_mail = MagicMock()
    mock_mail.select.return_value = ("OK", [b"INBOX"])
    mock_mail.search.return_value = ("OK", [b""])
    mock_mail.logout.side_effect = imaplib.IMAP4.abort(
        "provider cleanup detail must not escape"
    )
    mock_imap.return_value = mock_mail
    node = _node(_node_data(resolved_credential.credential_id))

    result = node._run(inputs={})

    assert result["emails"] == []


@patch("apps.workflow_engine.workflow.nodes.mail.mail_node._PinnedIMAP4")
def test_port_143_negotiates_starttls_before_login(plain_imap, resolved_credential):
    starttls_credential = ResolvedMailCredential(
        credential_id=resolved_credential.credential_id,
        email_address=resolved_credential.email_address,
        imap_host=resolved_credential.imap_host,
        imap_port=143,
        resolved_ip=resolved_credential.resolved_ip,
        use_ssl=False,
        secret=resolved_credential.secret,
    )
    mail = plain_imap.return_value
    node = _node(_node_data(starttls_credential.credential_id))

    node._connect_imap(starttls_credential)

    _, kwargs = plain_imap.call_args
    assert kwargs["timeout"] == MAIL_IMAP_TIMEOUT_SECONDS
    assert mail.method_calls[0][0] == "starttls"
    starttls_context = mail.starttls.call_args.kwargs["ssl_context"]
    assert starttls_context.verify_mode == ssl.CERT_REQUIRED
    assert starttls_context.check_hostname is True
    assert mail.method_calls[1] == (
        "login",
        ("mailbox@example.test", "synthetic-mail-secret"),
        {},
    )


def test_mail_empty_results(mock_imap, resolved_credential, credential_resolver):
    mock_mail = MagicMock()
    mock_mail.select.return_value = ("OK", [b"INBOX"])
    mock_mail.search.return_value = ("OK", [b""])
    mock_imap.return_value = mock_mail
    node = _node(_node_data(resolved_credential.credential_id))

    result = node._run(inputs={})

    assert result["total_count"] == 0
    assert result["emails"] == []


def test_node_factory_rejects_legacy_inline_secret_without_echoing_value():
    legacy_value = "synthetic-legacy-secret"
    schema = SimpleNamespace(
        id="mail-test",
        type="mailNode",
        data={
            "title": "Legacy Mail",
            "email": "mailbox@example.test",
            "password": legacy_value,
        },
    )

    with pytest.raises(ValueError, match="^mail.credential_reference_required$") as exc:
        NodeFactory.create(schema)

    assert legacy_value not in str(exc.value)


def test_mail_node_does_not_fallback_to_workflow_or_app_owner_identity():
    node = MailNode(
        id="mail-test",
        data=_node_data(uuid.uuid4()),
        execution_context={
            "user_id": str(uuid.uuid4()),
            "organization_id": str(uuid.uuid4()),
            "db": MagicMock(),
        },
    )

    with (
        patch(
            "apps.workflow_engine.workflow.nodes.mail.mail_node."
            "MailCredentialResolver.resolve"
        ) as resolver,
        pytest.raises(RuntimeError, match="^mail.execution_subject_required$"),
    ):
        node._run(inputs={})

    resolver.assert_not_called()
