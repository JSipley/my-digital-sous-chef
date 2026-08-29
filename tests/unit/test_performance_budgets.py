"""Performance budget assertions for non-LLM paths.

Grocery merge, plan validation, and history
queries each complete well under 200 ms at this project's data scale.
"""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.grocery import build_grocery_list
from sous_chef.services.history_repo import HistoryRepo
from sous_chef.services.plan_validator import validate_plan

BUDGET_SECONDS = 0.2


def elapsed(operation: Callable[[], object]) -> float:
    started = time.perf_counter()
    operation()
    return time.perf_counter() - started


def realistic_plan() -> WeeklyPlan:
    def meal(index: int) -> dict[str, Any]:
        return {
            "name": f"Meal {index}",
            "primary_protein": "chicken",
            "prep_minutes": 40,
            "servings": 2,
            "batch": (
                {"lunches_covered": 5, "total_portions": 12} if index == 0 else None
            ),
            "stretch": {"technique": f"technique-{index}"} if index == 1 else None,
            "source_url": None,
            "user_requested_repeat": False,
            "ingredients": [
                {
                    "name": f"ingredient {index}-{n}",
                    "quantity": 1.0 + n,
                    "unit": ["g", "kg", "cup", "tbsp", "count", "can"][n % 6],
                    "estimated_price_usd": 2.5,
                }
                for n in range(15)
            ],
        }

    return WeeklyPlan.model_validate(
        {
            "week_id": "2026-W30",
            "dinner_count": 4,
            "lunch_count": 5,
            "diet_type": None,
            "default_servings": 2,
            "weekly_budget_usd": 90.0,
            "meals": [meal(i) for i in range(4)],
        }
    )


class TestNonLlmBudgets:
    def test_grocery_merge_under_budget(self) -> None:
        plan = realistic_plan()
        assert elapsed(lambda: build_grocery_list(plan)) < BUDGET_SECONDS

    def test_plan_validation_under_budget(self) -> None:
        plan = realistic_plan()
        cooked = [f"dish {i}" for i in range(50)]
        techniques = [f"technique {i}" for i in range(50)]
        assert (
            elapsed(
                lambda: validate_plan(
                    plan,
                    cooked_names_last_4_weeks=cooked,
                    known_techniques=techniques,
                )
            )
            < BUDGET_SECONDS
        )

    def test_history_queries_under_budget(self, tmp_path: Path) -> None:
        repo = HistoryRepo(tmp_path / "perf.db")
        plan = realistic_plan()
        # A year of accepted, fully cooked weeks.
        for week in range(1, 53):
            week_id = f"2026-W{week:02d}"
            weekly = plan.model_copy(update={"week_id": week_id})
            repo.save_accepted_plan(
                weekly,
                build_grocery_list(weekly),
                accepted_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
            repo.record_checkin(week_id, [], user_skipped=True)

        def all_queries() -> None:
            repo.finalize_weeks_before("2026-W52")
            repo.cooked_dish_names_before("2026-W52")
            repo.cooked_techniques()
            repo.weeks_summary(8)
            repo.pending_checkin_week_id()
            repo.find_meals_by_normalized_name("meal 1")

        assert elapsed(all_queries) < BUDGET_SECONDS
