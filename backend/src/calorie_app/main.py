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
from calorie_app.integrations.keycloak import OIDCVerifier
from calorie_app.modules.ai.router import router as ai_router
from calorie_app.modules.analytics.motivation.router import router as motivation_router
from calorie_app.modules.analytics.router import router as analytics_router
from calorie_app.modules.catalog.community.feedback_router import router as feedback_router
from calorie_app.modules.catalog.community.router import router as community_router
from calorie_app.modules.catalog.community.transport import E6BodyMiddleware
from calorie_app.modules.catalog.moderation.router import router as moderation_router
from calorie_app.modules.catalog.protected_router import router as protected_catalog_router
from calorie_app.modules.catalog.router import router as catalog_router
from calorie_app.modules.diary.read_router import router as diary_read_router
from calorie_app.modules.identity.router import router as identity_router
from calorie_app.modules.profiles.router import router as profile_router
from calorie_app.modules.sync.router import router as sync_router


def create_app(settings: Settings | None = None, *, engine=None) -> FastAPI:
    settings = settings or Settings()
    db_engine = engine if engine is not None else make_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        configure_logging()
        # No network or DDL at startup: liveness still works during a DB outage.
        yield
        await app.state.oidc_verifier.close()
        if engine is None:
            db_engine.dispose()

    app = FastAPI(title="Wojskowy licznik kalorii", version=__version__, lifespan=lifespan)
    app.state.engine = db_engine
    app.state.settings = settings
    app.state.session_factory = session_factory(db_engine)
    app.state.catalog_artifact_root = settings.catalog_artifact_root
    app.state.catalog_page_token_secret = settings.catalog_page_token_secret
    app.state.oidc_verifier = OIDCVerifier(settings)

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
        # Include errors raised before the router, e.g. OIDC and validation.
        if request.url.path.startswith("/api/v1/"):
            response.headers["Cache-Control"] = "no-store"
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
    app.include_router(identity_router)
    app.include_router(profile_router)
    app.include_router(protected_catalog_router)
    app.include_router(sync_router)
    app.include_router(diary_read_router)
    app.include_router(analytics_router)
    app.include_router(motivation_router)
    app.include_router(community_router)
    app.include_router(feedback_router)
    app.include_router(moderation_router)
    app.include_router(ai_router)
    original_openapi = app.openapi

    def openapi_with_photo_parts():
        # The memory-only multipart and JSON routers deliberately avoid FastAPI's
        # spool/body parser. Their DTOs still belong to the same normative API.
        from calorie_app.modules.ai.result import ProviderFoodResult
        from calorie_app.modules.ai.schemas import CancelRequest, ConfirmRequest, CreateMetadata
        from calorie_app.modules.analytics.motivation.schemas import RankingQuery

        schema = original_openapi()
        components = schema["components"]["schemas"]
        for model in (
            CreateMetadata,
            ConfirmRequest,
            CancelRequest,
            ProviderFoodResult,
            RankingQuery,
        ):
            definition = model.model_json_schema(ref_template="#/components/schemas/{model}")
            for name, value in definition.pop("$defs", {}).items():
                components.setdefault(name, value)
            components[model.__name__] = definition
        return schema

    app.openapi = openapi_with_photo_parts
    app.add_middleware(E6BodyMiddleware)
    return app
