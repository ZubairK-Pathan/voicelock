"""
app/main.py — FastAPI application factory and entry point.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from app.api import api_router
from app.services.speaker_service import get_system
from app.core.config import load_allowed_cors_origins
from app.core.middleware import RequestSizeLimiterMiddleware, PayloadTooLargeError


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Pre-warm ML models and voiceprint profiles at startup."""
    import logging
    logger = logging.getLogger("uvicorn.error")
    # Pre-warm ML embedding model singleton
    from app.services.speaker_service import get_classifier
    get_classifier()
    # Attempt to pre-warm speaker profiles if database is initialized and accessible
    try:
        get_system()
        logger.info("VoiceLock speaker profiles pre-warmed successfully from database.")
    except Exception as exc:
        logger.warning("VoiceLock initial database profile pre-warm deferred: %s", exc)
    yield


def create_app() -> FastAPI:
    """Create and configure the VoiceLock FastAPI application instance."""
    app = FastAPI(
        title="VoiceLock — Enterprise Speaker Recognition API",
        description="High-security speaker recognition and stateful anti-spoofing challenge-response verification.",
        version="1.0.0",
        lifespan=lifespan,
    )

    # 1. Hardened CORS configuration (rejects wildcard '*' with credentials)
    cors_origins = load_allowed_cors_origins()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
        allow_headers=[
            "Authorization",
            "Content-Type",
            "X-Device-ID",
            "X-Device-Key",
            "X-Device-Timestamp",
            "X-Device-Nonce",
            "X-Device-Signature",
        ],
    )

    # 2. ASGI Request Body Size Limiter (terminates oversized bodies prior to multipart parsing)
    app.add_middleware(RequestSizeLimiterMiddleware)

    @app.exception_handler(PayloadTooLargeError)
    async def payload_too_large_exception_handler(request: Request, exc: PayloadTooLargeError):
        return JSONResponse(
            status_code=413,
            content={"detail": f"Payload too large. Streaming body size exceeded limit of {exc.limit_bytes} bytes."},
        )

    # Register aggregate API routes
    app.include_router(api_router)

    return app


app = create_app()
