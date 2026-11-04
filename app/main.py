"""Tec Tha Care Connect: FastAPI application entry point.

Run:  uvicorn app.main:app --reload
"""
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app import config, db, scheduler
from app.routes import api, ui, webhooks

HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    if config.settings.scheduler_enabled:
        scheduler.start(config.settings.scheduler_interval_seconds)
    yield
    scheduler.stop()


app = FastAPI(title="Tec Tha Care Connect", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.include_router(ui.router)
app.include_router(api.router, prefix="/api")
app.include_router(webhooks.router, prefix="/webhooks")
