import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", hide_input_in_errors=True)

    database_url: SecretStr
    db_connect_timeout: int = 2
    db_statement_timeout_ms: int = 2000
    db_pool_size: int = 5
    db_max_overflow: int = 5
    catalog_artifact_root: Path = Path("var/catalog")
    catalog_page_token_secret: SecretStr | None = None
    environment: Literal["production", "development", "test"] = "production"
    oidc_issuer: str | None = None
    oidc_jwks_url: str | None = None
    oidc_allow_local_http: bool = False
    oidc_jwks_cache_seconds: int = Field(default=900, ge=1, le=900)
    oidc_jwks_refresh_cooldown_seconds: int = Field(default=5, ge=1, le=60)
    oidc_jwks_timeout_seconds: float = Field(default=3, gt=0, le=10)

    @model_validator(mode="after")
    def trusted_oidc(self):
        if bool(self.oidc_issuer) != bool(self.oidc_jwks_url):
            raise ValueError("OIDC_ISSUER and OIDC_JWKS_URL must be configured together")
        if self.oidc_allow_local_http and self.environment == "production":
            raise ValueError("Local OIDC HTTP is forbidden in production")
        for value in (self.oidc_issuer, self.oidc_jwks_url):
            if value is None:
                continue
            try:
                parsed = urlsplit(value)
                port = parsed.port
            except ValueError:
                raise ValueError("OIDC URLs must be well-formed trusted URLs") from None
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or "*" in value
                or "\\" in value
                or port == 0
                or any(char.isspace() for char in value)
            ):
                raise ValueError("OIDC URLs must be exact trusted URLs")
            if parsed.scheme != "https" and not (
                parsed.scheme == "http"
                and self.oidc_allow_local_http
                and self.environment in {"development", "test"}
                and parsed.hostname in {"localhost", "127.0.0.1", "::1"}
            ):
                raise ValueError("OIDC requires HTTPS (explicit isolated loopback test exception)")
        return self

    @field_validator("catalog_page_token_secret")
    @classmethod
    def cursor_secret(cls, value: SecretStr | None) -> SecretStr | None:
        if value is not None and re.fullmatch(r"[0-9a-f]{64}", value.get_secret_value()) is None:
            raise ValueError(
                "CATALOG_PAGE_TOKEN_SECRET must be 32 random bytes as 64 lowercase hex digits"
            )
        return value

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
