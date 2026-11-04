"""Tec Tha Care Connect: FastAPI application entry point.

Run:  uvicorn app.main:app --reload
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config, db, scheduler, security
from app.routes import api, patient_app, ui, webhooks

HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    if config.settings.scheduler_enabled:
        scheduler.start(config.settings.scheduler_interval_seconds)
    yield
    scheduler.stop()


# The API explorer lists every endpoint and field: only on a developer machine (TT_ENV=dev).
_dev = os.environ.get("TT_ENV", "") == "dev"
app = FastAPI(title="Tec Tha Care Connect", lifespan=lifespan,
              docs_url="/docs" if _dev else None, redoc_url="/redoc" if _dev else None,
              openapi_url="/openapi.json" if _dev else None)
app.add_middleware(security.SecurityHeaders)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.include_router(ui.router)
app.include_router(api.router, prefix="/api")
app.include_router(webhooks.router, prefix="/webhooks")
app.include_router(patient_app.router, prefix="/my")
