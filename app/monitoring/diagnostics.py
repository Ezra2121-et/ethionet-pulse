"""Gateway, public-target, DNS, and optional HTTP-service diagnostics.

Results are troubleshooting clues, not proof of root cause. ICMP may be
blocked by a router, destination, or provider even when other traffic works.
"""

import asyncio
import socket
import shutil
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.config import settings
from app.monitoring.checker import _ping_target


async def discover_default_gateway() -> tuple[str | None, str | None]:
    """Return the IPv4 default gateway from the Linux routing table."""
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


def _as_probe(
    target: str,
    result: tuple[bool, float | None, str | None, bool],
) -> dict[str, Any]:
    reachable, latency_ms, error_message, completed = result
    status = (
        "online" if reachable and completed
        else "offline" if completed
        else "error"
    )
    return {
        "target": target,
        "status": status,
        "is_up": reachable if completed else None,
        "latency_ms": latency_ms,
        "error_message": error_message,
        "probe_completed": completed,
    }


def _resolve_host(host: str) -> list[str]:
    """Resolve a DNS name with the operating system's configured resolver."""
    answers = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    return sorted({answer[4][0] for answer in answers})


async def check_dns_host(host: str, timeout_seconds: float = 3.0) -> dict[str, Any]:
    """Check whether a configured hostname resolves using the system resolver."""
    started = time.perf_counter()
    try:
        addresses = await asyncio.wait_for(
            asyncio.to_thread(_resolve_host, host),
            timeout=timeout_seconds,
        )
        return {
            "host": host,
            "status": "resolved" if addresses else "failed",
            "resolved": bool(addresses),
            "address_count": len(addresses),
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_message": None if addresses else "No addresses were returned.",
            "probe_completed": True,
        }
    except socket.gaierror as exc:
        return {
            "host": host,
            "status": "failed",
            "resolved": False,
            "address_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_message": str(exc)[:200],
            "probe_completed": True,
        }
    except (asyncio.TimeoutError, OSError) as exc:
        return {
            "host": host,
            "status": "error",
            "resolved": None,
            "address_count": 0,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_message": (str(exc) or type(exc).__name__)[:200],
            "probe_completed": False,
        }


async def check_http_service(url: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Check an optional configured HTTP(S) endpoint without changing history."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return {
            "url": url,
            "host": parsed.hostname,
            "status": "error",
            "http_status_code": None,
            "latency_ms": None,
            "error_message": "SERVICE_URLS entries must be complete http:// or https:// URLs.",
            "probe_completed": False,
        }

    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(
            timeout=timeout_seconds,
            follow_redirects=True,
            headers={"User-Agent": "EthioNet-Pulse/1.0"},
        ) as client:
            response = await client.get(url)

        elapsed = round((time.perf_counter() - started) * 1000, 2)
        healthy = 200 <= response.status_code < 400
        return {
            "url": url,
            "host": parsed.hostname,
            "status": "online" if healthy else "unhealthy",
            "http_status_code": response.status_code,
            "latency_ms": elapsed,
            "error_message": None if healthy else f"HTTP {response.status_code}",
            "probe_completed": True,
        }
    except httpx.TimeoutException:
        return {
            "url": url,
            "host": parsed.hostname,
            "status": "offline",
            "http_status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_message": "HTTP service check timed out.",
            "probe_completed": True,
        }
    except httpx.HTTPError as exc:
        return {
            "url": url,
            "host": parsed.hostname,
            "status": "offline",
            "http_status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_message": (str(exc) or type(exc).__name__)[:200],
            "probe_completed": True,
        }


def classify_diagnosis(
    gateway_status: str,
    external_targets: list[dict[str, Any]],
    dns_checks: list[dict[str, Any]] | None = None,
    service_checks: list[dict[str, Any]] | None = None,
) -> dict[str, str]:
    """Turn checks into practical, cautious troubleshooting guidance."""
    dns_checks = dns_checks or []
    service_checks = service_checks or []

    reachable = [item for item in external_targets if item["status"] == "online"]
    all_external_completed = all(item["probe_completed"] for item in external_targets)
    all_external_failed = bool(external_targets) and all(
        item["status"] == "offline" for item in external_targets
    )
    dns_failed = [item for item in dns_checks if item["status"] == "failed"]
    dns_resolved = [item for item in dns_checks if item["status"] == "resolved"]
    healthy_services = [item for item in service_checks if item["status"] == "online"]
    failed_services = [item for item in service_checks if item["status"] != "online"]

    if service_checks and healthy_services and failed_services:
        return {
            "code": "partial_service_availability",
            "title": "Some services respond; others do not",
            "summary": f"{len(healthy_services)} of {len(service_checks)} configured HTTP service(s) responded successfully. The failing service may have its own problem, or a path/DNS issue may affect it.",
            "next_step": "Retry the failing service and check its URL, DNS result, and provider status before blaming the whole internet connection.",
        }

    if service_checks and not healthy_services and failed_services and reachable:
        return {
            "code": "service_access_issue",
            "title": "Public targets respond, but configured services do not",
            "summary": "Some public IP destinations respond to ping, while none of the configured HTTP service checks succeeded. This suggests a service-specific, DNS, TLS, or HTTP problem may exist.",
            "next_step": "Check the affected service's URL and status page, then review its DNS and HTTP error details.",
        }

    if dns_checks and dns_failed and reachable:
        if dns_resolved:
            return {
                "code": "partial_dns_resolution",
                "title": "Some DNS lookups failed",
                "summary": f"{len(dns_failed)} of {len(dns_checks)} configured DNS hostname(s) failed to resolve while public IP destinations responded.",
                "next_step": "Repeat the lookup and verify the hostnames and system DNS configuration. A single failure may be transient.",
            }
        if not dns_resolved and all(item["status"] != "error" for item in dns_checks):
            return {
                "code": "possible_dns_issue",
                "title": "Public IPs respond, but DNS lookups fail",
                "summary": "The public IP checks responded while none of the configured DNS hostnames resolved. This is consistent with a possible DNS-resolver or hostname issue.",
                "next_step": "Check the device's DNS server configuration and retry name resolution before changing router or ISP settings.",
            }

    if service_checks and healthy_services and not failed_services:
        return {
            "code": "service_connectivity_confirmed",
            "title": "Configured HTTP services respond",
            "summary": f"All {len(healthy_services)} configured HTTP service(s) returned a successful HTTP response. This confirms access to these endpoints, not every application.",
            "next_step": "If a user still has a problem, test that exact application and compare its host, URL, and response.",
        }

    if not external_targets and not service_checks:
        return {
            "code": "no_targets_configured",
            "title": "No external targets configured",
            "summary": "The monitor has no public destinations or HTTP services to check.",
            "next_step": "Configure INTERNET_TARGETS and, if useful, SERVICE_URLS, then try again.",
        }

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
            "next_step": "Retry failed checks and compare with a service users cannot reach before concluding the ISP is at fault.",
        }

    if not all_external_completed:
        return {
            "code": "inconclusive",
            "title": "Diagnosis inconclusive",
            "summary": "One or more public-target checks could not complete, so the results do not establish whether connectivity is down.",
            "next_step": "Check that ping is installed and allowed, then repeat the diagnosis.",
        }

    if dns_resolved and all_external_failed:
        return {
            "code": "ping_unresponsive_dns_works",
            "title": "DNS resolves, but public ping checks failed",
            "summary": "DNS lookups succeeded but none of the public ping targets responded. ICMP may be filtered, so this alone does not confirm an internet outage.",
            "next_step": "Open a known website or run a configured HTTP service check before treating this as an upstream outage.",
        }

    if all_external_failed and gateway_status == "online":
        return {
            "code": "possible_upstream_issue",
            "title": "Local gateway responds; public targets do not",
            "summary": "The local gateway answered, but none of the configured public targets did. This may indicate an upstream issue, target filtering, or ICMP restrictions.",
            "next_step": "Try opening a known website, check the router/ISP connection status, and repeat the test before deciding the cause.",
        }

    if all_external_failed and gateway_status == "offline":
        return {
            "code": "possible_local_network_issue",
            "title": "Neither the gateway nor public targets responded",
            "summary": "The checks could not reach the local gateway or configured public targets. A local Wi-Fi, cable, router, or routing problem is possible, but ICMP filtering can also cause this result.",
            "next_step": "Check the Wi-Fi/Ethernet link and gateway address, then retry before concluding the router is down.",
        }

    return {
        "code": "gateway_unavailable",
        "title": "Public targets did not respond; gateway check unavailable",
        "summary": "No configured public targets responded, and the local gateway could not be checked. The cause remains uncertain.",
        "next_step": "Check the local router and network link, then repeat the diagnosis. These checks cannot determine root cause by themselves.",
    }


async def run_connectivity_diagnosis() -> dict[str, Any]:
    """Probe the gateway, public IP targets, DNS, and optional HTTP services."""
    gateway, gateway_note = await discover_default_gateway()

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
    external = [
        _as_probe(target, result)
        for target, result in zip(targets, results)
    ]

    service_urls = settings.service_urls_list
    hosts = set(settings.dns_test_hosts_list)
    for url in service_urls:
        host = urlparse(url).hostname
        if host:
            hosts.add(host)

    dns_checks = await asyncio.gather(
        *(check_dns_host(host) for host in sorted(hosts))
    )
    service_checks = await asyncio.gather(
        *(check_http_service(url) for url in service_urls)
    )

    diagnosis = classify_diagnosis(
        gateway_result["status"],
        external,
        dns_checks=dns_checks,
        service_checks=service_checks,
    )
    return {
        "diagnosed_at": datetime.now(timezone.utc).isoformat(),
        "gateway": gateway_result,
        "external_targets": external,
        "dns_checks": dns_checks,
        "service_checks": service_checks,
        "diagnosis": diagnosis,
        "note": "Reachability tests are clues, not proof of root cause. Some networks block ICMP; HTTP checks cover only configured URLs.",
    }
