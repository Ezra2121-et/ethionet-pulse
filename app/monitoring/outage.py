from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Outage


def _as_utc(value: datetime) -> datetime:
    # SQLite may return timezone-naive datetime values.
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def update_internet_outage(
    session: AsyncSession,
    *,
    is_online: bool,
) -> None:
    """Open an outage when all probes fail, or close it on recovery."""
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

        active_outage.end_time = now
        active_outage.duration_seconds = max(
            0, int((now - start).total_seconds())
        )
        active_outage.is_resolved = True
        return

    if not is_online and active_outage is None:
        session.add(
            Outage(
                start_time=now,
                outage_type="internet",
                is_resolved=False,
                notes=(
                    "All configured connectivity probes failed. "
                    "This does not, by itself, prove a power outage."
                ),
            )
        )
