import unittest

from app.monitoring.diagnostics import classify_diagnosis


def target(status, completed=True):
    return {"status": status, "probe_completed": completed}


class DiagnosisTests(unittest.TestCase):
    def test_all_external_targets_online(self):
        result = classify_diagnosis("online", [target("online"), target("online")])
        self.assertEqual(result["code"], "connectivity_confirmed")

    def test_partial_reachability_does_not_claim_total_outage(self):
        result = classify_diagnosis("online", [target("online"), target("offline")])
        self.assertEqual(result["code"], "partial_target_reachability")

    def test_gateway_online_external_targets_failed(self):
        result = classify_diagnosis("online", [target("offline"), target("offline")])
        self.assertEqual(result["code"], "possible_upstream_issue")

    def test_gateway_and_external_targets_failed(self):
        result = classify_diagnosis("offline", [target("offline")])
        self.assertEqual(result["code"], "possible_local_network_issue")

    def test_incomplete_probe_is_inconclusive(self):
        result = classify_diagnosis("unavailable", [target("error", False)])
        self.assertEqual(result["code"], "inconclusive")

    def test_no_targets_configured(self):
        result = classify_diagnosis("unavailable", [])
        self.assertEqual(result["code"], "no_targets_configured")


if __name__ == "__main__":
    unittest.main(verbosity=2)
