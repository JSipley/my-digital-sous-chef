"""Unit tests for how quantities read on a phone screen (issue #23).

`count` ingredients drop the unit token and pluralize ('1 lemon',
'3 yellow onions'); packaged goods show how many packages to buy next to
the real total.
"""

from typing import Any

from sous_chef.bot.formatting import escape, render_grocery_list, render_instructions
from sous_chef.models.grocery import GroceryItem, GroceryList, PackageCount, Quantity
from sous_chef.models.plan import WeeklyPlan


def item(
    name: str,
    quantities: list[tuple[float, str]],
    price: float = 1.0,
    package: dict[str, Any] | None = None,
) -> GroceryItem:
    return GroceryItem(
        name=name,
        quantities=[Quantity(amount=amount, unit=unit) for amount, unit in quantities],
        package=None if package is None else PackageCount.model_validate(package),
        estimated_price_usd=price,
    )


def rendered(*items: GroceryItem) -> str:
    grocery = GroceryList(
        items=list(items), estimated_total_usd=1.0, budget_delta_usd=None
    )
    return "\n".join(render_grocery_list(grocery, None))


class TestCountRendering:
    def test_single_count_reads_as_one_thing(self) -> None:
        assert "1 lemon" in rendered(item("lemon", [(1.0, "count")]))

    def test_the_word_count_never_appears(self) -> None:
        assert "count" not in rendered(item("lemon", [(1.0, "count")]))

    def test_multiple_counts_pluralize_the_name(self) -> None:
        text = rendered(item("yellow onion", [(3.0, "count")]))
        assert "3 yellow onions" in text

    def test_qualified_count_name_pluralizes_its_last_word(self) -> None:
        assert "6 garlic cloves" in rendered(item("garlic clove", [(6.0, "count")]))

    def test_measured_units_keep_the_name_first(self) -> None:
        text = rendered(item("chicken thighs", [(1.5, "lb")]))
        assert escape("chicken thighs — 1.5 lb") in text


class TestPackageRendering:
    def test_packages_to_buy_shown_with_the_real_total(self) -> None:
        text = rendered(
            item(
                "kidney beans",
                [(38.0, "oz")],
                package={
                    "form": "can",
                    "size_amount": 15.0,
                    "size_unit": "oz",
                    "packages": 3,
                },
            )
        )
        assert escape("kidney beans — 3 x 15 oz can (38 oz)") in text

    def test_single_package_is_not_pluralized(self) -> None:
        text = rendered(
            item(
                "tomato paste",
                [(6.0, "oz")],
                package={
                    "form": "can",
                    "size_amount": 6.0,
                    "size_unit": "oz",
                    "packages": 1,
                },
            )
        )
        assert escape("tomato paste — 1 x 6 oz can") in text


def plan_with_ingredients(ingredients: list[dict[str, Any]]) -> WeeklyPlan:
    return WeeklyPlan.model_validate(
        {
            "week_id": "2026-W30",
            "dinner_count": 1,
            "lunch_count": 0,
            "diet_type": None,
            "default_servings": 1,
            "weekly_budget_usd": None,
            "meals": [
                {
                    "name": "Chicken chili",
                    "primary_protein": "chicken",
                    "prep_minutes": 30,
                    "servings": 1,
                    "batch": {"lunches_covered": 0, "total_portions": 1},
                    "stretch": None,
                    "source_url": None,
                    "user_requested_repeat": False,
                    "ingredients": ingredients,
                }
            ],
        }
    )


class TestInstructionIngredientLines:
    def test_count_ingredients_read_as_plain_english(self) -> None:
        plan = plan_with_ingredients(
            [
                {
                    "name": "garlic clove",
                    "quantity": 4.0,
                    "unit": "count",
                    "package": None,
                    "estimated_price_usd": 0.4,
                },
                {
                    "name": "lemon",
                    "quantity": 1.0,
                    "unit": "count",
                    "package": None,
                    "estimated_price_usd": 0.5,
                },
                {
                    "name": "chicken thighs",
                    "quantity": 1.5,
                    "unit": "lb",
                    "package": None,
                    "estimated_price_usd": 7.5,
                },
            ]
        )
        text = "\n".join(render_instructions(plan.meals[0], "Cook it."))
        assert "4 garlic cloves" in text
        assert "1 lemon" in text
        assert escape("1.5 lb chicken thighs") in text
        assert "count" not in text
