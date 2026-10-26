import unittest
from unittest.mock import patch

from app.config import settings
from app.monitoring.alerts import format_outage_message


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
