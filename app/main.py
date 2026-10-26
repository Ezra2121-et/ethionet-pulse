import logging
import secrets
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.database import Base, engine
from app.monitoring.checker import run_connectivity_checks
from app.monitoring.services import run_service_checks
from app.monitoring.quality import run_network_quality_checks
from app.api.routes import router
from app.api.statistics import router as statistics_router
from app.api.reports import router as reports_router
from app.web import auth_router, web_router, require_authenticated_user

# Importing the models registers their tables with Base.metadata.
import app.models  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Suppress HTTPX request-line logs so URL query strings cannot leak to console logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        await run_connectivity_checks()
    except Exception:
        logger.exception(
            "Initial connectivity check failed; the API will still start."
        )

    try:
        await run_service_checks()
    except Exception:
        logger.exception(
            "Initial HTTP service check failed; the API will still start."
        )

    try:
        await run_network_quality_checks()
    except Exception:
        logger.exception(
            "Initial network quality check failed; the API will still start."
        )

    scheduler = AsyncIOScheduler(timezone="UTC")
    scheduler.add_job(
        run_connectivity_checks,
        trigger="interval",
        seconds=max(5, settings.CHECK_INTERVAL_SECONDS),
        id="connectivity_checks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_service_checks,
        trigger="interval",
        seconds=max(5, settings.CHECK_INTERVAL_SECONDS),
        id="http_service_checks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        run_network_quality_checks,
        trigger="interval",
        seconds=max(5, settings.CHECK_INTERVAL_SECONDS),
        id="network_quality_checks",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    app.state.scheduler = scheduler

    logger.info("%s is starting.", settings.APP_NAME)

    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        await engine.dispose()
        logger.info("%s has stopped.", settings.APP_NAME)


app = FastAPI(
    title=settings.APP_NAME,
    description="Network connectivity and outage monitoring.",
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Set SESSION_SECRET_KEY in .env to keep signed sessions stable across restarts.
# A random development-only fallback avoids using an insecure hard-coded secret.
session_secret = settings.SESSION_SECRET_KEY.strip() or secrets.token_urlsafe(32)
if not settings.SESSION_SECRET_KEY.strip():
    logger.warning(
        "SESSION_SECRET_KEY is not set; sessions will expire after a server restart. "
        "Set a long random value in .env before deployment."
    )

app.add_middleware(
    SessionMiddleware,
    secret_key=session_secret,
    session_cookie="ethionet_pulse_session",
    max_age=12 * 60 * 60,
    same_site="lax",
    https_only=settings.SESSION_COOKIE_SECURE,
)

app.mount(
    "/static",
    StaticFiles(directory=str(APP_DIR / "static")),
    name="static",
)
app.include_router(auth_router)
app.include_router(web_router)

# Every monitoring API requires a valid signed-in session.
app.include_router(router, dependencies=[Depends(require_authenticated_user)])
app.include_router(
    statistics_router, dependencies=[Depends(require_authenticated_user)]
)
app.include_router(reports_router, dependencies=[Depends(require_authenticated_user)])


@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "application": settings.APP_NAME,
    }
