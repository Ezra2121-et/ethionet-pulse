from sqlalchemy import Column, Integer, String, DateTime, Boolean, Float, Text
from sqlalchemy.sql import func
from app.database import Base


class Outage(Base):
    """Stores every detected outage"""
    __tablename__ = "outages"

    id = Column(Integer, primary_key=True, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    outage_type = Column(String(50), nullable=False)  # internet / local / power
    is_resolved = Column(Boolean, default=False)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ConnectivityCheck(Base):
    """Stores individual connectivity checks (for history and graphs later)"""
    __tablename__ = "connectivity_checks"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now())
    target = Column(String(100), nullable=False)
    is_up = Column(Boolean, nullable=False)
    latency_ms = Column(Float, nullable=True)
    error_message = Column(String(255), nullable=True)



class ServiceCheck(Base):
    """Stores a scheduled HTTP(S) service probe without URL secrets."""
    __tablename__ = "service_checks"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    service_url = Column(String(512), nullable=False, index=True)
    is_up = Column(Boolean, nullable=False)
    probe_completed = Column(Boolean, nullable=False, default=True)
    http_status_code = Column(Integer, nullable=True)
    response_time_ms = Column(Float, nullable=True)
    error_message = Column(String(255), nullable=True)


class ServiceOutage(Base):
    """Stores confirmed outage transitions for an individual HTTP service."""
    __tablename__ = "service_outages"

    id = Column(Integer, primary_key=True, index=True)
    service_url = Column(String(512), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    is_resolved = Column(Boolean, nullable=False, default=False, index=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NetworkQualityCheck(Base):
    """Stores multi-packet measurements used to estimate network quality."""
    __tablename__ = "network_quality_checks"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    target = Column(String(100), nullable=False, index=True)
    probe_completed = Column(Boolean, nullable=False)
    packets_sent = Column(Integer, nullable=False)
    packets_received = Column(Integer, nullable=False)
    packet_loss_percent = Column(Float, nullable=True)
    latency_min_ms = Column(Float, nullable=True)
    latency_avg_ms = Column(Float, nullable=True)
    latency_max_ms = Column(Float, nullable=True)
    latency_jitter_ms = Column(Float, nullable=True)
    is_degraded = Column(Boolean, nullable=True)
    error_message = Column(String(255), nullable=True)


class NetworkQualityIncident(Base):
    """Stores sustained network quality degradation and recovery events."""
    __tablename__ = "network_quality_incidents"

    id = Column(Integer, primary_key=True, index=True)
    target = Column(String(100), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    is_resolved = Column(Boolean, nullable=False, default=False, index=True)
    peak_packet_loss_percent = Column(Float, nullable=True)
    peak_latency_ms = Column(Float, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class User(Base):
    """Account used to access the shared EthioNet Pulse monitoring workspace."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), nullable=False, unique=True, index=True)
    display_name = Column(String(120), nullable=False, default="")
    password_hash = Column(String(512), nullable=True)
    google_sub = Column(String(255), nullable=True, unique=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
