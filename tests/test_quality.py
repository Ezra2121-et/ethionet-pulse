import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models import NetworkQualityCheck, NetworkQualityIncident
from app.monitoring import quality


class PingParserTests(unittest.TestCase):
    def test_parses_packet_loss_latency_and_jitter(self):
        result = quality.parse_ping_output(
            "5 packets transmitted, 4 received, 20% packet loss, time 4000ms\n"
            "rtt min/avg/max/mdev = 10.000/15.000/20.000/3.000 ms",
            sample_count=5,
            return_code=1,
        )
        self.assertEqual(result["packets_sent"], 5)
        self.assertEqual(result["packets_received"], 4)
        self.assertEqual(result["packet_loss_percent"], 20.0)
        self.assertEqual(result["latency_avg_ms"], 15.0)
        self.assertEqual(result["latency_jitter_ms"], 3.0)

    def test_total_packet_loss_is_valid_without_latency_values(self):
        result = quality.parse_ping_output(
            "5 packets transmitted, 0 received, 100% packet loss",
            sample_count=5,
            return_code=1,
        )
        self.assertEqual(result["packets_received"], 0)
        self.assertEqual(result["packet_loss_percent"], 100.0)
        self.assertIsNone(result["latency_avg_ms"])


class NetworkQualityMonitoringTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "quality.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        self.original_targets = settings.INTERNET_TARGETS
        self.original_degraded_threshold = settings.DEGRADATION_CONSECUTIVE_ROUNDS
        self.original_recovery_threshold = settings.QUALITY_RECOVERY_CONSECUTIVE_ROUNDS
        settings.INTERNET_TARGETS = "192.0.2.10"
        settings.DEGRADATION_CONSECUTIVE_ROUNDS = 2
        settings.QUALITY_RECOVERY_CONSECUTIVE_ROUNDS = 2
        quality._degraded_rounds.clear()
        quality._healthy_rounds.clear()

    async def asyncTearDown(self):
        settings.INTERNET_TARGETS = self.original_targets
        settings.DEGRADATION_CONSECUTIVE_ROUNDS = self.original_degraded_threshold
        settings.QUALITY_RECOVERY_CONSECUTIVE_ROUNDS = self.original_recovery_threshold
        quality._degraded_rounds.clear()
        quality._healthy_rounds.clear()
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_sustained_degradation_and_recovery_alert_once(self):
        def sample(degraded, loss, average):
            return {
                "target": "192.0.2.10",
                "probe_completed": True,
                "packets_sent": 5,
                "packets_received": int(5 * (100 - loss) / 100),
                "packet_loss_percent": loss,
                "latency_min_ms": average,
                "latency_avg_ms": average,
                "latency_max_ms": average,
                "latency_jitter_ms": 2.0 if average is not None else None,
                "is_degraded": degraded,
                "status": "degraded" if degraded else "healthy",
                "error_message": None,
            }

        probe = AsyncMock(side_effect=[
            sample(True, 40.0, None),
            sample(True, 60.0, None),
            sample(True, 60.0, None),
            sample(False, 0.0, 35.0),
            sample(False, 0.0, 30.0),
        ])
        alert = AsyncMock()

        with (
            patch.object(quality, "AsyncSessionLocal", self.sessions),
            patch.object(quality, "probe_target_quality", probe),
            patch.object(quality, "send_outage_alert", alert),
        ):
            first = await quality.run_network_quality_checks()
            second = await quality.run_network_quality_checks()
            third = await quality.run_network_quality_checks()
            fourth = await quality.run_network_quality_checks()
            fifth = await quality.run_network_quality_checks()

        self.assertEqual(first["events"], [])
        self.assertEqual(second["events"][0]["event"], "network_quality_degraded")
        self.assertEqual(third["events"], [])
        self.assertEqual(fourth["events"], [])
        self.assertEqual(fifth["events"][0]["event"], "network_quality_recovered")
        self.assertEqual(alert.await_count, 2)

        async with self.sessions() as session:
            checks = (await session.scalars(select(NetworkQualityCheck))).all()
            incidents = (await session.scalars(select(NetworkQualityIncident))).all()

        self.assertEqual(len(checks), 5)
        self.assertEqual(len(incidents), 1)
        self.assertTrue(incidents[0].is_resolved)
        self.assertEqual(incidents[0].peak_packet_loss_percent, 60.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
