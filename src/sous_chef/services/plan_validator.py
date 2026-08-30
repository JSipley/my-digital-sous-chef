"""Deterministic plan validators: the code disposes.

Every rule the strict tool schema cannot express lives here; validation
failures are returned to the model as tool results for self-correction and
are never shown raw to the user.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from sous_chef.models.plan import (
    Ingredient,
    Meal,
    Unit,
    WeeklyPlan,
    normalize_dish_name,
)
from sous_chef.services.grocery import normalize_ingredient_name

DINNER_RANGE = range(1, 8)
LUNCH_RANGE = range(0, 8)

ERROR_CODES = frozenset(
    {
        "dinner_count_out_of_range",
        "lunch_count_out_of_range",
        "meal_count_mismatch",
        "batch_meal_count",
        "stretch_meal_count",
        "batch_stretch_same_meal",
        "batch_coverage_mismatch",
        "technique_not_new",
        "repeated_dish",
        "missing_field",
        "invalid_value",
        "ambiguous_ingredient",
    }
)

# Names that say nothing useful when counted: two garlic is two cloves or
# two heads, three onion is any of a dozen varieties (issue #23). Matching
# is on the normalized name, so 'garlic cloves' and 'yellow onion' pass.
AMBIGUOUS_COUNT_NAMES = frozenset(
    {
        "garlic",
        "onion",
        "shallot",
        "pepper",
        "chili",
        "chile",
        "squash",
        "melon",
        "cabbage",
        "lettuce",
        "greens",
        "herb",
        "mushroom",
        "potato",
    }
)


@dataclass(frozen=True)
class PlanError:
    code: str
    message: str


def validate_plan(
    plan: WeeklyPlan,
    *,
    cooked_names_last_4_weeks: Collection[str] = (),
    known_techniques: Collection[str] = (),
    repetition_relaxed: bool = False,
) -> list[PlanError]:
    """All rule violations in a proposed plan; an empty list means valid.

    History context comes from the caller: normalized dish names cooked in
    the 4 weeks before the plan's week, and techniques from cooked stretch
    meals (all history). `repetition_relaxed` is the session's announced
    relaxation flag.
    """
    errors: list[PlanError] = []
    errors.extend(_count_errors(plan))
    errors.extend(_flag_errors(plan))
    errors.extend(_batch_coverage_errors(plan))
    for meal in plan.meals:
        errors.extend(_meal_field_errors(meal))
    if not repetition_relaxed:
        errors.extend(_repeated_dish_errors(plan, cooked_names_last_4_weeks))
    errors.extend(_technique_errors(plan, known_techniques))
    return errors


def _repeated_dish_errors(
    plan: WeeklyPlan, cooked_names: Collection[str]
) -> list[PlanError]:
    cooked = {normalize_dish_name(name) for name in cooked_names}
    offending = [
        meal.name
        for meal in plan.meals
        if meal.normalized_name in cooked and not meal.user_requested_repeat
    ]
    if not offending:
        return []
    names = ", ".join(normalize_dish_name(name) for name in offending)
    return [
        PlanError(
            "repeated_dish",
            f"these dishes were cooked within the last 4 weeks: {names}; "
            "propose different dishes unless the user explicitly asked for "
            "a repeat",
        )
    ]


def _technique_errors(
    plan: WeeklyPlan, known_techniques: Collection[str]
) -> list[PlanError]:
    known = {normalize_dish_name(technique) for technique in known_techniques}
    errors = []
    for meal in plan.meals:
        if meal.stretch is None:
            continue
        technique = normalize_dish_name(meal.stretch.technique)
        if technique in known:
            errors.append(
                PlanError(
                    "technique_not_new",
                    f"the stretch technique '{technique}' is already in the "
                    "user's cooked history; pick a technique they have not "
                    "cooked before",
                )
            )
    return errors


def _count_errors(plan: WeeklyPlan) -> list[PlanError]:
    errors = []
    if plan.dinner_count not in DINNER_RANGE:
        errors.append(
            PlanError(
                "dinner_count_out_of_range",
                f"dinner_count must be 1-7, got {plan.dinner_count}",
            )
        )
    if plan.lunch_count not in LUNCH_RANGE:
        errors.append(
            PlanError(
                "lunch_count_out_of_range",
                f"lunch_count must be 0-7, got {plan.lunch_count}",
            )
        )
    if len(plan.meals) != plan.dinner_count:
        errors.append(
            PlanError(
                "meal_count_mismatch",
                f"plan has {len(plan.meals)} meals but dinner_count is "
                f"{plan.dinner_count}",
            )
        )
    return errors


def _flag_errors(plan: WeeklyPlan) -> list[PlanError]:
    errors = []
    batch_meals = [meal for meal in plan.meals if meal.batch is not None]
    stretch_meals = [meal for meal in plan.meals if meal.stretch is not None]
    if len(batch_meals) != 1:
        errors.append(
            PlanError(
                "batch_meal_count",
                f"exactly one meal must carry batch details, found {len(batch_meals)}",
            )
        )
    # A one-dinner week has a single meal, so batch and stretch cannot land on
    # two different dishes: batch wins (it carries the lunch coverage) and the
    # stretch meal is not planned at all.
    expected_stretch = 0 if plan.dinner_count == 1 else 1
    if len(stretch_meals) != expected_stretch:
        expectation = (
            "a one-dinner plan carries no stretch details — its single meal is "
            "the batch meal"
            if expected_stretch == 0
            else "exactly one meal must carry stretch details"
        )
        errors.append(
            PlanError(
                "stretch_meal_count",
                f"{expectation}, found {len(stretch_meals)}",
            )
        )
    if (
        expected_stretch == 1
        and len(batch_meals) == 1
        and len(stretch_meals) == 1
        and batch_meals[0] is stretch_meals[0]
    ):
        errors.append(
            PlanError(
                "batch_stretch_same_meal",
                "the batch meal and the stretch meal must be two different dishes; "
                f"'{batch_meals[0].name}' carries both flags",
            )
        )
    return errors


def _batch_coverage_errors(plan: WeeklyPlan) -> list[PlanError]:
    batch_meals = [meal for meal in plan.meals if meal.batch is not None]
    if len(batch_meals) != 1:
        return []
    meal = batch_meals[0]
    assert meal.batch is not None
    errors = []
    if meal.batch.lunches_covered != plan.lunch_count:
        errors.append(
            PlanError(
                "batch_coverage_mismatch",
                f"batch meal covers {meal.batch.lunches_covered} lunches but the "
                f"plan requests {plan.lunch_count}",
            )
        )
    expected_portions = (plan.lunch_count + 1) * meal.servings
    if meal.batch.total_portions != expected_portions:
        errors.append(
            PlanError(
                "batch_coverage_mismatch",
                f"batch meal total_portions must be (lunch_count + 1) x servings = "
                f"{expected_portions}, got {meal.batch.total_portions}",
            )
        )
    return errors


def _meal_field_errors(meal: Meal) -> list[PlanError]:
    errors = []
    if not meal.primary_protein.strip():
        errors.append(
            PlanError(
                "missing_field", f"meal '{meal.name}' is missing its primary_protein"
            )
        )
    if meal.prep_minutes <= 0:
        errors.append(
            PlanError(
                "invalid_value",
                f"meal '{meal.name}' prep_minutes must be > 0, got {meal.prep_minutes}",
            )
        )
    if meal.servings <= 0:
        errors.append(
            PlanError(
                "invalid_value",
                f"meal '{meal.name}' servings must be > 0, got {meal.servings}",
            )
        )
    if not meal.ingredients:
        errors.append(
            PlanError("missing_field", f"meal '{meal.name}' has no ingredients")
        )
    for ingredient in meal.ingredients:
        if not ingredient.name.strip():
            errors.append(
                PlanError(
                    "missing_field",
                    f"meal '{meal.name}' has an ingredient with a blank name",
                )
            )
        if ingredient.quantity <= 0:
            errors.append(
                PlanError(
                    "invalid_value",
                    f"ingredient '{ingredient.name}' of meal '{meal.name}' must "
                    f"have quantity > 0, got {ingredient.quantity}",
                )
            )
        if ingredient.estimated_price_usd < 0:
            errors.append(
                PlanError(
                    "invalid_value",
                    f"ingredient '{ingredient.name}' of meal '{meal.name}' must "
                    f"have a non-negative price, got {ingredient.estimated_price_usd}",
                )
            )
        errors.extend(_ambiguous_name_errors(meal, ingredient))
        errors.extend(_package_errors(meal, ingredient))
    return errors


def _ambiguous_name_errors(meal: Meal, ingredient: Ingredient) -> list[PlanError]:
    if ingredient.unit is not Unit.COUNT:
        return []
    if normalize_ingredient_name(ingredient.name) not in AMBIGUOUS_COUNT_NAMES:
        return []
    return [
        PlanError(
            "ambiguous_ingredient",
            f"'{ingredient.name}' of meal '{meal.name}' cannot be counted as "
            "written — name the variety or the part being counted (e.g. "
            "'garlic clove', 'yellow onion', 'red bell pepper'), or give a "
            "weight instead",
        )
    ]


def _package_errors(meal: Meal, ingredient: Ingredient) -> list[PlanError]:
    package = ingredient.package
    if package is None:
        return []
    errors = []
    if not package.form.strip():
        errors.append(
            PlanError(
                "missing_field",
                f"the package of ingredient '{ingredient.name}' of meal "
                f"'{meal.name}' is missing its form (e.g. 'can', 'bag')",
            )
        )
    if package.size_amount <= 0:
        errors.append(
            PlanError(
                "invalid_value",
                f"the package of ingredient '{ingredient.name}' of meal "
                f"'{meal.name}' must have size_amount > 0, got "
                f"{package.size_amount}",
            )
        )
    return errors
