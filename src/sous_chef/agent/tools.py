"""Client tool definitions wired to services (contracts/agent-tools.md).

Tools are built per session so each closure stages drafts into that
session's in-memory state. Results are JSON with a top-level "ok" flag;
failures return error lists the model can act on — never exceptions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from anthropic.lib.tools import BetaAsyncFunctionTool, beta_async_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sous_chef.models.plan import PlanStatus, WeeklyPlan
from sous_chef.services.grocery import build_grocery_list
from sous_chef.services.plan_validator import validate_plan
from sous_chef.services.weeks import week_has_ended

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

ACCEPT_PLAN_DESCRIPTION = (
    "Persist the currently staged draft as the week's plan (upsert on "
    "week_id — an accepted plan edited mid-week is re-proposed and "
    "re-accepted). Returns the final grocery list and estimated bill for "
    "presentation; render them verbatim, never altering items or totals."
)


class AcceptPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_id: str = Field(description="Must match the staged draft's week_id.")


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
        preview = build_grocery_list(plan)
        return json.dumps(
            {
                "ok": True,
                "staged": True,
                "estimated_bill_usd": preview.estimated_total_usd,
                "budget_delta_usd": preview.budget_delta_usd,
                "grocery_item_count": len(preview.items),
            }
        )

    async def accept_plan(**payload: Any) -> str:
        data = AcceptPlanInput.model_validate(payload)
        draft = session.state.staged_draft
        if draft is None:
            return _failure(
                "no_staged_draft",
                "no draft plan is staged this session; call propose_plan first",
            )
        if data.week_id != draft.week_id:
            return _failure(
                "week_mismatch",
                f"the staged draft is for {draft.week_id}, not {data.week_id}",
            )
        moment = session.current_moment()
        if session.repo.plan_status(data.week_id) == "final" or week_has_ended(
            data.week_id, session.tz, moment
        ):
            return _failure(
                "week_already_final",
                f"week {data.week_id} has ended; its plan is final and "
                "cannot be edited",
            )
        grocery = build_grocery_list(draft)
        accepted = draft.model_copy(
            update={"status": PlanStatus.ACCEPTED, "accepted_at": moment}
        )
        meals_logged = session.repo.save_accepted_plan(
            accepted, grocery, accepted_at=moment
        )
        session.record_acceptance(accepted, grocery)
        return json.dumps(
            {
                "ok": True,
                "week_id": accepted.week_id,
                "grocery_list": grocery.model_dump(),
                "meals_logged": meals_logged,
            }
        )

    return [
        beta_async_tool(
            propose_plan,
            name="propose_plan",
            description=PROPOSE_PLAN_DESCRIPTION,
            input_schema=WeeklyPlan,
            strict=True,
        ),
        beta_async_tool(
            accept_plan,
            name="accept_plan",
            description=ACCEPT_PLAN_DESCRIPTION,
            input_schema=AcceptPlanInput,
        ),
    ]


def _rejection(errors: list[dict[str, str]]) -> str:
    return json.dumps({"ok": False, "staged": False, "errors": errors})


def _failure(code: str, message: str) -> str:
    return json.dumps({"ok": False, "errors": [{"code": code, "message": message}]})


def _format_validation_error(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        location = ".".join(str(piece) for piece in error["loc"])
        parts.append(f"{location}: {error['msg']}")
    return "; ".join(parts)
