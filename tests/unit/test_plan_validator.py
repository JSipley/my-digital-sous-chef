"""Unit tests for the deterministic plan validators."""

from typing import Any

from sous_chef.models.plan import WeeklyPlan
from sous_chef.services.plan_validator import PlanError, validate_plan


def make_meal(
    name: str = "Turkey stir-fry",
    *,
    primary_protein: str = "turkey",
    prep_minutes: int = 30,
    servings: int = 1,
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
    ingredients: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if ingredients is None:
        ingredients = [
            {
                "name": "turkey",
                "quantity": 1.0,
                "unit": "lb",
                "package": None,
                "estimated_price_usd": 6.0,
            }
        ]
    return {
        "name": name,
        "primary_protein": primary_protein,
        "prep_minutes": prep_minutes,
        "servings": servings,
        "batch": batch,
        "stretch": stretch,
        "source_url": None,
        "user_requested_repeat": False,
        "ingredients": ingredients,
    }


def make_plan(
    *,
    dinner_count: int = 3,
    lunch_count: int = 2,
    meals: list[dict[str, Any]] | None = None,
    **overrides: Any,
) -> WeeklyPlan:
    if meals is None:
        meals = [
            make_meal(
                "Chicken chili",
                primary_protein="chicken",
                batch={
                    "lunches_covered": lunch_count,
                    "total_portions": lunch_count + 1,
                },
            ),
            make_meal(
                "Seared salmon",
                primary_protein="salmon",
                stretch={"technique": "searing"},
            ),
            make_meal(),
        ]
    payload: dict[str, Any] = {
        "week_id": "2026-W30",
        "dinner_count": dinner_count,
        "lunch_count": lunch_count,
        "diet_type": None,
        "default_servings": 1,
        "weekly_budget_usd": None,
        "meals": meals,
        **overrides,
    }
    return WeeklyPlan.model_validate(payload)


def codes(plan: WeeklyPlan) -> set[str]:
    return {error.code for error in validate_plan(plan)}


class TestNominal:
    def test_valid_three_dinner_plan_passes(self) -> None:
        assert validate_plan(make_plan()) == []

    def test_valid_four_dinner_plan_passes(self) -> None:
        plan = make_plan(
            dinner_count=4,
            meals=[
                make_meal(
                    "Chicken chili",
                    batch={"lunches_covered": 2, "total_portions": 3},
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal("Beef tacos"),
                make_meal("Pork stir-fry"),
            ],
        )
        assert validate_plan(plan) == []

    def test_errors_carry_code_and_message(self) -> None:
        errors = validate_plan(make_plan(dinner_count=8))
        assert errors
        for error in errors:
            assert isinstance(error, PlanError)
            assert error.code
            assert error.message


class TestCounts:
    def test_dinner_count_below_range(self) -> None:
        plan = make_plan(dinner_count=0, meals=[])
        assert "dinner_count_out_of_range" in codes(plan)

    def test_dinner_count_above_range(self) -> None:
        assert "dinner_count_out_of_range" in codes(make_plan(dinner_count=8))

    def test_dinner_count_boundaries_pass(self) -> None:
        one_dinner = make_plan(
            dinner_count=1,
            meals=[
                make_meal(
                    "Chicken chili",
                    batch={"lunches_covered": 2, "total_portions": 3},
                )
            ],
        )
        seven_dinners = make_plan(
            dinner_count=7,
            meals=[
                make_meal(
                    "Chicken chili",
                    batch={"lunches_covered": 2, "total_portions": 3},
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                *[make_meal(f"Weeknight dish {n}") for n in range(5)],
            ],
        )
        assert validate_plan(one_dinner) == []
        assert validate_plan(seven_dinners) == []

    def test_lunch_count_below_range(self) -> None:
        assert "lunch_count_out_of_range" in codes(make_plan(lunch_count=-1))

    def test_lunch_count_above_range(self) -> None:
        assert "lunch_count_out_of_range" in codes(make_plan(lunch_count=8))

    def test_lunch_count_boundaries_pass(self) -> None:
        for lunch_count in (0, 7):
            plan = make_plan(
                lunch_count=lunch_count,
                meals=[
                    make_meal(
                        "Chicken chili",
                        batch={
                            "lunches_covered": lunch_count,
                            "total_portions": lunch_count + 1,
                        },
                    ),
                    make_meal("Seared salmon", stretch={"technique": "searing"}),
                    make_meal(),
                ],
            )
            assert validate_plan(plan) == []

    def test_meal_count_must_match_dinner_count(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
            ]
        )
        assert "meal_count_mismatch" in codes(plan)


class TestBatchAndStretchFlags:
    def test_missing_batch_meal(self) -> None:
        plan = make_plan(
            meals=[
                make_meal("A", stretch={"technique": "searing"}),
                make_meal("B"),
                make_meal("C"),
            ]
        )
        assert "batch_meal_count" in codes(plan)

    def test_two_batch_meals(self) -> None:
        plan = make_plan(
            meals=[
                make_meal("A", batch={"lunches_covered": 2, "total_portions": 3}),
                make_meal("B", batch={"lunches_covered": 2, "total_portions": 3}),
                make_meal("C", stretch={"technique": "searing"}),
            ]
        )
        assert "batch_meal_count" in codes(plan)

    def test_missing_stretch_meal(self) -> None:
        plan = make_plan(
            meals=[
                make_meal("A", batch={"lunches_covered": 2, "total_portions": 3}),
                make_meal("B"),
                make_meal("C"),
            ]
        )
        assert "stretch_meal_count" in codes(plan)

    def test_two_stretch_meals(self) -> None:
        plan = make_plan(
            meals=[
                make_meal("A", batch={"lunches_covered": 2, "total_portions": 3}),
                make_meal("B", stretch={"technique": "searing"}),
                make_meal("C", stretch={"technique": "braising"}),
            ]
        )
        assert "stretch_meal_count" in codes(plan)

    def test_batch_and_stretch_on_same_meal_rejected(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "A",
                    batch={"lunches_covered": 2, "total_portions": 3},
                    stretch={"technique": "searing"},
                ),
                make_meal("B"),
                make_meal("C"),
            ]
        )
        assert "batch_stretch_same_meal" in codes(plan)

    def test_three_meals_with_flags_on_two_distinct_meals_passes(self) -> None:
        # Edge case: with 3 meals, two of the three carry the flags.
        assert validate_plan(make_plan()) == []


class TestSingleDinnerWeek:
    """At one dinner the batch meal stays; the stretch meal is not planned."""

    def test_single_batch_meal_and_no_stretch_passes(self) -> None:
        plan = make_plan(
            dinner_count=1,
            meals=[
                make_meal(
                    "Chicken chili",
                    batch={"lunches_covered": 2, "total_portions": 3},
                )
            ],
        )
        assert validate_plan(plan) == []

    def test_stretch_on_the_single_meal_is_rejected(self) -> None:
        # Exactly one fixable code: batch_stretch_same_meal must stay quiet,
        # or the model gets an error it cannot resolve at one dinner.
        plan = make_plan(
            dinner_count=1,
            meals=[
                make_meal(
                    "Chicken chili",
                    batch={"lunches_covered": 2, "total_portions": 3},
                    stretch={"technique": "searing"},
                )
            ],
        )
        assert codes(plan) == {"stretch_meal_count"}

    def test_missing_batch_meal_is_still_rejected(self) -> None:
        plan = make_plan(dinner_count=1, lunch_count=0, meals=[make_meal("A")])
        assert "batch_meal_count" in codes(plan)

    def test_lunches_are_covered_by_the_single_batch_meal(self) -> None:
        plan = make_plan(
            dinner_count=1,
            lunch_count=5,
            meals=[
                make_meal(
                    "Chicken chili",
                    servings=2,
                    batch={"lunches_covered": 5, "total_portions": 12},
                )
            ],
        )
        assert validate_plan(plan) == []


class TestBatchCoverage:
    def test_lunches_covered_must_equal_lunch_count(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 3, "total_portions": 4}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(),
            ]
        )
        assert "batch_coverage_mismatch" in codes(plan)

    def test_total_portions_must_cover_lunches_plus_dinner_times_servings(
        self,
    ) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 2}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(),
            ]
        )
        assert "batch_coverage_mismatch" in codes(plan)

    def test_total_portions_scales_with_servings(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili",
                    servings=2,
                    batch={"lunches_covered": 2, "total_portions": 6},
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(),
            ]
        )
        assert validate_plan(plan) == []

    def test_zero_lunch_batch_covers_dinner_night_only(self) -> None:
        plan = make_plan(
            lunch_count=0,
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 0, "total_portions": 1}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(),
            ],
        )
        assert validate_plan(plan) == []


class TestMealFields:
    def test_blank_primary_protein_is_missing_field(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(primary_protein="  "),
            ]
        )
        assert "missing_field" in codes(plan)

    def test_nonpositive_prep_minutes_is_invalid_value(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(prep_minutes=0),
            ]
        )
        assert "invalid_value" in codes(plan)

    def test_nonpositive_servings_is_invalid_value(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(servings=0),
            ]
        )
        assert "invalid_value" in codes(plan)

    def test_empty_ingredients_is_missing_field(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(ingredients=[]),
            ]
        )
        assert "missing_field" in codes(plan)

    def test_nonpositive_ingredient_quantity_is_invalid_value(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(
                    ingredients=[
                        {
                            "name": "turkey",
                            "quantity": 0,
                            "unit": "lb",
                            "package": None,
                            "estimated_price_usd": 6.0,
                        }
                    ]
                ),
            ]
        )
        assert "invalid_value" in codes(plan)

    def test_negative_ingredient_price_is_invalid_value(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(
                    ingredients=[
                        {
                            "name": "turkey",
                            "quantity": 1.0,
                            "unit": "lb",
                            "package": None,
                            "estimated_price_usd": -1.0,
                        }
                    ]
                ),
            ]
        )
        assert "invalid_value" in codes(plan)

    def test_blank_ingredient_name_is_missing_field(self) -> None:
        plan = make_plan(
            meals=[
                make_meal(
                    "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
                ),
                make_meal("Seared salmon", stretch={"technique": "searing"}),
                make_meal(
                    ingredients=[
                        {
                            "name": " ",
                            "quantity": 1.0,
                            "unit": "lb",
                            "package": None,
                            "estimated_price_usd": 6.0,
                        }
                    ]
                ),
            ]
        )
        assert "missing_field" in codes(plan)


def three_meals(ingredients: list[dict[str, Any]]) -> WeeklyPlan:
    """A valid three-dinner plan whose last meal carries `ingredients`."""
    return make_plan(
        meals=[
            make_meal(
                "Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}
            ),
            make_meal("Seared salmon", stretch={"technique": "searing"}),
            make_meal(ingredients=ingredients),
        ]
    )


def counted(name: str, package: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "quantity": 2.0,
        "unit": "count",
        "package": package,
        "estimated_price_usd": 1.0,
    }


class TestAmbiguousCountNames:
    """Issue #23: '2 count garlic' does not say cloves or heads."""

    def test_bare_garlic_by_count_is_ambiguous(self) -> None:
        assert "ambiguous_ingredient" in codes(three_meals([counted("garlic")]))

    def test_bare_onion_by_count_is_ambiguous(self) -> None:
        assert "ambiguous_ingredient" in codes(three_meals([counted("Onions")]))

    def test_qualified_name_is_accepted(self) -> None:
        assert codes(three_meals([counted("garlic cloves")])) == set()
        assert codes(three_meals([counted("yellow onion")])) == set()

    def test_unambiguous_count_name_is_accepted(self) -> None:
        assert codes(three_meals([counted("lemon")])) == set()

    def test_weighed_ingredient_is_never_ambiguous(self) -> None:
        weighed = {
            "name": "garlic",
            "quantity": 3.0,
            "unit": "oz",
            "package": None,
            "estimated_price_usd": 1.0,
        }
        assert codes(three_meals([weighed])) == set()

    def test_message_names_the_fix(self) -> None:
        errors = validate_plan(three_meals([counted("garlic")]))
        message = next(e.message for e in errors if e.code == "ambiguous_ingredient")
        assert "garlic" in message


class TestPackageFields:
    def test_nonpositive_package_size_is_invalid_value(self) -> None:
        plan = three_meals(
            [
                counted(
                    "lemon", {"form": "bag", "size_amount": 0.0, "size_unit": "count"}
                )
            ]
        )
        assert "invalid_value" in codes(plan)

    def test_blank_package_form_is_missing_field(self) -> None:
        plan = three_meals(
            [counted("lemon", {"form": " ", "size_amount": 4.0, "size_unit": "count"})]
        )
        assert "missing_field" in codes(plan)

    def test_valid_package_is_accepted(self) -> None:
        plan = three_meals(
            [
                counted(
                    "lemon", {"form": "bag", "size_amount": 4.0, "size_unit": "count"}
                )
            ]
        )
        assert codes(plan) == set()


class TestMultipleErrors:
    def test_all_violations_reported_together(self) -> None:
        plan = make_plan(
            dinner_count=8,
            lunch_count=9,
            meals=[make_meal(), make_meal(), make_meal()],
        )
        found = codes(plan)
        assert {
            "dinner_count_out_of_range",
            "lunch_count_out_of_range",
            "meal_count_mismatch",
            "batch_meal_count",
            "stretch_meal_count",
        } <= found
