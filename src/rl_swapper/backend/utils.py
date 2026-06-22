from datetime import datetime, timezone

def current_timestamp_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")