import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import settings
from app.database import Base
from app.models import ConnectivityCheck, Outage
from app.monitoring import checker


class MonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "test.db"

        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{db_path}"
        )

        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

        self.sessions = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

        self.original_targets = settings.INTERNET_TARGETS
        settings.INTERNET_TARGETS = "192.0.2.10,192.0.2.11"

    async def asyncTearDown(self):
        settings.INTERNET_TARGETS = self.original_targets
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_successful_checks_are_saved(self):
        ping = AsyncMock(
            side_effect=[
                (True, 12.5, None, True),
                (True, 18.0, None, True),
            ]
        )

        with (
            patch.object(checker, "AsyncSessionLocal", self.sessions),
            patch.object(checker, "_ping_target", ping),
        ):
            result = await checker.run_connectivity_checks()

        self.assertTrue(result["internet_online"])
        self.assertEqual(result["targets_checked"], 2)
        self.assertEqual(result["online_targets"], 2)

        async with self.sessions() as session:
            checks = (
                await session.scalars(select(ConnectivityCheck))
            ).all()
            outages = (
                await session.scalars(select(Outage))
            ).all()

        self.assertEqual(len(checks), 2)
        self.assertEqual(len(outages), 0)
        self.assertEqual(
            {check.target for check in checks},
            {"192.0.2.10", "192.0.2.11"},
        )

    async def test_outage_is_opened_and_resolved(self):
        ping = AsyncMock(
            side_effect=[
                (False, None, "No reply", True),
                (False, None, "No reply", True),
                (True, 14.0, None, True),
                (False, None, "No reply", True),
            ]
        )

        with (
            patch.object(checker, "AsyncSessionLocal", self.sessions),
            patch.object(checker, "_ping_target", ping),
        ):
            first_result = await checker.run_connectivity_checks()

            async with self.sessions() as session:
                outage = (
                    await session.scalars(select(Outage))
                ).first()
                self.assertIsNotNone(outage)
                self.assertFalse(outage.is_resolved)

            second_result = await checker.run_connectivity_checks()

        self.assertFalse(first_result["internet_online"])
        self.assertTrue(second_result["internet_online"])

        async with self.sessions() as session:
            outages = (
                await session.scalars(select(Outage))
            ).all()

        self.assertEqual(len(outages), 1)
        self.assertTrue(outages[0].is_resolved)
        self.assertIsNotNone(outages[0].end_time)
        self.assertIsNotNone(outages[0].duration_seconds)
        self.assertGreaterEqual(outages[0].duration_seconds, 0)

    async def test_probe_errors_do_not_create_false_outages(self):
        ping = AsyncMock(
            side_effect=[
                (False, None, "PROBE_ERROR: ping missing", False),
                (False, None, "PROBE_ERROR: ping missing", False),
            ]
        )

        with (
            patch.object(checker, "AsyncSessionLocal", self.sessions),
            patch.object(checker, "_ping_target", ping),
        ):
            result = await checker.run_connectivity_checks()

        self.assertIsNone(result["internet_online"])

        async with self.sessions() as session:
            outages = (
                await session.scalars(select(Outage))
            ).all()

            checks = (
                await session.scalars(select(ConnectivityCheck))
            ).all()

        self.assertEqual(len(outages), 0)
        self.assertEqual(len(checks), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
