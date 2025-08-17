from datetime import datetime, timezone

def utc_now():
    """Return timezone-aware datetime in UTC."""
    return datetime.now(timezone.utc)
