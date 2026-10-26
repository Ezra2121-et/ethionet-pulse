"""Scheduled HTTP(S) service checks, persistent history, and transition alerts."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import select

from app.config import settings
from app.database import AsyncSessionLocal
from app.models import ServiceCheck, ServiceOutage
from app.monitoring.alerts import send_outage_alert
from app.monitoring.urls import safe_service_url

logger = logging.getLogger(__name__)

# In-memory streaks are appropriate for this local, single-instance prototype.
# The database remains the source of truth for whether an incident is active.
_failed_rounds: dict[str, int] = {}
_successful_rounds: dict[str, int] = {}


async def probe_service_url(raw_url: str, client: httpx.AsyncClient) -> dict[str, Any]:
    """Probe one configured endpoint and return a safe, serializable result."""
    safe_url = safe_service_url(raw_url)
    if safe_url is None:
        return {
            "service_url": "(invalid configured URL)",
            "is_up": False,
            "probe_completed": False,
            "http_status_code": None,
            "response_time_ms": None,
            "error_message": "Invalid URL: configure an absolute HTTP(S) URL.",
        }

    started = time.perf_counter()
    try:
        # Streaming stops after response headers. We need status and latency,
        # not the potentially large body of a monitored application.
        async with client.stream("GET", raw_url) as response:
            status_code = response.status_code
        elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
        is_up = 200 <= status_code < 400
        return {
            "service_url": safe_url,
            "is_up": is_up,
            "probe_completed": True,
            "http_status_code": status_code,
            "response_time_ms": elapsed_ms,
            "error_message": None if is_up else f"HTTP {status_code} response",
        }
    except httpx.TimeoutException:
        return {
            "service_url": safe_url,
            "is_up": False,
            "probe_completed": True,
            "http_status_code": None,
            "response_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_message": "HTTP request timed out",
        }
    except (httpx.RequestError, httpx.InvalidURL) as exc:
        # Never include str(exc): HTTP client errors can include the full URL,
        # including credentials or query parameters from operator configuration.
        return {
            "service_url": safe_url,
            "is_up": False,
            "probe_completed": True,
            "http_status_code": None,
            "response_time_ms": round((time.perf_counter() - started) * 1000, 2),
            "error_message": f"HTTP request failed ({type(exc).__name__})",
        }


async def _update_service_outage(
    session,
    *,
    service_url: str,
    is_online: bool,
) -> dict[str, Any] | None:
    """Create or resolve one service incident and return only real transitions."""
    statement = (
        select(ServiceOutage)
        .where(
            ServiceOutage.service_url == service_url,
            ServiceOutage.is_resolved.is_(False),
        )
        .order_by(ServiceOutage.start_time.desc())
        .limit(1)
    )
    active = (await session.scalars(statement)).first()
    now = datetime.now(timezone.utc)

    if is_online and active is not None:
        start = active.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        duration = max(0, int((now - start).total_seconds()))
        active.end_time = now
        active.duration_seconds = duration
        active.is_resolved = True
        return {
            "event": "service_outage_recovered",
            "service_url": service_url,
            "outage_id": active.id,
            "start_time": start.isoformat(),
            "end_time": now.isoformat(),
            "duration_seconds": duration,
        }

    if not is_online and active is None:
        outage = ServiceOutage(
            service_url=service_url,
            start_time=now,
            is_resolved=False,
            notes="Configured HTTP service failed the required consecutive checks.",
        )
        session.add(outage)
        await session.flush()
        return {
            "event": "service_outage_started",
            "service_url": service_url,
            "outage_id": outage.id,
            "start_time": now.isoformat(),
        }

    return None


async def run_service_checks() -> dict[str, Any]:
    """Check configured HTTP services and alert on confirmed outage transitions."""
    configured: list[tuple[str, str]] = []
    seen: set[str] = set()
    invalid_count = 0

    # Remove duplicate normalized endpoints and do not expose query strings,
    # URL credentials, or fragments in stored measurements and alerts.
    for raw_url in settings.service_urls_list:
        safe_url = safe_service_url(raw_url)
        if safe_url is None:
            invalid_count += 1
            logger.warning("Skipping an invalid configured HTTP service URL.")
            continue
        if safe_url not in seen:
            seen.add(safe_url)
            configured.append((raw_url, safe_url))

    if not configured:
        return {
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "configured": 0,
            "checked": 0,
            "online": 0,
            "offline": 0,
            "invalid_configurations": invalid_count,
            "events": [],
        }

    timeout = max(1, settings.SERVICE_REQUEST_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        results = await asyncio.gather(
            *(probe_service_url(raw_url, client) for raw_url, _ in configured)
        )

    failure_threshold = max(1, settings.SERVICE_FAILURE_THRESHOLD)
    recovery_threshold = max(1, settings.SERVICE_RECOVERY_THRESHOLD)
    events: list[dict[str, Any]] = []

    async with AsyncSessionLocal() as session:
        try:
            for (_, expected_safe_url), result in zip(configured, results):
                # Keep the configured normalized key consistent with the DB key.
                service_url = expected_safe_url
                result["service_url"] = service_url

                session.add(
                    ServiceCheck(
                        service_url=service_url,
                        is_up=bool(result["is_up"]),
                        probe_completed=bool(result["probe_completed"]),
                        http_status_code=result["http_status_code"],
                        response_time_ms=result["response_time_ms"],
                        error_message=result["error_message"],
                    )
                )

                if not result["probe_completed"]:
                    _failed_rounds[service_url] = 0
                    _successful_rounds[service_url] = 0
                    continue

                if result["is_up"]:
                    _failed_rounds[service_url] = 0
                    _successful_rounds[service_url] = min(
                        recovery_threshold,
                        _successful_rounds.get(service_url, 0) + 1,
                    )
                    if _successful_rounds[service_url] >= recovery_threshold:
                        event = await _update_service_outage(
                            session,
                            service_url=service_url,
                            is_online=True,
                        )
                        if event:
                            events.append(event)
                else:
                    _successful_rounds[service_url] = 0
                    _failed_rounds[service_url] = min(
                        failure_threshold,
                        _failed_rounds.get(service_url, 0) + 1,
                    )
                    if _failed_rounds[service_url] >= failure_threshold:
                        event = await _update_service_outage(
                            session,
                            service_url=service_url,
                            is_online=False,
                        )
                        if event:
                            events.append(event)

            await session.commit()
        except Exception:
            await session.rollback()
            logger.exception("Could not save HTTP service check results.")
            raise

    # Commit the incident first. Telegram errors must not roll back history or
    # stop future checks. A transition is only emitted once per active incident.
    for event in events:
        try:
            await send_outage_alert(event)
        except Exception:
            logger.exception("Service alert handler failed; monitoring will continue.")

    online = sum(1 for result in results if result["probe_completed"] and result["is_up"])
    checked = sum(1 for result in results if result["probe_completed"])
    logger.info("HTTP service checks completed: %s/%s online.", online, checked)

    return {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "configured": len(configured),
        "checked": checked,
        "online": online,
        "offline": checked - online,
        "invalid_configurations": invalid_count,
        "events": events,
        "items": results,
    }
