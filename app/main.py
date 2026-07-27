from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import make_asgi_app
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.audit import router as audit_router
from app.api.health import router as health_router
from app.api.intake import router as intake_router
from app.api.remediation import router as remediation_router
from app.api.slack import router as slack_router
from app.api.teams import router as teams_router
from app.connectors.registry import ConnectorRegistry
from app.core.config import settings
from app.core.exceptions import AppError
from app.core.logging import logger_adapter, setup_logging
from app.core.middleware import RequestIDMiddleware
from app.db.redis import redis_manager
from app.policy.store import PolicyStore
from app.remediation.playbook import PlaybookRegistry
from app.schemas.errors import ErrorBody, ErrorResponse


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    setup_logging()

    # Fail-fast: a broken policy file must never let the app start.
    app.state.policy_store = PolicyStore(Path(settings.POLICY_DIR))
    logger_adapter.info(
        "Policy store loaded", system_count=len(app.state.policy_store.all())
    )

    app.state.connector_registry = ConnectorRegistry()
    app.state.playbook_registry = PlaybookRegistry()  

    await redis_manager.connect()
    logger_adapter.info("Redis connected")

    logger_adapter.info("Access Troubleshooting Agent starting", environment=settings.ENV)
    yield

    await redis_manager.close()
    logger_adapter.info("Access Troubleshooting Agent shutting down")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=settings.DESCRIPTION,
    version=settings.VERSION,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=settings.CORS_ALLOW_METHODS,
    allow_headers=settings.CORS_ALLOW_HEADERS,
)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    logger_adapter.warning(
        "Handled application error",
        error_code=exc.error_code,
        error_message=exc.message,
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorBody(code=exc.error_code, message=exc.message)
        ).model_dump(),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(
            error=ErrorBody(code="VALIDATION_ERROR", message="Invalid request data")
        ).model_dump(),
    )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(
    request: Request, exc: StarletteHTTPException
) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=ErrorBody(code="HTTP_ERROR", message=str(exc.detail))
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger_adapter.error(
        "Unhandled exception",
        error=str(exc),
        error_type=type(exc).__name__,
        path=request.url.path,
        request_id=getattr(request.state, "request_id", None),
    )
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorBody(code="INTERNAL_ERROR", message="An unexpected error occurred")
        ).model_dump(),
    )


if settings.ENABLE_METRICS:
    app.mount("/metrics", make_asgi_app())

app.include_router(health_router)
app.include_router(intake_router)
# app.include_router(slack_router)
# app.include_router(teams_router)
app.include_router(remediation_router)
app.include_router(audit_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "status": "running",
        "docs": "/docs",
    }


if __name__ == "__main__":
    uvicorn.run("app.main:app", host=settings.HOST, port=settings.PORT, reload=True)
