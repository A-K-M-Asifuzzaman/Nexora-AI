from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.api.v1.router import router as api_v1_router
from app.core.config import Settings, get_settings
from app.core.context import is_valid_request_id, request_id_var, tenant_context_var
from app.core.errors import install_exception_handlers
from app.core.ids import uuid7
from app.core.logging import configure_logging
from app.core.redis import create_redis_client
from app.db.base import import_all_models
from app.db.session import create_engine, create_session_factory
from app.modules.platform.router import router as platform_router


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        supplied_id = request.headers.get("X-Request-ID")
        request_id = (
            supplied_id if supplied_id and is_valid_request_id(supplied_id) else str(uuid7())
        )
        request_token = request_id_var.set(request_id)
        tenant_token = tenant_context_var.set(None)
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            return response
        finally:
            tenant_context_var.reset(tenant_token)
            request_id_var.reset(request_token)


def create_app(settings: Settings | None = None) -> FastAPI:
    # Register every mapped model before the first request. Without this the
    # metadata holds only whatever modules a request happened to import, and a
    # cross-module foreign key cannot resolve: recording a customer payment
    # raised NoReferencedTableError for `supplier_bills`, because
    # payment_allocations references both invoices and supplier_bills while
    # nothing had imported the purchasing models. Alembic and the tests already
    # call this; the running application did not.
    import_all_models()

    application_settings = settings or get_settings()
    configure_logging(
        application_settings.log_level,
        console=application_settings.log_format == "console",
    )
    engine = create_engine(application_settings)
    session_factory = create_session_factory(engine)
    redis = create_redis_client(application_settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await redis.aclose()  # type: ignore[attr-defined]  # stale third-party stubs lack redis-py 5+
        await engine.dispose()

    app = FastAPI(
        title=application_settings.app_name,
        debug=application_settings.debug,
        openapi_url=(
            f"{application_settings.api_v1_prefix}/openapi.json"
            if application_settings.environment == "development"
            else None
        ),
        docs_url=(
            f"{application_settings.api_v1_prefix}/docs"
            if application_settings.environment == "development"
            else None
        ),
        lifespan=lifespan,
    )
    app.state.settings = application_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.state.redis = redis
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=application_settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID", "X-CSRF-Token"],
    )
    install_exception_handlers(app)
    app.include_router(platform_router)
    app.include_router(api_v1_router, prefix=application_settings.api_v1_prefix)
    return app


app = create_app()
