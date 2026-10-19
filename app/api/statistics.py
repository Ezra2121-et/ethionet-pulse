from datetime import datetime, timedelta, timezone
from statistics import mean

from fastapi import APIRouter, Depends, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import ConnectivityCheck, Outage

router = APIRouter(prefix="/api", tags=["statistics"])
UTC = timezone.utc


def as_utc(value: datetime) -> datetime:
    """SQLite may return naive datetimes for UTC values."""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def classify_round(checks, targets: list[str]) -> str:
    """Classify a monitoring round without mistaking probe errors for outages."""
    if any(check.is_up for check in checks):
        return "online"

    by_target = {check.target: check for check in checks}

    if not targets or any(target not in by_target for target in targets):
        return "unknown"

    if any(
        (by_target[target].error_message or "").startswith("PROBE_ERROR:")
        for target in targets
    ):
        return "unknown"

    return "offline"


def group_rounds(
    checks,
    targets: list[str],
    tolerance_seconds: float,
) -> list[tuple[datetime, str]]:
    """Group records created by the same scheduled connectivity check."""
    groups: list[list] = []

    for check in sorted(checks, key=lambda item: as_utc(item.timestamp)):
        timestamp = as_utc(check.timestamp)

        if (
            groups
            and (timestamp - as_utc(groups[-1][0].timestamp)).total_seconds()
            <= tolerance_seconds
        ):
            groups[-1].append(check)
        else:
            groups.append([check])

    rounds = []
    for group in groups:
        timestamp = min(as_utc(item.timestamp) for item in group)
        rounds.append((timestamp, classify_round(group, targets)))

    return rounds


def calculate_time_buckets(
    rounds: list[tuple[datetime, str]],
    window_start: datetime,
    window_end: datetime,
    max_gap_seconds: int,
) -> dict[str, float]:
    """
    Estimate time by observed state.

    Each sample represents its state until the next sample, but never
    beyond max_gap_seconds. Longer gaps are left unmonitored.
    """
    buckets = {"online": 0.0, "offline": 0.0, "unknown": 0.0}
    window_start = as_utc(window_start)
    window_end = as_utc(window_end)
    max_gap = timedelta(seconds=max_gap_seconds)

    for index, (sample_time, status) in enumerate(rounds):
        sample_time = as_utc(sample_time)

        if sample_time >= window_end:
            continue

        next_time = (
            as_utc(rounds[index + 1][0])
            if index + 1 < len(rounds)
            else window_end
        )

        gap = next_time - sample_time
        if gap.total_seconds() <= 0:
            continue

        segment_end = (
            next_time if gap <= max_gap else sample_time + max_gap
        )

        segment_start = max(sample_time, window_start)
        segment_end = min(segment_end, window_end)

        if segment_end > segment_start:
            buckets[status] += (
                segment_end - segment_start
            ).total_seconds()

    return buckets


@router.get("/statistics")
async def get_statistics(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """
    Return estimated availability, measured coverage, latency and outages.

    Availability is calculated only from known online/offline intervals.
    Missing monitoring intervals are not treated as uptime.
    """
    now = datetime.now(UTC)
    window_start = now - timedelta(hours=hours)
    window_seconds = hours * 3600

    max_gap_seconds = max(60, settings.CHECK_INTERVAL_SECONDS * 2)
    tolerance_seconds = max(
        2.0,
        min(10.0, settings.CHECK_INTERVAL_SECONDS / 3),
    )

    # Fetch one maximum gap before the window so a sample immediately
    # before the window can contribute its legitimately observed interval.
    lookback = window_start - timedelta(
        seconds=max_gap_seconds + tolerance_seconds
    )

    statement = (
        select(ConnectivityCheck)
        .where(
            ConnectivityCheck.timestamp >= lookback,
            ConnectivityCheck.timestamp <= now,
        )
        .order_by(ConnectivityCheck.timestamp.asc())
    )
    checks = (await db.scalars(statement)).all()

    rounds = group_rounds(
        checks,
        settings.targets_list,
        tolerance_seconds,
    )

    buckets = calculate_time_buckets(
        rounds,
        window_start,
        now,
        max_gap_seconds,
    )

    online_seconds = buckets["online"]
    offline_seconds = buckets["offline"]
    unknown_seconds = buckets["unknown"]

    measured_seconds = online_seconds + offline_seconds + unknown_seconds
    known_seconds = online_seconds + offline_seconds

    uptime_percentage = (
        round(100 * online_seconds / known_seconds, 2)
        if known_seconds > 0
        else None
    )

    measurement_coverage = round(
        min(100.0, 100 * measured_seconds / window_seconds), 2
    )
    known_coverage = round(
        min(100.0, 100 * known_seconds / window_seconds), 2
    )

    latency_samples = [
        float(check.latency_ms)
        for check in checks
        if as_utc(check.timestamp) >= window_start
        and check.is_up
        and check.latency_ms is not None
    ]

    outage_statement = (
        select(Outage)
        .where(
            Outage.start_time <= now,
            or_(
                Outage.end_time.is_(None),
                Outage.end_time >= window_start,
            ),
        )
        .order_by(Outage.start_time.desc())
    )
    outage_rows = (await db.scalars(outage_statement)).all()

    outage_durations = []
    for outage in outage_rows:
        start = as_utc(outage.start_time)
        end = as_utc(outage.end_time) if outage.end_time else now

        overlap_start = max(start, window_start)
        overlap_end = min(end, now)

        if overlap_end > overlap_start:
            outage_durations.append(
                int((overlap_end - overlap_start).total_seconds())
            )

    round_count = sum(
        1 for timestamp, _ in rounds
        if timestamp >= window_start
    )

    return {
        "window_hours": hours,
        "window_start": window_start.isoformat(),
        "window_end": now.isoformat(),
        "rounds_observed": round_count,
        "configured_targets": len(settings.targets_list),
        "sampling": {
            "check_interval_seconds": settings.CHECK_INTERVAL_SECONDS,
            "max_gap_seconds": max_gap_seconds,
        },
        "uptime_percentage": uptime_percentage,
        "online_seconds": int(round(online_seconds)),
        "offline_seconds": int(round(offline_seconds)),
        "unknown_seconds": int(round(unknown_seconds)),
        "unmonitored_seconds": max(
            0,
            window_seconds - int(round(measured_seconds)),
        ),
        "measurement_coverage_percentage": measurement_coverage,
        "known_status_coverage_percentage": known_coverage,
        "latency": {
            "sample_count": len(latency_samples),
            "average_ms": round(mean(latency_samples), 2)
            if latency_samples else None,
            "minimum_ms": round(min(latency_samples), 2)
            if latency_samples else None,
            "maximum_ms": round(max(latency_samples), 2)
            if latency_samples else None,
        },
        "outages": {
            "count": len(outage_durations),
            "total_duration_seconds": sum(outage_durations),
            "longest_duration_seconds": max(outage_durations, default=0),
        },
    }
