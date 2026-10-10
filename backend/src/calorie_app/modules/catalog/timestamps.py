"""One UTC wire representation, matching PostgreSQL microsecond precision."""

from datetime import UTC, datetime


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def normalize_timestamp(value: dict) -> dict:
    """Called only after E0 validation; never normalize downloaded gzip bytes."""
    return value | {"published_at": utc_text(datetime.fromisoformat(value["published_at"]))}
