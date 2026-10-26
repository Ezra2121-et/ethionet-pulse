import asyncio
import logging
import re
import shutil
from datetime import datetime, timezone

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ConnectivityCheck
from app.monitoring.alerts import send_outage_alert
from app.monitoring.outage import update_internet_outage

logger = logging.getLogger(__name__)

# Consecutive complete check rounds reduce one-off false alarms.
_consecutive_failed_rounds = 0
_consecutive_successful_rounds = 0


async def _ping_target(
    target: str,
) -> tuple[bool, float | None, str | None, bool]:
    """
    Return (reachable, latency_ms, error_message, probe_completed).

    A missing local ping utility is a probe error, not proof of
    an internet outage.
    """
    if shutil.which("ping") is None:
        return (
            False,
            None,
            "PROBE_ERROR: ping utility not found; install iputils.",
            False,
        )

    timeout_seconds = max(1, settings.REQUEST_TIMEOUT_SECONDS)

    try:
        process = await asyncio.create_subprocess_exec(
            "ping",
            "-n",
            "-c",
            "1",
            "-W",
            str(timeout_seconds),
            target,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        try:
            output_bytes, _ = await asyncio.wait_for(
                process.communicate(),
                timeout=timeout_seconds + 2,
            )
        except asyncio.TimeoutError:
            process.kill()
            await process.communicate()
            return False, None, "Ping process timed out.", True

    except OSError as exc:
        return (
            False,
            None,
            f"PROBE_ERROR: Could not execute ping: {exc}"[:255],
            False,
        )

    output = output_bytes.decode("utf-8", errors="replace").strip()

    if process.returncode == 0:
        match = re.search(
            r"time[=<]\s*([\d.]+)\s*ms",
            output,
            re.IGNORECASE,
        )
        latency = float(match.group(1)) if match else None
        return True, latency, None, True

    error = output.splitlines()[-1] if output else "No reply received."
    return False, None, error[:255], True


async def run_connectivity_checks() -> dict:
    """Probe configured targets, record results, and alert on confirmed transitions."""
    global _consecutive_failed_rounds, _consecutive_successful_rounds

    targets = settings.targets_list

    if not targets:
        logger.warning("No connectivity targets are configured.")
        return {
            "targets_checked": 0,
            "internet_online": None,
            "outage_event": None,
        }

    results = await asyncio.gather(
        *(_ping_target(target) for target in targets)
    )

    online_targets = sum(
        1 for reachable, _, _, measured in results
        if measured and reachable
    )
    all_probes_completed = all(
        measured for _, _, _, measured in results
    )

    failure_threshold = max(1, settings.OUTAGE_FAILURE_THRESHOLD)
    recovery_threshold = max(1, settings.OUTAGE_RECOVERY_THRESHOLD)
    outage_event = None

    # Unknown probe results break a consecutive streak. We do not count
    # local monitoring/tool errors as evidence that the internet is down.
    if online_targets > 0:
        _consecutive_failed_rounds = 0
        _consecutive_successful_rounds += 1
    elif all_probes_completed:
        _consecutive_successful_rounds = 0
        _consecutive_failed_rounds += 1
    else:
        _consecutive_failed_rounds = 0
        _consecutive_successful_rounds = 0

    async with AsyncSessionLocal() as session:
        try:
            for target, result in zip(targets, results):
                reachable, latency, error, _ = result
                session.add(
                    ConnectivityCheck(
                        target=target,
                        is_up=reachable,
                        latency_ms=latency,
                        error_message=error,
                    )
                )

            # Confirm an outage only after a run of complete failed rounds.
            if (
                _consecutive_failed_rounds >= failure_threshold
                and all_probes_completed
            ):
                outage_event = await update_internet_outage(
                    session,
                    is_online=False,
                )
            # Recover only after consecutive successful rounds.
            elif _consecutive_successful_rounds >= recovery_threshold:
                outage_event = await update_internet_outage(
                    session,
                    is_online=True,
                )

            await session.commit()

        except Exception:
            await session.rollback()
            logger.exception("Could not save connectivity results.")
            raise

    if outage_event:
        try:
            await send_outage_alert(outage_event)
        except Exception:
            # Notification delivery must never break the monitor loop.
            logger.exception("Outage alert handler failed; monitoring will continue.")

    internet_online = (
        True if online_targets > 0
        else False if all_probes_completed
        else None
    )

    logger.info(
        "Connectivity check completed: %s/%s targets reachable.",
        online_targets,
        len(targets),
    )

    if outage_event:
        logger.info("Outage transition recorded: %s", outage_event["event"])

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "targets_checked": len(targets),
        "online_targets": online_targets,
        "internet_online": internet_online,
        "outage_event": outage_event,
    }
