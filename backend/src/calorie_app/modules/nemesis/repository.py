"""Narrow SQL entry points. PostgreSQL owns policy, locks and durable receipts."""

import json

from sqlalchemy import text


def execute(session, principal, epoch, operation, key, request_hash, payload):
    return session.scalar(
        text(
            "SELECT app.e8n_execute(:issuer,:subject,:epoch,:operation,:key,:hash,"
            "CAST(:payload AS jsonb))"
        ),
        {
            "issuer": principal.issuer,
            "subject": principal.subject,
            "epoch": epoch,
            "operation": operation,
            "key": key,
            "hash": request_hash,
            "payload": json.dumps(payload, ensure_ascii=False, allow_nan=False),
        },
    )


def read(session, principal, epoch, challenge_id=None, limit=30, cursor=None):
    return session.scalar(
        text("SELECT app.e8n_read(:issuer,:subject,:epoch,:id,:limit,:cursor)"),
        {
            "issuer": principal.issuer,
            "subject": principal.subject,
            "epoch": epoch,
            "id": challenge_id,
            "limit": limit,
            "cursor": cursor,
        },
    )


def statistics(session, principal, epoch, challenge_id):
    return session.scalar(
        text("SELECT app.e8n_statistics(:issuer,:subject,:epoch,:id)"),
        {
            "issuer": principal.issuer,
            "subject": principal.subject,
            "epoch": epoch,
            "id": challenge_id,
        },
    )
