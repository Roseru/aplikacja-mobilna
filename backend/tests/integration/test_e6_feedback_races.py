"""Real PostgreSQL barriers for votes and opposing catalogue merges."""

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from time import monotonic, sleep

import pytest
from sqlalchemy import text
from test_e6_community_publication import community_db  # noqa: F401
from test_e6_feedback_moderation import actors, feedback, merge, merge_body, mutation, product, vote

from calorie_app.modules.catalog.community.feedback import change_vote
from calorie_app.modules.catalog.moderation.service import merge_products

pytestmark = pytest.mark.integration


def wait_for_catalog(engine):
    deadline = monotonic() + 5
    while monotonic() < deadline:
        with engine.connect() as connection:
            if connection.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname=current_database() "
                    "AND wait_event_type='Lock' AND query LIKE '%lock_community_catalog%'"
                )
            ):
                return True
        sleep(0.02)
    return False


@pytest.mark.parametrize("vote_first", [True, False])
@pytest.mark.parametrize("value", [1, -1, None], ids=["plus", "change-minus", "withdraw"])
def test_vote_change_withdraw_versus_merge_real_wait(request, vote_first, value):
    engine = request.getfixturevalue("community_db")
    a, b, c, mod = actors(engine)
    source = product(engine, a[1], a[0], a[2], "Concurrent source")
    target = product(engine, b[1], b[0], b[2], "Concurrent target")
    assert vote(engine, c, source, 0, 1).error is None
    held, release = Event(), Event()

    def hold(action):
        def callback(session, account, operation):
            result = action(session, account, operation)
            held.set()
            assert release.wait(10)
            return result

        return callback

    def vote_callback(session, account, operation):
        return change_vote(session, account, source, 1, value, operation)

    def merge_callback(session, account, operation):
        return merge_products(session, account, source, merge_body(target), operation)

    first_actor, first_kind, first_action = (
        (c, "vote", vote_callback) if vote_first else (mod, "merge", merge_callback)
    )
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(
            mutation, engine, first_actor[0], first_actor[2], first_kind, hold(first_action)
        )
        assert held.wait(10)
        waiting = (
            pool.submit(merge, engine, mod, source, target)
            if vote_first
            else pool.submit(vote, engine, c, source, 1, value)
        )
        blocked = wait_for_catalog(engine)
        release.set()
        first_result = first.result(timeout=10)
        second_result = waiting.result(timeout=10)
    assert blocked and first_result.error is None
    if vote_first:
        assert second_result.error is None
    else:
        assert second_result.error.code == "product_merged"
    assert feedback(engine, c, target)["voters"] == 0


def test_opposing_merges_one_commit_one_stale_without_deadlock(request):
    engine = request.getfixturevalue("community_db")
    a, b, _, mod = actors(engine)
    _, _, _, other_mod = actors(engine)
    source = product(engine, a[1], a[0], a[2], "Opposing A")
    target = product(engine, b[1], b[0], b[2], "Opposing B")
    held, release = Event(), Event()

    def callback(session, account, operation):
        result = merge_products(session, account, source, merge_body(target), operation)
        held.set()
        assert release.wait(10)
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(mutation, engine, mod[0], mod[2], "merge", callback)
        assert held.wait(10)
        reverse = pool.submit(merge, engine, other_mod, target, source)
        blocked = wait_for_catalog(engine)
        release.set()
        assert first.result(timeout=10).error is None
        second = reverse.result(timeout=10)
    assert blocked and second.error.code == "product_merged"
