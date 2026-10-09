from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from calorie_app.core.config import Settings


def make_engine(settings: Settings):
    return create_engine(
        settings.database_url.get_secret_value(),
        pool_pre_ping=True,
        pool_size=settings.db_pool_size,
        max_overflow=settings.db_max_overflow,
        pool_timeout=settings.db_connect_timeout,
        connect_args={
            "connect_timeout": settings.db_connect_timeout,
            "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
        },
        hide_parameters=True,
    )


def session_factory(engine):
    # Callers own the transaction; repositories must not commit behind their back.
    return sessionmaker(bind=engine, expire_on_commit=False)
