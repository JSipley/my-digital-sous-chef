"""Unit tests for the 4-week repetition window and technique novelty (T042).

Normalized-name matching per the clarified rule (chicken chili twice =
repeat; beef chili ≠ chicken chili), cooked-only counting, explicit-repeat
and announced-relaxation bypasses, the 4-ISO-week boundary, and stretch
techniques judged against cooked history only.
"""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.grocery import build_grocery_list
from sous_chef.services.history_repo import HistoryRepo
from sous_chef.services.plan_validator import validate_plan


def meal(
    name: str,
    *,
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
    user_requested_repeat: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": "chicken",
        "prep_minutes": 30,
        "servings": 1,
        "batch": batch,
        "stretch": stretch,
        "source_url": None,
        "user_requested_repeat": user_requested_repeat,
        "ingredients": [
            {
                "name": "chicken",
                "quantity": 1.0,
                "unit": "lb",
                "estimated_price_usd": 8.0,
            }
        ],
    }


def plan_for(week_id: str, meals: list[dict[str, Any]] | None = None) -> WeeklyPlan:
    if meals is None:
        meals = [
            meal(
                "Chicken chili",
                batch={"lunches_covered": 2, "total_portions": 3},
            ),
            meal("Seared salmon", stretch={"technique": "searing"}),
            meal("Turkey stir-fry"),
        ]
    return WeeklyPlan.model_validate(
        {
            "week_id": week_id,
            "dinner_count": 3,
            "lunch_count": 2,
            "diet_type": None,
            "default_servings": 1,
            "weekly_budget_usd": None,
            "meals": meals,
        }
    )


def error_codes(errors: list[Any]) -> list[str]:
    return [error.code for error in errors]


class TestRepeatedDishValidator:
    def test_same_normalized_name_is_a_repeat(self) -> None:
        errors = validate_plan(
            plan_for("2026-W30"),
            cooked_names_last_4_weeks=["chicken chili"],
        )
        assert error_codes(errors) == ["repeated_dish"]
        assert "chicken chili" in errors[0].message

    def test_casefold_and_whitespace_insensitive_matching(self) -> None:
        plan = plan_for(
            "2026-W30",
            meals=[
                meal(
                    "  CHICKEN  Chili ",
                    batch={"lunches_covered": 2, "total_portions": 3},
                ),
                meal("Seared salmon", stretch={"technique": "searing"}),
                meal("Turkey stir-fry"),
            ],
        )
        errors = validate_plan(plan, cooked_names_last_4_weeks=["chicken chili"])
        assert error_codes(errors) == ["repeated_dish"]

    def test_different_dish_name_is_not_a_repeat(self) -> None:
        # beef chili ≠ chicken chili per the clarified same-named-dish rule.
        errors = validate_plan(
            plan_for("2026-W30"),
            cooked_names_last_4_weeks=["beef chili"],
        )
        assert errors == []

    def test_user_requested_repeat_bypasses_the_window(self) -> None:
        plan = plan_for(
            "2026-W30",
            meals=[
                meal(
                    "Chicken chili",
                    batch={"lunches_covered": 2, "total_portions": 3},
                    user_requested_repeat=True,
                ),
                meal("Seared salmon", stretch={"technique": "searing"}),
                meal("Turkey stir-fry"),
            ],
        )
        errors = validate_plan(plan, cooked_names_last_4_weeks=["chicken chili"])
        assert errors == []

    def test_announced_relaxation_bypasses_the_window(self) -> None:
        errors = validate_plan(
            plan_for("2026-W30"),
            cooked_names_last_4_weeks=["chicken chili"],
            repetition_relaxed=True,
        )
        assert errors == []

    def test_all_offending_names_listed_in_one_message(self) -> None:
        errors = validate_plan(
            plan_for("2026-W30"),
            cooked_names_last_4_weeks=["chicken chili", "turkey stir-fry"],
        )
        assert error_codes(errors) == ["repeated_dish"]
        assert "chicken chili" in errors[0].message
        assert "turkey stir-fry" in errors[0].message


class TestTechniqueNovelty:
    def test_cooked_technique_is_not_new(self) -> None:
        errors = validate_plan(plan_for("2026-W30"), known_techniques=["searing"])
        assert error_codes(errors) == ["technique_not_new"]
        assert "searing" in errors[0].message

    def test_technique_matching_is_casefolded(self) -> None:
        errors = validate_plan(plan_for("2026-W30"), known_techniques=[" Searing "])
        assert error_codes(errors) == ["technique_not_new"]

    def test_unknown_technique_is_new(self) -> None:
        errors = validate_plan(plan_for("2026-W30"), known_techniques=["braising"])
        assert errors == []


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "window.db")


def accept_week(repo: HistoryRepo, week_id: str) -> WeeklyPlan:
    plan = plan_for(week_id)
    repo.save_accepted_plan(
        plan,
        build_grocery_list(plan),
        accepted_at=datetime(2026, 7, 1, tzinfo=UTC),
    )
    return plan


class TestCookedHistoryQueries:
    def test_only_cooked_rows_count(self, repo: HistoryRepo) -> None:
        accept_week(repo, "2026-W29")
        repo.record_checkin("2026-W29", ["Chicken chili"], user_skipped=False)
        cooked = repo.cooked_dish_names_before("2026-W30")
        assert cooked == ["chicken chili"]
        # Skipped meals are re-proposable: they never enter the cooked set.
        assert "seared salmon" not in cooked
        assert "turkey stir-fry" not in cooked

    def test_planned_rows_do_not_count(self, repo: HistoryRepo) -> None:
        accept_week(repo, "2026-W29")
        assert repo.cooked_dish_names_before("2026-W30") == []

    def test_four_iso_week_boundary(self, repo: HistoryRepo) -> None:
        # W25 is five weeks before W30 — outside its window; W26 is inside.
        old_meals = [
            meal("Beef stew", batch={"lunches_covered": 2, "total_portions": 3}),
            meal("Poached cod", stretch={"technique": "poaching"}),
            meal("Lamb curry"),
        ]
        old_plan = plan_for("2026-W25", meals=old_meals)
        repo.save_accepted_plan(
            old_plan,
            build_grocery_list(old_plan),
            accepted_at=datetime(2026, 6, 20, tzinfo=UTC),
        )
        repo.record_checkin("2026-W25", [], user_skipped=True)
        accept_week(repo, "2026-W26")
        repo.record_checkin("2026-W26", [], user_skipped=True)

        cooked_for_w30 = repo.cooked_dish_names_before("2026-W30")
        assert cooked_for_w30 == ["chicken chili", "seared salmon", "turkey stir-fry"]
        assert "beef stew" not in cooked_for_w30, "W25 is outside the 4-week window"
        # From W27, both weeks fall inside the window.
        assert "beef stew" in repo.cooked_dish_names_before("2026-W27")
        # From W31, even W26 has aged out.
        assert repo.cooked_dish_names_before("2026-W31") == []


class TestTechniqueHistoryQueries:
    def test_only_cooked_stretch_techniques_are_known(self, repo: HistoryRepo) -> None:
        accept_week(repo, "2026-W29")
        # Salmon (the stretch meal) was skipped: its technique stays new.
        repo.record_checkin("2026-W29", ["Chicken chili"], user_skipped=False)
        assert repo.cooked_techniques() == []

    def test_cooked_stretch_technique_is_known(self, repo: HistoryRepo) -> None:
        accept_week(repo, "2026-W29")
        repo.record_checkin("2026-W29", ["Seared salmon"], user_skipped=False)
        assert repo.cooked_techniques() == ["searing"]
