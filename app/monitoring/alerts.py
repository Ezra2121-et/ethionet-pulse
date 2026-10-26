"""Optional Telegram alerts for confirmed outage transitions."""

import asyncio
import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def format_outage_message(event: dict[str, Any]) -> str:
    """Build a concise, plain-text alert without depending on Telegram."""
    name = settings.APP_NAME
    kind = event.get("event")

    if kind == "outage_started":
        timestamp = event.get("start_time") or "time unavailable"
        return (
            f"🚨 {name}: connectivity outage detected\n"
            f"Started: {timestamp}\n"
            "Details: all configured connectivity probes failed for the "
            "required consecutive checks. Verify local connectivity and "
            "repeat diagnosis before concluding the cause."
        )

    if kind == "outage_recovered":
        timestamp = event.get("end_time") or "time unavailable"
        duration = max(0, int(event.get("duration_seconds") or 0))
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        duration_label = (
            f"{hours}h {minutes}m {seconds}s" if hours
            else f"{minutes}m {seconds}s"
        )
        return (
            f"✅ {name}: connectivity recovered\n"
            f"Recovered: {timestamp}\n"
            f"Recorded outage duration: {duration_label}"
        )

    if kind == "service_outage_started":
        timestamp = event.get("start_time") or "time unavailable"
        service_url = event.get("service_url") or "configured HTTP service"
        return (
            f"🚨 {name}: monitored service is down\\n"
            f"Service: {service_url}\\n"
            f"Confirmed: {timestamp}\\n"
            "The endpoint failed the required consecutive checks. "
            "Verify the service and network before concluding the cause."
        )

    if kind == "service_outage_recovered":
        timestamp = event.get("end_time") or "time unavailable"
        service_url = event.get("service_url") or "configured HTTP service"
        duration = max(0, int(event.get("duration_seconds") or 0))
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        duration_label = (
            f"{hours}h {minutes}m {seconds}s" if hours
            else f"{minutes}m {seconds}s"
        )
        return (
            f"✅ {name}: monitored service recovered\\n"
            f"Service: {service_url}\\n"
            f"Recovered: {timestamp}\\n"
            f"Recorded incident duration: {duration_label}"
        )

    return f"{name}: monitoring event recorded."


async def send_outage_alert(event: dict[str, Any] | None) -> bool:
    """Send a Telegram message for a real database outage transition.

    Transient HTTP failures get a few short retries. Missing configuration
    or delivery errors never interrupt monitoring.
    """
    if not event:
        return False

    if not settings.ENABLE_TELEGRAM_ALERTS:
        logger.debug("Telegram alerts are disabled.")
        return False

    token = settings.TELEGRAM_BOT_TOKEN.strip()
    chat_id = settings.TELEGRAM_CHAT_ID.strip()
    if not token or not chat_id:
        logger.warning(
            "Telegram alerts are enabled, but the bot token or chat ID is missing."
        )
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = {
        "chat_id": chat_id,
        "text": format_outage_message(event),
        "disable_web_page_preview": True,
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(url, json=body)

            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                logger.warning("Telegram rejected an outage alert.")
                return False

            logger.info("Telegram outage alert delivered.")
            return True

        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            retryable = status == 429 or status >= 500
            if not retryable or attempt == 2:
                # Do not log the response/request URL because it contains the bot token.
                logger.warning(
                    "Telegram alert delivery was rejected with HTTP %s.", status
                )
                return False
        except httpx.RequestError:
            if attempt == 2:
                logger.warning(
                    "Telegram alert delivery failed after retries; monitoring will continue."
                )
                return False
        except ValueError:
            logger.warning("Telegram returned an invalid response; alert was not confirmed.")
            return False

        await asyncio.sleep(0.5 * (attempt + 1))

    return False
