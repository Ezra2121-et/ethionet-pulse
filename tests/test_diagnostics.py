import unittest

from app.monitoring.diagnostics import classify_diagnosis, _safe_service_url


def target(status, completed=True):
    return {"status": status, "probe_completed": completed}


def dns(status):
    return {"status": status}


def service(status):
    return {"status": status}


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

    def test_public_ips_respond_but_all_dns_lookups_fail(self):
        result = classify_diagnosis(
            "online",
            [target("online"), target("online")],
            dns_checks=[dns("failed"), dns("failed")],
        )
        self.assertEqual(result["code"], "possible_dns_issue")

    def test_partial_dns_failure_is_reported(self):
        result = classify_diagnosis(
            "online",
            [target("online")],
            dns_checks=[dns("resolved"), dns("failed")],
        )
        self.assertEqual(result["code"], "partial_dns_resolution")

    def test_resolved_dns_and_failed_ping_is_not_called_an_outage(self):
        result = classify_diagnosis(
            "online",
            [target("offline"), target("offline")],
            dns_checks=[dns("resolved")],
        )
        self.assertEqual(result["code"], "ping_unresponsive_dns_works")

    def test_http_service_success_confirms_specific_endpoint_even_if_ping_fails(self):
        result = classify_diagnosis(
            "online",
            [target("offline"), target("offline")],
            service_checks=[service("online")],
        )
        self.assertEqual(result["code"], "service_connectivity_confirmed")

    def test_mixed_http_service_results_are_reported(self):
        result = classify_diagnosis(
            "online",
            [target("online")],
            service_checks=[service("online"), service("unhealthy")],
        )
        self.assertEqual(result["code"], "partial_service_availability")

    def test_service_url_display_hides_credentials_query_and_fragment(self):
        safe = _safe_service_url(
            "https://user:password@example.com/health?token=secret#private"
        )
        self.assertEqual(safe, "https://example.com/health")
        self.assertNotIn("password", safe)
        self.assertNotIn("secret", safe)


if __name__ == "__main__":
    unittest.main(verbosity=2)
