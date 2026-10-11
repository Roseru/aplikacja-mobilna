"""Explicit component factory. Never imported or exported by production code."""

from uuid import uuid4

from fastapi import FastAPI

from calorie_app.core.errors import install_error_handlers
from calorie_app.modules.nemesis.router import router


def component_app(engine, verifier, projection_initializer=None):
    app = FastAPI(title="Private E8.3 component probe")
    app.state.engine = engine
    app.state.oidc_verifier = verifier
    app.state.nemesis_projection_initializer = projection_initializer

    @app.middleware("http")
    async def private_request_context(request, call_next):
        request.state.request_id = str(uuid4())
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    install_error_handlers(app)
    app.include_router(router)
    return app
