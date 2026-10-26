from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.models import (
    ConnectivityCheck, Outage, ServiceCheck, ServiceOutage,
    NetworkQualityCheck, NetworkQualityIncident,
)
from app.monitoring.urls import safe_service_url
from app.monitoring.diagnostics import run_connectivity_diagnosis

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


@router.get("/diagnose")
async def diagnose_connectivity() -> dict:
    """Run an on-demand gateway and external-target reachability diagnosis."""
    return await run_connectivity_diagnosis()


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



@router.get("/services")
async def get_services(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the latest scheduled check for each configured HTTP service."""
    configured_urls: list[str] = []
    for raw_url in settings.service_urls_list:
        safe_url = safe_service_url(raw_url)
        if safe_url and safe_url not in configured_urls:
            configured_urls.append(safe_url)

    latest_by_url: dict[str, ServiceCheck] = {}
    if configured_urls:
        statement = (
            select(ServiceCheck)
            .where(ServiceCheck.service_url.in_(configured_urls))
            .order_by(ServiceCheck.timestamp.desc(), ServiceCheck.id.desc())
            .limit(2000)
        )
        rows = (await db.scalars(statement)).all()
        for row in rows:
            latest_by_url.setdefault(row.service_url, row)

    items = []
    for service_url in configured_urls:
        check = latest_by_url.get(service_url)
        if check is None:
            status = "pending"
        elif not check.probe_completed:
            status = "error"
        else:
            status = "online" if check.is_up else "offline"

        items.append({
            "service_url": service_url,
            "status": status,
            "is_up": check.is_up if check else None,
            "http_status_code": check.http_status_code if check else None,
            "response_time_ms": check.response_time_ms if check else None,
            "timestamp": _iso(check.timestamp) if check else None,
            "error_message": check.error_message if check else None,
        })

    return {
        "configured_count": len(configured_urls),
        "online_count": sum(item["status"] == "online" for item in items),
        "offline_count": sum(item["status"] == "offline" for item in items),
        "items": items,
    }


@router.get("/services/history")
async def get_service_history(
    limit: int = Query(default=100, ge=1, le=1000),
    service_url: str | None = Query(default=None, max_length=512),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return historical HTTP service measurements, optionally for one URL."""
    statement = select(ServiceCheck)
    if service_url:
        safe_url = safe_service_url(service_url)
        if not safe_url:
            return {"count": 0, "items": []}
        statement = statement.where(ServiceCheck.service_url == safe_url)

    statement = statement.order_by(
        ServiceCheck.timestamp.desc(), ServiceCheck.id.desc()
    ).limit(limit)
    rows = (await db.scalars(statement)).all()

    return {
        "count": len(rows),
        "items": [
            {
                "id": row.id,
                "timestamp": _iso(row.timestamp),
                "service_url": row.service_url,
                "status": (
                    "error" if not row.probe_completed
                    else "online" if row.is_up
                    else "offline"
                ),
                "is_up": row.is_up,
                "probe_completed": row.probe_completed,
                "http_status_code": row.http_status_code,
                "response_time_ms": row.response_time_ms,
                "error_message": row.error_message,
            }
            for row in rows
        ],
    }


@router.get("/service-outages")
async def get_service_outages(
    limit: int = Query(default=10, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent confirmed HTTP service outages and recoveries."""
    statement = (
        select(ServiceOutage)
        .order_by(ServiceOutage.start_time.desc(), ServiceOutage.id.desc())
        .limit(limit)
    )
    rows = (await db.scalars(statement)).all()

    now = datetime.now(timezone.utc)
    items = []
    for row in rows:
        start = row.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = row.end_time
        if end is None and not row.is_resolved:
            duration = max(0, int((now - start).total_seconds()))
        elif end is not None:
            normalized_end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
            duration = row.duration_seconds
            if duration is None:
                duration = max(0, int((normalized_end - start).total_seconds()))
        else:
            duration = row.duration_seconds

        items.append({
            "id": row.id,
            "service_url": row.service_url,
            "start_time": _iso(row.start_time),
            "end_time": _iso(row.end_time),
            "duration_seconds": duration,
            "is_resolved": row.is_resolved,
            "notes": row.notes,
        })

    return {"count": len(items), "items": items}



@router.get("/quality")
async def get_network_quality(
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return the latest multi-packet quality measurements for each target."""
    targets = settings.targets_list
    latest_by_target: dict[str, NetworkQualityCheck] = {}
    if targets:
        statement = (
            select(NetworkQualityCheck)
            .where(NetworkQualityCheck.target.in_(targets))
            .order_by(NetworkQualityCheck.timestamp.desc(), NetworkQualityCheck.id.desc())
            .limit(2000)
        )
        rows = (await db.scalars(statement)).all()
        for row in rows:
            latest_by_target.setdefault(row.target, row)

    items = []
    for target in targets:
        row = latest_by_target.get(target)
        if row is None:
            status = "pending"
        elif not row.probe_completed:
            status = "error"
        else:
            status = "degraded" if row.is_degraded else "healthy"

        items.append({
            "target": target,
            "status": status,
            "timestamp": _iso(row.timestamp) if row else None,
            "probe_completed": row.probe_completed if row else None,
            "packets_sent": row.packets_sent if row else None,
            "packets_received": row.packets_received if row else None,
            "packet_loss_percent": row.packet_loss_percent if row else None,
            "latency_min_ms": row.latency_min_ms if row else None,
            "latency_avg_ms": row.latency_avg_ms if row else None,
            "latency_max_ms": row.latency_max_ms if row else None,
            "latency_jitter_ms": row.latency_jitter_ms if row else None,
            "error_message": row.error_message if row else None,
        })

    return {
        "configured_targets": len(targets),
        "healthy_targets": sum(item["status"] == "healthy" for item in items),
        "degraded_targets": sum(item["status"] == "degraded" for item in items),
        "items": items,
    }


@router.get("/quality/history")
async def get_network_quality_history(
    limit: int = Query(default=100, ge=1, le=1000),
    target: str | None = Query(default=None, max_length=100),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return historical multi-packet quality samples."""
    statement = select(NetworkQualityCheck)
    if target:
        statement = statement.where(NetworkQualityCheck.target == target)
    statement = statement.order_by(
        NetworkQualityCheck.timestamp.desc(), NetworkQualityCheck.id.desc()
    ).limit(limit)
    rows = (await db.scalars(statement)).all()

    return {
        "count": len(rows),
        "items": [
            {
                "id": row.id,
                "timestamp": _iso(row.timestamp),
                "target": row.target,
                "status": (
                    "error" if not row.probe_completed
                    else "degraded" if row.is_degraded
                    else "healthy"
                ),
                "probe_completed": row.probe_completed,
                "packets_sent": row.packets_sent,
                "packets_received": row.packets_received,
                "packet_loss_percent": row.packet_loss_percent,
                "latency_min_ms": row.latency_min_ms,
                "latency_avg_ms": row.latency_avg_ms,
                "latency_max_ms": row.latency_max_ms,
                "latency_jitter_ms": row.latency_jitter_ms,
                "error_message": row.error_message,
            }
            for row in rows
        ],
    }


@router.get("/quality-incidents")
async def get_network_quality_incidents(
    limit: int = Query(default=10, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return recent sustained degradation incidents, with duration so far."""
    statement = (
        select(NetworkQualityIncident)
        .order_by(
            NetworkQualityIncident.start_time.desc(),
            NetworkQualityIncident.id.desc(),
        )
        .limit(limit)
    )
    rows = (await db.scalars(statement)).all()
    now = datetime.now(timezone.utc)
    items = []

    for row in rows:
        start = row.start_time
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        end = row.end_time
        if end is None and not row.is_resolved:
            duration = max(0, int((now - start).total_seconds()))
        elif end is not None:
            normalized_end = end if end.tzinfo else end.replace(tzinfo=timezone.utc)
            duration = row.duration_seconds
            if duration is None:
                duration = max(0, int((normalized_end - start).total_seconds()))
        else:
            duration = row.duration_seconds

        items.append({
            "id": row.id,
            "target": row.target,
            "start_time": _iso(row.start_time),
            "end_time": _iso(row.end_time),
            "duration_seconds": duration,
            "is_resolved": row.is_resolved,
            "peak_packet_loss_percent": row.peak_packet_loss_percent,
            "peak_latency_ms": row.peak_latency_ms,
            "notes": row.notes,
        })

    return {"count": len(items), "items": items}
