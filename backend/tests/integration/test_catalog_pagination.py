"""Bounded cursor state and compatibility with previously issued UUID pages."""

import copy
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import test_catalog_delivery as delivery
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, insert, select, text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from calorie_app.core.config import Settings
from calorie_app.main import create_app
from calorie_app.modules.catalog import OFFICIAL_PACKAGE_ID
from calorie_app.modules.catalog.cli import main as catalog_command
from calorie_app.modules.catalog.export import publish_package
from calorie_app.modules.catalog.models import RationPageToken
from calorie_app.modules.catalog.pagination import (
    PAGE_TTL,
    decode_cursor,
    encode_cursor,
    prune_legacy_tokens,
)
from calorie_app.modules.catalog.service import import_catalog

pytestmark = pytest.mark.integration
catalog_db = delivery.catalog_db
synthetic_official = delivery.synthetic_official


def client_for(engine, url, root, **settings):
    return TestClient(
        create_app(
            Settings(database_url=url, catalog_artifact_root=root, **settings), engine=engine
        )
    )


def counts(engine):
    with engine.connect() as connection:
        return tuple(
            connection.scalar(text(f"SELECT count(*) FROM app.{table}"))
            for table in ("ration_page_tokens", "ration_page_token_tombstones")
        )


def seed_legacy(engine, migrate, value, tmp_path, *, expired=1):
    """Issue actual old-format rows under old schema/ACL, then upgrade without rewriting."""
    import_catalog(engine, value)
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    migrate("downgrade", "0004_catalog_timestamp")
    active, old = uuid4(), [uuid4() for _ in range(expired)]
    expires = datetime.now(UTC) + PAGE_TTL
    with engine.begin() as connection:
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_api")
        for token_id in [active, *old]:
            connection.execute(
                insert(RationPageToken).values(
                    id=token_id,
                    package_id=OFFICIAL_PACKAGE_ID,
                    release=1,
                    after_id=UUID(sorted(r["ration_id"] for r in value["rations"])[0]),
                    after_revision=1,
                    limit=1,
                    expires_at=expires
                    if token_id == active
                    else datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        before = list(connection.execute(select(RationPageToken).order_by(RationPageToken.id)))
    migrate("upgrade", "head")
    with engine.connect() as connection:
        assert (
            list(connection.execute(select(RationPageToken).order_by(RationPageToken.id))) == before
        )
    return active, old, expires


def test_repeated_first_and_following_pages_do_not_grow_persistent_state(catalog_db, tmp_path):
    engine, _, url = catalog_db
    import_catalog(engine, synthetic_official(count=4))
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    with TestClient(
        create_app(Settings(database_url=url, catalog_artifact_root=tmp_path), engine=engine)
    ) as client:
        first = client.get("/api/v1/rations?limit=1")
        assert first.status_code == 200
        token = first.json()["next_page_token"]
        previous = None
        for _ in range(25):
            assert client.get("/api/v1/rations?limit=1").status_code == 200
            following = client.get("/api/v1/rations", params={"limit": 1, "page_token": token})
            assert following.status_code == 200
            if previous is not None:
                assert following.json() == previous
            previous = following.json()
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM app.ration_page_tokens")) == 0
        assert counts(engine) == (0, 0)


def test_cursor_survives_restart_and_new_publication_without_renewing_ttl(catalog_db, tmp_path):
    engine, _, url = catalog_db
    value = synthetic_official(count=4)
    import_catalog(engine, value)
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    with client_for(engine, url, tmp_path) as client:
        first = client.get("/api/v1/rations?limit=1").json()
    secret = Settings(database_url=url).catalog_page_token_secret
    cursor = decode_cursor(first["next_page_token"], secret)
    newer = copy.deepcopy(value)
    newer["release"] = 2
    for ration in newer["rations"]:
        ration.update(revision=2, name=ration["name"] + " new")
    import_catalog(engine, newer)
    publish_package(engine, OFFICIAL_PACKAGE_ID, 2, tmp_path)
    runtime = create_engine(url, hide_parameters=True)

    @event.listens_for(runtime, "connect")
    def api_role(connection, _):
        with connection.cursor() as query:
            query.execute("SET ROLE calorie_app_api")
        connection.commit()

    try:
        with client_for(runtime, url, tmp_path) as restarted:
            items, token = first["items"], first["next_page_token"]
            while token is not None:
                response = restarted.get(
                    "/api/v1/rations", params={"limit": 1, "page_token": token}
                )
                assert response.status_code == 200
                result = response.json()
                items += result["items"]
                token = result["next_page_token"]
                if token is not None:
                    decoded = decode_cursor(token, secret)
                    assert decoded.expires_at == cursor.expires_at
                    assert (decoded.package_id, decoded.release, decoded.limit) == (
                        OFFICIAL_PACKAGE_ID,
                        1,
                        1,
                    )
            assert [item["ration_id"] for item in items] == sorted(
                r["ration_id"] for r in value["rations"]
            )
            assert all(item["revision"] == 1 for item in items)
            assert restarted.get("/api/v1/rations").json()["items"][0]["revision"] == 2
    finally:
        runtime.dispose()
    assert counts(engine) == (0, 0)


def test_expiry_boundary_is_exact_and_remains_410_after_cleanup_and_restart(
    catalog_db, tmp_path, monkeypatch
):
    engine, _, url = catalog_db
    import_catalog(engine, synthetic_official(count=3))
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    secret = Settings(database_url=url).catalog_page_token_secret
    with client_for(engine, url, tmp_path) as client:
        token = client.get("/api/v1/rations?limit=1").json()["next_page_token"]
        expiry = decode_cursor(token, secret).expires_at
        monkeypatch.setattr(
            "calorie_app.modules.catalog.router.database_now",
            lambda _: expiry - timedelta(microseconds=1),
        )
        assert (
            client.get("/api/v1/rations", params={"limit": 1, "page_token": token}).status_code
            == 200
        )
        monkeypatch.setattr("calorie_app.modules.catalog.router.database_now", lambda _: expiry)
        expired = client.get("/api/v1/rations", params={"limit": 1, "page_token": token})
        assert expired.status_code == 410 and expired.json()["code"] == "page_expired"
        assert expired.json()["details"] == []
    with Session(engine) as session, session.begin():
        assert prune_legacy_tokens(session) == 0
    with client_for(engine, url, tmp_path) as restarted:
        assert (
            restarted.get("/api/v1/rations", params={"limit": 1, "page_token": token}).status_code
            == 410
        )
    assert counts(engine) == (0, 0)


def test_modified_unknown_and_wrong_limit_tokens_are_422(catalog_db, tmp_path):
    engine, _, url = catalog_db
    import_catalog(engine, synthetic_official(count=3))
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    with client_for(engine, url, tmp_path) as client:
        token = client.get("/api/v1/rations?limit=1").json()["next_page_token"]
        prefix, payload, signature = token.split(".")
        for invalid in (
            "broken",
            str(uuid4()),
            token + "=",
            "rp2." + payload + "." + signature,
            prefix + "." + ("A" if payload[0] != "A" else "B") + payload[1:] + "." + signature,
            prefix + "." + payload + "." + ("A" if signature[0] != "A" else "B") + signature[1:],
        ):
            response = client.get("/api/v1/rations", params={"limit": 1, "page_token": invalid})
            assert response.status_code == 422 and response.json()["code"] == "invalid_request"
        assert (
            client.get("/api/v1/rations", params={"limit": 2, "page_token": token}).status_code
            == 422
        )
        secret = Settings(database_url=url).catalog_page_token_secret
        cursor = decode_cursor(token, secret)
        # Even a correctly authenticated cursor for a different channel cannot
        # select or disclose another package through the stable v1 URL.
        for expiry in (cursor.expires_at, datetime.now(UTC) - timedelta(seconds=1)):
            foreign = encode_cursor(replace(cursor, package_id=uuid4(), expires_at=expiry), secret)
            response = client.get("/api/v1/rations", params={"limit": 1, "page_token": foreign})
            assert response.status_code == 422


def test_legacy_upgrade_active_snapshot_restart_and_expired_after_cleanup(catalog_db, tmp_path):
    engine, migrate, url = catalog_db
    value = synthetic_official(count=4)
    active, expired, expires = seed_legacy(engine, migrate, value, tmp_path, expired=3)
    with client_for(engine, url, tmp_path) as client:
        response = client.get("/api/v1/rations", params={"limit": 1, "page_token": str(active)})
        assert response.status_code == 200
        next_token = response.json()["next_page_token"]
        assert (
            decode_cursor(
                next_token, Settings(database_url=url).catalog_page_token_secret
            ).expires_at
            == expires
        )
        assert counts(engine) == (1, 3)
    newer = delivery.next_release(value, 2)
    import_catalog(engine, newer)
    publish_package(engine, OFFICIAL_PACKAGE_ID, 2, tmp_path)
    with client_for(engine, url, tmp_path) as restarted:
        assert (
            restarted.get("/api/v1/rations", params={"limit": 1, "page_token": str(active)}).json()
            == response.json()
        )
        for token in expired:
            result = restarted.get("/api/v1/rations", params={"limit": 1, "page_token": str(token)})
            assert result.status_code == 410 and result.json()["code"] == "page_expired"
            assert (
                restarted.get(
                    "/api/v1/rations", params={"limit": 2, "page_token": str(token)}
                ).status_code
                == 422
            )
        assert (
            restarted.get(
                "/api/v1/rations", params={"limit": 1, "page_token": str(uuid4())}
            ).status_code
            == 422
        )
    assert counts(engine) == (1, 3)
    migrate("check")
    with pytest.raises(IntegrityError):
        migrate("downgrade", "0004_catalog_timestamp")


def test_retention_drains_bounded_batches_and_total_legacy_state_never_grows(catalog_db, tmp_path):
    engine, migrate, url = catalog_db
    active, expired, _ = seed_legacy(
        engine, migrate, synthetic_official(count=3), tmp_path, expired=1005
    )
    with client_for(engine, url, tmp_path) as client:
        assert client.get("/api/v1/rations?limit=1").status_code == 200
        assert counts(engine) == (6, 1000)
        assert client.get("/api/v1/rations?limit=1").status_code == 200
        assert counts(engine) == (1, 1005)
        for _ in range(10):
            assert client.get("/api/v1/rations?limit=1").status_code == 200
            assert (
                client.get(
                    "/api/v1/rations", params={"limit": 1, "page_token": str(active)}
                ).status_code
                == 200
            )
        assert (
            client.get(
                "/api/v1/rations", params={"limit": 1, "page_token": str(expired[-1])}
            ).status_code
            == 410
        )
    assert counts(engine) == (1, 1005)


@pytest.mark.parametrize("role", ["calorie_app_api", "calorie_app_worker"])
def test_runtime_can_only_invoke_restricted_cleanup_and_read_necessary_evidence(
    catalog_db, tmp_path, role
):
    engine, migrate, _ = catalog_db
    seed_legacy(engine, migrate, synthetic_official(count=3), tmp_path)
    with engine.begin() as connection:
        connection.exec_driver_sql(f"SET LOCAL ROLE {role}")
        for statement in (
            "DELETE FROM app.ration_page_tokens",
            "UPDATE app.ration_page_tokens SET expires_at=clock_timestamp()",
            "INSERT INTO app.ration_page_tokens SELECT * FROM app.ration_page_tokens LIMIT 1",
            "DELETE FROM app.ration_page_token_tombstones",
            'INSERT INTO app.ration_page_token_tombstones SELECT id,package_id,"limit" '
            "FROM app.ration_page_tokens",
            'UPDATE app.ration_page_token_tombstones SET "limit"=2',
        ):
            with pytest.raises(ProgrammingError), connection.begin_nested():
                connection.exec_driver_sql(statement)
        if role == "calorie_app_api":
            assert connection.scalar(text("SELECT app.prune_ration_page_tokens()")) == 1
        else:
            with pytest.raises(ProgrammingError), connection.begin_nested():
                connection.exec_driver_sql("SELECT app.prune_ration_page_tokens()")
    assert counts(engine) == ((1, 1) if role == "calorie_app_api" else (2, 0))
    with engine.connect() as connection:
        security = connection.execute(
            text(
                "SELECT prosecdef, proconfig, pg_get_userbyid(proowner) FROM pg_proc "
                "WHERE oid='app.prune_ration_page_tokens()'::regprocedure"
            )
        ).one()
        assert security.prosecdef is True
        assert security.proconfig == ["search_path=pg_catalog, pg_temp"]
        assert security.pg_get_userbyid == "calorie_app_migrator"
        assert not connection.scalar(
            text(
                "SELECT has_function_privilege('calorie_app_worker',"
                "'app.prune_ration_page_tokens()','EXECUTE')"
            )
        )


def test_missing_cursor_configuration_fails_closed_without_persistent_writes(catalog_db, tmp_path):
    engine, _, url = catalog_db
    import_catalog(engine, synthetic_official(count=3))
    publish_package(engine, OFFICIAL_PACKAGE_ID, 1, tmp_path)
    with client_for(engine, url, tmp_path, catalog_page_token_secret=None) as client:
        assert client.get("/health/ready").status_code == 503
        response = client.get("/api/v1/rations?limit=1")
        assert response.status_code == 503 and response.json()["code"] == "service_unavailable"
    assert counts(engine) == (0, 0)


def test_operator_cleanup_is_real_and_preserves_active_rows(catalog_db, tmp_path, capsys):
    engine, migrate, _ = catalog_db
    active, expired, _ = seed_legacy(engine, migrate, synthetic_official(count=3), tmp_path)
    assert catalog_command(["prune-page-tokens"]) == 0
    assert '"removed": 1' in capsys.readouterr().out
    assert counts(engine) == (1, 1)
    with Session(engine) as session:
        assert session.get(RationPageToken, active) is not None
        assert session.get(RationPageToken, expired[0]) is None
