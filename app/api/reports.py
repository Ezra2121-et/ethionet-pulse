import csv
import io
from datetime import datetime, timedelta, timezone
from statistics import mean

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.statistics import get_statistics
from app.config import settings
from app.database import get_db
from app.models import (
    ConnectivityCheck,
    Outage,
    ServiceCheck,
    ServiceOutage,
    NetworkQualityCheck,
    NetworkQualityIncident,
)
from app.monitoring.urls import safe_service_url

router = APIRouter(prefix="/api/reports", tags=["reports"])
UTC = timezone.utc


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def utc_iso(value):
    if value is None:
        return ""
    return as_utc(value).isoformat()


def iso_or_none(value):
    return as_utc(value).isoformat() if value is not None else None


def safe_text(value):
    """Prevent spreadsheet formula execution from untrusted text fields."""
    text = "" if value is None else str(value)
    if text.startswith(("=", "+", "-", "@", "\t", "\r")):
        return "'" + text
    return text


def overlap_duration(start_time, end_time, window_start, window_end):
    start = as_utc(start_time)
    end = as_utc(end_time) if end_time else as_utc(window_end)
    overlap_start = max(start, as_utc(window_start))
    overlap_end = min(end, as_utc(window_end))
    return max(0, int((overlap_end - overlap_start).total_seconds()))


@router.get("/csv")
async def export_csv(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    """Export network checks, service checks, quality samples, and incidents."""
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)

    checks = (await db.scalars(
        select(ConnectivityCheck)
        .where(ConnectivityCheck.timestamp >= start, ConnectivityCheck.timestamp <= now)
        .order_by(ConnectivityCheck.timestamp.asc())
    )).all()

    outages = (await db.scalars(
        select(Outage)
        .where(
            Outage.start_time <= now,
            or_(Outage.end_time.is_(None), Outage.end_time >= start),
        )
        .order_by(Outage.start_time.asc())
    )).all()

    service_checks = (await db.scalars(
        select(ServiceCheck)
        .where(ServiceCheck.timestamp >= start, ServiceCheck.timestamp <= now)
        .order_by(ServiceCheck.timestamp.asc())
    )).all()

    service_outages = (await db.scalars(
        select(ServiceOutage)
        .where(
            ServiceOutage.start_time <= now,
            or_(ServiceOutage.end_time.is_(None), ServiceOutage.end_time >= start),
        )
        .order_by(ServiceOutage.start_time.asc())
    )).all()

    quality_checks = (await db.scalars(
        select(NetworkQualityCheck)
        .where(NetworkQualityCheck.timestamp >= start, NetworkQualityCheck.timestamp <= now)
        .order_by(NetworkQualityCheck.timestamp.asc())
    )).all()

    quality_incidents = (await db.scalars(
        select(NetworkQualityIncident)
        .where(
            NetworkQualityIncident.start_time <= now,
            or_(NetworkQualityIncident.end_time.is_(None), NetworkQualityIncident.end_time >= start),
        )
        .order_by(NetworkQualityIncident.start_time.asc())
    )).all()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow([
        "record_type", "record_id", "timestamp", "target", "status",
        "latency_ms", "error_message", "outage_type", "start_time",
        "end_time", "duration_seconds", "is_resolved", "notes",
        "packets_sent", "packets_received", "packet_loss_percent",
        "latency_min_ms", "latency_avg_ms", "latency_max_ms",
        "latency_jitter_ms", "http_status_code", "response_time_ms",
    ])

    blank_quality = ["", "", "", "", "", "", ""]
    blank_service = ["", ""]

    for check in checks:
        probe_error = bool(
            check.error_message and check.error_message.startswith("PROBE_ERROR:")
        )
        status = "error" if probe_error else "online" if check.is_up else "offline"
        writer.writerow([
            "connectivity_check", check.id, utc_iso(check.timestamp),
            safe_text(check.target), status,
            check.latency_ms if check.latency_ms is not None else "",
            safe_text(check.error_message), "", "", "", "", "", "",
            *blank_quality, *blank_service,
        ])

    for outage in outages:
        duration = overlap_duration(outage.start_time, outage.end_time, start, now)
        writer.writerow([
            "internet_outage", outage.id, utc_iso(outage.start_time), "",
            "resolved" if outage.is_resolved else "active", "", "",
            safe_text(outage.outage_type), utc_iso(outage.start_time),
            utc_iso(outage.end_time), duration, outage.is_resolved,
            safe_text(outage.notes), *blank_quality, *blank_service,
        ])

    for check in service_checks:
        status = (
            "error" if not check.probe_completed
            else "online" if check.is_up
            else "offline"
        )
        writer.writerow([
            "service_check", check.id, utc_iso(check.timestamp),
            safe_text(check.service_url), status, "", safe_text(check.error_message),
            "", "", "", "", "", "", *blank_quality,
            check.http_status_code if check.http_status_code is not None else "",
            check.response_time_ms if check.response_time_ms is not None else "",
        ])

    for outage in service_outages:
        duration = overlap_duration(outage.start_time, outage.end_time, start, now)
        writer.writerow([
            "service_incident", outage.id, utc_iso(outage.start_time),
            safe_text(outage.service_url),
            "resolved" if outage.is_resolved else "active", "", "",
            "service", utc_iso(outage.start_time), utc_iso(outage.end_time),
            duration, outage.is_resolved, safe_text(outage.notes),
            *blank_quality, *blank_service,
        ])

    for check in quality_checks:
        status = (
            "error" if not check.probe_completed
            else "degraded" if check.is_degraded
            else "healthy"
        )
        writer.writerow([
            "quality_check", check.id, utc_iso(check.timestamp),
            safe_text(check.target), status,
            check.latency_avg_ms if check.latency_avg_ms is not None else "",
            safe_text(check.error_message), "", "", "", "", "", "",
            check.packets_sent, check.packets_received,
            check.packet_loss_percent if check.packet_loss_percent is not None else "",
            check.latency_min_ms if check.latency_min_ms is not None else "",
            check.latency_avg_ms if check.latency_avg_ms is not None else "",
            check.latency_max_ms if check.latency_max_ms is not None else "",
            check.latency_jitter_ms if check.latency_jitter_ms is not None else "",
            "", "",
        ])

    for incident in quality_incidents:
        duration = overlap_duration(incident.start_time, incident.end_time, start, now)
        writer.writerow([
            "quality_incident", incident.id, utc_iso(incident.start_time),
            safe_text(incident.target),
            "resolved" if incident.is_resolved else "active",
            incident.peak_latency_ms if incident.peak_latency_ms is not None else "",
            "", "network_quality", utc_iso(incident.start_time),
            utc_iso(incident.end_time), duration, incident.is_resolved,
            safe_text(incident.notes), "", "", 
            incident.peak_packet_loss_percent if incident.peak_packet_loss_percent is not None else "",
            "", incident.peak_latency_ms if incident.peak_latency_ms is not None else "",
            "", "", "", "",
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


@router.get("/reliability")
async def reliability_report(
    hours: int = Query(default=24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Return a compact evidence-based JSON reliability report for a time window."""
    now = datetime.now(UTC)
    start = now - timedelta(hours=hours)

    network = await get_statistics(hours=hours, db=db)

    service_checks = (await db.scalars(
        select(ServiceCheck)
        .where(ServiceCheck.timestamp >= start, ServiceCheck.timestamp <= now)
        .order_by(ServiceCheck.timestamp.asc(), ServiceCheck.id.asc())
    )).all()

    configured_services = []
    for raw_url in settings.service_urls_list:
        url = safe_service_url(raw_url)
        if url and url not in configured_services:
            configured_services.append(url)

    service_summaries = []
    for service_url in configured_services:
        samples = [row for row in service_checks if row.service_url == service_url]
        successful = sum(1 for row in samples if row.probe_completed and row.is_up)
        failed = sum(1 for row in samples if row.probe_completed and not row.is_up)
        response_times = [
            row.response_time_ms for row in samples if row.response_time_ms is not None
        ]
        latest = samples[-1] if samples else None
        service_summaries.append({
            "service_url": service_url,
            "sample_count": len(samples),
            "successful_checks": successful,
            "failed_checks": failed,
            "success_rate_percentage": (
                round(100 * successful / (successful + failed), 2)
                if successful + failed else None
            ),
            "average_response_time_ms": round(mean(response_times), 2) if response_times else None,
            "last_status": (
                "not_checked" if latest is None
                else "error" if not latest.probe_completed
                else "online" if latest.is_up
                else "offline"
            ),
            "last_checked": iso_or_none(latest.timestamp) if latest else None,
        })

    service_incidents = (await db.scalars(
        select(ServiceOutage).where(
            ServiceOutage.start_time <= now,
            or_(ServiceOutage.end_time.is_(None), ServiceOutage.end_time >= start),
        )
    )).all()
    service_incident_summary = {
        "count": len(service_incidents),
        "active_count": sum(not row.is_resolved for row in service_incidents),
        "overlap_duration_seconds": sum(
            overlap_duration(row.start_time, row.end_time, start, now)
            for row in service_incidents
        ),
    }

    quality_checks = (await db.scalars(
        select(NetworkQualityCheck)
        .where(NetworkQualityCheck.timestamp >= start, NetworkQualityCheck.timestamp <= now)
        .order_by(NetworkQualityCheck.timestamp.asc(), NetworkQualityCheck.id.asc())
    )).all()

    quality_summaries = []
    for target in settings.targets_list:
        samples = [row for row in quality_checks if row.target == target]
        valid = [row for row in samples if row.probe_completed]
        losses = [row.packet_loss_percent for row in valid if row.packet_loss_percent is not None]
        latencies = [row.latency_avg_ms for row in valid if row.latency_avg_ms is not None]
        latest = samples[-1] if samples else None
        quality_summaries.append({
            "target": target,
            "sample_count": len(samples),
            "completed_samples": len(valid),
            "degraded_samples": sum(1 for row in valid if row.is_degraded),
            "average_packet_loss_percent": round(mean(losses), 2) if losses else None,
            "average_latency_ms": round(mean(latencies), 2) if latencies else None,
            "last_status": (
                "not_checked" if latest is None
                else "error" if not latest.probe_completed
                else "degraded" if latest.is_degraded
                else "healthy"
            ),
            "last_checked": iso_or_none(latest.timestamp) if latest else None,
        })

    quality_incidents = (await db.scalars(
        select(NetworkQualityIncident).where(
            NetworkQualityIncident.start_time <= now,
            or_(NetworkQualityIncident.end_time.is_(None), NetworkQualityIncident.end_time >= start),
        )
    )).all()
    quality_incident_summary = {
        "count": len(quality_incidents),
        "active_count": sum(not row.is_resolved for row in quality_incidents),
        "overlap_duration_seconds": sum(
            overlap_duration(row.start_time, row.end_time, start, now)
            for row in quality_incidents
        ),
    }

    return {
        "generated_at": now.isoformat(),
        "window_hours": hours,
        "window_start": start.isoformat(),
        "window_end": now.isoformat(),
        "network": network,
        "services": {
            "configured_count": len(configured_services),
            "sample_count": len(service_checks),
            "incidents": service_incident_summary,
            "items": service_summaries,
        },
        "network_quality": {
            "sample_count": len(quality_checks),
            "incidents": quality_incident_summary,
            "items": quality_summaries,
            "note": "ICMP loss and latency are indicators; some networks and destinations filter ICMP.",
        },
    }
