import logging
from contextlib import asynccontextmanager
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.database import Base, engine
from app.monitoring.checker import run_connectivity_checks
from app.api.routes import router
from app.api.statistics import router as statistics_router

# Importing the models registers their tables with Base.metadata.
import app.models  # noqa: F401

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

APP_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(APP_DIR / "templates"))


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

app.mount(
    "/static",
    StaticFiles(directory=str(APP_DIR / "static")),
    name="static",
)
app.include_router(router)
app.include_router(statistics_router)


@app.get("/", include_in_schema=False)
async def dashboard(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="index.html",
        context={"app_name": settings.APP_NAME},
    )


@app.get("/health", tags=["system"])
async def health():
    return {
        "status": "ok",
        "application": settings.APP_NAME,
    }
