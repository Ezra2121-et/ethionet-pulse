import csv
import io
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models import (
    ConnectivityCheck,
    Outage,
    ServiceCheck,
    ServiceOutage,
    NetworkQualityCheck,
    NetworkQualityIncident,
)
from app.api.reports import export_csv, reliability_report


class ReliabilityReportTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "reports.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        self.original_targets = settings.INTERNET_TARGETS
        self.original_services = settings.SERVICE_URLS
        settings.INTERNET_TARGETS = "1.1.1.1"
        settings.SERVICE_URLS = "https://example.test/health?token=secret"
        now = datetime.now(timezone.utc)

        async with self.sessions() as session:
            session.add_all([
                ConnectivityCheck(
                    timestamp=now - timedelta(minutes=1),
                    target="1.1.1.1",
                    is_up=True,
                    latency_ms=25.0,
                ),
                Outage(
                    start_time=now - timedelta(minutes=10),
                    end_time=now - timedelta(minutes=9),
                    duration_seconds=60,
                    outage_type="internet",
                    is_resolved=True,
                ),
                ServiceCheck(
                    timestamp=now - timedelta(minutes=2),
                    service_url="https://example.test/health",
                    is_up=True,
                    probe_completed=True,
                    http_status_code=200,
                    response_time_ms=120.0,
                ),
                ServiceOutage(
                    service_url="https://example.test/health",
                    start_time=now - timedelta(minutes=20),
                    end_time=now - timedelta(minutes=19),
                    duration_seconds=60,
                    is_resolved=True,
                ),
                NetworkQualityCheck(
                    timestamp=now - timedelta(minutes=3),
                    target="1.1.1.1",
                    probe_completed=True,
                    packets_sent=5,
                    packets_received=4,
                    packet_loss_percent=20.0,
                    latency_min_ms=20.0,
                    latency_avg_ms=30.0,
                    latency_max_ms=40.0,
                    latency_jitter_ms=4.0,
                    is_degraded=True,
                ),
                NetworkQualityIncident(
                    target="1.1.1.1",
                    start_time=now - timedelta(minutes=30),
                    end_time=now - timedelta(minutes=25),
                    duration_seconds=300,
                    is_resolved=True,
                    peak_packet_loss_percent=40.0,
                    peak_latency_ms=450.0,
                ),
            ])
            await session.commit()

    async def asyncTearDown(self):
        settings.INTERNET_TARGETS = self.original_targets
        settings.SERVICE_URLS = self.original_services
        await self.engine.dispose()
        self.temp_dir.cleanup()

    async def test_csv_contains_network_service_quality_and_incident_records(self):
        async with self.sessions() as session:
            response = await export_csv(hours=24, db=session)

        csv_rows = list(csv.reader(io.StringIO(response.body.decode("utf-8"))))
        self.assertTrue(all(len(row) == len(csv_rows[0]) for row in csv_rows))
        rows = list(csv.DictReader(io.StringIO(response.body.decode("utf-8"))))
        record_types = {row["record_type"] for row in rows}
        self.assertTrue({
            "connectivity_check",
            "internet_outage",
            "service_check",
            "service_incident",
            "quality_check",
            "quality_incident",
        }.issubset(record_types))
        self.assertIn("packet_loss_percent", rows[0])
        self.assertIn("http_status_code", rows[0])

    async def test_json_report_uses_sample_success_rate_and_quality_metrics(self):
        async with self.sessions() as session:
            report = await reliability_report(hours=24, db=session)

        self.assertEqual(report["window_hours"], 24)
        service = report["services"]["items"][0]
        self.assertEqual(service["service_url"], "https://example.test/health")
        self.assertEqual(service["success_rate_percentage"], 100.0)
        self.assertEqual(service["average_response_time_ms"], 120.0)

        quality_summary = report["network_quality"]["items"][0]
        self.assertEqual(quality_summary["sample_count"], 1)
        self.assertEqual(quality_summary["degraded_samples"], 1)
        self.assertIn("measurement_coverage_percentage", report["network"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
