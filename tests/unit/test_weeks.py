"""Unit tests for ISO-week identity and lifecycle (T005)."""

from datetime import datetime
from zoneinfo import ZoneInfo

from sous_chef.services.weeks import (
    current_week_id,
    previous_week_ids,
    week_has_ended,
    week_id_for,
)

UTC = ZoneInfo("UTC")
NEW_YORK = ZoneInfo("America/New_York")
TOKYO = ZoneInfo("Asia/Tokyo")


class TestWeekIdFor:
    def test_midweek_moment_maps_to_iso_week(self) -> None:
        moment = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)  # Wednesday
        assert week_id_for(moment, UTC) == "2026-W29"

    def test_week_number_is_zero_padded(self) -> None:
        moment = datetime(2026, 2, 2, 12, 0, tzinfo=UTC)  # Monday of week 6
        assert week_id_for(moment, UTC) == "2026-W06"

    def test_same_instant_differs_across_timezones(self) -> None:
        # Monday 03:00 UTC is still Sunday 23:00 in New York.
        moment = datetime(2026, 7, 20, 3, 0, tzinfo=UTC)
        assert week_id_for(moment, UTC) == "2026-W30"
        assert week_id_for(moment, NEW_YORK) == "2026-W29"
        assert week_id_for(moment, TOKYO) == "2026-W30"

    def test_week_starts_monday_midnight_local(self) -> None:
        sunday_night = datetime(2026, 7, 19, 23, 59, tzinfo=NEW_YORK)
        monday_midnight = datetime(2026, 7, 20, 0, 0, tzinfo=NEW_YORK)
        assert week_id_for(sunday_night, NEW_YORK) == "2026-W29"
        assert week_id_for(monday_midnight, NEW_YORK) == "2026-W30"

    def test_january_can_belong_to_previous_iso_year(self) -> None:
        # 2027-01-01 is a Friday inside 2026's 53rd ISO week.
        moment = datetime(2027, 1, 1, 12, 0, tzinfo=UTC)
        assert week_id_for(moment, UTC) == "2026-W53"


class TestCurrentWeekId:
    def test_matches_week_of_now_in_timezone(self) -> None:
        assert current_week_id(UTC) == week_id_for(datetime.now(UTC), UTC)


class TestPreviousWeekIds:
    def test_default_window_is_four_weeks_most_recent_first(self) -> None:
        assert previous_week_ids("2026-W30") == [
            "2026-W29",
            "2026-W28",
            "2026-W27",
            "2026-W26",
        ]

    def test_window_crosses_year_boundary(self) -> None:
        assert previous_week_ids("2026-W01", count=2) == ["2025-W52", "2025-W51"]

    def test_window_crosses_into_53_week_year(self) -> None:
        assert previous_week_ids("2027-W01", count=1) == ["2026-W53"]

    def test_zero_count_gives_empty_window(self) -> None:
        assert previous_week_ids("2026-W30", count=0) == []


class TestWeekHasEnded:
    def test_past_week_has_ended(self) -> None:
        now = datetime(2026, 7, 20, 0, 0, tzinfo=UTC)  # Monday of W30
        assert week_has_ended("2026-W29", UTC, now=now)

    def test_current_week_has_not_ended(self) -> None:
        now = datetime(2026, 7, 19, 23, 59, tzinfo=UTC)  # Sunday of W29
        assert not week_has_ended("2026-W29", UTC, now=now)

    def test_future_week_has_not_ended(self) -> None:
        now = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
        assert not week_has_ended("2026-W30", UTC, now=now)

    def test_boundary_respects_timezone(self) -> None:
        # Monday 03:00 UTC: W29 is over in UTC but still Sunday in New York.
        now = datetime(2026, 7, 20, 3, 0, tzinfo=UTC)
        assert week_has_ended("2026-W29", UTC, now=now)
        assert not week_has_ended("2026-W29", NEW_YORK, now=now)
