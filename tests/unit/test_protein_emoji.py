"""Unit tests for the protein emoji mapping in the plan message.

`primary_protein` is free text from the model, so the mapping matches on
keywords. The cases that matter are the collisions: proteins that contain
another category's keyword as a substring ("tuna steak", "turkey bacon",
"eggplant"), and values the mapping does not recognize at all.
"""

from typing import Any

import pytest

from sous_chef.bot.formatting import _protein_emoji, render_plan
from sous_chef.models.plan import WeeklyPlan

WEEK = "2026-W31"


@pytest.mark.parametrize(
    ("primary_protein", "expected"),
    [
        # Red meat.
        ("beef", "🥩"),
        ("Ground beef", "🥩"),
        ("sirloin steak", "🥩"),
        ("bone-in short ribs", "🥩"),
        ("lamb shoulder", "🥩"),
        ("pork tenderloin", "🥩"),
        ("bacon", "🥩"),
        ("Italian sausage", "🥩"),
        # Poultry.
        ("chicken", "🍗"),
        ("Chicken thighs", "🍗"),
        ("turkey", "🍗"),
        ("ground turkey", "🍗"),
        ("duck breast", "🍗"),
        # Fish.
        ("salmon", "🐟"),
        ("Seared cod", "🐟"),
        ("canned tuna", "🐟"),
        # Shellfish.
        ("shrimp", "🍤"),
        ("bay scallops", "🍤"),
        # Eggs.
        ("eggs", "🥚"),
        ("Egg", "🥚"),
        # Plant-based.
        ("tofu", "🌱"),
        ("extra-firm tofu", "🌱"),
        ("black beans", "🌱"),
        ("red lentils", "🌱"),
        ("chickpeas", "🌱"),
        ("tempeh", "🌱"),
        ("seitan", "🌱"),
    ],
)
def test_recognized_proteins_map_to_their_category(
    primary_protein: str, expected: str
) -> None:
    assert _protein_emoji(primary_protein) == expected


@pytest.mark.parametrize(
    ("primary_protein", "expected"),
    [
        # Fish and poultry win over the red-meat keyword they contain.
        ("tuna steak", "🐟"),
        ("salmon steak", "🐟"),
        ("turkey bacon", "🍗"),
        ("chicken sausage", "🍗"),
        ("chicken-apple sausage", "🍗"),
        # A vegetable that merely starts with "egg" is not eggs.
        ("eggplant", ""),
        ("eggplant parmesan", ""),
    ],
)
def test_colliding_keywords_resolve_to_the_right_category(
    primary_protein: str, expected: str
) -> None:
    assert _protein_emoji(primary_protein) == expected


@pytest.mark.parametrize(
    "primary_protein",
    ["", "mystery protein", "leftovers", "whatever is in the fridge"],
)
def test_unrecognized_protein_has_no_emoji(primary_protein: str) -> None:
    assert _protein_emoji(primary_protein) == ""


def meal(primary_protein: str, **overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "name": "A dish",
        "primary_protein": primary_protein,
        "prep_minutes": 30,
        "servings": 1,
        "batch": None,
        "stretch": None,
        "source_url": None,
        "user_requested_repeat": False,
        "ingredients": [
            {
                "name": "olive oil",
                "quantity": 1.0,
                "unit": "tbsp",
                "package": None,
                "estimated_price_usd": 0.3,
            }
        ],
    }
    base.update(overrides)
    return base


def plan_with(*meals: dict[str, Any]) -> WeeklyPlan:
    return WeeklyPlan.model_validate(
        {
            "week_id": WEEK,
            "dinner_count": len(meals),
            "lunch_count": 0,
            "diet_type": None,
            "default_servings": 1,
            "weekly_budget_usd": None,
            "meals": list(meals),
        }
    )


def test_rendered_plan_uses_the_matching_emoji_per_meal() -> None:
    rendered = render_plan(
        plan_with(
            meal("chicken", name="Chicken chili"),
            meal("salmon", name="Seared salmon"),
            meal("beef", name="Beef stew"),
        )
    )

    assert "🍗 chicken" in rendered
    assert "🐟 salmon" in rendered
    assert "🥩 beef" in rendered


def test_rendered_plan_omits_the_emoji_and_its_space_when_unrecognized() -> None:
    rendered = render_plan(plan_with(meal("mystery protein", name="Kitchen sink bowl")))

    assert "\nmystery protein\n" in f"\n{rendered}\n"
    assert " mystery protein" not in rendered
