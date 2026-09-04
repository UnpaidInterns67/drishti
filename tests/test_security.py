import unittest
from dataclasses import replace
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.auth import auth_service
from backend.config import settings
from backend.main import app
from backend.security import SlidingWindowRateLimiter
from test_api import mock_png


class SecurityControlTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        auth_service.create_officer_for_test(
            "security-admin",
            "security-admin-password-123",
            role="ADMIN",
        )
        auth_service.create_officer_for_test(
            "security-officer",
            "security-officer-password-123",
            role="OFFICER",
        )

    def login(self, client, username, password):
        response = client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        self.assertEqual(response.status_code, 200, response.text)
        client.headers.update({"X-CSRF-Token": response.json()["csrf_token"]})
        return response

    def test_rate_limiter_enforces_sliding_window(self):
        limiter = SlidingWindowRateLimiter(limit=2, window_seconds=10)
        self.assertTrue(limiter.check("officer", now=1).allowed)
        self.assertTrue(limiter.check("officer", now=2).allowed)
        blocked = limiter.check("officer", now=3)
        self.assertFalse(blocked.allowed)
        self.assertGreaterEqual(blocked.retry_after, 1)
        self.assertTrue(limiter.check("officer", now=12).allowed)

    def test_production_configuration_fails_closed(self):
        unsafe = replace(
            settings,
            environment="production",
            auth_cookie_secure=False,
            require_https=False,
            data_volume_encrypted=False,
            allowed_hosts=("*",),
            cors_origins=("http://example.test",),
        )
        with self.assertRaisesRegex(RuntimeError, "Unsafe production configuration"):
            unsafe.validate_startup()

        secure = replace(
            settings,
            environment="production",
            auth_cookie_secure=True,
            require_https=True,
            data_volume_encrypted=True,
            allowed_hosts=("drishti.example.gov.in",),
            cors_origins=("https://drishti.example.gov.in",),
            bootstrap_officer_password=None,
        )
        secure.validate_startup()

    def test_security_headers_and_no_store_are_applied_to_errors(self):
        with TestClient(app, base_url="https://testserver") as client:
            response = client.get("/api/v1/auth/me")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["x-frame-options"], "DENY")
        self.assertIn("default-src 'self'", response.headers["content-security-policy"])
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertGreaterEqual(len(response.headers["x-request-id"]), 16)

    def test_officer_cannot_access_admin_watchlist_but_can_change_post(self):
        with TestClient(app, base_url="https://testserver") as client:
            self.login(
                client,
                "security-officer",
                "security-officer-password-123",
            )
            denied = client.get("/api/v1/watchlist")
            history_denied = client.get("/api/v1/screenings")
            switched = client.post(
                "/api/v1/auth/active-checkpoint",
                json={"checkpoint_code": "ICP-MOREH-03"},
            )
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(history_denied.status_code, 403)
        self.assertEqual(
            denied.json()["detail"]["code"],
            "INSUFFICIENT_OFFICER_PERMISSIONS",
        )
        self.assertEqual(switched.status_code, 200, switched.text)

    def test_upload_content_type_must_match_verified_image(self):
        with TestClient(app, base_url="https://testserver") as client:
            self.login(client, "security-admin", "security-admin-password-123")
            response = client.post(
                "/api/v1/screenings",
                files={"document": ("passport.jpg", mock_png(), "image/jpeg")},
            )
        self.assertEqual(response.status_code, 415)
        self.assertEqual(
            response.json()["detail"]["code"],
            "IMAGE_CONTENT_TYPE_MISMATCH",
        )

    def test_internal_exception_detail_is_not_returned(self):
        with (
            patch(
                "backend.main.ocr_service.extract",
                side_effect=RuntimeError("sensitive-internal-detail"),
            ),
            TestClient(app, base_url="https://testserver") as client,
        ):
            self.login(client, "security-admin", "security-admin-password-123")
            response = client.post(
                "/api/v1/screenings",
                files={"document": ("passport.png", mock_png(), "image/png")},
            )
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("sensitive-internal-detail", response.text)

    def test_unexpected_login_fields_and_injection_username_are_rejected(self):
        with TestClient(app, base_url="https://testserver") as client:
            response = client.post(
                "/api/v1/auth/login",
                json={
                    "username": "admin' OR 1=1--",
                    "password": "irrelevant",
                    "is_admin": True,
                },
            )
        self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
