"""Telegram MarkdownV2 rendering of plans for phone screens.

The transport renders artifacts verbatim from the models — it never
recomputes or reorders anything the tools produced.
"""

from __future__ import annotations

import re

from sous_chef.models.grocery import GroceryItem, GroceryList, PackageCount, Quantity
from sous_chef.models.plan import BatchDetails, Meal, Unit, WeeklyPlan
from sous_chef.services.grocery import pluralize_ingredient_name

NIGHTS_PER_WEEK = 7
TELEGRAM_MESSAGE_LIMIT = 4096

_MARKDOWN_V2_RESERVED = re.compile(r"([_*\[\]()~`>#+\-=|{}.!\\])")

# `primary_protein` is free text, so the emoji is keyword-matched.
# Order is load-bearing: categories collide as substrings, and the first
# match wins — a "tuna steak" is fish, "turkey bacon" is poultry.
_PROTEIN_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "🍤",
        ("shrimp", "prawn", "scallop", "crab", "lobster", "clam", "mussel", "oyster"),
    ),
    (
        "🐟",
        (
            "fish",
            "seafood",
            "salmon",
            "tuna",
            "cod",
            "halibut",
            "tilapia",
            "trout",
            "haddock",
            "mahi",
            "snapper",
            "sea bass",
            "swordfish",
            "sardine",
            "anchovy",
        ),
    ),
    ("🍗", ("chicken", "turkey", "duck", "poultry", "cornish hen")),
    (
        "🥩",
        (
            "beef",
            "steak",
            "sirloin",
            "ribeye",
            "brisket",
            "short rib",
            "lamb",
            "pork",
            "bacon",
            "ham",
            "sausage",
            "chorizo",
            "prosciutto",
            "veal",
            "venison",
            "bison",
        ),
    ),
    ("🥚", ("egg",)),
    (
        "🌱",
        (
            "tofu",
            "tempeh",
            "seitan",
            "bean",
            "lentil",
            "chickpea",
            "garbanzo",
            "edamame",
            "quinoa",
            "plant",
        ),
    ),
)

# Trailing `s?` covers plurals without letting a keyword match inside a
# longer word: "eggs" is eggs, "eggplant" is not.
_PROTEIN_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b(?:{'|'.join(keywords)})s?\b"), emoji)
    for emoji, keywords in _PROTEIN_KEYWORDS
)


def escape(text: str) -> str:
    """Escape every MarkdownV2 reserved character."""
    return _MARKDOWN_V2_RESERVED.sub(r"\\\1", text)


def render_plan(plan: WeeklyPlan) -> str:
    """One meal per block: bold name, flag lines, prep, servings, protein, source."""
    blocks = [f"*{escape(f'Plan for {plan.week_id}')}*"]
    blocks.extend(_render_meal(meal) for meal in plan.meals)
    open_nights = NIGHTS_PER_WEEK - plan.dinner_count
    # A full week has nothing to report here; the line would only state a zero.
    if open_nights > 0:
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
        escape(f"  • {_quantity_phrase(i.quantity, i.unit, i.name)}")
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
    price = f"(est. ${item.estimated_price_usd:.2f})"
    counted = None if item.package is not None else _lone_count(item)
    # A plain countable thing reads as English, not as a measurement:
    # '1 lemon', not 'lemon — 1 count'.
    if counted is not None:
        return escape(f"• {_quantity_phrase(counted, Unit.COUNT, item.name)} {price}")
    measure = " + ".join(_measure(quantity, item.name) for quantity in item.quantities)
    if item.package is not None:
        measure = f"{_package_label(item.package)} ({measure})"
    return escape(f"• {item.name} — {measure} {price}")


def _lone_count(item: GroceryItem) -> float | None:
    """The amount when the item is nothing but a count, else None."""
    if len(item.quantities) != 1 or item.quantities[0].unit is not Unit.COUNT:
        return None
    return item.quantities[0].amount


def _measure(quantity: Quantity, name: str) -> str:
    if quantity.unit is Unit.COUNT:
        return _quantity_phrase(quantity.amount, quantity.unit, name)
    return f"{_format_amount(quantity.amount)} {quantity.unit}"


def _package_label(package: PackageCount) -> str:
    """How many packages to buy: '3 x 15 oz can', '1 x 12 carton'."""
    size = _format_amount(package.size_amount)
    if package.size_unit is not Unit.COUNT:
        size = f"{size} {package.size_unit}"
    return f"{package.packages} x {size} {package.form}"


def _quantity_phrase(amount: float, unit: Unit, name: str) -> str:
    """'1.5 lb chicken thighs' — but 'count' is never a word the user reads."""
    if unit is Unit.COUNT:
        display = name if amount == 1 else pluralize_ingredient_name(name)
        return f"{_format_amount(amount)} {display}"
    return f"{_format_amount(amount)} {unit} {name}"


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


def _batch_coverage(batch: BatchDetails) -> str:
    """What the batch meal covers. Zero lunches is the default week, so it
    reads as coverage, not as a warning about lunches the user never asked for.
    """
    portions = f"{batch.total_portions} " + (
        "portion" if batch.total_portions == 1 else "portions"
    )
    if batch.lunches_covered == 0:
        return f"covers 1 dinner night ({portions})"
    lunches = f"{batch.lunches_covered} " + (
        "lunch" if batch.lunches_covered == 1 else "lunches"
    )
    return f"covers {lunches} + 1 dinner ({portions})"


def _protein_emoji(primary_protein: str) -> str:
    """Emoji for a free-text protein; empty when nothing is recognized."""
    text = primary_protein.casefold()
    for pattern, emoji in _PROTEIN_PATTERNS:
        if pattern.search(text):
            return emoji
    return ""


def _render_meal(meal: Meal) -> str:
    lines = [f"*{escape(meal.name)}*"]
    if meal.batch is not None:
        lines.append(escape(f"🍲 Batch meal — {_batch_coverage(meal.batch)}"))
    if meal.stretch is not None:
        lines.append(
            escape(f"✨ Stretch meal — new technique: {meal.stretch.technique}")
        )
    lines.append(escape(f"⏱ {meal.prep_minutes} min prep"))
    serving_word = "serving" if meal.servings == 1 else "servings"
    lines.append(escape(f"🍽 {meal.servings} {serving_word}"))
    emoji = _protein_emoji(meal.primary_protein)
    protein = f"{emoji} {meal.primary_protein}" if emoji else meal.primary_protein
    lines.append(escape(protein))
    if meal.source_url is not None:
        lines.append(escape(f"🔗 Recipe: {meal.source_url}"))
    return "\n".join(lines)
