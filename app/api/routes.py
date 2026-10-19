from datetime import datetime, timezone, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import ConnectivityCheck, Outage

router = APIRouter(prefix="/api", tags=["monitoring"])


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    # SQLite can return UTC timestamps without timezone information.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _outage_dict(outage: Outage) -> dict:
    start = outage.start_time

    if start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)

    duration = outage.duration_seconds

    if duration is None and not outage.is_resolved:
        duration = max(
            0,
            int((datetime.now(timezone.utc) - start).total_seconds()),
        )

    return {
        "id": outage.id,
        "type": outage.outage_type,
        "start_time": _iso(outage.start_time),
        "end_time": _iso(outage.end_time),
        "duration_seconds": duration,
        "is_resolved": outage.is_resolved,
        "notes": outage.notes,
    }


@router.get("/status")
async def get_status(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Current status of each configured network target."""
    statement = (
        select(ConnectivityCheck)
        .order_by(
            ConnectivityCheck.timestamp.desc(),
            ConnectivityCheck.id.desc(),
        )
        .limit(1000)
    )
    rows = (await db.scalars(statement)).all()

    latest_by_target: dict[str, ConnectivityCheck] = {}

    for check in rows:
        latest_by_target.setdefault(check.target, check)

    targets = settings.targets_list
    target_states = []

    for target in targets:
        check = latest_by_target.get(target)

        if check is None:
            target_states.append({
                "target": target,
                "status": "not_checked",
                "is_up": None,
                "latency_ms": None,
                "timestamp": None,
                "error_message": None,
            })
            continue

        probe_error = bool(
            check.error_message
            and check.error_message.startswith("PROBE_ERROR:")
        )

        target_states.append({
            "target": target,
            "status": (
                "error" if probe_error
                else "online" if check.is_up
                else "offline"
            ),
            "is_up": None if probe_error else check.is_up,
            "latency_ms": check.latency_ms,
            "timestamp": _iso(check.timestamp),
            "error_message": check.error_message,
        })

    if any(item["status"] == "online" for item in target_states):
        overall = "online"
    elif not targets or any(
        item["status"] in {"error", "not_checked"}
        for item in target_states
    ):
        overall = "unknown"
    else:
        overall = "offline"

    active_statement = (
        select(Outage)
        .where(
            Outage.outage_type == "internet",
            Outage.is_resolved.is_(False),
        )
        .order_by(Outage.start_time.desc())
        .limit(1)
    )
    active = (await db.scalars(active_statement)).first()

    return {
        "application": settings.APP_NAME,
        "internet_status": overall,
        "last_checked": _iso(rows[0].timestamp) if rows else None,
        "targets": target_states,
        "active_outage": _outage_dict(active) if active else None,
    }


@router.get("/history")
async def get_history(
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent connectivity check records."""
    statement = (
        select(ConnectivityCheck)
        .order_by(
            ConnectivityCheck.timestamp.desc(),
            ConnectivityCheck.id.desc(),
        )
        .limit(limit)
    )
    rows = (await db.scalars(statement)).all()

    return {
        "count": len(rows),
        "items": [
            {
                "id": row.id,
                "timestamp": _iso(row.timestamp),
                "target": row.target,
                "is_up": row.is_up,
                "latency_ms": row.latency_ms,
                "error_message": row.error_message,
            }
            for row in rows
        ],
    }


@router.get("/outages")
async def get_outages(
    limit: int = Query(default=100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent outage events, including unresolved outages."""
    statement = (
        select(Outage)
        .order_by(Outage.start_time.desc(), Outage.id.desc())
        .limit(limit)
    )
    rows = (await db.scalars(statement)).all()

    return {
        "count": len(rows),
        "items": [_outage_dict(row) for row in rows],
    }
