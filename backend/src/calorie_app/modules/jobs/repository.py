"""Bounded candidate reads followed by account-first qualified SQL transitions."""

from sqlalchemy import text

from calorie_app.modules.ai.repository import call


def candidates(session, batch):
    return list(
        session.scalars(
            text(
                "SELECT id FROM app.ai_jobs WHERE ("
                "(state='queued' AND next_attempt_at<=clock_timestamp()) OR "
                "(state='running' AND lease_until<=clock_timestamp()) "
                ") ORDER BY next_attempt_at,id LIMIT :batch"
            ),
            {"batch": batch},
        )
    )


def claim(session, job, fence):
    return call(session, "SELECT app.e7_claim(:job,:fence)", job=job, fence=fence)


def dispatch(session, job, fence, kind, attempt, worker):
    return call(
        session,
        "SELECT app.e7_dispatch(:job,:fence,:kind,:attempt,:worker)",
        job=job,
        fence=fence,
        kind=kind,
        attempt=attempt,
        worker=worker,
    )


def physical_finish(session, attempt, worker, outcome):
    status = (
        "ok"
        if outcome.code == "ok"
        else "unknown"
        if outcome.code == "provider_result_unknown"
        else "denied"
    )
    return call(
        session,
        "SELECT app.e7_io_finished(:attempt,:worker,:status,:input,:output,:thoughts)",
        attempt=attempt,
        worker=worker,
        status=status,
        input=outcome.input_tokens,
        output=outcome.output_tokens,
        thoughts=outcome.thoughts_tokens,
    )
