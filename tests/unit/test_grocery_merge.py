"""Unit tests for deterministic grocery merging.

Name normalization, unit-family conversion, compound quantities for
unmergeable units, and the guarantee that each normalized ingredient
appears exactly once.
"""

from typing import Any

from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.grocery import build_grocery_list, normalize_ingredient_name


def ingredient(
    name: str, quantity: float, unit: str, price: float = 1.0
) -> dict[str, Any]:
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "estimated_price_usd": price,
    }


def meal(
    name: str,
    ingredients: list[dict[str, Any]],
    *,
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": "chicken",
        "prep_minutes": 30,
        "servings": 1,
        "batch": batch,
        "stretch": stretch,
        "source_url": None,
        "user_requested_repeat": False,
        "ingredients": ingredients,
    }


def plan_of(
    meals: list[dict[str, Any]],
    *,
    lunch_count: int = 2,
    weekly_budget_usd: float | None = None,
) -> WeeklyPlan:
    return WeeklyPlan.model_validate(
        {
            "week_id": "2026-W30",
            "dinner_count": len(meals),
            "lunch_count": lunch_count,
            "diet_type": None,
            "default_servings": 1,
            "weekly_budget_usd": weekly_budget_usd,
            "meals": meals,
        }
    )


class TestNameNormalization:
    def test_casefold_trim_and_collapse(self) -> None:
        assert normalize_ingredient_name("  Olive  OIL ") == "olive oil"

    def test_simple_plural_singularized(self) -> None:
        assert normalize_ingredient_name("eggs") == normalize_ingredient_name("egg")
        assert normalize_ingredient_name("chicken thighs") == normalize_ingredient_name(
            "chicken thigh"
        )

    def test_oes_plural_singularized(self) -> None:
        assert normalize_ingredient_name("tomatoes") == normalize_ingredient_name(
            "tomato"
        )

    def test_ies_plural_singularized(self) -> None:
        assert normalize_ingredient_name("berries") == normalize_ingredient_name(
            "berry"
        )

    def test_double_s_not_stripped(self) -> None:
        assert normalize_ingredient_name("watercress") == "watercress"

    def test_distinct_names_stay_distinct(self) -> None:
        assert normalize_ingredient_name("beef chili") != normalize_ingredient_name(
            "chicken chili"
        )


class TestUnitFamilyConversion:
    def test_mass_units_merge_into_first_seen_unit(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("chicken thighs", 1.0, "lb", 4.0)]),
                meal("B", [ingredient("chicken thighs", 8.0, "oz", 2.0)]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        chicken = next(i for i in grocery.items if i.name == "chicken thighs")
        assert [(q.amount, q.unit) for q in chicken.quantities] == [(1.5, "lb")]
        assert chicken.estimated_price_usd == 6.0

    def test_metric_mass_merges(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("flour", 500.0, "g")]),
                meal("B", [ingredient("flour", 1.0, "kg")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        flour = next(i for i in grocery.items if i.name == "flour")
        assert [(q.amount, q.unit) for q in flour.quantities] == [(1500.0, "g")]

    def test_volume_units_merge(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("olive oil", 1.0, "cup")]),
                meal("B", [ingredient("olive oil", 4.0, "tbsp")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        oil = next(i for i in grocery.items if i.name == "olive oil")
        assert [(q.amount, q.unit) for q in oil.quantities] == [(1.25, "cup")]

    def test_count_units_merge(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("egg", 4.0, "count")]),
                meal("B", [ingredient("eggs", 6.0, "count")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        eggs = next(i for i in grocery.items if i.name == "egg")
        assert [(q.amount, q.unit) for q in eggs.quantities] == [(10.0, "count")]

    def test_same_freeform_unit_merges(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("black beans", 1.0, "can")]),
                meal("B", [ingredient("black beans", 2.0, "can")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        beans = next(i for i in grocery.items if i.name == "black beans")
        assert [(q.amount, q.unit) for q in beans.quantities] == [(3.0, "can")]


class TestUnmergeableUnits:
    def test_cross_family_quantities_render_compound(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("crushed tomatoes", 2.0, "cup", 2.0)]),
                meal("B", [ingredient("crushed tomatoes", 1.0, "can", 1.5)]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        tomatoes = next(i for i in grocery.items if i.name == "crushed tomatoes")
        assert [(q.amount, q.unit) for q in tomatoes.quantities] == [
            (2.0, "cup"),
            (1.0, "can"),
        ]
        # Still exactly one line item, with the prices combined.
        assert tomatoes.estimated_price_usd == 3.5


class TestExactlyOnce:
    def test_each_normalized_ingredient_appears_exactly_once(self) -> None:
        shared = [
            ingredient("Olive Oil", 2.0, "tbsp"),
            ingredient("garlic", 2.0, "count"),
        ]
        plan = plan_of(
            [
                meal("A", [*shared, ingredient("chicken thighs", 1.0, "lb")]),
                meal("B", [*shared, ingredient("salmon", 1.0, "lb")]),
                meal("C", [ingredient("olive  oil", 1.0, "tbsp")]),
            ]
        )
        grocery = build_grocery_list(plan)
        names = [item.name for item in grocery.items]
        assert len(names) == len(set(names)), "each ingredient exactly once"
        assert names == ["olive oil", "garlic", "chicken thighs", "salmon"]
        oil = grocery.items[0]
        assert [(q.amount, q.unit) for q in oil.quantities] == [(5.0, "tbsp")]

    def test_item_order_is_first_appearance(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("rice", 1.0, "cup")]),
                meal("B", [ingredient("beans", 1.0, "can")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        assert [item.name for item in grocery.items] == ["rice", "beans"]


class TestBatchCoverageScaling:
    def test_batch_meal_quantities_pass_through_at_full_coverage(self) -> None:
        # The model scales batch ingredients to lunches + dinner already;
        # the merge must use those quantities verbatim.
        plan = plan_of(
            [
                meal(
                    "Chicken chili",
                    [ingredient("chicken thighs", 3.0, "lb", 12.0)],
                    batch={"lunches_covered": 2, "total_portions": 3},
                ),
                meal("B", [ingredient("salmon", 1.0, "lb")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        chicken = next(i for i in grocery.items if i.name == "chicken thighs")
        assert [(q.amount, q.unit) for q in chicken.quantities] == [(3.0, "lb")]
        assert chicken.estimated_price_usd == 12.0
