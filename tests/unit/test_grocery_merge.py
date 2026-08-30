"""Unit tests for deterministic grocery merging.

Name normalization, U.S. customary unit conversion, the display-unit
ladder, package (can/jar/bag) math, compound quantities for unmergeable
families, and the guarantee that each normalized ingredient appears
exactly once.
"""

from typing import Any

from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.grocery import (
    build_grocery_list,
    normalize_ingredient_name,
    pluralize_ingredient_name,
)


def ingredient(
    name: str,
    quantity: float,
    unit: str,
    price: float = 1.0,
    package: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "quantity": quantity,
        "unit": unit,
        "package": package,
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


def quantities(plan: WeeklyPlan, name: str) -> list[tuple[float, str]]:
    item = next(i for i in build_grocery_list(plan).items if i.name == name)
    return [(q.amount, q.unit) for q in item.quantities]


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


class TestPluralization:
    def test_last_word_pluralized(self) -> None:
        assert pluralize_ingredient_name("yellow onion") == "yellow onions"
        assert pluralize_ingredient_name("garlic clove") == "garlic cloves"

    def test_sibilant_endings_take_es(self) -> None:
        assert pluralize_ingredient_name("squash") == "squashes"
        assert pluralize_ingredient_name("tomato") == "tomatoes"

    def test_consonant_y_becomes_ies(self) -> None:
        assert pluralize_ingredient_name("berry") == "berries"

    def test_vowel_y_takes_s(self) -> None:
        assert pluralize_ingredient_name("bay") == "bays"

    def test_already_plural_is_left_alone(self) -> None:
        assert pluralize_ingredient_name("eggs") == "eggs"


class TestDisplayUnitLadder:
    """The code picks the display unit from the merged total, not from
    whichever meal happened to list the ingredient first."""

    def test_weight_promotes_to_pounds_at_sixteen_ounces(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("chicken thighs", 1.0, "lb", 4.0)]),
                meal("B", [ingredient("chicken thighs", 8.0, "oz", 2.0)]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "chicken thighs") == [(1.5, "lb")]

    def test_weight_under_a_pound_stays_ounces(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("walnuts", 0.25, "lb")]),
                meal("B", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "walnuts") == [(4.0, "oz")]

    def test_teaspoons_promote_to_a_tablespoon(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("cumin", 2.0, "tsp")]),
                meal("B", [ingredient("cumin", 1.0, "tsp")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "cumin") == [(1.0, "tbsp")]

    def test_tablespoons_and_fluid_ounces_merge_to_one_unit(self) -> None:
        # Issue #23: 5 tbsp of a sauce plus 2 fl oz of it is one number.
        plan = plan_of(
            [
                meal("A", [ingredient("soy sauce", 5.0, "tbsp")]),
                meal("B", [ingredient("soy sauce", 2.0, "fl oz")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "soy sauce") == [(4.5, "fl oz")]

    def test_cups_and_tablespoons_merge(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("olive oil", 1.0, "cup")]),
                meal("B", [ingredient("olive oil", 4.0, "tbsp")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "olive oil") == [(1.25, "cup")]

    def test_pint_is_accepted_but_displayed_in_cups(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("chicken stock", 1.0, "pint")]),
                meal("B", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "chicken stock") == [(2.0, "cup")]

    def test_large_volume_promotes_to_quarts(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("chicken stock", 6.0, "cup")]),
                meal("B", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "chicken stock") == [(1.5, "quart")]

    def test_tiny_volume_stays_teaspoons(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("saffron", 0.5, "tsp")]),
                meal("B", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "saffron") == [(0.5, "tsp")]

    def test_count_units_merge_and_keep_count(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("egg", 4.0, "count")]),
                meal("B", [ingredient("eggs", 6.0, "count")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(plan, "egg") == [(10.0, "count")]

    def test_display_unit_is_independent_of_meal_order(self) -> None:
        forward = plan_of(
            [
                meal("A", [ingredient("soy sauce", 2.0, "fl oz")]),
                meal("B", [ingredient("soy sauce", 5.0, "tbsp")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        reversed_ = plan_of(
            [
                meal("B", [ingredient("soy sauce", 5.0, "tbsp")]),
                meal("A", [ingredient("soy sauce", 2.0, "fl oz")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        assert quantities(forward, "soy sauce") == quantities(reversed_, "soy sauce")


CAN_15_OZ = {"form": "can", "size_amount": 15.0, "size_unit": "oz"}


class TestPackages:
    def test_whole_packages_are_rounded_up(self) -> None:
        plan = plan_of(
            [
                meal(
                    "A",
                    [ingredient("kidney beans", 30.0, "oz", 2.0, package=CAN_15_OZ)],
                ),
                meal(
                    "B",
                    [ingredient("kidney beans", 8.0, "oz", 1.0, package=CAN_15_OZ)],
                ),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        beans = next(
            i for i in build_grocery_list(plan).items if i.name == "kidney beans"
        )
        assert beans.package is not None
        # 38 oz needs three 15 oz cans.
        assert beans.package.packages == 3
        assert (beans.package.form, beans.package.size_amount) == ("can", 15.0)
        # The package's own unit wins the display, so the line reads
        # '3 x 15 oz can (38 oz)' rather than promoting to pounds.
        assert [(q.amount, q.unit) for q in beans.quantities] == [(38.0, "oz")]

    def test_exact_multiple_buys_no_extra_package(self) -> None:
        plan = plan_of(
            [
                meal(
                    "A",
                    [ingredient("kidney beans", 45.0, "oz", 3.0, package=CAN_15_OZ)],
                ),
                meal("B", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        beans = next(
            i for i in build_grocery_list(plan).items if i.name == "kidney beans"
        )
        assert beans.package is not None
        assert beans.package.packages == 3

    def test_first_declared_package_wins(self) -> None:
        plan = plan_of(
            [
                meal(
                    "A",
                    [ingredient("kidney beans", 15.0, "oz", 1.0, package=CAN_15_OZ)],
                ),
                meal(
                    "B",
                    [
                        ingredient(
                            "kidney beans",
                            15.0,
                            "oz",
                            1.0,
                            package={
                                "form": "can",
                                "size_amount": 28.0,
                                "size_unit": "oz",
                            },
                        )
                    ],
                ),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        beans = next(
            i for i in build_grocery_list(plan).items if i.name == "kidney beans"
        )
        assert beans.package is not None
        assert beans.package.size_amount == 15.0
        assert beans.package.packages == 2

    def test_package_in_a_different_family_is_dropped(self) -> None:
        plan = plan_of(
            [
                meal(
                    "A",
                    [
                        ingredient(
                            "tomato puree",
                            2.0,
                            "cup",
                            2.0,
                            package={
                                "form": "can",
                                "size_amount": 15.0,
                                "size_unit": "oz",
                            },
                        )
                    ],
                ),
                meal("B", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        puree = next(
            i for i in build_grocery_list(plan).items if i.name == "tomato puree"
        )
        assert puree.package is None
        assert [(q.amount, q.unit) for q in puree.quantities] == [(2.0, "cup")]

    def test_items_without_a_package_report_none(self) -> None:
        plan = plan_of([meal("A", [ingredient("rice", 1.0, "cup")])])
        assert build_grocery_list(plan).items[0].package is None


class TestUnmergeableUnits:
    def test_cross_family_quantities_render_compound(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("crushed tomatoes", 2.0, "cup", 2.0)]),
                meal("B", [ingredient("crushed tomatoes", 8.0, "oz", 1.5)]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        tomatoes = next(
            i for i in build_grocery_list(plan).items if i.name == "crushed tomatoes"
        )
        assert [(q.amount, q.unit) for q in tomatoes.quantities] == [
            (2.0, "cup"),
            (8.0, "oz"),
        ]
        # Still exactly one line item, with the prices combined.
        assert tomatoes.estimated_price_usd == 3.5


class TestExactlyOnce:
    def test_each_normalized_ingredient_appears_exactly_once(self) -> None:
        shared = [
            ingredient("Olive Oil", 2.0, "tbsp"),
            ingredient("garlic cloves", 2.0, "count"),
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
        assert names == ["olive oil", "garlic cloves", "chicken thighs", "salmon"]
        # 2 + 2 + 1 tbsp is 5 tbsp, which the ladder shows as fluid ounces.
        assert [(q.amount, q.unit) for q in grocery.items[0].quantities] == [
            (2.5, "fl oz")
        ]

    def test_item_order_is_first_appearance(self) -> None:
        plan = plan_of(
            [
                meal("A", [ingredient("rice", 1.0, "cup")]),
                meal("B", [ingredient("black beans", 1.0, "lb")]),
                meal("C", [ingredient("rice", 1.0, "cup")]),
            ]
        )
        grocery = build_grocery_list(plan)
        assert [item.name for item in grocery.items] == ["rice", "black beans"]


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
        chicken = next(
            i for i in build_grocery_list(plan).items if i.name == "chicken thighs"
        )
        assert [(q.amount, q.unit) for q in chicken.quantities] == [(3.0, "lb")]
        assert chicken.estimated_price_usd == 12.0
