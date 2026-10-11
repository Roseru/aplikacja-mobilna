"""Real PG/API-role consent freshness and exact pre-E8 receipt compatibility."""

import hashlib
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session
from test_e8_ranking_pg import participant
from test_e8_ranking_pg import ranking_state as ranking_state

from calorie_app.modules.analytics.motivation.ranking import ranking_publication
from calorie_app.modules.catalog.validation import canonical_json

pytestmark = pytest.mark.integration


def put(client, ranking=True, energy=False, revision=1, key=None, epoch=None):
    headers = {
        "Authorization": "Bearer a",
        "If-Match": f'"{revision}"',
        "Idempotency-Key": str(key or uuid4()),
    }
    if epoch is not None:
        headers["X-Ranking-Consent-Epoch"] = str(epoch)
    return client.put(
        "/api/v1/me/consents",
        headers=headers,
        json={"ranking": ranking, "automatic_energy_adjustment": energy},
    )


def state(engine, owner, epoch):
    with Session(engine) as session, session.begin():
        return ranking_publication(session, owner, epoch)


def test_legacy_hash_response_unchanged_and_no_automatic_publication(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "Old", 10, owners["a"], fresh=False)
    key = uuid4()
    response = put(client, key=key)
    assert response.status_code == 200, response.text
    assert set(response.json()) == {
        "revision",
        "ranking",
        "automatic_energy_adjustment",
        "updated_at",
    }
    assert state(engine, owners["a"], epoch)["pending_consent_refresh"] is True
    expected = hashlib.sha256(
        canonical_json(
            {
                "body": {"ranking": True, "automatic_energy_adjustment": False},
                "if_match": 1,
            }
        )
    ).hexdigest()
    with engine.connect() as connection:
        stored = connection.scalar(
            text(
                "SELECT request_hash FROM app.online_receipts "
                "WHERE owner_id=:owner AND operation='consents' AND key=:key"
            ),
            {"owner": owners["a"], "key": key},
        )
        assert stored == expected
    assert put(client, key=key).json() == response.json()
    assert put(client, key=key, epoch=epoch).json()["code"] == "idempotency_key_reused"
    assert state(engine, owners["a"], epoch)["effective"] is False


def test_fresh_affirmation_energy_change_optout_and_old_replay(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "Old", 10, owners["a"], fresh=False)
    key = uuid4()
    accepted = put(client, key=key, epoch=epoch)
    assert accepted.status_code == 200, accepted.text
    assert state(engine, owners["a"], epoch)["effective"] is True
    changed = put(client, energy=True, revision=2)
    assert changed.status_code == 200, changed.text
    assert changed.json()["automatic_energy_adjustment"] is True
    assert state(engine, owners["a"], epoch)["effective"] is True
    with engine.connect() as connection:
        marker_revision = connection.scalar(
            text("SELECT source_revision FROM app.ranking_affirmations WHERE owner_id=:owner"),
            {"owner": owners["a"]},
        )
        assert marker_revision == 2  # Provenance does not require live consent revision==2.
    assert put(client, ranking=False, energy=True, revision=3).status_code == 200
    assert state(engine, owners["a"], epoch)["requested"] is False
    replay = put(client, key=key, epoch=epoch)
    assert replay.json() == accepted.json()
    assert state(engine, owners["a"], epoch)["effective"] is False
    assert state(engine, owners["a"], epoch)["requested"] is False
    assert put(client, energy=True, revision=4).status_code == 200
    restored = state(engine, owners["a"], epoch)
    assert restored["requested"] is True and restored["pending_consent_refresh"] is True
    assert restored["effective"] is False
    assert put(client, energy=True, revision=5, epoch=epoch).status_code == 200
    assert state(engine, owners["a"], epoch)["effective"] is True


@pytest.mark.parametrize("header,ranking", [("other", True), ("current", False)])
def test_invalid_new_epoch_context_is_atomic(ranking_state, header, ranking):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "Old", 10, owners["a"], fresh=False)
    key = uuid4()
    response = put(client, ranking=ranking, key=key, epoch=uuid4() if header == "other" else epoch)
    assert response.status_code == 409, response.text
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT revision,ranking,automatic_energy_adjustment FROM "
                "app.user_consents WHERE owner_id=:owner"
            ),
            {"owner": owners["a"]},
        ).one()
        assert row == (1, True, False)
        assert (
            connection.scalar(
                text(
                    "SELECT count(*) FROM app.online_receipts WHERE "
                    "owner_id=:owner AND operation='consents' AND key=:key"
                ),
                {"owner": owners["a"], "key": key},
            )
            == 0
        )
        assert (
            connection.scalar(
                text("SELECT count(*) FROM app.ranking_affirmations WHERE owner_id=:owner"),
                {"owner": owners["a"]},
            )
            == 0
        )
    assert response.headers["cache-control"] == "no-store"


def test_restored_true_in_new_epoch_and_rebuild_cannot_regrant(ranking_state):
    engine, _, owners, old_epoch, client = ranking_state
    participant(engine, old_epoch, "Old", 10, owners["a"], fresh=False)
    key = uuid4()
    old_receipt = put(client, key=key, epoch=old_epoch)
    assert old_receipt.status_code == 200
    # Backup would contain true and the old provenance marker. Later opt-out is
    # intentionally lost by restoring that source snapshot under a new epoch.
    assert put(client, ranking=False, revision=2).status_code == 200
    new_epoch = uuid4()
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE app.installation_state SET sync_epoch=:epoch WHERE id=1"),
            {"epoch": new_epoch},
        )
        connection.execute(
            text("DELETE FROM app.user_consents WHERE owner_id=:owner"), {"owner": owners["a"]}
        )
        connection.execute(
            text("INSERT INTO app.user_consents(owner_id,ranking,revision) VALUES(:owner,true,2)"),
            {"owner": owners["a"]},
        )
        connection.execute(
            text("INSERT INTO app.ranking_affirmations VALUES(:owner,:old,2)"),
            {"owner": owners["a"], "old": old_epoch},
        )
        connection.execute(
            text(
                "UPDATE app.motivation_accounts SET sync_epoch=:epoch,backfill_state='ready' "
                "WHERE owner_id=:owner"
            ),
            {"owner": owners["a"], "epoch": new_epoch},
        )
    assert state(engine, owners["a"], new_epoch)["effective"] is False
    assert (
        client.get("/api/v1/ranking", headers={"Authorization": "Bearer a"}).json()["items"] == []
    )
    assert put(client, key=key, epoch=old_epoch).json()["code"] == "sync_epoch_changed"
    assert put(client, energy=True, revision=2).status_code == 200
    assert state(engine, owners["a"], new_epoch)["effective"] is False
    assert put(client, energy=True, revision=3, epoch=new_epoch).status_code == 200
    assert state(engine, owners["a"], new_epoch)["effective"] is True
    assert put(client, ranking=False, energy=True, revision=4).status_code == 200
    assert state(engine, owners["a"], new_epoch)["effective"] is False


@pytest.mark.parametrize(
    "header", ["", "garbage", "UPPERCASE", "{00000000-0000-0000-0000-000000000001}"]
)
def test_epoch_parser_no_store_and_no_private_echo(ranking_state, header):
    response = put(ranking_state[-1], epoch=header)
    assert response.status_code == 422, response.text
    assert response.headers["cache-control"] == "no-store"
    assert header not in response.text if header else True


def test_header_presence_epoch_or_body_changed_key_conflict(ranking_state):
    engine, _, owners, epoch, client = ranking_state
    participant(engine, epoch, "Old", 10, owners["a"], fresh=False)
    key = uuid4()
    assert put(client, key=key, epoch=epoch).status_code == 200
    for supplied_epoch, energy in [(None, False), (uuid4(), False), (epoch, True)]:
        rejected = put(client, key=key, epoch=supplied_epoch, energy=energy)
        assert rejected.status_code == 409
        assert rejected.json()["code"] == "idempotency_key_reused"
    assert state(engine, owners["a"], epoch)["effective"] is True
