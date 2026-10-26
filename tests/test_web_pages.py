import asyncio
import re
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from starlette.middleware.sessions import SessionMiddleware

from app import models  # Register all SQLAlchemy models on Base.metadata.
from app.database import Base, get_db
from app.web import auth_router, web_router


class WebPageFlowTests(unittest.TestCase):
    """Exercise the public auth flow and protected multi-page dashboard without starting probes."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        database_path = Path(self.temp_dir.name) / "web-pages.db"
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path}",
            poolclass=NullPool,
        )
        asyncio.run(self._create_schema())
        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self.app = FastAPI()
        self.app.add_middleware(
            SessionMiddleware,
            secret_key="test-only-session-secret-that-is-not-used-in-production",
            session_cookie="ethionet_pulse_test_session",
            same_site="lax",
            https_only=False,
        )
        self.app.include_router(auth_router)
        self.app.include_router(web_router)

        async def override_get_db():
            async with self.sessions() as session:
                yield session

        self.app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(
            self.app,
            base_url="http://testserver",
            follow_redirects=False,
        )

    async def _create_schema(self):
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    def tearDown(self):
        self.client.close()
        asyncio.run(self.engine.dispose())
        self.temp_dir.cleanup()

    @staticmethod
    def csrf_token(response_text: str) -> str:
        match = re.search(r'name="csrf_token" value="([^"]+)"', response_text)
        if not match:
            raise AssertionError("The page did not include a CSRF token.")
        return match.group(1)

    def register_account(self, email="test.user@example.test"):
        page = self.client.get("/register")
        self.assertEqual(page.status_code, 200)
        token = self.csrf_token(page.text)
        response = self.client.post(
            "/auth/register",
            data={
                "csrf_token": token,
                "name": "Test User",
                "email": email,
                "password": "a-long-test-password",
                "confirm_password": "a-long-test-password",
            },
        )
        return response

    def test_root_is_a_login_page_with_contact_and_registration_links(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/auth/login"', response.text)
        self.assertIn('href="/auth/google"', response.text)
        self.assertIn('href="/register"', response.text)
        self.assertIn("auth-footer", response.text)
        self.assertIn('class="auth-contact"', response.text)
        self.assertIn("Need help?", response.text)
        self.assertTrue(
            "Contact on GitHub" in response.text or 'href="mailto:' in response.text
        )
        self.assertNotIn("Testimonials", response.text)
        self.assertNotIn("Customer reviews", response.text)

    def test_private_feature_pages_redirect_before_sign_in(self):
        paths = [
            "/dashboard",
            "/dashboard/connectivity",
            "/dashboard/services",
            "/dashboard/quality",
            "/dashboard/diagnosis",
            "/dashboard/incidents",
            "/dashboard/reports",
            "/dashboard/settings",
        ]
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 303)
                self.assertEqual(response.headers["location"], "/login")

    def test_registration_sets_session_and_all_feature_pages_render(self):
        response = self.register_account()
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/dashboard")

        pages = {
            "/dashboard": ("overview", "Monitoring workspace"),
            "/dashboard/connectivity": ("connectivity", "Latency trend"),
            "/dashboard/services": ("services", "Monitored HTTP services"),
            "/dashboard/quality": ("quality", "Latest network quality"),
            "/dashboard/diagnosis": ("diagnosis", "Connectivity diagnosis"),
            "/dashboard/incidents": ("incidents", "Connectivity outages"),
            "/dashboard/reports": ("reports", "Reliability summary"),
            "/dashboard/settings": ("settings", "Appearance"),
        }
        for path, (page_key, expected_text) in pages.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(f'data-page="{page_key}"', response.text)
                self.assertIn(expected_text, response.text)

    def test_dashboard_uses_sidebar_navigation_and_mobile_menu(self):
        registration = self.register_account()
        self.assertEqual(registration.status_code, 303)

        response = self.client.get("/dashboard")
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="app-sidebar" id="app-sidebar"', response.text)
        self.assertIn('id="sidebar-toggle"', response.text)
        self.assertIn('id="sidebar-backdrop"', response.text)
        self.assertIn('src="/static/sidebar.js"', response.text)

        for path in (
            "/dashboard",
            "/dashboard/connectivity",
            "/dashboard/services",
            "/dashboard/quality",
            "/dashboard/diagnosis",
            "/dashboard/incidents",
            "/dashboard/reports",
            "/dashboard/settings",
        ):
            with self.subTest(path=path):
                self.assertIn(f'href="{path}"', response.text)

    def test_manual_login_works_after_registration_and_logout(self):
        response = self.register_account()
        self.assertEqual(response.status_code, 303)

        settings_page = self.client.get("/dashboard/settings")
        self.assertEqual(settings_page.status_code, 200)
        logout_token = self.csrf_token(settings_page.text)
        logout_response = self.client.post(
            "/auth/logout",
            data={"csrf_token": logout_token},
        )
        self.assertEqual(logout_response.status_code, 303)
        self.assertEqual(logout_response.headers["location"], "/login")

        login_page = self.client.get("/login")
        login_token = self.csrf_token(login_page.text)
        login_response = self.client.post(
            "/auth/login",
            data={
                "csrf_token": login_token,
                "email": "test.user@example.test",
                "password": "a-long-test-password",
            },
        )
        self.assertEqual(login_response.status_code, 303)
        self.assertEqual(login_response.headers["location"], "/dashboard")
        self.assertEqual(self.client.get("/dashboard").status_code, 200)

    def test_google_signin_explains_when_oauth_is_not_configured(self):
        from app.config import settings

        with (
            patch.object(settings, "GOOGLE_CLIENT_ID", ""),
            patch.object(settings, "GOOGLE_CLIENT_SECRET", ""),
        ):
            response = self.client.get("/auth/google")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        page = self.client.get("/login")
        self.assertIn("Google sign-in is not configured yet", page.text)

    def test_registration_rejects_missing_csrf_token(self):
        response = self.client.post(
            "/auth/register",
            data={
                "name": "Test User",
                "email": "test.user@example.test",
                "password": "a-long-test-password",
                "confirm_password": "a-long-test-password",
            },
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/register")
        page = self.client.get("/register")
        self.assertIn("form expired", page.text.lower())

    def test_login_rejects_missing_csrf_token(self):
        response = self.client.post(
            "/auth/login",
            data={"email": "nobody@example.test", "password": "some-password"},
        )
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/login")
        page = self.client.get("/login")
        self.assertIn("form expired", page.text.lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
