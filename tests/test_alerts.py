import unittest
from unittest.mock import patch

from app.config import settings
from app.monitoring.alerts import format_outage_message, send_outage_alert


class AlertMessageTests(unittest.TestCase):
    def test_outage_start_message_contains_important_details(self):
        with patch.object(settings, "APP_NAME", "EthioNet Pulse"):
            message = format_outage_message({
                "event": "outage_started",
                "outage_id": 12,
                "start_time": "2026-10-26T10:00:00+00:00",
            })
        self.assertIn("EthioNet Pulse", message)
        self.assertIn("connectivity outage detected", message)
        self.assertIn("2026-10-26T10:00:00+00:00", message)

    def test_recovery_message_includes_duration(self):
        message = format_outage_message({
            "event": "outage_recovered",
            "end_time": "2026-10-26T10:20:00+00:00",
            "duration_seconds": 125,
        })
        self.assertIn("connectivity recovered", message)
        self.assertIn("2m 5s", message)

    def test_service_outage_message_names_the_service(self):
        message = format_outage_message({
            "event": "service_outage_started",
            "service_url": "https://example.test/health",
            "start_time": "2026-10-26T10:00:00+00:00",
        })
        self.assertIn("monitored service is down", message)
        self.assertIn("https://example.test/health", message)

    def test_service_recovery_message_includes_duration(self):
        message = format_outage_message({
            "event": "service_outage_recovered",
            "service_url": "https://example.test/health",
            "end_time": "2026-10-26T10:20:00+00:00",
            "duration_seconds": 125,
        })
        self.assertIn("monitored service recovered", message)
        self.assertIn("2m 5s", message)

    def test_quality_degradation_message_includes_measurements(self):
        message = format_outage_message({
            "event": "network_quality_degraded",
            "target": "1.1.1.1",
            "packet_loss_percent": 40.0,
            "latency_avg_ms": 450.0,
        })
        self.assertIn("network quality degraded", message)
        self.assertIn("40.0%", message)
        self.assertIn("450.0 ms", message)

    def test_quality_recovery_message_includes_duration(self):
        message = format_outage_message({
            "event": "network_quality_recovered",
            "target": "1.1.1.1",
            "end_time": "2026-10-26T10:20:00+00:00",
            "duration_seconds": 125,
            "peak_packet_loss_percent": 40.0,
            "peak_latency_ms": 450.0,
        })
        self.assertIn("network quality recovered", message)
        self.assertIn("2m 5s", message)


class AlertDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_disabled_alerts_do_not_contact_telegram(self):
        from app.monitoring import alerts

        with (
            patch.object(settings, "ENABLE_TELEGRAM_ALERTS", False),
            patch.object(alerts.httpx, "AsyncClient") as client,
        ):
            result = await send_outage_alert({"event": "outage_started"})

        self.assertFalse(result)
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
