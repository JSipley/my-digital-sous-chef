"""Integration tests for the weekly-budget story.

Optional weekly budget: offered at conversation start, never blocking when
declined, exact overage amounts when nutrition wins, and mid-session
set/change/remove without restarting the session.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fake_llm import FakeTransport, ScriptedText, ScriptedToolCall

from sous_chef.agent.prompt import SYSTEM_PROMPT
from sous_chef.agent.session import Session
from sous_chef.agent.tools import build_tools
from sous_chef.bot.formatting import render_grocery_list
from sous_chef.services.history_repo import HistoryRepo

CHAT_ID = 4242
WEEK_ID = "2026-W30"
FIXED_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def meal(
    name: str,
    *,
    protein: str = "chicken",
    price: float = 8.0,
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": protein,
        "prep_minutes": 30,
        "servings": 1,
        "batch": batch,
        "stretch": stretch,
        "source_url": None,
        "user_requested_repeat": False,
        "ingredients": [
            {
                "name": f"{name} ingredients",
                "quantity": 1.0,
                "unit": "lb",
                "package": None,
                "estimated_price_usd": price,
            }
        ],
    }


def plan_payload(
    *, weekly_budget_usd: float | None = None, meal_price: float = 8.0
) -> dict[str, Any]:
    return {
        "week_id": WEEK_ID,
        "dinner_count": 3,
        "lunch_count": 2,
        "diet_type": None,
        "default_servings": 1,
        "weekly_budget_usd": weekly_budget_usd,
        "meals": [
            meal(
                "Chicken chili",
                price=meal_price,
                batch={"lunches_covered": 2, "total_portions": 3},
            ),
            meal(
                "Seared salmon",
                protein="salmon",
                price=meal_price,
                stretch={"technique": "searing"},
            ),
            meal("Turkey stir-fry", protein="turkey", price=meal_price),
        ],
    }


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "story3.db")


def make_session(transport: FakeTransport, repo: HistoryRepo) -> Session:
    return Session(
        chat_id=CHAT_ID,
        transport=transport,
        repo=repo,
        system_prompt=SYSTEM_PROMPT,
        tool_factory=build_tools,
        tz=UTC,
        now=lambda: FIXED_NOW,
    )


class TestScenario1BudgetOfferedAtStart:
    def test_system_prompt_requires_the_budget_offer(self) -> None:
        # The offer is agent behavior; the deterministic artifact is the
        # instruction in the stable prompt: offer at start, declining never
        # blocks, budget never carries across weeks.
        prompt = SYSTEM_PROMPT.casefold()
        assert "budget" in prompt
        assert "offer" in prompt
        assert "declin" in prompt
        assert "never carr" in prompt

    async def test_declining_the_budget_does_not_block_planning(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [
                ScriptedText(
                    "Happy to plan! Do you want to set a weekly grocery budget? "
                    "You can skip it."
                )
            ],
            [
                ScriptedToolCall("propose_plan", plan_payload()),
                ScriptedText("No budget — here's your plan."),
            ],
        )
        session = make_session(transport, repo)
        first = await session.handle_message("3 dinners, 2 lunches")
        assert first.newly_staged_plan is None
        outcome = await session.handle_message("no budget, thanks")
        assert outcome.newly_staged_plan is not None
        assert outcome.newly_staged_plan.weekly_budget_usd is None


class TestScenario2NoComparisonWhenDeclined:
    async def test_no_budget_yields_no_delta_and_no_budget_line(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", plan_payload()), ScriptedText("Plan!")],
            [
                ScriptedToolCall("accept_plan", {"week_id": WEEK_ID}),
                ScriptedText("Accepted."),
            ],
        )
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches, no budget")
        propose_result = json.loads(transport.tool_calls[0].result)
        assert propose_result["budget_delta_usd"] is None

        outcome = await session.handle_message("accept")
        accepted = outcome.newly_accepted
        assert accepted is not None
        assert accepted.grocery.budget_delta_usd is None
        rendered = "\n".join(
            render_grocery_list(accepted.grocery, accepted.plan.weekly_budget_usd)
        )
        assert "budget" not in rendered.casefold()


class TestScenario3BillFitsBudget:
    async def test_bill_within_budget_reports_negative_delta(
        self, repo: HistoryRepo
    ) -> None:
        payload = plan_payload(weekly_budget_usd=60.0, meal_price=15.0)
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", payload), ScriptedText("Plan fits!")],
            [
                ScriptedToolCall("accept_plan", {"week_id": WEEK_ID}),
                ScriptedText("Accepted."),
            ],
        )
        session = make_session(transport, repo)
        await session.handle_message("3 dinners, 2 lunches, budget $60")
        propose_result = json.loads(transport.tool_calls[0].result)
        assert propose_result["ok"] is True
        assert propose_result["estimated_bill_usd"] == 45.0
        assert propose_result["budget_delta_usd"] == -15.0

        outcome = await session.handle_message("accept")
        accepted = outcome.newly_accepted
        assert accepted is not None
        rendered = "\n".join(
            render_grocery_list(accepted.grocery, accepted.plan.weekly_budget_usd)
        ).replace("\\", "")
        assert "(budget $60.00 — under by $15.00)" in rendered


class TestScenario4OverageStatedWithAmount:
    async def test_overage_is_staged_with_exact_amount_never_rejected(
        self, repo: HistoryRepo
    ) -> None:
        payload = plan_payload(weekly_budget_usd=60.0, meal_price=24.5)
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", payload),
                ScriptedText(
                    "Meeting the nutrition standard runs $13.50 over your $60 "
                    "budget. I can swap the salmon for tilapia or the chili's "
                    "chicken thighs for drumsticks to bring the cost down."
                ),
            ],
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners, 2 lunches, budget $60")

        result = json.loads(transport.tool_calls[0].result)
        assert result["ok"] is True and result["staged"] is True
        assert result["estimated_bill_usd"] == 73.5
        assert result["budget_delta_usd"] == 13.5
        assert outcome.newly_staged_plan is not None, "over-budget plan still staged"
        assert "$13.50 over" in outcome.reply_text

    def test_prompt_demands_overage_amount_and_adjustments(self) -> None:
        prompt = SYSTEM_PROMPT.casefold()
        assert "overage" in prompt
        assert "nutrition" in prompt


class TestScenario5MidSessionBudgetChanges:
    async def test_set_change_and_remove_budget_without_restart(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", plan_payload(weekly_budget_usd=60.0)),
                ScriptedText("Within $60."),
            ],
            [
                ScriptedToolCall("propose_plan", plan_payload(weekly_budget_usd=45.0)),
                ScriptedText("Re-checked against $45."),
            ],
            [
                ScriptedToolCall("propose_plan", plan_payload()),
                ScriptedText("Budget removed."),
            ],
        )
        session = make_session(transport, repo)

        await session.handle_message("3 dinners, 2 lunches, budget $60")
        assert session.state.weekly_budget_usd == 60.0
        assert json.loads(transport.tool_calls[0].result)["budget_delta_usd"] == -36.0

        await session.handle_message("make the budget $45")
        assert session.state.weekly_budget_usd == 45.0
        assert json.loads(transport.tool_calls[1].result)["budget_delta_usd"] == -21.0

        outcome = await session.handle_message("drop the budget")
        assert session.state.weekly_budget_usd is None
        assert json.loads(transport.tool_calls[2].result)["budget_delta_usd"] is None
        assert outcome.newly_staged_plan is not None
        # One continuous session: full history retained across all turns.
        assert len(session.state.messages) > 6
