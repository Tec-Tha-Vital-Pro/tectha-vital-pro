"""Tec Tha Vital (Hospital OS): FastAPI application entry point.

Run:  uvicorn app.main:app --reload
"""
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exception_handlers import http_exception_handler
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException

from app import config, db, scheduler, security
from app.routes import api, patient_app, ui, webhooks
from app.routes import command, diagnostics as diagnostics_routes

HERE = Path(__file__).resolve().parent


@asynccontextmanager
async def lifespan(_app: FastAPI):
    db.init_db()
    command.add_optional_nav(_app)   # AI Labs / Account appear once their routes exist
    if config.settings.scheduler_enabled:
        scheduler.start(config.settings.scheduler_interval_seconds)
    yield
    scheduler.stop()


# The API explorer lists every endpoint and field: only on a developer machine (TT_ENV=dev).
_dev = os.environ.get("TT_ENV", "") == "dev"
app = FastAPI(title=f"{config.PRODUCT_NAME} · {config.PRODUCT_TAGLINE}", lifespan=lifespan,
              docs_url="/docs" if _dev else None, redoc_url="/redoc" if _dev else None,
              openapi_url="/openapi.json" if _dev else None)
app.add_middleware(security.SecurityHeaders)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
app.include_router(ui.router)
app.include_router(api.router, prefix="/api")
app.include_router(webhooks.router, prefix="/webhooks")
app.include_router(patient_app.router, prefix="/my")
app.include_router(diagnostics_routes.router)
app.include_router(command.router)


@app.exception_handler(StarletteHTTPException)
async def friendly_not_found(request: Request, exc: StarletteHTTPException):
    """Unknown screens get a proper page with navigation; the API and webhooks keep JSON errors."""
    path = request.url.path
    if exc.status_code == 404 and not path.startswith(("/api", "/webhooks", "/static")):
        if path == "/my" or path.startswith("/my/"):
            return patient_app.not_found_page(request)
        return ui.not_found_page(request)
    return await http_exception_handler(request, exc)
