from pathlib import Path
from typing import AsyncIterator

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.config import settings


# Create the directory needed by a file-based SQLite database.
database_url = make_url(settings.DATABASE_URL)

if (
    database_url.get_backend_name() == "sqlite"
    and database_url.database
    and database_url.database != ":memory:"
):
    Path(database_url.database).expanduser().parent.mkdir(
        parents=True, exist_ok=True
    )

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""


async def get_db() -> AsyncIterator[AsyncSession]:
    """Provide one database session per request."""
    async with AsyncSessionLocal() as session:
        yield session
