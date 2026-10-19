import asyncio
import logging
import re
import shutil
from datetime import datetime, timezone

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ConnectivityCheck
from app.monitoring.outage import update_internet_outage

logger = logging.getLogger(__name__)


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
    """Probe configured targets and persist the results."""
    targets = settings.targets_list

    if not targets:
        logger.warning("No connectivity targets are configured.")
        return {
            "targets_checked": 0,
            "internet_online": None,
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

            # One responding target proves connectivity. To declare
            # an outage, every configured probe must have completed.
            if online_targets > 0 or all_probes_completed:
                await update_internet_outage(
                    session,
                    is_online=online_targets > 0,
                )

            await session.commit()

        except Exception:
            await session.rollback()
            logger.exception("Could not save connectivity results.")
            raise

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

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "targets_checked": len(targets),
        "online_targets": online_targets,
        "internet_online": internet_online,
    }
