"""Inline-keyboard plumbing for /cookbook.

Telegram caps callback_data at 64 bytes — far too tight for arbitrary meal
names — so a meal tap is encoded as its *index into the plan's meals list*.
The cookbook rows are rendered from that same list, which keeps the button
at index i pointing at the row shown at index i.
"""

from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from sous_chef.models.plan import WeeklyPlan

MEAL_PREFIX = "cb"
WEEK_PREFIX = "cbw"
CALLBACK_DATA_LIMIT = 64


@dataclass(frozen=True)
class MealTap:
    """A tap on one meal's button."""

    week_id: str
    index: int


@dataclass(frozen=True)
class WeekNav:
    """A tap on an earlier/later week button."""

    week_id: str


def encode_meal(week_id: str, index: int) -> str:
    return f"{MEAL_PREFIX}:{week_id}:{index}"


def encode_week(week_id: str) -> str:
    return f"{WEEK_PREFIX}:{week_id}"


def decode(data: str | None) -> MealTap | WeekNav | None:
    """Parse callback data; None for anything this bot did not produce.

    Buttons in old messages stay live indefinitely, so unparseable data is
    a normal condition to handle, never an exception.
    """
    if not data:
        return None
    parts = data.split(":")
    if len(parts) == 2 and parts[0] == WEEK_PREFIX and parts[1]:
        return WeekNav(week_id=parts[1])
    if len(parts) == 3 and parts[0] == MEAL_PREFIX and parts[1]:
        try:
            index = int(parts[2])
        except ValueError:
            return None
        return MealTap(week_id=parts[1], index=index) if index >= 0 else None
    return None


def build_keyboard(
    week_id: str,
    plan: WeeklyPlan | None,
    instructions_by_name: dict[str, str],
    *,
    previous_week: str | None,
    next_week: str | None,
) -> InlineKeyboardMarkup | None:
    """A button per reachable meal, then the week-navigation row.

    A meal with a recipe link and no saved steps gets no button — its link
    is already inline. Once steps exist it gets one anyway, so a meal whose
    link turned out to be unusable ends up with both. Returns None when
    there is nothing to tap at all.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for index, meal in enumerate(plan.meals if plan is not None else []):
        has_steps = meal.normalized_name in instructions_by_name
        if meal.source_url is not None and not has_steps:
            continue
        label = f"{'📝' if has_steps else '⏳'} {meal.name}"
        rows.append(
            [InlineKeyboardButton(label, callback_data=encode_meal(week_id, index))]
        )
    nav = [
        InlineKeyboardButton(f"← {week}", callback_data=encode_week(week))
        for week in (previous_week,)
        if week is not None
    ]
    nav.extend(
        InlineKeyboardButton(f"{week} →", callback_data=encode_week(week))
        for week in (next_week,)
        if week is not None
    )
    if nav:
        rows.append(nav)
    return InlineKeyboardMarkup(rows) if rows else None
