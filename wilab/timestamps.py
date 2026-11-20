from datetime import datetime, timezone


def format_utc_timestamp(epoch: float | None) -> str | None:
    """Format Unix seconds as an RFC 3339 UTC timestamp, preserving null."""
    if epoch is None:
        return None
    return datetime.fromtimestamp(epoch, tz=timezone.utc).isoformat().removesuffix("+00:00") + "Z"
