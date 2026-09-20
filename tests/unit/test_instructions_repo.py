"""Persistence of cooking instructions on the meals table.

The regression this file exists for: `save_accepted_plan` deletes and
re-inserts every meal row, and mid-week re-acceptance is a supported flow,
so saved steps must survive an edit.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.grocery import build_grocery_list
from sous_chef.services.history_repo import HistoryRepo, InstructionsError

WEEK = "2026-W31"
MOMENT = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def meal(name: str, *, source_url: str | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": "chicken",
        "prep_minutes": 30,
        "servings": 1,
        "batch": None,
        "stretch": None,
        "source_url": source_url,
        "user_requested_repeat": False,
        "ingredients": [
            {
                "name": "chicken thighs",
                "quantity": 1.5,
                "unit": "lb",
                "package": None,
                "estimated_price_usd": 7.5,
            }
        ],
    }


def plan_with(*names: str) -> WeeklyPlan:
    return WeeklyPlan.model_validate(
        {
            "week_id": WEEK,
            "dinner_count": len(names),
            "lunch_count": 0,
            "diet_type": None,
            "default_servings": 1,
            "weekly_budget_usd": None,
            "meals": [meal(name) for name in names],
        }
    )


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "instructions.db")


def accept(repo: HistoryRepo, plan: WeeklyPlan) -> None:
    repo.save_accepted_plan(plan, build_grocery_list(plan), accepted_at=MOMENT)


class TestSaveAndRead:
    def test_round_trip_and_overwrite(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Chicken chili", "Miso cod"))
        repo.save_meal_instructions(WEEK, "Chicken chili", "Brown the chicken.")
        assert repo.meal_instructions(WEEK, "Chicken chili") == "Brown the chicken."

        repo.save_meal_instructions(WEEK, "Chicken chili", "Different.")
        assert repo.meal_instructions(WEEK, "Chicken chili") == "Different."

    def test_lookup_normalizes_the_name(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Chicken chili"))
        repo.save_meal_instructions(WEEK, "  CHICKEN   chili ", "Steps.")
        assert repo.meal_instructions(WEEK, "chicken chili") == "Steps."

    def test_unsaved_meal_reads_as_none(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Chicken chili"))
        assert repo.meal_instructions(WEEK, "Chicken chili") is None

    def test_instructions_for_week_omits_null_rows(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Chicken chili", "Miso cod"))
        repo.save_meal_instructions(WEEK, "Miso cod", "Broil it.")
        assert repo.instructions_for_week(WEEK) == {"miso cod": "Broil it."}

    def test_unknown_week_raises(self, repo: HistoryRepo) -> None:
        with pytest.raises(InstructionsError) as caught:
            repo.save_meal_instructions("2020-W01", "Chicken chili", "Steps.")
        assert caught.value.code == "unknown_week"

    def test_unknown_meal_raises(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Chicken chili"))
        with pytest.raises(InstructionsError) as caught:
            repo.save_meal_instructions(WEEK, "Beef wellington", "Steps.")
        assert caught.value.code == "unknown_meal_name"


class TestReacceptanceCarryForward:
    def test_surviving_meals_keep_their_instructions(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Chicken chili", "Miso cod"))
        repo.save_meal_instructions(WEEK, "Chicken chili", "Brown the chicken.")
        repo.save_meal_instructions(WEEK, "Miso cod", "Broil it.")

        # The user swaps one meal mid-week and re-accepts.
        accept(repo, plan_with("Chicken chili", "Braised short ribs"))

        assert repo.meal_instructions(WEEK, "Chicken chili") == "Brown the chicken."
        assert repo.meal_instructions(WEEK, "Braised short ribs") is None
        assert set(repo.instructions_for_week(WEEK)) == {"chicken chili"}

    def test_dropped_meal_does_not_resurrect(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Miso cod"))
        repo.save_meal_instructions(WEEK, "Miso cod", "Broil it.")
        accept(repo, plan_with("Chicken chili"))
        accept(repo, plan_with("Miso cod"))
        assert repo.meal_instructions(WEEK, "Miso cod") is None


class TestWeekNavigation:
    def test_walks_accepted_weeks_skipping_gaps(self, repo: HistoryRepo) -> None:
        for week_id in ("2026-W28", "2026-W31"):
            plan = plan_with("Chicken chili").model_copy(update={"week_id": week_id})
            accept(repo, plan)

        assert repo.previous_accepted_week("2026-W31") == "2026-W28"
        assert repo.previous_accepted_week("2026-W28") is None
        assert repo.next_accepted_week("2026-W28") == "2026-W31"
        assert repo.next_accepted_week("2026-W31") is None
        # A current week with no plan of its own still finds history behind it.
        assert repo.previous_accepted_week("2026-W33") == "2026-W31"


class TestPlanForWeek:
    def test_returns_the_plan_in_its_own_meal_order(self, repo: HistoryRepo) -> None:
        accept(repo, plan_with("Zucchini boats", "Chicken chili"))
        stored = repo.plan_for_week(WEEK)
        assert stored is not None
        assert [m.name for m in stored.meals] == ["Zucchini boats", "Chicken chili"]
        assert [m.meal_name for m in repo.meals_for_week(WEEK)] == [
            "Chicken chili",
            "Zucchini boats",
        ], "meals_for_week is alphabetical — the cookbook must not use it"

    def test_missing_week_is_none(self, repo: HistoryRepo) -> None:
        assert repo.plan_for_week("2020-W01") is None
