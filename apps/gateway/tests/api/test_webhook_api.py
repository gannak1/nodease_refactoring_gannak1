import asyncio
import inspect
import unittest
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from unittest.mock import MagicMock

from fastapi import BackgroundTasks, HTTPException
from fastapi.testclient import TestClient

from apps.gateway.api.v1.endpoints import webhook as webhook_endpoint
from apps.gateway.api.v1.endpoints.webhook import CAPTURE_SESSIONS
from apps.gateway.auth.dependencies import get_current_user
from apps.gateway.main import app
from apps.shared.db.session import get_db
from apps.shared.db.models.workflow_deployment import DeploymentType


class _FakeRequest:
    def __init__(self, query_params=None, headers=None, payload=None):
        self.query_params = query_params or {}
        self.headers = headers or {}
        self._payload = payload if payload is not None else {}

    async def json(self):
        return self._payload


class TestWebhookApi(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.url_slug = "test-slug"
        self.auth_secret = "secret123"
        self.workflow_id = uuid4()
        self.current_user = MagicMock()
        self.current_user.id = uuid4()

        # 캡처 세션 초기화
        CAPTURE_SESSIONS.clear()
        app.dependency_overrides = {}

    def tearDown(self):
        app.dependency_overrides = {}
        CAPTURE_SESSIONS.clear()

    def _mock_db_with_app(self, *, active_deployment=False):
        mock_db_session = MagicMock()
        mock_app = MagicMock()
        mock_app.id = uuid4()
        mock_app.url_slug = self.url_slug
        mock_app.auth_secret = self.auth_secret
        mock_app.workflow_id = self.workflow_id
        mock_app.active_deployment_id = uuid4() if active_deployment else None
        mock_app.created_by = uuid4()
        mock_app.organization_id = uuid4()

        mock_deployment = MagicMock()
        mock_deployment.id = mock_app.active_deployment_id
        mock_deployment.type = DeploymentType.WEBHOOK

        def query(model):
            result = MagicMock()
            if model is webhook_endpoint.App:
                result.filter.return_value.first.return_value = mock_app
            elif model is webhook_endpoint.WorkflowDeployment:
                result.filter.return_value.first.return_value = mock_deployment
            else:
                result.filter.return_value.first.return_value = None
            return result

        mock_db_session.query.side_effect = query
        return mock_db_session

    def _authorize_capture_user(self, mock_db_session):
        app.dependency_overrides[get_db] = lambda: mock_db_session
        app.dependency_overrides[get_current_user] = lambda: self.current_user

        original_ensure = webhook_endpoint.ensure_workflow_permission
        webhook_endpoint.ensure_workflow_permission = lambda *args, **kwargs: None
        return original_ensure

    def test_capture_lifecycle_returns_redacted_preview_once(self):
        """캡처 시작 -> 웹훅 수신 -> 상태 조회 시나리오 테스트"""

        # 1. DB Mock 설정 (App 조회용)
        mock_db_session = self._mock_db_with_app()
        original_ensure = self._authorize_capture_user(mock_db_session)

        try:
            # === Step 1: 캡처 시작 ===
            response = self.client.get(f"/api/v1/hooks/{self.url_slug}/capture/start")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "waiting")
            capture_id = response.json()["capture_id"]

            # 메모리에 세션 생성 확인
            self.assertIn(self.url_slug, CAPTURE_SESSIONS)
            self.assertEqual(CAPTURE_SESSIONS[self.url_slug]["status"], "waiting")
            self.assertEqual(CAPTURE_SESSIONS[self.url_slug]["capture_id"], capture_id)
            self.assertEqual(
                CAPTURE_SESSIONS[self.url_slug]["requested_by"],
                str(self.current_user.id),
            )

            # === Step 2: Webhook 수신 (캡처 모드) ===
            payload = {
                "event": "test",
                "data": 123,
                "token": "secret-token-value",
                "message": "Bearer api-very-secret-token",
            }
            response = self.client.post(
                f"/api/v1/hooks/{self.url_slug}?token={self.auth_secret}", json=payload
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["status"], "captured")
            self.assertNotEqual(CAPTURE_SESSIONS[self.url_slug]["payload"], payload)

            # === Step 3: 캡처 상태 조회 ===
            response = self.client.get(
                f"/api/v1/hooks/{self.url_slug}/capture/status",
                params={"capture_id": capture_id},
            )
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertEqual(data["status"], "captured")
            self.assertTrue(data["payload_redacted"])
            self.assertEqual(data["payload"]["event"], "test")
            self.assertEqual(
                data["payload"]["token"], "[REDACTED: sensitive value]"
            )
            self.assertNotIn("secret-token-value", str(data))
            self.assertNotIn("api-very-secret-token", str(data))

            # 조회 후 메모리에서 삭제되었는지 확인
            self.assertNotIn(self.url_slug, CAPTURE_SESSIONS)

        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_preview_redacts_sensitive_fields_and_caps_shape(self):
        github_token = "ghp_" + "a" * 36
        jwt_token = f"eyJ{'a' * 20}.{'b' * 20}.{'c' * 20}"
        slack_token = "xoxb-" + "1" * 12
        aws_access_key = "AKIA" + "A" * 16
        google_api_key = "AIza" + "a" * 35
        pem_key = "-----BEGIN PRIVATE KEY-----\nsecret\n-----END PRIVATE KEY-----"
        payload = {
            "headers": {"Authorization": "Bearer very-sensitive-token-value"},
            "github": github_token,
            "jwt": jwt_token,
            "slack": slack_token,
            "aws": aws_access_key,
            "google": google_api_key,
            "pem": pem_key,
            "items": list(range(55)),
            "long_text": "x" * 2100,
            "nested": {"a": {"b": {"c": {"d": "hidden by depth cap"}}}},
        }

        preview = webhook_endpoint._redact_capture_payload(payload)

        self.assertEqual(
            preview["headers"]["Authorization"], "[REDACTED: sensitive value]"
        )
        self.assertEqual(len(preview["items"]), 51)
        self.assertEqual(preview["items"][-1], "[TRUNCATED]")
        self.assertTrue(preview["long_text"].endswith("\n[TRUNCATED]"))
        self.assertEqual(preview["nested"]["a"]["b"]["c"], "[TRUNCATED]")
        self.assertNotIn("very-sensitive-token-value", str(preview))
        self.assertNotIn(github_token, str(preview))
        self.assertNotIn(jwt_token, str(preview))
        self.assertNotIn(slack_token, str(preview))
        self.assertNotIn(aws_access_key, str(preview))
        self.assertNotIn(google_api_key, str(preview))
        self.assertNotIn("BEGIN PRIVATE KEY", str(preview))

    def test_capture_preview_preserves_public_key_fields_and_sanitizes_key_names(self):
        secret_key_name = "ghp_" + "a" * 36
        second_secret_key_name = "xoxb-" + "1" * 12
        long_key_name = "x" * 250
        payload = {
            "key": "public-root-id",
            "issue": {"key": "MBA-179"},
            "project": {"key": "NODEASE"},
            "api_key": "api-secret-value",
            "api": {"key": "nested-api-key-value"},
            "headers": {"x-api-key": "header-secret-value"},
            "secret-key": "hyphen-secret-value",
            "secretKey": "secret-key-value",
            "access_key": "access-key-value",
            secret_key_name: "first-value",
            second_secret_key_name: "second-value",
            long_key_name: "long-key-value",
        }

        preview = webhook_endpoint._redact_capture_payload(payload)

        self.assertEqual(preview["key"], "public-root-id")
        self.assertEqual(preview["issue"]["key"], "MBA-179")
        self.assertEqual(preview["project"]["key"], "NODEASE")
        self.assertEqual(preview["api_key"], "[REDACTED: sensitive value]")
        self.assertEqual(preview["api"]["key"], "[REDACTED: sensitive value]")
        self.assertEqual(preview["headers"]["x-api-key"], "[REDACTED: sensitive value]")
        self.assertEqual(preview["secret-key"], "[REDACTED: sensitive value]")
        self.assertEqual(preview["secretKey"], "[REDACTED: sensitive value]")
        self.assertEqual(preview["access_key"], "[REDACTED: sensitive value]")
        self.assertEqual(preview["[REDACTED: sensitive key]"], "first-value")
        self.assertEqual(preview["[REDACTED: sensitive key]#2"], "second-value")
        capped_key = (
            "x" * webhook_endpoint.CAPTURE_PREVIEW_MAX_KEY_CHARS + "\n[TRUNCATED]"
        )
        self.assertEqual(preview[capped_key], "long-key-value")
        self.assertNotIn(secret_key_name, str(preview))
        self.assertNotIn(second_secret_key_name, str(preview))
        self.assertNotIn(long_key_name, str(preview))

    def test_capture_preview_caps_large_array_without_full_copy(self):
        class LargeList(list):
            def __iter__(self):
                for index in range(webhook_endpoint.CAPTURE_PREVIEW_MAX_ITEMS + 2):
                    if index > webhook_endpoint.CAPTURE_PREVIEW_MAX_ITEMS:
                        raise AssertionError("preview iterated past the cap")
                    yield index

        preview = webhook_endpoint._redact_capture_payload(LargeList())

        self.assertEqual(len(preview), webhook_endpoint.CAPTURE_PREVIEW_MAX_ITEMS + 1)
        self.assertEqual(preview[-1], "[TRUNCATED]")

    def test_capture_preview_handles_non_object_payloads(self):
        self.assertEqual(webhook_endpoint._redact_capture_payload(["ok"]), ["ok"])
        self.assertEqual(
            webhook_endpoint._redact_capture_payload("xoxb-" + "1" * 12),
            "[REDACTED: sensitive value]",
        )

    def test_capture_start_requires_login(self):
        start_signature = inspect.signature(webhook_endpoint.start_capture)
        status_signature = inspect.signature(webhook_endpoint.get_capture_status)
        cancel_signature = inspect.signature(webhook_endpoint.cancel_capture)

        self.assertIs(
            start_signature.parameters["current_user"].default.dependency,
            get_current_user,
        )
        self.assertIs(
            status_signature.parameters["current_user"].default.dependency,
            get_current_user,
        )
        self.assertIs(
            cancel_signature.parameters["current_user"].default.dependency,
            get_current_user,
        )

    def test_capture_start_requires_deploy_permission(self):
        mock_db_session = self._mock_db_with_app()

        original_ensure = webhook_endpoint.ensure_workflow_permission
        webhook_endpoint.ensure_workflow_permission = MagicMock(
            side_effect=HTTPException(status_code=403, detail="Forbidden")
        )
        try:
            with self.assertRaises(HTTPException) as exc:
                webhook_endpoint.start_capture(
                    self.url_slug,
                    db=mock_db_session,
                    current_user=self.current_user,
                )

            self.assertEqual(exc.exception.status_code, 403)
            webhook_endpoint.ensure_workflow_permission.assert_called_once()
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_status_rejects_wrong_capture_id(self):
        mock_db_session = self._mock_db_with_app()
        original_ensure = self._authorize_capture_user(mock_db_session)
        CAPTURE_SESSIONS[self.url_slug] = {
            "capture_id": "correct",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            "payload": None,
            "requested_by": str(self.current_user.id),
            "status": "waiting",
        }
        try:
            with self.assertRaises(HTTPException) as exc:
                webhook_endpoint.get_capture_status(
                    self.url_slug,
                    capture_id="wrong",
                    db=mock_db_session,
                    current_user=self.current_user,
                )

            self.assertEqual(exc.exception.status_code, 404)
            self.assertIn(self.url_slug, CAPTURE_SESSIONS)
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_status_rejects_different_requester(self):
        mock_db_session = self._mock_db_with_app()
        original_ensure = self._authorize_capture_user(mock_db_session)
        CAPTURE_SESSIONS[self.url_slug] = {
            "capture_id": "capture-id",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            "payload": None,
            "requested_by": str(uuid4()),
            "status": "waiting",
        }
        try:
            with self.assertRaises(HTTPException) as exc:
                webhook_endpoint.get_capture_status(
                    self.url_slug,
                    capture_id="capture-id",
                    db=mock_db_session,
                    current_user=self.current_user,
                )

            self.assertEqual(exc.exception.status_code, 404)
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_status_removes_expired_session(self):
        mock_db_session = self._mock_db_with_app()
        original_ensure = self._authorize_capture_user(mock_db_session)
        CAPTURE_SESSIONS[self.url_slug] = {
            "capture_id": "expired",
            "created_at": datetime.now(timezone.utc) - timedelta(seconds=120),
            "expires_at": datetime.now(timezone.utc) - timedelta(seconds=1),
            "payload": None,
            "requested_by": str(self.current_user.id),
            "status": "waiting",
        }
        try:
            with self.assertRaises(HTTPException) as exc:
                webhook_endpoint.get_capture_status(
                    self.url_slug,
                    capture_id="expired",
                    db=mock_db_session,
                    current_user=self.current_user,
                )

            self.assertEqual(exc.exception.status_code, 404)
            self.assertNotIn(self.url_slug, CAPTURE_SESSIONS)
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_cancel_deletes_waiting_session(self):
        mock_db_session = self._mock_db_with_app()
        original_ensure = self._authorize_capture_user(mock_db_session)
        CAPTURE_SESSIONS[self.url_slug] = {
            "capture_id": "capture-id",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            "payload": None,
            "requested_by": str(self.current_user.id),
            "status": "waiting",
        }
        try:
            response = webhook_endpoint.cancel_capture(
                self.url_slug,
                capture_id="capture-id",
                db=mock_db_session,
                current_user=self.current_user,
            )

            self.assertEqual(response["status"], "cancelled")
            self.assertNotIn(self.url_slug, CAPTURE_SESSIONS)
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_cancel_rejects_wrong_capture_id(self):
        mock_db_session = self._mock_db_with_app()
        original_ensure = self._authorize_capture_user(mock_db_session)
        CAPTURE_SESSIONS[self.url_slug] = {
            "capture_id": "correct",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            "payload": None,
            "requested_by": str(self.current_user.id),
            "status": "waiting",
        }
        try:
            with self.assertRaises(HTTPException) as exc:
                webhook_endpoint.cancel_capture(
                    self.url_slug,
                    capture_id="wrong",
                    db=mock_db_session,
                    current_user=self.current_user,
                )

            self.assertEqual(exc.exception.status_code, 404)
            self.assertIn(self.url_slug, CAPTURE_SESSIONS)
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_cancel_rejects_different_requester(self):
        mock_db_session = self._mock_db_with_app()
        original_ensure = self._authorize_capture_user(mock_db_session)
        CAPTURE_SESSIONS[self.url_slug] = {
            "capture_id": "capture-id",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            "payload": None,
            "requested_by": str(uuid4()),
            "status": "waiting",
        }
        try:
            with self.assertRaises(HTTPException) as exc:
                webhook_endpoint.cancel_capture(
                    self.url_slug,
                    capture_id="capture-id",
                    db=mock_db_session,
                    current_user=self.current_user,
                )

            self.assertEqual(exc.exception.status_code, 404)
            self.assertIn(self.url_slug, CAPTURE_SESSIONS)
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_capture_cancel_requires_deploy_permission(self):
        mock_db_session = self._mock_db_with_app()

        original_ensure = webhook_endpoint.ensure_workflow_permission
        webhook_endpoint.ensure_workflow_permission = MagicMock(
            side_effect=HTTPException(status_code=403, detail="Forbidden")
        )
        try:
            with self.assertRaises(HTTPException) as exc:
                webhook_endpoint.cancel_capture(
                    self.url_slug,
                    capture_id="capture-id",
                    db=mock_db_session,
                    current_user=self.current_user,
                )

            self.assertEqual(exc.exception.status_code, 403)
            webhook_endpoint.ensure_workflow_permission.assert_called_once()
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure

    def test_cancelled_capture_allows_next_webhook_execution(self):
        mock_db_session = self._mock_db_with_app(active_deployment=True)
        original_ensure = self._authorize_capture_user(mock_db_session)
        original_budget_check = (
            webhook_endpoint.WorkflowBudgetService
            .ensure_workflow_budget_allows_execution
        )
        webhook_endpoint.WorkflowBudgetService.ensure_workflow_budget_allows_execution = (
            lambda *args, **kwargs: None
        )
        CAPTURE_SESSIONS[self.url_slug] = {
            "capture_id": "capture-id",
            "created_at": datetime.now(timezone.utc),
            "expires_at": datetime.now(timezone.utc) + timedelta(seconds=60),
            "payload": None,
            "requested_by": str(self.current_user.id),
            "status": "waiting",
        }
        try:
            webhook_endpoint.cancel_capture(
                self.url_slug,
                capture_id="capture-id",
                db=mock_db_session,
                current_user=self.current_user,
            )
            response = asyncio.run(
                webhook_endpoint.receive_webhook(
                    self.url_slug,
                    _FakeRequest(
                        query_params={"token": self.auth_secret},
                        payload={"event": "after_cancel"},
                    ),
                    BackgroundTasks(),
                    db=mock_db_session,
                )
            )

            self.assertEqual(response["status"], "accepted")
            self.assertNotIn(self.url_slug, CAPTURE_SESSIONS)
        finally:
            webhook_endpoint.ensure_workflow_permission = original_ensure
            webhook_endpoint.WorkflowBudgetService.ensure_workflow_budget_allows_execution = (
                original_budget_check
            )

    def test_webhook_invalid_token(self):
        """잘못된 토큰으로 웹훅 수신 시 거부 테스트"""
        mock_db_session = self._mock_db_with_app()

        with self.assertRaises(HTTPException) as exc:
            asyncio.run(
                webhook_endpoint.receive_webhook(
                    self.url_slug,
                    _FakeRequest(
                        query_params={"token": "wrong-token"},
                        payload={},
                    ),
                    BackgroundTasks(),
                    db=mock_db_session,
                )
            )

        self.assertEqual(exc.exception.status_code, 403)


if __name__ == "__main__":
    unittest.main()
