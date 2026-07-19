"""Telegram MarkdownV2 rendering of plans for phone screens (FR-026).

The transport renders artifacts verbatim from the models — it never
recomputes or reorders anything the tools produced.
"""

from __future__ import annotations

import re

from sous_chef.models.plan import Meal, WeeklyPlan

NIGHTS_PER_WEEK = 7

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
        lines.append(escape(f"🔗 {meal.source_url}"))
    return "\n".join(lines)
