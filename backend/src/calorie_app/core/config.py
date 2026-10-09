from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    db_connect_timeout: int = 2
    db_statement_timeout_ms: int = 2000
    db_pool_size: int = 5
    db_max_overflow: int = 5

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            valid = url.drivername == "postgresql+psycopg" and bool(url.database)
        except Exception:
            valid = False
        if not valid:
            raise ValueError("DATABASE_URL must use postgresql+psycopg and name a database")
        return value

    @field_validator("db_connect_timeout", "db_statement_timeout_ms", "db_pool_size")
    @classmethod
    def positive(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("Must be positive")
        return value

    @field_validator("db_max_overflow")
    @classmethod
    def nonnegative(cls, value: int) -> int:
        if value < 0:
            raise ValueError("Must be nonnegative")
        return value
