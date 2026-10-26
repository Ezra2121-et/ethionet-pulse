"""On-demand checks to help localize connectivity problems.

Results are clues, not proof of root cause: a router or destination may
block ICMP echo requests while forwarding other traffic normally.
"""

import asyncio
import shutil
from datetime import datetime, timezone
from typing import Any

from app.config import settings
from app.monitoring.checker import _ping_target


async def discover_default_gateway() -> tuple[str | None, str | None]:
    """Return the IPv4 default gateway from Linux's routing table."""
    ip_command = shutil.which("ip")
    if not ip_command:
        return None, "The 'ip' command is unavailable; gateway discovery needs Linux iproute2."

    try:
        process = await asyncio.create_subprocess_exec(
            ip_command,
            "route",
            "show",
            "default",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=3
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return None, "Default-gateway lookup timed out."

        if process.returncode != 0:
            detail = stderr.decode("utf-8", errors="replace").strip()
            return None, (detail or "Could not read the default route.")[:200]

        for line in stdout.decode("utf-8", errors="replace").splitlines():
            parts = line.split()
            if parts and parts[0] == "default" and "via" in parts:
                index = parts.index("via")
                if index + 1 < len(parts):
                    return parts[index + 1], None

        return None, "No IPv4 default gateway with a 'via' address was found."
    except OSError as exc:
        return None, f"Could not inspect the default route: {exc}"[:200]


def _as_probe(target: str, result: tuple[bool, float | None, str | None, bool]) -> dict[str, Any]:
    reachable, latency_ms, error_message, completed = result
    status = "online" if reachable and completed else "offline" if completed else "error"
    return {
        "target": target,
        "status": status,
        "is_up": reachable if completed else None,
        "latency_ms": latency_ms,
        "error_message": error_message,
        "probe_completed": completed,
    }


def classify_diagnosis(
    gateway_status: str,
    external_targets: list[dict[str, Any]],
) -> dict[str, str]:
    """Convert probe results into cautious, actionable troubleshooting guidance."""
    if not external_targets:
        return {
            "code": "no_targets_configured",
            "title": "No external targets configured",
            "summary": "The monitor has no public destinations to check.",
            "next_step": "Configure at least one destination in INTERNET_TARGETS and try again.",
        }

    reachable = [target for target in external_targets if target["status"] == "online"]
    all_external_completed = all(target["probe_completed"] for target in external_targets)
    all_external_failed = all(target["status"] == "offline" for target in external_targets)

    if reachable:
        if len(reachable) == len(external_targets):
            return {
                "code": "connectivity_confirmed",
                "title": "Connectivity confirmed",
                "summary": f"All {len(reachable)} configured public target(s) responded. This confirms reachability to those targets, not every website or service.",
                "next_step": "If users still report problems, test the specific service and compare its response time.",
            }
        return {
            "code": "partial_target_reachability",
            "title": "Some public targets respond; others do not",
            "summary": f"{len(reachable)} of {len(external_targets)} configured public targets responded. The failed checks may be destination-specific, transient, or affected by filtering.",
            "next_step": "Retry the failed checks and compare with a service users cannot reach before concluding the ISP is at fault.",
        }

    if not all_external_completed:
        return {
            "code": "inconclusive",
            "title": "Diagnosis inconclusive",
            "summary": "One or more checks could not complete, so the results are not enough to determine whether connectivity is down.",
            "next_step": "Check that the monitor has permission to run ping and that the required network tools are installed, then retry.",
        }

    if all_external_failed and gateway_status == "online":
        return {
            "code": "possible_upstream_issue",
            "title": "Local gateway responds; public targets do not",
            "summary": "The local gateway answered, but none of the configured public targets did. This may indicate an upstream connection issue, target filtering, or ICMP restrictions.",
            "next_step": "Try opening a known website, check the router/ISP connection status, and repeat the test before deciding the cause.",
        }

    if all_external_failed and gateway_status == "offline":
        return {
            "code": "possible_local_network_issue",
            "title": "Neither the gateway nor public targets responded",
            "summary": "The checks could not reach the local gateway or configured public targets. A local Wi-Fi, cable, router, or routing problem is possible, but ICMP filtering can also cause this result.",
            "next_step": "Check the device's Wi-Fi or Ethernet link, confirm the gateway address, and retry before concluding the router is down.",
        }

    return {
        "code": "gateway_unavailable",
        "title": "Public targets did not respond; gateway check unavailable",
        "summary": "No configured public targets responded, and the local gateway could not be checked. The cause remains uncertain.",
        "next_step": "Check the local router and network link, then repeat the diagnosis. This system cannot identify the root cause from these checks alone.",
    }


async def run_connectivity_diagnosis() -> dict[str, Any]:
    """Probe the local gateway and internet targets once, without changing history."""
    gateway, gateway_note = await discover_default_gateway()

    gateway_result: dict[str, Any]
    if gateway:
        gateway_result = _as_probe(gateway, await _ping_target(gateway))
    else:
        gateway_result = {
            "target": None,
            "status": "unavailable",
            "is_up": None,
            "latency_ms": None,
            "error_message": gateway_note,
            "probe_completed": False,
        }

    targets = settings.targets_list
    results = await asyncio.gather(*(_ping_target(target) for target in targets))
    external = [_as_probe(target, result) for target, result in zip(targets, results)]

    diagnosis = classify_diagnosis(gateway_result["status"], external)
    return {
        "diagnosed_at": datetime.now(timezone.utc).isoformat(),
        "gateway": gateway_result,
        "external_targets": external,
        "diagnosis": diagnosis,
        "note": "These are reachability clues, not proof of root cause. Some routers and networks block ICMP ping.",
    }
