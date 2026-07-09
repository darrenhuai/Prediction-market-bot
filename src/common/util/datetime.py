import re
from datetime import datetime

_FRACTIONAL_TZ_RE = re.compile(r"(.+\.\d+)([+-].+)")


def parse_iso_datetime(val: str) -> datetime:
    """Parse an ISO-8601 datetime string, tolerating any fractional-second precision.

    datetime.fromisoformat on Python <3.11 only accepts 0, 3, or 6 fractional
    digits, so fractional seconds of any other precision (Kalshi sends a single
    digit, Polymarket sometimes sends nanosecond precision) are padded or
    truncated to exactly 6 digits before parsing. A trailing "Z" suffix is
    normalized to an explicit "+00:00" offset so the regex below also handles
    Zulu timestamps.
    """
    val = val.replace("Z", "+00:00")
    match = _FRACTIONAL_TZ_RE.match(val)
    if match:
        base, tz = match.groups()
        date_part, frac = base.split(".")
        val = f"{date_part}.{frac.ljust(6, '0')[:6]}{tz}"
    return datetime.fromisoformat(val)
