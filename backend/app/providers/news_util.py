from __future__ import annotations

import re
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from html import unescape


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", s or ""))).strip()


def parse_ts(s: str) -> int:
    """ISO-8601, RFC-2822 or compact (20260105T093000[Z]) -> UTC epoch seconds."""
    s = (s or "").strip()
    for fmt in ("%Y%m%dT%H%M%SZ", "%Y%m%dT%H%M%S"):
        try:
            return int(datetime.strptime(s, fmt).replace(tzinfo=UTC).timestamp())
        except ValueError:
            pass
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC).timestamp())
    except ValueError:
        return int(parsedate_to_datetime(s).astimezone(UTC).timestamp())


def bare_symbol(sym: str) -> str:
    """RELIANCE.NSE / RELIANCE.NS / NSE:RELIANCE -> RELIANCE."""
    s = sym.upper().split(":")[-1]
    return re.sub(r"\.(NSE|NS|BSE|BO)$", "", s)
