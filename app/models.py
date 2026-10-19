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
