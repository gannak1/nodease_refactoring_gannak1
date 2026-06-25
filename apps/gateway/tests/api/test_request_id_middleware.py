import unittest

from fastapi.testclient import TestClient

from apps.gateway.main import app
from apps.gateway.utils.audit import _request_metadata
from apps.shared.audit.context import clear_current_metadata, set_current_metadata


class TestRequestIdMiddleware(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_request_id_header_is_preserved(self):
        response = self.client.get("/", headers={"X-Request-ID": "req-test"})

        self.assertEqual(response.headers["X-Request-ID"], "req-test")

    def test_request_id_header_is_generated(self):
        response = self.client.get("/")

        self.assertTrue(response.headers.get("X-Request-ID"))


class TestAuditContext(unittest.TestCase):
    def test_audit_metadata_reads_request_context_without_request_arg(self):
        token = set_current_metadata(
            {"ip": "127.0.0.1", "user_agent": "test-agent", "request_id": "req-test"}
        )
        try:
            self.assertEqual(
                _request_metadata(None),
                {
                    "ip": "127.0.0.1",
                    "user_agent": "test-agent",
                    "request_id": "req-test",
                },
            )
        finally:
            clear_current_metadata(token)


if __name__ == "__main__":
    unittest.main()
