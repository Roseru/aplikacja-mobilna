"""Explicit test adapter for existing graph/locking regressions.

Historical migration tests use the frozen pre-ledger driver only on schemas
without the new entry points. Head tests use the real producer and a durable,
authenticated test sink, with separate DB commits at every protocol boundary.
"""

import tempfile
from pathlib import Path
from uuid import uuid4

from sqlalchemy import text

from calorie_app.modules.identity import deletion as production
from calorie_app.modules.identity.models import UserAccount
from tests.support.ledger import LedgerHarness

_HARNESSES = {}
_BY_DATABASE = {}


def harness(engine):
    database_key = (engine.url.host, engine.url.port, engine.url.database)
    known = _BY_DATABASE.get(database_key)
    # A minimal real LOGIN cannot read keys/config. Reuse only the independently
    # registered fixture receiver for the same owned DB; never fetch keys as actor.
    if known is not None and engine.url.username != known.engine.url.username:
        return known
    with engine.connect() as connection:
        stream = connection.scalar(text("SELECT stream_id FROM app.deletion_ledger_source"))
    key = (str(engine.url), stream)
    if key not in _HARNESSES:
        _HARNESSES[key] = LedgerHarness(engine, Path(tempfile.mkdtemp(prefix="ledger-contract-")))
    _BY_DATABASE[database_key] = _HARNESSES[key]
    return _HARNESSES[key]


def ledger_present(connection):
    return connection.scalar(text("SELECT to_regprocedure('app.ledger_status(uuid)') IS NOT NULL"))


def begin(connection, account_id, operation_id, expected_generation):
    if ledger_present(connection):
        return production.begin(connection, account_id, operation_id, expected_generation)
    from tests.support.legacy_deletion import begin as old_begin

    return old_begin(connection, account_id, operation_id, expected_generation)


def status(connection, operation_id):
    if ledger_present(connection):
        return production.status(connection, operation_id)
    from tests.support.legacy_deletion import status as old_status

    return old_status(connection, operation_id)


def resume(engine, operation_id, adapter, *, barrier=None):
    with engine.connect() as connection:
        current = ledger_present(connection)
    if not current:
        from tests.support.legacy_deletion import resume as old_resume

        return old_resume(engine, operation_id, adapter, barrier=barrier)
    return production.resume(
        engine, operation_id, adapter, barrier=barrier, delivery=harness(engine).deliver
    )


def begin_deleting(session, account_id, expected_generation=None):
    account = session.get(UserAccount, account_id, populate_existing=True)
    generation = expected_generation if expected_generation is not None else account.generation
    connection = session.connection()
    if ledger_present(connection):
        prior = connection.scalar(text("SELECT current_user"))
        connection.exec_driver_sql("SET LOCAL ROLE calorie_app_deletion_operator")
        try:
            production.begin(connection, account_id, uuid4(), generation)
        finally:
            connection.exec_driver_sql('SET LOCAL ROLE "' + prior.replace('"', '""') + '"')
        session.refresh(account)
        return account
    # Frozen pre-ledger schema rule, used only by explicitly historical tests.
    from calorie_app.modules.identity.service import lock_account

    account = lock_account(session, account_id, expected_generation)
    account.state = "deleting"
    account.generation += 1
    session.flush()
    return account


class ConfirmedProvider:
    def delete_and_confirm(self, issuer, subject):
        """Synthetic graph regression only; real provider acceptance is separate."""


def purge(engine, owner, operation=None, generation=1):
    operation = operation or uuid4()
    with engine.begin() as connection:
        begin(connection, owner, operation, generation)
    return resume(engine, operation, ConfirmedProvider())
