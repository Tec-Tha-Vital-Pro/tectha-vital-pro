"""Shared helpers: IST time, phone numbers, rupee formatting."""
import re
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
FMT = "%Y-%m-%d %H:%M:%S"


def now() -> datetime:
    """Current IST time, naive (all stored times are IST)."""
    return datetime.now(IST).replace(tzinfo=None, microsecond=0)


def ts(dt: datetime) -> str:
    return dt.strftime(FMT)


def parse(s: str) -> datetime:
    return datetime.strptime(s, FMT)


def normalize_phone(raw: str) -> str:
    """Return an Indian mobile as 91XXXXXXXXXX. Raises ValueError when it is not one."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    if not (len(digits) == 12 and digits.startswith("91") and digits[2] in "6789"):
        raise ValueError(f"Not a valid Indian mobile number: {raw!r}")
    return digits


def inr(amount: int | float) -> str:
    """Format rupees the Indian way: 1234567 -> ₹12,34,567."""
    n = int(round(amount))
    sign = "-" if n < 0 else ""
    s = str(abs(n))
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        s = ",".join(parts) + "," + tail
    return f"{sign}₹{s}"


def patient_uid(pid: int) -> str:
    return f"TT-{pid:06d}"
