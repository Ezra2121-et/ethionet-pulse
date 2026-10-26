"""Optional Telegram alerts for confirmed outage transitions."""

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
            f"Details: all configured connectivity probes failed for the "
            f"required consecutive checks. Verify local connectivity and "
            f"repeat diagnosis before concluding the cause."
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

    return f"{name}: monitoring event recorded."


async def send_outage_alert(event: dict[str, Any] | None) -> bool:
    """Send a Telegram message for a real database outage transition.

    Missing configuration or delivery errors never interrupt monitoring.
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
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": format_outage_message(event),
                    "disable_web_page_preview": True,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if not payload.get("ok"):
                logger.warning("Telegram rejected an outage alert.")
                return False
    except (httpx.HTTPError, ValueError):
        # Avoid logging the request URL because it contains the bot token.
        logger.warning("Telegram alert delivery failed; monitoring will continue.")
        return False

    logger.info("Telegram outage alert delivered.")
    return True
