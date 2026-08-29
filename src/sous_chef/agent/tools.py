"""Client tool definitions wired to services.

Tools are built per session so each closure stages drafts into that
session's in-memory state. Results are JSON with a top-level "ok" flag;
failures return error lists the model can act on — never exceptions.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from anthropic.lib.tools import BetaAsyncFunctionTool, beta_async_tool
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from sous_chef.models.history import CheckinResult
from sous_chef.models.plan import PlanStatus, WeeklyPlan, normalize_dish_name
from sous_chef.services.grocery import build_grocery_list
from sous_chef.services.history_repo import CheckinError, InstructionsError
from sous_chef.services.plan_validator import validate_plan
from sous_chef.services.weeks import week_has_ended

if TYPE_CHECKING:
    from sous_chef.agent.session import Session

# Consecutive repeated_dish rejections before the session announces it is
# relaxing the 4-week repetition window.
REPETITION_RELAXATION_THRESHOLD = 2

RELAXATION_NOTE = (
    "every alternative kept colliding with the 4-week repetition window, so "
    "it has been relaxed for this session (prefer repeating the oldest "
    "cooked dishes first); tell the user you are doing this, then re-propose"
)

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

GET_MEAL_HISTORY_DESCRIPTION = (
    "Read accumulated meal history: past weeks' meals with cooked status, "
    "dish names cooked in the last 4 weeks (the repetition window), known "
    "stretch techniques, and any pending cooked check-in. Call this before "
    "the first proposal of every session."
)

RECORD_COOKED_CHECKIN_DESCRIPTION = (
    "Record which of the pending week's planned meals were actually "
    "cooked; meals of that week not listed are marked skipped. Set "
    "user_skipped_checkin=true when the user skips or cannot recall the "
    "check-in — every planned meal is then marked cooked."
)

SAVE_MEAL_INSTRUCTIONS_DESCRIPTION = (
    "Save step-by-step cooking instructions for one meal of an accepted "
    "week, so they can be pulled up later from the cookbook. Write the "
    "steps only — ingredients are already stored with the plan and must "
    "not be repeated here. Call this after accept_plan for every name in "
    "its instructions_needed list, and whenever you write steps for a meal "
    "on request. Re-saving overwrites."
)

GET_MEAL_INSTRUCTIONS_DESCRIPTION = (
    "Read a meal's stored cooking instructions plus its ingredients and "
    "recipe source_url. Omit week_id to resolve the most recent week "
    "containing that dish. When instructions comes back null the meal "
    "exists but has no steps yet — write them and call "
    "save_meal_instructions with the week_id returned here."
)


class AcceptPlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_id: str = Field(description="Must match the staged draft's week_id.")


class GetMealHistoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    weeks_back: int = Field(
        default=8,
        description="How many past weeks to return, most recent first. Default 8.",
    )


class RecordCookedCheckinInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_id: str = Field(
        description="The week being checked in, from pending_checkin_week_id."
    )
    cooked_meal_names: list[str] = Field(
        default=[],
        description=(
            "Names of the meals the user actually cooked. Meals of that "
            "week not listed are marked skipped."
        ),
    )
    user_skipped_checkin: bool = Field(
        default=False,
        description=(
            "True when the user skipped or could not recall the check-in; "
            "every planned meal is then marked cooked."
        ),
    )


class SaveMealInstructionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    week_id: str = Field(description="The accepted week the meal belongs to.")
    meal_name: str = Field(description="The meal's name as it appears in the plan.")
    steps: list[str] = Field(
        description=(
            "The cooking steps in order, one string per step, unnumbered. "
            "Steps only — never restate ingredients."
        )
    )


class GetMealInstructionsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    meal_name: str = Field(description="The dish to look up.")
    week_id: str | None = Field(
        default=None,
        description=(
            "The week to read from. Omit to resolve the most recent week "
            "containing this dish."
        ),
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
        errors = validate_plan(
            plan,
            cooked_names_last_4_weeks=session.repo.cooked_dish_names_before(
                plan.week_id
            ),
            known_techniques=session.repo.cooked_techniques(),
            repetition_relaxed=session.state.repetition_relaxed,
        )
        if errors:
            reported = [
                {"code": error.code, "message": error.message} for error in errors
            ]
            if any(error.code == "repeated_dish" for error in errors):
                session.repetition_rejections += 1
                if (
                    session.repetition_rejections >= REPETITION_RELAXATION_THRESHOLD
                    and not session.state.repetition_relaxed
                ):
                    session.state.repetition_relaxed = True
                    return json.dumps(
                        {
                            "ok": False,
                            "staged": False,
                            "errors": reported,
                            "note": RELAXATION_NOTE,
                        }
                    )
            return _rejection(reported)
        session.repetition_rejections = 0
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
                # The worklist for save_meal_instructions: every meal with no
                # recipe link to send the user to.
                "instructions_needed": [
                    meal.name for meal in accepted.meals if meal.source_url is None
                ],
            }
        )

    async def get_meal_history(**payload: Any) -> str:
        data = GetMealHistoryInput.model_validate(payload)
        current_week_id = session.current_week_id()
        session.repo.finalize_weeks_before(current_week_id)
        pending = session.repo.pending_checkin_week_id()
        session.state.pending_checkin = (
            CheckinResult(week_id=pending, cooked=[], skipped=[])
            if pending is not None
            else None
        )
        return json.dumps(
            {
                "ok": True,
                "current_week_id": current_week_id,
                "pending_checkin_week_id": pending,
                "cooked_dish_names_last_4_weeks": (
                    session.repo.cooked_dish_names_before(current_week_id)
                ),
                "known_techniques": session.repo.cooked_techniques(),
                "weeks": session.repo.weeks_summary(data.weeks_back),
            }
        )

    async def record_cooked_checkin(**payload: Any) -> str:
        data = RecordCookedCheckinInput.model_validate(payload)
        try:
            result = session.repo.record_checkin(
                data.week_id,
                data.cooked_meal_names,
                user_skipped=data.user_skipped_checkin,
            )
        except CheckinError as exc:
            return _failure(exc.code, exc.message)
        session.state.pending_checkin = None
        return json.dumps(
            {
                "ok": True,
                "recorded": {"cooked": result.cooked, "skipped": result.skipped},
            }
        )

    async def save_meal_instructions(**payload: Any) -> str:
        data = SaveMealInstructionsInput.model_validate(payload)
        try:
            meal_name = session.repo.save_meal_instructions(
                data.week_id, data.meal_name, "\n".join(data.steps)
            )
        except InstructionsError as exc:
            return _failure(exc.code, exc.message)
        return json.dumps({"ok": True, "week_id": data.week_id, "meal_name": meal_name})

    async def get_meal_instructions(**payload: Any) -> str:
        data = GetMealInstructionsInput.model_validate(payload)
        week_id = data.week_id
        if week_id is None:
            # No week given: the same dish in two weeks can carry different
            # steps, so take the most recent (already week_id DESC).
            matches = session.repo.find_meals_by_normalized_name(data.meal_name)
            if not matches:
                return _failure(
                    "unknown_meal_name",
                    f"no week contains a meal named: {data.meal_name}",
                )
            week_id = matches[0].week_id
        plan = session.repo.plan_for_week(week_id)
        if plan is None:
            return _failure("unknown_week", f"no plan exists for week {week_id}")
        normalized = normalize_dish_name(data.meal_name)
        meal = next((m for m in plan.meals if m.normalized_name == normalized), None)
        if meal is None:
            return _failure(
                "unknown_meal_name",
                f"week {week_id} has no meal named: {data.meal_name}",
            )
        return json.dumps(
            {
                "ok": True,
                "week_id": week_id,
                "meal_name": meal.name,
                # null means "no steps saved yet" — write them and save.
                "instructions": session.repo.meal_instructions(week_id, meal.name),
                "ingredients": [
                    ingredient.model_dump() for ingredient in meal.ingredients
                ],
                "source_url": meal.source_url,
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
        beta_async_tool(
            get_meal_history,
            name="get_meal_history",
            description=GET_MEAL_HISTORY_DESCRIPTION,
            input_schema=GetMealHistoryInput,
        ),
        beta_async_tool(
            record_cooked_checkin,
            name="record_cooked_checkin",
            description=RECORD_COOKED_CHECKIN_DESCRIPTION,
            input_schema=RecordCookedCheckinInput,
        ),
        beta_async_tool(
            save_meal_instructions,
            name="save_meal_instructions",
            description=SAVE_MEAL_INSTRUCTIONS_DESCRIPTION,
            input_schema=SaveMealInstructionsInput,
        ),
        beta_async_tool(
            get_meal_instructions,
            name="get_meal_instructions",
            description=GET_MEAL_INSTRUCTIONS_DESCRIPTION,
            input_schema=GetMealInstructionsInput,
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
