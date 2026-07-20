"""Integration tests for the spec Edge Cases section (T049) and the
transport error states from contracts/telegram-bot.md (T050).

Counts out of range, zero lunches, vegan protein adaptation, announced
repetition relaxation, post-acceptance serving changes, abandoned sessions,
skipped check-ins, unsatisfiable constraints, web-search fallback, agent
failure recovery, and the /history empty state.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fake_llm import FakeTransport, ScriptedText, ScriptedToolCall

from sous_chef.agent.prompt import SYSTEM_PROMPT
from sous_chef.agent.session import Session
from sous_chef.agent.tools import build_tools
from sous_chef.bot.app import (
    AGENT_FAILURE_TEXT,
    CANCEL_TEXT,
    EMPTY_HISTORY_TEXT,
    BotHandlers,
)
from sous_chef.bot.formatting import render_plan
from sous_chef.services.history_repo import HistoryRepo

CHAT_ID = 4242
WEEK_ID = "2026-W30"
FIXED_NOW = datetime(2026, 7, 22, 12, 0, tzinfo=UTC)


def meal(
    name: str,
    *,
    protein: str = "chicken",
    servings: int = 1,
    batch: dict[str, Any] | None = None,
    stretch: dict[str, Any] | None = None,
    ingredient_quantity: float = 1.0,
    ingredient_price: float = 8.0,
) -> dict[str, Any]:
    return {
        "name": name,
        "primary_protein": protein,
        "prep_minutes": 30,
        "servings": servings,
        "batch": batch,
        "stretch": stretch,
        "source_url": None,
        "user_requested_repeat": False,
        "ingredients": [
            {
                "name": f"{name} base",
                "quantity": ingredient_quantity,
                "unit": "lb",
                "estimated_price_usd": ingredient_price,
            }
        ],
    }


def payload(
    *,
    dinner_count: int = 3,
    lunch_count: int = 2,
    diet_type: str | None = None,
    default_servings: int = 1,
    meals: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if meals is None:
        meals = [
            meal(
                "Chicken chili",
                servings=default_servings,
                batch={
                    "lunches_covered": lunch_count,
                    "total_portions": (lunch_count + 1) * default_servings,
                },
            ),
            meal(
                "Seared salmon",
                protein="salmon",
                servings=default_servings,
                stretch={"technique": "searing"},
            ),
            meal("Turkey stir-fry", protein="turkey", servings=default_servings),
        ]
    return {
        "week_id": WEEK_ID,
        "dinner_count": dinner_count,
        "lunch_count": lunch_count,
        "diet_type": diet_type,
        "default_servings": default_servings,
        "weekly_budget_usd": None,
        "meals": meals,
    }


@pytest.fixture
def repo(tmp_path: Path) -> HistoryRepo:
    return HistoryRepo(tmp_path / "edge.db")


def make_session(
    transport: Any, repo: HistoryRepo, moment: datetime = FIXED_NOW
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


class TestCountsOutOfRange:
    async def test_dinner_count_outside_range_reprompted(
        self, repo: HistoryRepo
    ) -> None:
        five_meals = [
            meal("Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}),
            meal("Seared salmon", stretch={"technique": "searing"}),
            meal("Turkey stir-fry"),
            meal("Pork chops", protein="pork"),
            meal("Beef tacos", protein="beef"),
        ]
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall(
                    "propose_plan", payload(dinner_count=5, meals=five_meals)
                ),
                ScriptedText(
                    "I plan 3-4 dinners a week — open nights absorb the rest. "
                    "How many dinners (3-4) would you like?"
                ),
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("5 dinners and 2 lunches")
        result = json.loads(transport.tool_calls[0].result)
        assert result["ok"] is False
        assert "dinner_count_out_of_range" in [e["code"] for e in result["errors"]]
        assert outcome.newly_staged_plan is None
        assert "3-4" in outcome.reply_text

    async def test_more_than_seven_lunches_rejected(self, repo: HistoryRepo) -> None:
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", payload(lunch_count=8)),
                ScriptedText("I can cover at most 7 lunches — how many (0-7)?"),
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners, 8 lunches")
        result = json.loads(transport.tool_calls[0].result)
        assert result["ok"] is False
        assert [e["code"] for e in result["errors"]] == ["lunch_count_out_of_range"]
        assert outcome.newly_staged_plan is None


class TestZeroLunches:
    async def test_zero_lunch_batch_meal_still_flagged(self, repo: HistoryRepo) -> None:
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", payload(lunch_count=0)),
                ScriptedText(
                    "No lunches this week, so the batch meal covers only its "
                    "dinner night — less meal-prep benefit, still one pot."
                ),
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners, no lunches")
        plan = outcome.newly_staged_plan
        assert plan is not None
        assert plan.batch_meal is not None and plan.batch_meal.batch is not None
        assert plan.batch_meal.batch.lunches_covered == 0
        assert plan.batch_meal.batch.total_portions == 1
        rendered = render_plan(plan)
        assert "🍲 Batch meal" in rendered
        assert "covers 0 lunches" in rendered
        assert "meal-prep benefit" in outcome.reply_text


class TestVeganProteinAdaptation:
    async def test_vegan_plan_adapts_proteins_and_explains(
        self, repo: HistoryRepo
    ) -> None:
        vegan_meals = [
            meal(
                "Lentil chili",
                protein="lentils",
                batch={"lunches_covered": 2, "total_portions": 3},
            ),
            meal(
                "Crispy tofu bowls",
                protein="tofu",
                stretch={"technique": "pressing tofu"},
            ),
            meal("Tempeh stir-fry", protein="tempeh"),
        ]
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall(
                    "propose_plan", payload(diet_type="vegan", meals=vegan_meals)
                ),
                ScriptedText(
                    "All vegan: protein comes from lentils, tofu, and tempeh "
                    "— each dinner still leads with a named protein."
                ),
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners, 2 lunches, vegan please")
        plan = outcome.newly_staged_plan
        assert plan is not None
        assert plan.diet_type == "vegan"
        assert {m.primary_protein for m in plan.meals} == {"lentils", "tofu", "tempeh"}
        assert "protein" in outcome.reply_text

    def test_prompt_never_refuses_a_diet(self) -> None:
        prompt = SYSTEM_PROMPT.casefold()
        assert "never refuse a diet" in prompt


def relaxed_payload() -> dict[str, Any]:
    meals = [
        meal("Chicken chili", batch={"lunches_covered": 2, "total_portions": 3}),
        meal(
            "Braised salmon",
            protein="salmon",
            stretch={"technique": "braising"},
        ),
        meal("Turkey stir-fry", protein="turkey"),
    ]
    return payload(meals=meals)


class TestRelaxedWindowAnnouncement:
    async def test_repeated_rejections_relax_the_window_with_note(
        self, repo: HistoryRepo
    ) -> None:
        # Seed W29 history: everything cooked, so chili keeps colliding.
        seed = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", payload() | {"week_id": "2026-W29"}),
                ScriptedToolCall("accept_plan", {"week_id": "2026-W29"}),
                ScriptedText("Seeded."),
            ]
        )
        seed_session = make_session(
            seed, repo, moment=datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
        )
        await seed_session.handle_message("3 dinners, 2 lunches")
        repo.record_checkin("2026-W29", [], user_skipped=True)

        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("get_meal_history", {}),
                ScriptedToolCall("propose_plan", payload()),
                ScriptedToolCall("propose_plan", payload()),
                ScriptedText(
                    "Everything new kept colliding, so I'm relaxing the "
                    "repetition window, starting with your oldest dishes."
                ),
            ],
            [
                # Relaxation lifts the dish window only — the stretch
                # technique must still be new, so the re-proposal swaps
                # searing for braising.
                ScriptedToolCall("propose_plan", relaxed_payload()),
                ScriptedText("Here's the plan with the relaxed window."),
            ],
        )
        session = make_session(transport, repo)
        first = await session.handle_message("3 dinners, 2 lunches")

        first_rejection = json.loads(transport.tool_calls[1].result)
        assert first_rejection["ok"] is False
        assert "note" not in first_rejection
        second_rejection = json.loads(transport.tool_calls[2].result)
        assert second_rejection["ok"] is False
        assert "relaxed" in second_rejection["note"]
        assert session.state.repetition_relaxed is True
        assert "relaxing the repetition window" in first.reply_text

        outcome = await session.handle_message("ok, repeats are fine")
        relaxed_result = json.loads(transport.tool_calls[3].result)
        assert relaxed_result["ok"] is True
        assert outcome.newly_staged_plan is not None


class TestServingChangeAfterAcceptance:
    async def test_serving_change_recalculates_grocery_and_bill(
        self, repo: HistoryRepo
    ) -> None:
        doubled_meals = [
            meal(
                "Chicken chili",
                servings=2,
                batch={"lunches_covered": 2, "total_portions": 6},
                ingredient_quantity=2.0,
                ingredient_price=16.0,
            ),
            meal(
                "Seared salmon",
                protein="salmon",
                servings=2,
                stretch={"technique": "searing"},
                ingredient_quantity=2.0,
                ingredient_price=16.0,
            ),
            meal(
                "Turkey stir-fry",
                protein="turkey",
                servings=2,
                ingredient_quantity=2.0,
                ingredient_price=16.0,
            ),
        ]
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", payload()),
                ScriptedToolCall("accept_plan", {"week_id": WEEK_ID}),
                ScriptedText("Accepted."),
            ],
            [
                ScriptedToolCall(
                    "propose_plan",
                    payload(default_servings=2, meals=doubled_meals),
                ),
                ScriptedToolCall("accept_plan", {"week_id": WEEK_ID}),
                ScriptedText("Doubled and re-accepted."),
            ],
        )
        session = make_session(transport, repo)
        first = await session.handle_message("3 dinners, 2 lunches — accept it")
        second = await session.handle_message("make everything 2 servings")

        assert first.newly_accepted is not None
        assert second.newly_accepted is not None
        assert (
            second.newly_accepted.grocery.estimated_total_usd
            == first.newly_accepted.grocery.estimated_total_usd * 2
        )
        assert repo.connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 1


class TestAbandonedSession:
    async def test_cancel_discards_staged_draft_and_leaves_no_rows(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [ScriptedToolCall("propose_plan", payload()), ScriptedText("Plan!")]
        )
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: make_session(transport, repo),
        )
        bot = RecordingBot()
        context = SimpleNamespace(bot=bot)
        await handlers.on_text(fake_update("3 dinners, 2 lunches"), context)
        assert handlers.sessions[CHAT_ID].state.staged_draft is not None

        await handlers.on_cancel(fake_update("/cancel"), context)
        assert CHAT_ID not in handlers.sessions
        assert (CANCEL_TEXT, None) in bot.messages
        assert repo.connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0
        assert repo.connection.execute("SELECT COUNT(*) FROM meals").fetchone()[0] == 0


class TestSkippedCheckinDefaultsToCooked:
    async def test_user_skipped_checkin_marks_planned_as_cooked(
        self, repo: HistoryRepo
    ) -> None:
        seed = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", payload() | {"week_id": "2026-W29"}),
                ScriptedToolCall("accept_plan", {"week_id": "2026-W29"}),
                ScriptedText("Seeded."),
            ]
        )
        await make_session(
            seed, repo, moment=datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
        ).handle_message("3 dinners, 2 lunches")

        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("get_meal_history", {}),
                ScriptedToolCall(
                    "record_cooked_checkin",
                    {"week_id": "2026-W29", "user_skipped_checkin": True},
                ),
                ScriptedText("No problem — logged them all as cooked."),
            ]
        )
        session = make_session(transport, repo)
        await session.handle_message("can't remember, skip the check-in")
        result = json.loads(transport.tool_calls[1].result)
        assert result["ok"] is True
        assert sorted(result["recorded"]["cooked"]) == [
            "Chicken chili",
            "Seared salmon",
            "Turkey stir-fry",
        ]
        assert result["recorded"]["skipped"] == []
        statuses = repo.connection.execute(
            "SELECT DISTINCT cooked_status FROM meals WHERE week_id = '2026-W29'"
        ).fetchall()
        assert [row["cooked_status"] for row in statuses] == ["cooked"]


class TestUnsatisfiableConstraints:
    def test_prompt_demands_naming_the_failed_constraint(self) -> None:
        prompt = SYSTEM_PROMPT.casefold()
        assert "which constraint failed" in prompt
        assert "never return an empty result" in prompt

    async def test_constraint_conflict_reply_names_constraint(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted(
            [
                ScriptedText(
                    "I can't fit 4 high-protein dinners in a $15 budget — the "
                    "budget is the constraint that fails. You could raise it "
                    "to about $45, or drop to 3 dinners."
                )
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("4 dinners, $15 budget")
        assert "budget" in outcome.reply_text
        assert outcome.reply_text.strip(), "never an empty reply"


class TestWebSearchFallback:
    def test_prompt_directs_fallback_to_own_knowledge(self) -> None:
        prompt = SYSTEM_PROMPT.casefold()
        assert "fall back to your own knowledge" in prompt
        assert "never fail the session over search" in prompt

    async def test_plan_proposed_without_any_web_search(
        self, repo: HistoryRepo
    ) -> None:
        # Search unavailable: the agent proposes purely from its own
        # knowledge — the session works with zero web_search calls.
        transport = FakeTransport.scripted(
            [
                ScriptedToolCall("propose_plan", payload()),
                ScriptedText("Search was down, so these are from memory."),
            ]
        )
        session = make_session(transport, repo)
        outcome = await session.handle_message("3 dinners, 2 lunches")
        assert outcome.newly_staged_plan is not None
        assert all(m.source_url is None for m in outcome.newly_staged_plan.meals)


class RecordingBot:
    def __init__(self) -> None:
        self.messages: list[tuple[str, str | None]] = []

    async def send_chat_action(self, chat_id: int, action: str) -> None:
        pass

    async def send_message(
        self, chat_id: int, text: str, parse_mode: str | None = None
    ) -> None:
        self.messages.append((text, parse_mode))


def fake_update(text: str) -> Any:
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=CHAT_ID),
        effective_message=SimpleNamespace(text=text),
    )


class FailingTransport:
    """Raises like a timed-out or refused API call."""

    async def run_turn(self, **_kwargs: Any) -> Any:
        raise RuntimeError("simulated API failure")


class TestAgentFailureErrorState:
    async def test_failure_reply_sent_and_session_retained(
        self, repo: HistoryRepo
    ) -> None:
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: make_session(FailingTransport(), repo),
        )
        bot = RecordingBot()
        context = SimpleNamespace(bot=bot)
        await handlers.on_text(fake_update("3 dinners please"), context)

        assert (AGENT_FAILURE_TEXT, None) in bot.messages
        assert CHAT_ID in handlers.sessions, "session kept so the turn can be retried"
        assert repo.connection.execute("SELECT COUNT(*) FROM plans").fetchone()[0] == 0


class TestHistoryEmptyState:
    async def test_history_command_explains_no_past_weeks(
        self, repo: HistoryRepo
    ) -> None:
        transport = FakeTransport.scripted()  # the agent must never be called
        handlers = BotHandlers(
            allowed_chat_id=CHAT_ID,
            session_factory=lambda chat_id: make_session(transport, repo),
        )
        bot = RecordingBot()
        await handlers.on_history(fake_update("/history"), SimpleNamespace(bot=bot))
        assert (EMPTY_HISTORY_TEXT, None) in bot.messages
        assert transport.events == [], "no agent call for the empty state"
