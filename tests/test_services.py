import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models import ServiceCheck, ServiceOutage
from app.monitoring import services
from app.monitoring.urls import safe_service_url


class FakeResponse:
    def __init__(self, status_code):
        self.status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class FakeHTTPClient:
    def __init__(self, statuses):
        self.statuses = statuses

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def stream(self, _method, _url):
        return FakeResponse(next(self.statuses))


class ServiceURLTests(unittest.TestCase):
    def test_safe_url_removes_credentials_query_and_fragment(self):
        result = safe_service_url(
            "https://user:password@example.test/health?token=secret#private"
        )
        self.assertEqual(result, "https://example.test/health")
        self.assertNotIn("password", result)
        self.assertNotIn("secret", result)

    def test_rejects_non_http_and_invalid_urls(self):
        self.assertIsNone(safe_service_url("ftp://example.test/file"))
        self.assertIsNone(safe_service_url("not a URL"))


class ServiceMonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "services.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        self.original_urls = settings.SERVICE_URLS
        self.original_failure_threshold = settings.SERVICE_FAILURE_THRESHOLD
        self.original_recovery_threshold = settings.SERVICE_RECOVERY_THRESHOLD
        settings.SERVICE_URLS = "https://example.test/health"
        settings.SERVICE_FAILURE_THRESHOLD = 2
        settings.SERVICE_RECOVERY_THRESHOLD = 2
        services._failed_rounds.clear()
        services._successful_rounds.clear()

    async def asyncTearDown(self):
        settings.SERVICE_URLS = self.original_urls
        settings.SERVICE_FAILURE_THRESHOLD = self.original_failure_threshold
        settings.SERVICE_RECOVERY_THRESHOLD = self.original_recovery_threshold
        services._failed_rounds.clear()
        services._successful_rounds.clear()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_thresholds_record_service_outage_and_recovery_once(self):
        statuses = iter([503, 503, 503, 200, 200])
        client = FakeHTTPClient(statuses)
        alert = AsyncMock()

        with (
            patch.object(services, "AsyncSessionLocal", self.sessions),
            patch.object(services.httpx, "AsyncClient", return_value=client),
            patch.object(services, "send_outage_alert", alert),
        ):
            first = await services.run_service_checks()
            second = await services.run_service_checks()
            third = await services.run_service_checks()
            fourth = await services.run_service_checks()
            fifth = await services.run_service_checks()

        self.assertEqual(first["offline"], 1)
        self.assertEqual(first["events"], [])
        self.assertEqual(second["events"][0]["event"], "service_outage_started")
        self.assertEqual(third["events"], [])
        self.assertEqual(fourth["events"], [])
        self.assertEqual(fifth["events"][0]["event"], "service_outage_recovered")
        self.assertEqual(alert.await_count, 2)

        async with self.sessions() as session:
            checks = (await session.scalars(select(ServiceCheck))).all()
            outages = (await session.scalars(select(ServiceOutage))).all()

        self.assertEqual(len(checks), 5)
        self.assertEqual(len(outages), 1)
        self.assertTrue(outages[0].is_resolved)
        self.assertEqual(outages[0].service_url, "https://example.test/health")
        self.assertNotIn("token", checks[0].service_url)

    async def test_invalid_url_is_skipped_without_creating_an_incident(self):
        settings.SERVICE_URLS = "file:///etc/passwd"
        with patch.object(services, "AsyncSessionLocal", self.sessions):
            result = await services.run_service_checks()

        self.assertEqual(result["configured"], 0)
        self.assertEqual(result["invalid_configurations"], 1)
        async with self.sessions() as session:
            outages = (await session.scalars(select(ServiceOutage))).all()
        self.assertEqual(outages, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
