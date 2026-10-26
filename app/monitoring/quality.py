"""Packet-loss, latency, jitter, and sustained degradation monitoring."""

import asyncio
import logging
import re
import shutil
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import NetworkQualityCheck, NetworkQualityIncident
from app.monitoring.alerts import send_outage_alert

logger = logging.getLogger(__name__)

_LOSS_RE = re.compile(r"([0-9.]+)%\s*packet loss", re.IGNORECASE)
_PACKET_RE = re.compile(
    r"([0-9]+)\s+packets transmitted,\s*([0-9]+)\s+(?:packets\s+)?received",
    re.IGNORECASE,
)
_RTT_RE = re.compile(
    r"(?:rtt|round-trip)\s+min/avg/max/(?:mdev|stddev)\s*=\s*"
    r"([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms",
    re.IGNORECASE,
)
_RTT_THREE_RE = re.compile(
    r"(?:rtt|round-trip)\s+min/avg/max\s*=\s*"
    r"([0-9.]+)/([0-9.]+)/([0-9.]+)\s*ms",
    re.IGNORECASE,
)

_degraded_rounds: dict[str, int] = {}
_healthy_rounds: dict[str, int] = {}


def parse_ping_output(
    output: str,
    *,
    sample_count: int,
    return_code: int,
) -> dict[str, Any]:
    """Parse common iputils ping summaries; tolerate missing RTT on total loss."""
    sent = max(1, sample_count)
    received = sent if return_code == 0 else 0

    packet_match = _PACKET_RE.search(output)
    if packet_match:
        sent = max(1, int(packet_match.group(1)))
        received = min(sent, int(packet_match.group(2)))

    loss_match = _LOSS_RE.search(output)
    if loss_match:
        loss = min(100.0, max(0.0, float(loss_match.group(1))))
    else:
        loss = round(100.0 * (sent - received) / sent, 2)

    rtt = _RTT_RE.search(output)
    if rtt:
        latency_min, latency_avg, latency_max, jitter = (
            float(value) for value in rtt.groups()
        )
    else:
        rtt_three = _RTT_THREE_RE.search(output)
        if rtt_three:
            latency_min, latency_avg, latency_max = (
                float(value) for value in rtt_three.groups()
            )
            jitter = None
        else:
            latency_min = latency_avg = latency_max = jitter = None

    return {
        "packets_sent": sent,
        "packets_received": received,
        "packet_loss_percent": loss,
        "latency_min_ms": latency_min,
        "latency_avg_ms": latency_avg,
        "latency_max_ms": latency_max,
        "latency_jitter_ms": jitter,
    }


async def probe_target_quality(target: str) -> dict[str, Any]:
    """Send multiple ICMP samples to one target and parse quality statistics."""
    count = max(1, min(20, settings.PING_SAMPLES_PER_CHECK))
    timeout = max(1, settings.QUALITY_PING_TIMEOUT_SECONDS)

    if shutil.which("ping") is None:
        return {
            "target": target,
            "probe_completed": False,
            "packets_sent": count,
            "packets_received": 0,
            "packet_loss_percent": None,
            "latency_min_ms": None,
            "latency_avg_ms": None,
            "latency_max_ms": None,
            "latency_jitter_ms": None,
            "is_degraded": None,
            "status": "error",
            "error_message": "PROBE_ERROR: ping utility not found; install iputils.",
        }

    try:
        process = await asyncio.create_subprocess_exec(
            "ping", "-n", "-c", str(count), "-W", str(timeout), target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            output_bytes, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=(timeout * count) + 3,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return {
                "target": target,
                "probe_completed": False,
                "packets_sent": count,
                "packets_received": 0,
                "packet_loss_percent": None,
                "latency_min_ms": None,
                "latency_avg_ms": None,
                "latency_max_ms": None,
                "latency_jitter_ms": None,
                "is_degraded": None,
                "status": "error",
                "error_message": "PROBE_ERROR: multi-packet ping timed out.",
            }
    except OSError as exc:
        return {
            "target": target,
            "probe_completed": False,
            "packets_sent": count,
            "packets_received": 0,
            "packet_loss_percent": None,
            "latency_min_ms": None,
            "latency_avg_ms": None,
            "latency_max_ms": None,
            "latency_jitter_ms": None,
            "is_degraded": None,
            "status": "error",
            "error_message": f"PROBE_ERROR: Could not execute ping ({type(exc).__name__}).",
        }

    output = output_bytes.decode("utf-8", errors="replace")
    metrics = parse_ping_output(
        output, sample_count=count, return_code=process.returncode
    )
    loss = metrics["packet_loss_percent"]
    average = metrics["latency_avg_ms"]
    degraded = (
        loss is not None and loss >= settings.PACKET_LOSS_WARNING_PERCENT
    ) or (
        average is not None and average >= settings.HIGH_LATENCY_WARNING_MS
    )
    return {
        "target": target,
        **metrics,
        "probe_completed": True,
        "is_degraded": bool(degraded),
        "status": "degraded" if degraded else "healthy",
        "error_message": None if not degraded else (
            "Packet loss or latency exceeded the configured warning threshold."
        ),
    }


async def _update_quality_incident(
    session,
    *,
    target: str,
    is_degraded: bool,
    packet_loss_percent: float | None,
    latency_avg_ms: float | None,
) -> dict[str, Any] | None:
    """Open/resolve an incident only when a sustained state changes."""
    statement = (
        select(NetworkQualityIncident)
        .where(
            NetworkQualityIncident.target == target,
            NetworkQualityIncident.is_resolved.is_(False),
        )
        .order_by(NetworkQualityIncident.start_time.desc())
        .limit(1)
    )
    active = (await session.scalars(statement)).first()
    now = datetime.now(timezone.utc)

    if is_degraded and active is not None:
        if packet_loss_percent is not None:
            active.peak_packet_loss_percent = max(
                active.peak_packet_loss_percent or 0.0, packet_loss_percent
            )
        if latency_avg_ms is not None:
            active.peak_latency_ms = max(active.peak_latency_ms or 0.0, latency_avg_ms)
        return None

    if not is_degraded and active is not None:
        start = active.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        duration = max(0, int((now - start).total_seconds()))
        active.end_time = now
        active.duration_seconds = duration
        active.is_resolved = True
        return {
            "event": "network_quality_recovered",
            "target": target,
            "start_time": start.isoformat(),
            "end_time": now.isoformat(),
            "duration_seconds": duration,
            "peak_packet_loss_percent": active.peak_packet_loss_percent,
            "peak_latency_ms": active.peak_latency_ms,
        }

    if is_degraded and active is None:
        incident = NetworkQualityIncident(
            target=target,
            start_time=now,
            is_resolved=False,
            peak_packet_loss_percent=packet_loss_percent,
            peak_latency_ms=latency_avg_ms,
            notes=(
                "Sustained packet loss or latency crossed configured thresholds. "
                "ICMP filtering can affect these measurements."
            ),
        )
        session.add(incident)
        await session.flush()
        return {
            "event": "network_quality_degraded",
            "target": target,
            "start_time": now.isoformat(),
            "packet_loss_percent": packet_loss_percent,
            "latency_avg_ms": latency_avg_ms,
        }

    return None


async def run_network_quality_checks() -> dict[str, Any]:
    """Persist multi-packet quality samples and alert on sustained degradation."""
    targets = settings.targets_list
    if not targets:
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "configured": 0,
            "checked": 0,
            "healthy": 0,
            "degraded": 0,
            "events": [],
            "items": [],
        }

    results = await asyncio.gather(*(probe_target_quality(target) for target in targets))
    degraded_threshold = max(1, settings.DEGRADATION_CONSECUTIVE_ROUNDS)
    recovery_threshold = max(1, settings.QUALITY_RECOVERY_CONSECUTIVE_ROUNDS)
    events: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        try:
            for result in results:
                target = result["target"]
                session.add(
                    NetworkQualityCheck(
                        target=target,
                        probe_completed=result["probe_completed"],
                        packets_sent=result["packets_sent"],
                        packets_received=result["packets_received"],
                        packet_loss_percent=result["packet_loss_percent"],
                        latency_min_ms=result["latency_min_ms"],
                        latency_avg_ms=result["latency_avg_ms"],
                        latency_max_ms=result["latency_max_ms"],
                        latency_jitter_ms=result["latency_jitter_ms"],
                        is_degraded=result["is_degraded"],
                        error_message=result["error_message"],
                    )
                )

                if not result["probe_completed"]:
                    _degraded_rounds[target] = 0
                    _healthy_rounds[target] = 0
                    continue

                if result["is_degraded"]:
                    _healthy_rounds[target] = 0
                    _degraded_rounds[target] = min(
                        degraded_threshold, _degraded_rounds.get(target, 0) + 1
                    )
                    if _degraded_rounds[target] >= degraded_threshold:
                        event = await _update_quality_incident(
                            session,
                            target=target,
                            is_degraded=True,
                            packet_loss_percent=result["packet_loss_percent"],
                            latency_avg_ms=result["latency_avg_ms"],
                        )
                        if event:
                            events.append(event)
                else:
                    _degraded_rounds[target] = 0
                    _healthy_rounds[target] = min(
                        recovery_threshold, _healthy_rounds.get(target, 0) + 1
                    )
                    if _healthy_rounds[target] >= recovery_threshold:
                        event = await _update_quality_incident(
                            session,
                            target=target,
                            is_degraded=False,
                            packet_loss_percent=result["packet_loss_percent"],
                            latency_avg_ms=result["latency_avg_ms"],
                        )
                        if event:
                            events.append(event)

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Could not save network quality measurements.")
            raise

    for event in events:
        try:
            await send_outage_alert(event)
        except Exception:
            logger.exception("Network quality alert failed; monitoring will continue.")

    checked = sum(1 for result in results if result["probe_completed"])
    degraded = sum(
        1 for result in results if result["probe_completed"] and result["is_degraded"]
    )
    logger.info("Network quality checks completed: %s degraded of %s checked.", degraded, checked)
    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "configured": len(targets),
        "checked": checked,
        "healthy": checked - degraded,
        "degraded": degraded,
        "events": events,
        "items": results,
    }
