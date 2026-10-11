"""Explicitly add the standard optional profile scope to an existing local Android client."""

import argparse
import json
import ssl
from pathlib import Path

import httpx
from run import host_address


def configure(state: Path):
    config = json.loads((state / "config.json").read_text())
    host = host_address(config["host"])
    origin = f"https://{host}:{int(config['port'])}"
    if origin != config["origin"]:
        raise ValueError("Inconsistent local issuer configuration")
    credentials = json.loads((state / "credentials.json").read_text())
    trust = ssl.create_default_context(cafile=state / "tls/ca.pem")
    with httpx.Client(verify=trust, trust_env=False, timeout=15, follow_redirects=False) as client:
        response = client.post(
            origin + "/realms/master/protocol/openid-connect/token",
            data={
                "grant_type": "password",
                "client_id": "admin-cli",
                **credentials["admin"],
            },
        )
        response.raise_for_status()
        headers = {"Authorization": "Bearer " + response.json()["access_token"]}
        base = origin + "/admin/realms/calorie-dev"

        def get(path, **kwargs):
            result = client.get(base + path, headers=headers, **kwargs)
            result.raise_for_status()
            return result.json()

        matches = get("/clients", params={"clientId": "calorie-android"})
        if len(matches) != 1:
            raise ValueError("Expected one local Android client")
        path = "/clients/" + matches[0]["id"]
        before = get(path)
        if not (
            before["publicClient"]
            and before["standardFlowEnabled"]
            and not before["directAccessGrantsEnabled"]
            and not before["implicitFlowEnabled"]
            and before["attributes"]["pkce.code.challenge.method"] == "S256"
            and set(before["redirectUris"])
            == {
                "pl.roseru.kalorie:/oauth2redirect",
                "pl.roseru.kalorie.validation:/oauth2redirect",
            }
        ):
            raise ValueError("Unexpected client security configuration; no mutation performed")
        profiles = [scope for scope in get("/client-scopes") if scope["name"] == "profile"]
        if len(profiles) != 1 or profiles[0]["protocol"] != "openid-connect":
            raise ValueError("Expected the existing built-in OIDC profile scope")
        defaults = get(path + "/default-client-scopes")
        optional = get(path + "/optional-client-scopes")
        scope_id = profiles[0]["id"]
        changed = scope_id not in {scope["id"] for scope in defaults + optional}
        if changed:
            result = client.put(
                base + path + "/optional-client-scopes/" + scope_id, headers=headers
            )
            result.raise_for_status()
        after = get(path)
        # Client representation may expose scope lists; nothing else may change.
        for value in (before, after):
            value.pop("optionalClientScopes", None)
        if after != before:
            raise RuntimeError("Unexpected client change; inspect locally")
        if get(path + "/default-client-scopes") != defaults:
            raise RuntimeError("Default scopes changed unexpectedly")
        final = get(path + "/optional-client-scopes")
        if scope_id not in {scope["id"] for scope in final + defaults}:
            raise RuntimeError("Profile assignment not confirmed")
    return {"client": "calorie-android", "profile_available": True, "changed": changed}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state", required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(configure(args.state.resolve())))


if __name__ == "__main__":
    main()
