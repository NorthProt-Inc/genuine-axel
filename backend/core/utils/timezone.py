from datetime import datetime
from zoneinfo import ZoneInfo

VANCOUVER_TZ = ZoneInfo("America/Vancouver")

def now_vancouver() -> datetime:

    return datetime.now(VANCOUVER_TZ)

def ensure_aware(dt: datetime) -> datetime:

    if dt.tzinfo is None:
        return dt.replace(tzinfo=VANCOUVER_TZ)
    return dt

def to_iso_vancouver(dt: datetime = None) -> str:

    if dt is None:
        dt = now_vancouver()
    return dt.isoformat()
