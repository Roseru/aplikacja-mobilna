"""Explicit local provider configuration; never performs registration or a password reset."""

import argparse
import hashlib
import json
import ssl
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from infra.local.integration import mail_sink
from infra.local.integration.native import HERE, Native, write_json

FORMAT = "calorie-native-provider-profile/v1"
PROFILE = HERE / "provider-registration.json"
PROFILE_STATE = Path("config-generation/provider-profile.json")
FLAGS = {
    "registrationAllowed": True,
    "resetPasswordAllowed": True,
    "verifyEmail": True,
    "registrationEmailAsUsername": True,
    "loginWithEmailAllowed": True,
    "duplicateEmailsAllowed": False,
    "internationalizationEnabled": True,
    "supportedLocales": ["pl", "en"],
    "defaultLocale": "pl",
}
SMTP = {
    "host": "127.0.0.1",
    "from": "noreply@calorie-demo.test",
    "fromDisplayName": "Calorie Native Test",
    "auth": "false",
    "ssl": "false",
    "starttls": "false",
}


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def load_profile(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if (
        set(value) != {"format", "name", "realm", "default_client_role"}
        or value["format"] != FORMAT
    ):
        raise ValueError("Unsupported explicit provider profile")
    if value["name"] != "registration-reset-local" or value["default_client_role"] != {
        "client_id": "calorie-api",
        "role": "user",
    }:
        raise ValueError("Only the basic API user role is permitted")
    realm = value["realm"]
    if set(realm) != set(FLAGS) | {"smtpServer"} or any(
        type(realm[k]) is not type(v) or realm[k] != v for k, v in FLAGS.items()
    ):
        raise ValueError("Unexpected provider flags or locale")
    smtp = realm["smtpServer"]
    if set(smtp) != set(SMTP) | {"port"} or any(smtp[k] != v for k, v in SMTP.items()):
        raise ValueError("Only the declared local SMTP sink is permitted")
    if (
        not isinstance(smtp["port"], str)
        or not smtp["port"].isdigit()
        or not 1024 <= int(smtp["port"]) <= 65535
        or str(int(smtp["port"])) != smtp["port"]
    ):
        raise ValueError("A nonprivileged SMTP port is required")
    return value


def sink_status(state, profile):
    observed = mail_sink.status(state)
    if (
        not observed["running"]
        or observed["host"] != "127.0.0.1"
        or str(observed["smtp_port"]) != profile["realm"]["smtpServer"]["port"]
    ):
        raise ValueError("Qualified running loopback SMTP sink does not match this profile")
    return {
        k: observed[k]
        for k in ("host", "smtp_port", "http_port", "version", "zip_sha256", "exe_sha256")
    }


def app_epoch(stack):
    url = make_url(stack.env("migrate")["DATABASE_URL"])
    if (
        url.host != "127.0.0.1"
        or url.port != stack.config["pg_port"]
        or url.database != "calorie_app"
    ):
        raise ValueError("Epoch read must target this owned native PostgreSQL database")
    engine = create_engine(
        url,
        connect_args={"options": "-c default_transaction_read_only=on"},
        hide_parameters=True,
    )
    try:
        with engine.connect() as connection:
            return str(
                UUID(
                    str(
                        connection.execute(
                            text("SELECT sync_epoch FROM app.installation_state WHERE id=1")
                        ).scalar_one()
                    )
                )
            )
    finally:
        engine.dispose()


def client(stack):
    return httpx.Client(
        verify=ssl.create_default_context(cafile=stack.state / "tls/ca.pem"),
        trust_env=False,
        timeout=15,
        follow_redirects=False,
    )


class Admin:
    def __init__(self, connection, stack):
        self.connection = connection
        self.origin = stack.origin
        credentials = json.loads((stack.state / "credentials.json").read_text())["admin"]
        result = connection.post(
            self.origin + "/realms/master/protocol/openid-connect/token",
            data={"grant_type": "password", "client_id": "admin-cli", **credentials},
        )
        if result.status_code != 200:
            raise RuntimeError("Own provider administrative authentication failed")
        self.headers = {"Authorization": "Bearer " + result.json()["access_token"]}
        self.base = self.origin + "/admin/realms/calorie-dev"

    def request(self, method, path="", *, payload=None, params=None):
        response = self.connection.request(
            method, self.base + path, headers=self.headers, json=payload, params=params
        )
        if response.status_code not in ({200} if method == "GET" else {204}):
            raise RuntimeError("Provider administrative request failed")
        return response.json() if method == "GET" else None

    def get_client(self, name):
        result = self.request("GET", "/clients", params={"clientId": name})
        if len(result) != 1 or result[0].get("clientId") != name:
            raise ValueError("Expected unique configured provider client")
        return result[0]

    def role_graph(self, role):
        pending = [role]
        found = {}
        while pending:
            current = pending.pop()
            if current["id"] in found:
                continue
            if len(found) >= 256:
                raise ValueError("Default role graph exceeds local acceptance bound")
            found[current["id"]] = {
                k: current.get(k) for k in ("id", "name", "clientRole", "containerId", "composite")
            }
            if current.get("composite"):
                pending.extend(
                    self.request(
                        "GET", "/roles-by-id/" + quote(current["id"], safe="") + "/composites"
                    )
                )
        return found

    def snapshot(self):
        realm = self.request("GET")
        if realm["realm"] != "calorie-dev":
            raise ValueError("Only the owned calorie-dev realm may be configured")
        discovery = self.connection.get(
            self.origin + "/realms/calorie-dev/.well-known/openid-configuration"
        )
        jwks = self.connection.get(
            self.origin + "/realms/calorie-dev/protocol/openid-connect/certs"
        )
        if (
            discovery.status_code != 200
            or jwks.status_code != 200
            or discovery.json()["issuer"] != self.origin + "/realms/calorie-dev"
        ):
            raise ValueError("Exact HTTPS provider issuer changed")
        mobile = self.get_client("calorie-android")
        if not (
            mobile.get("publicClient") is True
            and mobile.get("standardFlowEnabled") is True
            and mobile.get("directAccessGrantsEnabled") is False
            and mobile.get("implicitFlowEnabled") is False
            and mobile.get("attributes", {}).get("pkce.code.challenge.method") == "S256"
            and set(mobile.get("redirectUris", []))
            == {"pl.roseru.kalorie:/oauth2redirect", "pl.roseru.kalorie.validation:/oauth2redirect"}
        ):
            raise ValueError("Mobile Code/S256/callback configuration is not qualified")
        if (
            "roles" not in mobile.get("defaultClientScopes", [])
            or "profile"
            not in mobile.get("defaultClientScopes", []) + mobile.get("optionalClientScopes", [])
            or not any(
                mapper.get("protocolMapper") == "oidc-audience-mapper"
                and mapper.get("config", {}).get("included.client.audience") == "calorie-api"
                and mapper.get("config", {}).get("access.token.claim") == "true"
                for mapper in mobile.get("protocolMappers", [])
            )
        ):
            raise ValueError("Mobile profile scope or API audience is not qualified")
        api = self.get_client("calorie-api")
        role = self.request("GET", "/clients/" + quote(api["id"], safe="") + "/roles/user")
        if (
            role.get("name") != "user"
            or role.get("clientRole") is not True
            or role.get("composite") is not False
            or role.get("containerId") != api["id"]
        ):
            raise ValueError("The basic user role must not grant composite privileges")
        role = {k: role[k] for k in ("id", "name", "clientRole", "containerId", "composite")}
        default = realm["defaultRole"]
        graph = self.role_graph(default)
        management = self.get_client("realm-management")
        if any(
            r["clientRole"]
            and r["containerId"] == management["id"]
            or r["name"] in {"admin", "catalog_moderator", "realm-admin"}
            for r in graph.values()
        ):
            raise ValueError("Default role must not grant provider or application administration")
        if any(
            r["name"] != "user"
            for r in graph.values()
            if r["clientRole"] and r["containerId"] == api["id"]
        ):
            raise ValueError("Default role grants elevated API privileges")
        users = []
        for first in range(0, 10000, 100):
            page = self.request("GET", "/users", params={"first": first, "max": 100})
            users.extend(user["id"] for user in page)
            if len(page) < 100:
                break
        else:
            raise ValueError("Provider user count exceeds local acceptance bound")
        selected = {
            k: mobile.get(k)
            for k in (
                "id",
                "clientId",
                "enabled",
                "protocol",
                "publicClient",
                "standardFlowEnabled",
                "implicitFlowEnabled",
                "directAccessGrantsEnabled",
                "serviceAccountsEnabled",
                "redirectUris",
                "webOrigins",
                "attributes",
                "defaultClientScopes",
                "optionalClientScopes",
                "protocolMappers",
            )
        }
        settings = {k: realm.get(k) for k in FLAGS}
        settings["smtpServer"] = realm.get("smtpServer", {})
        # Exclude arbitrary SMTP fields/passwords from every persisted observation.
        settings["smtpServer"] = {k: settings["smtpServer"].get(k) for k in (*SMTP, "port")}
        observed = {
            "realm_id": realm["id"],
            "realm": realm["realm"],
            "issuer": discovery.json()["issuer"],
            "settings": settings,
            "mobile_sha256": digest(selected),
            "jwks_sha256": digest(sorted(jwks.json()["keys"], key=lambda k: k["kid"])),
            "user_ids": sorted(users),
            "default_role_id": default["id"],
            "roles": graph,
            "user_role": role,
        }
        if len(json.dumps(observed).encode()) > 12000:
            raise ValueError("Provider observation exceeds the local configuration-record bound")
        return observed


def invariant(before, after, *, new_users=False):
    for key in ("realm_id", "realm", "issuer", "mobile_sha256", "jwks_sha256", "default_role_id"):
        if before[key] != after[key]:
            raise ValueError("Provider identity, keys or mobile configuration changed")
    if not (
        set(before["user_ids"]) <= set(after["user_ids"])
        if new_users
        else before["user_ids"] == after["user_ids"]
    ):
        raise ValueError("Existing provider identities changed")


def settings_match(actual, expected):
    actual = dict(actual)
    expected = dict(expected)
    actual["supportedLocales"] = sorted(actual.get("supportedLocales") or [])
    expected["supportedLocales"] = sorted(expected.get("supportedLocales") or [])
    return actual == expected


def roles_match(before, after):
    expected = {key: dict(value) for key, value in before["roles"].items()}
    expected[before["default_role_id"]]["composite"] = True
    expected[before["user_role"]["id"]] = dict(before["user_role"])
    return after["roles"] == expected


def configure(state, mail_state, *, opt_in=False, profile_path=PROFILE):
    if opt_in is not True:
        raise ValueError("Explicit opt-in registration/reset is required")
    profile = load_profile(profile_path)
    stack = Native(state)
    with stack.operation():
        binding = stack.require_running()
        sink = sink_status(mail_state, profile)
        report = {
            "format": FORMAT,
            "generation": str(uuid4()),
            "result": "FAIL",
            "profile_sha256": digest(profile),
            "expected": profile,
            "mail_state": str(Path(mail_state).absolute()),
            "sink": sink,
            "steps": [],
            "wf01_acceptance": "NOT_RUN",
            "at": datetime.now(UTC).isoformat(),
        }
        try:
            with client(stack) as connection:
                admin = Admin(connection, stack)
                before = admin.snapshot()
                epoch = app_epoch(stack)
                report["before"] = before
                report["app_epoch"] = epoch
                role = before["user_role"]
                if role["id"] not in before["roles"]:
                    report["steps"].append(
                        {"operation": "add_default_basic_user_role", "state": "attempted"}
                    )
                    admin.request(
                        "POST",
                        "/roles-by-id/" + quote(before["default_role_id"], safe="") + "/composites",
                        payload=[role],
                    )
                    report["steps"][-1]["state"] = "acknowledged"
                report["steps"].append(
                    {"operation": "apply_explicit_realm_fields", "state": "attempted"}
                )
                admin.request("PUT", payload=profile["realm"])
                report["steps"][-1]["state"] = "acknowledged"
                after = admin.snapshot()
                report["after"] = after
                invariant(before, after)
                if (
                    app_epoch(stack) != epoch
                    or not settings_match(after["settings"], profile["realm"])
                    or not roles_match(before, after)
                ):
                    raise ValueError(
                        "Provider profile readback or preserved application epoch differs"
                    )
                if sink_status(mail_state, profile) != sink:
                    raise ValueError("Qualified mail sink changed during configuration")
                report["result"] = "CONFIGURED"
        except Exception as error:
            report["error_type"] = type(error).__name__
            report["result"] = "PARTIAL" if report["steps"] else "FAIL"
        # Confirm existing process/source binding before changing its configuration generation.
        current = None
        try:
            verified = stack.require_running()
            if verified != binding:
                raise ValueError("Native generation changed while configuring the provider")
            current = verified
        except Exception as error:
            report["binding_error_type"] = type(error).__name__
            report["result"] = "PARTIAL" if report["steps"] else "FAIL"
        report["binding_verified"] = current is not None
        directory = stack.state / "config-generation"
        directory.mkdir(exist_ok=True)
        write_json(directory / (report["generation"] + ".json"), report)
        if not report["steps"]:
            return {
                "result": report["result"],
                "generation": report["generation"],
                "profile_sha256": report["profile_sha256"],
                "wf01_acceptance": "NOT_RUN",
            }
        write_json(stack.state / PROFILE_STATE, report)
        if current is not None:
            current["configuration"] = stack.configuration_binding()
            current["generation"] = str(uuid4())
            write_json(stack.state / "runtime-binding.json", current)
        return {
            "result": report["result"],
            "generation": report["generation"],
            "profile_sha256": report["profile_sha256"],
            "wf01_acceptance": "NOT_RUN",
        }


def status(state):
    stack = Native(state)
    with stack.operation():
        stack.require_running()
        saved = stack.state / PROFILE_STATE
        record = json.loads(saved.read_text()) if saved.exists() else None
        with client(stack) as connection:
            observed = Admin(connection, stack).snapshot()
        if record is None:
            closed = (
                not observed["settings"]["registrationAllowed"]
                and not observed["settings"]["resetPasswordAllowed"]
            )
            return {
                "result": "DEFAULT_CLOSED" if closed else "UNTRACKED_DRIFT",
                "wf01_acceptance": "NOT_RUN",
            }
        profile = record["expected"]
        sink = sink_status(Path(record["mail_state"]), profile)
        invariant(record["before"], observed, new_users=True)
        matches = (
            settings_match(observed["settings"], profile["realm"])
            and sink == record["sink"]
            and app_epoch(stack) == record["app_epoch"]
            and roles_match(record["before"], observed)
        )
        return {
            "result": "MATCH" if matches else "DRIFT",
            "configuration_result": record["result"],
            "generation": record["generation"],
            "profile_sha256": record["profile_sha256"],
            "wf01_acceptance": "NOT_RUN",
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("configure", "status"))
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--mail-state", type=Path)
    parser.add_argument("--profile", type=Path, default=PROFILE)
    parser.add_argument("--opt-in-registration-reset", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "configure":
            if args.mail_state is None:
                raise ValueError("Owned qualified mail state is required")
            result = configure(
                args.state,
                args.mail_state,
                opt_in=args.opt_in_registration_reset,
                profile_path=args.profile,
            )
        else:
            result = status(args.state)
        print(json.dumps(result, sort_keys=True))
        return 0 if result["result"] in {"CONFIGURED", "MATCH", "DEFAULT_CLOSED"} else 1
    except Exception as error:  # noqa: BLE001 - no credentials or action links at the CLI boundary.
        print(
            json.dumps(
                {"result": "FAIL", "error_type": type(error).__name__, "wf01_acceptance": "NOT_RUN"}
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
