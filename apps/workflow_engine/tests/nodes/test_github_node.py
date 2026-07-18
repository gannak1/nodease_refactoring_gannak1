"""GitHub 노드의 opaque credential reference 실행 경계 테스트."""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
import requests

from apps.shared.services.external_action_credential import (
    ExternalActionCredentialRuntimeError,
    ExternalActionCredentialUseResolver,
)
from apps.workflow_engine.workflow.nodes.github.entities import (
    GithubAction,
    GithubNodeData,
    GithubVariable,
)
from apps.workflow_engine.workflow.errors import NonRetryableWorkflowError
from apps.workflow_engine.workflow.nodes.github.github_node import GithubNode


ORGANIZATION_ID = uuid4()
USER_ID = uuid4()
CREDENTIAL_ID = uuid4()


@pytest.fixture(autouse=True)
def _stub_external_action_credential_resolver(monkeypatch):
    def resolve(_db, **kwargs):
        assert kwargs == {
            "user_id": USER_ID,
            "organization_id": ORGANIZATION_ID,
            "credential_id": CREDENTIAL_ID,
            "expected_provider": "github",
        }
        return SimpleNamespace(secret="test-only-placeholder", revision=1)

    monkeypatch.setattr(
        ExternalActionCredentialUseResolver,
        "resolve",
        staticmethod(resolve),
    )
    monkeypatch.setattr(
        ExternalActionCredentialUseResolver,
        "revalidate_use",
        staticmethod(lambda _db, **_kwargs: None),
    )


def _github_node(**overrides) -> GithubNode:
    data = {
        "title": "GitHub",
        "credential_id": str(CREDENTIAL_ID),
        **overrides,
    }
    return GithubNode(
        id="github-1",
        data=GithubNodeData(**data),
        execution_context={
            "organization_id": str(ORGANIZATION_ID),
            "execution_subject": {"subject_type": "user", "subject_id": str(USER_ID)},
            "db": MagicMock(),
        },
    )


@patch("requests.get")
def test_get_pr_success(mock_get):
    pr_response = MagicMock()
    pr_response.json.return_value = {
        "title": "Add new feature",
        "body": "This PR adds a new feature",
        "state": "open",
        "number": 123,
        "diff_url": "https://github.com/owner/repo/pull/123.diff",
    }
    files_response = MagicMock()
    files_response.json.return_value = [
        {
            "filename": "src/app.py",
            "status": "modified",
            "additions": 10,
            "deletions": 5,
            "changes": 15,
            "patch": "@@ -1,5 +1,10 @@\n+new code",
        }
    ]
    mock_get.side_effect = [pr_response, files_response]

    result = _github_node(
        action=GithubAction.GET_PR,
        repo_owner="facebook",
        repo_name="react",
        pr_number="123",
    )._run(inputs={})

    assert result["pr_title"] == "Add new feature"
    assert result["pr_body"] == "This PR adds a new feature"
    assert result["pr_state"] == "open"
    assert result["pr_number"] == 123
    assert result["files_count"] == 1
    assert result["files"][0]["filename"] == "src/app.py"
    assert result["files"][0]["additions"] == 10
    assert result["diff_url"] == "https://github.com/owner/repo/pull/123.diff"
    assert mock_get.call_count == 2


@patch("requests.post")
def test_comment_pr_success(mock_post):
    comment_response = MagicMock()
    comment_response.json.return_value = {
        "id": 456789,
        "html_url": "https://github.com/owner/repo/pull/123#issuecomment-456789",
        "body": "Great work!",
    }
    mock_post.return_value = comment_response

    result = _github_node(
        action=GithubAction.COMMENT_PR,
        repo_owner="facebook",
        repo_name="react",
        pr_number="123",
        comment_body="Great work!",
    )._run(inputs={})

    assert result == {
        "comment_id": 456789,
        "comment_url": "https://github.com/owner/repo/pull/123#issuecomment-456789",
        "comment_body": "Great work!",
    }
    mock_post.assert_called_once()
    assert "/issues/123/comments" in mock_post.call_args[0][0]
    assert mock_post.call_args.kwargs["json"]["body"] == "Great work!"


@patch("requests.post")
def test_variable_substitution_uses_opaque_credential_reference(mock_post):
    response = MagicMock()
    response.json.return_value = {
        "id": 1,
        "html_url": "https://github.com/test",
        "body": "Review result: LGTM!",
    }
    mock_post.return_value = response

    _github_node(
        action=GithubAction.COMMENT_PR,
        repo_owner="facebook",
        repo_name="react",
        pr_number="123",
        comment_body="Review result: {{ review }}",
        referenced_variables=[
            GithubVariable(name="review", value_selector=["llm-1", "text"])
        ],
    )._run(inputs={"llm-1": {"text": "LGTM!"}})

    assert mock_post.call_args.kwargs["json"]["body"] == "Review result: LGTM!"


@patch("requests.get")
def test_provider_request_failure_is_safe(mock_get):
    error_response = MagicMock()
    error_response.raise_for_status.side_effect = requests.exceptions.HTTPError(
        "401 Unauthorized"
    )
    mock_get.return_value = error_response

    with pytest.raises(RuntimeError, match="github.provider_request_failed"):
        _github_node(
            action=GithubAction.GET_PR,
            repo_owner="facebook",
            repo_name="react",
            pr_number="123",
        )._run(inputs={})


def test_missing_credential_reference_fails_before_resolver_or_provider_call():
    node = _github_node(
        action=GithubAction.GET_PR,
        credential_id=None,
        repo_owner="facebook",
        repo_name="react",
        pr_number="123",
    )

    with pytest.raises(
        NonRetryableWorkflowError,
        match="external_action_credential.reference_required",
    ):
        node._run(inputs={})


@patch("requests.get")
def test_revoked_or_rotated_credential_blocks_provider_call(mock_get, monkeypatch):
    def deny_revalidation(_db, **_kwargs):
        raise ExternalActionCredentialRuntimeError()

    monkeypatch.setattr(
        ExternalActionCredentialUseResolver,
        "revalidate_use",
        staticmethod(deny_revalidation),
    )

    with pytest.raises(
        NonRetryableWorkflowError,
        match="external_action_credential.unavailable",
    ):
        _github_node(
            action=GithubAction.GET_PR,
            repo_owner="facebook",
            repo_name="react",
            pr_number="123",
        )._run(inputs={})

    mock_get.assert_not_called()


@patch("requests.get")
def test_credential_resolution_session_closes_before_github_provider_call(mock_get):
    initial_session = MagicMock()
    first_revalidation_session = MagicMock()
    second_revalidation_session = MagicMock()
    sessions = iter(
        (initial_session, first_revalidation_session, second_revalidation_session)
    )
    pr_response = MagicMock()
    pr_response.json.return_value = {
        "title": "Add new feature",
        "body": "",
        "state": "open",
        "number": 123,
        "diff_url": "https://github.com/owner/repo/pull/123.diff",
    }
    files_response = MagicMock()
    files_response.json.return_value = []
    provider_responses = iter((pr_response, files_response))

    def provider_get(*_args, **_kwargs):
        initial_session.close.assert_called_once_with()
        return next(provider_responses)

    mock_get.side_effect = provider_get
    node = _github_node(
        action=GithubAction.GET_PR,
        repo_owner="facebook",
        repo_name="react",
        pr_number="123",
    )
    node.execution_context["db_session_factory"] = lambda: next(sessions)

    node._run(inputs={})

    first_revalidation_session.close.assert_called_once_with()
    second_revalidation_session.close.assert_called_once_with()
