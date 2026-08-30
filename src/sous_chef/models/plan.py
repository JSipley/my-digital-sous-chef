"""WeeklyPlan and meal models: the propose_plan payload (weekly-plan.schema.json).

Field descriptions are pinned verbatim against the contract schema by
tests/contract/test_plan_schema.py — keep them in sync with the contract.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import SkipJsonSchema


class Unit(StrEnum):
    """The U.S. customary units a quantity may be stated in (R9, issue #23).

    Volume and weight are separate families and never convert into each
    other, so `fl oz` (volume) and `oz` (weight) are distinct members.
    """

    TSP = "tsp"
    TBSP = "tbsp"
    FL_OZ = "fl oz"
    CUP = "cup"
    PINT = "pint"
    QUART = "quart"
    GALLON = "gallon"
    OZ = "oz"
    LB = "lb"
    COUNT = "count"


class PlanStatus(StrEnum):
    DRAFT = "draft"
    ACCEPTED = "accepted"
    FINAL = "final"


def normalize_dish_name(name: str) -> str:
    """Casefold, trim, and collapse whitespace for repetition matching."""
    return " ".join(name.casefold().split())


class Package(BaseModel):
    model_config = ConfigDict(extra="forbid")

    form: str = Field(
        description=(
            "What the package is, singular and lowercase: 'can', 'jar', "
            "'bag', 'box', 'bottle'."
        )
    )
    size_amount: float = Field(
        description="How much one package holds. Validator enforces > 0."
    )
    size_unit: Unit = Field(
        description=(
            "Unit of size_amount. Must be in the same family as the "
            "ingredient's unit, or the package is ignored."
        )
    )


class Ingredient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description=(
            "Ingredient name; merged across meals after normalization. A count "
            "ingredient must name a specific countable thing ('garlic clove', "
            "'yellow onion'), never a bare ambiguous one ('garlic', 'onion')."
        )
    )
    quantity: float = Field(
        description="Amount in the given unit. Validator enforces > 0."
    )
    unit: Unit = Field(description="U.S. customary unit for the quantity.")
    package: Package | None = Field(
        description=(
            "How this ingredient is sold when it comes in a fixed-size package "
            "(a 15 oz can, a 5 lb bag); null for loose or measured goods. The "
            "quantity stays the real amount needed — the grocery list computes "
            "how many packages to buy."
        )
    )
    estimated_price_usd: float = Field(
        description=(
            "Good-faith typical grocery price for this quantity, USD. "
            "The weekly bill is the computed sum of these."
        )
    )


class BatchDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lunches_covered: int = Field(description="Must equal the plan's lunch_count.")
    total_portions: int = Field(
        description=(
            "Total portions cooked once: (lunches_covered + 1 dinner night) x servings."
        )
    )


class StretchDetails(BaseModel):
    model_config = ConfigDict(extra="forbid")

    technique: str = Field(
        description=(
            "The new cooking technique this meal introduces, named (e.g. 'braising'). "
            "Must not appear in cooked-meal technique history."
        )
    )


class Meal(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        description=(
            "Named main dish, e.g. 'Chicken chili'. "
            "Repetition matching uses the normalized form of this name."
        )
    )
    primary_protein: str = Field(
        description="Primary protein source, stated qualitatively."
    )
    prep_minutes: int = Field(
        description="Estimated prep time in minutes. Validator enforces > 0."
    )
    servings: int = Field(
        description="Servings for this meal's cooking night. Validator enforces > 0."
    )
    batch: BatchDetails | None = Field(
        description="Non-null on exactly one meal: the big-batch meal-prep dish."
    )
    stretch: StretchDetails | None = Field(
        description=(
            "Non-null on exactly one meal (distinct from the batch meal): "
            "the stretch meal. Null on every meal when dinner_count is 1."
        )
    )
    source_url: str | None = Field(
        description=(
            "Source URL when the meal is based on a recipe found via web search; "
            "null otherwise."
        )
    )
    user_requested_repeat: bool = Field(
        description=(
            "True only when the user explicitly asked to repeat this past meal; "
            "exempts it from the 4-week repetition rule."
        )
    )
    ingredients: list[Ingredient] = Field(
        description=(
            "All ingredients, with quantities scaled to this meal's full coverage "
            "(for the batch meal: every covered lunch plus its dinner night)."
        )
    )

    @property
    def normalized_name(self) -> str:
        return normalize_dish_name(self.name)


class WeeklyPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_id: str = Field(
        description="ISO 8601 week the plan belongs to, e.g. '2026-W30'."
    )
    dinner_count: int = Field(
        description=(
            "Number of dinners the user asked to cook this week. "
            "Validator enforces 1-7."
        )
    )
    lunch_count: int = Field(
        description=(
            "Number of lunches to cover, all supplied by the batch meal. "
            "0 unless the user volunteered a count. Validator enforces 0-7."
        )
    )
    diet_type: str | None = Field(
        description="User-stated diet type (e.g. 'vegetarian'); null when none stated."
    )
    default_servings: int = Field(
        description=(
            "Servings per meal unless a meal overrides; "
            "1 unless the user stated otherwise."
        )
    )
    weekly_budget_usd: float | None = Field(
        description=(
            "Weekly grocery budget if the user set one this session; null otherwise."
        )
    )
    meals: list[Meal] = Field(
        description=(
            "Exactly dinner_count meals. Exactly one meal carries batch details and "
            "exactly one different meal carries stretch details — except at "
            "dinner_count 1, where the single meal carries batch details only."
        )
    )
    status: SkipJsonSchema[PlanStatus] = PlanStatus.DRAFT
    accepted_at: SkipJsonSchema[datetime | None] = None

    @property
    def batch_meal(self) -> Meal | None:
        return next((meal for meal in self.meals if meal.batch is not None), None)

    @property
    def stretch_meal(self) -> Meal | None:
        return next((meal for meal in self.meals if meal.stretch is not None), None)
