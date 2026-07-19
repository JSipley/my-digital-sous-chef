"""Client tool definitions wired to services (contracts/agent-tools.md).

Tools are built per session so each closure stages drafts into that
session's in-memory state. Results are JSON with a top-level "ok" flag;
failures return error lists the model can act on — never exceptions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from anthropic.lib.tools import BetaAsyncFunctionTool, beta_async_tool
from pydantic import ValidationError

from sous_chef.models.plan import WeeklyPlan, normalize_dish_name
from sous_chef.services.plan_validator import validate_plan

if TYPE_CHECKING:
    from sous_chef.agent.session import Session

PROPOSE_PLAN_DESCRIPTION = (
    "Register a structured draft weekly plan for this session. Runs the "
    "deterministic validators; on failure returns ok=false with an error list "
    "to self-correct from (never show raw errors to the user), and on success "
    "stages the draft and returns the computed grocery/bill preview so budget "
    "fit can be checked before presenting the plan. Call this for every plan "
    "revision, including single-meal swaps and preference changes."
)


def build_tools(session: Session) -> list[BetaAsyncFunctionTool[Any]]:
    """The client tools for one session, closing over its state."""

    async def propose_plan(**payload: Any) -> str:
        try:
            plan = WeeklyPlan.model_validate(payload)
        except ValidationError as exc:
            return _rejection(
                [{"code": "invalid_value", "message": _format_validation_error(exc)}]
            )
        errors = validate_plan(plan)
        if errors:
            return _rejection(
                [{"code": error.code, "message": error.message} for error in errors]
            )
        session.stage_draft(plan)
        bill = _estimated_bill(plan)
        budget = plan.weekly_budget_usd
        return json.dumps(
            {
                "ok": True,
                "staged": True,
                "estimated_bill_usd": bill,
                "budget_delta_usd": None if budget is None else round(bill - budget, 2),
                "grocery_item_count": _distinct_ingredient_count(plan),
            }
        )

    return [
        beta_async_tool(
            propose_plan,
            name="propose_plan",
            description=PROPOSE_PLAN_DESCRIPTION,
            input_schema=WeeklyPlan,
            strict=True,
        )
    ]


def _rejection(errors: list[dict[str, str]]) -> str:
    return json.dumps({"ok": False, "staged": False, "errors": errors})


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(piece) for piece in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)


def _estimated_bill(plan: WeeklyPlan) -> float:
    return round(
        sum(
            ingredient.estimated_price_usd
            for meal in plan.meals
            for ingredient in meal.ingredients
        ),
        2,
    )


def _distinct_ingredient_count(plan: WeeklyPlan) -> int:
    return len(
        {
            normalize_dish_name(ingredient.name)
            for meal in plan.meals
            for ingredient in meal.ingredients
        }
    )
