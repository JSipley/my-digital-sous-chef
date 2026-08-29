"""Unit tests for estimated-bill totaling and budget comparison.

The bill is the computed sum of item price estimates — never generated as
text. Nominal sums, empty/zero-price boundaries, rounding determinism, and
budget-delta math (over-budget plans report an exact overage,
they are never rejected).
"""

from typing import Any

from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.grocery import build_grocery_list
from sous_chef.services.plan_validator import validate_plan


def ingredient(
    name: str, price: float, quantity: float = 1.0, unit: str = "count"
) -> dict[str, Any]:
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "estimated_price_usd": price,
    }


def meal(name: str, ingredients: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": "chicken",
        "prep_minutes": 30,
        "servings": 1,
        "batch": None,
        "stretch": None,
        "source_url": None,
        "user_requested_repeat": False,
        "ingredients": ingredients,
    }


def plan_of(
    meals: list[dict[str, Any]], *, weekly_budget_usd: float | None = None
) -> WeeklyPlan:
    return WeeklyPlan.model_validate(
        {
            "week_id": "2026-W30",
            "dinner_count": max(len(meals), 3),
            "lunch_count": 0,
            "diet_type": None,
            "default_servings": 1,
            "weekly_budget_usd": weekly_budget_usd,
            "meals": meals,
        }
    )


class TestBillTotals:
    def test_total_is_sum_of_item_prices(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("chicken", 8.0), ingredient("rice", 2.5)]),
                meal("B", [ingredient("salmon", 11.25)]),
            ]
        )
        grocery = build_grocery_list(plan)
        assert grocery.estimated_total_usd == 21.75
        assert grocery.estimated_total_usd == round(
            sum(item.estimated_price_usd for item in grocery.items), 2
        )

    def test_merged_ingredient_prices_sum_into_one_item(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("olive oil", 3.0)]),
                meal("B", [ingredient("olive oil", 2.0)]),
            ]
        )
        grocery = build_grocery_list(plan)
        assert len(grocery.items) == 1
        assert grocery.items[0].estimated_price_usd == 5.0
        assert grocery.estimated_total_usd == 5.0

    def test_zero_price_ingredients_total_zero(self) -> None:
        plan = plan_of([meal("A", [ingredient("water", 0.0), ingredient("salt", 0.0)])])
        grocery = build_grocery_list(plan)
        assert grocery.estimated_total_usd == 0.0

    def test_no_meals_totals_zero_with_no_items(self) -> None:
        grocery = build_grocery_list(plan_of([]))
        assert grocery.items == []
        assert grocery.estimated_total_usd == 0.0

    def test_totals_are_rounded_to_cents(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("a", 0.1), ingredient("b", 0.2)]),
                meal("B", [ingredient("c", 0.3)]),
            ]
        )
        grocery = build_grocery_list(plan)
        assert grocery.estimated_total_usd == 0.6

    def test_no_budget_means_no_delta(self) -> None:
        grocery = build_grocery_list(plan_of([meal("A", [ingredient("a", 5.0)])]))
        assert grocery.budget_delta_usd is None


class TestBudgetComparison:
    def test_under_budget_delta_is_negative(self) -> None:
        plan = plan_of(
            [meal("A", [ingredient("chicken", 54.5)])], weekly_budget_usd=60.0
        )
        grocery = build_grocery_list(plan)
        assert grocery.budget_delta_usd == -5.5

    def test_overage_reports_exact_amount(self) -> None:
        plan = plan_of([meal("A", [ingredient("wagyu", 74.5)])], weekly_budget_usd=60.0)
        grocery = build_grocery_list(plan)
        assert grocery.budget_delta_usd == 14.5

    def test_exactly_at_budget_delta_is_zero(self) -> None:
        plan = plan_of(
            [meal("A", [ingredient("chicken", 60.0)])], weekly_budget_usd=60.0
        )
        grocery = build_grocery_list(plan)
        assert grocery.budget_delta_usd == 0.0

    def test_over_budget_plan_is_not_rejected_by_validators(self) -> None:
        # Nutrition wins — an over-budget plan is valid;
        # the overage is surfaced as data, never as a validation error.
        meals = [
            meal("Chicken chili", [ingredient("chicken", 99.0)])
            | {"batch": {"lunches_covered": 0, "total_portions": 1}},
            meal("Seared salmon", [ingredient("salmon", 88.0)])
            | {"stretch": {"technique": "searing"}},
            meal("Turkey stir-fry", [ingredient("turkey", 77.0)]),
        ]
        plan = plan_of(meals, weekly_budget_usd=10.0)
        grocery = build_grocery_list(plan)
        assert validate_plan(plan) == []
        assert grocery.budget_delta_usd == round(99.0 + 88.0 + 77.0 - 10.0, 2)
