"""Integration tests for the meal-history story.

Two consecutive weekly sessions over one SQLite file: acceptance logs
meals, the next session opens with a cooked check-in, cooked dishes don't
repeat within 4 weeks, past weeks are queryable, explicit repeats are
honored, and a first-ever session runs with no check-in and no repetition
rule.
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
from sous_chef.services.history_repo import HistoryRepo

CHAT_ID = 4242
WEEK_ONE = "2026-W30"
WEEK_TWO = "2026-W31"
NOW_WEEK_ONE = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)
NOW_WEEK_TWO = datetime(2026, 7, 29, 12, 0, tzinfo=UTC)


def meal(
    name: str,
    *,
    protein: str = "chicken",
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
    user_requested_repeat: bool = False,
) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": protein,
        "prep_minutes": 30,
        "servings": 1,
        "batch": batch,
        "stretch": stretch,
        "source_url": None,
        "user_requested_repeat": user_requested_repeat,
        "ingredients": [
            {
                "name": f"{protein} cut",
                "quantity": 1.0,
                "unit": "lb",
                "package": None,
                "estimated_price_usd": 8.0,
            }
        ],
    }


def week_one_payload() -> dict[str, Any]:
    return {
        "week_id": WEEK_ONE,
        "dinner_count": 3,
        "lunch_count": 2,
        "diet_type": None,
        "default_servings": 1,
        "weekly_budget_usd": None,
        "meals": [
            meal(
                "Chicken chili",
                batch={"lunches_covered": 2, "total_portions": 3},
            ),
            meal("Seared salmon", protein="salmon", stretch={"technique": "searing"}),
            meal("Turkey stir-fry", protein="turkey"),
        ],
    }


def week_two_payload(meals: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "week_id": WEEK_TWO,
        "dinner_count": 3,
        "lunch_count": 2,
        "diet_type": None,
        "default_servings": 1,
        "weekly_budget_usd": None,
        "meals": meals,
    }


def clean_week_two_meals() -> list[dict[str, Any]]:
    return [
        meal("Pork tenderloin", protein="pork"),
        meal(
            "Braised beef",
            protein="beef",
            stretch={"technique": "braising"},
        ),
        meal(
            "Turkey stir-fry",
            protein="turkey",
            batch={"lunches_covered": 2, "total_portions": 3},
        ),
    ]


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "story4.db")


def session_at(
    transport: FakeTransport, repo: HistoryRepo, moment: datetime
) -> Session:
    return Session(
        chat_id=CHAT_ID,
        transport=transport,
        repo=repo,
        system_prompt=SYSTEM_PROMPT,
        tool_factory=build_tools,
        tz=UTC,
        now=lambda: moment,
    )


async def run_week_one(repo: HistoryRepo) -> FakeTransport:
    """A full first-ever week-one session: history check, plan, accept."""
    transport = FakeTransport.scripted(
        [
            ScriptedToolCall("get_meal_history", {}),
            ScriptedToolCall("propose_plan", week_one_payload()),
            ScriptedText("First plan!"),
        ],
        [
            ScriptedToolCall("accept_plan", {"week_id": WEEK_ONE}),
            ScriptedText("Accepted."),
        ],
    )
    session = session_at(transport, repo, NOW_WEEK_ONE)
    await session.handle_message("3 dinners, 2 lunches")
    await session.handle_message("accept")
    return transport


class TestScenario6FirstEverSession:
    async def test_no_checkin_and_no_repetition_rule(self, repo: HistoryRepo) -> None:
        transport = await run_week_one(repo)
        history_result = json.loads(transport.tool_calls[0].result)
        assert history_result["ok"] is True
        assert history_result["pending_checkin_week_id"] is None
        assert history_result["cooked_dish_names_last_4_weeks"] == []
        assert history_result["known_techniques"] == []
        assert history_result["weeks"] == []
        # Planning proceeded immediately: the very next call staged a plan.
        propose_result = json.loads(transport.tool_calls[1].result)
        assert propose_result["ok"] is True


class TestScenario1MealsLoggedOnAcceptance:
    async def test_accepted_meals_logged_with_week(self, repo: HistoryRepo) -> None:
        await run_week_one(repo)
        rows = repo.connection.execute(
            "SELECT meal_name, is_batch, is_stretch, technique, cooked_status "
            "FROM meals WHERE week_id = ?",
            (WEEK_ONE,),
        ).fetchall()
        by_name = {row["meal_name"]: row for row in rows}
        assert set(by_name) == {"Chicken chili", "Seared salmon", "Turkey stir-fry"}
        assert by_name["Chicken chili"]["is_batch"] == 1
        assert by_name["Seared salmon"]["is_stretch"] == 1
        assert by_name["Seared salmon"]["technique"] == "searing"
        assert all(row["cooked_status"] == "planned" for row in rows)


class TestScenario3CheckinBeforeCurating:
    async def test_next_session_opens_with_pending_checkin(
        self, repo: HistoryRepo
    ) -> None:
        await run_week_one(repo)
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("get_meal_history", {}),
                ScriptedText(
                    "Before we plan: which of last week's meals did you cook?"
                ),
            ],
            [
                ScriptedToolCall(
                    "record_cooked_checkin",
                    {
                        "week_id": WEEK_ONE,
                        "cooked_meal_names": ["Chicken chili", "Seared salmon"],
                    },
                ),
                ScriptedToolCall(
                    "propose_plan", week_two_payload(clean_week_two_meals())
                ),
                ScriptedText("Logged. Here's this week's plan!"),
            ],
        )
        session = session_at(transport, repo, NOW_WEEK_TWO)
        await session.handle_message("/plan")
        history_result = json.loads(transport.tool_calls[0].result)
        assert history_result["pending_checkin_week_id"] == WEEK_ONE
        assert session.state.pending_checkin is not None

        outcome = await session.handle_message(
            "I cooked the chili and the salmon, skipped the stir-fry"
        )
        checkin_result = json.loads(transport.tool_calls[1].result)
        assert checkin_result["ok"] is True
        assert sorted(checkin_result["recorded"]["cooked"]) == [
            "Chicken chili",
            "Seared salmon",
        ]
        assert checkin_result["recorded"]["skipped"] == ["Turkey stir-fry"]
        assert session.state.pending_checkin is None

        # The skipped stir-fry reappears in week two's accepted proposal.
        propose_result = json.loads(transport.tool_calls[2].result)
        assert propose_result["ok"] is True
        assert outcome.newly_staged_plan is not None
        assert "Turkey stir-fry" in [m.name for m in outcome.newly_staged_plan.meals]

    def test_prompt_demands_history_then_checkin_before_curating(self) -> None:
        prompt = SYSTEM_PROMPT.casefold()
        assert "get_meal_history" in prompt
        assert "record_cooked_checkin" in prompt
        assert "check-in" in prompt


async def checked_in_week_two_session(
    repo: HistoryRepo, *turns: list[Any]
) -> tuple[Session, FakeTransport]:
    """Week one accepted; chili and salmon cooked, stir-fry skipped.

    Returns a week-two session ready to plan: the cooked set is
    {chicken chili, seared salmon}, known techniques {searing}, and the
    skipped stir-fry is re-proposable.
    """
    await run_week_one(repo)
    repo.record_checkin(
        WEEK_ONE, ["Chicken chili", "Seared salmon"], user_skipped=False
    )
    transport = FakeTransport.scripted(*turns)
    return session_at(transport, repo, NOW_WEEK_TWO), transport


class TestScenario2NoRepeatsWithinFourWeeks:
    async def test_cooked_dish_rejected_then_clean_plan_staged(
        self, repo: HistoryRepo
    ) -> None:
        repeat_meals = [
            meal("Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}),
            meal("Braised beef", protein="beef", stretch={"technique": "braising"}),
            meal("Pork tenderloin", protein="pork"),
        ]
        session, transport = await checked_in_week_two_session(
            repo,
            [
                ScriptedToolCall("get_meal_history", {}),
                ScriptedToolCall("propose_plan", week_two_payload(repeat_meals)),
                ScriptedToolCall(
                    "propose_plan", week_two_payload(clean_week_two_meals())
                ),
                ScriptedText("Fresh plan, nothing repeated!"),
            ],
        )
        outcome = await session.handle_message("3 dinners, 2 lunches")

        history_result = json.loads(transport.tool_calls[0].result)
        assert "chicken chili" in history_result["cooked_dish_names_last_4_weeks"]
        rejected = json.loads(transport.tool_calls[1].result)
        assert rejected["ok"] is False
        assert [e["code"] for e in rejected["errors"]] == ["repeated_dish"]
        assert "chicken chili" in rejected["errors"][0]["message"]

        accepted = json.loads(transport.tool_calls[2].result)
        assert accepted["ok"] is True
        assert outcome.newly_staged_plan is not None
        names = {m.name for m in outcome.newly_staged_plan.meals}
        assert "Chicken chili" not in names

    async def test_cooked_stretch_technique_not_new_again(
        self, repo: HistoryRepo
    ) -> None:
        stale_technique_meals = clean_week_two_meals()
        stale_technique_meals[1]["stretch"] = {"technique": "searing"}
        session, transport = await checked_in_week_two_session(
            repo,
            [
                ScriptedToolCall("get_meal_history", {}),
                ScriptedToolCall(
                    "propose_plan", week_two_payload(stale_technique_meals)
                ),
                ScriptedText("Hmm, let me rework that."),
            ],
        )
        await session.handle_message("3 dinners, 2 lunches")
        rejected = json.loads(transport.tool_calls[1].result)
        assert rejected["ok"] is False
        assert [e["code"] for e in rejected["errors"]] == ["technique_not_new"]


class TestScenario4PastWeekQuery:
    async def test_past_week_answered_from_history(self, repo: HistoryRepo) -> None:
        session, transport = await checked_in_week_two_session(
            repo,
            [
                ScriptedToolCall("get_meal_history", {}),
                ScriptedText(
                    "Last week you cooked chicken chili, seared salmon, and "
                    "turkey stir-fry."
                ),
            ],
        )
        outcome = await session.handle_message("what did I cook last week?")
        history_result = json.loads(transport.tool_calls[0].result)
        (week,) = [w for w in history_result["weeks"] if w["week_id"] == WEEK_ONE]
        statuses = {m["name"]: m["cooked_status"] for m in week["meals"]}
        assert statuses == {
            "Chicken chili": "cooked",
            "Seared salmon": "cooked",
            "Turkey stir-fry": "skipped",
        }
        assert "chicken chili" in outcome.reply_text


class TestScenario5ExplicitRepeatHonored:
    async def test_requested_repeat_is_included_and_counted(
        self, repo: HistoryRepo
    ) -> None:
        repeat_meals = [
            meal(
                "Chicken chili",
                batch={"lunches_covered": 2, "total_portions": 3},
                user_requested_repeat=True,
            ),
            meal("Braised beef", protein="beef", stretch={"technique": "braising"}),
            meal("Pork tenderloin", protein="pork"),
        ]
        session, transport = await checked_in_week_two_session(
            repo,
            [
                ScriptedToolCall("get_meal_history", {}),
                ScriptedToolCall("propose_plan", week_two_payload(repeat_meals)),
                ScriptedText("Chili is back by request!"),
            ],
        )
        outcome = await session.handle_message(
            "3 dinners, 2 lunches — and bring back that chili"
        )
        result = json.loads(transport.tool_calls[1].result)
        assert result["ok"] is True
        plan = outcome.newly_staged_plan
        assert plan is not None
        assert plan.dinner_count == 3
        assert len(plan.meals) == 3, "the repeat counts toward the dinner count"
        assert "Chicken chili" in [m.name for m in plan.meals]
