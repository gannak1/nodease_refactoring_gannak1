"""GitHub API integration node using opaque credential references."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import requests
from jinja2 import Environment

from apps.shared.db.session import SessionLocal
from apps.shared.services.external_action_credential import (
    ExternalActionCredentialRuntimeError,
    ExternalActionCredentialUseResolver,
)
from apps.workflow_engine.adapters.providers.github import (
    GithubCommentEffectAdapter,
    GithubCommentRequest,
    GithubSecretMaterial,
)
from apps.workflow_engine.workflow.errors import NonRetryableWorkflowError
from apps.workflow_engine.workflow.nodes.base.node import Node
from apps.workflow_engine.workflow.nodes.github.entities import GithubNodeData


_jinja_env = Environment(autoescape=False)


def _get_nested_value(data: Any, keys: List[str]) -> Any:
    for key in keys:
        if isinstance(data, dict):
            data = data.get(key)
        else:
            return None
    return data


class GithubNode(Node[GithubNodeData]):
    """Run GitHub actions without persisting a GitHub secret in the graph."""

    node_type = "githubNode"

    def _run(self, inputs: Dict[str, Any]) -> Dict[str, Any]:
        data = self.data
        organization_id = self._required_context_uuid("organization_id")
        user_id = self._required_execution_subject_uuid()
        credential_id = self._credential_id()
        db, should_close = self._borrow_db_session()
        try:
            credential = ExternalActionCredentialUseResolver.resolve(
                db,
                user_id=user_id,
                organization_id=organization_id,
                credential_id=credential_id,
                expected_provider="github",
            )
            secret = GithubSecretMaterial(credential.secret)
            repo_owner = self._render_template(data.repo_owner, inputs)
            repo_name = self._render_template(data.repo_name, inputs)
            pr_number_str = self._render_template(str(data.pr_number), inputs)
            try:
                pr_number = int(pr_number_str)
            except ValueError as exc:
                raise ValueError("github.pr_number_invalid") from exc
            if pr_number <= 0:
                raise ValueError("github.pr_number_invalid")

            if data.action == "get_pr":
                self._guard_read_only_effect_slot()
                return self._get_pull_request(
                    secret=secret,
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    pr_number=pr_number,
                    user_id=user_id,
                    organization_id=organization_id,
                    credential_id=credential_id,
                    credential_revision=credential.revision,
                )
            if data.action == "comment_pr":
                comment_body = self._render_template(data.comment_body or "", inputs)
                if not comment_body:
                    raise ValueError("github.comment_body_required")
                return self._create_comment(
                    secret=secret,
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    pr_number=pr_number,
                    comment_body=comment_body,
                    user_id=user_id,
                    organization_id=organization_id,
                    credential_id=credential_id,
                    credential_revision=credential.revision,
                )
            raise ValueError("github.action_unsupported")
        except ExternalActionCredentialRuntimeError as exc:
            # A missing, revoked, or newly rotated credential cannot be made
            # valid by retrying this workflow run.  Keep it out of Celery's
            # generic retry path just like the Slack node does.
            raise NonRetryableWorkflowError(exc.reason_code) from exc
        finally:
            if should_close:
                db.close()

    def _get_pull_request(
        self,
        *,
        secret: GithubSecretMaterial,
        repo_owner: str,
        repo_name: str,
        pr_number: int,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        credential_revision: int,
    ) -> Dict[str, Any]:
        headers = self._headers(secret)
        base_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}"
        try:
            self._revalidate_credential_use(
                user_id=user_id,
                organization_id=organization_id,
                credential_id=credential_id,
                expected_revision=credential_revision,
            )
            pr_response = requests.get(
                f"{base_url}/pulls/{pr_number}",
                headers=headers,
                timeout=30,
            )
            pr_response.raise_for_status()
            pr = pr_response.json()

            self._revalidate_credential_use(
                user_id=user_id,
                organization_id=organization_id,
                credential_id=credential_id,
                expected_revision=credential_revision,
            )
            files_response = requests.get(
                f"{base_url}/pulls/{pr_number}/files",
                headers=headers,
                timeout=30,
            )
            files_response.raise_for_status()
            files_data = files_response.json()
        except ExternalActionCredentialRuntimeError:
            raise
        except requests.exceptions.RequestException:
            raise RuntimeError("github.provider_request_failed") from None
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("github.provider_response_invalid") from None

        files = [
            {
                "filename": item["filename"],
                "status": item["status"],
                "additions": item["additions"],
                "deletions": item["deletions"],
                "changes": item["changes"],
                "patch": item.get("patch", ""),
            }
            for item in files_data
        ]
        try:
            return {
                "pr_title": pr["title"],
                "pr_body": pr.get("body") or "",
                "pr_state": pr["state"],
                "pr_number": pr["number"],
                "files_count": len(files),
                "files": files,
                "diff_url": pr["diff_url"],
            }
        except (KeyError, TypeError):
            raise RuntimeError("github.provider_response_invalid") from None

    def _create_comment(
        self,
        *,
        secret: GithubSecretMaterial,
        repo_owner: str,
        repo_name: str,
        pr_number: int,
        comment_body: str,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        credential_revision: int,
    ) -> Dict[str, Any]:
        if self._runtime_control is not None:
            adapter = GithubCommentEffectAdapter()
            output = self._run_external_effect(
                adapter,
                GithubCommentRequest(
                    secret=secret,
                    repo_owner=repo_owner,
                    repo_name=repo_name,
                    pr_number=pr_number,
                    comment_body=comment_body,
                    authorization_guard=lambda: self._revalidate_credential_use(
                        user_id=user_id,
                        organization_id=organization_id,
                        credential_id=credential_id,
                        expected_revision=credential_revision,
                    ),
                ),
            )
            self._capture_provider_trace(adapter)
            self._trace_payloads = []
            return output

        try:
            self._revalidate_credential_use(
                user_id=user_id,
                organization_id=organization_id,
                credential_id=credential_id,
                expected_revision=credential_revision,
            )
            response = requests.post(
                (
                    "https://api.github.com/repos/"
                    f"{repo_owner}/{repo_name}/issues/{pr_number}/comments"
                ),
                headers=self._headers(secret),
                json={"body": comment_body},
                timeout=30,
            )
            response.raise_for_status()
            comment = response.json()
            return {
                "comment_id": comment["id"],
                "comment_url": comment["html_url"],
                "comment_body": comment["body"],
            }
        except ExternalActionCredentialRuntimeError:
            raise
        except requests.exceptions.RequestException:
            raise RuntimeError("github.provider_request_failed") from None
        except (KeyError, TypeError, ValueError):
            raise RuntimeError("github.provider_response_invalid") from None

    @staticmethod
    def _headers(secret: GithubSecretMaterial) -> dict[str, str]:
        return {
            "Authorization": f"token {secret.reveal_for_adapter()}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "moduly",
        }

    def _credential_id(self) -> uuid.UUID:
        try:
            return uuid.UUID(str(self.data.credential_id))
        except (TypeError, ValueError) as exc:
            raise NonRetryableWorkflowError(
                "external_action_credential.reference_required"
            ) from exc

    def _required_context_uuid(self, key: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(self.execution_context.get(key)))
        except (TypeError, ValueError) as exc:
            raise NonRetryableWorkflowError(
                "external_action_credential.context_invalid"
            ) from exc

    def _required_execution_subject_uuid(self) -> uuid.UUID:
        subject = self.execution_context.get("execution_subject")
        if not isinstance(subject, dict):
            raise NonRetryableWorkflowError(
                "external_action_credential.execution_subject_required"
            )
        subject_type = subject.get("subject_type") or subject.get("type") or "user"
        subject_id = subject.get("subject_id") or subject.get("id")
        if subject_type != "user":
            raise NonRetryableWorkflowError(
                "external_action_credential.execution_subject_required"
            )
        try:
            return uuid.UUID(str(subject_id))
        except (TypeError, ValueError) as exc:
            raise NonRetryableWorkflowError(
                "external_action_credential.execution_subject_required"
            ) from exc

    def _borrow_db_session(self):
        factory = self.execution_context.get("db_session_factory")
        if callable(factory):
            return factory(), True
        legacy_session = self.execution_context.get("db")
        if legacy_session is not None:
            return legacy_session, False
        return SessionLocal(), True

    def _revalidate_credential_use(
        self,
        *,
        user_id: uuid.UUID,
        organization_id: uuid.UUID,
        credential_id: uuid.UUID,
        expected_revision: int | None = None,
    ) -> None:
        db, should_close = self._borrow_db_session()
        try:
            ExternalActionCredentialUseResolver.revalidate_use(
                db,
                user_id=user_id,
                organization_id=organization_id,
                credential_id=credential_id,
                expected_provider="github",
                expected_revision=expected_revision,
            )
        finally:
            if should_close:
                db.close()

    def _render_template(self, template: Optional[str], inputs: Dict[str, Any]) -> str:
        if not template:
            return ""
        context: Dict[str, Any] = {}
        for variable in self.data.referenced_variables:
            var_name = variable.name
            selector = variable.value_selector
            if not var_name or not selector:
                context[var_name] = ""
                continue
            source_data = inputs.get(selector[0])
            if source_data is None:
                context[var_name] = ""
                continue
            if len(selector) > 1:
                value = _get_nested_value(source_data, selector[1:])
                context[var_name] = value if value is not None else ""
            else:
                context[var_name] = source_data
        try:
            return _jinja_env.from_string(template).render(**context)
        except Exception:
            raise ValueError("github.template_render_failed") from None
