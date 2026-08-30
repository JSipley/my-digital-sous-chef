"""Unit tests for the cookbook surface: row states, callbacks, ordering.

The one bug this file exists to prevent: rendering rows from one ordering
and resolving taps against another. Rows and callback indices must both
come from the plan's own meals list.
"""

from typing import Any

from sous_chef.bot.cookbook import (
    CALLBACK_DATA_LIMIT,
    MealTap,
    WeekNav,
    build_keyboard,
    decode,
    encode_meal,
    encode_week,
)
from sous_chef.bot.formatting import (
    TELEGRAM_MESSAGE_LIMIT,
    render_cookbook,
    render_cookbook_empty_week,
    render_instructions,
)
from sous_chef.models.plan import WeeklyPlan

WEEK = "2026-W31"


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
                "name": "bone-in short ribs",
                "quantity": 2.0,
                "unit": "lb",
                "package": None,
                "estimated_price_usd": 18.0,
            },
            {
                "name": "crushed tomatoes",
                "quantity": 28.0,
                "unit": "oz",
                "package": {
                    "form": "can",
                    "size_amount": 28.0,
                    "size_unit": "oz",
                },
                "estimated_price_usd": 2.5,
            },
        ],
    }


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


# Deliberately *not* alphabetical: "Zucchini boats" sorts last but is first
# in the plan. meals_for_week() would return these reordered.
UNSORTED_PLAN = plan_with(
    meal("Zucchini boats"),
    meal("Chicken chili", source_url="https://example.com/chili"),
    meal("Braised short ribs"),
)


class TestCallbackCodec:
    def test_meal_round_trip(self) -> None:
        assert decode(encode_meal(WEEK, 2)) == MealTap(week_id=WEEK, index=2)

    def test_week_round_trip(self) -> None:
        assert decode(encode_week(WEEK)) == WeekNav(week_id=WEEK)

    def test_prefixes_do_not_collide(self) -> None:
        assert isinstance(decode(encode_week(WEEK)), WeekNav)
        assert isinstance(decode(encode_meal(WEEK, 0)), MealTap)

    def test_fits_telegram_callback_limit(self) -> None:
        for data in (encode_meal(WEEK, 99), encode_week(WEEK)):
            assert len(data.encode()) <= CALLBACK_DATA_LIMIT

    def test_unparseable_data_is_none_not_an_exception(self) -> None:
        for data in (None, "", "nonsense", "cb:", "cb:2026-W31", "cb:2026-W31:x"):
            assert decode(data) is None, data

    def test_negative_index_rejected(self) -> None:
        assert decode("cb:2026-W31:-1") is None


class TestCookbookRows:
    def test_three_row_states(self) -> None:
        text = render_cookbook(
            WEEK, UNSORTED_PLAN, {"braised short ribs": "Sear the ribs."}
        )
        assert "📝 steps" in text
        assert "🔗 recipe" in text
        assert "⏳ tap to write steps" in text

    def test_rows_follow_plan_order_not_alphabetical(self) -> None:
        text = render_cookbook(WEEK, UNSORTED_PLAN, {})
        positions = [
            text.index("Zucchini"),
            text.index("Chicken"),
            text.index("Braised"),
        ]
        assert positions == sorted(positions), "rows render in plan_json order"

    def test_current_week_header(self) -> None:
        assert "this week" in render_cookbook(
            WEEK, UNSORTED_PLAN, {}, is_current_week=True
        )
        assert "this week" not in render_cookbook(WEEK, UNSORTED_PLAN, {})

    def test_link_meal_with_saved_steps_shows_both(self) -> None:
        """The paywalled-link path leaves a meal with a link and a button."""
        text = render_cookbook(
            WEEK, UNSORTED_PLAN, {"chicken chili": "Brown the chicken."}
        )
        chili_row = next(line for line in text.splitlines() if "Chicken" in line)
        assert "📝 steps" in chili_row
        assert "example\\.com/chili" in chili_row

    def test_empty_week_still_names_the_week(self) -> None:
        text = render_cookbook_empty_week(WEEK, is_current_week=True)
        assert "2026" in text and "this week" in text


class TestKeyboard:
    def test_link_meal_gets_a_button_once_steps_exist(self) -> None:
        keyboard = build_keyboard(
            WEEK,
            UNSORTED_PLAN,
            {"chicken chili": "Brown the chicken."},
            previous_week=None,
            next_week=None,
        )
        assert keyboard is not None
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        assert "📝 Chicken chili" in labels

    def test_recipe_meals_get_no_button(self) -> None:
        keyboard = build_keyboard(
            WEEK, UNSORTED_PLAN, {}, previous_week=None, next_week=None
        )
        assert keyboard is not None
        labels = [button.text for row in keyboard.inline_keyboard for button in row]
        assert not any("Chicken chili" in label for label in labels)
        assert len(labels) == 2

    def test_button_index_resolves_to_the_row_it_names(self) -> None:
        keyboard = build_keyboard(
            WEEK, UNSORTED_PLAN, {}, previous_week=None, next_week=None
        )
        assert keyboard is not None
        for row in keyboard.inline_keyboard:
            for button in row:
                action = decode(button.callback_data)
                assert isinstance(action, MealTap)
                assert UNSORTED_PLAN.meals[action.index].name in button.text

    def test_navigation_row_only_offers_existing_weeks(self) -> None:
        keyboard = build_keyboard(
            WEEK, UNSORTED_PLAN, {}, previous_week="2026-W28", next_week=None
        )
        assert keyboard is not None
        nav = keyboard.inline_keyboard[-1]
        assert [button.text for button in nav] == ["← 2026-W28"]
        assert decode(nav[0].callback_data) == WeekNav(week_id="2026-W28")

    def test_both_arrows_when_both_exist(self) -> None:
        keyboard = build_keyboard(
            WEEK, UNSORTED_PLAN, {}, previous_week="2026-W28", next_week="2026-W33"
        )
        assert keyboard is not None
        assert [b.text for b in keyboard.inline_keyboard[-1]] == [
            "← 2026-W28",
            "2026-W33 →",
        ]

    def test_no_keyboard_when_nothing_is_tappable(self) -> None:
        only_recipes = plan_with(meal("Chicken chili", source_url="https://x.test/c"))
        assert (
            build_keyboard(WEEK, only_recipes, {}, previous_week=None, next_week=None)
            is None
        )

    def test_missing_plan_still_offers_navigation(self) -> None:
        keyboard = build_keyboard(
            WEEK, None, {}, previous_week="2026-W28", next_week=None
        )
        assert keyboard is not None
        assert [b.text for b in keyboard.inline_keyboard[0]] == ["← 2026-W28"]


class TestInstructionsMessage:
    def test_ingredients_lead_then_numbered_steps(self) -> None:
        target = UNSORTED_PLAN.meals[2]
        (chunk,) = render_instructions(target, "Pat the ribs dry.\nSear all sides.")
        assert chunk.index("Ingredients") < chunk.index("Steps")
        assert "short ribs" in chunk
        assert "1\\. Pat the ribs dry\\." in chunk
        assert "2\\. Sear all sides\\." in chunk

    def test_markdown_reserved_characters_are_escaped(self) -> None:
        target = UNSORTED_PLAN.meals[2]
        (chunk,) = render_instructions(target, "Reduce by half (about 20-25 min).")
        for raw in ("(", ")", "-", "."):
            assert f"\\{raw}" in chunk

    def test_long_instructions_split_at_line_boundaries(self) -> None:
        target = UNSORTED_PLAN.meals[2]
        steps = "\n".join(f"Step number {n} with some detail" for n in range(400))
        chunks = render_instructions(target, steps)
        assert len(chunks) > 1
        for chunk in chunks:
            assert len(chunk) <= TELEGRAM_MESSAGE_LIMIT
        # Nothing was lost and no line was cut in half.
        rejoined = "\n".join(chunks)
        assert rejoined.count("Step number") == 400

    def test_blank_lines_do_not_become_steps(self) -> None:
        target = UNSORTED_PLAN.meals[2]
        (chunk,) = render_instructions(target, "First.\n\n\nSecond.")
        assert "2\\. Second\\." in chunk
        assert "3\\." not in chunk
