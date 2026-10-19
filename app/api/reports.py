import csv
import io
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import ConnectivityCheck, Outage

router = APIRouter(prefix="/api/reports", tags=["reports"])


def utc_iso(value):
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def safe_text(value):
    """Prevent spreadsheet formula execution from untrusted text fields."""
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


@router.get("/csv")
async def export_csv(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    """Export connectivity measurements and overlapping outage events."""
    now = datetime.now(timezone.utc)
    start = now - timedelta(hours=hours)

    checks_query = (
        select(ConnectivityCheck)
        .where(
            ConnectivityCheck.timestamp >= start,
            ConnectivityCheck.timestamp <= now,
        )
        .order_by(ConnectivityCheck.timestamp.asc())
    )
    checks = (await db.scalars(checks_query)).all()

    outages_query = (
        select(Outage)
        .where(
            Outage.start_time <= now,
            or_(
                Outage.end_time.is_(None),
                Outage.end_time >= start,
            ),
        )
        .order_by(Outage.start_time.asc())
    )
    outages = (await db.scalars(outages_query)).all()

    output = io.StringIO(newline="")
    writer = csv.writer(output)

    writer.writerow([
        "record_type", "record_id", "timestamp", "target", "status",
        "latency_ms", "error_message", "outage_type", "start_time",
        "end_time", "duration_seconds", "is_resolved", "notes",
    ])

    for check in checks:
        probe_error = bool(
            check.error_message
            and check.error_message.startswith("PROBE_ERROR:")
        )
        status = (
            "error" if probe_error
            else "online" if check.is_up
            else "offline"
        )

        writer.writerow([
            "connectivity_check",
            check.id,
            utc_iso(check.timestamp),
            safe_text(check.target),
            status,
            check.latency_ms if check.latency_ms is not None else "",
            safe_text(check.error_message),
            "", "", "", "", "", "",
        ])

    for outage in outages:
        event_start = (
            outage.start_time.replace(tzinfo=timezone.utc)
            if outage.start_time.tzinfo is None
            else outage.start_time.astimezone(timezone.utc)
        )
        event_end = (
            outage.end_time.replace(tzinfo=timezone.utc)
            if outage.end_time and outage.end_time.tzinfo is None
            else outage.end_time.astimezone(timezone.utc)
            if outage.end_time
            else now
        )

        # Report the portion of the event that overlaps the selected window.
        overlap_start = max(event_start, start)
        overlap_end = min(event_end, now)
        duration = max(
            0, int((overlap_end - overlap_start).total_seconds())
        )

        writer.writerow([
            "outage",
            outage.id,
            utc_iso(outage.start_time),
            "",
            "resolved" if outage.is_resolved else "active",
            "",
            "",
            safe_text(outage.outage_type),
            utc_iso(outage.start_time),
            utc_iso(outage.end_time),
            duration,
            outage.is_resolved,
            safe_text(outage.notes),
        ])

    filename = f"ethionet-pulse-report-{hours}h.csv"

    return Response(
        content=output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "no-store",
        },
    )
