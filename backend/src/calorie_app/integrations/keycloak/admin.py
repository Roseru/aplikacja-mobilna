"""Trusted, exact issuer mapping for the operator's Keycloak deletion client.

No URL or subject originates in an HTTP deletion request. Responses are never
logged: even failed token responses can contain confidential information.
"""

from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx
from pydantic import SecretStr


class AdminFailure(Exception):
    def __init__(self, code="identity_provider_unavailable"):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RealmAdminConfig:
    issuer: str
    admin_base_url: str
    realm: str
    client_id: str
    client_secret: SecretStr = field(repr=False)
    allow_local_http: bool = False

    def __post_init__(self):
        if not self.realm or quote(self.realm, safe="") != self.realm:
            raise ValueError("Realm must be one exact URL path segment")
        for value in (self.issuer, self.admin_base_url):
            parsed = urlsplit(value)
            if (
                not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or "\\" in value
                or "*" in value
                or any(char.isspace() for char in value)
                or value.endswith("/")
                or parsed.scheme != "https"
                and not (
                    self.allow_local_http
                    and parsed.scheme == "http"
                    and parsed.hostname == "127.0.0.1"
                )
            ):
                raise ValueError("Admin endpoints must be exact trusted HTTPS URLs")
        if self.issuer != self.admin_base_url + "/realms/" + self.realm:
            raise ValueError("Issuer must match the configured base URL and realm exactly")
        if not self.client_id or not self.client_secret.get_secret_value():
            raise ValueError("A separate confidential service account is required")


class KeycloakAdmin:
    def __init__(self, configurations, *, client=None):
        self.configurations = {entry.issuer: entry for entry in configurations}
        if len(self.configurations) != len(configurations):
            raise ValueError("Duplicate exact issuer mapping")
        self.client = client or httpx.Client(timeout=10, trust_env=False, follow_redirects=False)
        self.owns_client = client is None

    def close(self):
        if self.owns_client:
            self.client.close()

    def delete_and_confirm(self, issuer: str, subject: str) -> None:
        config = self.configurations.get(issuer)
        if config is None:
            raise AdminFailure("identity_provider_unconfigured")
        try:
            # Keycloak's database user id, never username/email or request input.
            if str(UUID(subject)) != subject:
                raise ValueError
        except (TypeError, ValueError):
            raise AdminFailure("identity_provider_invalid_subject") from None
        try:
            token_response = self.client.post(
                config.issuer + "/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": config.client_id,
                    "client_secret": config.client_secret.get_secret_value(),
                },
            )
            if token_response.status_code != 200:
                raise AdminFailure("identity_provider_admin_denied")
            token = token_response.json().get("access_token")
            if not isinstance(token, str) or not token:
                raise AdminFailure()
            headers = {"Authorization": "Bearer " + token}
            users = config.admin_base_url + "/admin/realms/" + config.realm + "/users"
            # This authorized collection probe rules out a wrong/missing realm,
            # unauthenticated gateway 404, or expired/underprivileged token.
            probe = self.client.get(users, params={"max": 1}, headers=headers)
            if probe.status_code != 200 or not isinstance(probe.json(), list):
                raise AdminFailure("identity_provider_admin_denied")
            target = users + "/" + subject
            before = self.client.get(target, headers=headers)
            if before.status_code == 200:
                if before.json().get("id") != subject:
                    raise AdminFailure("identity_provider_target_mismatch")
                removed = self.client.delete(target, headers=headers)
                if removed.status_code not in (204, 404):
                    raise AdminFailure("identity_provider_admin_denied")
            elif before.status_code != 404:
                raise AdminFailure("identity_provider_admin_denied")
            after = self.client.get(target, headers=headers)
            if after.status_code != 404:
                raise AdminFailure("identity_provider_absence_unconfirmed")
        except (httpx.HTTPError, ValueError, TypeError, KeyError):
            raise AdminFailure() from None
