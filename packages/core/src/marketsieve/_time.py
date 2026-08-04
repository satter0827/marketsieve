"""Internal helpers for comparing absolute instants."""

from __future__ import annotations

from datetime import UTC, datetime


def as_utc(value: datetime) -> datetime:
    """Return an aware datetime as its unambiguous UTC instant."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must include a UTC offset")
    return value.astimezone(UTC)
