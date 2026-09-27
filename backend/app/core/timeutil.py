import datetime as dt
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:  # pragma: no cover - validated on input
        raise ValueError(f"unknown timezone {tz_name}") from exc


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def local_today(tz_name: str, now: dt.datetime | None = None) -> dt.date:
    return (now or utcnow()).astimezone(zone(tz_name)).date()


def local_date(ts: dt.datetime, tz_name: str) -> dt.date:
    return ts.astimezone(zone(tz_name)).date()


def day_bounds_utc(start: dt.date, end: dt.date, tz_name: str) -> tuple[dt.datetime, dt.datetime]:
    """Half-open UTC interval covering local dates [start, end] inclusive in the shop timezone."""
    tz = zone(tz_name)
    lo = dt.datetime.combine(start, dt.time.min, tzinfo=tz)
    hi = dt.datetime.combine(end + dt.timedelta(days=1), dt.time.min, tzinfo=tz)
    return lo.astimezone(dt.UTC), hi.astimezone(dt.UTC)
