import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.api.statistics import classify_round, calculate_time_buckets


class StatisticsTests(unittest.TestCase):
    def check(self, target, is_up, error_message=None):
        return SimpleNamespace(
            target=target,
            is_up=is_up,
            error_message=error_message,
        )

    def test_any_successful_target_means_online(self):
        checks = [
            self.check("a", False, "No reply"),
            self.check("b", True),
        ]
        self.assertEqual(classify_round(checks, ["a", "b"]), "online")

    def test_all_completed_failed_targets_mean_offline(self):
        checks = [
            self.check("a", False, "No reply"),
            self.check("b", False, "Request timed out"),
        ]
        self.assertEqual(classify_round(checks, ["a", "b"]), "offline")

    def test_probe_error_is_unknown_not_offline(self):
        checks = [
            self.check("a", False, "PROBE_ERROR: ping missing"),
            self.check("b", False, "No reply"),
        ]
        self.assertEqual(classify_round(checks, ["a", "b"]), "unknown")

    def test_missing_target_is_unknown(self):
        checks = [self.check("a", False, "No reply")]
        self.assertEqual(classify_round(checks, ["a", "b"]), "unknown")

    def test_long_gaps_are_not_counted_as_uptime(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(seconds=150)

        rounds = [
            (start, "online"),
            (start + timedelta(seconds=120), "offline"),
        ]

        buckets = calculate_time_buckets(
            rounds, start, end, max_gap_seconds=60
        )

        self.assertEqual(buckets["online"], 60)
        self.assertEqual(buckets["offline"], 30)
        measured = sum(buckets.values())
        self.assertEqual(measured, 90)
        self.assertEqual((end - start).total_seconds() - measured, 60)

    def test_empty_history_has_no_observed_time(self):
        start = datetime(2026, 1, 1, tzinfo=timezone.utc)
        end = start + timedelta(hours=24)

        buckets = calculate_time_buckets(
            [], start, end, max_gap_seconds=60
        )

        self.assertEqual(
            buckets,
            {"online": 0.0, "offline": 0.0, "unknown": 0.0},
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
