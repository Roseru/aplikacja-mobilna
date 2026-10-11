"""Explicit component factory. Never imported or exported by production code."""

from fastapi import FastAPI

from calorie_app.core.errors import install_error_handlers
from calorie_app.modules.nemesis.router import router


def component_app(engine, verifier, projection_initializer=None):
    app = FastAPI(title="Private E8.3 component probe")
    app.state.engine = engine
    app.state.oidc_verifier = verifier
    app.state.nemesis_projection_initializer = projection_initializer
    install_error_handlers(app)
    app.include_router(router)
    return app
