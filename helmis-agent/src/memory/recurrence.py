"""Pure, timezone-aware recurrence calculations for tasks."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

WEEKDAY_NAMES = {
    "monday": 0, "mon": 0, "senin": 0,
    "tuesday": 1, "tue": 1, "selasa": 1,
    "wednesday": 2, "wed": 2, "rabu": 2,
    "thursday": 3, "thu": 3, "kamis": 3,
    "friday": 4, "fri": 4, "jumat": 4, "jum'at": 4,
    "saturday": 5, "sat": 5, "sabtu": 5,
    "sunday": 6, "sun": 6, "minggu": 6, "ahad": 6,
}


def _timezone(rule: dict[str, Any], fallback: ZoneInfo | str | None = None) -> ZoneInfo:
    raw = rule.get("timezone") or rule.get("tz") or fallback or "UTC"
    if isinstance(raw, ZoneInfo):
        return raw
    return ZoneInfo(str(raw))


def _aware(value: datetime, timezone: ZoneInfo) -> datetime:
    return value.replace(tzinfo=timezone) if value.tzinfo is None else value.astimezone(timezone)


def _parse_time(value: Any) -> tuple[int, int]:
    if isinstance(value, str):
        parts = value.strip().split(":", 1)
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            hour, minute = int(parts[0]), int(parts[1])
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return hour, minute
    if isinstance(value, (int, float)) and int(value) == value and 0 <= value <= 23:
        return int(value), 0
    raise ValueError("recurrence time must be HH:MM")


def _parse_datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if isinstance(value, datetime):
        return _aware(value, timezone)
    if not value or not isinstance(value, str):
        return None
    clean = value.strip().replace(" WIB", "").replace(" UTC", "")
    try:
        return _aware(datetime.fromisoformat(clean), timezone)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(clean, fmt).replace(tzinfo=timezone)
            except ValueError:
                continue
    return None


def _weekdays(rule: dict[str, Any]) -> list[int]:
    raw = rule.get("weekdays", rule.get("days", rule.get("weekday", [])))
    if not isinstance(raw, (list, tuple, set)):
        raw = [raw]
    values: list[int] = []
    for value in raw:
        if isinstance(value, int) and 0 <= value <= 6:
            values.append(value)
        elif isinstance(value, str):
            key = value.strip().lower()
            if key in WEEKDAY_NAMES:
                values.append(WEEKDAY_NAMES[key])
            elif key.isdigit() and 0 <= int(key) <= 6:
                values.append(int(key))
    return sorted(set(values))


def _interval(rule: dict[str, Any]) -> timedelta | None:
    if isinstance(rule.get("every"), dict):
        every = rule["every"]
        value, unit = every.get("value", every.get("amount")), every.get("unit", "days")
    else:
        value, unit = rule.get("interval", rule.get("interval_value")), rule.get("unit", "days")
        if value is None:
            for key, key_unit in (("interval_minutes", "minutes"), ("interval_hours", "hours"), ("interval_days", "days")):
                if rule.get(key) is not None:
                    value, unit = rule[key], key_unit
                    break
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        amount = float(value)
    except (TypeError, ValueError):
        return None
    if amount <= 0:
        return None
    unit_key = str(unit).lower().rstrip("s")
    factors = {"minute": 60, "min": 60, "hour": 3600, "hr": 3600, "day": 86400, "week": 604800}
    return timedelta(seconds=amount * factors.get(unit_key, 86400))


def next_occurrence(
    recurrence: dict[str, Any] | None,
    after: datetime,
    *,
    anchor: datetime | None = None,
) -> datetime | None:
    """Return the next occurrence strictly after ``after``.

    Weekly rules use ``weekdays`` (0=Monday) and ``time``.  Interval rules use
    ``interval``/``unit`` or ``interval_minutes``/``interval_hours``/``interval_days``.
    All calculations are aware and happen in the rule's timezone.
    """
    if not isinstance(recurrence, dict):
        return None
    timezone = _timezone(recurrence, after.tzinfo if isinstance(after.tzinfo, ZoneInfo) else None)
    current = _aware(after, timezone)
    kind = str(recurrence.get("type", recurrence.get("kind", ""))).lower().strip()
    if kind in {"weekly", "week", "weekly_time"}:
        days = _weekdays(recurrence)
        if not days:
            return None
        hour, minute = _parse_time(recurrence.get("time", recurrence.get("at", "00:00")))
        for offset in range(8):
            date = (current + timedelta(days=offset)).date()
            candidate = datetime(date.year, date.month, date.day, hour, minute, tzinfo=timezone)
            if date.weekday() in days and candidate > current:
                return candidate
        return None

    interval = _interval(recurrence)
    if interval is None or kind not in {"", "interval", "every", "periodic"}:
        return None
    base = _parse_datetime(recurrence.get("start_at", recurrence.get("anchor")), timezone)
    if anchor is not None:
        base = _aware(anchor, timezone)
    if base is None:
        base = current
    if base > current:
        return base
    steps = int((current - base).total_seconds() // interval.total_seconds()) + 1
    return base + interval * steps


def next_occurrence_for_task(task: dict[str, Any], after: datetime) -> datetime | None:
    recurrence = task.get("recurrence") or task.get("recurrence_policy")
    if not isinstance(recurrence, dict):
        return None
    timezone = _timezone(recurrence, after.tzinfo if isinstance(after.tzinfo, ZoneInfo) else None)
    anchor = _parse_datetime(task.get("due"), timezone)
    return next_occurrence(recurrence, after, anchor=anchor)


def interval_seconds(rule: dict[str, Any] | None) -> float | None:
    interval = _interval(rule) if isinstance(rule, dict) else None
    return interval.total_seconds() if interval else None


def weekly_next_occurrence(weekdays: list[int | str], time: str, after: datetime, timezone: str = "UTC") -> datetime | None:
    return next_occurrence({"type": "weekly", "weekdays": weekdays, "time": time, "timezone": timezone}, after)


def interval_next_occurrence(every: int | float, unit: str, after: datetime, anchor: datetime | None = None) -> datetime | None:
    return next_occurrence({"type": "interval", "interval": every, "unit": unit}, after, anchor=anchor)


def format_occurrence(value: datetime, *, include_timezone: bool = True) -> str:
    suffix = f" {value.tzname()}" if include_timezone and value.tzname() else ""
    return value.strftime("%Y-%m-%d %H:%M") + suffix


calculate_next_occurrence = next_occurrence
get_next_occurrence = next_occurrence
