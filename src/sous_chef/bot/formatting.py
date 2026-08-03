"""Telegram MarkdownV2 rendering of plans for phone screens (FR-026).

The transport renders artifacts verbatim from the models — it never
recomputes or reorders anything the tools produced.
"""

from __future__ import annotations

import re

from sous_chef.models.grocery import GroceryItem, GroceryList
from sous_chef.models.plan import Meal, WeeklyPlan

NIGHTS_PER_WEEK = 7
TELEGRAM_MESSAGE_LIMIT = 4096

_MARKDOWN_V2_RESERVED = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")


def escape(text: str) -> str:
    """Escape every MarkdownV2 reserved character."""
    return _MARKDOWN_V2_RESERVED.sub(r"\\\1", text)


def render_plan(plan: WeeklyPlan) -> str:
    """One meal per block: bold name, flag lines, prep, servings, protein, source."""
    blocks = [f"*{escape(f'Plan for {plan.week_id}')}*"]
    blocks.extend(_render_meal(meal) for meal in plan.meals)
    open_nights = NIGHTS_PER_WEEK - plan.dinner_count
    blocks.append(escape(f"Open nights: {open_nights}"))
    return "\n\n".join(blocks)


def render_grocery_list(
    grocery: GroceryList, weekly_budget_usd: float | None
) -> list[str]:
    """The grocery-list message chunks: one item per line, bill line last.

    Items and totals come verbatim from the accept_plan result. Output is
    split at line boundaries (never mid-item) to fit Telegram's message
    limit; usually this is a single message.
    """
    lines = [_render_grocery_item(item) for item in grocery.items]
    bill = f"Estimated bill: ${grocery.estimated_total_usd:.2f}"
    if weekly_budget_usd is not None and grocery.budget_delta_usd is not None:
        delta = grocery.budget_delta_usd
        direction = "over" if delta > 0 else "under"
        bill += f" (budget ${weekly_budget_usd:.2f} — {direction} by ${abs(delta):.2f})"
    lines.append(escape(bill))
    return _split_at_lines(lines)


def render_instructions(meal: Meal, instructions: str) -> list[str]:
    """One meal's cooking instructions: ingredients first, then numbered steps.

    Ingredients come from the stored plan — they are never duplicated into
    the saved instructions text, which holds the steps alone. Split at line
    boundaries so a long recipe never breaks mid-step.
    """
    lines = [f"*{escape(f'📝 {meal.name}')}*", "", f"*{escape('Ingredients')}*"]
    lines.extend(
        escape(f"  • {_format_amount(i.quantity)} {i.unit} {i.name}")
        for i in meal.ingredients
    )
    steps = [step for step in instructions.splitlines() if step.strip()]
    if steps:
        lines.extend(["", f"*{escape('Steps')}*"])
        lines.extend(
            escape(f"  {number}. {step.strip()}")
            for number, step in enumerate(steps, start=1)
        )
    return _split_at_lines(lines)


def render_cookbook(
    week_id: str,
    plan: WeeklyPlan,
    instructions_by_name: dict[str, str],
    *,
    is_current_week: bool = False,
) -> str:
    """One row per meal, in plan order, in one of three states.

    Rows and callback indices both come from `plan.meals`, so the button at
    index i always resolves to the row rendered at index i.
    """
    heading = f"this week ({week_id})" if is_current_week else week_id
    lines = [f"*{escape(f'📖 Your cookbook — {heading}')}*", ""]
    for meal in plan.meals:
        if meal.normalized_name in instructions_by_name:
            # Steps win the marker: a meal keeps its link too, but the
            # button is the thing to tap.
            state = "📝 steps"
            if meal.source_url is not None:
                state += f" · 🔗 {meal.source_url}"
        elif meal.source_url is not None:
            state = f"🔗 recipe: {meal.source_url}"
        else:
            state = "⏳ tap to write steps"
        lines.append(escape(f"  {meal.name} — {state}"))
    return "\n".join(lines)


def render_cookbook_empty_week(week_id: str, *, is_current_week: bool = False) -> str:
    """A week with no accepted plan: header, explanation, nav still offered."""
    heading = f"this week ({week_id})" if is_current_week else week_id
    return "\n".join(
        [
            f"*{escape(f'📖 Your cookbook — {heading}')}*",
            "",
            escape(
                "  Nothing accepted for this week yet — the cookbook fills in "
                "when you accept a plan."
            ),
        ]
    )


def _render_grocery_item(item: GroceryItem) -> str:
    quantity = " + ".join(
        f"{_format_amount(q.amount)} {q.unit}" for q in item.quantities
    )
    return escape(f"• {item.name} — {quantity} (est. ${item.estimated_price_usd:.2f})")


def _format_amount(amount: float) -> str:
    text = f"{amount:.2f}".rstrip("0").rstrip(".")
    return text if text else "0"


def _split_at_lines(lines: list[str]) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    length = 0
    for line in lines:
        added = len(line) + (1 if current else 0)
        if current and length + added > TELEGRAM_MESSAGE_LIMIT:
            chunks.append("\n".join(current))
            current, length = [], 0
            added = len(line)
        current.append(line)
        length += added
    if current:
        chunks.append("\n".join(current))
    return chunks


def _render_meal(meal: Meal) -> str:
    lines = [f"*{escape(meal.name)}*"]
    if meal.batch is not None:
        lines.append(
            escape(
                f"🍲 Batch meal — covers {meal.batch.lunches_covered} lunches "
                f"+ 1 dinner ({meal.batch.total_portions} portions)"
            )
        )
    if meal.stretch is not None:
        lines.append(
            escape(f"✨ Stretch meal — new technique: {meal.stretch.technique}")
        )
    lines.append(escape(f"⏱ {meal.prep_minutes} min prep"))
    serving_word = "serving" if meal.servings == 1 else "servings"
    lines.append(escape(f"🍽 {meal.servings} {serving_word}"))
    lines.append(escape(f"🥩 {meal.primary_protein}"))
    if meal.source_url is not None:
        lines.append(escape(f"🔗 Recipe: {meal.source_url}"))
    return "\n".join(lines)
