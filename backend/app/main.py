from decimal import Decimal

from fastapi import FastAPI
from fastapi.encoders import ENCODERS_BY_TYPE
from fastapi.middleware.cors import CORSMiddleware

from app.api import ai, auth, catalog, purchasing, reports, sales
from app.config import get_settings
from app.core.errors import AppError, IdempotentReplay, app_error_handler, replay_handler

# Money must never be serialised as a JSON float. Pydantic models already emit Decimal as strings; this makes
# plain-dict responses (reports, dashboard) and stored idempotent responses do the same.
ENCODERS_BY_TYPE[Decimal] = str


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.environment == "production" and (
        settings.jwt_secret == "change-me-in-production" or len(settings.jwt_secret) < 32
    ):
        raise RuntimeError("Set MSME_JWT_SECRET to a random value of at least 32 characters in production")
    app = FastAPI(
        title="MSME Business Dashboard API",
        version="1.0.0",
        description="Multi-tenant inventory, invoicing, khata, purchasing and reporting for small businesses.",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["Idempotent-Replay"],
    )
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(IdempotentReplay, replay_handler)
    for module in (auth, catalog, sales, purchasing, reports, ai):
        app.include_router(module.router, prefix="/api/v1")

    @app.get("/healthz", tags=["meta"])
    def healthz():
        return {"status": "ok"}

    return app


app = create_app()
