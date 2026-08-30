"""ISO-week identity and lifecycle.

Weeks are identified as ISO 8601 week strings (`2026-W30`, Monday start),
computed in the configured timezone. Week-end transitions are evaluated
lazily — a week has ended once "now" falls in a later week.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, tzinfo

REPETITION_WINDOW_WEEKS = 4


def week_id_for(moment: datetime, tz: tzinfo) -> str:
    """The ISO week id of an aware moment, evaluated in the given timezone."""
    year, week, _ = moment.astimezone(tz).isocalendar()
    return f"{year}-W{week:02d}"


def current_week_id(tz: tzinfo) -> str:
    return week_id_for(datetime.now(tz), tz)


def monday_of(week_id: str) -> date:
    """The Monday a week starts on."""
    year, week = _parse_week_id(week_id)
    return date.fromisocalendar(year, week, 1)


def previous_week_ids(week_id: str, count: int = REPETITION_WINDOW_WEEKS) -> list[str]:
    """The `count` weeks before `week_id`, most recent first."""
    monday = monday_of(week_id)
    ids = []
    for offset in range(1, count + 1):
        year, week, _ = (monday - timedelta(weeks=offset)).isocalendar()
        ids.append(f"{year}-W{week:02d}")
    return ids


def week_has_ended(week_id: str, tz: tzinfo, now: datetime | None = None) -> bool:
    """True once the current moment falls after the week's Sunday (in `tz`)."""
    moment = datetime.now(tz) if now is None else now
    return moment.astimezone(tz).date() > monday_of(week_id) + timedelta(days=6)


def _parse_week_id(week_id: str) -> tuple[int, int]:
    year_part, _, week_part = week_id.partition("-W")
    return int(year_part), int(week_part)
