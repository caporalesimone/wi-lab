from datetime import UTC, datetime


def format_utc_timestamp(epoch: float | None) -> str | None:
    """Format Unix seconds as an RFC 3339 UTC timestamp, preserving null."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=UTC).isoformat().removesuffix("+00:00") + "Z"
