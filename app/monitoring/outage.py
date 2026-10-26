from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outage


def _as_utc(value: datetime) -> datetime:
    # SQLite can return timezone-naive datetime values.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def update_internet_outage(
    session: AsyncSession,
    *,
    is_online: bool,
) -> dict[str, Any] | None:
    """Open or resolve an outage and return an event only on state changes."""
    statement = (
        select(Outage)
        .where(
            Outage.outage_type == "internet",
            Outage.is_resolved.is_(False),
        )
        .order_by(Outage.start_time.desc())
        .limit(1)
    )

    active_outage = (await session.scalars(statement)).first()
    now = datetime.now(timezone.utc)

    if is_online and active_outage is not None:
        start = _as_utc(active_outage.start_time)
        duration = max(0, int((now - start).total_seconds()))

        active_outage.end_time = now
        active_outage.duration_seconds = duration
        active_outage.is_resolved = True

        return {
            "event": "outage_recovered",
            "outage_id": active_outage.id,
            "start_time": start.isoformat(),
            "end_time": now.isoformat(),
            "duration_seconds": duration,
        }

    if not is_online and active_outage is None:
        new_outage = Outage(
            start_time=now,
            outage_type="internet",
            is_resolved=False,
            notes=(
                "All configured connectivity probes failed for the "
                "required consecutive check rounds. This does not, by "
                "itself, prove a power outage or identify root cause."
            ),
        )
        session.add(new_outage)
        await session.flush()

        return {
            "event": "outage_started",
            "outage_id": new_outage.id,
            "start_time": now.isoformat(),
        }

    # No transition occurred; callers must not send another alert.
    return None
