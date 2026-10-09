import logging
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import UUID, uuid4

from fastapi import FastAPI, Request

from calorie_app import __version__
from calorie_app.core.config import Settings
from calorie_app.core.errors import error_response, install_error_handlers
from calorie_app.core.logging import configure_logging
from calorie_app.db.session import make_engine, session_factory
from calorie_app.health import router
from calorie_app.modules.catalog.router import router as catalog_router


def create_app(settings: Settings | None = None, *, engine=None) -> FastAPI:
    settings = settings or Settings()
    db_engine = engine if engine is not None else make_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        # No network or DDL at startup: liveness still works during a DB outage.
        yield
        if engine is None:
            db_engine.dispose()

    app = FastAPI(title="Wojskowy licznik kalorii", version=__version__, lifespan=lifespan)
    app.state.engine = db_engine
    app.state.session_factory = session_factory(db_engine)
    app.state.catalog_artifact_root = settings.catalog_artifact_root

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        started = perf_counter()
        try:
            request_id = str(UUID(request.headers.get("X-Request-ID", "")))
        except ValueError:
            request_id = str(uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            response = error_response(request, 500, "internal_error", "Wewnętrzny błąd serwera.")
        response.headers["X-Request-ID"] = request_id
        logging.getLogger("calorie_app").info(
            "request_complete",
            extra={
                "data": {
                    "request_id": request_id,
                    "method": request.method,
                    "status": response.status_code,
                    "duration_ms": round((perf_counter() - started) * 1000, 2),
                }
            },
        )
        return response

    install_error_handlers(app)
    app.include_router(router)
    app.include_router(catalog_router)
    return app
